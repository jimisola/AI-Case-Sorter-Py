# CLAUDE.md

Guidance for AI assistants (and humans) working in this repository. It maps the
architecture, the moving parts, and the conventions so a new contributor can be
productive without reverse-engineering the whole tree. **Keep this file current:
when you add a tab, change the data model, or alter a subsystem boundary, update
the relevant section here in the same change.**

---

## 1. What this project is

The **AI Case Sorter** is a cross-platform (Windows + Linux/Ubuntu) desktop
application that drives a physical machine which sorts spent brass cartridge
casings by **headstamp** (the stamp on the base of the case). A camera
photographs each case, an image classifier predicts the headstamp, and a
serial-connected sorting machine drops the case into the correct bin.

It is the **full-parity Python/Tkinter version of the existing Windows-only
WinForms application** and is intended to eventually replace it. Much of the
code deliberately mirrors the WinForms behavior.

The "community" features (model sharing, downloads, feedback loop) authenticate
against a hosted backend at `reloadingrecipes.com` via Azure AD B2C. The app
runs fully without ever signing in — community features are the only auth-gated
surface.

Two ways to classify:
- **AI Config mode** (no local model active): send the cropped image to an
  OpenAI-compatible HTTP server (`/v1/chat/completions`).
- **Local model mode**: run a PyTorch **ConvNeXt** model locally. The model can
  be one the user trained in the Train tab, a pretrained model downloaded from
  the community, or one imported from a ZIP — running locally does **not** require
  the user to have trained it. PyTorch is an **optional** dependency
  (`pip install .[ml]`) installed on demand.

---

## 2. Running, testing, layout

**Entry point:** `main.py` → initializes paths, opens the SQLite DB (migrating
from a legacy `data/config.json` if present), loads `Config`, and launches
`sorter.ui.app.MainWindow`.

**Launch (handles venv + system deps automatically):**
- Linux/macOS: `./start.sh` (`--auto` / `AUTO_INSTALL=1` auto-confirms `sudo`
  package installs for tkinter/libGL/glib/venv)
- Windows: `start.bat`
- Directly: `python main.py`

**Tests:** `pytest` from the repo root (`tests/conftest.py` puts the repo on
`sys.path`). There are ~30 test modules covering the non-UI logic (config, db,
repository, evaluator, model_io, run_controller, serial emulator, auth, etc.).
There is **no CI configured** — run pytest locally before pushing.

**Python:** 3.10+. **Core deps:** pyserial, opencv-python, numpy, Pillow,
requests, msal, platformdirs (+ `pygrabber` on Windows). **Optional ML deps:**
torch, torchvision.

```
AI-Case-Sorter-Py/
├── main.py                  # entry point
├── start.sh / start.bat     # bootstrap launchers (venv + system deps)
├── pyproject.toml           # package metadata; [ml] extra = torch/torchvision
├── requirements.txt
├── sorter/                  # all application code
│   ├── ui/                  # Tkinter UI (tabs + dialogs + theme)
│   └── training/            # out-of-process ConvNeXt trainer
├── tests/                   # pytest suite (logic, not UI)
└── data/                    # created at runtime; gitignored (see §6)
```

---

## 3. Architecture at a glance

The app separates **hardware I/O**, **control logic**, **persistence**, and
**UI** into independent, testable layers, glued by a thread-safe event bus.

