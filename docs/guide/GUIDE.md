# AI Case Sorter — Qt UI Guide

A short guide to the Qt desktop client (launched with `--qt`), covering the
screens you use day to day. This is a proof-of-concept guide: it documents
two screens end to end so the same Markdown can be checked both on GitHub
and inside the app's own help viewer.

## Contents

- [Sort dashboard](#sort-dashboard) — the sidebar's main working screen: the
  current case, slot cards, sorting templates, and the
  Start/Stop/Manual-feed controls.
- [Settings](#settings) — device and board configuration, including
  [Serial](#serial) and [Camera](#camera).

## How this guide works

This whole guide is one Markdown file, rendered two ways:

- **On GitHub**, browsing straight to `docs/guide/GUIDE.md`.
- **In the app**, through the help viewer (`F1`, or Help → User Guide),
  which opens this file and jumps straight to the section for whatever
  screen you're on — like [Settings → Serial](#serial).

## Sort dashboard

The Sort activity (the sidebar's top button) is where sorting actually
happens. It combines the current case, the slot layout, and the run
controls on one screen instead of spreading them across tabs.

<!-- screenshot: Sort dashboard — cropped-headstamp panel beside the slot-card grid, action row above -->

### The current case

The left-hand panel shows the **last captured and cropped headstamp** —
exactly the image the classifier was given — with what it made of it
underneath: the headstamp it matched and how confident it was. A confidence
below the confidence floor is highlighted, and that case goes to the
Catch-All. Only the current case is shown here; the running history lives in
the classification history panel (View → Classification History).

**Show live camera** above the panel adds the live camera feed as a smaller
second panel below the crop. It is off by default — the feed is a setup aid,
not what an operator watches during a run — and while it is off no frames are
read at all. Use [Settings → Camera](#camera) to pick or aim a device.

### Slot cards

Each physical bin gets a card, arranged in a grid, plus one **Catch-All**
card for anything unclassified, below the confidence floor, or not routed
to a slot. A card shows:

- the slot number (or "Catch-All")
- how many cases have landed there this run
- every headstamp currently routed to it, listed in full — the card grows
  to fit the list rather than truncating it

### Editing an assignment

Click any card except Catch-All to open its assignment editor. Tick a
headstamp to route it to that slot; unticking sends it back to the
Catch-All. Outside of [package mode](#package-mode) a headstamp can only be
assigned to one slot at a time — ticking it here moves it off whichever slot
it was in before, and a filter box narrows a long headstamp list by name.

### Sorting templates

The right-hand end of the run-controls row holds the active **sorting
template** — a named snapshot of the whole slot layout, so one model can
carry several bin arrangements ("Range brass" vs. "Match prep") and switch
between them from the dropdown. **+** creates one (optionally copied from the
current layout); **✎** renames or deletes the active one. Switching templates
replaces every slot assignment at once, so it's blocked while a run is in
progress — stop first.

### Start, Stop, and Manual feed

- **Start** begins the continuous sort loop: capture, classify, sort,
  repeat. It is one button: while the loop runs it reads **Stop**, in red.
- **Stop** ends it — case counts are kept, not reset, so an operator can
  clear a jam and pick back up mid-tray.
- **Manual feed** runs exactly one cycle without starting the loop, useful
  for testing a single case.

Starting (or a manual feed) is refused, with a status message explaining
why, if the board isn't connected, the AI Config endpoint isn't set up, the
active model's checkpoint is missing, or PyTorch isn't installed yet for a
local model.

### Package mode

Toggling **Package mode** switches the grid to batch counting: each slot
gets a target batch size, shown as "count / target" on its card. A slot
that reaches its target stops taking that headstamp; once every slot for a
given headstamp is full, the run halts and asks you to empty bins and reset
counters. Any card's **⟲ Reset** button empties just that bin's counter
without stopping the run, so it can keep filling.

## Settings

The Settings activity groups everything you configure once and rarely
touch again — connections and calibration — behind a single section list.

### Serial

Connects the Qt UI to the sorting machine over the board's UART protocol.

- **Port** — pick a detected serial port, or **Emulated** to run against the
  built-in board emulator with no hardware attached.
- **Baud** and **probe timeout** — connection parameters; the defaults match
  the firmware.
- **Connect** / **Disconnect** open or close the link; the status bar's
  serial indicator mirrors the result.
- **Initialize these settings on startup** pushes the board init settings
  below automatically on every connect (auto or manual), instead of only
  when you press "Push to board".

Further down, **Board init settings** covers the machine's tunables — feed
and sort speed, homing offsets, motor current, debounce timing, and the
camera LED level — with **Get config from board** / **Push to board** to
read or write them, and a **Sort arm** group to jog the arm to a slot
(`sortto:<n>`) or home it, for testing wiring before a real run.

**Airdrop configuration** holds the three timing values (pre-drop delay,
signal duration, post-drop delay) for boards fitted with an airdrop
mechanism.

### Camera

Picks which camera the Sort dashboard's preview and the classifier both
read from.

- **Detect / Refresh** probes attached cameras (opens each one briefly to
  read its supported resolutions) and fills the **Camera** and
  **Resolution** dropdowns.
- **Apply** swaps the live camera to the selected device and resolution —
  the preview beneath updates immediately, so a bad pick is obvious before
  you leave the page.

The current device and resolution are shown beneath the controls so you can
confirm what's live without reopening this page.
