"""Tests for the SQLite Database wrapper + JSON migration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sorter.db import DEFAULT_CARTRIDGE_NAME, DEFAULT_MODEL_MODE, Database


def test_fresh_db_seeds_default_cartridge_and_model(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    db.ensure_initialized()

    cartridges = db.dump_table("cartridges")
    models = db.dump_table("models")
    settings = {r["key"]: json.loads(r["value"]) for r in db.dump_table("settings")}

    assert len(cartridges) == 1
    assert cartridges[0]["name"] == DEFAULT_CARTRIDGE_NAME
    assert len(models) == 1
    assert models[0]["model_mode"] == DEFAULT_MODEL_MODE
    # The seeded model is NOT auto-activated — fresh install defaults to AI Config mode.
    assert "default_model_id" not in settings


def test_ensure_initialized_is_idempotent(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    db.ensure_initialized()
    first_models = db.dump_table("models")
    db.ensure_initialized()  # second call must not duplicate
    second_models = db.dump_table("models")
    assert first_models == second_models


def test_migration_from_legacy_json(tmp_path: Path) -> None:
    legacy = tmp_path / "config.json"
    legacy.write_text(
        json.dumps(
            {
                "api": {"endpoint_url": "http://example.com", "model": "9mm-comp"},
                "serial": {"port": "COM3", "baud": 115200},
                "image_proc": {"strategy": "hough"},
                "camera": {"device_index": 1},
                "headstamps": [
                    {"name": "WIN", "slot": 3},
                    {"name": "FC", "slot": 5},
                ],
            }
        )
    )

    db = Database(tmp_path / "test.db")
    db.ensure_initialized(legacy_config_json=legacy)

    cartridges = db.dump_table("cartridges")
    models = db.dump_table("models")
    headstamps = db.dump_table("headstamps")
    settings = {r["key"]: json.loads(r["value"]) for r in db.dump_table("settings")}

    assert len(cartridges) == 1
    assert len(models) == 1
    assert models[0]["name"] == "9mm-comp"
    assert {h["name"] for h in headstamps} == {"WIN", "FC"}
    assert {h["slot"] for h in headstamps} == {3, 5}
    assert settings["api"]["endpoint_url"] == "http://example.com"
    assert settings["serial"]["port"] == "COM3"
    assert settings["camera"]["device_index"] == 1
    # Migration does not set an active model — AI Config mode is the default.
    assert "default_model_id" not in settings

    assert not legacy.exists(), "legacy JSON should be renamed to .bak"
    assert legacy.with_suffix(".json.bak").exists()


def test_migration_corrupt_json_falls_back_to_seed(tmp_path: Path) -> None:
    legacy = tmp_path / "config.json"
    legacy.write_text("{not json")

    db = Database(tmp_path / "test.db")
    db.ensure_initialized(legacy_config_json=legacy)

    cartridges = db.dump_table("cartridges")
    assert len(cartridges) == 1
    assert cartridges[0]["name"] == DEFAULT_CARTRIDGE_NAME


def test_foreign_key_constraint_enforced(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    db.ensure_initialized()

    with pytest.raises(Exception):  # IntegrityError
        db.conn.execute("INSERT INTO models(name, cartridge_id, model_mode) VALUES ('bad', 9999, 'convnext_tiny')")


def test_model_mode_check_constraint(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    db.ensure_initialized()
    cart_id = db.conn.execute("SELECT id FROM cartridges LIMIT 1").fetchone()["id"]
    with pytest.raises(Exception):
        db.conn.execute(
            "INSERT INTO models(name, cartridge_id, model_mode) VALUES (?, ?, ?)",
            ("bad-mode", cart_id, "resnet50"),
        )
