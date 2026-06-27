# OSS Client — Architecture & Handoff

This document captures the design, conventions, and quirks of the Case Sorter
OSS Client so a fresh contributor (human or AI) can keep working without
re-discovering everything by reading source and bug history.

> The companion `Readme.md` is the original product spec. This file is the
> implementation reference.

---

## 1. Purpose & scope

The OSS Client is a cross-platform (Windows / Linux) desktop client that
exercises the **minimum** functionality of the C# Case Sorter application:

1. Connect to an OpenAI-compatible classification server.
2. Drive a Case Sorter control board over USB serial.
3. Capture frames from a webcam, crop the brass headstamp out, optionally
   mask the primer, and send the result to the server.
4. Route classified cases to physical slots on the sort arm.

### Explicitly out of scope (R1)

- Multi-rotation / multi-image run modes (`Single Image Highest Confidence`
  is the only run mode).
- Parent / child headstamp classification.
- Image history / re-classification viewer.
- Feedback-image upload to the model owner (Azure SAS flow in
  `ServerChanges.md`).
- Community model browser.
- Packaging / installers.

The line-scan crop strategy is implemented but **hidden in the UI** — see
§7.4.

---

## 2. Repository layout

```
OSSClient/
  main.py                       entrypoint
  pyproject.toml
  requirements.txt              runtime deps (pygrabber is Windows-only)
  start.bat                     Windows launcher (system Python + venv)
  start.sh                      Linux launcher
  data/config.json              persisted settings (created on first save)
  sorter/
    __init__.py
    config.py                   load/save JSON; DEFAULT_*_SETTINGS
    api_client.py               classify() + get_headstamps()
    serial_broker.py            pyserial wrapper, threads, helpers
    serial_emulator.py          in-process fake broker
    camera.py                   cv2.VideoCapture wrapper + name probe
    image_proc.py               Hough + (dormant) line-scan crop, primer mask
    run_controller.py           continuous-run state machine + test_once
    events.py                   thread-safe pub/sub EventBus
    ui/
      app.py                    MainWindow shell + auto-connect + worker pump
      widgets.py                NumericField, ImagePanel, build_button_row
      tab_run.py                Run tab (slot grid + run controls + details)
      tab_ai.py                 AI Config + headstamp list + integrated Test
      tab_imageproc.py          Hough config + primer + LED slider
      tab_serial.py             port/baud + Sort arm + init-settings
      tab_camera.py             camera + resolution dropdowns + preview
  tests/
    conftest.py
    sample_images/
    test_api_client.py
    test_config.py
    test_image_proc.py
    test_run_controller.py
    test_serial_emulator.py
```

---

## 3. Tech stack & dependencies

- **Python 3.10+**. Type hints throughout; `__future__` import where needed.
- `tkinter` + `tkinter.ttk` for the UI. **Tkinter ships with CPython** on
  Windows and macOS; on Debian/Ubuntu it's `apt install python3-tk`.
  `start.sh` checks and bails with a clear message if missing.
- `opencv-python` for camera + crop.
- `pyserial` for the control-board link.
- `Pillow` for converting cv2 BGR frames to Tk-displayable images.
- `requests` for HTTP.
- `numpy` (transitive via cv2).
- **Windows only**: `pygrabber>=0.2` (DirectShow camera-name enumeration).
  Declared with `; platform_system == "Windows"` in `requirements.txt`.

There is **no embedded Python distribution**. The earlier `python_e/`
folder was removed because the embeddable distribution lacks Tcl/Tk and
pip. Both launchers require a system Python (recommended: official
python.org installer, "Add Python to PATH" checked).

`start.sh` and `start.bat` both create a local `.venv`, install
`requirements.txt` once, then run `main.py`. A `.installed` sentinel file
skips reinstall on subsequent launches — delete it to force a refresh.

---

## 4. Top-level architecture

```
                 ┌───────────────────────────────────────────┐
                 │              MainWindow (Tk)              │
                 │  ┌─────────┐  ┌────────┐  ┌───────────┐   │
                 │  │ EventBus│  │ Camera │  │  broker   │   │
                 │  │ (Queue) │  │ (CV2)  │  │ Serial or │   │
                 │  └────┬────┘  └───┬────┘  │ Emulator  │   │
                 │       │           │       └─────┬─────┘   │
                 │   drain every     │             │         │
                 │   50 ms on        │             │         │
                 │   Tk thread       │             │         │
                 └───────┼───────────┼─────────────┼─────────┘
                         ▼           ▼             ▼
                  ┌──────────────────────────────────────────┐
                  │              RunController               │
                  │  start()/stop()/test_once()/run_once()   │
                  └──────────────────────────────────────────┘
```

