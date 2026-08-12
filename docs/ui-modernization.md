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
- **Cons:** Full rewrite of `ui/` and its tests. Heavy wheel (~150 MB —
  though small next to torch). LGPL (fine for this project). Prefer PySide6
  over PyQt6 (same toolkit, but PyQt6 is GPL/commercial).

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

## Open questions

- Is the pain mostly *visual* (option 2 fixes it) or *structural* — DPI,
  widget quality, testability (only option 1 fixes those)?
- Keep the `EventBus` as-is under Qt, or migrate to signals/slots? (Bus keeps
  the non-UI layers untouched; signals are the idiomatic end state.)
- Wheel-size impact on `bootstrap.py` first-run sync time — acceptable?
- What happens to the custom theme editor / halftone & ink-outline themes
  under QSS? (Portable in principle; needs spike validation.)

## Decision log

| Date | Decision |
|------|----------|
| 2026-08-12 | Ruled out web-rendered (NiceGUI/Flet), Kivy, Dear PyGui, wxPython against the four requirements. PySide6 identified as the only full-fit; skin-refresh kept as fallback. No go/no-go yet. |
