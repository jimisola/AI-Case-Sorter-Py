"""Tests for the update check + staging half of the updater."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
import requests

from sorter import updater
from sorter.updater import UpdateError, UpdateInfo


@pytest.fixture(autouse=True)
def _isolated_data_root(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CASESORTER_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("CASESORTER_UPDATE_DISABLED", raising=False)
    monkeypatch.delenv("CASESORTER_UPDATE_REPO", raising=False)
    monkeypatch.delenv("CASESORTER_UPDATE_API_BASE", raising=False)
    return tmp_path


# ----- version comparison -----------------------------------------------------


@pytest.mark.parametrize(
    "candidate,current,expected",
    [
        ("0.2.0", "0.1.0", True),
        ("v0.2.0", "0.1.0", True),
        ("0.1.0", "0.1.0", False),
        ("0.1.0", "0.2.0", False),
        ("1.0.0", "0.9.9", True),
        ("0.10.0", "0.9.0", True),  # numeric, not lexicographic
        ("0.2", "0.2.0", False),  # zero-padded to equal
        ("0.2.1", "0.2", True),
        ("0.2.0-rc1", "0.1.0", True),  # prerelease still newer than 0.1.0
        ("0.2.0-rc1", "0.2.0", False),  # ...but older than its own release
        ("0.2.0", "0.2.0-rc1", True),
        ("garbage", "0.1.0", False),  # malformed tag reads as "not newer"
        ("", "0.1.0", False),
    ],
)
def test_is_newer(candidate: str, current: str, expected: bool) -> None:
    assert updater.is_newer(candidate, current) is expected


# ----- checking ---------------------------------------------------------------


class _Resp:
    def __init__(self, status: int, payload=None) -> None:
        self.status_code = status
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def _release(tag: str = "v0.9.0", assets=None, body: str = "notes") -> dict:
    return {"tag_name": tag, "body": body, "assets": assets or [], "published_at": "2026-01-01T00:00:00Z"}


def test_check_returns_info_when_newer(monkeypatch) -> None:
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp(200, _release()))
    info = updater.check_for_update(current="0.1.0")
    assert info is not None
    assert info.version == "0.9.0"
    assert info.tag == "v0.9.0"
    assert info.notes == "notes"
    # No .zip asset published → fall back to the tag source archive.
    assert info.url.endswith("/archive/refs/tags/v0.9.0.zip")


def test_check_prefers_the_named_app_asset(monkeypatch) -> None:
    assets = [
        {"name": "checksums.txt", "browser_download_url": "https://x/c.txt"},
        {"name": "ai-case-sorter-py-0.9.0.zip", "browser_download_url": "https://x/app.zip", "size": 4242},
    ]
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp(200, _release(assets=assets)))
    info = updater.check_for_update(current="0.1.0")
    assert info is not None
    assert info.url == "https://x/app.zip"
    assert info.size == 4242


def test_check_ignores_a_stray_zip_asset(monkeypatch) -> None:
    """A wheel/sdist-publishing release also carries other .zip-ish files
    (e.g. a Windows packaging artifact, or just an unrelated attachment).
    Only the exact expected app-archive name should ever be picked -- "first
    asset ending in .zip" would let any of these silently become the tree
    unpacked over the app folder."""
    assets = [
        {"name": "some-unrelated-thing.zip", "browser_download_url": "https://x/bogus.zip", "size": 999},
    ]
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp(200, _release(assets=assets)))
    info = updater.check_for_update(current="0.1.0")
    assert info is not None
    # Falls through to the tag source archive, not the stray zip.
    assert info.url.endswith("/archive/refs/tags/v0.9.0.zip")


def test_check_ignores_the_wheel_and_sdist(monkeypatch) -> None:
    """Confirms the real-world case this hardening exists for: a release
    with a wheel and sdist (attached by the publish workflow) but no
    purpose-built app archive falls back correctly, exactly as a release
    with no assets at all always has."""
    assets = [
        {"name": "ai_case_sorter_py-0.9.0-py3-none-any.whl", "browser_download_url": "https://x/w.whl"},
        {"name": "ai_case_sorter_py-0.9.0.tar.gz", "browser_download_url": "https://x/s.tar.gz"},
    ]
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp(200, _release(assets=assets)))
    info = updater.check_for_update(current="0.1.0")
    assert info is not None
    assert info.url.endswith("/archive/refs/tags/v0.9.0.zip")


def test_check_returns_none_when_current(monkeypatch) -> None:
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp(200, _release(tag="v0.1.0")))
    assert updater.check_for_update(current="0.1.0") is None


def test_check_returns_none_when_no_releases(monkeypatch) -> None:
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp(404))
    assert updater.check_for_update(current="0.1.0") is None


def test_check_disabled_by_env(monkeypatch) -> None:
    monkeypatch.setenv("CASESORTER_UPDATE_DISABLED", "1")

    def _boom(*a, **k):
        raise AssertionError("network must not be touched when disabled")

    monkeypatch.setattr(requests, "get", _boom)
    assert updater.check_for_update(current="0.1.0") is None


def test_check_raises_on_server_error(monkeypatch) -> None:
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp(500))
    with pytest.raises(UpdateError):
        updater.check_for_update(current="0.1.0")


def test_check_wraps_network_failure(monkeypatch) -> None:
    def _boom(*a, **k):
        raise requests.ConnectionError("no route to host")

    monkeypatch.setattr(requests, "get", _boom)
    with pytest.raises(UpdateError, match="Could not reach"):
        updater.check_for_update(current="0.1.0")


# ----- staging ----------------------------------------------------------------


def _zip_bytes(entries: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return buf.getvalue()


def _good_archive(prefix: str = "AI-Case-Sorter-Py-v0.9.0/") -> bytes:
    return _zip_bytes(
        {
            f"{prefix}main.py": "print('new')\n",
            f"{prefix}sorter/__init__.py": '__version__ = "0.9.0"\n',
            f"{prefix}sorter/updater.py": "# new\n",
            f"{prefix}requirements.txt": "requests\n",
        }
    )


class _StreamResp:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload
        self.headers = {"Content-Length": str(len(payload))}

    def raise_for_status(self) -> None:
        return None

    def iter_content(self, chunk_size: int = 1):
        for i in range(0, len(self._payload), chunk_size):
            yield self._payload[i : i + chunk_size]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _serve(monkeypatch, payload: bytes) -> None:
    monkeypatch.setattr(requests, "get", lambda *a, **k: _StreamResp(payload))


def _info() -> UpdateInfo:
    return UpdateInfo(version="0.9.0", tag="v0.9.0", url="https://x/app.zip")


def test_stage_extracts_and_strips_the_github_wrapper(monkeypatch) -> None:
    _serve(monkeypatch, _good_archive())
    pending = updater.stage_update(_info())

    assert pending.version == "0.9.0"
    assert (pending.path / "main.py").read_text(encoding="utf-8") == "print('new')\n"
    assert (pending.path / "sorter" / "__init__.py").is_file()
    # The wrapper directory must be gone, not nested.
    assert not (pending.path / "AI-Case-Sorter-Py-v0.9.0").exists()


def test_stage_records_pending_metadata(monkeypatch) -> None:
    _serve(monkeypatch, _good_archive())
    updater.stage_update(_info())

    found = updater.pending_update()
    assert found is not None
    assert found.version == "0.9.0"
    assert found.tag == "v0.9.0"
    assert found.staged_at

    meta = json.loads((updater.paths.updates_dir() / "pending.json").read_text())
    assert meta["from_version"] == updater.current_version()


def test_stage_reports_progress(monkeypatch) -> None:
    _serve(monkeypatch, _good_archive())
    seen: list[tuple[int, int | None]] = []
    updater.stage_update(_info(), progress=lambda d, t: seen.append((d, t)))
    assert seen
    assert seen[-1][0] == seen[-1][1]  # finished at 100%


def test_stage_rejects_traversal_entries(monkeypatch) -> None:
    _serve(
        monkeypatch,
        _zip_bytes(
            {
                "pkg/main.py": "x",
                "pkg/sorter/__init__.py": "x",
                "pkg/../../evil.py": "pwned",
            }
        ),
    )
    with pytest.raises(UpdateError, match="traversal"):
        updater.stage_update(_info())
    assert updater.pending_update() is None


def test_stage_rejects_an_archive_that_is_not_the_app(monkeypatch) -> None:
    _serve(monkeypatch, _zip_bytes({"wrong/readme.txt": "hello"}))
    with pytest.raises(UpdateError, match="does not look like the app"):
        updater.stage_update(_info())
    assert updater.pending_update() is None


def test_stage_rejects_a_non_zip(monkeypatch) -> None:
    _serve(monkeypatch, b"definitely not a zip")
    with pytest.raises(UpdateError, match="not a valid ZIP"):
        updater.stage_update(_info())
    assert updater.pending_update() is None


def test_failed_stage_leaves_the_previous_pending_update_intact(monkeypatch) -> None:
    _serve(monkeypatch, _good_archive())
    updater.stage_update(_info())
    assert updater.pending_update() is not None

    _serve(monkeypatch, b"corrupt")
    with pytest.raises(UpdateError):
        updater.stage_update(UpdateInfo(version="1.0.0", tag="v1.0.0", url="https://x/b.zip"))

    still = updater.pending_update()
    assert still is not None and still.version == "0.9.0"


def test_stage_leaves_no_scratch_files_behind(monkeypatch) -> None:
    _serve(monkeypatch, _good_archive())
    updater.stage_update(_info())
    updates = updater.paths.updates_dir()
    assert not (updates / "download.zip").exists()
    assert not (updates / "staging").exists()


def test_clear_pending(monkeypatch) -> None:
    _serve(monkeypatch, _good_archive())
    updater.stage_update(_info())
    updater.clear_pending()
    assert updater.pending_update() is None


def test_pending_update_none_without_metadata() -> None:
    assert updater.pending_update() is None
