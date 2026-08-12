"""Classification history — Qt port of ``sorter.ui.monitor`` (CLAUDE.md §5).

``sorter.ui.monitor.MonitorWindow`` is a separate Toplevel with a fixed-position
tile grid and a "snake" of border colours trailing the newest classification.
This is the same idea reshaped for Qt: a scrollable, newest-first list any
container (dock or expanded feed — the orchestrator decides) can host, so it
grows downward instead of wrapping a fixed grid. The recency fade survives as
a border highlight on the first few entries, using the same neutral
(hue-free) palette roles the rest of the chrome uses for focus/selection —
see CLAUDE.md's "Hue is meaning" note in ``ui/theme.py``'s section.

Subscribes ``run/history`` on ``win.bus`` at construction; payload shape is
``{"image": <BGR ndarray>, "label", "parent", "confidence", "slot"}``, the same
one ``RunController`` posts and ``qtui.app._on_run_history`` already reads for
the one-line feed strip.

Thumbnails are decoded to ``QPixmap`` on arrival, on the main thread: a
classification lands here at most once per case, not in bulk, so there is no
batch of frames to justify a worker thread the way the live camera preview
would.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from PySide6.QtCore import Qt, Signal  # ty: ignore[unresolved-import]
from PySide6.QtGui import QImage, QPixmap  # ty: ignore[unresolved-import]
from PySide6.QtWidgets import (  # ty: ignore[unresolved-import]
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

THUMB = 56
PREVIEW_SIZE = 320
# Fixed, unlike the Tk monitor's window-size-derived capacity: this is a
# scrollable list, not a tiled grid that has to fit a fixed area.
HISTORY_MAX_ENTRIES = 40
EMPTY_TEXT = "Recent classifications will appear here."

# Newest -> oldest border tint for the trailing "snake". Neutral roles only
# (focus/selection brightness, not hue) so recency reads the same way in
# every theme, including the hue-free surfaces the tinted themes keep.
SNAKE_ROLES = ("border_focus", "accent", "accent_dim")


def _bgr_to_pixmap(image: Any, size: int) -> QPixmap:
    """A BGR numpy frame as a square QPixmap; anything else renders blank.

    ``QImage`` borrows the buffer it is handed, so ``.copy()`` cuts the result
    loose — same technique as ``qtui.app.frame_to_image`` and
    ``dialog_image_preview.bgr_to_pixmap``, duplicated rather than imported so
    this module has no dependency on the main window or another dialog.
    """
    if not isinstance(image, np.ndarray) or image.size == 0:
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        return pixmap
    buffer = np.ascontiguousarray(image)
    height, width = buffer.shape[:2]
    qimage = QImage(buffer.data, width, height, buffer.strides[0], QImage.Format.Format_BGR888).copy()
    return QPixmap.fromImage(qimage).scaled(
        size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
    )


def _slot_text(slot: Any) -> str:
    try:
        slot_number = int(slot or 0)
    except (TypeError, ValueError):
        slot_number = 0
    return "Catch-All" if slot_number == 0 else f"Slot {slot_number}"


def _confidence(record: dict[str, Any]) -> float:
    try:
        return float(record.get("confidence", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


class HistoryEntry(QFrame):
    """One classification: thumbnail + label + confidence + slot, click to enlarge."""

    clicked = Signal(object)  # emits its own record dict

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("historyEntry")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.record: dict[str, Any] = {}
        self.below_floor = False

        row = QHBoxLayout(self)
        row.setContentsMargins(6, 6, 6, 6)
        row.setSpacing(8)

        self.thumb_label = QLabel(self)
        self.thumb_label.setFixedSize(THUMB, THUMB)
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self.thumb_label)

        text_col = QVBoxLayout()
        text_col.setSpacing(1)
        self.label_label = QLabel(self)
        self.label_label.setObjectName("historyLabel")
        self.confidence_label = QLabel(self)
        self.confidence_label.setObjectName("historyConfidence")
        self.slot_label = QLabel(self)
        self.slot_label.setObjectName("historySlot")
        text_col.addWidget(self.label_label)
        text_col.addWidget(self.confidence_label)
        text_col.addWidget(self.slot_label)
        row.addLayout(text_col, 1)

    def set_record(self, record: dict[str, Any]) -> None:
        self.record = record
        self.thumb_label.setPixmap(_bgr_to_pixmap(record.get("image"), THUMB))
        label = str(record.get("label") or "(empty)")
        parent = record.get("parent")
        self.label_label.setText(f"{parent} · {label}" if parent else label)
        self.confidence_label.setText(f"{_confidence(record):.0f}%")
        self.slot_label.setText(_slot_text(record.get("slot", 0)))

    def apply_style(self, colors: dict[str, str], *, highlight: str | None) -> None:
        """Card chrome + recency border. Re-run on every push and on a theme switch."""
        border = highlight or colors.get("border", "#3a3a3a")
        width = 2 if highlight else 1
        self.setStyleSheet(
            "QFrame#historyEntry {"
            f"background-color: {colors.get('bg_card', '#272727')};"
            f"border: {width}px solid {border};"
            "border-radius: 4px;"
            "}"
            "QFrame#historyEntry:hover {"
            f"background-color: {colors.get('bg_card_hover', '#333333')};"
            "}"
            "QLabel { background: transparent; }"
        )
        self.label_label.setStyleSheet(f"color: {colors.get('text', '#d4d4d4')}; font-weight: bold;")
        conf_color = colors.get("warning", "#f59e0b") if self.below_floor else colors.get("text_muted", "#9a9a9a")
        self.confidence_label.setStyleSheet(f"color: {conf_color};")
        self.slot_label.setStyleSheet(f"color: {colors.get('text_muted', '#9a9a9a')};")

    def mousePressEvent(self, event: Any) -> None:
        self.clicked.emit(self.record)
        super().mousePressEvent(event)


class HistoryPreviewDialog(QDialog):
    """Enlarged single-record view, opened from a click on a `HistoryEntry`."""

    def __init__(self, parent: QWidget | None, record: dict[str, Any]) -> None:
        super().__init__(parent)
        self.setWindowTitle("Classification detail")
        column = QVBoxLayout(self)

        self.image_label = QLabel(self)
        self.image_label.setObjectName("imagePreview")
        self.image_label.setFixedSize(PREVIEW_SIZE, PREVIEW_SIZE)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setPixmap(_bgr_to_pixmap(record.get("image"), PREVIEW_SIZE))
        column.addWidget(self.image_label)

        label = str(record.get("label") or "(empty)")
        parent_name = record.get("parent")
        self.title_label = QLabel(f"{parent_name} · {label}" if parent_name else label, self)
        title_font = self.title_label.font()
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        column.addWidget(self.title_label)

        self.detail_label = QLabel(f"{_confidence(record):.0f}% · {_slot_text(record.get('slot', 0))}", self)
        self.detail_label.setObjectName("mutedLabel")
        column.addWidget(self.detail_label)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        column.addWidget(buttons)


class HistoryView(QWidget):
    """Scrollable, newest-first classification history with images.

    Construct via :func:`build_history_view`, not directly — that keeps the
    one required argument (the main window) obvious at the call site.
    """

    def __init__(self, win: Any) -> None:
        super().__init__()
        self._win = win
        self._entries: list[HistoryEntry] = []  # newest first
        # Swappable like ImagePreviewDialog's notify/confirm: a test replaces
        # this to observe a click without a modal ever opening.
        self.open_preview: Any = self._open_preview_dialog

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.empty_label = QLabel(EMPTY_TEXT, self)
        self.empty_label.setObjectName("mutedLabel")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)
        outer.addWidget(self.empty_label)

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._holder = QWidget(self._scroll)
        self._list = QVBoxLayout(self._holder)
        self._list.setContentsMargins(6, 6, 6, 6)
        self._list.setSpacing(6)
        self._list.addStretch(1)
        self._scroll.setWidget(self._holder)
        self._scroll.hide()
        outer.addWidget(self._scroll, 1)

        win.bus.subscribe("run/history", self._on_history)

    # ----- record push ---------------------------------------------------------

    def _on_history(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            return
        entry = HistoryEntry(self._holder)
        entry.set_record(payload)
        floor = float(getattr(self._win.config, "run_confidence_floor", 0) or 0)
        entry.below_floor = floor > 0 and _confidence(payload) < floor
        entry.clicked.connect(lambda record: self.open_preview(record))
        self._entries.insert(0, entry)
        self._list.insertWidget(0, entry)

        while len(self._entries) > HISTORY_MAX_ENTRIES:
            oldest = self._entries.pop()
            self._list.removeWidget(oldest)
            oldest.deleteLater()

        self._recolor()
        self._update_empty_state()

    def _recolor(self) -> None:
        colors = self._win.palette_colors
        for index, entry in enumerate(self._entries):
            role = SNAKE_ROLES[index] if index < len(SNAKE_ROLES) else None
            highlight = colors.get(role) if role else None
            entry.apply_style(colors, highlight=highlight)

    def _update_empty_state(self) -> None:
        has_entries = bool(self._entries)
        self.empty_label.setVisible(not has_entries)
        self._scroll.setVisible(has_entries)

    # ----- theme -----------------------------------------------------------------

    def apply_palette(self) -> None:
        """Re-paint every entry from ``win.palette_colors``. Call after a theme switch.

        Entry borders and the confidence warning colour are baked into each
        widget's own stylesheet (same reason ``ui/serial_monitor.py``'s text
        tags need an explicit ``apply_palette`` call rather than a generic
        retheme sweep), so a switch has to re-run this explicitly.
        """
        muted = f"color: {self._win.palette_colors.get('text_muted', '#9a9a9a')};"
        self.empty_label.setStyleSheet(muted)
        self._recolor()

    # ----- preview ---------------------------------------------------------------

    def _open_preview_dialog(self, record: dict[str, Any]) -> None:
        HistoryPreviewDialog(self, record).exec()

    # ----- lifecycle ---------------------------------------------------------------

    def unsubscribe(self) -> None:
        """Detach from the bus. Call when the host (dock or page) is torn down."""
        try:
            self._win.bus.unsubscribe("run/history", self._on_history)
        except Exception:
            pass

    def closeEvent(self, event: Any) -> None:
        self.unsubscribe()
        super().closeEvent(event)


def build_history_view(win: Any) -> HistoryView:
    """Build the classification history widget for ``win`` (a ``QtMainWindow``).

    The caller decides how to host it — a dock beside the serial monitor or an
    expandable feed on the Sort page; both just need one widget instance.
    """
    return HistoryView(win)
