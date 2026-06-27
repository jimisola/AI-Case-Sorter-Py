# Open-Source Readiness Review

**Project:** AI Case Sorter
**Review date:** 2026-06-27
**Goal:** Identify everything that would make this repository problematic,
surprising, or legally risky to open-source — and what to add before flipping it
public. This is a companion to `Security.md` (which covers vulnerabilities).
Nothing here is fixed; it is an actionable checklist.

Severity legend: **Blocker** (do not open-source without it) · **High** ·
**Medium** · **Low/Polish**.

---

## A. Licensing & legal

### A1. **Blocker — No LICENSE file**
There is no `LICENSE`/`COPYING` anywhere in the repo. Under copyright law, code
published with **no license is "all rights reserved"**: people can view it but
cannot legally use, modify, fork, or contribute. This is the single most
important gap.
- **Action:** Choose and add a license. For a permissive, contribution-friendly
  posture use **MIT** or **Apache-2.0** (Apache-2.0 additionally grants an
  explicit patent license — a plus given the CV/ML domain). Add the SPDX
  identifier to `pyproject.toml` (`license = "Apache-2.0"`) and a short header or
  `NOTICE` as appropriate.
- Confirm you (the author) hold rights to all code being released — i.e. it
  wasn't written under an employment/contract assignment that would conflict.

### A2. **High — Third-party dependency license compatibility**
You redistribute behavior built on these runtime deps: `pyserial`,
`opencv-python`, `numpy`, `Pillow`, `requests`, `msal`, `platformdirs`,
`pygrabber` (Windows), and optionally `torch`/`torchvision`. Most are permissive
(BSD/MIT/Apache/HPND). Two things to verify before you advertise binaries:
- **`opencv-python` wheels** bundle OpenCV plus, in some builds, **FFmpeg**, whose
  licensing (LGPL/GPL + software-patent considerations) matters **if you ship
  pre-built binaries/installers**. Running from source via pip is fine; bundling
  is where you must check. Consider documenting `opencv-python-headless` as an
  option.
- Produce a short **third-party notices** list (or `THIRD_PARTY_LICENSES.md`) once
  a license is chosen. Tools: `pip-licenses`.

### A3. **High — Domain sensitivity (ammunition reloading / firearms-adjacent)**
The app's purpose — sorting spent brass casings by headstamp — sits in the
**ammunition reloading** domain (the backend is literally `reloadingrecipes.com`).
This is legal and permitted on GitHub, but:
- Some organizations, CI providers, app stores, and downstream redistributors
  have policies restricting firearms/ammunition-related projects. Contributors
  using work accounts may be affected.
- **Action:** Add a clear **scope + disclaimer** to the README: this software
  sorts inert brass cases by their stamped markings; it is not a firearm, not a
  munition, and contains no load/recipe data. State the intended lawful use.

### A4. **Medium — Liability disclaimer for physical hardware control**
This software drives **motors and a solenoid/"airdrop" output** over serial and
issues motion commands. An open-source release invites others to run it against
real hardware. Beyond the license's standard "NO WARRANTY," add an explicit
**safety/assumption-of-risk disclaimer** (moving machinery, pinch points,
electrical) in the README and ideally at first run.

### A5. **Medium — Branding / trademark**
The code embeds product/brand identifiers: `reloadingrecipes.com`, the `SJS_*`
naming lineage, the author's name/email, and the "Case Sorter" product name.
- **Action:** Confirm you have the right to release these names, and decide
  whether the OSS project keeps the brand or uses a neutral name. Ensure the
  upstream WinForms app's code/assets aren't inadvertently included under a
  different license.

---

## B. Backend & infrastructure coupling

### B1. **High — Cloud features are hardwired to the author's private backend**
`sorter/auth.py` hardcodes a specific **Azure AD B2C** tenant, client ID,
authority, and redirect; `sorter/community_api.py` hardcodes
`https://www.reloadingrecipes.com/api`. These tie sign-in, model download/search,
sharing, and the feedback loop to **a single hosted backend a fork cannot
reproduce** (the backend service is not part of this repository).
- This is not a secret leak (a public client ID is meant to ship in the app),
  but it is a **forkability and expectation problem**: a community contributor
  cannot stand up their own server, and the "community" half of the app is
  unusable against anything but the author's service.
