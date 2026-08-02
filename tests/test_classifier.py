"""Tests for the classify dispatcher."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np

from sorter import classifier
from sorter.db import Database
from sorter.repository import ModelRepo, SettingsRepo


def _seed_db(tmp_path: Path) -> Database:
    db = Database(tmp_path / "x.db")
    db.ensure_initialized()
    return db


def _activate_seeded_model(db: Database) -> int:
    seed = ModelRepo(db).list()[0]
    SettingsRepo(db).set_active_model_id(seed.id)
    return seed.id


def test_falls_back_to_http_when_no_active_model(tmp_path: Path) -> None:
    """AI Config mode (no active model) routes to HTTP."""
    db = _seed_db(tmp_path)
    image = np.zeros((10, 10, 3), dtype=np.uint8)
    with patch("sorter.classifier.api_client.classify", return_value=("X", 42.0)) as m:
        with patch("sorter.classifier.local_inference.classify") as m_local:
            result = classifier.classify_active(image, ["A"], {"endpoint_url": "http://x"}, db)
    assert result == ("X", 42.0)
    m.assert_called_once()
    m_local.assert_not_called()


def test_falls_back_to_http_when_active_model_has_no_path(tmp_path: Path) -> None:
    db = _seed_db(tmp_path)
    _activate_seeded_model(db)
    image = np.zeros((10, 10, 3), dtype=np.uint8)
    with patch("sorter.classifier.api_client.classify", return_value=("X", 42.0)) as m:
        with patch("sorter.classifier.local_inference.classify") as m_local:
            result = classifier.classify_active(image, ["A"], {"endpoint_url": "http://x"}, db)
    assert result == ("X", 42.0)
    m.assert_called_once()
    m_local.assert_not_called()


def test_uses_local_when_active_model_has_path(tmp_path: Path) -> None:
    db = _seed_db(tmp_path)
    active_id = _activate_seeded_model(db)
    fake_model_file = tmp_path / "fake.pth"
    fake_model_file.write_bytes(b"dummy")
    model = ModelRepo(db).get(active_id)
    model.model_path = str(fake_model_file)
    ModelRepo(db).update(model)

    image = np.zeros((10, 10, 3), dtype=np.uint8)
    with patch("sorter.classifier.local_inference.classify", return_value=("LOCAL_X", 90.0)) as m_local:
        with patch("sorter.classifier.api_client.classify") as m_http:
            result = classifier.classify_active(image, [], {}, db)
    assert result == ("LOCAL_X", 90.0)
    m_local.assert_called_once()
    m_http.assert_not_called()


def test_no_db_falls_back_to_http(tmp_path: Path) -> None:
    image = np.zeros((10, 10, 3), dtype=np.uint8)
    with patch("sorter.classifier.api_client.classify", return_value=("Y", 50.0)) as m:
        result = classifier.classify_active(image, [], {}, None)
    assert result == ("Y", 50.0)


def test_missing_model_file_falls_back_to_http(tmp_path: Path) -> None:
    db = _seed_db(tmp_path)
    active_id = _activate_seeded_model(db)
    model = ModelRepo(db).get(active_id)
    model.model_path = str(tmp_path / "does_not_exist.pth")
    ModelRepo(db).update(model)

    image = np.zeros((10, 10, 3), dtype=np.uint8)
    with patch("sorter.classifier.api_client.classify", return_value=("Z", 33.0)) as m:
        with patch("sorter.classifier.local_inference.classify") as m_local:
            result = classifier.classify_active(image, [], {}, db)
    assert result == ("Z", 33.0)
    m_local.assert_not_called()
