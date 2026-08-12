# UI modernization — research & decisions

Working document tracking the investigation into replacing or refreshing the
Tkinter UI. Audience: Seth + contributors. Status: **research — no decision
made yet.**

## Problem

The current Tkinter/ttk UI looks dated and has structural ceilings we can't
theme our way out of:

- Blurry/limited fractional DPI scaling on Windows.
- Dated widget rendering, especially on Linux.
- Headless testing requires Xvfb (`xvfb-run -a pytest`); without a display the
  UI test modules skip.
- No animation/layout niceties; a lot of hand-rolled infrastructure
  (`ScrollableFrame`, `retheme_widgets`, gradient/halftone painting) exists to
  compensate for the toolkit.

## Requirements

1. Modern, UX-friendly look.
2. Windows + Linux + macOS.
3. **No dependencies outside PyPI** — no system packages, no bundled
   non-Python runtimes.
4. Headless-testable, ideally without Xvfb.

**Port principle: function parity, not UI parity.** The end state must cover
(more or less) everything the Tk UI does — sorting, models, training, AI
config, camera/serial/image-proc setup, community, updates — but the Qt UI is
free (and expected) to redesign the UX rather than clone the current screens
one-for-one. Concretely: parity is tracked per *capability*, not per
tab/dialog; the Tk UI is the behavioral reference (what must be possible),
not the layout reference (how it looks). Note the app already deviates from
the WinForms original in UI while keeping its behavior — this is the same
move again.

## What's at stake (sizing)

`src/sorter/ui/` is ~13,500 lines across 24 modules (largest: `tab_run.py`
1751, `theme.py` 1500, `tab_models.py` 1246, `app.py` 1082), plus ~4,000 lines
of UI tests. A toolkit swap is a full rewrite of that layer.

Mitigating factor: the non-UI layers (`hardware/`, `control/`, `data/`, `ml/`,
`community/`, `update/`) talk to the UI only through the event bus, so the
seam for a swap already exists.

## Options evaluated

### 1. PySide6 (Qt for Python) — rewrite candidate

- **Pros:** Only option meeting all four requirements. Qt is bundled inside
  the PyPI wheel (no system Qt) on all three OSes. Modern, DPI-aware widgets;
  full styling via QSS so the theme system ports. Headless testing is
  first-class: `QT_QPA_PLATFORM=offscreen` runs real widget tests with no
  display, and `pytest-qt` is mature. Signals/slots are thread-safe by design
  and could replace the hand-rolled `EventBus` + 50 ms drain loop. `QImage`
  renders BGR numpy camera frames directly.
- **Cons:** Full rewrite of `ui/` and its tests. Heavy wheels — measured in
  the spike: the `PySide6` meta-package is 256 MB download / 648 MB on disk
  (it drags in QtWebEngine/Qt3D/Charts via `pyside6-addons`, none of it
  used); `PySide6-Essentials` alone is ~80 MB / ~200 MB and covers everything
  the app needs. Still small next to torch. LGPL (fine for this project).
  Prefer PySide6 over PyQt6 (same toolkit, but PyQt6 is GPL/commercial).

### 2. Stay on Tkinter, modernize the skin — cheap option

- **Pros:** Near-zero migration risk; event bus, threading rules, and all UI
  tests survive. sv-ttk (Sun Valley / Windows-11-style ttk theme, pure PyPI)
  or continued investment in our own `theme.py` (already a full theming
  engine).
- **Cons:** Tkinter's ceiling remains: DPI, rendering, Xvfb-only testing.
  customtkinter and ttkbootstrap specifically **fight our architecture** —
  customtkinter replaces ttk widgets with canvas-drawn ones (breaks
  `retheme_widgets` and the style system), ttkbootstrap wants to own the ttk
  style engine that `theme.py` owns.

### 3. NiceGUI / Flet (web-rendered) — rejected

- **Pros:** Easiest modern look; NiceGUI's headless pytest `user` fixture is
  best-in-class (no browser at all).
