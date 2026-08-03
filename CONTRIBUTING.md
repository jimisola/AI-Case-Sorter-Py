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

Requires **some Python 3** already on your machine — new enough to run
`bootstrap.py` itself, which is not a strict requirement, since its whole job
is to provision the app's *actual* interpreter separately via
[uv](https://docs.astral.sh/uv/). If you don't have uv yet, the launch
scripts install it automatically (into a project-local `.uv/`, not
system-wide) on first run.

**Linux / macOS**
```bash
git clone https://github.com/sjseth/AI-Case-Sorter-Py.git
cd AI-Case-Sorter-Py
./start.sh
```

**Windows:** run `start.bat`.

**Prefer to drive `uv` yourself?**
```bash
uv sync              # dependencies + dev tools (pytest, ruff) from uv.lock
uv run python main.py
```
`uv sync`/`uv run` resolve against the committed `uv.lock`, so this is
deterministic — no separate "install deps" step to remember or forget.

Local training/inference additionally needs PyTorch (optional):
```bash
uv sync --extra ml      # torch + torchvision
```

### No hardware? Use the emulator

In the **Serial** tab, choose the **`Emulated`** port to exercise the run loop
and the UI without a physical sorter attached.

## Running the tests

```bash
uv run pytest
```

Around 500 tests cover the non-UI logic; please run them before opening a PR.
The torch-dependent tests skip automatically when PyTorch isn't installed. The
UI itself is not covered by automated tests, so smoke-test UI changes by
running the app. CI (`.github/workflows/build.yml`) runs the same suite across
a Python version matrix on every push and PR — treat a red CI run the same as
a local test failure, not as something to wait out.

## Coding guidelines

- **Read [`CLAUDE.md`](CLAUDE.md) first** — it maps the architecture (event bus,
  threading model, persistence, UI tabs). **Keep it current:** if you add a tab,
  change the data model, or move a subsystem boundary, update `CLAUDE.md` in the
  same change.
- **Lint and format with [ruff](https://docs.astral.sh/ruff/)** before pushing:
  ```bash
  uv run ruff check .            # lint
  uv run ruff format .           # format
  ```
  CI runs both (`.github/workflows/lint.yml`) and fails the PR check if either
  would change anything. Match the style of the surrounding code beyond what
  ruff enforces too — naming, type hints, comment density.
- **Threading rule:** never touch Tk widgets off the main thread. Do blocking
  work in a worker/daemon thread and post results through the event bus.
- **PyTorch is optional and lazily imported** — guard any torch use and add it
  under `[project.optional-dependencies] ml`, not the base dependency list.
- Keep SQL **parameterized**; never build SQL by string interpolation.
- Never commit anything under `data/` (it's gitignored and holds local state,
  including credentials).
- Preserve interop with the legacy Windows app where the code calls it out
  (filename conventions, manifest key spellings, exact serial command strings).

## Pull request flow

1. Branch off `main`.
2. Keep PRs focused and write clear commit messages.
3. Run `uv run pytest` and `uv run ruff check .` (and smoke-test UI changes)
   before opening the PR — CI runs both, but catching it locally is faster.
4. Describe what changed and why in the PR.

### Commit messages and PR titles: Conventional Commits

Both commit subjects and the PR title must follow
[Conventional Commits](https://www.conventionalcommits.org/):
`type(optional-scope): summary`, e.g. `fix(camera): handle missing device on
enumerate`. A GitHub Action checks the PR title on every push
(`.github/workflows/check-semantic-pr.yml`); allowed types are `feat`, `fix`,
`refactor`, `chore`, `security`, `revert`, `test`, `docs`, `perf`, `style`,
`ci`, `build`. Use `type!:` or a `BREAKING CHANGE:` footer for a breaking
change.

This isn't just a style preference: commit type drives the automated
changelog and — once release automation lands — the version number itself.
A `fix:` that reads like a `feat:` (or vice versa) produces a wrong changelog
entry and, later, a wrong version bump.

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
