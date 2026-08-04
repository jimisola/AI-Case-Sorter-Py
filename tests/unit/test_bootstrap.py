"""Guards on bootstrap.py and the launcher shims that call it.

bootstrap.py has to run on whatever old Python the user's system ships --
its whole job is to provision a newer one via uv -- so the properties worth
guarding are "doesn't import anything that isn't in the box" and "does what
the CLI contract promises", not the actual uv install/sync (that needs a
real network and a real uv release; exercised in CI's launcher-smoke job on
real runners, and manually against a real uv install while this was built).
"""

from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
BOOTSTRAP_PATH = ROOT / "bootstrap.py"


def _load_bootstrap():
    spec = importlib.util.spec_from_file_location("bootstrap", BOOTSTRAP_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def bootstrap(monkeypatch):
    # Never let a test accidentally shell out to a real uv/sudo/network call.
    module = _load_bootstrap()
    monkeypatch.setattr(module.subprocess, "run", MagicMock())
    monkeypatch.setattr(module.subprocess, "call", MagicMock(return_value=0))
    return module


def test_bootstrap_py_is_stdlib_only_at_module_level() -> None:
    """Deferred, function-scoped imports (e.g. sorter.apply_update) are fine
    -- sorter itself is stdlib-only by design (see CLAUDE.md). What must
    never happen is a *module-level* import of anything third-party, since
    that would break before this script gets a chance to provision uv."""
    tree = ast.parse(BOOTSTRAP_PATH.read_text(encoding="utf-8"))
    top_level_modules: set[str] = set()
    for node in tree.body:  # module-level statements only, not nested in defs
        if isinstance(node, ast.Import):
            top_level_modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            top_level_modules.add(node.module.split(".")[0])

    allowed = set(sys.stdlib_module_names) | {"__future__"}
    offenders = top_level_modules - allowed
    assert not offenders, f"bootstrap.py imports non-stdlib module(s) at module level: {offenders}"


def test_bootstrap_py_compiles() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "py_compile", str(BOOTSTRAP_PATH)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_main_consumes_auto_flags_and_forwards_the_rest(bootstrap, monkeypatch) -> None:
    monkeypatch.setattr(bootstrap, "find_uv", MagicMock(return_value="/fake/uv"))
    monkeypatch.setattr(bootstrap, "apply_pending_update", MagicMock())
    monkeypatch.setattr(bootstrap, "ensure_linux_runtime_libs", MagicMock())
    fake_run = MagicMock(returncode=0)
    monkeypatch.setattr(bootstrap.subprocess, "run", MagicMock(return_value=fake_run))

    bootstrap.main(["--auto", "--some-app-flag", "value"])

    calls = bootstrap.subprocess.run.call_args_list
    launch_call = calls[-1]
    launched_argv = launch_call.args[0]
    assert launched_argv[:2] == ["/fake/uv", "run"]
    assert "--auto" not in launched_argv
    assert "--some-app-flag" in launched_argv
    assert "value" in launched_argv


def test_main_dash_y_is_equivalent_to_auto(bootstrap, monkeypatch) -> None:
    monkeypatch.setattr(bootstrap, "find_uv", MagicMock(return_value="/fake/uv"))
    monkeypatch.setattr(bootstrap, "apply_pending_update", MagicMock())
    seen = {}

    def fake_ensure(_uv, auto_install):
        seen["auto_install"] = auto_install

    monkeypatch.setattr(bootstrap, "ensure_linux_runtime_libs", fake_ensure)
    monkeypatch.setattr(bootstrap.subprocess, "run", MagicMock(returncode=0))

    bootstrap.main(["-y"])
    assert seen["auto_install"] is True


def test_apply_update_runs_before_sync(bootstrap, monkeypatch) -> None:
    """The one ordering invariant carried over from start.sh/start.bat: a
    staged update must be applied before dependencies sync, so an update
    that changes pyproject.toml/uv.lock gets its new dependencies installed
    on this same launch."""
    monkeypatch.setattr(bootstrap, "find_uv", MagicMock(return_value="/fake/uv"))
    monkeypatch.setattr(bootstrap, "ensure_linux_runtime_libs", MagicMock())
    monkeypatch.setattr(bootstrap.subprocess, "run", MagicMock(returncode=0))

    order = []
    monkeypatch.setattr(bootstrap, "apply_pending_update", lambda: order.append("apply_update"))
    real_run = bootstrap.subprocess.run

    def tracking_run(cmd, *a, **kw):
        if cmd[1:2] == ["sync"]:
            order.append("uv_sync")
        return real_run(cmd, *a, **kw)

    monkeypatch.setattr(bootstrap.subprocess, "run", tracking_run)

    bootstrap.main([])
    assert order == ["apply_update", "uv_sync"]


def test_sync_is_inexact_so_the_ml_extra_survives(bootstrap, monkeypatch) -> None:
    """`uv sync` is exact by default and prunes anything absent from the
    lockfile. torch/torchvision are the [ml] extra -- installed on demand by
    dialog_install_torch.py into this same venv, outside the lock -- so
    without --inexact every launch silently uninstalls PyTorch."""
    monkeypatch.setattr(bootstrap, "find_uv", MagicMock(return_value="/fake/uv"))
    monkeypatch.setattr(bootstrap, "apply_pending_update", MagicMock())
    monkeypatch.setattr(bootstrap, "ensure_linux_runtime_libs", MagicMock())

    sync_cmd = []

    def tracking_run(cmd, *a, **kw):
        if cmd[1:2] == ["sync"]:
            sync_cmd.extend(cmd)
        return MagicMock(returncode=0)

    monkeypatch.setattr(bootstrap.subprocess, "run", tracking_run)

    bootstrap.main([])
    assert "--inexact" in sync_cmd, f"launcher sync would prune the [ml] extra: {sync_cmd}"


def test_sync_failure_exits_with_a_readable_message(bootstrap, monkeypatch) -> None:
    """The audience for this script is a non-developer who downloaded a ZIP;
    a raw CalledProcessError traceback is not an actionable failure."""
    monkeypatch.setattr(bootstrap, "find_uv", MagicMock(return_value="/fake/uv"))
    monkeypatch.setattr(bootstrap, "apply_pending_update", MagicMock())
    monkeypatch.setattr(bootstrap, "ensure_linux_runtime_libs", MagicMock())

    def failing_run(cmd, *a, **kw):
        if cmd[1:2] == ["sync"]:
            raise bootstrap.subprocess.CalledProcessError(1, cmd)
        return MagicMock(returncode=0)

    monkeypatch.setattr(bootstrap.subprocess, "run", failing_run)

    with pytest.raises(SystemExit) as excinfo:
        bootstrap.main([])
    assert "Dependency sync failed" in str(excinfo.value)


def test_runtime_lib_probe_retries_for_each_known_library(bootstrap, monkeypatch) -> None:
    """The cv2 import reports only the first missing library, so a box short
    of both libGL and glib needs a second pass -- otherwise bootstrap installs
    libGL, declares success, and the app dies on glib with no guidance."""
    monkeypatch.setattr(bootstrap.sys, "platform", "linux")

    installed = []
    monkeypatch.setattr(
        bootstrap,
        "_try_install_system_pkg",
        lambda feature, auto_install: installed.append(feature) or True,
    )

    errors = [
        "ImportError: libGL.so.1: cannot open shared object file",
        "ImportError: libgthread-2.0.so.0: cannot open shared object file",
    ]

    def fake_run(cmd, *a, **kw):
        if errors:
            return MagicMock(returncode=1, stderr=errors.pop(0))
        return MagicMock(returncode=0, stderr="")

    monkeypatch.setattr(bootstrap.subprocess, "run", fake_run)

    bootstrap.ensure_linux_runtime_libs("/fake/uv", auto_install=True)
    assert installed == ["gl", "glib"]


def test_find_uv_delegates_to_sorter_paths(bootstrap, monkeypatch) -> None:
    """The actual lookup logic is tested in tests/test_paths.py -- it lives
    in sorter/paths.py so dialog_install_torch.py can reuse it after launch.
    This only checks bootstrap.py calls through to it correctly."""
    from sorter import paths

    monkeypatch.setattr(paths, "find_uv", MagicMock(return_value="/sentinel/uv"))
    assert bootstrap.find_uv() == "/sentinel/uv"


def test_requirements_txt_is_gone() -> None:
    """Superseded by pyproject.toml + uv.lock; keeping both would let them
    drift the way requirements.txt and pyproject.toml already had (pygrabber
    was declared in one but not the other)."""
    assert not (ROOT / "requirements.txt").exists()


def test_uv_lock_is_committed() -> None:
    assert (ROOT / "uv.lock").is_file()


def test_python_version_pin_exists() -> None:
    assert (ROOT / ".python-version").is_file()


@pytest.mark.parametrize("shim", ["start.sh", "start.bat"])
def test_shims_are_thin_and_delegate_to_bootstrap(shim: str) -> None:
    text = (ROOT / shim).read_text(encoding="utf-8")
    assert "bootstrap.py" in text
    non_blank_lines = [line for line in text.splitlines() if line.strip()]
    assert len(non_blank_lines) < 25, (
        f"{shim} has grown past a thin shim ({len(non_blank_lines)} non-blank lines) "
        "-- bootstrap logic belongs in bootstrap.py, not duplicated per-platform again."
    )