- **Cons (deal-breakers):** A native window needs pywebview → system
  WebKitGTK on Linux, violating requirement 3; otherwise the app lives in a
  browser tab. Live camera preview becomes MJPEG streaming over localhost.
  Hardware threads + web event loop is a worse threading story than today.
  Flet additionally ships a Flutter client binary and has had API churn.

### 4. Kivy / Dear PyGui — rejected

Kivy: PyPI-pure but mobile-toolkit look on desktop (non-native dialogs, weak
menu/DPI story); headless needs GL workarounds. Dear PyGui: GPU required,
effectively untestable headless, poor accessibility.

### 5. wxPython — rejected

No manylinux wheels on PyPI (Linux needs an extra index or a compiler),
violating requirement 3. Look is native-2010, not modern.

## Recommendation

**PySide6**, via an incremental port on a long-lived branch:

1. Spike: shell (main window + status bar) plus one simple tab (Serial or
   Camera) to prove out theming, threading, and camera-frame rendering.
2. Judge look and per-tab effort from the spike before committing.
3. If accepted, port tabs one at a time; the event bus keeps both UIs
   drivable during the transition.

Fallback if the rewrite cost is too high now: option 2 (sv-ttk / own theme
work) — a visual refresh in days instead of weeks, but the DPI/rendering/Xvfb
ceilings remain.

## Spike: PySide6 shell co-existing with the Tk UI

Status: implemented on this branch. Design goals: prove the risky parts
(theming, threading, camera rendering, headless tests) **without touching
`src/sorter/ui/` at all**, so the branch keeps merging cleanly with upstream
`main`'s Tk UI changes and both UIs can be developed in parallel.

**How the two UIs co-exist:**

- New package `src/sorter/qtui/` beside `ui/` — nothing in `ui/` changes.
- Launch: `python -m sorter --qt` (or `CASESORTER_QT=1`); default launch is
  the Tk UI, unchanged. The only shared file touched is `__main__.py`, a
  few-line branch — minimal merge surface against upstream.
- PySide6 is an optional extra (`[qt]`, mirroring how torch is `[ml]`), so
  end users and CI don't pull the wheels at all — verified: bootstrap's
  `--no-dev` sync never installs the extra. Dev setup:
  `uv sync --no-install-project --extra qt` — **add `--extra ml` in the same
  command if you use local models**: a sync installs exactly the extras named,
  so syncing `qt` alone removes an installed torch (and a `.python-version`
  bump recreates `.venv` outright, observed going 3.13→3.14 on Windows). Not
  data loss — the in-app gate reinstalls torch on the next local-model run —
  but a ~2 GB redownload waiting to happen.
- Both UIs reuse the non-UI layers unchanged: `EventBus` (Qt drains it with a
  50 ms `QTimer` instead of `root.after` — same threading contract), `Camera`,
  `SerialBroker`/`EmulatorBroker`, `Config`/`SettingsRepo`.
- **One source of truth for colors:** the Qt shell imports the palettes from
  `sorter.ui.theme.THEMES` (custom themes included) and renders them as QSS
  (`qtui/theme.py::build_stylesheet`). A theme added or edited on either side
  shows up in both.

**Increment 1 scope** (its layout is superseded by increment 2 below;
everything else carries over): main-window shell (gradient header, theme
picker, tabs, status bar), serial/camera status indicators driven by the bus, live camera
preview (BGR numpy → `QImage`), serial auto-connect (same port-walking probe
as the Tk UI), theme switching with persistence. Run/Serial tabs are
placeholders — no tab logic is ported.

**Headless testing:** `tests/unit/qtui/` runs with
`QT_QPA_PLATFORM=offscreen` — real widget construction and event-bus-driven
UI updates with no display and no Xvfb. This is the requirement-4 proof.

### Spike findings

Implemented 2026-08-12 (~660 lines: `qtui/app.py` 407, `qtui/theme.py` 135,
tests 115). All verification green: 17 qtui tests pass **offscreen with
`DISPLAY` unset** in 0.24 s (no Xvfb, no pytest-qt); full unit suite 812
passed / 0 failed; ruff and ty clean.

- **Headless testing is better than advertised** — the whole window
  constructs, the bus drives UI updates, and pixmaps rasterize with no
  display server. Stronger than the Tk side, whose UI tests need a display.
