"""Guards on cliff.toml -- the file that decides the released version number.

Nothing else in the repo encodes a version, so a wrong answer here ships a
wrong release (CLAUDE.md §8). These tests run the *real* git-cliff binary
against throwaway repos, because the only thing worth asserting is what the
tool actually does -- the failure mode being guarded against is documentation
that describes git-cliff's behaviour correctly-in-theory and wrongly in fact.

Skipped when git-cliff isn't installed; CI's release workflows install it, and
a contributor without it still gets the rest of the suite.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CLIFF_CONFIG = ROOT / "cliff.toml"

pytestmark = pytest.mark.skipif(shutil.which("git-cliff") is None, reason="git-cliff not installed")


def _repo(tmp_path: Path, base_tag: str, commits: list[str]) -> Path:
    """A throwaway git repo tagged ``base_tag`` with ``commits`` on top."""
    repo = tmp_path / "repo"
    repo.mkdir()
    run = lambda *a: subprocess.run(a, cwd=repo, check=True, capture_output=True)  # noqa: E731
    run("git", "init", "-q", "-b", "main", ".")
    run("git", "config", "user.email", "t@example.com")
    run("git", "config", "user.name", "T")
    # Never inherit the developer's signing config -- it makes commits fail here.
    run("git", "config", "commit.gpgsign", "false")
    run("git", "config", "tag.gpgsign", "false")
    shutil.copy(CLIFF_CONFIG, repo / "cliff.toml")

    (repo / "base.txt").write_text("base\n", encoding="utf-8")
    run("git", "add", "-A")
    run("git", "commit", "-q", "-m", "chore: base")
    run("git", "tag", base_tag)

    for i, subject in enumerate(commits):
        (repo / f"f{i}.txt").write_text("x\n", encoding="utf-8")
        run("git", "add", "-A")
        run("git", "commit", "-q", "-m", subject)
    return repo


def _bumped_version(repo: Path) -> str:
    result = subprocess.run(
        ["git-cliff", "--config", "cliff.toml", "--bumped-version"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


@pytest.mark.parametrize(
    ("base", "subject", "expected"),
    [
        # Full semver, and it applies at 0.x too -- git-cliff does NOT use the
        # looser "anything goes below 1.0" convention some tools do, because
        # features_always_bump_minor/breaking_always_bump_major default to true.
        ("0.1.0", "fix: a bug", "0.1.1"),
        ("0.1.0", "feat: a feature", "0.2.0"),
        ("0.1.0", "feat!: a breaking feature", "1.0.0"),
        ("0.0.1", "feat: a feature", "0.1.0"),
        ("0.9.3", "feat: a feature", "0.10.0"),
        ("1.2.3", "fix: a bug", "1.2.4"),
        ("1.2.3", "feat: a feature", "1.3.0"),
        ("1.2.3", "feat!: a breaking feature", "2.0.0"),
    ],
)
def test_bump_mapping_is_what_the_docs_claim(tmp_path: Path, base: str, subject: str, expected: str) -> None:
    """CONTRIBUTING.md publishes this table and RELEASING.md repeats it; a
    contributor picks their commit type from it. The `0.1.0` + `feat!:` ->
    `1.0.0` row is the counter-intuitive one and the reason this test exists.
    """
    assert _bumped_version(_repo(tmp_path, base, [subject])) == expected


def test_tag_pattern_ignores_a_v_prefixed_tag(tmp_path: Path) -> None:
    """tag_pattern is an unanchored regex in git-cliff, so the obvious
    "[0-9].*" also matches any tag merely *containing* a digit -- including
    the `v1.0.0` form check-release.yml rejects. With that pattern a stray
    v-tag becomes the latest release and the next version is computed from
    it: `0.1.0` + a feat would resolve to `v1.0.1` rather than `0.2.0` -- both
    the wrong number and a `v` prefix the release workflow would then reject.
    """
    repo = _repo(tmp_path, "0.1.0", ["feat: a feature"])
    subprocess.run(["git", "tag", "v1.0.0"], cwd=repo, check=True, capture_output=True)

    assert _bumped_version(repo) == "0.2.0"
