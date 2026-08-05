"""In-app updater — check GitHub Releases, download, stage.

Deliberately **git-free**: `git clone`/`git pull` over HTTPS and a release
ZIP over HTTPS have the same trust anchor (TLS to github.com), and at this
repo's size the delta-transfer advantage is worth nothing. Dropping git means
non-developers never install a 60 MB dependency to receive a 1 MB update.

The flow is **stage now, apply at next launch**:

    check_for_update()  →  stage_update()  →  [restart]  →  sorter.apply_update

Staging never touches the app folder. Windows keeps the venv's ``.pyd``/
``.dll`` files (opencv, numpy) locked while the app is running, so replacing
files in-place is unreliable by construction; the launcher applies the staged
tree before Python loads anything. That also means a staged update's own
``requirements.txt`` is in place before the launcher's dependency check runs,
so dependency changes install on the same restart.

Everything in the ``updates/`` tree lives under the data root, which is
outside the app folder (see ``sorter/paths.py``).

Environment overrides:
  ``CASESORTER_UPDATE_REPO``      — ``owner/repo`` to check (default: upstream)
  ``CASESORTER_UPDATE_API_BASE``  — GitHub API base, for testing
  ``CASESORTER_UPDATE_DISABLED``  — ``1`` disables checking entirely
"""

from __future__ import annotations

import json
import os
import shutil
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC
from pathlib import Path, PurePosixPath
from typing import Any

import requests

from . import __version__, paths

DEFAULT_REPO = "sjseth/AI-Case-Sorter-Py"
DEFAULT_API_BASE = "https://api.github.com"

# Settings key (SettingsRepo) for the startup check opt-out.
SETTING_CHECK_ON_STARTUP = "updates.check_on_startup"

# GitHub's unauthenticated API allows 60 requests/hour per IP. A once-per-launch
# check is nowhere near that, but keep the timeout tight so a slow or blocked
# network never delays startup.
CHECK_TIMEOUT = 10
DOWNLOAD_TIMEOUT = 60

# An update archive must look like this repo before we let it near the app
# folder — cheap insurance against a mis-tagged or truncated release.
REQUIRED_ENTRIES = ("main.py", "sorter/__init__.py")

# Refuse absurd archives outright rather than filling the user's disk. The
# source tree is ~1 MB; 200 MB is orders of magnitude of headroom.
MAX_ARCHIVE_BYTES = 200 * 1024 * 1024


class UpdateError(RuntimeError):
    """Raised when a check or download fails in a way worth showing the user."""


@dataclass(frozen=True)
class UpdateInfo:
    """A release newer than what's running."""

    version: str  # normalized, no leading "v"
    tag: str  # the tag as GitHub reports it
    url: str  # ZIP to download
    notes: str = ""  # release body (markdown)
    size: int | None = None
    published_at: str = ""


@dataclass(frozen=True)
class PendingUpdate:
    """A downloaded, verified update waiting for the next launch."""

    version: str
    tag: str
    path: Path
    staged_at: str = ""


# ----- version comparison -----------------------------------------------------


def _parse_version(text: str) -> tuple[tuple[int, ...], int]:
    """Parse ``v1.2.3`` / ``1.2.3-rc1`` into a sortable key.

    Returns ``(numbers, rank)`` where rank is 0 for a pre-release and 1 for a
    final release, so ``1.2.0-rc1 < 1.2.0``. Non-numeric junk is ignored
    rather than raising — a malformed upstream tag should read as "not newer",
    never as a crash on startup.
    """
    s = (text or "").strip().lstrip("vV")
    pre = 0 if any(c in s for c in "-+") else 1
    core = s.split("-", 1)[0].split("+", 1)[0]

    nums: list[int] = []
    for part in core.split("."):
        digits = ""
        for ch in part:
            if not ch.isdigit():
                break
            digits += ch
        if not digits:
            break
        nums.append(int(digits))
    return tuple(nums), pre


def is_newer(candidate: str, current: str) -> bool:
    """True when ``candidate`` is a strictly newer version than ``current``."""
    cand_nums, cand_pre = _parse_version(candidate)
    cur_nums, cur_pre = _parse_version(current)
    if not cand_nums:
        return False
    # Zero-pad so 1.2 and 1.2.0 compare equal.
    width = max(len(cand_nums), len(cur_nums))
    cand_padded = cand_nums + (0,) * (width - len(cand_nums))
    cur_padded = cur_nums + (0,) * (width - len(cur_nums))
    return (cand_padded, cand_pre) > (cur_padded, cur_pre)