- **Wheel cost is 3.2× the original estimate** (256 MB / 648 MB on disk via
  the `PySide6` meta-package — the venv grows ~360 MB → 1.0 GB). Cause:
  `pyside6-addons` (QtWebEngine, Qt3D, Charts, Multimedia — all unused).
  **Depend on `PySide6-Essentials` (~80 MB / ~200 MB) for a real port.**
  End users are unaffected either way (extra never installs for them).
- **The `EventBus` ports unchanged.** Swapping `root.after` for a `QTimer`
  was the entire threading change; `run_worker`, the serial probe, and the
  `serial/*` topics were copied verbatim and work.
- **Live theme switching collapses to one call** — `setStyleSheet` on the
  window re-polishes the whole tree; no `retheme_widgets` equivalent needed.
  Port convention: express color roles as objectNames (`#action`, `#danger` —
  the QSS analogue of ttk style names) and keep per-widget stylesheets to a
  minimum, since those are the only thing a theme switch must re-apply by
  hand.
- **QSS gotchas found:** `QWidget { background-color }` cascades into child
  labels (needs `#header QLabel { background: transparent }` under the
  gradient); `QTabWidget::pane { top: -1px }` closes the seam under the
  selected tab.
- **Halftone/ink-outline themes have no QSS equivalent.** Comic Book renders
  flat; the ben-day screen and ink borders would need `QPainter` in a
  `paintEvent` or a generated tiled pixmap. The flat themes port 1:1.
- **`qtui` still imports tkinter transitively** — the palettes live in
  `sorter/ui/theme.py`. Harmless during co-existence; the palette-extraction
  refactor (see below) is the one `ui/` change the design eventually needs.
- **CI wiring is a decision, not free:** `build.yml` syncs without the extra,
  so the qtui tests skip there until a job adds `--extra qt`.

### Second increment: the clean-slate layout (2026-08-12)

The tabbed shell was a straight transcription of the Tk UI; increment 2 replaces
it with the shell of the design in "Proposed layout (clean-slate)" below, to
judge the *navigation* rather than the widgets. Still a layout spike — real
chrome, placeholder content wherever porting tab logic would be needed.

- **Activities sidebar** (fixed 84 px, exclusive `QToolButton`s) driving a
  `QStackedWidget`: Sort / Train / Models / Community, with Settings pinned at
  the bottom. Replaces the tab bar — the Tk UI's eight tabs don't fit one row,
  and half of them are setup, not work.
- **Sort is a dashboard**, not a tab: action row (Start/Stop/Manual feed,
  disabled — no run controller in the spike) over a `QSplitter` holding the
  camera preview beside the (unported) slot grid, with a one-line recent-
  classification strip beneath.
- **Settings is one page with a section list** (Camera, Serial, Image Proc, AI
  Config, Updates, Theme), which is where the six configuration tabs go. The
  theme picker moved out of the title bar into Settings → Theme; the header
  keeps title/subtitle only.
- **Serial monitor is a `QDockWidget`** (right, closable/floatable) instead of
  the Tk detached `Toplevel` — `View → Serial Monitor` is literally the dock's
  `toggleViewAction()`. It renders `serial/rx`, `serial/tx` and `serial/note`
  from the bus into a `QPlainTextEdit` with `setMaximumBlockCount(500)` — the
  ring buffer the Tk monitor hand-rolls with a deque.
- **Menu bar**: File → Open Data Folder / Quit, View, Help → About. The Tk UI
  has no menu bar at all; this is where "not a tab, not a button" actions
  (data folder, updates, about) stop competing for status-bar space.

Verified the same way as increment 1: 28 offscreen tests, full unit suite (823)
green, ruff/ty clean.

**Gotchas found in increment 2:**