- **Action:** (1) Clearly document in the README that the app is **fully usable
  offline/local** (local training + local inference + AI Config against any
  OpenAI-compatible server) and that **community features require the hosted
  backend**. (2) Consider lifting the endpoints/tenant into config or env vars so
  a fork *could* point at its own deployment. (3) State plainly that the server is
  not part of this open-source release.

### B2. **Medium — Community workflows depend on an external server**
This repository is the **full-parity application** (local training, inference,
and sorting all work standalone), but the community half talks to the hosted
`reloadingrecipes.com` service, which is not in this repo and (presumably) not
open. Set this expectation up front so contributors aren't surprised that
end-to-end community workflows can't be developed/tested without access.

### B3. **Medium — External hardware & firmware not in repo**
Full use requires the physical sorter, a camera, and a serial-connected
microcontroller running specific firmware (the serial protocol in
`serial_broker.py` targets it). None of that is in the repo.
- **Action:** Document the **emulator path** (`serial_emulator.py`, port
  `"Emulated"`) so contributors without hardware can still run the UI and the
  sort loop. Link to where the firmware/hardware lives, or state it's external.

---

## C. Project hygiene & contributor onboarding (all missing)

### C1. **Blocker — No README.md**
There is no README at all. A public repo needs, at minimum: what it is, a
screenshot, supported platforms, install/run (`start.sh` / `start.bat` /
`python main.py`), the local-only vs community distinction, the hardware/emulator
note, and links to `CLAUDE.md`, `Security.md`, and the license.

### C2. **High — No contribution / community files**
Missing: `CONTRIBUTING.md` (how to set up, run `pytest`, coding style, branch/PR
flow), `CODE_OF_CONDUCT.md`, and a **`SECURITY.md` vulnerability-disclosure
policy** (note: the existing `Security.md` is a *review*, not a reporting policy —
consider renaming to avoid confusion, e.g. `docs/security-review.md`, and add a
real disclosure `SECURITY.md`). Issue/PR templates under `.github/` help too.

### C3. **High — No CI**
There are ~30 pytest modules but **no `.github/workflows`** to run them. New
contributors can break things silently.
- **Action:** Add a CI workflow that runs `pytest` on Linux (and ideally Windows)
  across Python 3.10–3.12, plus a lint/format/type check. Headless note: the UI
  isn't tested, but the logic suite should pass without a display; verify it runs
  without `torch` installed (ML tests should skip/guard).

### C4. **Medium — No linter/formatter/type-check config**
The code is consistently typed and styled, but there's no enforced tooling
(`ruff`/`black`/`flake8`, `mypy`/`pyright`, `pre-commit`). Add configuration so
contributions stay consistent; wire it into CI (C3).

### C5. **Medium — `pyproject.toml` metadata gaps**
Missing `license`, `authors`, `readme`, `urls` (Homepage/Repository/Issues), and
trove `classifiers`. (The distribution `name`/`description` have been updated to
`ai-case-sorter-py` and a full-app description — the early "OSS client" framing is
no longer in `pyproject.toml`.) `version = 0.1.0` implies possible PyPI intent —
decide whether you're publishing. If so, also reconcile **C6**.

### C6. **Low — Runtime writes next to the source tree**
`paths.app_data_dir()` defaults to `<repo>/data/`. That works when launched from a
checkout (the intended flow) but would be **non-writable inside `site-packages`**
if the package were `pip install`-ed and run as an installed module. If PyPI/
installed distribution is ever a goal, default to a platform user-data dir
(`platformdirs` is already a dependency) with the current behavior as a fallback.
Not a blocker for the run-from-clone model.

### C7. **Low — No CHANGELOG / release process**
No `CHANGELOG.md`, no tags/releases. Add lightweight release notes once public.