### Threading model

- Tk main thread runs the UI and drains the bus.
- One **camera grab thread** keeps the latest BGR frame in a single slot.
- One **serial reader thread** + **serial ping thread** in `SerialBroker`.
- The continuous run loop runs in its own thread (`RunController._loop`).
- Every other long task (Detect cameras, push init settings, classify,
  manual feed) goes through `MainWindow.run_worker(fn, on_done=, on_error=)`,
  which spawns a daemon thread and posts `worker/done/<id>` /
  `worker/err/<id>` events.

### The event bus contract

`sorter/events.py` — a `queue.Queue` plus a topic → handler-list dict.

- Worker threads call `bus.post(topic, payload)`.
- Tk main thread calls `bus.drain()` from `root.after(50, …)`. Handlers run
  on the Tk thread, so they may safely touch widgets.
- Subscriptions are append-only by design; tabs hold their handler
  references for the lifetime of the window.

**Standard topics:**

| Topic                | Payload              | Producer       | Consumer            |
|----------------------|----------------------|----------------|---------------------|
| `status`             | `str`                | many           | `MainWindow.set_status` (status bar) |
| `serial/rx`          | `str`                | broker         | Serial Config monitor log |
| `serial/tx`          | `str`                | broker         | Serial Config monitor log |
| `run/started`        | `None`               | RunController  | RunTab (toggle Start↔Stop) |
| `run/stopped`        | `None`               | RunController  | RunTab |
| `run/error`          | `str`                | RunController  | RunTab |
| `run/status`         | `str`                | RunController  | RunTab → status bar |
| `run/cropped`        | `np.ndarray` 480×480 | RunController  | RunTab (last cropped) |
| `run/classified`     | dict label/conf/slot | RunController  | RunTab (result rows) |
| `run/result`         | full result dict     | RunController  | RunTab (counters) |
| `test/status`        | `str`                | RunController.test_once | AiTab |
| `test/cropped`       | `np.ndarray`         | RunController.test_once | AiTab |
| `test/classified`    | dict                 | RunController.test_once | AiTab |
| `test/error`         | `str`                | RunController.test_once | AiTab |

`run/*` and `test/*` are intentionally separate so the single-shot Test
controls on the AI tab don't fire when a continuous run is in progress.

---

## 5. Configuration

A single `data/config.json` file owned by `sorter.config.Config`. The
`Config.load()` merges saved values over `DEFAULTS` — unknown keys are
preserved on save, missing keys fall back to defaults.

### Top-level schema

```jsonc
{
  "api": {
    "endpoint_url":     "http://localhost:8000",
    "api_key":          "nokey",
    "model":            "9mm",
    "prompt":           "Not used for local AI Server",
    "image_quality":    100,
    "image_scale":      100
  },
  "headstamps": [
    { "name": "WIN", "slot": 3 },           // slot 0 = catch-all (unassigned)
    { "name": "FC",  "slot": 0 }
  ],
  "serial": {
    "port":                "",
    "baud":                9600,
    "slot_quantity":       8,               // TOTAL slots including slot 0
    "handshake_timeout_s": 4.0,             // per-port probe timeout
    "init_on_startup":     false,           // auto-push init_settings after connect
    "init_settings": { /* see §6 */ }
  },
  "image_proc": {
    "strategy":      "hough",               // always "hough" in the UI; "linescan" dormant
    "primer_mode":   "hide",                // "none" | "use" | "hide"
    "primer_radius": 135,
    "hough":    { "dp": 2.0, "min_dist": 500, "param1": 100,
                  "param2": 60, "min_radius": 150, "max_radius": 250 },
    "linescan": { "scan_precision": 1, "scan_sensitivity": 5.0,
                  "padding_pct": 5, "bg_cliff": 0 }
  },
  "camera": {
    "device_index":  0,
    "device_chosen": false,                 // true once user clicks Apply on Camera tab
    "width":         640,
    "height":        480
  }
}
```

Notable behaviors:

- `headstamps` is **always a list of dicts**, never a list of strings, even
  though the AI Config tab only shows names. The `slot` field is managed by
  the Run tab. Slot `0` means *unassigned* — anything routed there lands in
  the catch-all bin.
- `serial.slot_quantity` is the TOTAL slot count **including the catch-all
  at index 0**, so `8` means physical slots 0..7. The Run tab uses
  `range(0, slot_quantity)` to build cards.