- **`QAction.menu()` destroys the menu.** Iterating `menuBar().actions()` and
  calling `.menu()` on each hands back a *Python-owned* wrapper; when the
  temporary is collected, shiboken deletes the C++ `QMenu` and the menu bar
  silently loses that entry (later access raises "Internal C++ object already
  deleted"). Keep the menus in a dict on the window (`self.menus`) and go
  through that — in app code and in tests.
- **`QWidget`-selector cascade bites again, harder.** The base
  `QMainWindow, QWidget` rule paints every descendant, so each new container
  (`#sidebar`, its `QToolButton`s) needs an explicit background or it fights
  the surface it sits on. Same class of fix as `#header QLabel`.
- **`QDockWidget::title` is style-able, its buttons are not** (without shipping
  icons): float/close glyphs come from the platform style, so a dark palette
  gets platform-colored controls on a themed title bar. Acceptable; icons are a
  later polish item.
- **`QSplitter::handle` needs an explicit `width`/`height`** as well as a
  background, or the themed handle is invisible.
- Emoji-as-icon in the sidebar works and renders fine offscreen, but real SVG
  icons (`QIcon`) are the end state — emoji colour is out of the palette's
  control, which breaks the "every color comes from the theme" rule.

### Third increment: the showcase (implemented 2026-08-12)

Makes the Sort dashboard actually sort, so the demo needs no slideware: slot
cards with live counts from the real `Config`, the `RunController` wired
(same preflights as the Tk Run tab; PyTorch install still deferred to the Tk
UI), a live recent-classification feed, and a minimally real Settings→Serial
page whose port picker includes **"Emulated"** — the whole demo runs against
the `SerialEmulator` with no machine on the bench, over the same code path
the real board uses.

**Demo script (~2 minutes):**

1. `./start.sh` → the familiar Tk UI. Close it. Same command with `--qt` →
   the new UI. (Point: both ship from one tree; end users see no change.)
2. Sort dashboard: sidebar, live camera preview, slot cards.
3. Settings → Serial → port "Emulated" → Connect → status dot goes green,
   serial dock streams the handshake.
4. Back to Sort → Manual feed, then Start: cards count up, the recent feed
   scrolls with confidence coloring, the dock shows each exchange.
5. Switch theme mid-run (Settings → Theme): everything restyles live,
   including the dock and cards.
6. Close, `git log --oneline`: every increment tested headless (no display
   server) and green in the same suite as the Tk UI.

Explicitly not in the showcase (parity items for the real port): package
mode counters/reset, sorting-template UI, slot-assignment editing (checkbox
grid + slot details), auto-select `mode/changed` re-render, wish-list
capture, the AI-credentials preflight, cropped-frame preview, Serial-page
disconnect/init-settings push, and the PyTorch install dialog (deliberately
routed to the Tk UI; `dialog_install_torch`'s `after()`-from-worker pattern
must not be copied anyway).

**Demo caveat:** the emulator removes the *hardware* dependency, not the
classifier one. On a fresh DB the app is in AI-config mode and Start will
fail at classify time against an unconfigured endpoint — demo with a
configured AI endpoint or a local model (checkpoint + torch). Manual feed
demos fine with the emulator alone.

**Increment-3 findings (54 qtui tests, full suite 849, ruff/ty clean):**

- Verified `run/*` payload shapes worth pinning for the port: `run/result`
  carries `ok` and a `slot` even for a failed cycle — counts must key off
  `ok`; `run/stopped` fires from the loop's `finally` (also on error and
  package-halt), so button state must derive from `run/started`/`run/stopped`
  and never from the click handlers; `run/error` does not imply the run
  stopped.
- The transparent-children rule is now a rule, not a gotcha: every container
  with a QSS background (`#header`, `#sidebar`, now `#slotCard`) needs a
  `... QLabel { background: transparent; }` companion.
