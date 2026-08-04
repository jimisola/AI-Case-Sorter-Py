# Feedback & decision log

Working document for the repo-standardization contribution to
[`sjseth/AI-Case-Sorter-Py`](https://github.com/sjseth/AI-Case-Sorter-Py).

The work is staged **on the fork** (`jimisola/AI-Case-Sorter-Py`) so every piece can be
verified before any of it is proposed upstream as **one PR**. This file is the running record
of what changed, what was decided and why, and what needs the repo owner.

**Two audiences, deliberately kept apart:**

- The **fork PR** (`jimisola/AI-Case-Sorter-Py#1`) is a staging branch, written for the
  contributor: current state, what's blocked, what's left to decide.
- The **upstream PR** (not yet open) is written for the maintainer, and gets its own
  description drawn from this file — decisions from §2, the owner checklist from §6.

**This file itself is not intended to ship upstream.** It's process meta about *this
contribution*, not documentation of the project, and would sit oddly as a permanent file in
someone else's repo. The plan is to fold its durable content into the upstream PR description
and turn §9 into individual issues, then drop the file in the commit that opens upstream.
Kept for now because the work is still in flight and this is the working record.

**Nothing else in the repo references this file**, so deleting it leaves no dangling links —
that is a deliberate invariant, please keep it that way. The one piece of durable content that
did have external references, §6's owner checklist, now lives permanently at
[`.github/REPO_SETUP.md`](.github/REPO_SETUP.md); §6 is retained below only as the working
record of how it was arrived at.

**Status:** implemented; all commits green on CI (Ubuntu + Windows). Not yet exercised: a real
release cut on the fork — see §8.
**Last updated:** 2026-08-03

---

## 1. How to review this (upstream)

The changes arrive as one PR, so **review commit-by-commit rather than by the combined
diff.** Commit boundaries are kept clean deliberately:

- The ruff reformat is its own commit, and its SHA is listed in `.git-blame-ignore-revs` —
  skip it in review, `git blame` will skip it too.
- Every other commit is scoped to one concern and has a Conventional Commits subject.
- The early commits (templates, Python floor, ruff, CI, Renovate) touch no application code.

Across the whole change, the **runtime-behavior surface is four files**: `sorter/updater.py`
(asset selection), `sorter/__init__.py` (version resolution), `sorter/ui/app.py` (window
title), `sorter/ui/dialog_install_torch.py` (pip → uv), plus the launchers. Everything else is
tooling, CI, or config.

---

## 2. Decision log

| # | Decision | Rationale | Status |
|---|---|---|---|
| D1 | Python floor **3.12** | 3.10 EOL Oct 2026. Ubuntu 24.04 LTS ships 3.12. Doesn't move the torch floor (see F3). | ✅ decided |
| D2 | CI matrix **3.12 / 3.13 / 3.14** | 3.14 non-blocking (`continue-on-error`) until opencv/torch wheels are reliable. | ✅ decided |
| D3 | Build backend **hatchling** | Needed for `hatch-vcs`. `uv build` invokes it via PEP 517. | ✅ decided |
| D4 | Versioning **hatch-vcs**, git-tag derived | Removes the "bump `__version__` in the same commit you tag" footgun. Requires F1 to be solved. | ✅ implemented — see D4a for the real pitfall this surfaced |
| D4a | `bootstrap.py`'s `uv sync`/`uv run` use `--no-install-project`/`--no-sync`, not just `--frozen` | Empirically confirmed (not assumed) that running hatch-vcs's build hook with no `.git` present either hard-crashes the build, or — with a `fallback-version` configured to avoid that — *silently overwrites* an already-correct `sorter/_version.py` with the fallback. `bootstrap.py`'s `uv sync` and `uv run` each rebuild the project by default on every launch, so a correctly pre-baked release version would get clobbered the first time a downloaded release actually ran. `--frozen` alone does not prevent this — it only constrains *how* a sync resolves, not whether one happens; `uv run --frozen` was confirmed to still rebuild and clobber. `--no-install-project` (on the sync) + `--no-sync` (on the run) together mean the hook never fires client-side at all, which is fine: `main.py` never needed `sorter` installed into site-packages, it imports straight from the source tree. | ✅ decided, verified against a real git-less copy of this repo |
| D5 | Env/dependency tool **uv**, not hatch | Both now have lockfiles and can provision Python. uv wins on bootstrap: single static binary with a standalone installer, so PEP 668 on Ubuntu is a non-issue. Hatch needs pip/pipx. | ✅ decided |
| D6 | Lint/format **ruff** | Replaces black + flake8 with one tool, one config block. Project currently has neither. | ✅ decided |
| D7 | **Vendor** the reqstool workflows, don't `uses:` them cross-org | Calling `reqstool/.github@main` couples this repo's CI to another org's default branch. | ✅ decided |
| D8 | Changelog via **git-cliff**; releases are **drafts** | Automated notes from Conventional Commits; nothing publishes without a human clicking. | ✅ decided |
| D9 | **Do not** migrate to `src/` layout | `apply_update.py` prunes stale files scoped to the literal `sorter/` dir; `paths.py` resolves relative to `main.py`. Small payoff, blast radius is the updater. | ✅ decided |
| D10 | Replace `start.sh`/`start.bat` with one `bootstrap.py` | Same intent currently encoded twice in two languages; the bash half is untestable except by string-matching. | ✅ decided |
| D11 | PyPI publishing **implemented but disabled** | Gated on a repo variable, unset = off. Merging changes nothing until you opt in. | ✅ decided |
| D12 | Attach wheel + sdist to **GitHub Releases** now | Gives pre-built downloads with no PyPI dependency. Safe today — see F2. | ✅ decided |
| D13 | Renovate over Dependabot | Grouping, scheduling and label control. Requires Dependabot *security updates* to be **off** or both bots open duplicate PRs. | ✅ decided |
| D13a | `minimumReleaseAge` on minor/patch updates (3 days) and major updates (7 days) | Not just noise reduction — a supply-chain-attack mitigation. A malicious or compromised package version published today gets caught and yanked/reported well within that window in the common case; auto-merging same-day means installing it before anyone's had a chance to notice. The delay costs nothing for a legitimate release. | ✅ decided |
| D14 | Superseded: originally proposed `hatch` for envs | Reversed by D5 after examining the launcher. Recorded so the reasoning isn't re-litigated. | ↩︎ superseded |
| D15 | Release version **auto-detected** by default; `force` required to override | Adopted from the `resurs-internal` `.github` template. The commit types already encode the intended bump, so making a human retype it is a chance to get it wrong. `force` turns a silent mismatch into a hard error naming both numbers. `ref` allows releasing from `release/*`/`hotfix/*`. | ✅ decided, all three paths verified locally via `act` |
| D16 | **Auto-label PRs** by subsystem (`.github/labeler.yml`) | Config adapted from the same template, but every glob rewritten — theirs are Gradle/multi-module Java paths. Labels map to CLAUDE.md's subsystem boundaries, so a label says which part of the app is in play. | ✅ decided |
| D16a | The labeler is the one workflow using `pull_request_target` | Labeling needs `pull-requests: write`, which a `pull_request` run from a fork never gets. The usual danger — running untrusted PR code with a writable token — doesn't apply: the job never checks out the PR head and never executes anything from it. zizmor clean at `--min-severity low`. Flagged explicitly because the rest of this series deliberately avoids that trigger. | ✅ decided, considered exception |
| D17 | **Not** adopting `security-scan.yml` from that template | It re-prints Dependabot/Code-Scanning/Secret-Scanning alerts that GitHub already surfaces natively, that Renovate already opens PRs for (D13/D13a), and that zizmor already covers at the workflow level — and it runs `continue-on-error`, so it never blocks anything. A dashboard, not a control. (Initially called "a real gap" on a skim; corrected on a proper read.) | ❌ declined, with reasons |
| D18 | Release Preview is **manual-only**, not per-PR | Briefly ran on every PR on the theory it'd catch a mistyped commit type pre-merge. But it wrote to the job summary — invisible unless you click into the run — on every PR including docs-only ones, and its computed "next version" goes stale the moment another PR merges. On-demand delivers the same signal, at the point someone actually wants it (before cutting a release), without the per-PR noise. | ✅ decided |

---

## 3. Findings — things that are well built and were deliberately preserved

Worth stating explicitly, because several of them constrained the design and none should be
mistaken for accidents:

- **The update apply-order.** `start.sh:198` runs `main.py --apply-update` *before* the
  dependency step, so an update that changes its own dependency manifest gets those
  dependencies installed on the same restart. `.installed` sits in `PROTECTED_TOP_LEVEL` so the
  old digest survives the file swap and correctly registers as a mismatch. This is subtle and
  correct; the replacement preserves the ordering exactly.
- **Applying updates pre-launch** to sidestep Windows `.pyd`/`.dll` locking, with backup,
  rollback, and `always exit 0` so a broken updater can never stop the app starting.
- **The data root lives outside the app folder**, which makes the updater safe by construction
  rather than by maintaining an exclusion list.
- **Traversal-safe archive extraction** in both `model_io` and `updater`, rejecting `..` and
  absolute paths.
- **`torch.load(..., weights_only=True)`** in `local_inference`, so a malicious `.pth` from a
  community download can't execute code.
- **`pending.json` is a sibling of `pending/`, never inside it** — with a comment explaining
  why. Exactly the kind of thing that gets broken by a future edit without that comment.
- **Headstamps read fresh, never cached**, with the reason (prior silent data loss) recorded.
- **`apply_update.py` and `paths.py` are stdlib-only on purpose**, because they run before the
  venv has third-party packages.

`CLAUDE.md` is unusually good as an architecture document and made this analysis much faster
than it would otherwise have been.

---

## 4. Findings — issues this work addresses

| | Finding | Where | Addressed by |
|---|---|---|---|
| F1 | `__version__` is read at **runtime** by the updater but the app is never pip-installed, so git-tag versioning has nothing to derive from in a release ZIP | `sorter/updater.py:130`, `sorter/__init__.py:6` | Generated `_version.py` + fallback chain + a purpose-built release asset |
| F2 | `_pick_asset` takes **the first asset whose name ends in `.zip`**, in upload order. Wheels/sdists don't match, so attaching them is safe — but any future stray `.zip` silently becomes the tree unpacked over the app folder | `sorter/updater.py:161` | Match an exact expected asset name; regression test |
| F3 | Two dependency lists that have already diverged — `pygrabber` is in `requirements.txt` but not in `[project.dependencies]` | `requirements.txt:10`, `pyproject.toml:31` | Single source in `pyproject.toml` + `uv.lock` |
| F4 | The dependency marker hashes a **file**, not the environment — a partial install, deleted package, or broken torch install is never detected or repaired | `start.sh:206`, `start.bat:37` | `uv sync` reconciles against `site-packages` metadata |
| F5 | Every constraint is an unpinned `>=` range, so **the hash is not a lock** — two users with an identical digest can have entirely different versions installed. No lockfile exists anywhere | `requirements.txt` | Committed `uv.lock`; `--frozen` at launch, `--locked` in CI |
| F6 | The marker ignores the interpreter, so a `.venv` built on 3.10 keeps being used after a system upgrade — which bites the moment the floor moves to 3.12 | `start.sh:206` | uv keys the environment on the interpreter |
| F7 | No hash pinning on install, so a compromised release installs silently | — | Lockfile with hashes |
| F8 | The Windows installer provisions **3.12** while declaring a 3.10 floor | `install-windows.ps1:56` vs `:59` | D1 makes the file self-consistent |
| F9 | No linter, no formatter, and **no pytest configuration anywhere** — no `[tool.pytest.ini_options]`, no `pytest.ini`, no `setup.cfg` | — | ruff + pytest config |
| F10 | No CI, no dependency automation, no issue/PR templates, no `CODEOWNERS` | — | PRs 1, 4, 5 |
| F11 | The repo ships both a `.sh` and a `.bat` with no `.gitattributes`, so a CRLF-committed shell script fails with a cryptic `\r` error | — | `.gitattributes` |
| F12 | **The system Python is the app's Python.** It must be ≥ the floor, have tkinter, and have `venv`/`ensurepip` — because `.venv` is created from it. Users on a distro whose system Python is too old cannot run the app without changing their system | `start.sh:151`, `:159`, `:172`, `:186` | uv provisions the app's interpreter independently — see §4a |
| F13 | **The window title hardcoded `v2.0.1`** — a literal connected to nothing. Not a git tag (there are none, in this fork or upstream), not `__version__` (`0.1.0` at the time), not `pyproject.toml`. Users read one version off the title bar while the in-app updater compared a completely different one against release tags. Nothing in CI could catch it: a string literal lints clean and every test passed with it wrong | `sorter/ui/app.py:58` | Derived from `__version__`, plus a guard test that parses the title call and rejects any hardcoded `x.y.z` — verified it actually fails when the old literal is restored |

---

### 4a. The Python requirement, before and after

Worth being precise about, because an earlier draft of this analysis overstated it. The claim
that uv "deletes the version check" was **too strong** — `bootstrap.py` still needs *some*
Python to run at all, so a minimal check remains. What actually changes is *which* Python has
to satisfy the requirement.

| | Today | After |
|---|---|---|
| System Python must exist | yes | yes |
| System Python must meet the version floor | **yes** — `start.sh:151` hard-fails | no |
| System Python must have tkinter | **yes** — `start.sh:172` checks it and apt-installs `python3-tk` | no |
| System Python must have `venv` / `ensurepip` | **yes** — `start.sh:159` | no |
| What the app actually runs on | the system Python (`.venv` is built from it) | a uv-provisioned interpreter, independent of the system |

The practical effect: a user on Ubuntu 22.04 with system Python 3.10 can run the app on 3.13
without touching their system Python at all. Today that user cannot run a 3.12-floor build
without upgrading system packages — which is precisely the group least equipped to do it.

**Design constraint that follows:** `bootstrap.py` must run on an *old* interpreter, since its
whole job is to provision a newer one. It should target a low floor (~3.8) and stdlib only.
This conflicts with the repo-wide ruff `target-version = "py312"`, whose pyupgrade (`UP`) rules
would happily rewrite it into 3.12-only syntax and silently break the bootstrap on exactly the
systems it exists to serve. **`bootstrap.py` needs a per-file ruff override**, and a comment
saying why.

---

## 5. Constraints discovered that shaped the design

Recorded so reviewers know these were considered, not overlooked:

- **The test suite is threading-fragile.** `tests/conftest.py` documents that Tk widget garbage
  collected on a worker thread calls into Tcl from the wrong thread and either hangs or aborts
  the process; fixtures force collection between tests. **CI must stay serial** — no
  `pytest-xdist`, no randomising plugin. This is easy to add reflexively later and would
  produce intermittent CI aborts that look like flakes.
- **UI tests need a display.** Linux CI runs under `xvfb-run -a`.
- **`portable.txt` installs** put the data root inside the app folder, so the virtualenv must
  stay in-project rather than in a central tool directory.
- **The repo must stay public** — `installer/` and `updater.py` both fetch anonymously and 404
  against a private repo, indistinguishably from "no releases yet".
- **Legacy WinForms interop is intentional** (PascalCase manifest keys, .NET ticks filenames,
  exact serial strings). Untouched by this work.

---

## 6. Needs the repo owner — cannot be done in a PR

Checklist form, so it can be worked through mechanically. None of this can land as a diff —
it's all in repo/org settings or third-party app installs.

**Merge behavior** (Settings → General → Pull Requests)
- [ ] Squash merging only — disable "Allow merge commits" and "Allow rebase merging"
- [ ] Squash commit title = `PR_TITLE`, squash commit message = `COMMIT_MESSAGES`
- [ ] Auto-delete head branches
- [ ] Allow auto-merge

**Branch protection** (Settings → Rules → Rulesets, target `main`)
- [ ] Require a pull request before merging, 1 approving review
- [ ] Dismiss stale approvals when new commits are pushed
- [ ] Require conversation/thread resolution before merging
- [ ] Block force-pushes and branch deletion
- [ ] Require status checks to pass: `lint`, `test` (the `build.yml` job), `semantic-pr`

**Security** (Settings → Code security)
- [ ] Dependabot alerts: **on**
- [ ] Dependabot *automated security updates* (the ones that open PRs): **off** — Renovate
      is the dependency-PR bot in this setup; running both opens duplicate PRs for the same CVE
- [ ] Secret scanning: **on**
- [ ] Secret scanning push protection: **on**
- [ ] CodeQL default setup: **on**
- [ ] Private vulnerability reporting: **on**

**Apps and integrations**
- [ ] **Install the Renovate GitHub App** on this repository — `.github/renovate.json5` in
      this PR does nothing until the app is installed; it won't self-activate
- [ ] Enable GitHub Discussions (the issue templates route support questions there instead
      of Issues)
- [ ] Approve the first CI run on this PR — GitHub holds workflow runs from first-time
      outside contributors until a maintainer clicks "Approve and run"
- [ ] **Create the labels the config files reference.** Neither tool creates them:
      `actions/labeler` errors on a missing label, and Renovate silently applies nothing.
      Both sets were referenced but had never existed — the Renovate ones had been dead
      config since the moment they were written. 17 needed beyond GitHub's defaults
      (`documentation` already exists). All of it is also declared in
      `.github/settings.yml`, so installing `repository-settings/app` applies it instead.
      Copy-pasteable:
      ```bash
      # Subsystem labels -- .github/labeler.yml, applied by changed path
      gh label create ui           --color 1d76db --description "Tkinter UI: tabs, dialogs, theme"
      gh label create training     --color 6f42c1 --description "Model training, local inference, evaluation"
      gh label create hardware     --color b60205 --description "Serial board, camera, image processing"
      gh label create community    --color 0e8a16 --description "Community backend, auth, feedback loop"
      gh label create updater      --color fbca04 --description "In-app updater and the Windows installer"
      gh label create launcher     --color d4c5f9 --description "bootstrap.py and the start.sh/start.bat shims"
      gh label create tests        --color c2e0c6 --description "Test suite"
      gh label create ci           --color 000000 --description "CI/CD workflows and repo tooling"
      gh label create dependencies --color 0366d6 --description "Dependency updates"

      # Renovate labels -- .github/renovate.json5
      gh label create bot-renovate            --color 5319e7 --description "Opened by Renovate"
      gh label create bot-renovate-stop       --color 5d0811 --description "Renovate: stop updating this PR (add it yourself to pin a PR)"
      gh label create security                --color b60205 --description "Vulnerability alert / security update"
      gh label create needs-hardware-test     --color e99695 --description "torch/torchvision bump -- verify on real CUDA hardware before merging"
      gh label create renovate-version-major  --color d73a4a --description "Major version update (breaking risk; never auto-merged)"
      gh label create renovate-version-minor  --color fbca04 --description "Minor version update"
      gh label create renovate-version-patch  --color 0e8a16 --description "Patch version update"
      gh label create renovate-version-digest --color c5def5 --description "Digest/SHA pin update (never auto-merged)"
      ```
      (All already created on the fork, so both tools work there today.)

**Only if PyPI publishing is ever turned on** (currently shipped disabled — see D11)
- [ ] Create the project on TestPyPI and PyPI
- [ ] Configure trusted publishing (OIDC) for both — no API tokens needed
- [ ] Create the `test` and `prod` GitHub Environments referenced by the publish workflow
- [ ] Set the repo variable `PYPI_PUBLISH_ENABLED=true`

---

## 7. Open questions for Seth

1. **PyPI vs. the in-app updater.** Two distribution channels for the same app. `pip install`
   suits developers, but the updater's whole design exists because non-developers have no pip.
   Our assumption is that PyPI *supplements* rather than replaces it. Publishing ships disabled
   so this can be decided later — but it determines what gets attached to a release.
2. **PyPI name.** PyPI has no reservation mechanism; a name is yours only once you've published.
   If `ai-case-sorter-py` matters, someone should push a `0.0.1` placeholder.
3. ~~**DCO sign-off** — want it required on contributions? Affects the PR template.~~ Resolved:
   CONTRIBUTING.md already required it; the PR template checklist just never mentioned it. Fixed
   in jimisola/AI-Case-Sorter-Py#2.
4. **`CODEOWNERS`** — `* @sjseth`, or something narrower?

---

## 8. Verification

Everything is demonstrated on the fork before it is proposed upstream, because releases,
artifact uploads and the self-update path require `contents: write` and **cannot** run on an
upstream PR at all.

| Change | How it was verified |
|---|---|
| lint / test matrix / xvfb | Green on the fork; also runs on the upstream PR itself |
| actionlint / zizmor | Run locally against every new workflow before each push, not just left to CI |
| `uv`-provisioned Python bundles Tcl/Tk | `uv python install 3.12` + `import tkinter` on this machine → `Tk 9.0`, before writing `bootstrap.py` around that assumption |
| `install_uv()` | Actually ran with the real global `uv` hidden from `PATH` — genuine download, real checksum verification by the official installer, confirmed version `0.12.1` |
| `bootstrap.py` end to end (non-GUI path) | `python bootstrap.py --apply-update` on this machine → real `uv sync`, real `uv run`, exit 0 |
| `launcher-smoke` (both `start.sh` and `start.bat`, for real) | **Green on both `ubuntu-latest` and `windows-latest`, on real GitHub Actions runners.** Along the way it caught and drove the fix for four real bugs, not zero: `start.sh` had lost its executable bit when rewritten into a thin shim; a test hardcoded the POSIX binary name and failed for real on Windows while passing on Linux; `install_uv()`'s Windows path piped a multi-line script to `powershell.exe` via `-Command -` on stdin, which silently did nothing (exit 0, no file created) — switched to a temp file + `-File`; and once that made the *real* error visible, `-File` itself exposed a PowerShell cross-version module-loading failure (`Get-ExecutionPolicy` from `Microsoft.PowerShell.Security` failing to load) from spawning legacy `powershell.exe` out of a `pwsh` session — fixed by preferring `pwsh` when available. Each fix was driven by actual CI output, not guessed; see the commit history on `chore/repo-modernization` for the full trail. This is the launcher-smoke job earning its keep, not incidental noise. |
| release notes + draft release | `release-preview.yml` ran for real on this PR while it still had a `pull_request` trigger — `NEXT: 0.1.0` confirmed in its actual job summary. (It's since been changed to manual-only; see D18.) `release.yml` was then exercised locally via `act` against this repo's real history, all three input paths: auto-detect resolved `0.1.0` and succeeded; a mismatched `9.9.9` without `force` failed with an error naming both versions; the same with `force` succeeded with a warning. Dry-run correctly skipped the tag-push and draft-release steps entirely. **Not yet exercised**: cutting a real tag on the fork — the next step before proposing upstream. |
| artifact upload | Mechanism built and pushed (commit 9), `uv build` + `twine check --strict` verified locally against this real package. **Not yet exercised**: a real `release: published` event to confirm `gh release upload` actually attaches the wheel/sdist/app-archive. |
| purpose-built app archive (`ai-case-sorter-py-<tag>.zip`) with a correct baked version | Built and pushed (commit 10). The two riskiest pieces verified directly, not assumed: (1) hatch-vcs's build hook against a real git-less copy of this repo — confirmed it either crashes or silently overwrites a correct `sorter/_version.py`, which is why `bootstrap.py` now runs with `--no-install-project`/`--no-sync`; (2) the archive-assembly sequence itself (`git archive` + inject `_version.py` + zip) run locally, confirmed the file lands in the right place. **Not yet exercised**: an actual release building this archive in CI. |
| end-to-end self-update | **Not yet done.** Needs a real release on the fork (the two rows above) before it's possible via `CASESORTER_UPDATE_REPO` (`updater.py:149`) — the next concrete step. |
| Interactive first run on a real Windows machine | **Still not done.** CI proves the bootstrap mechanics work on a stock Windows runner; it does not replace a human clicking through `start.bat` on their own machine. Flagged explicitly rather than implied by the CI passing. |

---

## 9. Suggestions for improvement (post-merge)

Out of scope for this PR — it's tooling/CI/packaging, not an application code review — but
worth a deliberate look afterward. Two sources: my own pass while working in this codebase,
and an independent read by a fresh subagent instructed to avoid re-covering anything already
listed here. Ranked roughly by how much it matters, not by count.

### From working in this codebase

1. **Python 3.12 idioms, not just the floor.** This PR raises `requires-python` to 3.12 and
   ruff's `target-version` follows it, so `ruff check --select UP` will keep surfacing
   auto-fixable upgrades over time — but a deliberate pass would also catch things pyupgrade
   doesn't auto-fix: the relaxed f-string grammar (nested same-quotes, backslashes), PEP 695
   generic syntax where generics exist, `Path.walk()` in `training/dataset.py`'s directory
   scans, etc.
2. **Resolve the deferred ruff findings from the lint-adoption commit.** `F841`, `F811`,
   `B023`, `B007`, `B017`, `B904`, `UP042` were deliberately excluded from `pyproject.toml`'s
   ruff config rather than silently fixed in a "just formatting" commit — see that commit's
   message for the reasoning. `B023` in particular (`sorter/camera.py`) is a closure/loop-
   variable pattern worth a real look, not just a style nit — it's the kind of thing that can
   be a genuine latent bug in threaded code.
3. **Apple Silicon (MPS) support in `sorter/local_inference.py`.** Device selection
   (`_pick_device`, line ~121) is CUDA-or-CPU only — confirmed while answering "would this run
   on a Mac": it would, but always on CPU, leaving an M-series chip's GPU unused. A `torch.backends.mps.is_available()`
   branch alongside the existing CUDA check would be a small, well-scoped addition.
4. **A `macos-latest` CI leg**, once/if macOS support is a real goal — would turn "probably
   works" into a verified claim. `sorter/camera.py` has explicit backends for Windows
   (`CAP_DSHOW`) and Linux (`CAP_V4L2`) but nothing for Darwin; worth knowing whether the
   OpenCV default backend is actually fine there.
5. **An OpenAPI spec for the community backend** (reloadingrecipes.com) would help, but that
   service is a separate, closed-source repo — not something this repo or PR can add. Worth
   raising with whoever owns that project, not actionable here.
6. **A formal core/UI split** was asked about directly (prompted by "could this support a
   web frontend"), and it's worth separating into two independent questions rather than one:
   - **As architecture/testability, on its own merits:** genuinely worth doing regardless of
     any web UI. The non-UI code already doesn't import `tkinter` anywhere — the boundary
     exists structurally, just not formally enforced (no package split, no import-linter rule
     stopping `sorter/*.py` from reaching into `sorter/ui/`). Formalizing it would make the
     non-UI layer more independently testable and harder to accidentally couple to Tk.
   - **As a web UI specifically:** a much bigger, separate question. The event bus assumes an
     in-process Tk consumer, camera frames would need encoding for network transport, and —
     most importantly — this app commands real motors, so remote reachability is a
     safety/security question to answer deliberately, not a side effect of a refactor.
   The first is a reasonable near-term follow-up; the second is a legitimate long-term idea
   that depends on the first but shouldn't be assumed to follow from it.
7. **Test coverage measurement.** Nothing currently reports what fraction of the non-UI code
   the suite actually exercises; `pytest-cov` in CI (per-module floor, not a global number —
   a global one would be dominated by the untestable UI modules and say nothing useful) would
   turn "the suite covers the non-UI logic" from a claim into a number.
8. **`installer/install-windows.ps1`'s tkinter-discovery is now stricter than it needs to be.**
   `Find-SuitablePython` (~line 78-113) searches for a Python that has both the version floor
   *and* a working `tkinter` import — necessary before this PR, since the venv `start.bat`
   built was made from whatever system Python it found. Now that `bootstrap.py` provisions the
   app's own interpreter via uv (which bundles Tcl/Tk itself, verified in this PR), the
   installer only needs *some* qualifying Python, not one with tkinter specifically. A Python
   with tkinter still satisfies the current check — nothing is broken — it's just doing more
   work than necessary. Deliberately **not** touched in this PR: `.ps1` changes can't be
   verified without a real Windows machine, and this file already has one documented
   past failure mode from an unverified edit (`tests/test_installer_scripts.py`'s ASCII/CRLF
   guards exist because of it).
9. **`CLAUDE.md` is 613 lines, and every assistant session loads all of it.** Raised during
   this work as a context-cost concern. Measured rather than guessed:

   | Section | Lines |
   |---|---|
   | §4 Module reference | 194 |
   | §5 The UI | 110 |
   | §7 Updates & Windows install | 75 |
   | §8 Conventions & gotchas | ~47 |
   | §1–3, §6 | ~168 |

   §4 + §5 are half the file. They're also the part that most earns its keep — the module
   reference is what made navigating this codebase fast, and it's where the constraints that
   actually shaped this PR live (the threading rule, `pending.json` being a sibling of
   `pending/`, headstamps never being cached). Cutting them would remove the file's core
   value, so **nothing was cut here** — deliberately, since it's an architecture doc written
   by the maintainer and trimming it inside a tooling PR is scope creep on content the
   contributor is not best placed to judge. The one thing that *was* fixed is
   self-inflicted: this PR briefly added a full restatement of `CONTRIBUTING.md`'s commit-type
   list to §8, now reduced to a 5-line pointer.

   Options, roughly in order of recommendation:
   - **Split §4/§5 into `docs/architecture.md`** and leave `CLAUDE.md` a ~300-line index
     pointing at it. Same information, always-loaded file halves, nothing lost. Lowest risk.
   - **Trim §5's per-dialog list**, which largely restates what the filenames already say
     (~40 lines, mild loss).
   - **Leave it.** 613 lines is roughly 8k tokens — real, but modest next to an assistant
     guessing wrong about the threading model or the updater's constraints, which is exactly
     what this file prevents.

   Worth noting the file's own header says *"Keep this file current"* — the length is at
   least partly deliberate, so this is a judgement call for the maintainer, not a defect.

### From an independent review pass (fresh subagent, codebase only — not shown this session's
work, so it couldn't just agree with the above)

Every item below cites a real file/line and was checked against the code, not inferred from
docs. Full detail (why it matters, suggested fix) is in the PR description under this same
heading — kept short here since FEEDBACK.md is already long.

1. `run_worker` (`sorter/ui/app.py`) keys subscriptions on `id(fn)` and never unsubscribes —
   a stale handler from an earlier closed dialog can fire again if CPython reuses that address.
2. `EventBus.drain()` swallows every handler exception with a bare `except: pass`
   (`sorter/events.py`), and the app has **no `logging` module usage anywhere** — six modules,
   six different `print(..., file=sys.stderr)` prefixes, no file sink. Flagged as the single
   highest-leverage, cheapest fix available.
3. `safe_label`/`parse_label` (`sorter/training/dataset.py`) don't round-trip on `__` —
   untrusted classification-server labels can silently merge two training classes.
4. `serial_broker._process_buffer` (`sorter/serial_broker.py`) does unanchored substring
   matching (`"ok" in line`) rather than anchored matching, and has **zero test coverage** —
   only the emulator is tested, so the real parser and the emulator can silently diverge.
5. A mid-run serial disconnect surfaces only as a 20-second generic timeout, with no
   `on_disconnect` callback and no bus event — the connection indicator stays "connected."
6. `updater._pick_asset` picks the first `.zip` release asset with no integrity/signature
   check beyond TLS — directly relevant once this PR's series starts attaching build
   artifacts to releases (commit 9).
7. `model_io`'s zip-bomb guard only checks entries ≥ 1 MB — many-small-entries archives skip
   the check entirely.
8. The MSAL token-cache temp file briefly exists at default (world-readable) permissions
   before its `chmod(0600)`; the SQLite DB (which holds the AI Config API key in cleartext)
   is never chmod'd at all.
9. `eval_report.py`'s `json.dumps` into a `<script>` block doesn't escape `</` — and the
   report can include model **class names** sourced from a community-downloaded checkpoint,
   not just locally-trusted folder names as the existing CLAUDE.md caveat implies.
10. `requirements.txt`/`pyproject.toml` drift, independently rediscovered (matches F3/F9 here)
    — now resolved by this PR deleting `requirements.txt` entirely.
11. Three near-duplicated capture→crop→classify blocks in `run_controller.py`
    (`test_once`/`run_once`/`cycle_once`) — one's already marked `# noqa: C901`.
12. Concrete, worth-it test-coverage gaps beyond "UI isn't tested": `sorter/events.py` (the
    architectural backbone) has no test file at all, `serial_broker`'s real parser is
    untested, and the SQLite migration path isn't exercised against an old-shape DB.

---

## 10. Document changelog

| Date | Change |
|---|---|
| 2026-08-03 | Created. Decisions D1–D14, findings F1–F11 recorded from the planning phase. |
| 2026-08-03 | Added F12 (the system Python is the app's Python) and §4a correcting an earlier overstatement that uv "deletes the version check". Recorded the resulting ruff constraint on `bootstrap.py`. |
| 2026-08-03 | Added §9 "Suggestions for improvement" (own findings + an independent subagent review). Updated §8's verification table to reflect what actually happened: uv/tkinter/libGL claims verified empirically, `bootstrap.py` proven on real GitHub Actions runners on both platforms (catching two real bugs in the process), and marked what's genuinely not done yet (releases, artifact upload, self-update, a human's own hands on Windows). |
| 2026-08-03 | `launcher-smoke` is now green on both `ubuntu-latest` and `windows-latest`. Getting there caught two more real bugs beyond the first two: `install_uv()`'s Windows path silently failed when piping the installer script via stdin, and a PowerShell cross-version module-loading failure when spawning `powershell.exe` from a `pwsh` session. Four real bugs total from this one CI job — recorded as the concrete case for why it's worth having, not just process for its own sake. |
| 2026-08-03 | Adopted three inputs from the `resurs-internal` `.github` template's release workflow (auto-detect version, `ref`, `force` — D15) and its PR auto-labeling (D16); declined its `security-scan.yml` with reasons (D17). Made Release Preview manual-only (D18). Recorded F13: the window title hardcoded `v2.0.1`, connected to no tag, no `__version__`, and no `pyproject.toml` — found by a user actually launching the app, not by any check in here. Corrected §1's stale "three files"/"planning not started" framing. |
| 2026-08-03 | Added suggestion §9.9: `CLAUDE.md`'s 613-line size as a context cost, with per-section measurements and three options — recorded rather than acted on, since §4/§5 are the maintainer's architecture reference and half the file. Fixed the part that was self-inflicted (a duplicated commit-type list added earlier in this PR, now a pointer). Also moved the release branch restriction (`main`/`hotfix/*`/`release/*`) into `release.yml` so it rejects before tagging — `check-release.yml` only ran on `release: published`, i.e. after the tag and draft already existed. |
| 2026-08-03 | Separated the two audiences. The fork PR's description was written as a pitch to the maintainer, but its actual reader is the contributor — rewritten as a staging-branch status: what's done, what's blocked (a real release, which needs a merge to `main` first), and what's still to decide. The maintainer-facing pitch belongs on the upstream PR, which doesn't exist yet. Also recorded the intent that this file does **not** ship upstream: durable content folds into that PR's description, §9 becomes individual issues, and the file is dropped in the commit that opens upstream. |
