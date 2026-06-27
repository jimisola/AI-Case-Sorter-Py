"""Tests for the portable-data path layout."""
from __future__ import annotations

import os
from pathlib import Path

from sorter import paths


def test_default_root_is_inside_oss_client_folder(monkeypatch) -> None:
    monkeypatch.delenv("CASESORTER_DATA_DIR", raising=False)
    root = paths.app_data_dir()
    # paths.py lives at `<oss>/sorter/paths.py`; the data root must be `<oss>/data`.
    expected = Path(paths.__file__).resolve().parent.parent / "data"
    assert root == expected


def test_env_override(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CASESORTER_DATA_DIR", str(tmp_path))
    assert paths.app_data_dir() == tmp_path
    assert paths.config_dir() == tmp_path / "config"
    assert paths.db_path() == tmp_path / "config" / "casesorter.db"
    assert paths.token_cache_path() == tmp_path / "config" / "msal_cache.bin"
    assert paths.models_dir() == tmp_path / "models"


def test_per_model_layout(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CASESORTER_DATA_DIR", str(tmp_path))
    mid = 7
    assert paths.model_dir(mid) == tmp_path / "models" / "7"
    assert paths.model_images_dir(mid) == tmp_path / "models" / "7" / "images"
    assert paths.model_feedback_dir(mid) == tmp_path / "models" / "7" / "feedback_images"
    assert paths.model_trained_dir(mid) == tmp_path / "models" / "7" / "trainedmodel"
    assert paths.model_trained_path(mid) == tmp_path / "models" / "7" / "trainedmodel" / "7.pth"


def test_ensure_directories_creates_top_level(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CASESORTER_DATA_DIR", str(tmp_path))
    paths.ensure_directories()
    assert paths.config_dir().is_dir()
    assert paths.models_dir().is_dir()


def test_ensure_model_subtree(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CASESORTER_DATA_DIR", str(tmp_path))
    paths.ensure_model_subtree(42)
    assert paths.model_images_dir(42).is_dir()
    assert paths.model_trained_dir(42).is_dir()


def test_export_temp_dir_is_app_local(monkeypatch, tmp_path: Path) -> None:
    # The share/export scratch folder must live under the app's own data dir,
    # never the OS temp dir (which on Windows can be locked or cleaned mid-write).
    monkeypatch.setenv("CASESORTER_DATA_DIR", str(tmp_path))
    assert paths.export_temp_dir() == tmp_path / "tmp"
    assert paths.export_temp_dir().parent == paths.app_data_dir()
