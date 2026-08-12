# Sort dashboard

The Sort activity (the sidebar's top button) is where sorting actually
happens. It combines the live camera feed, the slot layout, and the run
controls on one screen instead of spreading them across tabs.

<!-- screenshot: Sort dashboard — camera preview beside the slot-card grid, action row above, recent-classification strip below -->

## Slot cards

Each physical bin gets a card, arranged in a grid, plus one **Catch-All**
card for anything unclassified, below the confidence floor, or not routed
to a slot. A card shows:

- the slot number (or "Catch-All")
- how many cases have landed there this run
- every headstamp currently routed to it, listed in full — the card grows
  to fit the list rather than truncating it

## Editing an assignment

Click any card except Catch-All to open its assignment editor. Tick a
headstamp to route it to that slot; unticking sends it back to the
Catch-All. Outside of [package mode](#package-mode) a headstamp can only be
assigned to one slot at a time — ticking it here moves it off whichever slot
it was in before, and a filter box narrows a long headstamp list by name.

## Sorting templates

The bar above the grid holds the active **sorting template** — a named
snapshot of the whole slot layout, so one model can carry several bin
arrangements ("Range brass" vs. "Match prep") and switch between them from
the dropdown. **+ New** creates one (optionally copied from the current
layout); **✎ Edit** renames or deletes the active one. Switching templates
replaces every slot assignment at once, so it's blocked while a run is in
progress — stop first.

## Start, Stop, and Manual feed

- **Start** begins the continuous sort loop: capture, classify, sort,
  repeat.
- **Stop** ends it — case counts are kept, not reset, so an operator can
  clear a jam and pick back up mid-tray.
- **Manual feed** runs exactly one cycle without starting the loop, useful
  for testing a single case.

Starting (or a manual feed) is refused, with a status message explaining
why, if the board isn't connected, the AI Config endpoint isn't set up, the
active model's checkpoint is missing, or PyTorch isn't installed yet for a
local model.

## Package mode

Toggling **Package mode** switches the grid to batch counting: each slot
gets a target batch size, shown as "count / target" on its card. A slot
that reaches its target stops taking that headstamp; once every slot for a
given headstamp is full, the run halts and asks you to empty bins and reset
counters. Any card's **⟲ Reset** button empties just that bin's counter
without stopping the run, so it can keep filling.

---

See also: [Settings → Serial](settings.md#serial) to connect the board this
screen sorts through.