def current_version() -> str:
    return __version__


def launcher_path() -> Path | None:
    """The launcher script to re-exec on "Restart Now", if the install has one.

    Running from a bare ``python main.py`` checkout there may not be one — the
    caller then tells the user to relaunch by hand rather than guessing.
    """
    import sys

    name = "start.bat" if sys.platform == "win32" else "start.sh"
    candidate = paths.app_root() / name
    return candidate if candidate.is_file() else None


# ----- checking ---------------------------------------------------------------


def update_repo() -> str:
    return os.environ.get("CASESORTER_UPDATE_REPO") or DEFAULT_REPO


def checks_disabled() -> bool:
    return os.environ.get("CASESORTER_UPDATE_DISABLED", "").strip() in ("1", "true", "yes")


def _api_base() -> str:
    return (os.environ.get("CASESORTER_UPDATE_API_BASE") or DEFAULT_API_BASE).rstrip("/")


def _pick_asset(release: dict[str, Any], tag: str) -> tuple[str, int | None]:
    """Prefer a published ``.zip`` asset; fall back to the tag source archive.

    A purpose-built asset lets the maintainer ship a trimmed archive (no tests,
    no CI config); the source archive means a release with no assets still
    updates correctly.
    """
    for asset in release.get("assets") or []:
        name = str(asset.get("name") or "")
        url = asset.get("browser_download_url")
        if name.lower().endswith(".zip") and url:
            size = asset.get("size")
            return str(url), int(size) if isinstance(size, int) else None
    repo = update_repo()
    return f"https://github.com/{repo}/archive/refs/tags/{tag}.zip", None


def check_for_update(
    *,
    current: str | None = None,
    session: requests.Session | None = None,
    timeout: int = CHECK_TIMEOUT,
) -> UpdateInfo | None:
    """Return the latest release if it's newer than what's running, else None.

    ``/releases/latest`` already excludes drafts and pre-releases, so users on
    the stable channel never see a release candidate.
    """
    if checks_disabled():
        return None

    cur = current or current_version()
    url = f"{_api_base()}/repos/{update_repo()}/releases/latest"
    get = (session or requests).get
    try:
        resp = get(
            url,
            timeout=timeout,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": f"CaseSorter/{cur}",
            },
        )
    except requests.RequestException as exc:
        raise UpdateError(f"Could not reach the update server: {exc}") from exc

    if resp.status_code == 404:
        # No releases published yet — not an error worth surfacing.
        return None
    if resp.status_code != 200:
        raise UpdateError(f"Update check failed (HTTP {resp.status_code}).")

    try:
        release = resp.json()
    except ValueError as exc:
        raise UpdateError("Update server returned a malformed response.") from exc

    tag = str(release.get("tag_name") or "").strip()
    if not tag:
        return None
    version = tag.lstrip("vV")
    if not is_newer(version, cur):
        return None

    asset_url, size = _pick_asset(release, tag)
    return UpdateInfo(
        version=version,
        tag=tag,
        url=asset_url,
        notes=str(release.get("body") or "").strip(),
        size=size,
        published_at=str(release.get("published_at") or ""),
    )


# ----- staging ----------------------------------------------------------------


def _pending_meta_path() -> Path:
    # Sibling of the payload, never inside it: anything in `pending/` gets
    # copied into the app folder verbatim.
    return paths.updates_dir() / "pending.json"


def pending_dir() -> Path:
    return paths.updates_dir() / "pending"


def pending_update() -> PendingUpdate | None:
    """The staged update waiting for the next launch, if any."""
    meta_path = _pending_meta_path()
    payload = pending_dir()
    if not meta_path.is_file() or not payload.is_dir():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    version = str(meta.get("version") or "")
    if not version:
        return None
    return PendingUpdate(
        version=version,
        tag=str(meta.get("tag") or version),
        path=payload,
        staged_at=str(meta.get("staged_at") or ""),
    )


