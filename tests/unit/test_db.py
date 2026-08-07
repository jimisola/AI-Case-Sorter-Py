"""Tests for the SQLite Database wrapper + JSON migration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sorter.db import DEFAULT_CARTRIDGE_NAME, DEFAULT_MODEL_MODE, SCHEMA_VERSION, Database

from ._legacy_db import LEGACY_MODEL_COLUMNS, columns, write_legacy_db


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


def test_migration_from_v1_adds_columns_and_keeps_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    write_legacy_db(db_path, user_version=1, with_parents_table=False)

    db = Database(db_path)
    db.ensure_initialized()

    assert _user_version(db) == SCHEMA_VERSION

    # The column migration added parent_id to the existing headstamps table.
    assert "parent_id" in columns(db.conn, "headstamps")
    # headstamp_parents and slot_templates did not exist at all, so these come
    # from the idempotent CREATE TABLE IF NOT EXISTS pass, NOT from a column
    # migration — _apply_column_migrations skips a table it has to create.
    assert {"slot", "model_id", "name"} <= columns(db.conn, "headstamp_parents")
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


def test_an_existing_models_table_is_not_migrated_at_all(tmp_path: Path) -> None:
    """Characterization: `models` has no column migration, so it stays legacy.

    `_apply_column_migrations` only ever touches `headstamps.parent_id` and
    `headstamp_parents.slot`, and the schema DDL is CREATE TABLE IF NOT EXISTS,
    so a `models` table that predates `model_type` / `community_model_uid` /
    the feedback-loop columns keeps its old shape forever. Every repository
    read of those columns then raises OperationalError on such a database.

    See issue #44, which proposes making the migration a real ordered ladder.
    Flipping this assertion is the point of that fix.
    """
    db_path = tmp_path / "legacy.db"
    write_legacy_db(db_path, user_version=1, with_parents_table=False)

    db = Database(db_path)
    db.ensure_initialized()

    assert columns(db.conn, "models") == LEGACY_MODEL_COLUMNS
    for missing in ("model_type", "community_model_uid", "feedback_loop_enabled"):
        assert missing not in columns(db.conn, "models")


def test_migration_adds_slot_to_an_existing_headstamp_parents_table(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    write_legacy_db(db_path, user_version=3, with_parents_table=True)

    db = Database(db_path)
    db.ensure_initialized()

    assert _user_version(db) == SCHEMA_VERSION
    assert "slot" in columns(db.conn, "headstamp_parents")

    parents = db.dump_table("headstamp_parents")
    assert len(parents) == 1
    assert parents[0]["name"] == "Winchester"
    assert parents[0]["slot"] == 0, "new NOT NULL column backfills to its default"


def test_migration_is_idempotent_on_an_already_migrated_db(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    write_legacy_db(db_path, user_version=1, with_parents_table=True)

    db = Database(db_path)
    db.ensure_initialized()
    first = {
        table: db.dump_table(table) for table in ("cartridges", "models", "headstamps", "headstamp_parents", "settings")
    }
    cols = {table: columns(db.conn, table) for table in first}

    # A second *process* is the realistic repeat, not a second call on the same
    # object: a fresh Database re-runs connect()'s WAL setup against a file that
    # is already in WAL mode, which the same-object path never exercises.
    reopened = Database(db_path)
    reopened.ensure_initialized()

    assert _user_version(reopened) == SCHEMA_VERSION
    assert {table: reopened.dump_table(table) for table in first} == first
    assert {table: columns(reopened.conn, table) for table in first} == cols


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