- New-widget color roles belong in objectNames (`#slotCount`, `#slotNames`),
  which the single `setStyleSheet` repaints on theme switch; only colors
  baked into rich text (the feed's confidence spans, the status dots) need
  hand re-rendering.
- The emulator path is a genuine end-to-end test: `Emulated` →
  `EmulatorBroker` → `RunController.cycle_once` → timer-delayed `done` →
  `run/result` → card count, driven headless in 0.12 s by pumping
  `bus.drain()` in a bounded poll (`drain_until` in the qtui conftest) — the
  pattern for every future qtui test involving a worker.
- qtui tests now run against a real `Database` + `Config` on `tmp_path`
  (shared conftest), not a stub — removed defensive code from the widgets.

## Cost to complete (calibration in progress)

Unit of measure: one *increment* = spec → Opus agent implements → review,
verify (pytest/ruff/ty), commit. Measured so far: spike 1 ≈ 8 min agent time
/ ~30 min wall clock (~660 lines); spike 2 ≈ 9 min / ~30 min (~460 lines);
user-found fixes ≈ 5–10 min each (2 so far). The remaining parity work is
~17–25 increments (per-chunk table in the session notes; Sort and Models are
the dense ones).

First estimate ranged **15–25 h** on the assumption that dense,
behavior-pinned chunks run well above spike velocity. JL disputed that as too
high, and spike 3 — the deliberate calibration point, ~3× the size of the
earlier increments and wired into the real run path — measured **~10.5 min
agent time, ~880 changed lines, 2 implementation passes, ~30 min wall
clock**: triple the scope at the *same* wall-clock cost. The assumption was
wrong; density is absorbed by the agent, and the wall-clock floor is the
spec/review/verify cycle (~20 min) rather than the code volume.

**Re-baselined estimate: ~8–12 h of session wall clock** — the remaining
parity work is roughly 10–14 spike-3-sized increments at ~30–45 min each.
Residual risk sits in the deferred-items list above (package mode, template
UI, assignment editing, the community/auth surfaces that need the real
backend) and in increments that need look-and-feel rounds. The user-paced
parts (bench validation against the physical machine) still sit outside
these hours and set the calendar time regardless.

## What retiring `ui/` would remove (beyond the directory itself)

Audited 2026-08-12: outside `src/sorter/ui/` and `tests/unit/ui/`, nothing in
`src/` imports tkinter or `sorter.ui` except the one launch line in
`__main__.py` — the layering is genuinely clean. Dropping `ui/` at the end of
a full port also retires:

- **`tests/unit/ui/`** (~4,000 lines) — replaced by offscreen Qt tests.
- **The `--qt` switch itself** — Qt becomes the only path in `__main__.py`.
- **Xvfb everywhere.** `build.yml`'s `xvfb-run -a pytest` and the xvfb
  apt-installs go; Qt tests run on `QT_QPA_PLATFORM=offscreen` with no
  display server. The launcher-smoke's `import tkinter` check becomes an
  `import PySide6` check.
- **The Tcl/Tk constraint on the Python runtime.** uv-provisioned Python was
  chosen partly because its builds bundle Tcl/Tk (bootstrap.py, CLAUDE.md §2,
  build.yml comments); that requirement — and re-verifying it on every
  `.python-version` bump — disappears.
- **Tk-compensation infrastructure** that exists only because Tk lacks the
  feature: `ScrollableFrame`, `ImagePanel`, canvas gradient/halftone painting,
  `retheme_widgets` (re-colouring widgets that baked colors in),
  `markdown_render.py` (252-line hand-rolled markdown→Tk-Text renderer — Qt
  renders markdown natively), and the `widget.after()` threading gotchas.
- **Pillow from the core dependencies, probably.** Outside `ui/` it's used
  only by `train_convnext.py` and `eval_report.py`, both of which run under
  the `[ml]` extra where torchvision already requires Pillow. Qt renders
  numpy frames directly (`QImage`), so the core-dep slot ships ~10 MB lighter.
  (Verify the transitive guarantee before actually dropping it.)

**One prerequisite before `ui/` can be deleted:** the palette data
(`THEMES`, `BUILTIN_THEMES`, `normalize_palette`, custom-theme persistence)
lives in `sorter/ui/theme.py`, and the Qt spike deliberately imports it from
there (single source of truth during co-existence). It must move to a
toolkit-neutral module first; only the Tk-rendering half of `theme.py` (ttk
styles, fonts, canvas painting) dies with `ui/`.

What stays despite feeling UI-adjacent: `pygrabber` (Windows camera names),
opencv, and the `EventBus` (still the UI seam; migrating to signals/slots is
a separate, optional step).

### The hardware layer stays toolkit-neutral: pyserial + cv2

Qt ships its own serial (QtSerialPort) and camera (QtMultimedia) stacks;
decided against both:

- **pyserial stays.** The serial consumer isn't the UI — it's the sort loop,
  a daemon thread making *blocking* calls (`sort_and_move` waits on the
  board's `done`/`ok` with a timeout). QSerialPort is async,
  event-loop-driven, and not usable across threads without its own
  `QThread`+loop, so adopting it means rebuilding the run loop's synchronous
  waits as state machines — real work, no functional gain. Its enumeration
  perks (VID/PID, friendly names) pyserial already has. It also lives in
  `pyside6-addons`, which we deliberately don't install.
- **cv2 stays.** The classifier needs raw numpy BGR frames — exactly what
  cv2 produces and QtMultimedia doesn't want to hand out.
- Keeping `hardware/` Qt-free is also what lets both UIs share it during
  co-existence, along with the emulator and the firmware-pinned protocol
  tests.

## Proposed layout (clean-slate)

Per the port principle above, the Qt UI does not clone the Tk screens. The
Tk UI's flat row of eight equal tabs treats daily activities and one-time
setup as siblings; actual usage is that **Run is where an operator lives**,
Train/Models/Community are occasional, and Camera/Serial/Image Proc/AI
Config are setup surfaces visited rarely. The proposed shape follows what
mature Qt apps converge on (Qt Creator, OBS, Telegram Desktop, Arduino
IDE 2):

```
┌──────────────────────────────────────────────────────────────┐
│ File  View  Tools  Help                                      │
├────┬─────────────────────────────────────┬───────────────────┤
│ ▶  │  [▶ Start]  [Feed 1]   Template ▾   │  Serial Monitor   │
│Sort│ ┌───────────────┐ ┌───────────────┐ │  (dock, optional) │
│ 🎓 │ │ live preview  │ │ slot cards    │ │ <- ok             │
│Train│ │ (camera)     │ │ w/ counts     │ │ -> xf:0           │
│ 📦 │ └───────────────┘ └───────────────┘ │ <- done           │
│Mdls│  recent: 9mm ✓ .223 ✓ 9mm ✓ 45acp ?│                   │
│ 🌐 │                                     │                   │
│Comm│                                     │                   │
│ ⚙️ │                                     │                   │
├────┴─────────────────────────────────────┴───────────────────┤
│ Idle.                    ● Camera: OK   ● Serial: COM3  ⟳ 👤 │
└──────────────────────────────────────────────────────────────┘
```

1. **Left activity sidebar → `QStackedWidget`**, not a top tab row. Four
   activities — Sort, Train, Models, Community — plus a Settings entry
   pinned at the bottom (the Qt Creator mode-selector / Telegram pattern).
   Mode-driven visibility (Train only for owned models, Community only when
   signed in) maps to hiding/showing sidebar entries, same `mode/changed`
   event as today.
2. **Sort is a dashboard, not a form.** Live camera preview *in* the Sort
   view (operators want to see what the machine sees while it runs), a
   prominent Start/Stop, the slot-card grid with live counts, and the
   recent-classification feed integrated — an OBS-style monitoring surface.
   A `QSplitter` trades preview size against grid size.
3. **All configuration becomes one Settings view**: Camera, Serial, Image
   Proc, AI Config, Updates, Theme as a searchable section list (Qt Creator
   Options / OBS Settings pattern). Removes four top-level tabs in one move.
4. **`QDockWidget` for utility panels.** Serial monitor and classification
   history become dockable/floatable panels — beside Sort on a wide screen,
   floated to a second monitor, closed when irrelevant. Native Qt strength;
   the Tk app grew detached toplevels precisely because Tk lacks this.
5. **A real `QMenuBar` + shortcuts** (File/View/Tools/Help): Check for
   Updates, Open Data Folder, Sign In, About. Free discoverability and
   accessibility; absent in Tk because Tk menus fight the theming.
6. **Empty states instead of assumptions.** No camera/board/model on first
   run → guided panels with action buttons where the dashboard will be,
   not tabs that presume a configured machine.

Function parity per capability is unaffected — this changes where things
live, not what exists. **Spike 2 on this branch implements the shell of
this layout** (sidebar, dashboard skeleton, Settings view, serial-monitor
dock, menu bar) with placeholders where real tab logic would go.

## Open questions

- Is the pain mostly *visual* (option 2 fixes it) or *structural* — DPI,
  widget quality, testability (only option 1 fixes those)?
- Keep the `EventBus` as-is under Qt, or migrate to signals/slots? (Bus keeps
  the non-UI layers untouched; signals are the idiomatic end state.)
- ~~Wheel-size impact on first-run sync~~ — answered: end users never get
  the extra; devs pay 36 s once. The extra now pins `PySide6-Essentials`
  (~80 MB; venv 594 MB vs 1.0 GB with the meta-package). Anything from
  `pyside6-addons` a future feature wants (e.g. QtWebEngine for in-app HTML
  reports) gets added to the extra explicitly at that point.
- Halftone & ink-outline themes: accept flat rendering under Qt, or invest
  in a `paintEvent`/tiled-pixmap port? (Spike showed QSS alone can't do it;
  everything else themes 1:1.)
- CI: add a `--extra qt` job (or matrix leg) so the qtui tests actually run,
  and decide when the ~256 MB per-job download is worth it.

## Decision log

| Date | Decision |
|------|----------|
| 2026-08-12 | Ruled out web-rendered (NiceGUI/Flet), Kivy, Dear PyGui, wxPython against the four requirements. PySide6 identified as the only full-fit; skin-refresh kept as fallback. No go/no-go yet. |
| 2026-08-12 | Spike built as a **co-existing** UI: `sorter/qtui/` beside `ui/`, `--qt`/`CASESORTER_QT=1` opt-in, PySide6 as a `[qt]` extra, palettes shared from `sorter.ui.theme`. Lets Qt work proceed in parallel while tracking upstream Tk changes. |
| 2026-08-12 | Port principle set: **function parity, not UI parity** — the Qt UI redesigns the UX freely as long as every capability of the Tk UI survives. |
| 2026-08-12 | Spike implemented and verified (17 offscreen tests, full suite green, ruff/ty clean). Headless story confirmed; wheel estimate corrected to 256 MB (meta) vs ~80 MB (`PySide6-Essentials` — recommended); halftone/ink themes flagged as the one theming gap. |
| 2026-08-12 | `[qt]` extra swapped to `PySide6-Essentials==6.11.1` — pixel-identical (spike uses only QtCore/QtGui/QtWidgets, all in essentials; the meta-package adds only unused addons + stubs). Gotcha for existing dev venvs: the wheels overlap, so uninstalling the meta clobbers `PySide6/__init__.py` and the stubs — fix with `uv sync --extra qt --reinstall-package pyside6-essentials`. |
| 2026-08-12 | Hardware layer stays toolkit-neutral (pyserial + cv2); QtSerialPort/QtMultimedia rejected — see "The hardware layer stays toolkit-neutral". |
| 2026-08-12 | Clean-slate layout proposed (activity sidebar + Sort dashboard + unified Settings + docks + menu bar — see "Proposed layout"); spike 2 implements its shell. |
| 2026-08-12 | Spike 3 (showcase) implemented: Sort dashboard sorts for real — slot cards with live counts, RunController wired, recent feed, Settings→Serial with the Emulated port. 54 headless tests. |
| 2026-08-12 | Cost estimate re-baselined from spike 3's measurement: ~8–12 h session time to parity (was 15–25 h; the "dense chunks are slower" assumption measured false). |
| 2026-08-12 | **Windows validated**: the showcase build runs on a real Windows machine from a plain `uv sync --extra qt` — sidebar, dashboard and all; only runtime noise is OpenCV's DSHOW "no camera" warning. Requirement 2 now confirmed empirically on Linux + Windows. |
| 2026-08-12 | Spike 2 built and verified (28 offscreen tests, full unit suite green, ruff/ty clean). New gotchas: `QAction.menu()` deletes the menu it returns; dock title-bar buttons aren't themable without icons. Sidebar glyphs stay emoji until real `QIcon`s exist. |