```
        ┌───────────────────────── UI (Tkinter, main thread) ─────────────────────────┐
        │  app.MainWindow  ·  ttk.Notebook of tabs  ·  modal dialogs  ·  theme         │
        └───────▲───────────────────────────────────────────────────────────▲─────────┘
                │ subscribes (drained on main thread)        run_worker(fn)  │ spawns
        ┌───────┴─────────── events.EventBus (Queue-backed pub/sub) ─────────┴─────────┐
        │  post() from any worker thread → drain() pumps handlers on the Tk main loop  │
        └───────▲──────────────▲───────────────▲────────────────▲─────────────────────┘
                │              │               │                │
        run_controller   serial_broker     camera          training.manager
        (sort loop,      (UART protocol,   (cv2 grab        (subprocess +
         daemon thread)   reader+ping       thread)          stdout JSON markers)
                │         threads)              │                │
                ▼                               ▼                ▼
        classifier ──► local_inference (torch)  image_proc    train_convnext.py
                  └──► api_client (HTTP)         (Hough crop)  (ConvNeXt, separate proc)

        Persistence:  config.Config ──► repository.*Repo ──► db.Database (SQLite, WAL)
        Filesystem:   paths.* defines data/ layout;  model_io (ZIP import/export)
        Community:    auth.AuthManager (MSAL) ──► community_api.CommunityApi (HTTPS)
                      feedback.FeedbackService (below-threshold image queue)
```

### The event bus (`sorter/events.py`)
A single `EventBus` with a thread-safe `Queue`. Workers call `bus.post(topic,
payload)` from any thread; the Tk main loop calls `bus.drain()` on a 50 ms
`root.after` timer to dispatch queued events to subscribers **on the main
thread**, so handlers can safely touch widgets. Handler exceptions are
swallowed. Topics are slash-namespaced strings: `run/*`, `test/*`, `serial/*`,
`training/*`, `mode/changed`, `feedback/*`, `community/*`. This is the **only**
sanctioned way for worker threads to update the UI.

---

## 4. Module reference (`sorter/`)

### Persistence & configuration
- **`db.py`** — `Database`: owns one `sqlite3.Connection` (WAL, foreign keys on,
  `check_same_thread=False` with an `RLock` serializing multi-statement
  transactions / SAVEPOINTs). Schema is `PRAGMA user_version`-versioned
  (`SCHEMA_VERSION = 3`) with idempotent DDL + `_apply_column_migrations`.
  `ensure_initialized()` creates the DB, runs a one-shot import from legacy
  `data/config.json` (renaming it `.bak`), or seeds a default cartridge+model.
  Tables: `cartridges`, `models`, `headstamp_parents`, `headstamps`, `settings`.
- **`repository.py`** — `CartridgeRepo`, `ModelRepo`, `HeadstampRepo`,
  `HeadstampParentRepo`, `SettingsRepo`. All SQL is **parameterized**. `SettingsRepo`
  is a typed key/value store (JSON-encoded values) and holds `default_model_id`
  (the "active model").
- **`config.py`** — `Config`: in-memory mirror of the `settings` sections (`api`,
  `serial`, `image_proc`, `camera`) plus the canonical `DEFAULTS`. Headstamps are
  **not cached** — they're read fresh from the DB on every access (scoped to the
  active model; AI Config mode stashes them in a settings key). Also the home of
  routing logic: `slot_for_headstamp`, package-mode slot maps, parent
  classifications, auto-select, run options (confidence floor, store-images mode).
- **`models.py`** — dataclasses: `Model`, `Headstamp`, `Cartridge`,
  `TrainingConfig`, `AIModelConfig`, `ImageProcessingConfig`, plus normalizers
  (`normalize_upload_mode`, `SUPPORTED_MODEL_MODES`).
- **`paths.py`** — single source of truth for the on-disk layout (see §6).
  `CASESORTER_DATA_DIR` overrides the data root.

### Active-model concept
"Active model" = `settings.default_model_id`. When **absent**, the app is in
**AI Config mode** (cloud HTTP classification, headstamps in a settings key).
When **set**, that local model is active (Train tab visible, local inference
used, headstamps in the `headstamps` table). Activating a model posts
`mode/changed`, which toggles tab visibility.

### Hardware control
- **`serial_broker.py`** — `SerialBroker`: ASCII command protocol over UART
  (default 9600 8N1). A **reader thread** parses responses and fans them out to
  callback lists (`on_done`/`on_ok`/`on_error`/`on_received`/…); a **ping thread**
  keeps the link alive; a write lock serializes commands. Key commands: `xf:0`
  (feed one), `xf:<slot>` (force feed + sort), bare `<slot>` (sort imaged case),
  `sortto:<slot>` (move arm), `getconfig` (JSON board state), `version`, `stop`,
  `<key>:<value>` (set board param). `try_open()` does a version handshake.
