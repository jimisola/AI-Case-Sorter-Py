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
├── main.py                  # entry point (+ `--apply-update` pre-launch hook)
├── start.sh / start.bat     # bootstrap launchers (venv + system deps + update)
├── pyproject.toml           # package metadata; [ml] extra = torch/torchvision
├── requirements.txt
├── sorter/                  # all application code
│   ├── ui/                  # Tkinter UI (tabs + dialogs + theme)
│   └── training/            # out-of-process ConvNeXt trainer
├── installer/               # Windows bootstrapper (see §7)
└── tests/                   # pytest suite
```

The data root lives **outside** the repo by default — see §6.

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
  (`SCHEMA_VERSION = 4`) with idempotent DDL + `_apply_column_migrations`.
  `ensure_initialized()` creates the DB, runs a one-shot import from legacy
  `data/config.json` (renaming it `.bak`), or seeds a default cartridge+model.
  Tables: `cartridges`, `models`, `headstamp_parents`, `headstamps`,
  `slot_templates`, `settings`.
- **`repository.py`** — `CartridgeRepo`, `ModelRepo`, `HeadstampRepo`,
  `HeadstampParentRepo`, `SlotTemplateRepo`, `SettingsRepo`. All SQL is
  **parameterized**. `SettingsRepo` is a typed key/value store (JSON-encoded
  values) and holds `default_model_id` (the "active model").
- **`config.py`** — `Config`: in-memory mirror of the `settings` sections (`api`,
  `serial`, `image_proc`, `camera`) plus the canonical `DEFAULTS`. Headstamps are
  **not cached** — they're read fresh from the DB on every access (scoped to the
  active model; AI Config mode stashes them in a settings key). Also the home of
  routing logic: `slot_for_headstamp`, package-mode slot maps, parent
  classifications, auto-select, run options (confidence floor, store-images mode),
  and the sorting-template API (see below).
- **`models.py`** — dataclasses: `Model`, `Headstamp`, `Cartridge`, `SlotTemplate`,
  `TrainingConfig`, `AIModelConfig`, `ImageProcessingConfig`, plus normalizers
  (`normalize_upload_mode`, `SUPPORTED_MODEL_MODES`, `SLOT_TEMPLATE_MODES`).
- **`paths.py`** — single source of truth for the on-disk layout (see §6) and
  the legacy-data migration. `CASESORTER_DATA_DIR` overrides the data root.
  **Stdlib-only and import-light on purpose:** the pre-launch update step
  imports it before the venv has any third-party packages.
- **`appenv.py`** — developer overrides for the community backend, read from the
  environment with an optional `.env` (real env vars always win; see
  `.env.example`). `api_base()` applies `CASESORTER_API_BASE` over the
  production default; `tls_verify()` returns what to pass `requests` as
  `verify=` — a `CASESORTER_API_CA_BUNDLE` path, or `False` when
  `CASESORTER_API_INSECURE=1` **and** the base URL is loopback (it is ignored,
  with a warning, for any other host). `main.py` calls `load_dotenv()` at
  startup; `CommunityApi` resolves both at construction, not import.

### Active-model concept
"Active model" = `settings.default_model_id`. When **absent**, the app is in
**AI Config mode** (cloud HTTP classification, headstamps in a settings key).
When **set**, that local model is active (Train tab visible, local inference
used, headstamps in the `headstamps` table). Activating a model posts
`mode/changed`, which toggles tab visibility.

### Sorting templates
A **sorting template** is a named snapshot of the Run tab's slot assignments, so
one model can carry several bin layouts ("Range brass", "Match prep") and switch
between them from the Run tab's template dropdown.

- **Scope:** per model (`model_id NULL` = AI Config mode) **and** per run mode.
  Standard and package mode keep separate lists — package assignments are
  many-to-many (one headstamp in several slots), so a layout from one mode is
  meaningless in the other. `config.slot_template_mode()` picks the list.
- **Storage:** rows in `slot_templates`; `assignments_json` is name-keyed
  (`{"headstamps": {name: slot}, "parents": {name: slot}}`, or
  `{"slots": {slot: [names]}}` for package mode) so a template survives a
  headstamp being deleted and re-added. Unknown names are ignored on apply.
- **The live assignments stay authoritative.** A run still reads
  `headstamps.slot` / `headstamp_parents.slot` / the package slot map — templates
  never sit in the hot path. The *active* template (settings key
  `active_slot_template:<model id|ai>:<mode>`) is kept in lock-step with them by
  `Config.sync_active_slot_template()`, called from every slot mutation, so
  there is no explicit "save template" step. Switching is therefore a straight
  save-current / load-next swap (`activate_slot_template`), and applying a
  template **clears** any slot it doesn't mention.
- **Seeding/upgrade:** the first read of a scope with no rows creates "Default"
  holding whatever is currently assigned, so existing installs keep their layout.
  The last template in a scope can't be deleted.

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
  trained `image_size` through. `active_local_model` / `uses_local_inference`
  expose that routing decision alone, so the UI can ask "does this action need
  PyTorch?" before starting a run — keep them in lock-step with
  `classify_active` or the install gate (§5) drifts from reality.
- **`local_inference.py`** — lazy-imports torch; picks the device once; caches
  loaded models by `(path, mtime)`; runs all inference through a single-threaded
  executor to keep cuDNN state warm. Detects the checkpoint's classifier layout
  and rebuilds the ConvNeXt head. Loads checkpoints with
  `torch.load(..., weights_only=True)` so a malicious `.pth` (community download
  or imported ZIP) cannot execute code on load. Two presence checks, and the
  difference matters: `is_installed()` is a `find_spec` probe (free, safe on the
  UI thread) and is what the install gate uses; `is_available()` actually
  imports torch and on first call runs the device probe + benchmark dump, which
  would freeze the UI if called from a button handler.
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
  (for interop with the legacy Windows app). `save_training_image`,
  `feedback_filename` (`{label}__{confidence}__{ticks}.jpg`), `parse_label`,
  `class_counts`. Labels are run through `safe_label` before becoming filenames
  (classification labels can come from an untrusted classification server).
- **`evaluator.py`** — offline batch evaluation of a model against a labeled
  folder, with folder-label→model-class mapping (auto-suggest via token scoring)
  and `summarize` (per-class accuracy/confidence).
- **`eval_report.py`** — self-contained interactive HTML report (base64 thumbnails
  + embedded results JSON), a verbatim port of the legacy app's report. ⚠️ Result
  rows are interpolated into a `<script>` block, so the report is only safe to
  open for locally-evaluated, trusted image folders.
- **`gpu_detect.py`** — shells out to `nvidia-smi` (torch not yet installed) to
  detect a compute-capability ≥ 8.0 NVIDIA GPU for the Install-PyTorch dialog.
- **`image_store.py`** — pure pathlib helpers to list/filter/reclassify/delete
  training images by their `{headstamp}__{ticks}` filenames.
- **`models.py` ownership helpers** — `is_foreign_model` / `is_trainable` /
  `FOREIGN_MODEL_TYPES`: the single definition of "this model belongs to
  someone else" (see §5, *Model ownership*).
- **`model_io.py`** — model **ZIP** import/export compatible with the WinForms
  format (`manifest.json` + `model/<id>.pth` + `images/*`). Accepts both
  snake_case and WinForms PascalCase manifest keys. Import **rejects `..`
  traversal entries** and only uses entry basenames; export strips paths/secrets.
  An archive whose `community_model_uid` is already installed is an **update**:
  `import_model` refreshes that row in place (same model id → same directories,
  headstamp slots, and sorting templates) instead of creating a duplicate, and
  keeps the local name / feedback-loop opt-in / AI config. `find_update_target`
  tells a caller which path an archive will take; `update_existing=False`
  forces a separate copy. `community_download=True` marks the install as the
  publisher's, and an update never downgrades that (§5, *Model ownership*).

### Self-update (see §7 for the full flow)
- **`updater.py`** — GitHub Releases check, version comparison, and download →
  verify → stage. Needs `requests`. Never writes to the app folder.
- **`apply_update.py`** — the pre-launch half: copies a staged tree over the app
  folder, with backup/rollback. **Stdlib-only** — it runs before `pip install`.

### Community / cloud
- **`auth.py`** — `AuthManager`: MSAL `PublicClientApplication` against Azure AD
  B2C (hardcoded tenant/client/authority/redirect, mirroring WinForms). Token
  cache is a single file, chmod 0600 on POSIX. Decodes ID-token claims **for
  display only** (signature not verified — never used for authz). Auth is
  optional; the only gated surface is the Community tab.
- **`community_api.py`** — `CommunityApi`: HTTPS client for
  `reloadingrecipes.com/api` (cartridges, model search, download via Azure-blob
  SAS URL, feedback-image upload, wish-list fetch, model share). Bearer token
  pulled fresh from `AuthManager` per call. Downloads/uploads stream with atomic
  writes. Base URL and TLS trust come from `appenv` (see above); `verify` is
  passed **per request**, never set on the session — `REQUESTS_CA_BUNDLE` /
  `CURL_CA_BUNDLE` in the environment outrank `session.verify`, so a
  session-level setting is silently ignored on machines that set them.
- **`feedback.py`** — `FeedbackService`: the community **feedback loop**. When a
  community model with the loop enabled produces a below-floor prediction (floor
  clamped to ≥ 50), the cropped image is staged to
  `data/models/<id>/feedback_images/`. **The folder is the queue** (no DB mirror);
  `upload_pending` drains it via `CommunityApi`, deleting on success or drop on
  failure. Debug tracing to stderr is **off by default** — enable with
  `CASESORTER_FEEDBACK_DEBUG=1`.
  Also owns the **wish list** (model balancing): `GET /Models/FetchWishList`
  returns the classifications a model is short of images for. The Run tab fetches
  it on a worker thread at Start (gated on `is_feedback_model`, so an opted-out
  user's auth path is untouched) and clears it at Stop; `should_capture` then
  captures on *below floor **or** wanted label*. Wish-list capture applies to
  continuous runs only (not Manual Feed), is capped at
  `MAX_WISH_LIST_CAPTURES_PER_LABEL` (40) per classification per run, and **fails
  open** — any error or non-200 installs an empty list, i.e. confidence-only
  behavior. No UI surface.

---

## 5. The UI (`sorter/ui/`)

`MainWindow` (`app.py`) is the shell: gradient title bar (with the theme picker
parked at its right edge), a `ttk.Notebook` of tabs (each wrapped in a
`ScrollableFrame` for small displays, and hosted on a backdrop canvas that owns
the margin around it), and a status bar with connection indicators + sign-in. It owns the `EventBus`, `SerialBroker`,
`Camera`, `RunController`, and `AuthManager`, auto-connects serial/camera on
startup, and runs the bus drain loop. `run_worker(fn, on_done, on_error)` is the
standard helper for offloading blocking work to a thread and marshaling the
result back through the bus.

**Tab visibility is mode-driven:** Train shows for a local active model **that
this user owns** (`models.is_trainable` — see *Model ownership* below); AI
Config shows in AI Config mode; Community is mounted only while signed in. The
`mode/changed` event re-evaluates this.

### Model ownership
A model installed from the **Community tab** is stamped `model_type =
"CommunityManaged"` by `import_model(..., community_download=True)`, and
`models.is_trainable()` is False for it: the local checkpoint is the
publisher's, retraining forks it from the version they keep updating, and the
archive usually ships without the images it was built from. `ReadOnly` (the
legacy app's marker) is treated the same. `_merge_onto_installed` never lets
an update downgrade ownership.

**`community_model_uid` is not an ownership signal** — sharing your own model
stamps a UID onto your local copy, so a UID means "exists in the community",
not "isn't yours". Ownership is decided by *how the model reached this
machine*, which is why the flag is a parameter of `import_model` rather than
something read out of the manifest (a publisher's own copy is `Standard`, and
that's what they export). A plain ZIP import stays owned — it's just as likely
to be a user restoring their own model onto a new machine.

### The PyTorch install gate
PyTorch is the optional `[ml]` extra, so a fresh install has none. **The rule:
torch is installed the first time something actually needs it, and never
before** — an AI Config user must never be prompted. `ui/torch_gate.py` is the
single entry point; it opens `dialog_install_torch` and re-enters the caller on
success:

```python
if not ensure_torch(self, self._start, reason="Sorting needs PyTorch"):
    return
```

Gated: Run tab Start + Manual feed (only when `classifier.uses_local_inference`
is True), the evaluator, and training. The Train tab's Feed *offers* rather
than gates — capturing and labelling images is exactly the workflow that
doesn't need torch, so declining costs only the predicted-label convenience and
is remembered for the session. Call it on the **main thread only** (it opens a
modal), and never gate on `is_available()`.

### Tabs (`tab_*.py`)
| Tab | File | Purpose |
|-----|------|---------|
| **Run** | `tab_run.py` | Production sorting. Sorting-template bar; flow-grid of slot cards + per-slot headstamp checkboxes with live counts; Start/Stop/Manual-feed; package-mode counters. The largest UI module. |
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
image browser/reclassify/delete), `dialog_share_model` (publish to community),
`dialog_slot_template` (new / rename / delete a sorting template),
`dialog_theme_editor` (build a theme from the active one: a color picker per
palette role, a canvas preview of a miniature app, and JSON export/import —
reached from the gear beside the title-bar theme picker; "Save & apply"
writes back to a saved theme, rename included, and "Create new…" always makes
a separate one, so a built-in is never the thing being written to),
`dialog_update` (release notes → download progress → "Restart to update"; §7).

### Shared UI infrastructure
- **`theme.py`** — `THEMES`, the live `PALETTE`, `apply_theme(root, theme=…)`
  (fonts + ttk styles, single source of truth), `retheme_widgets`,
  `paint_gradient`. **Every color in the app comes from here.**
  - **Themes.** `THEMES` maps a display name to a full palette; the user picks
    one from the dropdown in the title bar and it's stored in the `ui.theme`
    setting (`theme.SETTING_THEME`). Ships with Dark (the original), Light,
    Sepia, Midnight Blue, Gothic, and Comic Book. **The role of each key is
    fixed; only its color changes per theme** — a new theme is a copy of
    `_DARK` with new values, and it must define exactly the same keys.
    `success` mirrors `action` and `error` mirrors `danger`, so a theme with
    no green (Comic Book, where blue is "go") has a blue "connected"
    indicator, not a green one.
  - **Halftone screens.** `HALFTONE_INK` names the themes that print a
    ben-day dot field, and the ink to print it in; `paint_halftone` prints
    one over any box of a canvas, fading in from whichever edge you name.
    Only canvases can carry it — ttk widgets always fill their own
    background, so nothing shows through them. Two places screen themselves,
    both app chrome: the title bar (`app._repaint_header`) and the margin
    around the notebook (`app._layout_page` — the notebook rides on a
    backdrop canvas for exactly this reason). Keep it to the chrome: a screen
    behind the working area of a tab is noise, not decoration.
  - **Ink outlines.** `INK_OUTLINE` names the themes that draw comic-book
    borders and how many pixels wide; everything else stays flat and
    borderless. `apply_theme` reads it for panels, cards, buttons and fields.
    A card's outline belongs to the card, not to the layout rows inside it —
    those use `row_style(card_style)` (`Card.TFrame` → `CardRow.TFrame`),
    which shares the fill but never the border. Cards that restyle their
    children on hover/selection must map through `row_style` too.
  - **Switching is live**, so it must stay that way: `apply_theme` reloads the
    ttk styles (which every ttk widget follows on its own) and
    `retheme_widgets` walks the widget tree translating the colors baked into
    classic Tk widgets (`tk.Label`, `tk.Canvas`, `tk.Text`) at construction.
    That translation is by color value, which is why no two roles inside one
    theme may share a color — except `success`/`error`, which must equal
    `action`/`danger` (`tests/test_theme.py` enforces both rules).
  - **`PALETTE` is mutated in place** on a switch. Read it at call time
    (`PALETTE["bg_card"]`); never copy a color into a module-level constant.
  - **User-made themes.** `BUILTIN_THEMES` is what ships; `THEMES` is the live
    registry — built-ins plus whatever the theme editor has saved.
    `register_custom_theme` adds one (and its halftone/outline options),
    `rename_custom_theme` moves one (a rename is not copy-and-delete — the
    theme keeps its place and options), `custom_themes_payload` is what the
    app persists to the `ui.custom_themes` setting, and `load_custom_themes`
    re-registers them at startup, before the saved theme name is resolved.
    Names are capped at `MAX_THEME_NAME` because the picker is sized to the
    longest of them. From then on a user
    palette is an ordinary entry in `THEMES` — nothing downstream knows the
    difference. `normalize_palette` is the gate: it fills gaps from a base
    theme, drops unknown keys and non-colors, and forces `success`/`error`
    back onto `action`/`danger`, so neither a hand-edited settings row nor an
    imported file can produce a broken palette..
  - **Hue is meaning.** Dark keeps its chrome (window, panels, cards, inputs,
    borders, text, focus/selection tints) **neutral grayscale**, reserving hue
    for action buttons (`action*` green = primary/go, `update*` blue = refresh
    something installed, `danger*` red = stop/destructive) and status text.
    The tinted themes keep the same discipline internally: their surfaces are
    one low-saturation family so the action buttons stay the most saturated
    thing on screen. Don't add a saturated surface to any theme.
- **`widgets.py`** — `ScrollableFrame` (pass `viewport=(w, h)` to fix how much
  is visible and let the rest scroll), `ImagePanel` (shows BGR numpy frames),
  `NumericField`, labeled-entry/button-row helpers.
- **`monitor.py`** — detachable history window: ring buffer of recent
  classifications with a color "snake" trailing the latest. Subscribes `run/history`.
- **`torch_gate.py`** — `ensure_torch(parent, proceed, reason=…)`: the only
  sanctioned way to front a local-model action with the PyTorch install dialog.
  See *The PyTorch install gate* above.
- **`sysutil.py`** — `open_path` (os.startfile / open / xdg-open).

---

## 6. Data & on-disk layout

Everything the app writes lives under a single **data root**, resolved once by
`paths.app_data_dir()`:

1. `CASESORTER_DATA_DIR` — explicit override, wins over everything.
2. A `portable.txt` marker next to `main.py` → `<app>/data` (USB-stick installs).
3. Otherwise the per-user OS location: `%LOCALAPPDATA%\CaseSorter` on Windows,
   `$XDG_DATA_HOME/CaseSorter` (default `~/.local/share/CaseSorter`) elsewhere.

**The data root is outside the app folder by default, and that is load-bearing:**
the in-app updater replaces the app folder wholesale (§7). Keeping user data out
of it makes the updater safe by construction rather than by maintaining an
exclusion list. `paths.migrate_legacy_data_dir()` moves a pre-0.2 `<app>/data`
up on first run, so upgrades are invisible. `<app>/data` is still **gitignored**
and must never be committed.

```
<data root>/
├── config/
│   ├── casesorter.db      # SQLite (all settings, models, headstamps)
│   └── msal_cache.bin     # MSAL token cache (chmod 0600 on POSIX)
├── models/
│   └── <model_id>/
│       ├── images/          # raw training images   {label}__{ticks}.jpg
│       ├── run_images/      # opt-in run captures
│       ├── feedback_images/ # below-threshold feedback queue (folder == queue)
│       ├── reports/         # evaluator HTML reports
│       └── trainedmodel/    # <model_id>.pth checkpoint
└── updates/               # staged app updates (§7)
    ├── pending/             # extracted tree awaiting the next launch
    ├── pending.json         # its metadata — a SIBLING, never inside pending/
    ├── backup/              # previous version, kept for rollback
    └── last_applied.json
```

**Filename convention** (WinForms-compatible): training images are
`{label}__{ticks}.jpg`; feedback images are `{label}__{confidence}__{ticks}.jpg`,
where `ticks` is the .NET `DateTime.Ticks` value.

---

## 7. Updates & Windows install

Non-developers get the app without git, and keep it current from inside the app.
There is no git dependency anywhere in this path: a release ZIP over HTTPS has
the same trust anchor as `git pull` over HTTPS, and the source tree is ~1 MB, so
delta transfer buys nothing.

**Version:** `sorter/__init__.py.__version__` is the single source.
`pyproject.toml` reads it via `[tool.setuptools.dynamic]`, and the updater
compares it against the latest release tag. **Bump it in the same commit you tag
a release** — otherwise the updater re-offers a release users already have.

**The flow is stage now, apply at next launch:**

```
updater.check_for_update()   GET /releases/latest, compare tags   [needs requests]
        ↓
updater.stage_update()       download → verify → <data>/updates/pending/
        ↓                    (the app folder is NOT touched)
     [restart]
        ↓
main.py --apply-update       run by start.bat/start.sh BEFORE pip  [stdlib ONLY]
        ↓
sorter.apply_update          backup → copy over app dir → prune → clear pending
```

- **`updater.py`** — check/download/stage. Traversal-safe extraction (same
  rejections as `model_io`), strips GitHub's `<repo>-<tag>/` wrapper, requires
  `main.py` + `sorter/__init__.py` to be present before trusting an archive, and
  caps the archive size. Staging is atomic: `pending/` only ever exists complete.
- **`apply_update.py`** — **must stay stdlib-only.** It runs against a venv that
  may hold nothing but pip; importing `requests` here would break the very launch
  it exists to fix. Backs up everything it will overwrite, rolls back on failure,
  and **always exits 0** so a broken updater can never stop the app starting.
  Pruning stale files is confined to `sorter/`; `PROTECTED_TOP_LEVEL` (`.git`,
  `.venv`, `data`, `.env`, `.installed`, `portable.txt`) is never touched.
- **Why a pre-launch step at all:** on Windows the venv's `.pyd`/`.dll` files
  (opencv, numpy) are locked while the app runs, so in-place replacement is
  unreliable. Applying before Python loads anything sidesteps locking — and puts
  a new `requirements.txt` in place *before* the launcher's hash check, so
  dependency changes install on the same restart.
- **UI** — `dialog_update.py` (notes → progress → "Restart to update") reached
  from a status-bar button in `app.py` that appears only when there's something
  to do. A silent check runs 2.5 s after startup; opt out via the dialog's
  checkbox (`updates.check_on_startup`) or `CASESORTER_UPDATE_DISABLED=1`.
- **`installer/`** — `install-windows.ps1` (+ `.bat` wrapper) provisions Python
  via winget or a silent python.org install, lays the app down in
  `%LOCALAPPDATA%\Programs\CaseSorter`, and hands off to `start.bat`. Per-user,
  no admin. See `installer/README.md`.

---

## 8. Conventions & gotchas

- **Threading rule:** never touch Tk widgets off the main thread. Do blocking
  work in `run_worker`/daemon threads and `bus.post(...)`; the drain loop
  delivers handlers on the main thread. **`widget.after()` is not an escape
  hatch** — it registers a Tcl command and is itself unsafe off the main
  thread. A worker must hand results to a `Queue` (the bus, or a dialog-local
  one as in `dialog_update.py`) that a main-thread poller drains.
  `dialog_install_torch.py` predates this note and still calls `after()` from
  its pip-pump thread; don't copy that pattern.
- **Legacy-app interop is intentional.** Many odd choices (PascalCase manifest
  keys, .NET ticks filenames, ConvNeXt-mode integer mapping, the exact serial
  command strings, the verbatim HTML report) exist so this app round-trips with
  the legacy Windows app — preserve that compatibility when editing these.
- **PyTorch is optional and lazily imported.** Guard any torch use; surface a
  friendly "install PyTorch" path rather than letting an `ImportError` escape.
  Don't add torch to `requirements.txt` (it's the `[ml]` extra). Any **new**
  entry point that runs a model locally must go through
  `ui/torch_gate.ensure_torch` (§5) — a bare `LocalInferenceError` reaching the
  user is the bug that gate exists to prevent.
- **DB access is shared across threads** via one connection + RLock. Wrap
  multi-statement work in `db.transaction()` (reentrant via SAVEPOINT).
- **Headstamps are read fresh, not cached** — don't reintroduce a cached
  snapshot (it previously caused silent data loss).
- **Cloud features depend on the hosted `reloadingrecipes.com` backend** and a
  specific Azure B2C tenant. The API base URL and its TLS trust are
  environment-overridable (`appenv`, `.env.example`) so you can run against a
  local copy of the backend; the **Azure B2C tenant/client/scopes in `auth.py`
  are still hardcoded**, so a fork pointing at its own identity provider has to
  edit that file. The backend itself is a separate service, not in this repo.
- **Releases drive the updater.** Bump `sorter/__init__.py.__version__` in the
  same commit you tag a release, and keep the tag and that value in step.
  `/releases/latest` excludes pre-releases, so tagging an rc won't reach
  stable users.
- **The distribution path assumes a public repo.** The installer and updater
  both fetch anonymously over HTTPS; against a private repo every request
  404s and there is no in-band way to tell that apart from "no releases yet"
  (the API returns 404 for both). If the repo must stay private, distribution
  has to move off GitHub — see `installer/README.md`.
- **No CI yet.** Run `pytest` before pushing. Most UI modules need a display —
  `xvfb-run -a python -m pytest` covers them on a headless box; without
  tkinter installed those modules skip rather than fail.
- See **`OPEN_SOURCE_READINESS.md`** for the open-source readiness assessment and
  **`CONTRIBUTING.md`** for how to set up and contribute.
