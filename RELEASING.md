# Releasing AI Case Sorter

## How it works

1. Merge whatever should be in the release to `main`. Commit subjects must follow
   [Conventional Commits](CONTRIBUTING.md#commit-messages-and-pr-titles-conventional-commits) --
   `check-semantic-pr.yml` already enforces that on every PR, so this should already be true.
2. Every PR shows a **Release Preview** in its job summary: the next version git-cliff would
   compute and a draft of the changelog, computed from `main` plus that PR's commits. Use it
   to sanity-check what a release right now would look like, before actually cutting one.
3. When ready, run the **Release** workflow manually (Actions tab -> Release -> Run workflow):
   - `version`: the version to tag, PEP 440, no `v` prefix (e.g. `0.2.0`).
   - `dry-run`: leave **checked** the first time you try a given version, to see the generated
     notes in the job summary without pushing a tag or creating anything. Uncheck it to
     actually tag and open a draft release.
4. The workflow tags `main` at its current HEAD, generates changelog notes from commits since
   the last tag via [git-cliff](https://git-cliff.org/) (`cliff.toml`), and opens a **draft**
   GitHub Release with those notes. Nothing is published automatically -- review the draft and
   click **Publish release** yourself.
5. Publishing the release triggers `check-release.yml`, which validates the tag format and
   target branch. (Publishing a release also triggers whatever's wired to `release: published`
   in the future -- e.g. attaching build artifacts and, if enabled, publishing to PyPI. See
   `FEEDBACK.md` for what's live today.)

## Versioning

Currently `sorter/__init__.py.__version__` is a static string, bumped by hand in the same
commit as the release tag (see `CLAUDE.md` §7). A later change in this series
(`build: derive the version from git tags via hatch-vcs`) makes this automatic -- the version
will be derived from the tag itself rather than needing a manual bump. Until that lands,
**bump `sorter/__init__.py.__version__` to match the tag you're about to create, in a commit
that lands before you run the Release workflow** -- otherwise the app's own version string and
the release tag drift apart, and the in-app updater (which compares them) can misbehave.

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
