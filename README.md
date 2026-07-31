# AI Case Sorter

A cross-platform (Windows + Linux) desktop app that drives a machine which
**sorts spent brass cartridge casings by headstamp**. A camera photographs each
case, an image classifier predicts the headstamp stamped on its base, and a
serial-connected sorting machine drops the case into the correct bin.

This is the **full-parity Python/Tkinter version** of the original Windows-only
WinForms application, intended to eventually replace it. It runs fully offline —
signing in to the community is optional and only unlocks model sharing/downloads.

> ⚠️ **Scope & safety.** This software sorts inert, already-fired brass cases by
> their stamped markings. It is not a firearm, not a munition, and contains no
> load data. It also commands real motors and a drop mechanism over a serial
> link — moving machinery has pinch points and electrical hazards. Run it on
> hardware at your own risk and keep hands clear during operation. Provided
> **as-is, with no warranty** (see [LICENSE](LICENSE)).

<!-- TODO: add a screenshot or short GIF of the Run tab here. -->

---

## How the pieces fit together

The case sorter is built from a few separate repositories. **This repo is just
the desktop software.**

| Project | What it is | Link |
|---------|-----------|------|
| **AI Case Sorter (this repo)** | The cross-platform desktop app: capture, classify, route, train, evaluate. | — |
| **CS7.2 hardware** | 3D-printable models, build kits, assembly guides, and the Arduino-based firmware the app talks to over serial. | [AI-Case-Sorter-CS7.2](https://github.com/sjseth/AI-Case-Sorter-CS7.2) |
| **CaseSorter AI Server** | A small local HTTP server that hosts your trained ConvNeXt models behind an OpenAI-compatible API. This is what **AI Config mode** points at. | [AI-Case-Sorter-Server](https://github.com/sjseth/AI-Case-Sorter-Server) |
| **Community backend** | Hosted service at [reloadingrecipes.com](https://www.reloadingrecipes.com/HeadstampSorter) for sign-in, model sharing/downloads, and the feedback loop. A separate hosted service — **not** part of this open-source release. | [reloadingrecipes.com](https://www.reloadingrecipes.com/HeadstampSorter) |

You do **not** need an account to use the app. Everything except community
sharing/downloads works locally and offline.

---

## Two ways to classify

The app can predict a headstamp in one of two modes:

- **AI Config mode** *(no local model active)* — the cropped case image is sent
  to an **OpenAI-compatible HTTP server** (`POST /v1/chat/completions`). Point it
  at a local [CaseSorter AI Server](https://github.com/sjseth/AI-Case-Sorter-Server)
  (default `http://localhost:8000`) to run inference against your own trained
  models with no GPU drivers on the client.
- **Local model mode** *(a model is active)* — run a **PyTorch ConvNeXt** model
  directly on this machine. The model can be one you trained in the **Train** tab,
  one **downloaded from the community**, or one **imported from a ZIP** — running
  locally does not require you to have trained it yourself. PyTorch is an optional
  dependency installed on demand (see [Optional: PyTorch](#optional-pytorch)).

---

## Features

- **Run** tab — production sorting: live slot grid, per-headstamp counts,
  confidence floor, auto-select trays, and package/batch mode.
- **Models** tab — model library: create, activate, import/export (ZIP),
  evaluate, and manage training images.
- **Train** tab — feed → capture → classify → label → save, then launch a local
  ConvNeXt training run.
- **AI Config** tab — configure the HTTP classification server and headstamps.
- **Camera / Serial / Image Proc** tabs — device selection, board settings and
  sort-arm testing, and headstamp-crop tuning (Hough circles + primer mask).
- **Community** tab *(sign-in required)* — browse, search, and download
  community-published models.
- A **serial emulator** so you can run and explore the app with no hardware
  attached.

---

## Requirements

- **Python 3.10+**
- Core Python dependencies (installed automatically by the launch scripts):
  pyserial, opencv-python, numpy, Pillow, requests, msal, platformdirs
  (+ pygrabber on Windows for friendly camera names).
- **A webcam** for image capture, and the **CS7.2 sorter hardware** on a serial
  port for actual sorting (the emulator covers everything else).
- **Optional:** PyTorch + torchvision for local training/inference — see below.

---

## Install & run

The launch scripts create a virtual environment and install dependencies on
first run.

**Linux / macOS**
```bash
git clone https://github.com/sjseth/AI-Case-Sorter-Py.git
cd AI-Case-Sorter-Py
./start.sh
```
On minimal Linux installs the script may offer to install system packages
(tkinter, libGL, glib, venv) via `sudo`. Pass `--auto` (or set `AUTO_INSTALL=1`)
to confirm those installs automatically — it will print a notice before doing so.

**Windows**
```bat
git clone https://github.com/sjseth/AI-Case-Sorter-Py.git
cd AI-Case-Sorter-Py
start.bat
```

**Run it directly** (if you manage your own environment):
```bash
pip install -r requirements.txt
python main.py
```

### Running without hardware

No sorter attached? In the **Serial** tab choose the **`Emulated`** port. The
emulator mirrors the real board's protocol so you can exercise the run loop, the
UI, and most workflows without any hardware.

---

## Optional: PyTorch

Local training and local inference need PyTorch. The app will offer to install it
for you (the **Install PyTorch** dialog), or you can install the `ml` extra:

```bash
pip install ".[ml]"        # torch + torchvision
```

- **GPU:** an NVIDIA card with **compute capability ≥ 8.0** (Ampere / RTX
  30-series and newer) is used automatically; older or absent GPUs fall back to
  **CPU**, which still works but is slower.
- **AI Config mode needs no PyTorch on the client** — inference runs on the
  server instead.

---

## Where your data lives

Everything the app writes lives under `data/` next to `main.py` (override with
the `CASESORTER_DATA_DIR` environment variable). Delete the folder to reset all
state. It is **gitignored** and never committed.

```
data/
├── config/   casesorter.db (settings/models/headstamps) + msal_cache.bin (token cache)
└── models/<id>/  images · run_images · feedback_images · reports · trainedmodel
```

---

## Development

```bash
pip install -r requirements.txt pytest
pytest                       # ~200 tests covering the non-UI logic
```

Please run `pytest` before opening a PR. The UI itself is not covered by
automated tests. See [`CONTRIBUTING.md`](CONTRIBUTING.md) for setup and
guidelines, and [`SECURITY.md`](SECURITY.md) to report a vulnerability.

### Pointing at a local community backend

The community client talks to `https://www.reloadingrecipes.com/api` and
verifies TLS normally. To develop against a local copy of that backend, copy
[`.env.example`](.env.example) to `.env` (next to `main.py`, or in
`data/config/`) and set:

| Variable | Purpose |
|----------|---------|
| `CASESORTER_API_BASE` | Base URL of the community API, e.g. `https://localhost:7043/api`. |
| `CASESORTER_API_CA_BUNDLE` | PEM cert/bundle to trust — the right way to make a local HTTPS dev server verify. |
| `CASESORTER_API_INSECURE` | `1` skips TLS verification. **Honoured only when the API base is localhost**, so it can't weaken production traffic. |

Real environment variables take precedence over the `.env` file, and `.env` is
gitignored. For an ASP.NET Core dev server, export its certificate with
`dotnet dev-certs https --export-path devcert.pem --format PEM --no-password`
and point `CASESORTER_API_CA_BUNDLE` at it.

- [`CONTRIBUTING.md`](CONTRIBUTING.md) — how to set up, run the tests, and submit
  changes.
- [`CLAUDE.md`](CLAUDE.md) — architecture map for contributors and AI coding
  assistants (layers, event bus, module reference, UI tabs, data layout).
- [`OPEN_SOURCE_READINESS.md`](OPEN_SOURCE_READINESS.md) — open-source readiness
  assessment and checklist.

---

## License

Copyright (C) 2026 SJSeth Solutions

This program is free software: you can redistribute it and/or modify it under
the terms of the **GNU General Public License** as published by the Free
Software Foundation, either version 3 of the License, or (at your option) any
later version.

It is distributed in the hope that it will be useful, but **WITHOUT ANY
WARRANTY**; without even the implied warranty of MERCHANTABILITY or FITNESS FOR
A PARTICULAR PURPOSE. See the GNU General Public License for details. The full
text is in [LICENSE](LICENSE), or see <https://www.gnu.org/licenses/>.

## Acknowledgements

Part of the [SJSeth](https://shop.sjseth.com) AI Case Sorter ecosystem. The
hardware, firmware, and build guides live in the
[CS7.2 repository](https://github.com/sjseth/AI-Case-Sorter-CS7.2); the local
model host lives in [AI-Case-Sorter-Server](https://github.com/sjseth/AI-Case-Sorter-Server).