- `camera.device_chosen` distinguishes "user has saved a preference" from
  "default 0". Without it the Camera tab would always prefer the saved
  index over the Webcam heuristic.

`Config.slot_for_headstamp(name)` returns the slot for the given headstamp
name, or `None` if not registered. RunController falls through to slot 0 in
either of those cases.

---

## 6. Wire protocol (control board)

Every command is sent as ASCII followed by `\n`. The reader thread strips
`\r\n\t ` and pattern-matches the lower-cased line.

### Commands sent

| Helper                              | Wire                | When                                            |
|-------------------------------------|---------------------|-------------------------------------------------|
| `feed_one()`                        | `xf:0`              | Prime the very first case in `_loop` and the AI tab's Feed button |
| `force_sort_and_move(slot)`         | `xf:<slot>`         | (unused by R1) |
| `sort_and_move(slot)`               | `<slot>` (bare int) | End of every run cycle — drops current case AND advances the next |
| `move_sorter_to_slot(slot)`         | `sortto:<slot>`     | Serial Config "Sort to" spinbox + Home Sorter button |
| `stop_run()`                        | `stop`              | Run tab Stop button |
| `use_feed_sensor(bool)`             | `usefeedsensor:0/1` | Available via debug entry; UI checkbox removed |
| `get_config()`                      | `getconfig`         | Serial Config "Get config from board" |
| `update_init_settings(dict)`        | `key:value` per line | Serial Config Push, init-on-startup, LED slider |

### Responses dispatched

| Substring (case-insensitive) | Fires        |
|------------------------------|--------------|
| `done`                       | `on_done`    |
| `ok`                         | `on_ok`      |
| `error`                      | `on_error`   |
| `waiting`                    | `on_waiting` |
| anything else (non-empty)    | `on_response`|

`on_received` always fires before the dispatch. Substring matches mirror
the C# behavior — firmware messages containing "done"/"ok"/"error" as
substrings will fire those events. Don't tighten this.

### The CRITICAL feed/sort interaction

The firmware's `sort_and_move(N)` command does TWO things:

1. Move the sorter to slot N and drop the current case.
2. Advance the **next** case into the imaging area.
3. Send `done` (when both are complete).

This is why the C# `ProcessOne` (MainForm_Run.cs:272-281) is just
`sortAndMove → CaptureAnImage` per cycle — there's no separate feed.
The OSS client mirrors this: the run loop primes once with `xf:0`, then
every cycle is `capture → classify → sort_and_move`. Calling `feed_one`
inside `run_once` (the earlier bug) caused a "double feed" where the
hopper queued a second case every iteration.

### Handshake

`SerialBroker.try_open`:
1. Open the port at 9600 8N1, DTR=True (this **resets the Arduino**).
2. `readline()` for up to `handshake_timeout_s` — board's boot banner.
3. `read_all()` — drain anything else.
4. Write `version\n`.
5. `readline()` for the firmware version string.
6. Connected if version contains `ok` or `7.`, OR banner contains `Ready`
   (or `require_serial_ready=False`).

Boot takes ~2-3 s after the DTR pulse. **`handshake_timeout_s` must be at
least 4 s** for reliable auto-connect on an Arduino-based board. This is
the configurable "Probe timeout" field in Serial Config.

### Ping loop

If no command is sent and nothing is received for >2 s, the broker sends
`ping` every 1 s to keep the connection considered live.

---

## 7. Image processing

### 7.1 Pipeline

```
camera frame (BGR, any size)
    │
    ▼  hough_detect()  — Gaussian blur (9×9), HoughCircles
    │
    ▼  pick LARGEST circle in [min_radius, max_radius]
    │
    ▼  _clip_to_circle()  — pad by 5%, paste circular ROI on 480×480 black
    │
    ▼  apply_primer_mask(mode, radius)
    │   - "use"  → re-clip to inner circle at (240,240)
    │   - "hide" → draw filled black circle at (240,240)
    │   - "none" → pass-through
    ▼
final 480×480 BGR (always; output contract)
```

### 7.2 Why "largest" not "highest accumulator vote"

`cv2.HoughCircles` returns circles sorted by accumulator votes. For brass
case headstamps, the **primer's inner edge often outvotes the case rim**
because its local contrast is higher. We pick the largest circle in the
configured radius range instead — the primer is always smaller than the
case, so this consistently selects the brass rim.

`overlay_detection()` draws the picked circle on the source frame so the
operator can see what got selected while tuning. Used by the
**Capture Image** button in the Image Processing tab.

### 7.3 The Hough parameters in operator language