### C8. **Medium — Stale "OSS client" and WinForms-source comments in the code**
The codebase carries leftover docstrings and inline comments from the early
**client-only ("OSS client")** development phase, plus many comments that cite the
original WinForms C# sources by filename (e.g. `SJS_OpenAI.cs`,
`SJS_ReloadingRecipesAPI`, `AIConfig.cs:196`, line-number references into the C#
app). To an outside contributor — or an LLM coding agent — these are misdirecting:
they imply a "client only" scope that is no longer true and reference files that
do not exist in this repository.
- **Action:** Sweep the tree and remove/rewrite (a) every "OSS client" / "client
  only" reference, and (b) every comment that points at the WinForms `.cs` sources
  or their line numbers. Keep the *intent* where a comment explains a deliberate
  compatibility choice (e.g. ".NET ticks filenames for interop"), but drop the
  specific C# file/line citations. Also update the `pyproject.toml` name/description
  (C5) and any module docstrings that open with "Mirrors `SJS_*.cs`...".
- Suggested starting grep: `OSS`, `client only`, `\.cs`, `SJS_`, `WinForms` —
  across `sorter/` and `main.py`.

---

## D. User-experience surprises to document

These aren't defects, but they will generate issues if undocumented:

- **D1. GPU support is restrictive.** `gpu_detect.py` requires NVIDIA **compute
  capability ≥ 8.0** (Ampere/RTX 30-series and newer). Users with older but
  CUDA-capable cards will be steered to **CPU-only** training/inference. Call this
  out so it isn't reported as a bug.
- **D2. PyTorch is a large, optional, environment-sensitive install.** It's
  installed on demand via a dialog (pinned `torch`/`torchvision`). Document the
  CPU vs CUDA choice, the download size, and that AI Config mode needs no torch.
- **D3. Linux camera defaults are opinionated.** `camera.py` sets a fixed manual
  exposure tuned for an LED ring on V4L2. On other setups this may produce dark/
  bright previews; document how to adjust.
- **D4. Windows-only dependency.** `pygrabber` (friendly camera names) is
  Windows-only; behavior differs across platforms by design.
- **D5. `start.sh --auto` installs system packages via `sudo`.** Document this
  (also noted in `Security.md` #9) so users opt in knowingly.

## E. Privacy / data-flow transparency

- **E1. The community feedback loop uploads captured images.** For community
  models with the loop enabled, below-confidence cropped case images are staged
  and uploaded to the backend (`feedback.py` → `community_api.py`). This is a
  reasonable feature, but for an open-source release add a short **privacy note**:
  what is collected, when, where it goes, and that it only applies to
  community-managed models the user has opted into. Default the verbose feedback
  debug logging **off** (see `Security.md` #8).

---

## Prioritized "make it public" checklist

**Must-have before going public (Blockers):**
1. Add a **LICENSE** (A1).
2. Add a **README.md** (C1) — including the local-vs-community scope (B1),
   domain/safety disclaimers (A3/A4), and the emulator path (B3).

**Strongly recommended (High):**
3. Verify dependency-license compatibility + third-party notices (A2).
4. Document backend coupling / make endpoints configurable (B1/B2).
5. Add `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, and a disclosure-policy
   `SECURITY.md`; rename the existing review file to avoid confusion (C2).
6. Add **CI** running pytest + lint (C3).
7. Sweep the code for stale "OSS client" and WinForms `.cs` comments (C8).

**Polish (Medium/Low):**
8. Linter/formatter/type-check config + pre-commit (C4).
9. Fill in `pyproject.toml` metadata; decide on PyPI (C5/C6).
10. CHANGELOG + release process (C7).
11. Document the UX surprises (Section D) and the privacy note (E1).

## Positive observations
- `data/` (DB, token cache, config, models) is **gitignored**; the git history
  contains **no committed secrets or user data**.
- Cross-platform care is evident (Windows/Linux backends, atomic writes, venv
  bootstrap scripts).
- Strong, consistent type hints and a substantial test suite already exist —
  good foundations for outside contributors once CI enforces them.
- Sensitive fields are stripped from exported model manifests.
