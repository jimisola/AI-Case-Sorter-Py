#!/usr/bin/env python3
"""Cross-platform launcher bootstrap.

Replaces the platform-duplicated logic that used to live separately in
start.sh and start.bat -- both are now three-line shims that just call this
file. Having one implementation in one language means the bootstrap logic
is actually unit-testable, which the bash half never was.

This file has to run on whatever old Python ships with the user's system,
since its whole job is to provision a newer one via uv -- so it targets a
low floor deliberately (see the ruff per-file-ignore for "bootstrap.py" in
pyproject.toml: pyupgrade rewrites would happily rewrite this into
3.12-only syntax and silently break it on exactly the systems it exists to
serve) and imports nothing beyond the standard library.

What it does, in order:
  1. On Linux, offer to install libGL/glib via the system package manager
     if the app's dependencies need them and they're missing. uv's
     provisioned Python bundles Tcl/Tk (verified empirically while building
     this), but graphics libraries like libGL aren't part of a Python
     build -- they're system X11/GPU libraries opencv dlopens at runtime.
  2. Ensure uv is available, installing it via the official installer
     (pinned to UV_VERSION, not "latest") into a project-local .uv/ if it
     isn't already on PATH. The installer itself verifies a sha256 baked in
     at release time for each platform's binary; this script doesn't
     re-invent that.
  3. Apply any staged in-app update BEFORE syncing dependencies, so an
     update that changes pyproject.toml/uv.lock gets its new dependencies
     installed on this same launch. Mirrors the ordering start.sh used to
     encode around --apply-update and the old requirements.txt hash --
     only now there's no hash-based marker at all, because `uv sync`
     reconciles against the venv's actual contents rather than trusting a
     proxy for them.
  4. `uv sync --frozen` -- takes the committed uv.lock as-is and never
     re-resolves on a user's machine, so launches stay deterministic and
     offline-safe. (CI uses `--locked` instead, which fails if the lock has
     drifted from pyproject.toml -- see .github/workflows/build.yml.)
  5. Launch the app: `uv run --frozen python main.py <forwarded args>`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Bump deliberately, not automatically -- re-verify tkinter/libGL behavior
# (see the module docstring) after bumping, the same way this version was
# chosen: by actually running `uv python install` and importing tkinter/cv2,
# not by assuming.
UV_VERSION = "0.12.1"
UV_INSTALL_DIR = ROOT / ".uv" / "bin"


def log(msg: str) -> None:
    print(f"[bootstrap] {msg}")


def warn(msg: str) -> None:
    print(f"[bootstrap] {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# uv itself
# ---------------------------------------------------------------------------


def find_uv() -> str | None:
    # Deferred: sorter is stdlib-only-compatible (see CLAUDE.md), so this is
    # safe to import here, but doing it at module level would be one more
    # thing that could break before this script gets a chance to matter.
    # The logic lives in sorter/paths.py, not duplicated here, because
    # dialog_install_torch.py needs the same lookup after launch (a
    # uv-managed venv doesn't ship pip, so it uses `uv pip install` instead).
    sys.path.insert(0, str(ROOT))
    from sorter.paths import find_uv as _find_uv

    return _find_uv()


def install_uv() -> str:
    log(f"uv not found; installing uv {UV_VERSION} into {UV_INSTALL_DIR} ...")
    UV_INSTALL_DIR.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ)
    env["UV_INSTALL_DIR"] = str(UV_INSTALL_DIR)
    env["UV_NO_MODIFY_PATH"] = "1"
    # Skip the receipt/self-update machinery the official installer sets up
    # for a normal user install -- this copy is project-local and managed by
    # this script, not by `uv self update`.
    env["UV_UNMANAGED_INSTALL"] = str(UV_INSTALL_DIR)

    base = f"https://github.com/astral-sh/uv/releases/download/{UV_VERSION}"
    if os.name == "nt":
        script_url = f"{base}/uv-installer.ps1"
        with urllib.request.urlopen(script_url, timeout=30) as resp:
            script = resp.read().decode("utf-8")
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", "-"],
            input=script,
            text=True,
            env=env,
            check=True,
        )
    else:
        script_url = f"{base}/uv-installer.sh"
        with urllib.request.urlopen(script_url, timeout=30) as resp:
            script = resp.read().decode("utf-8")
        subprocess.run(["sh"], input=script, text=True, env=env, check=True)

    uv = find_uv()
    if uv is None:
        raise SystemExit(
            "[bootstrap] The uv installer ran but uv still isn't where it should be "
            f"({UV_INSTALL_DIR}). Install uv yourself from https://docs.astral.sh/uv/ "
            "and re-run."
        )
    return uv


# ---------------------------------------------------------------------------
# Linux system packages -- not something uv or pip can install
# ---------------------------------------------------------------------------

_PKG_INSTALL = {
    "apt": ["sudo", "apt-get", "install", "-y"],
    "dnf": ["sudo", "dnf", "install", "-y"],
    "pacman": ["sudo", "pacman", "-S", "--noconfirm"],
}
_PKG_NAMES = {
    "apt": {"gl": "libgl1", "glib": "libglib2.0-0"},
    "dnf": {"gl": "mesa-libGL", "glib": "glib2"},
    "pacman": {"gl": "libglvnd", "glib": "glib2"},
}


def _detect_pkg_mgr() -> str | None:
    for binary, name in (("apt-get", "apt"), ("dnf", "dnf"), ("pacman", "pacman")):
        if shutil.which(binary):
            return name
    return None


def _try_install_system_pkg(feature: str, auto_install: bool) -> bool:
    mgr = _detect_pkg_mgr()
    if mgr is None:
        warn(f"Could not detect apt/dnf/pacman -- install the system {feature} library yourself.")
        return False
    pkg = _PKG_NAMES[mgr][feature]
    if not auto_install:
        if not sys.stdin.isatty():
            warn(f"Not running interactively; re-run with --auto to install '{pkg}' via sudo {mgr} automatically.")
            return False
        reply = input(f"[bootstrap] Install '{pkg}' via sudo {mgr}? [y/N] ")
        if reply.strip().lower() not in ("y", "yes"):
            return False
    cmd = _PKG_INSTALL[mgr] + [pkg]
    log(f"Running: {' '.join(cmd)}")
    return subprocess.call(cmd) == 0


def ensure_linux_runtime_libs(uv: str, auto_install: bool) -> None:
    """opencv dlopens libGL/glib at runtime. uv's Python bundles Tcl/Tk, but
    not these -- they're system X11/graphics libraries, not part of a Python
    build. Probed the same way start.sh did: try the import for real, in the
    app's actual environment, and read the failure instead of guessing."""
    if not sys.platform.startswith("linux"):
        return

    probe = subprocess.run(
        [uv, "run", "--frozen", "python", "-c", "import cv2"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if probe.returncode == 0:
        return

    stderr = probe.stderr or ""
    if "libgl" in stderr.lower():
        log("OpenCV needs libGL.so.1 from the system.")
        if not _try_install_system_pkg("gl", auto_install):
            raise SystemExit("[bootstrap] Install the system OpenGL library and re-run.")
    elif "libgthread" in stderr.lower() or "libglib" in stderr.lower():
        log("OpenCV needs glib from the system.")
        if not _try_install_system_pkg("glib", auto_install):
            raise SystemExit("[bootstrap] Install glib2 (apt: libglib2.0-0) and re-run.")
    else:
        raise SystemExit(f"[bootstrap] OpenCV failed to import:\n{stderr}")


# ---------------------------------------------------------------------------
# Staged self-update -- must run before `uv sync` so a staged update's own
# pyproject.toml/uv.lock is what gets synced. sorter.apply_update is
# stdlib-only by design (see its module docstring) specifically so it's
# importable here, before uv has put anything in a venv yet.
# ---------------------------------------------------------------------------


def apply_pending_update() -> None:
    sys.path.insert(0, str(ROOT))
    from sorter.apply_update import main as apply_main

    apply_main()  # always exits 0 internally; a broken updater must never block launch


# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)

    auto_install = os.environ.get("AUTO_INSTALL", "0") in ("1", "true", "yes")
    forward_args = []
    for arg in args:
        if arg in ("--auto", "-y"):
            auto_install = True
        else:
            forward_args.append(arg)

    uv = find_uv() or install_uv()

    apply_pending_update()

    log("Syncing dependencies with uv ...")
    subprocess.run([uv, "sync", "--frozen"], cwd=ROOT, check=True)

    ensure_linux_runtime_libs(uv, auto_install)

    result = subprocess.run([uv, "run", "--frozen", "python", "main.py", *forward_args], cwd=ROOT)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
