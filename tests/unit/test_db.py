"""Tests for the SQLite Database wrapper + JSON migration."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from sorter.db import DEFAULT_CARTRIDGE_NAME, DEFAULT_MODEL_MODE, SCHEMA_VERSION, Database


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


def _user_version(db: Database) -> int:
    return db.conn.execute("PRAGMA user_version").fetchone()[0]


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _write_legacy_db(path: Path, *, user_version: int, with_parents_table: bool) -> None:
    """Lay down a pre-SCHEMA_VERSION database by hand.

    Only the tables the column migrations touch are given their *old* shape:
    `headstamps` without `parent_id`, and (optionally) `headstamp_parents`
    without `slot`. Everything else is close enough to current that the
    idempotent DDL leaves it alone.
    """
    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(
        """
        CREATE TABLE cartridges (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL UNIQUE
        );
        CREATE TABLE models (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL,
          cartridge_id INTEGER NOT NULL REFERENCES cartridges(id) ON DELETE RESTRICT,
          model_mode TEXT NOT NULL
            CHECK(model_mode IN ('convnext_tiny','convnext_small','convnext_base','convnext_large')),
          model_type TEXT NOT NULL DEFAULT 'Standard'
            CHECK(model_type IN ('Standard','ReadOnly','CommunityManaged')),
          community_model_uid TEXT,
          model_version INTEGER NOT NULL DEFAULT 1,
          enable_image_processing INTEGER NOT NULL DEFAULT 1,
          image_processing_json TEXT,
          training_config_json TEXT,
          ai_model_config_json TEXT,
          use_primer_mask INTEGER NOT NULL DEFAULT 0,
          hide_primer INTEGER NOT NULL DEFAULT 1,
          primer_mask_size INTEGER NOT NULL DEFAULT 135,
          last_training_date TEXT,
          last_training_duration INTEGER NOT NULL DEFAULT 0,
          trained_image_count INTEGER NOT NULL DEFAULT 0,
          training_confusion_table TEXT,
          feedback_loop_enabled INTEGER NOT NULL DEFAULT 0,
          feedback_loop_confidence_floor INTEGER NOT NULL DEFAULT 95,
          feedback_loop_upload_mode TEXT NOT NULL DEFAULT 'Manual',
          model_path TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        -- Old shape: no parent_id column.
        CREATE TABLE headstamps (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL,
          model_id INTEGER NOT NULL REFERENCES models(id) ON DELETE CASCADE,
          slot INTEGER NOT NULL DEFAULT 0,
          UNIQUE(model_id, name)
        );
        CREATE TABLE settings (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );
        """
    )
    if with_parents_table:
        # Old shape: parents existed but carried no slot of their own.
        conn.execute(
            "CREATE TABLE headstamp_parents ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  name TEXT NOT NULL,"
            "  model_id INTEGER NOT NULL REFERENCES models(id) ON DELETE CASCADE,"
            "  UNIQUE(model_id, name))"
        )

    cart_id = conn.execute("INSERT INTO cartridges(name) VALUES ('9mm')").lastrowid
    model_id = conn.execute(
        "INSERT INTO models(name, cartridge_id, model_mode) VALUES ('Legacy', ?, 'convnext_small')",
        (cart_id,),
    ).lastrowid
    conn.execute("INSERT INTO headstamps(name, model_id, slot) VALUES ('WIN', ?, 3)", (model_id,))
    conn.execute("INSERT INTO headstamps(name, model_id, slot) VALUES ('FC', ?, 5)", (model_id,))
    if with_parents_table:
        conn.execute("INSERT INTO headstamp_parents(name, model_id) VALUES ('Winchester', ?)", (model_id,))
    conn.execute("INSERT INTO settings(key, value) VALUES ('api', ?)", (json.dumps({"model": "legacy"}),))
    conn.execute(f"PRAGMA user_version = {user_version}")
    conn.close()


def test_migration_from_v1_adds_columns_and_keeps_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    _write_legacy_db(db_path, user_version=1, with_parents_table=False)

    db = Database(db_path)
    db.ensure_initialized()

    assert _user_version(db) == SCHEMA_VERSION

    # The column migration added parent_id; the DDL created the tables that
    # did not exist yet.
    assert "parent_id" in _columns(db.conn, "headstamps")
    assert {"slot", "model_id", "name"} <= _columns(db.conn, "headstamp_parents")
    assert db.conn.execute("SELECT COUNT(*) FROM slot_templates").fetchone()[0] == 0

    # Pre-existing data survives untouched, with a sane default for the new column.
    headstamps = {h["name"]: h for h in db.dump_table("headstamps")}
    assert set(headstamps) == {"WIN", "FC"}
    assert headstamps["WIN"]["slot"] == 3
    assert headstamps["FC"]["slot"] == 5
    assert headstamps["WIN"]["parent_id"] is None

    models = db.dump_table("models")
    assert len(models) == 1, "an existing DB must not be re-seeded"
    assert models[0]["name"] == "Legacy"
    assert models[0]["model_mode"] == "convnext_small"

    settings = {r["key"]: json.loads(r["value"]) for r in db.dump_table("settings")}
    assert settings["api"]["model"] == "legacy"


def test_migration_adds_slot_to_an_existing_headstamp_parents_table(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    _write_legacy_db(db_path, user_version=3, with_parents_table=True)

    db = Database(db_path)
    db.ensure_initialized()

    assert _user_version(db) == SCHEMA_VERSION
    assert "slot" in _columns(db.conn, "headstamp_parents")

    parents = db.dump_table("headstamp_parents")
    assert len(parents) == 1
    assert parents[0]["name"] == "Winchester"
    assert parents[0]["slot"] == 0, "new NOT NULL column backfills to its default"


def test_migration_is_idempotent_on_an_already_migrated_db(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    _write_legacy_db(db_path, user_version=1, with_parents_table=True)

    db = Database(db_path)
    db.ensure_initialized()
    first = {
        table: db.dump_table(table) for table in ("cartridges", "models", "headstamps", "headstamp_parents", "settings")
    }
    columns = {table: _columns(db.conn, table) for table in first}

    db.ensure_initialized()

    assert _user_version(db) == SCHEMA_VERSION
    assert {table: db.dump_table(table) for table in first} == first
    assert {table: _columns(db.conn, table) for table in first} == columns


def test_ensure_initialized_does_not_downgrade_user_version(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    db.ensure_initialized()
    db.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 10}")
    db.ensure_initialized()
    # The bump is guarded by `current_version < SCHEMA_VERSION`, so a DB
    # written by a newer build keeps its stamp.
    assert _user_version(db) == SCHEMA_VERSION + 10


def test_model_mode_check_constraint(tmp_path: Path) -> None:
    db = Database(tmp_path / "test.db")
    db.ensure_initialized()
    cart_id = db.conn.execute("SELECT id FROM cartridges LIMIT 1").fetchone()["id"]
    with pytest.raises(Exception):
        db.conn.execute(
            "INSERT INTO models(name, cartridge_id, model_mode) VALUES (?, ?, ?)",
            ("bad-mode", cart_id, "resnet50"),
        )
