"""One hand-written pre-SCHEMA_VERSION database, shared by the migration tests.

Three modules used to carry their own copy of a "legacy" schema
(`test_db.py`, `test_headstamp_parents.py`, `test_parent_runtime.py`), which
meant three things to keep in step and three chances to drift.

The tables are deliberately kept to the **minimum the inserts need**. An
earlier version of this helper reproduced the current `models` DDL verbatim,
all 24 columns of it, which made the fixture look like it covered a
`models` migration when no such migration exists — `_apply_column_migrations`
only ever touches `headstamps.parent_id` and `headstamp_parents.slot`. A
genuinely old `models` table is left exactly as it is found. Keeping the
fixture minimal states that honestly and cannot drift out of date, since
there is nothing here to keep in sync. That gap is issue #44.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

# The columns `models` carried before any of the later additions. Everything
# the current DDL has beyond this is what a real legacy DB would be *missing*
# — and would go on missing, because nothing migrates this table.
LEGACY_MODEL_COLUMNS = {"id", "name", "cartridge_id", "model_mode"}


def write_legacy_db(
    path: Path,
    *,
    user_version: int,
    with_parents_table: bool,
    with_parent_id: bool = False,
) -> None:
    """Lay down a pre-SCHEMA_VERSION database by hand.

    Only the tables the column migrations touch are given their *old* shape:
    `headstamps` without `parent_id` (unless `with_parent_id`), and optionally
    a `headstamp_parents` that carries no `slot` of its own. Everything else
    is the minimum the seed rows below need.

    Note `user_version` is essentially decorative: `_apply_column_migrations`
    decides what to do by inspecting the columns that are actually present,
    not by reading the stamp, so the same DB shape migrates identically at any
    starting version. It is set only so the "did the stamp get bumped" assertion
    has somewhere to start from.
    """
    conn = sqlite3.connect(path, isolation_level=None)
    conn.executescript(
        """
        CREATE TABLE cartridges (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL UNIQUE
        );
        CREATE TABLE models (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL,
          cartridge_id INTEGER NOT NULL,
          model_mode TEXT NOT NULL DEFAULT 'convnext_tiny'
        );
        CREATE TABLE settings (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );
        """
    )
    conn.execute(
        "CREATE TABLE headstamps ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  name TEXT NOT NULL,"
        "  model_id INTEGER NOT NULL,"
        "  slot INTEGER NOT NULL DEFAULT 0,"
        + ("  parent_id INTEGER," if with_parent_id else "")
        + "  UNIQUE(model_id, name))"
    )
    if with_parents_table:
        # Old shape: parents existed but carried no slot of their own.
        conn.execute(
            "CREATE TABLE headstamp_parents ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  name TEXT NOT NULL,"
            "  model_id INTEGER NOT NULL,"
            "  UNIQUE(model_id, name))"
        )

    conn.execute("INSERT INTO cartridges(id, name) VALUES (1, '9mm')")
    conn.execute("INSERT INTO models(id, name, cartridge_id, model_mode) VALUES (1, 'Legacy', 1, 'convnext_small')")
    conn.execute("INSERT INTO headstamps(name, model_id, slot) VALUES ('WIN', 1, 3)")
    conn.execute("INSERT INTO headstamps(name, model_id, slot) VALUES ('FC', 1, 5)")
    if with_parents_table:
        conn.execute("INSERT INTO headstamp_parents(id, name, model_id) VALUES (1, 'Winchester', 1)")
    conn.execute("INSERT INTO settings(key, value) VALUES ('api', ?)", (json.dumps({"model": "legacy"}),))
    conn.execute(f"PRAGMA user_version = {user_version}")
    conn.close()


def columns(conn: sqlite3.Connection, table: str) -> set[str]:
    """The column names of `table`.

    `PRAGMA` cannot take a bound parameter in sqlite3, hence the f-string; the
    table name is always a test literal.
    """
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