| Field (UI label)               | cv2 name      | Effect |
|--------------------------------|---------------|--------|
| Accumulator scale (dp)         | `dp`          | Higher = faster + tolerant, lower precision |
| Min center separation (px)     | `minDist`     | One-case-per-frame: set to ~image width |
| Edge strength (param1)         | `param1`      | Canny high threshold |
| Detection threshold (param2)   | `param2`      | Accumulator vote threshold |
| Min case radius (px)           | `minRadius`   | Absolute pixels — depends on camera res + distance |
| Max case radius (px)           | `maxRadius`   | Same |

Operator-confirmed defaults (`config.py`):

```
dp=2.0, min_dist=500, param1=100, param2=60, min_radius=150, max_radius=250
primer_mode="hide", primer_radius=135
```

### 7.4 The dormant line-scan strategy

`linescan_crop()` is a numpy port of the C# `ScanImageHalves` algorithm
(SJS_ImageProcessing.cs:835-1017). It works but is hidden in the UI per
operator request. To bring it back: restore the strategy radio + line-scan
LabelFrame in `tab_imageproc.py`, and uncomment the dispatch in
`crop_headstamp()`:

```python
# strategy = (config.get("strategy") or "hough").lower()
# if strategy == "linescan":
#     return linescan_crop(frame_bgr, LineScanParams.from_dict(config.get("linescan", {})))
return hough_crop(...)
```

The line-scan-specific config (`bg_cliff`, `padding_pct`, etc.) is still
persisted, so dormant data round-trips through Save.

---

## 8. Camera handling

### 8.1 Enumeration

- **Linux**: `/sys/class/video4linux/videoN/name` for friendly names.
- **Windows**: `pygrabber.dshow_graph.FilterGraph().get_input_devices()`.
- **macOS / fallback**: `Camera N` (no friendly name).

`camera_names()` is the fast path — no devices are opened, just OS-level
metadata. The `CameraTab.__init__` uses this to populate the dropdown
immediately on startup without disrupting the running preview.

