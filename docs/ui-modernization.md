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
  `uv sync --no-install-project --extra qt`.
- Both UIs reuse the non-UI layers unchanged: `EventBus` (Qt drains it with a
  50 ms `QTimer` instead of `root.after` — same threading contract), `Camera`,
  `SerialBroker`/`EmulatorBroker`, `Config`/`SettingsRepo`.
- **One source of truth for colors:** the Qt shell imports the palettes from
  `sorter.ui.theme.THEMES` (custom themes included) and renders them as QSS
  (`qtui/theme.py::build_stylesheet`). A theme added or edited on either side
  shows up in both.

**Spike scope:** main-window shell (gradient header, theme picker, tabs,
status bar), serial/camera status indicators driven by the bus, live camera
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

## Open questions

- Is the pain mostly *visual* (option 2 fixes it) or *structural* — DPI,
  widget quality, testability (only option 1 fixes those)?
- Keep the `EventBus` as-is under Qt, or migrate to signals/slots? (Bus keeps
  the non-UI layers untouched; signals are the idiomatic end state.)
- ~~Wheel-size impact on first-run sync~~ — answered: end users never get
  the extra; devs pay 36 s once. Remaining decision: switch the extra to
  `PySide6-Essentials` before the real port starts.
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