- **`serial_emulator.py`** — `SerialEmulator`: drop-in fake mirroring the broker
  API (port name `"Emulated"`), responding after a timer delay. Enables running
  and testing without hardware.
- **`camera.py`** — `Camera`: `cv2.VideoCapture` with a background **grab thread**
  keeping the latest frame; platform backends (CAP_DSHOW on Windows w/ optional
  pygrabber for friendly names + resolution probing, CAP_V4L2 on Linux, MJPG for
  ≥1080p). `enumerate_devices` / `list_cameras_with_metadata` for the Camera tab.

### The sort loop
- **`run_controller.py`** — `RunController`: the production loop on a daemon
  thread. Per case: capture → `image_proc.crop_headstamp` → optional primer mask
  → `classifier.classify_active` → `_resolve_destination(label, confidence)` →
  `broker.sort_and_move(slot)`. Handles the 5-position wheel pipeline
  (`_last_classified_slot`), the **confidence floor** (below → catch-all slot 0),
  **auto-select trays**, **package/batch mode** (`_package_counts` under a lock),
  optional run-image storage, and feedback capture. Also `cycle_once()` (manual
  feed) and `test_once()` (feed+classify, no sort). Posts `run/*` and `test/*`.

### Classification
- **`classifier.py`** — `classify_active`: routes to **local inference** when the
  active model has a valid `model_path`, else to the **HTTP API**. Passes the
  trained `image_size` through.
