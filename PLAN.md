# qtui full-port plan

Living document — the orchestrator (Claude Fable 5) updates status and the
progress log after every increment; implementation is delegated to subagents
(Opus for dense/behavior-pinned work, Sonnet for well-specified forms).
Research, findings, and decisions stay in `docs/ui-modernization.md`; this
file is the execution tracker.

**Goal:** function parity per capability with `sorter/ui/` (Tk), per the port
principle — UX is redesigned, capabilities are not dropped. End state: the Qt
UI can be someone's daily driver; retiring `ui/` is a later, separate
decision.

## Ground rules (every increment)

- `src/sorter/ui/` is never touched. `__main__.py` keeps the `--qt` branch.
- Workers never touch widgets: bus post → 50 ms drain, `run_worker` pattern.
- Every increment lands with tests at BOTH levels (JL 2026-08-12):
  - **Unit**: headless widget/behavior tests (offscreen, real `Database` +
    `Config` on tmp_path via `tests/unit/qtui/conftest.py`).
  - **Integration**: at least one end-to-end flow through the real layers —
    the emulator-driven pattern from increment 3 (real bus → RunController →
    EmulatorBroker → widgets), DB round-trips for anything persisted, and
    for subsystem seams (updater, model ZIPs, training subprocess) hooks
    into the flows `tests/integration/` already exercises.
  - Green gates before commit: full `pytest` (integration included, minus
    self-skipping external tools), `ruff check`, `ty check`.
- Increment 16 additionally builds a cross-cutting e2e suite: scripted
  demo-path runs (connect→assign→sort→counts→templates) against the
  emulator, asserting the same things a human demo shows.
- New pages/dialogs go in their own module; `app.py` only wires.
- Colors via objectNames in `qtui/theme.py`; every color from the palette.
- Commits: conventional, DCO-signed, one increment per commit, pushed to
  `origin/ui-modernization-research` after review.
- **UX deltas are conservative by default** (JL 2026-08-12): users know the
  WinForms-style UI, so don't change workflows gratuitously. Layout/idiom
  modernization is fine; *bigger* departures (a workflow moving, an
  interaction model changing, a feature relocating) stop and ask JL first
  unless the improvement is obvious.

## Increments

Status: ☐ todo · ▶ in progress · ✔ done · ✗ blocked