def clear_pending() -> None:
    """Discard any staged update. Safe to call when there isn't one."""
    shutil.rmtree(pending_dir(), ignore_errors=True)
    try:
        _pending_meta_path().unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def _safe_members(zf: zipfile.ZipFile) -> list[tuple[zipfile.ZipInfo, PurePosixPath]]:
    """Validate archive entries and strip GitHub's top-level folder.

    Rejects the same shapes ``model_io`` rejects — ``..`` traversal and
    absolute paths — because this archive is written straight into the app
    folder. GitHub's source archives nest everything under
    ``<repo>-<tag>/``; that single wrapper is stripped so the tree lines up
    with the app folder.
    """
    raw: list[tuple[zipfile.ZipInfo, PurePosixPath]] = []
    total = 0
    for entry in zf.infolist():
        name = entry.filename.replace("\\", "/")
        if name.endswith("/"):
            continue
        if name.startswith("/") or (len(name) > 1 and name[1] == ":"):
            raise UpdateError(f"Update archive contains an absolute path: {entry.filename}")
        rel = PurePosixPath(name.lstrip("/"))
        if any(part == ".." for part in rel.parts):
            raise UpdateError(f"Update archive contains a traversal path: {entry.filename}")
        total += entry.file_size
        if total > MAX_ARCHIVE_BYTES:
            raise UpdateError("Update archive is implausibly large; refusing to extract.")
        raw.append((entry, rel))

    if not raw:
        raise UpdateError("Update archive is empty.")

    # Strip a single common top-level directory, if every entry shares one.
    tops = {rel.parts[0] for _, rel in raw if len(rel.parts) > 1}
    singles = [rel for _, rel in raw if len(rel.parts) == 1]
    if len(tops) == 1 and not singles:
        return [(entry, PurePosixPath(*rel.parts[1:])) for entry, rel in raw]
    return raw


def _download(
    url: str,
    dest: Path,
    progress: Callable[[int, int | None], None] | None,
    session: requests.Session | None,
    timeout: int,
) -> Path:
    """Stream ``url`` to ``dest`` with an atomic ``.tmp`` → ``os.replace``."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    get = (session or requests).get
    try:
        with get(url, stream=True, timeout=timeout) as resp:
            resp.raise_for_status()
            total: int | None = None
            cl = resp.headers.get("Content-Length")
            if cl is not None:
                try:
                    total = int(cl)
                except ValueError:
                    total = None
            done = 0
            with open(tmp, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    done += len(chunk)
                    if done > MAX_ARCHIVE_BYTES:
                        raise UpdateError("Update download exceeded the size limit.")
                    fh.write(chunk)
                    if progress is not None:
                        progress(done, total)
    except requests.RequestException as exc:
        tmp.unlink(missing_ok=True)
        raise UpdateError(f"Download failed: {exc}") from exc
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise

    os.replace(tmp, dest)
    return dest


def stage_update(
    info: UpdateInfo,
    *,
    progress: Callable[[int, int | None], None] | None = None,
    session: requests.Session | None = None,
    timeout: int = DOWNLOAD_TIMEOUT,
) -> PendingUpdate:
    """Download and verify ``info``, leaving it staged for the next launch.

    The app folder is not touched. On any failure the previous staged update
    (if any) is left intact and the partial work is cleaned up.
    """
    updates = paths.updates_dir()
    updates.mkdir(parents=True, exist_ok=True)
    archive = updates / "download.zip"
    staging = updates / "staging"

    shutil.rmtree(staging, ignore_errors=True)
    try:
        _download(info.url, archive, progress, session, timeout)

        if not zipfile.is_zipfile(archive):
            raise UpdateError("Downloaded file is not a valid ZIP archive.")

        with zipfile.ZipFile(archive) as zf:
            members = _safe_members(zf)
            names = {str(rel) for _, rel in members}
            missing = [e for e in REQUIRED_ENTRIES if e not in names]
            if missing:
                raise UpdateError(f"Update archive does not look like the app (missing {', '.join(missing)}).")
            staging.mkdir(parents=True, exist_ok=True)
            for entry, rel in members:
                out = staging / Path(*rel.parts)
                out.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(entry) as src, open(out, "wb") as dst:
                    shutil.copyfileobj(src, dst)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        archive.unlink(missing_ok=True)
        raise

    archive.unlink(missing_ok=True)

    # Swap staging into place last, so `pending/` only ever exists complete.
    clear_pending()
    os.replace(staging, pending_dir())

    from datetime import datetime

    staged_at = datetime.now(UTC).isoformat(timespec="seconds")
    _pending_meta_path().write_text(
        json.dumps(
            {
                "version": info.version,
                "tag": info.tag,
                "staged_at": staged_at,
                "from_version": current_version(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return PendingUpdate(version=info.version, tag=info.tag, path=pending_dir(), staged_at=staged_at)
