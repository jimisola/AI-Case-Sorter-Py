# Releasing AI Case Sorter

## How it works

1. Merge whatever should be in the release to `main`. Commit subjects must follow
   [Conventional Commits](CONTRIBUTING.md#commit-messages-and-pr-titles-conventional-commits) --
   `check-semantic-pr.yml` already enforces that on every PR, so this should already be true.
2. Every PR shows a **Release Preview** in its job summary: the next version git-cliff would
   compute and a draft of the changelog, computed from `main` plus that PR's commits. Use it
   to sanity-check what a release right now would look like, before actually cutting one. It
   can also be run manually (Actions -> Release Preview -> Run workflow) against any `ref`,
   which is how you preview a `release/*` or `hotfix/*` branch that has no open PR.
3. When ready, run the **Release** workflow manually (Actions tab -> Release -> Run workflow):
   - `version`: **leave empty to auto-detect.** git-cliff computes the next version from the
     Conventional Commits since the last tag. **While the project is pre-1.0 that means
     `feat:` and `fix:` both bump the patch, and a `!`/`BREAKING CHANGE:` bumps the minor** --
     git-cliff's standard 0.x behaviour, since 0.x is where breaking changes are expected.
     From the first 1.x tag it switches to the familiar `feat:` -> minor, `!` -> major on its
     own. See CONTRIBUTING.md for the full table. Passing a version explicitly overrides all
     of this.
   - `ref`: branch to release from. Empty means the branch you dispatched on. **Must be
     `main`, `hotfix/*`, or `release/*`** — anything else is rejected before a tag is
     created. A raw commit SHA is rejected for the same reason: release from the branch
     containing it instead, so the release is traceable to a branch.
   - `force`: only needed when you pass a `version` that **disagrees** with the auto-detected
     one. Without it, a mismatch is a hard error naming both numbers -- that's the guard that
     catches "meant 0.3.0, typed 0.2.0" before it becomes a tag.
   - `dry-run`: **defaults to on.** Shows the resolved version and generated notes in the job
     summary without pushing a tag or creating anything. Uncheck it to actually release.
4. The workflow tags the chosen ref, generates changelog notes from commits since the last tag
   via [git-cliff](https://git-cliff.org/) (`cliff.toml`), and opens a **draft** GitHub
   Release with those notes. Nothing is published automatically -- review the draft and click
   **Publish release** yourself.
5. Publishing the release triggers `check-release.yml`, which validates the tag format and
   target branch. (Publishing a release also triggers whatever's wired to `release: published`
   in the future -- e.g. attaching build artifacts and, if enabled, publishing to PyPI.
   Artifact attachment is live; PyPI publishing ships disabled, gated on the repo variable
   `PYPI_PUBLISH_ENABLED` -- see `.github/REPO_SETUP.md`.)

## Versioning

**There is no version to bump by hand.** The tag is the single source of truth: hatch-vcs
derives the version from it at build time (`pyproject.toml`'s `[tool.hatch.version] source =
"vcs"`), writing `sorter/_version.py`, which `sorter/__init__.py` reads. Don't edit a version
string anywhere -- there isn't one to edit.

That's the point of the setup: the old arrangement had a static `__version__` that had to be
bumped in the same commit as the tag, and it drifted in practice. When this was written, the
app's window title said `v2.0.1` while `__version__` said `0.1.0` and no git tag existed at
all -- three different answers to "what version is this?", one of them shown to users.

How the version reaches a user who never has `.git`:

- **A downloaded release** gets `ai-case-sorter-py-<tag>.zip`, which `publish.yml` builds from
  a `git archive` of the tagged commit with the CI-generated `sorter/_version.py` copied in.
  `sorter/updater.py` looks for that asset by exact name.
- **A pip/uv install** (if PyPI is ever enabled) reads it from package metadata.
- **A plain `git clone` that was never built** falls back to `0.0.0+unknown`. Expected -- it's
  a contributor path, not a release path.

See `CLAUDE.md` §7 for why `bootstrap.py` passes `--no-install-project`/`--no-sync`: without
them, a launch from a git-less release would silently overwrite the correct baked version.

## Commit-type -> changelog section mapping

Set by `cliff.toml`, matching the types `check-semantic-pr.yml` enforces:

| Commit type | Changelog section |
|---|---|
| `feat` | Features |
| `fix` | Bug Fixes |
| `perf` | Performance |
| `refactor` | Refactoring |
| `chore` | Miscellaneous |
| `docs` | Documentation |
| `test` | Testing |
| `security` | Security |
| `style` | Style |
| `ci`, `build` | (omitted from the changelog -- internal tooling, not user-facing) |

Commits that don't parse as Conventional Commits are skipped entirely (`filter_unconventional
= true`), which is why every commit on this repo needs a properly-typed subject line.
