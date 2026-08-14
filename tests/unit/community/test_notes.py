"""The moderator-note acknowledgement store (sorter/community/notes.py).

Acknowledgement is client-side only, so these pin the two properties that
matter: a fetch never un-acknowledges anything, and a note the server stops
sending stays in the history.
"""

from __future__ import annotations

import pytest

from sorter.community import notes as notes_store
from sorter.community.community_api import ModeratorNote
from sorter.data.db import Database
from sorter.data.repository import SettingsRepo

UID = "uid-1"


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "notes.db")
    database.ensure_initialized()
    return database


def note(note_id: int, text: str = "Center the case.", created: str = "2026-08-01T09:00:00") -> ModeratorNote:
    return ModeratorNote(id=note_id, note=text, created=created)


def test_key_is_scoped_per_model() -> None:
    assert notes_store.settings_key(UID) == "community_notes:uid-1"


def test_a_model_with_no_row_has_no_notes(db) -> None:
    assert notes_store.load(db, UID) == []
    assert notes_store.load(None, UID) == []
    assert notes_store.load(db, "") == []


def test_merge_stores_incoming_notes_unacknowledged(db) -> None:
    stored = notes_store.merge(db, UID, [note(1), note(2, "Lighting is dark.")])

    assert [(n.id, n.note, n.acknowledged) for n in stored] == [
        (1, "Center the case.", False),
        (2, "Lighting is dark.", False),
    ]
    assert notes_store.load(db, UID) == stored


def test_merge_updates_text_and_date_but_keeps_the_acknowledgement(db) -> None:
    notes_store.merge(db, UID, [note(1)])
    notes_store.acknowledge(db, UID, [1])

    stored = notes_store.merge(db, UID, [note(1, "Edited text.", "2026-08-02T10:00:00")])

    assert [(n.id, n.note, n.created, n.acknowledged) for n in stored] == [
        (1, "Edited text.", "2026-08-02T10:00:00", True)
    ]


def test_a_note_the_server_stops_sending_stays_as_history(db) -> None:
    notes_store.merge(db, UID, [note(1), note(2, "Gone next time.")])

    stored = notes_store.merge(db, UID, [note(1)])

    assert [n.id for n in stored] == [1, 2]


def test_unacknowledged_filters(db) -> None:
    notes_store.merge(db, UID, [note(1), note(2, "Second")])
    notes_store.acknowledge(db, UID, [1])

    assert [n.id for n in notes_store.unacknowledged(notes_store.load(db, UID))] == [2]


def test_acknowledging_an_unknown_id_changes_nothing(db) -> None:
    notes_store.merge(db, UID, [note(1)])

    assert [n.acknowledged for n in notes_store.acknowledge(db, UID, [99])] == [False]


def test_notes_are_scoped_per_model_uid(db) -> None:
    notes_store.merge(db, UID, [note(1)])
    notes_store.merge(db, "uid-2", [note(5, "Other model")])

    assert [n.id for n in notes_store.load(db, UID)] == [1]
    assert [n.id for n in notes_store.load(db, "uid-2")] == [5]


def test_a_hand_edited_row_cannot_break_the_store(db) -> None:
    """The Sort page reads this on every entry — garbage must be dropped, not raise."""
    SettingsRepo(db).set(
        notes_store.settings_key(UID),
        [
            {"id": 1, "note": "keep", "created": "2026-08-01", "acknowledged": True},
            {"note": "no id"},
            {"id": "x", "note": "bad id"},
            {"id": 2, "note": "   "},
            "not a dict",
            42,
        ],
    )

    assert [(n.id, n.acknowledged) for n in notes_store.load(db, UID)] == [(1, True)]

    SettingsRepo(db).set(notes_store.settings_key(UID), {"not": "a list"})
    assert notes_store.load(db, UID) == []