`list_cameras_with_metadata()` is the full probe — opens each device,
calls `cap.read()` once, then tries every resolution in
`COMMON_RESOLUTIONS` (320×240 through 4K) and collects whatever the
driver actually returned. **Cannot run while the preview is using the
camera** (DirectShow won't allow a second open), so the Detect button
stops the live camera before probing and restarts it afterwards.

### 8.2 Default device selection

`_pick_default_camera`:

1. If `device_chosen=True` and the saved index is still present → use it.
2. Else if any detected device's name contains `webcam`
   (case-insensitive) → use it.
3. Else first detected.

### 8.3 Default resolution

`_probe_resolutions` returns supported sizes sorted by pixel count, so
`resolutions[-1]` is the highest. If the saved (`width`, `height`) is in
the list for the saved device, use it; otherwise default to the highest.

### 8.4 Preview thread

`Camera._grab_loop` reads frames at ~95 fps into a single-slot
`_latest_frame` under a lock. `capture_frame()` returns the latest grabbed
frame; if no preview thread is running it opens the device inline and
retries `cap.read()` up to 3× with 50 ms gaps.

`MainWindow._refresh_preview` runs at 20 fps via `root.after`, painting
the same frame into both `RunTab` and `CameraTab`'s previews.

---

## 9. API client

`sorter/api_client.py` uses a module-level `requests.Session()`. The
session pools TCP/TLS connections per host, so back-to-back classify
calls to the same endpoint skip the 100-500 ms handshake cost — important
for the continuous run loop.

### 9.1 classify()

`classify(image_bgr, headstamps, cfg) -> (label, confidence_pct)`

1. Resize the BGR frame by `image_scale` (`cv2.resize`, `INTER_AREA`).
2. JPEG-encode at `image_quality`.
3. Base64 + `data:image/jpeg;base64,` URI.
4. Build the prompt by replacing `{{headstamps}}` with `\n`-joined names.
5. POST to `{endpoint}/v1/chat/completions` with `Authorization: Bearer
   {api_key}`. Body shape is OpenAI-compatible (single user message with
   text + image_url content blocks; `temperature: 0`).
6. Extract `choices[0].message.content` as the label, strip surrounding
   quotes.
7. **Read `payload.confidence`** (a float 0-1 from the SJS server). If
   present, return `confidence * 100.0` as a float. If missing or
   unparseable, return `-1.0` to make it obvious in the UI that the
   server didn't supply one.

Confidence is **not** used for slot routing — the confidence floor was
removed. Unknown labels just go to slot 0.

### 9.2 get_headstamps()

`GET {endpoint}/getheadstamps?model={model}` → list of strings. Used by
the AI Config tab's "Load from server" button. Mirrors `AIConfig.cs:424`.

---

## 10. Run controller

`RunController` lives on `MainWindow` and is rebuilt by `_rebuild_run_controller`
every time a serial connection is established (auto-connect or manual).

### 10.1 test_once()

Single-shot used by the AI Config tab's Feed button:

```
feed_one → capture → crop → primer_mask → classify
```

Posts `test/status`, `test/cropped`, `test/classified` along the way so
the cropped image renders before the HTTP call returns. No sort.

### 10.2 run_once() — continuous cycle iteration

```
capture → crop → primer_mask → classify → look-up slot → sort_and_move
```

**Does NOT call `feed_one`.** The prior `sort_and_move` advanced the next
case. Posts `run/status`, `run/cropped`, `run/classified` along the way,
then `run/result` from `_loop` once the sort completes.

### 10.3 _loop()

```python
broker.feed_one()                # prime the first case (xf:0)
while not self._stop_event.is_set():
    result = self.run_once()
    bus.post("run/result", result)
    if result.error: break
    stop_event.wait(0.05)        # small UI breath
```

Stops on any error or when the user clicks Stop.

---

## 11. Tab-by-tab tour

### Run (first tab)

Top half is a 2-column `grid` layout:

- **Column 0** (slot grid): `weight=1`, `minsize=CARD_WIDTH+24` (=264 px).
  This is the elastic column — it eats slack space and collapses down to a
  single column of slot cards before the right side starts to shrink.
- **Column 1** (run controls): `weight=0`, `minsize=320` so it always has
  enough room for long classification strings.

`SlotGrid` (alias of `FlowGrid`) is a custom flow-layout container — on
`<Configure>` it computes `cols = width // (cell_width + gutter)` and
re-grids its children. Used for both slot cards (`expand_cells=True`,
cards stretch to fill columns) and the headstamp checkbox cells in the
details panel (`expand_cells=False`, left-aligned).

`SlotCard` shows: `Slot #N` (or "Catch-All"), CSV of assigned headstamps,
session count. Clicking anywhere on the card selects it.

`SlotDetailsPanel` is the bottom half:
- Slot 0 = Catch-All. Every checkbox is `state="disabled"`.
- Other slots show every headstamp as a `HeadstampCell` in the flow grid.
  Already assigned elsewhere → greyed out + `in slot #M` hint. Available
  → toggleable. Each cell has a per-(slot, headstamp) session counter
  rendered as `(N)`.

The Run controls (right column): Start/Stop toggle, Manual feed (xf:0),
Master counter with Reset, last cropped 200×200 panel, three left-aligned
bold result rows (label, confidence, destination).

### AI Config

Split layout — top split into config (left) and headstamps (right);
bottom is the integrated Test panel.

- Server group: endpoint URL, API key (Entry `show="*"`), model.
- Prompt: multi-line `Text` widget. `{{headstamps}}` is replaced at
  request time with the newline-joined list.
- Image encoding: JPEG quality + scale spinboxes (default 100/100).
- Headstamp list manager:
  - "New" entry + Add button (Enter submits).
  - "Load from server".
  - Scrollable Listbox (alphabetical, case-insensitive). Delete key on a
    selection removes it.
  - Side panel: Remove selected, Clear all (with confirm), live count.
  - Edits auto-save; server/prompt/image fields require Save.
- Test panel: live preview (left), last cropped (middle), Feed button +
  bold label/confidence (right). Subscribes to `test/*` topics; uses
  `RunController.test_once`.

### Image Processing

- **Configuration** (Hough params): six spinboxes, labels include the
  cv2 parameter name in parens.
- **Primer mask**: None / Keep primer area only / Hide primer + radius
  spinbox.
- **Camera LED brightness**: horizontal `ttk.Scale` (1-255). 500 ms
  debounce via `tk.after` — every value change cancels the pending
  callback and reschedules. On fire: persists into
  `init_settings.cameraledlevel`, sends `cameraledlevel:N`, then
  schedules `test_on_frame()` 200 ms later to refresh the preview with
  the new lighting.
- **Save** / **Capture Image** buttons. Capture Image:
  - Saves the current Hough config.
  - Runs `hough_detect()` + `overlay_detection()` to show the picked
    circle in red with a yellow crosshair on the left preview.
  - Runs the full crop + primer mask on the right preview.
  - Status bar shows `Detected circle: r=180 px at (320, 240)`.

### Serial Config

- **Connection** box: port combobox + Refresh ports (always appends
  `"Emulated"` for the in-process fake), baud spinbox, **Probe timeout
  (s)** spinbox, Initialize-on-startup checkbox, Connect / Disconnect /
  Get config / Push to board / Save.
- **Sort arm** box: Slot count (drives Run tab grid), Sort slot steps
  (mirrors `init_settings.sortsteps`), **Sort to slot** spinbox with a
  `trace_add("write", …)` handler that fires `move_sorter_to_slot(N)`
  on every change (initial synthetic write is suppressed), **Home
  sorter** button → `sortto:0`.
- **Board init settings**: ~15 NumericFields in a 3-column grid, each
  bound to a wire-protocol key. `Sort slot steps` is intentionally NOT
  here — it lives only in the Sort arm box (`_apply_board_config` has a
  small carve-out so a `sortsteps` value from `getconfig` still routes to
  the Sort arm spinbox).
- **Airdrop**: enabled checkbox + 3 numeric fields.
- **Serial monitor / debug**: command Entry (Enter submits), Send button,
  scrolling 10-line `tk.Text` log driven by `serial/rx` and `serial/tx`
  events. Auto-trimmed to ~500 lines.

#### Init settings the operator tuned

```
feedhomingoffset 0    sorthomingoffset 0
feedspeed 90          sortspeed 90
feedsteps 70          sortsteps 20
slotdropdelay 300     notificationdelay 160
automotorstandbytimeout 0
feedmotorcurrent 900  sortmotorcurrent 900
fan 100               cameraledlevel 130
debounceTimeout 500   debounceTime 300
airdropenabled 0      airdroppredelay 50
airdropdsignalduration 70   airdroppostdelay 50
```

### Camera

- Camera dropdown shows `(idx) Friendly Name`. Populated immediately on
  startup from `camera_names()` (fast, no device opens).
- Resolution dropdown shows the saved size; full supported list appears
  after Detect.
- Buttons: Detect (pauses preview, runs full probe, restarts preview),
  Apply / Start preview (commits selection; sets `device_chosen=True`),
  Stop preview.
- Selecting a camera from the dropdown also restarts the preview against
  that device (no probe required — keeps the saved resolution).

---

## 12. Defaults & key constants

```python
# api defaults
endpoint_url = "http://localhost:8000"
api_key      = "nokey"
model        = "9mm"
prompt       = "Not used for local AI Server"

# serial
baud = 9600
slot_quantity = 8
handshake_timeout_s = 4.0
HANDSHAKE_READ_TIMEOUT_S = 4.0   # serial_broker constant; UI overrides per-config
DISCOVERY_HANDSHAKE_TIMEOUT_S = 1.5  # legacy; auto-connect now uses config value
PING_INTERVAL_S = 1.0
PING_IDLE_THRESHOLD_S = 2.0
FEED_TIMEOUT_S = 2.0
FORCE_FEED_TIMEOUT_S = 3.0
SORT_TIMEOUT_S = 20.0
READ_TIMEOUT_S = 0.5   # reader thread loop interval

# image processing
OUTPUT_SIZE = 480
COMMON_RESOLUTIONS = [...10 entries from 320x240 up to 3840x2160...]

# UI
PREVIEW_FPS = 20
CARD_WIDTH = 240
HEADSTAMP_CELL_WIDTH = 200
```

---

## 13. Known quirks & gotchas

- **DTR reset**: opening a USB-serial port to an Arduino asserts DTR which
  hardware-resets the board. The handshake must wait through the boot
  (`Ready` banner appears 2-3 s after open). Don't lower
  `handshake_timeout_s` below 4 s unless you've changed the bootloader.
- **`sort_and_move(N)` feeds the next case** — do not call `feed_one`
  inside `run_once`. Prime once at the start of `_loop` only.
- **DirectShow second-open fails**: the Detect button must stop the live
  preview before probing resolutions or the values come back as 0.
- **`self.after` is a `tk.Widget` method**. Don't shadow it. The image
  panels on the IP tab are deliberately named `before_panel` /
  `after_panel` — there's a comment in `tab_imageproc.py` to that effect.
- **`ttk.Scale.set()` fires the `command=` callback synchronously**. Any
  state the callback touches must exist before you call `.set(initial)`
  (the LED slider had a one-line bug from this).
- **Camera names on Windows require pygrabber**. Conditional dep:
  `pygrabber>=0.2; platform_system == "Windows"`.
- **Embeddable Python doesn't ship Tcl/Tk OR pip** — that's why the
  bundled `python_e/` was removed. Operators install Python 3.10+ from
  python.org with the "Add to PATH" option.
- **Run worker subscriptions leak** — `run_worker` calls
  `bus.subscribe(topic, handler)` once per call (topic key = `id(fn)`).
  Handler references stay in the bus map until the window closes. Fine
  for R1 given the volume of calls; revisit if it ever becomes an issue.
- **Substring response matching is intentional** — `done` matches `redone`.
  Mirrors C# behavior so firmware messages that contain trigger words as
  substrings keep firing events. Don't tighten it.
- **`use_feed_sensor` checkbox is gone but the broker method stays** —
  the operator can still send `usefeedsensor:0` or `usefeedsensor:1` via
  the Serial Config debug entry if they need to toggle it at runtime.
- **`use_legacy_comms` removed entirely** from the broker — the reader
  loop now only has the `readline()` path. If you ever need byte-mode
  reading back, see history before the cleanup.
- **`linescan_crop` looks dormant but its config still round-trips**.
  Don't strip the LineScanParams class or `linescan_crop` — the dispatch
  in `crop_headstamp` is the only thing commented out.

---

## 14. Confidence values

The SJS server returns a non-standard top-level `confidence` field
(0..1). When it's missing — e.g. plain OpenAI — `classify` returns
**-1.0** as a flag value. The UI prints it via `:.2f%` so the user sees
`-1.00%`. Slot routing ignores confidence entirely; unknown labels just
fall through to slot 0.

---

## 15. Testing

```
cd OSSClient
.venv/bin/python -m pytest tests/ -q
```

32 tests as of the latest commit. All headless / no hardware required.

Covers:

- `image_proc`: both crop strategies produce 480×480 BGR; primer mask
  modes; "pick largest circle" property when primer + brass both
  detected; overlay sanity.
- `api_client`: request URL/headers/body shape; `{{headstamps}}` rendering;
  server-confidence parsing (success / missing → -1 / unparseable → -1);
  HTTP errors raise `ApiError`.
- `config`: round-trip; default merging for partial files; corrupt JSON
  falls back to defaults; `slot_for_headstamp` lookup.
- `serial_emulator`: `feed_one`, `sort_and_move`, `get_config` work; every
  command fires `on_sent`; `update_init_settings` pushes per-key.
- `run_controller`: `run_once` routes known labels to assigned slots and
  unknown labels to slot 0; `test_once` does not call `sort_and_move`.

Manual / hardware-only smoke checks (operator's job — see
`OSSClient/Readme.md` for the spec):

- Camera enumerate / preview / snapshot on the target box.
- Live serial against a real board: handshake; `getconfig` returns JSON;
  init-settings round-trip; a full feed→sort cycle finishes in budget.
- End-to-end classify against the production server.
- Full continuous run with brass and watch the counters tick on the
  right card.

---

## 16. What's next (out of R1 scope)

- **Run modes beyond Single Image**. The C# version has Multi-Image
  Highest Confidence, Highest Average, Popular Highest Average. Hook
  point: extend `RunController._loop` to accumulate rotations + scores
  before sort.
- **Parent / child headstamp classification**. Needs a second list in
  config and a different `slot_for_headstamp` lookup.
- **Feedback image upload**. `ServerChanges.md` defines two endpoints
  (`/api/Models/FeedbackImageUploadRequest`, `/api/Models/CompleteFeedbackUpload`).
  Would add an Azure Blob client dep.
- **Packaging / installers**. Out of scope per the original Readme.

If you bring the line-scan UI back, follow the comments in
`crop_headstamp` and `tab_imageproc.py`.

---

## 16b. Run-screen parity features

These four Run/Train features and the community publish flow were added to
match the WinForms app. All settings live in the key/value `settings` table
via `Config`; routing lives in `RunController`.

### Package Mode (batch sorting)

- `Config.run_package_mode` / `run_package_size` plus a per-(active-context)
  **package slot map** (`package_slots:<model_id|ai>` → `{slot: [names]}`).
  Unlike single-slot routing this is **many-to-many** — a headstamp may be
  ticked into several slots (mirrors the separate `PackageMode` SlotConfig list
  in WinForms). API: `package_slot_map`, `slots_for_headstamp_package`,
  `set_package_slot_headstamp`, `headstamps_in_package_slot`.
- Run tab: a **Package Mode** checkbox reveals a **Batch size** spinbox; each
  non-catch-all `SlotCard` grows a live **Reset count** button; the
  `SlotDetailsPanel` switches to a flat, multi-assign checkbox grid
  (`_build_package_mode`).
- `RunController._route_slot_package` fills the fullest non-full slot for the
  label; `_commit_package_count` tallies after the sort and posts
  `run/package_full` (UI rings `root.bell()`) when a batch completes. When every
  slot for a headstamp is full, `run_once` returns `halt=True`, `_loop` posts
  `run/package_halt`, and the run stops. Counts are owned by the controller
  (`_package_counts` under a lock) so the UI reset button is thread-safe.
  `start()` does **not** reset the counters — a stopped-then-restarted run
  resumes its batches; only Reset counters / a per-slot reset clears them.

### Automatically Select Trays

- `Config.run_auto_select_trays`; `first_empty_slot` /
  `assign_headstamp_to_empty_slot`. **Empty-slot detection is scoped to the
  active mode**: child mode counts only per-headstamp slots, parent mode counts
  parent + orphan slots, package mode counts only the package map. A slot used
  by a *different* mode's config never blocks an auto-assignment in the current
  mode.
- `RunController._maybe_auto_select` runs inside `_resolve_destination` for any
  above-floor, unmapped headstamp and posts `run/assignment_changed` so the Run
  tab re-renders. Respects existing assignments; one headstamp per empty slot.

### Monitor (image history)

- `ui/monitor.py` — a separate `Toplevel` opened from the Run tab. Fixed-position
  ring buffer sized to the window (top→bottom, left→right, wraps to top-left);
  the current tile has a **black** border and the trailing few fade dark-blue →
  white (`SNAKE_COLORS`); recomputes on resize. Fed by the `run/history` event
  that `RunController._post_history` posts each cycle. Unsubscribes on close.

### Sort While Training

- `Config.sort_while_training`. Train tab adds a checkbox; `_feed` sends
  `force_sort_and_move(slot)` for the selected label's run slot (xf:<slot>)
  instead of xf:0. Slot is resolved from the label combobox at feed time
  (Python classifies *after* the feed).

### Community — Share a Model

- `community_api`: `SasResponse` + `request_file_upload` / `upload_blob` /
  `complete_upload` / `request_manifest_upload` / `upload_manifest`, and
  `share_model()` which runs the exact WinForms order: FileUploadRequest → PUT
  zip → CompleteUpload → ManifestUploadRequest → **PUT the manifest by itself**.
  No `azure-storage-blob` dep — the SAS blob PUT mirrors the feedback upload.
  `request_file_upload` raises `CommunityApiError` carrying the server's status
  + body so a refusal surfaces a real reason. **`ModelExportMode` is sent as the
  integer the WinForms Newtonsoft client emits** (ModelOnly=0, ModelAndImages=1,
  ImagesOnly=2) — a string fails to bind on the System.Text.Json endpoint.
  `upload_blob` PUTs a `_ProgressReader` (a file-like with `__len__`) rather than
  a generator, so `requests` sets a Content-Length and never uses chunked
  encoding — Azure Put-Blob rejects chunked bodies by dropping the TLS
  connection (the SSL-EOF on share). Transient SSL/connection drops retry with
  backoff.
- `model_io.export_for_share` builds the ZIP and stamps the community fields
  (`CommunityModelUID`, feedback enable/floor, `FeedbackLoopUploadMode=Instant`)
  into the manifest; `write_manifest_sidecar` extracts `manifest.json` back out
  to a `<uid>.manifest.json` for the standalone upload.
- `ui/dialog_share_model.ShareModelDialog` collects the metadata and drives the
  export+upload on a worker, then stamps the returned UID/version onto the local
  model. The Community tab's **Share a Model** button (Contribute role only)
  opens it. The community UID is a standard dashed GUID (`str(uuid4())`) and the
  export ZIP is built under `paths.export_temp_dir()` (`<app>/data/tmp`), not the
  OS temp dir — the latter raised a WinError 267 on Windows.

---

## 17. Branch / commit notes

Development happened on `claude/nice-cannon-sn86kv` against
`sjseth/sjseth.casesorter`. Notable architectural commits worth
re-reading if you need history context:

- "Add cross-platform Python OSS client …" — the initial drop.
- "Fix double-feed in run loop; slot details flow with alpha-sorted
  headstamps" — the prime-once + sort-feeds-next correction.
- "Camera: split fast name probe from full Detect" — explains why Detect
  pauses preview.
- "Confidence: read server's top-level 'confidence' field; fall back to
  -1" — confidence semantics.
- "HoughCircles: pick largest circle, overlay detection on test preview"
  — the brass-vs-primer fix.