- **`local_inference.py`** — lazy-imports torch; picks the device once; caches
  loaded models by `(path, mtime)`; runs all inference through a single-threaded
  executor to keep cuDNN state warm. Detects the checkpoint's classifier layout
  and rebuilds the ConvNeXt head. Loads checkpoints with
  `torch.load(..., weights_only=True)` so a malicious `.pth` cannot execute code
  on load (see `Security.md` #1).
- **`api_client.py`** — stateless HTTP client (`classify`, `get_headstamps`)
  against an OpenAI-compatible server. JPEG-encodes the frame to a base64 data
  URL, renders the `{{headstamps}}` prompt placeholder, parses `choices[0]...`
  and a top-level `confidence` float.
- **`image_proc.py`** — crops the headstamp to a fixed **480×480 BGR** canvas.
  Default strategy: **Hough circles** (`HoughParams`); a dormant **line-scan**
  strategy is ported but UI-hidden. `apply_primer_mask` (none/use/hide),
  `overlay_detection` for preview.

### Training & evaluation
- **`training/manager.py`** — `TrainingManager`: spawns `train_convnext.py` as a
  **subprocess** (clean cancellation, no GIL fights), pumps stdout for
  `[PROGRESS] {json}` markers, and re-emits them as `training/*` events. SIGTERM
  → SIGKILL escalation on cancel. `build_command` builds the argv (list form, no
  shell).
- **`training/train_convnext.py`** — the worker script. Trains
  `convnext_{tiny,small,base,large}` via torchvision pretrained weights; AdamW +
  cosine LR, optional focal loss, label smoothing, stochastic depth, SWA, mixed
  precision. Saves a dict checkpoint: `{model_state_dict, classes, base,
  image_size, ...}` via `torch.save`. Module-level dataset classes so Windows
  `spawn` DataLoader workers can pickle them.
- **`training/dataset.py`** — filename convention helpers. Training images are
  `{label}__{ticks}.jpg` where `ticks` is the **.NET `DateTime.Ticks`** value
  (WinForms interop). `save_training_image`, `feedback_filename`
  (`{label}__{confidence}__{ticks}.jpg`), `parse_label`, `class_counts`.
  ⚠️ Labels are not sanitized before becoming filenames — see `Security.md`.
- **`evaluator.py`** — offline batch evaluation of a model against a labeled
  folder, with folder-label→model-class mapping (auto-suggest via token scoring)
  and `summarize` (per-class accuracy/confidence).
- **`eval_report.py`** — self-contained interactive HTML report (base64 thumbnails
  + embedded results JSON), a verbatim port of the WinForms report.
  ⚠️ Result rows are interpolated into a `<script>` block — see `Security.md`.
- **`gpu_detect.py`** — shells out to `nvidia-smi` (torch not yet installed) to
  detect a compute-capability ≥ 8.0 NVIDIA GPU for the Install-PyTorch dialog.
- **`image_store.py`** — pure pathlib helpers to list/filter/reclassify/delete
  training images by their `{headstamp}__{ticks}` filenames.
- **`model_io.py`** — model **ZIP** import/export compatible with the WinForms
  format (`manifest.json` + `model/<id>.pth` + `images/*`). Accepts both
  snake_case and WinForms PascalCase manifest keys. Import **rejects `..`
  traversal entries** and only uses entry basenames; export strips paths/secrets.

### Community / cloud
- **`auth.py`** — `AuthManager`: MSAL `PublicClientApplication` against Azure AD
  B2C (hardcoded tenant/client/authority/redirect, mirroring WinForms). Token
  cache is a single file, chmod 0600 on POSIX. Decodes ID-token claims **for
  display only** (signature not verified — never used for authz). Auth is
  optional; the only gated surface is the Community tab.
- **`community_api.py`** — `CommunityApi`: HTTPS client for
  `reloadingrecipes.com/api` (cartridges, model search, download via Azure-blob
  SAS URL, feedback-image upload, model share). Bearer token pulled fresh from
  `AuthManager` per call. Downloads/uploads stream with atomic writes.
- **`feedback.py`** — `FeedbackService`: the community **feedback loop**. When a
  community model with the loop enabled produces a below-floor prediction (floor
  clamped to ≥ 50), the cropped image is staged to
  `data/models/<id>/feedback_images/`. **The folder is the queue** (no DB mirror);
  `upload_pending` drains it via `CommunityApi`, deleting on success or drop on
  failure. Debug tracing to stderr is **off by default** — enable with
  `CASESORTER_FEEDBACK_DEBUG=1`.

---

## 5. The UI (`sorter/ui/`)

`MainWindow` (`app.py`) is the shell: gradient title bar, a `ttk.Notebook` of
tabs (each wrapped in a `ScrollableFrame` for small displays), and a status bar
with connection indicators + sign-in. It owns the `EventBus`, `SerialBroker`,
`Camera`, `RunController`, and `AuthManager`, auto-connects serial/camera on
startup, and runs the bus drain loop. `run_worker(fn, on_done, on_error)` is the
standard helper for offloading blocking work to a thread and marshaling the
result back through the bus.

**Tab visibility is mode-driven:** Train shows for a local active model; AI
Config shows in AI Config mode; Community is mounted only while signed in. The
`mode/changed` event re-evaluates this.

### Tabs (`tab_*.py`)
| Tab | File | Purpose |
|-----|------|---------|
| **Run** | `tab_run.py` | Production sorting. Flow-grid of slot cards + per-slot headstamp checkboxes with live counts; Start/Stop/Manual-feed; package-mode counters. The largest UI module. |
| **Models** | `tab_models.py` | Model library: browse/filter, create, edit, **activate**, import/export, delete. Synthetic "Use AI Config" row. |
| **Train** | `tab_train.py` | Feed→capture→classify→label→save loop; "Sort While Training"; launches training (Install-PyTorch dialog if needed → progress dialog). |
| **AI Config** | `tab_ai.py` | HTTP server config (endpoint/key/model/prompt/encoding), headstamp manager, single-shot test. Visible only in AI Config mode. |
| **Camera** | `tab_camera.py` | Device + resolution detection and live preview. |
| **Serial** | `tab_serial.py` | Connection, 14 board init settings, sort-arm test, airdrop config, raw serial monitor. |
| **Image Proc** | `tab_imageproc.py` | Tune Hough params + primer mask + LED brightness against a captured frame (before/after preview). |
| **Community** | `tab_community.py` | Browse/search/download community models; share entry point. Auth-gated. |

### Dialogs (`dialog_*.py`)
`dialog_training_progress` (live training console), `dialog_training_config`
(hyperparameters), `dialog_model_editor` (create/edit model + feedback-loop
opt-in), `dialog_install_torch` (pip-installs torch/torchvision into the venv),
`dialog_login` (MSAL interactive sign-in), `dialog_model_evaluator` (run eval +
HTML report + history), `dialog_model_images` + `dialog_image_preview` (training
image browser/reclassify/delete), `dialog_share_model` (publish to community).

### Shared UI infrastructure
- **`theme.py`** — `PALETTE` (dark slate theme), `apply_theme(root)` (fonts +
  ttk styles, single source of truth), `paint_gradient`.
- **`widgets.py`** — `ScrollableFrame`, `ImagePanel` (shows BGR numpy frames),
  `NumericField`, labeled-entry/button-row helpers.
- **`monitor.py`** — detachable history window: ring buffer of recent
  classifications with a color "snake" trailing the latest. Subscribes `run/history`.
- **`sysutil.py`** — `open_path` (os.startfile / open / xdg-open).

---

## 6. Data & on-disk layout

Everything the app writes lives under `data/` next to `main.py` (override with
`CASESORTER_DATA_DIR`). Delete the folder, delete all state. **`data/` is
gitignored** and must never be committed.

```
data/
├── config/
│   ├── casesorter.db      # SQLite (all settings, models, headstamps)
│   └── msal_cache.bin     # MSAL token cache (chmod 0600 on POSIX)
└── models/
    └── <model_id>/
        ├── images/          # raw training images   {label}__{ticks}.jpg
        ├── run_images/      # opt-in run captures
        ├── feedback_images/ # below-threshold feedback queue (folder == queue)
        ├── reports/         # evaluator HTML reports
        └── trainedmodel/    # <model_id>.pth checkpoint
```

**Filename convention** (WinForms-compatible): training images are
`{label}__{ticks}.jpg`; feedback images are `{label}__{confidence}__{ticks}.jpg`,
where `ticks` is the .NET `DateTime.Ticks` value.

---

## 7. Conventions & gotchas

- **Threading rule:** never touch Tk widgets off the main thread. Do blocking
  work in `run_worker`/daemon threads and `bus.post(...)`; the drain loop
  delivers handlers on the main thread.
- **WinForms interop is intentional.** Many odd choices (PascalCase manifest
  keys, .NET ticks filenames, ConvNeXt-mode integer mapping, the exact serial
  command strings, the verbatim HTML report) exist so this app round-trips
  with the legacy WinForms app. Comments cite the C# source — preserve compatibility when
  editing these.
- **PyTorch is optional and lazily imported.** Guard any torch use; surface a
  friendly "install PyTorch" path rather than letting an `ImportError` escape.
  Don't add torch to `requirements.txt` (it's the `[ml]` extra).
- **DB access is shared across threads** via one connection + RLock. Wrap
  multi-statement work in `db.transaction()` (reentrant via SAVEPOINT).
- **Headstamps are read fresh, not cached** — don't reintroduce a cached
  snapshot (it previously caused silent data loss).
- **Cloud features depend on the hosted `reloadingrecipes.com` backend** and a
  specific Azure B2C tenant, both hardcoded. The backend is a separate service
  (not in this repo); a fork cannot run community features against its own infra
  without editing `auth.py` / `community_api.py`.
- **No CI yet.** Run `pytest` before pushing; UI is not covered by tests.
- See **`Security.md`** for the security review and **`OPEN_SOURCE_READINESS.md`**
  for the open-source readiness assessment.
