# Repository setup — the parts that can't land as a diff

Everything in this repo that *can* be configured as code, is: `.github/settings.yml`
declares the repo settings and labels, `.github/renovate.json5` the dependency policy,
`.github/workflows/` the CI. This file covers the rest — repo/org settings and
third-party app installs that only a repo owner can apply, through the GitHub UI or
`gh`.

Checklist form, so it can be worked through mechanically.

> **If you install [`repository-settings/app`](https://github.com/repository-settings/app)**,
> most of the "Merge behavior" and all of the "Labels" sections below are applied
> automatically from `.github/settings.yml` and you can skip them. Note that
> `settings.yml` here is *not* in safe-settings format — see the comments at the top of
> that file. Without the app installed, this document is the manual fallback.

## Merge behavior

Settings → General → Pull Requests.

- [ ] Squash merging only — disable "Allow merge commits" and "Allow rebase merging"
- [ ] Squash commit title = `PR_TITLE`, squash commit message = `COMMIT_MESSAGES`
- [ ] Auto-delete head branches
- [ ] Allow auto-merge

## Branch protection

Settings → Rules → Rulesets, target `main`.

- [ ] Require a pull request before merging, 1 approving review
- [ ] Dismiss stale approvals when new commits are pushed
- [ ] Require conversation/thread resolution before merging
- [ ] Block force-pushes and branch deletion
- [ ] Require status checks to pass. These are **job names**, not workflow names, and the
      ruleset matches them literally — a name that never reports blocks every merge
      indefinitely rather than failing loudly:
      - `ruff (check + format)`
      - `lint the workflows themselves`
      - `release version mapping`
      - `pytest (ubuntu-latest, py3.12)`
      - `pytest (windows-latest, py3.12)`
      - `Validate PR title`

      The other matrix legs are deliberately not required: 3.14 runs
      `continue-on-error`, and requiring 3.13 as well buys nothing 3.12 doesn't already
      catch. Keep this list in step with the `contexts:` block in `settings.yml`.

Note that requiring an approving review makes it impossible to merge your own PR
(GitHub won't let you approve your own), which locks a solo maintainer or a fork owner
out of their own repo. That's why the equivalent `branches:` block in
`.github/settings.yml` ships commented out — enable it upstream, where PRs get an actual
second pair of eyes.

## Security

Settings → Code security.

- [ ] Dependabot alerts: **on**
- [ ] Dependabot *automated security updates* (the ones that open PRs): **off** —
      Renovate is the dependency-PR bot in this setup; running both opens duplicate PRs
      for the same CVE
- [ ] Secret scanning: **on**
- [ ] Secret scanning push protection: **on**
- [ ] CodeQL default setup: **on**
- [ ] Private vulnerability reporting: **on**

## Apps and integrations

- [ ] **Install the Renovate GitHub App** on this repository — `.github/renovate.json5`
      does nothing until the app is installed; it won't self-activate
- [ ] **Enable Issues** (Settings → General → Features). `.github/settings.yml` declares
      `has_issues: true`, but that only takes effect once `repository-settings/app` is
      installed — without it, or until then, this needs toggling by hand. The issue
      templates, `triage`/subsystem labels, and `labeler.yml` all depend on Issues being on;
      none of them do anything on a repo where it's off.
- [ ] Enable GitHub Discussions (the issue templates route support questions there
      instead of Issues)
- [ ] Approve the first CI run on a new contributor's PR — GitHub holds workflow runs
      from first-time outside contributors until a maintainer clicks "Approve and run"

## Labels

**Neither tool creates the labels it references.** `actions/labeler` errors on a missing
label; Renovate and GitHub issue forms silently apply nothing. All of these are declared
in `.github/settings.yml`, so installing `repository-settings/app` applies them for you.
Otherwise, copy-pasteable (18 beyond GitHub's defaults; `documentation` already exists):

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

# Issue templates -- .github/ISSUE_TEMPLATE/*.yml
gh label create triage       --color ededed --description "New issue awaiting triage"

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

## Only if PyPI publishing is turned on

Currently shipped disabled, gated on the repo variable `PYPI_PUBLISH_ENABLED`.

- [ ] Create the project on TestPyPI and PyPI
- [ ] Configure trusted publishing (OIDC) for both — no API tokens needed
- [ ] Create the `test` and `prod` GitHub Environments referenced by `publish.yml`
- [ ] Set the repo variable `PYPI_PUBLISH_ENABLED=true`
