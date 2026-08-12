"""Slot cards for the Sort dashboard — one card per physical bin, live counts.

Read-only in the spike: the assignments come from ``Config`` (which reads
headstamps fresh on every access — never cache them here) and editing them is
still the Tk Run tab's job.

Colors come from objectNames matched by ``qtui/theme.py``'s QSS, so a theme
switch repaints the cards with no per-widget stylesheet to re-apply.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from PySide6.QtCore import Qt  # ty: ignore[unresolved-import]
from PySide6.QtWidgets import (  # ty: ignore[unresolved-import]
    QFrame,
    QGridLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

COLUMNS = 3
DEFAULT_SLOT_QUANTITY = 8
CATCH_ALL_HINT = "Unclassified, below floor, unmapped"
EMPTY_HINT = "(no headstamps)"


class SlotCard(QFrame):
    """One bin: its number, the headstamps routed to it, and how many landed."""

    def __init__(self, slot_number: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.slot_number = slot_number
        self.setObjectName("slotCard")
        column = QVBoxLayout(self)
        column.setContentsMargins(10, 8, 10, 8)
        column.setSpacing(2)

        self.title_label = QLabel("Catch-All" if slot_number == 0 else f"Slot #{slot_number}", self)
        self.title_label.setObjectName("slotTitle")
        self.count_label = QLabel("0", self)
        self.count_label.setObjectName("slotCount")
        self.names_label = QLabel(CATCH_ALL_HINT if slot_number == 0 else EMPTY_HINT, self)
        self.names_label.setObjectName("slotNames")
        self.names_label.setWordWrap(True)
        self.names_label.setAlignment(Qt.AlignmentFlag.AlignTop)

        column.addWidget(self.title_label)
        column.addWidget(self.count_label)
        column.addWidget(self.names_label, 1)

    def set_headstamps(self, names: list[str]) -> None:
        if names:
            self.names_label.setText(", ".join(names))
        else:
            self.names_label.setText(CATCH_ALL_HINT if self.slot_number == 0 else EMPTY_HINT)

    def set_count(self, count: int) -> None:
        self.count_label.setText(str(count))


class SlotGrid(QWidget):
    """The card grid, rebuilt from ``Config`` and counted up from run events."""

    def __init__(self, config: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.config = config
        self.cards: dict[int, SlotCard] = {}
        self._counts: dict[int, int] = defaultdict(int)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._holder = QWidget(self._scroll)
        self._grid = QGridLayout(self._holder)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(8)
        self._scroll.setWidget(self._holder)
        outer.addWidget(self._scroll)

        self.refresh_assignments()

    # ----- assignments --------------------------------------------------------

    def refresh_assignments(self) -> None:
        """Re-read the live Config: slot count first, then what routes where."""
        self._ensure_cards(self._slot_count())
        slot_map = self._slot_map()
        for slot, card in self.cards.items():
            card.set_headstamps(sorted(slot_map.get(slot, []), key=str.casefold))

    def _slot_count(self) -> int:
        # Total physical slots INCLUDING the catch-all, so 8 means 0..7.
        return max(1, int(self.config.serial.get("slot_quantity", DEFAULT_SLOT_QUANTITY)))

    def _slot_map(self) -> dict[int, list[str]]:
        """slot -> labels, in whichever routing mode the config is in.

        Same three branches as the Tk Run tab: package mode is many-to-many,
        parent mode routes children through their parent's slot, and the plain
        case is the per-headstamp assignment.
        """
        slot_map: dict[int, list[str]] = defaultdict(list)
        if self.config.run_package_mode:
            for slot, names in self.config.package_slot_map().items():
                if int(slot) > 0 and names:
                    slot_map[int(slot)].extend(names)
            return slot_map

        parents = self.config.parents_with_slots()
        if parents and self.config.use_parent_classifications:
            for parent in parents:
                if int(parent["slot"]) > 0:
                    slot_map[int(parent["slot"])].append(parent["name"])
            for entry in self.config.headstamps_with_parents():
                if entry["parent_id"] is None and int(entry["slot"]) > 0:
                    slot_map[int(entry["slot"])].append(entry["name"])
            return slot_map

        for entry in self.config.headstamps:
            name = entry.get("name")
            slot = int(entry.get("slot", 0))
            if name and slot > 0:
                slot_map[slot].append(name)
        return slot_map

    def _ensure_cards(self, slot_count: int) -> None:
        if len(self.cards) == slot_count:
            return
        for card in self.cards.values():
            self._grid.removeWidget(card)
            card.deleteLater()
        self.cards = {}
        for slot in range(slot_count):
            card = SlotCard(slot, self._holder)
            card.set_count(self._counts[slot])
            self._grid.addWidget(card, slot // COLUMNS, slot % COLUMNS)
            self.cards[slot] = card
        # Absorb the leftover space so cards keep their natural height.
        self._grid.setRowStretch(self._grid.rowCount(), 1)

    # ----- counts -------------------------------------------------------------

    def increment(self, slot: int) -> int:
        """Tally one sorted case into ``slot``; returns its new count."""
        slot = int(slot)
        self._counts[slot] += 1
        card = self.cards.get(slot)
        if card is not None:
            card.set_count(self._counts[slot])
        return self._counts[slot]

    def count(self, slot: int) -> int:
        return self._counts[int(slot)]

    def reset_counts(self) -> None:
        self._counts.clear()
        for card in self.cards.values():
            card.set_count(0)
