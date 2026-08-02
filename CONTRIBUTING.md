# Contributing to AI Case Sorter

Thanks for your interest in improving the AI Case Sorter! This repository is the
cross-platform **desktop application**. The hardware, firmware, and the optional
local model server live in separate repositories (linked from the
[README](README.md)).

By participating in this project you agree to abide by our
[Code of Conduct](CODE_OF_CONDUCT.md).

## Ways to contribute

- Report bugs or request features via [GitHub Issues](https://github.com/sjseth/AI-Case-Sorter-Py/issues/new/choose)
  — pick the bug report or feature request form so we get what we need to reproduce it.
- General questions belong in [Discussions](https://github.com/sjseth/AI-Case-Sorter-Py/discussions),
  not Issues.
- Improve documentation — including [`CLAUDE.md`](CLAUDE.md), the architecture map.
- Fix bugs or add features via pull requests (the PR template lists the checklist).
- Report **security** issues privately — see [`SECURITY.md`](SECURITY.md). Please
  do not file security problems as public issues.

## Development setup

Requires **Python 3.12+**.

**Linux / macOS**
```bash
git clone https://github.com/sjseth/AI-Case-Sorter-Py.git
cd AI-Case-Sorter-Py
./start.sh
```

**Windows:** run `start.bat`. Or manage your own environment:
```bash
pip install -r requirements.txt pytest
python main.py
```

Local training/inference additionally needs PyTorch (optional):
```bash
pip install ".[ml]"      # torch + torchvision
```

### No hardware? Use the emulator

In the **Serial** tab, choose the **`Emulated`** port to exercise the run loop
and the UI without a physical sorter attached.

## Running the tests

```bash
pytest
```

Around 200 tests cover the non-UI logic; please run them before opening a PR. The
torch-dependent tests skip automatically when PyTorch isn't installed. The UI
itself is not covered by automated tests, so smoke-test UI changes by running the
app.

## Coding guidelines

- **Read [`CLAUDE.md`](CLAUDE.md) first** — it maps the architecture (event bus,
  threading model, persistence, UI tabs). **Keep it current:** if you add a tab,
  change the data model, or move a subsystem boundary, update `CLAUDE.md` in the
  same change.
- Match the style of the surrounding code — naming, type hints, comment density.
- **Threading rule:** never touch Tk widgets off the main thread. Do blocking
  work in a worker/daemon thread and post results through the event bus.
- **PyTorch is optional and lazily imported** — guard any torch use and don't add
  it to `requirements.txt` (it's the `[ml]` extra).
- Keep SQL **parameterized**; never build SQL by string interpolation.
- Never commit anything under `data/` (it's gitignored and holds local state,
  including credentials).
- Preserve interop with the legacy Windows app where the code calls it out
  (filename conventions, manifest key spellings, exact serial command strings).

## Pull request flow

1. Branch off `main`.
2. Keep PRs focused and write clear commit messages.
3. Run `pytest` (and smoke-test UI changes) before opening the PR.
4. Describe what changed and why in the PR.

## Contributions & licensing (DCO)

This project is licensed under **GPL-3.0-or-later**. By submitting a contribution
you agree that it is provided under that same license (inbound = outbound).

We use the **Developer Certificate of Origin (DCO)**: sign off each commit to
certify you have the right to submit it under the project license.

```bash
git commit -s -m "Your message"
```

This appends a `Signed-off-by: Your Name <you@example.com>` line to the commit.
The full DCO text is at <https://developercertificate.org>.