| # | Increment | Covers (Tk reference) | Agent | Status |
|---|-----------|----------------------|-------|--------|
| 0 | Spikes 1–3: shell, layout, showcase | app shell, run loop core | Opus | ✔ (`2f0711b`…`5de9b58`) |
| 1 | Sort parity core: slot-assignment editing, sorting-template bar + dialog, master/package counters, package halt+bell, cropped-crop preview, AI-credentials preflight, `mode/changed` (Train visibility + grid refresh) | `tab_run.py`, `dialog_slot_template.py` | Opus | ✔ (`3e2e4b6`) |
| 2 | Settings: Camera page (enumerate/resolutions/apply/restart) + Image Proc page (Hough/primer/LED, before-after preview) | `tab_camera.py`, `tab_imageproc.py` | Sonnet | ✔ (`427dadb`, wired in `3e2e4b6`) |
| 3 | Settings: AI Config page (server config, headstamp manager, single-shot test) | `tab_ai.py` | Opus | ✔ (`be64586`) |
| 4 | Settings: Serial page parity (init settings, disconnect, sort-arm test, airdrop) | `tab_serial.py` | Sonnet | ✔ (`5cb9c50`) |
| 5 | Models activity: library browse/filter/create/edit/activate/delete, import/export ZIP, "Use AI Config" row; model editor dialog | `tab_models.py`, `dialog_model_editor.py` | Opus | ✔ (`29d7be6`) |
| 6 | Train activity: feed→capture→classify→label→save loop, sort-while-training, training config + progress dialogs, launch/cancel training | `tab_train.py`, `dialog_training_*.py` | Opus | ✔ (`2c8fd6c`) |
| 7 | Install-PyTorch dialog (Qt-native, correct threading — do NOT copy the Tk `after()` pattern) + torch gate equivalent | `dialog_install_torch.py`, `torch_gate.py` | Opus | ✔ (`6101ddb`) |
| 8 | Model images browser + preview (reclassify/delete) | `dialog_model_images.py`, `dialog_image_preview.py` | Sonnet | ✔ (`cc6b425`) |
| 9 | Evaluator: run eval, HTML report, history | `dialog_model_evaluator.py` | Opus | ✔ (`39e178f`) |
| 10 | Community activity + login + share dialogs (auth-gated sidebar entry) | `tab_community.py`, `dialog_login.py`, `dialog_share_model.py` | Opus | ✔ (`8e20b81`, wired `255a3fe`) |
| 11 | Updates: **Help → "Check for updates…"** (JL 2026-08-12: not under Settings) + status-bar affordance when one is staged, dialog (notes→progress→restart), version picker; drop the Settings→Updates section | `dialog_update.py`, `app.py` update wiring | Opus | ✔ (`415d33c`, wired `255a3fe`) |
| 12 | Serial monitor dock parity: filter, RX/TX/notes toggles, pause/flush, save, timestamps, line endings, command box + history, baud switch, full-history-since-launch (JL: upstream #78/#86 features) | `serial_monitor.py` | Sonnet | ✔ (`0bf3e8b`) |
| 13 | Classification history with images (dashboard feed grows thumbnails / dock) | `monitor.py` | Sonnet | ✔ (`1a43bb1`) |
| 14 | Chrome parity: sign-in button + auth state, empty states (no camera/board/model), Tools menu (check updates, sign in), window/session polish, **remaining Run options: confidence floor, store-images mode, auto-select trays (left out of #1)**; **Help menu grows (JL): bigger About, Help→License, links (this repo, CS7.2 hardware/firmware repo, Seth's shop, report-an-issue)**; dock-position persistence (saveState) | `app.py` (Tk), `tab_run.py` options | Sonnet | ✔ (`8bc7f6d`) |
| 15 | Theme editor (build/save/rename/import/export custom themes) — descopable; halftone/ink themes stay flat under Qt either way | `dialog_theme_editor.py` | Opus | ▶ |
| 17 | **Headstamp manager dialog** (parents, auto-suggest, rename incl. on-disk image renames, unsaved guard — gap found in #5: Tk's Models tab has it, no Qt equivalent; ~660 Tk lines) | `dialog_headstamps.py` (Tk: inside `tab_models.py`) | Opus | ✔ (`35c9896`) |
| 20 | **The PR** (JL 2026-08-13, clarified: **in the fork** — base `jimisola:main`, head `ui-modernization-research`, created by Fable via `gh`; Seth reviews by link; NOT a cross-repo PR to sjseth). Body top-to-bottom: (1) how to run the qtui (clone/sync/launch, three OSes); (2) explicit note that the Tk UI is untouched and remains the default — nothing removed (yet); (3) feature-parity table from PLAN's checklist; (4) design decisions (co-existence, activity sidebar, docks, function-not-UI parity) + the judgment-call register; (5) open items (register "Open" rows, halftone themes, #18 docs approval) + LINK the parity-gap issue jimisola#29 (Windows-guide inventory); (6) pros of the stack — LEAD with the testability contrast (JL): the Tk UI's modules sit at 9–19% coverage because its tests need a display and skip headless, while the Qt layer measures **91% (branch) fully headless** — same functionality, no Xvfb, no display server, 460+ tests in ~80s; include the per-layer coverage table, note whole-app 55% today rises sharply when ui/ retires, plus PySide6-Essentials sizing, LGPL/GPL fit, single-source docs PoC; (7) test/velocity numbers. Draft PR; no merge — Seth decides. | `docs/ui-modernization.md`, `PLAN.md` as sources | Fable | ☐ **GO GRANTED (JL 2026-08-13): create after the final sweep** |
| 18 | **Application documentation** — original user guide for the OSS app, informed by the structure/topics of Seth's CS7.2 Application Guide PDF (his copyrighted work: adapt with permission, never copy); includes picking the format and an in-app context-aware help mechanism (see log) | new `docs/guide/` | — | ✗ **blocked: needs Seth's green light (JL 2026-08-13)** |
| 19 | **Decouple qtui from ui/** (JL 2026-08-13: no qtui→ui dependencies): copy palettes + theme machinery to `qtui/palettes.py`, copy serial-monitor constants; byte-equality drift-pin tests against the ui/ originals (CI-enforced); drop tkinter importorskip from qtui tests | `ui/theme.py`, `ui/serial_monitor.py` (read-only) | Fable | ☐ (after wave-3 integration) |
| 21 | Polish batch (JL live-testing): app-wide ISO dates (YYYY-MM-DD, 24h) via one shared helper regardless of UI language; Models-table column sorting (typed items, evaluator's `_SortableItem` pattern — natively supported by Qt); Settings gear colored via objectName QSS; file-filter labels that survive GNOME's paren-stripping (e.g. "Model archives — *.zip") | qtui polish | Sonnet | ▶ (dates respec'd: OS-locale formats via QLocale.system, NOT hardcoded ISO — JL correction) |
| 16 | CI: qt test job (offscreen, `--extra qt`); CLAUDE.md + docs final pass; parity sign-off checklist | workflows, docs | Opus | ▶ |

Increments 1–2 run in parallel (disjoint modules; the orchestrator wires
`app.py` integration for #2 to avoid conflicts). Later increments are
sequential unless files are provably disjoint.

## Capability parity checklist

Checked when the Qt UI covers it (not necessarily with the Tk layout):

- [x] Live camera preview; camera connect state
- [x] Serial connect (auto + manual + emulator); connect state
- [x] Start/Stop/manual-feed with Tk preflights (torch/checkpoint)
- [x] Slot cards with live counts; catch-all slot
- [x] Recent-classification feed (labels + confidence)
- [x] Slot assignment editing (standard + package + parents)
- [x] Sorting templates (switch/new/rename/delete, live sync)
- [x] Package mode (counters, halt, bell, reset)
- [x] Auto-select trays (`run/assignment_changed`) — grid follows; the enable toggle ships with #14
- [x] Master counter + reset
- [x] Camera setup (device/resolution)
- [x] Image-proc tuning (Hough, primer mask, LED)
- [x] AI Config (server, prompt, headstamp manager, test shot)
- [x] Serial board init settings + sort-arm test + airdrop
- [x] Models library (create/edit/activate/delete/import/export)
- [x] Train loop (capture/label/save, sort-while-training)
- [x] Training runs (config, progress, cancel)
- [x] PyTorch install gate (Qt-native)
- [x] Training-image browser (reclassify/delete)
- [x] Evaluator + HTML report
- [x] Community (browse/download/share) + sign-in
- [x] Feedback loop + wish-list capture (Run-tab side) — RunController-side, active since #3's run wiring
- [x] Self-update dialog + version picker
- [x] Serial monitor (full feature set)
- [x] Theme switching (built-ins + custom loading) — editor is #15
- [x] First-run/empty states

## Progress log

- 2026-08-12 ~21:15 — Plan created. Wave 1 launched: increment 1 (Opus) and
  increment 2 (Sonnet, module-only contract; orchestrator wires `app.py`).
- 2026-08-12 ~22:05 — Increments 3–4 launched in parallel with 1 (JL asked
  for all settings). Theme editor decision (JL): keep in plan, late (#15).
- 2026-08-12 ~22:40 — Increments 1, 2, 3 landed (`427dadb`, `3e2e4b6`,
  `be64586`). qtui tests 54 → 133; full suite 940 green. Orchestrator
  overrides applied per the conservative-UX rule: counts survive Stop/Start
  (Tk parity, jam-clearing), package-halt shows the dialog again (queued out
  of the drain), AI-page Clear-all keeps Tk's confirmation. Run options
  (floor/store-images/auto-select) moved to #14. Increment 4 still running.
- 2026-08-12 ~23:10 — Increment 4 landed (`5cb9c50`): the Settings view is
  complete (Camera, Serial, Image Proc, AI Config, Theme). qtui tests 158,
  full suite 965. Orchestrator fixes at integration: init-on-startup push
  moved into the shared `_after_connect` (auto-connect parity gap the agent
  flagged), `connect_serial` decoupled from page widgets. Free-hands
  wishlist started in docs/ui-modernization.md (JL). Next wave: #5 Models
  (Opus) + #8 image browser (Sonnet, module-only).
- 2026-08-12 ~23:25 — JL: session tokens nearly exhausted (reset ~01:00).
  After increments 5+8 integrate, switch to ONE subagent at a time to pace
  the burn; #12 (serial monitor parity, Sonnet) goes first as the cheapest
  file-disjoint increment, then back to plan order after the reset.
- 2026-08-13 ~00:05 — Increments 5+8 landed (`29d7be6`, `cc6b425`); qtui
  tests 199, full suite 1006. Session token ceiling: STOPPING here. Next
  session: hoist CASESORTER_DATA_DIR isolation into qtui conftest (#5's
  finding), then #6+#7 (Opus), #12 (Sonnet), and new #17 (headstamp
  manager — parity gap #5 uncovered). Open UX flags for JL: three-way
  import choice (kept), preview prev/next (kept), Images-disabled for
  foreign models (kept).
- 2026-08-13 — New token session; JL: max parallelism. Wave 3 = SIX
  concurrent: #6 (Opus, sole app.py owner), #7/#9/#17 (Opus, module-only),
  #12/#13 (Sonnet, module-only). theme.py frozen for everyone — QSS lands
  via the orchestrator at integration. Landed meanwhile: resizable model
  columns (`35a25fd`), Settings-Camera live feed (`a97a5b2`), bottom serial
  dock (`05bdd01`).
- 2026-08-13 — #18 added (JL), explicitly NOT started until Seth approves:
  app documentation adapted for the OSS version. Format leaning: Markdown
  in-repo (GitHub renders it; MkDocs Material later if a site is wanted;
  AsciiDoc overpowered here; Mintlify is hosted/commercial and shaped for
  API/SaaS docs — poor fit for a desktop app). Context-aware inline help is
  feasible with zero new deps: QTextBrowser renders Markdown natively, so
  the same docs source can back per-page F1 help via anchors, plus Qt's
  built-in QWhatsThis (Shift+F1 per-widget) and status-bar tips. Decision
  deferred to the increment itself.
- 2026-08-13 — JL rules: NO runtime dependencies qtui→ui. Mechanism: copies
  + byte-equality drift-pin tests (ui/ stays untouched; custom themes still
  sync via the DB setting). Added as #19, right after wave-3 integration.
  Docs' "one source of truth for colors" section to be amended accordingly.
- 2026-08-13 — JL: write out "Image Proc" as "Image Processing" in the UI.
  Queued for the wave-3 integration pass (the string is in app.py, owned by
  #6 until it lands).
- 2026-08-13 — Wave 3 fully integrated and pushed (`2c8fd6c`…`e6cf42f`):
  Train, torch gate, serial monitor, history dock, evaluator, headstamp
  manager, docs PoC, OSS title + GPL header, "Image Processing" written
  out. Full suite 1176 passed; ruff/format/ty clean. Register additions:
  Feed disabled without a board (#6, changed), counts-list click
  saves-and-feeds (#6, kept Tk), evaluator preview uses #8's browsable
  navigation. Remaining: #10 Community, #11 Updates, #14 chrome, #15 theme
  editor, #19 decouple, #16 CI/e2e, #18 (Seth), #20 (PR, JL go).
- 2026-08-13 — Wave 4 launched: #10 Community (Opus, module-only), #11
  Updates dialog (Opus, module-only; Help-menu wiring at integration), #14
  chrome (Sonnet, sole app.py/theme.py owner). Also in flight: single-file
  guide restructure (Sonnet); help-as-dock conversion (JL) applies at its
  integration. #19 decoupling held until #14 releases app.py.
- 2026-08-13 — Wave 4 fully landed (`8bc7f6d`, `8e20b81`, `415d33c`,
  `255a3fe`): chrome, Community, updates, sign-in, guide dock. qtui 463
  green; full suite 1277. Issue #29 expanded to implementable specs (agent
  audit corrected 6 inventory items — e.g. Model Statistics schema already
  exists as dead columns). #20 note (JL): the PR points at PLAN.md; PLAN.md
  and docs/guide PoC get DELETED from the branch before any upstream merge.
  Remaining: #21 polish batch, #15 theme editor, #19 decoupling, #16 CI+e2e,
  #18 (Seth), #20 (PR — JL go).
- 2026-08-13 — qtui coverage measured: 91% (7,281 stmts / 657 missed;
  modules 85–100%). JL grants the #20 go: PR is created by Fable right after
  the final sweep (integrate 15/16/21 → #19 decoupling → register/PLAN/
  checklist sweep → full gates → draft PR in the fork, linking issue #29 and
  PLAN.md, noting PLAN.md + docs/guide PoC are deleted before upstream
  merge).
- 2026-08-13 — JL: quick parity batch (issue #29 B1/B2/A6/A12/A14/A16)
  WAITS until after the PR. Sequence locked: #21+#16 land → integrate +
  wire #15's editor button → #19 decoupling (Fable) → final sweep → PR.
