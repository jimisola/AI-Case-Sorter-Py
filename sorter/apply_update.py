"""Apply a staged update — the pre-launch half of the updater.

Run by ``start.bat`` / ``start.sh`` via ``python main.py --apply-update``,
*before* the dependency install, so a staged update's own
``requirements.txt`` is the one the launcher then installs.

**This module must stay stdlib-only.** It runs against a virtualenv that may
contain nothing but pip — importing ``requests`` here would break the very
launch it is supposed to fix. That is also why it re-reads ``pending.json``
itself instead of importing ``sorter.updater``.

Why a separate pre-launch step at all: on Windows the venv's ``.pyd``/``.dll``
files (opencv, numpy) are locked while the app is running, so replacing files
in-place is unreliable. Applying before Python loads anything sidesteps
file-locking entirely.

Safety model:

* Everything about to be overwritten or pruned is copied to
  ``<data>/updates/backup/`` first, and restored if any step raises.
* Pruning is confined to ``sorter/`` — a package directory that never holds
  user data — so removed-upstream modules don't linger as importable stale
  code. Every other path is overwrite-only.
* The exit code is **always 0**. A broken updater must never stop the app
  from starting; it reports on stderr and leaves the previous version running.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from . import __version__, paths

# Never overwritten, never pruned, regardless of what an archive contains.
PROTECTED_TOP_LEVEL = frozenset({".git", ".venv", "venv", ".uv", "data", ".env", "portable.txt"})

# Pruning stale files is confined to these directories.
PRUNE_ROOTS = ("sorter",)


def _log(msg: str) -> None:
    print(f"[update] {msg}", file=sys.stderr)


def _meta_path() -> Path:
    return paths.updates_dir() / "pending.json"


def _pending_dir() -> Path:
    return paths.updates_dir() / "pending"


def _backup_dir() -> Path:
    return paths.updates_dir() / "backup"


def _is_protected(rel: Path) -> bool:
    return bool(rel.parts) and rel.parts[0] in PROTECTED_TOP_LEVEL


def _archive_files(root: Path) -> list[Path]:
    """Relative paths of every file in the staged tree, protected ones dropped."""
    out: list[Path] = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if _is_protected(rel):
            continue
        out.append(rel)
    return out


def _stale_files(app_dir: Path, keep: set[Path]) -> list[Path]:
    """Files under PRUNE_ROOTS that the new version no longer ships."""
    out: list[Path] = []
    for root_name in PRUNE_ROOTS:
        root = app_dir / root_name
        if not root.is_dir():
            continue
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            rel = p.relative_to(app_dir)
            if _is_protected(rel) or rel in keep:
                continue
            out.append(rel)
    return out


def _backup(app_dir: Path, backup: Path, rel: Path) -> None:
    dest = backup / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(app_dir / rel, dest)


def _rollback(app_dir: Path, backup: Path, created: list[Path]) -> int:
    """Undo a half-applied update: drop new files, restore saved ones.

    Returns the number of files it could **not** restore. A non-zero count
    means the install is genuinely inconsistent, which the caller reports
    loudly — the backup is left on disk so it can be recovered by hand.
    """
    failures = 0
    for rel in created:
        try:
            (app_dir / rel).unlink(missing_ok=True)
        except OSError:
            failures += 1
    if not backup.is_dir():
        return failures
    for src in backup.rglob("*"):
        if not src.is_file():
            continue
        rel = src.relative_to(backup)
        dest = app_dir / rel
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
        except OSError as exc:
            failures += 1
            _log(f"rollback could not restore {rel}: {exc}")
    return failures


def apply_pending(app_dir: Path | None = None) -> bool:
    """Apply the staged update if there is one. Returns True if applied."""
    root = Path(app_dir) if app_dir is not None else paths.app_root()
    meta_path = _meta_path()
    pending = _pending_dir()

    if not meta_path.is_file() or not pending.is_dir():
        return False

    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        _log(f"staged update metadata is unreadable ({exc}); discarding it.")
        _discard()
        return False

    version = str(meta.get("version") or "")
    if not version:
        _log("staged update has no version; discarding it.")
        _discard()
        return False

    files = _archive_files(pending)
    if not files:
        _log("staged update is empty; discarding it.")
        _discard()
        return False

    keep = set(files)
    stale = _stale_files(root, keep)

    backup = _backup_dir()
    shutil.rmtree(backup, ignore_errors=True)
    backup.mkdir(parents=True, exist_ok=True)

    created: list[Path] = []
    _log(f"applying {__version__} → {version} ({len(files)} files)")
    try:
        for rel in stale:
            _backup(root, backup, rel)
            (root / rel).unlink()

        for rel in files:
            dest = root / rel
            if dest.exists():
                _backup(root, backup, rel)
            else:
                created.append(rel)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(pending / rel, dest)
    except (OSError, shutil.Error) as exc:
        _log(f"failed: {exc}")
        _log("rolling back to the previous version…")
        failures = _rollback(root, backup, created)
        if failures:
            _log(
                f"WARNING: rollback could not restore {failures} file(s). "
                f"A copy of the previous version is at {backup}."
            )
        else:
            _log("rollback complete; keeping the staged update for a later retry.")
        return False

    _discard()
    try:
        (paths.updates_dir() / "last_applied.json").write_text(
            json.dumps(
                {
                    "version": version,
                    "tag": str(meta.get("tag") or version),
                    "from_version": str(meta.get("from_version") or __version__),
                    "pruned": len(stale),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError:
        pass

    _log(f"updated to {version}." + (f" Pruned {len(stale)} stale file(s)." if stale else ""))
    return True


def _discard() -> None:
    shutil.rmtree(_pending_dir(), ignore_errors=True)
    try:
        _meta_path().unlink()
    except OSError:
        pass


def main(argv: list[str] | None = None) -> int:
    """Entry point. Always returns 0 — never block the app from launching."""
    args = list(sys.argv[1:] if argv is None else argv)
    app_dir: Path | None = None
    if "--app-dir" in args:
        idx = args.index("--app-dir")
        if idx + 1 < len(args):
            app_dir = Path(args[idx + 1])

    try:
        # A pre-0.2 install still has its data inside the app folder; move it
        # before looking for staged updates, so both halves agree on where
        # the updates/ tree lives.
        paths.migrate_legacy_data_dir()
        apply_pending(app_dir)
    except Exception as exc:  # noqa: BLE001 — must not stop the launcher
        _log(f"unexpected error: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
