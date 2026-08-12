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
| 5 | Models activity: library browse/filter/create/edit/activate/delete, import/export ZIP, "Use AI Config" row; model editor dialog | `tab_models.py`, `dialog_model_editor.py` | Opus | ☐ |
| 6 | Train activity: feed→capture→classify→label→save loop, sort-while-training, training config + progress dialogs, launch/cancel training | `tab_train.py`, `dialog_training_*.py` | Opus | ☐ |
| 7 | Install-PyTorch dialog (Qt-native, correct threading — do NOT copy the Tk `after()` pattern) + torch gate equivalent | `dialog_install_torch.py`, `torch_gate.py` | Opus | ☐ |
| 8 | Model images browser + preview (reclassify/delete) | `dialog_model_images.py`, `dialog_image_preview.py` | Sonnet | ☐ |
| 9 | Evaluator: run eval, HTML report, history | `dialog_model_evaluator.py` | Opus | ☐ |
| 10 | Community activity + login + share dialogs (auth-gated sidebar entry) | `tab_community.py`, `dialog_login.py`, `dialog_share_model.py` | Opus | ☐ |
| 11 | Updates: **Help → "Check for updates…"** (JL 2026-08-12: not under Settings) + status-bar affordance when one is staged, dialog (notes→progress→restart), version picker; drop the Settings→Updates section | `dialog_update.py`, `app.py` update wiring | Opus | ☐ |
| 12 | Serial monitor dock parity: filter, RX/TX/notes toggles, pause/flush, save, timestamps, line endings, command box + history, baud switch, backlog replay | `serial_monitor.py` | Sonnet | ☐ |
| 13 | Classification history with images (dashboard feed grows thumbnails / dock) | `monitor.py` | Sonnet | ☐ |
| 14 | Chrome parity: sign-in button + auth state, empty states (no camera/board/model), Tools menu (check updates, sign in), window/session polish, **remaining Run options: confidence floor, store-images mode, auto-select trays (left out of #1)** | `app.py` (Tk), `tab_run.py` options | Sonnet | ☐ |
| 15 | Theme editor (build/save/rename/import/export custom themes) — descopable; halftone/ink themes stay flat under Qt either way | `dialog_theme_editor.py` | Opus | ☐ |
| 16 | CI: qt test job (offscreen, `--extra qt`); CLAUDE.md + docs final pass; parity sign-off checklist | workflows, docs | Fable | ☐ |

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
- [ ] Models library (create/edit/activate/delete/import/export)
- [ ] Train loop (capture/label/save, sort-while-training)
- [ ] Training runs (config, progress, cancel)
- [ ] PyTorch install gate (Qt-native)
- [ ] Training-image browser (reclassify/delete)
- [ ] Evaluator + HTML report
- [ ] Community (browse/download/share) + sign-in
- [ ] Feedback loop + wish-list capture (Run-tab side)
- [ ] Self-update dialog + version picker
- [ ] Serial monitor (full feature set)
- [ ] Theme switching (built-ins + custom loading) — done; editor pending
- [ ] First-run/empty states

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
