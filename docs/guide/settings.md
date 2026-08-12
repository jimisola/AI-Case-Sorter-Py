# Settings

The Settings activity groups everything you configure once and rarely
touch again — connections and calibration — behind a single section list.

## Serial

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

## Camera

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

---

Back to [the guide](index.md).
