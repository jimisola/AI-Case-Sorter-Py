"""Classification history: parity with ``sorter.ui.monitor``'s image tray.

Everything here runs offscreen against a real SQLite-backed ``Config`` and,
for the end-to-end case, the in-process serial emulator — no display, no
hardware, no network. Mirrors ``test_qt_sort.py``'s fixtures and its
emulator + manual-feed pattern rather than importing from it, so this module
stays independent of another increment's in-flight file.
"""

from __future__ import annotations

import types

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("tkinter")  # sorter.ui.theme (the palettes) imports it

from sorter.hardware.serial_emulator import EMULATED_PORT
from sorter.ml import classifier
from sorter.qtui.history_view import (
    HISTORY_MAX_ENTRIES,
    SNAKE_ROLES,
    HistoryPreviewDialog,
    build_history_view,
)

from .conftest import drain_until

_IMAGE = np.zeros((16, 16, 3), np.uint8)


def history(label: str, confidence: float, slot: int = 1, parent: str | None = None) -> dict:
    """A ``run/history`` payload as ``RunController._post_history`` builds it."""
    return {"image": _IMAGE, "label": label, "parent": parent, "confidence": confidence, "slot": slot}


def push(window, view, label: str, confidence: float, slot: int = 1, parent: str | None = None) -> None:
    window.bus.post("run/history", history(label, confidence, slot, parent))
    window.bus.drain()


# ----- empty state -------------------------------------------------------------


def test_empty_state_shows_hint_and_hides_the_list(window) -> None:
    view = build_history_view(window)

    assert not view.empty_label.isHidden()
    assert view._scroll.isHidden()
    assert view._entries == []


def test_first_entry_reveals_the_list_and_hides_the_hint(window) -> None:
    view = build_history_view(window)

    push(window, view, "9mm FC", 92.0)

    assert view.empty_label.isHidden()
    assert not view._scroll.isHidden()


# ----- rendering -----------------------------------------------------------------


def test_entries_render_newest_first_with_correct_text(window) -> None:
    view = build_history_view(window)

    push(window, view, "9mm", 91.0, slot=1)
    push(window, view, ".223", 82.0, slot=3)
    push(window, view, "45 ACP", 77.0, slot=0)

    labels = [entry.label_label.text() for entry in view._entries]
    assert labels == ["45 ACP", ".223", "9mm"]
    assert view._entries[0].confidence_label.text() == "77%"
    assert view._entries[0].slot_label.text() == "Catch-All"
    assert view._entries[1].slot_label.text() == "Slot 3"
    assert not view._entries[0].thumb_label.pixmap().isNull()


def test_a_parent_classification_prefixes_the_label(window) -> None:
    view = build_history_view(window)

    push(window, view, "FC 12", 88.0, parent="9mm")

    assert view._entries[0].label_label.text() == "9mm · FC 12"


def test_non_dict_payloads_are_ignored(window) -> None:
    view = build_history_view(window)

    window.bus.post("run/history", None)
    window.bus.post("run/history", "not a dict")
    window.bus.drain()

    assert view._entries == []


# ----- cap -------------------------------------------------------------------------


def test_cap_respected_oldest_dropped(window) -> None:
    view = build_history_view(window)

    for index in range(HISTORY_MAX_ENTRIES + 5):
        push(window, view, f"hs{index}", 99.0)

    assert len(view._entries) == HISTORY_MAX_ENTRIES
    labels = [entry.label_label.text() for entry in view._entries]
    assert "hs0" not in labels  # the oldest fell off the end
    assert "hs4" not in labels
    assert labels[0] == f"hs{HISTORY_MAX_ENTRIES + 4}"  # newest survives, at the top
    assert labels[-1] == "hs5"


# ----- recency highlight ("snake") --------------------------------------------------


def test_latest_entry_highlight_moves(window) -> None:
    view = build_history_view(window)
    colors = window.palette_colors

    push(window, view, "first", 99.0)
    assert colors[SNAKE_ROLES[0]] in view._entries[0].styleSheet()

    push(window, view, "second", 99.0)
    assert colors[SNAKE_ROLES[0]] in view._entries[0].styleSheet()
    assert colors[SNAKE_ROLES[1]] in view._entries[1].styleSheet()
    # The now-second-oldest entry no longer carries the newest's highlight.
    assert colors[SNAKE_ROLES[0]] not in view._entries[1].styleSheet()


