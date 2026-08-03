"""Tests for the pre-launch apply step.

The invariants that matter: user data survives, stale modules get pruned, a
failure rolls back, and the launcher is never blocked.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sorter import apply_update, paths


@pytest.fixture()
def install(monkeypatch, tmp_path: Path):
    """A fake install: app folder, separate data root, a staged update."""
    app = tmp_path / "app"
    data = tmp_path / "data"
    (app / "sorter").mkdir(parents=True)
    (app / "main.py").write_text("old main\n", encoding="utf-8")
    (app / "sorter" / "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")
    (app / "sorter" / "gone.py").write_text("removed upstream\n", encoding="utf-8")
    (app / "pyproject.toml").write_text("requests\n", encoding="utf-8")
    monkeypatch.setenv("CASESORTER_DATA_DIR", str(data))
    monkeypatch.setattr(paths, "app_root", lambda: app)
    return app, data


def _stage(data: Path, files: dict[str, str], *, version: str = "0.9.0") -> None:
    pending = data / "updates" / "pending"
    for rel, content in files.items():
        p = pending / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    (data / "updates" / "pending.json").write_text(
        json.dumps({"version": version, "tag": f"v{version}", "from_version": "0.1.0"}),
        encoding="utf-8",
    )


def test_no_pending_update_is_a_noop(install) -> None:
    app, _ = install
    assert apply_update.apply_pending() is False
    assert (app / "main.py").read_text(encoding="utf-8") == "old main\n"


def test_applies_staged_files(install) -> None:
    app, data = install
    _stage(
        data,
        {
            "main.py": "new main\n",
            "sorter/__init__.py": '__version__ = "0.9.0"\n',
            "sorter/updater.py": "brand new\n",
            "pyproject.toml": "requests\nnumpy\n",
        },
    )

    assert apply_update.apply_pending() is True
    assert (app / "main.py").read_text(encoding="utf-8") == "new main\n"
    assert (app / "sorter" / "updater.py").read_text(encoding="utf-8") == "brand new\n"
    # pyproject.toml/uv.lock must land before bootstrap.py's `uv sync` runs,
    # so a dependency change in an update installs on this same launch.
    assert (app / "pyproject.toml").read_text(encoding="utf-8") == "requests\nnumpy\n"


def test_prunes_modules_removed_upstream(install) -> None:
    app, data = install
    _stage(data, {"main.py": "new\n", "sorter/__init__.py": "new\n"})

    assert apply_update.apply_pending() is True
    assert not (app / "sorter" / "gone.py").exists()


def test_pruning_is_confined_to_the_package_dir(install) -> None:
    """A top-level file the archive omits is left alone, not deleted."""
    app, data = install
    (app / "notes.txt").write_text("mine", encoding="utf-8")
    _stage(data, {"main.py": "new\n", "sorter/__init__.py": "new\n"})

    apply_update.apply_pending()
    assert (app / "notes.txt").read_text(encoding="utf-8") == "mine"


def test_protected_paths_survive(install) -> None:
    app, data = install
    (app / ".venv" / "lib").mkdir(parents=True)
    (app / ".venv" / "lib" / "pyvenv.cfg").write_text("venv", encoding="utf-8")
    (app / ".env").write_text("SECRET=1", encoding="utf-8")
    (app / ".uv" / "bin").mkdir(parents=True)
    (app / ".uv" / "bin" / "uv").write_text("uv-binary", encoding="utf-8")
    (app / "data").mkdir()
    (app / "data" / "casesorter.db").write_text("portable db", encoding="utf-8")

    # A hostile/mistaken archive that tries to overwrite all of them.
    _stage(
        data,
        {
            "main.py": "new\n",
            "sorter/__init__.py": "new\n",
            ".env": "STOLEN=1",
            ".uv/bin/uv": "clobbered",
            "data/casesorter.db": "clobbered",
            ".venv/lib/pyvenv.cfg": "clobbered",
        },
    )

    assert apply_update.apply_pending() is True
    assert (app / ".env").read_text(encoding="utf-8") == "SECRET=1"
    assert (app / ".uv" / "bin" / "uv").read_text(encoding="utf-8") == "uv-binary"
    assert (app / "data" / "casesorter.db").read_text(encoding="utf-8") == "portable db"
    assert (app / ".venv" / "lib" / "pyvenv.cfg").read_text(encoding="utf-8") == "venv"


def test_pending_is_cleared_after_success(install) -> None:
    app, data = install
    _stage(data, {"main.py": "new\n", "sorter/__init__.py": "new\n"})
    apply_update.apply_pending()

    assert not (data / "updates" / "pending").exists()
    assert not (data / "updates" / "pending.json").exists()
    # Second launch must not re-apply.
    assert apply_update.apply_pending() is False


def test_records_what_was_applied(install) -> None:
    app, data = install
    _stage(data, {"main.py": "new\n", "sorter/__init__.py": "new\n"})
    apply_update.apply_pending()

    record = json.loads((data / "updates" / "last_applied.json").read_text())
    assert record["version"] == "0.9.0"
    assert record["from_version"] == "0.1.0"


def test_rollback_restores_the_previous_version(install, monkeypatch) -> None:
    app, data = install
    _stage(
        data,
        {
            "main.py": "new main\n",
            "sorter/__init__.py": "new init\n",
            "sorter/updater.py": "new module\n",
        },
    )

    real_copy = apply_update.shutil.copy2
    staged_root = data / "updates" / "pending"

    def _flaky_copy(src, dst, *a, **k):
        # Simulate the realistic failure: one staged file can't be written
        # (locked, permissions). Copies *out of* the backup still work, which
        # is what lets the rollback do its job.
        if Path(src).is_relative_to(staged_root) and Path(src).name == "updater.py":
            raise OSError("permission denied")
        return real_copy(src, dst, *a, **k)

    monkeypatch.setattr(apply_update.shutil, "copy2", _flaky_copy)

    assert apply_update.apply_pending() is False
    # Everything back the way it was.
    assert (app / "main.py").read_text(encoding="utf-8") == "old main\n"
    assert (app / "sorter" / "__init__.py").read_text(encoding="utf-8") == '__version__ = "0.1.0"\n'
    assert (app / "sorter" / "gone.py").read_text(encoding="utf-8") == "removed upstream\n"
    assert not (app / "sorter" / "updater.py").exists()
    # Kept for a later retry rather than silently dropped.
    assert (data / "updates" / "pending.json").is_file()


def test_empty_staged_tree_is_discarded(install) -> None:
    app, data = install
    (data / "updates" / "pending").mkdir(parents=True)
    (data / "updates" / "pending.json").write_text(json.dumps({"version": "0.9.0"}), encoding="utf-8")
    assert apply_update.apply_pending() is False
    assert not (data / "updates" / "pending.json").exists()


def test_corrupt_metadata_is_discarded(install) -> None:
    app, data = install
    (data / "updates" / "pending").mkdir(parents=True)
    (data / "updates" / "pending" / "main.py").write_text("x", encoding="utf-8")
    (data / "updates" / "pending.json").write_text("{not json", encoding="utf-8")

    assert apply_update.apply_pending() is False
    assert not (data / "updates" / "pending.json").exists()
    assert (app / "main.py").read_text(encoding="utf-8") == "old main\n"


def test_main_always_exits_zero(install, monkeypatch) -> None:
    """A broken updater must never stop the launcher."""

    def _boom(*a, **k):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(apply_update, "apply_pending", _boom)
    assert apply_update.main([]) == 0


def test_main_accepts_an_app_dir_override(install) -> None:
    app, data = install
    _stage(data, {"main.py": "new\n", "sorter/__init__.py": "new\n"})
    assert apply_update.main(["--app-dir", str(app)]) == 0
    assert (app / "main.py").read_text(encoding="utf-8") == "new\n"