def test_entries_past_the_snake_carry_no_highlight(window) -> None:
    view = build_history_view(window)
    colors = window.palette_colors

    for index in range(len(SNAKE_ROLES) + 2):
        push(window, view, f"hs{index}", 99.0)

    plain_border = colors.get("border")
    tail = view._entries[len(SNAKE_ROLES)]
    for role in SNAKE_ROLES:
        assert colors[role] not in tail.styleSheet()
    assert plain_border in tail.styleSheet()


# ----- confidence floor coloring ------------------------------------------------------


def test_below_floor_confidence_colored_warning(window, config) -> None:
    config.set_run_confidence_floor(80)
    view = build_history_view(window)

    push(window, view, "9mm", 92.0)
    push(window, view, "unknown", 41.0)

    above, below = view._entries[1], view._entries[0]  # newest first: 41 pushed last
    assert f"color: {window.palette_colors['warning']}" in below.confidence_label.styleSheet()
    assert f"color: {window.palette_colors['text_muted']}" in above.confidence_label.styleSheet()


def test_a_disabled_floor_never_warns(window, config) -> None:
    config.set_run_confidence_floor(0)
    view = build_history_view(window)

    push(window, view, "unknown", 3.0)

    assert f"color: {window.palette_colors['text_muted']}" in view._entries[0].confidence_label.styleSheet()


# ----- click -> preview --------------------------------------------------------------


def test_clicking_an_entry_opens_the_preview_with_its_record(window) -> None:
    view = build_history_view(window)
    push(window, view, "9mm FC", 92.0, slot=2)
    opened = []
    view.open_preview = lambda record: opened.append(record)

    view._entries[0].clicked.emit(view._entries[0].record)

    assert len(opened) == 1
    assert opened[0]["label"] == "9mm FC"
    assert opened[0]["slot"] == 2


def test_preview_dialog_shows_the_record(qapp, window) -> None:
    view = build_history_view(window)
    push(window, view, "9mm FC", 92.0, slot=2, parent="9mm")

    dialog = HistoryPreviewDialog(view, view._entries[0].record)

    assert dialog.title_label.text() == "9mm · 9mm FC"
    assert dialog.detail_label.text() == "92% · Slot 2"
    assert not dialog.image_label.pixmap().isNull()


# ----- theme -------------------------------------------------------------------------


def test_apply_palette_repaints_after_a_theme_switch(window) -> None:
    view = build_history_view(window)
    push(window, view, "9mm", 99.0)
    before = view._entries[0].styleSheet()

    window.set_theme("Comic Book")
    view.apply_palette()

    after = view._entries[0].styleSheet()
    assert after != before
    assert window.palette_colors[SNAKE_ROLES[0]] in after


# ----- lifecycle -----------------------------------------------------------------------


def test_unsubscribe_stops_further_pushes(window) -> None:
    view = build_history_view(window)
    push(window, view, "9mm", 99.0)

    view.unsubscribe()
    window.bus.post("run/history", history("after-unsubscribe", 99.0))
    window.bus.drain()

    assert len(view._entries) == 1
    assert view._entries[0].label_label.text() == "9mm"


# ----- integration: a real manual-feed cycle lands in the widget ---------------------


def test_manual_feed_cycle_lands_in_the_history_view(window, config, monkeypatch) -> None:
    config.add_headstamp("9mm FC", 2)
    monkeypatch.setattr(classifier, "classify_active", lambda *a, **k: ("9mm FC", 97.0))
    # The controller captures the camera it is built with, so stub before connecting.
    window.camera = types.SimpleNamespace(
        capture_frame=lambda: np.zeros((480, 640, 3), np.uint8),
        latest_frame=lambda: None,
        stop=lambda: None,
    )
    view = build_history_view(window)
    window.connect_serial(EMULATED_PORT)

    window.action_buttons["Manual feed"].click()

    assert drain_until(window, lambda: len(view._entries) == 1)
    assert view._entries[0].label_label.text() == "9mm FC"
    assert view._entries[0].slot_label.text() == "Slot 2"
