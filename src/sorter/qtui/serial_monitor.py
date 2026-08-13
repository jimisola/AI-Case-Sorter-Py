"""Serial monitor: the dock content behind the status bar's serial indicator.

Behavior reference: ``sorter/ui/serial_monitor.py`` (the Tk port of upstream
PRs #78/#86) — read that file's module docstring for the feature rationale;
this is the same feature set on ``QPlainTextEdit`` instead of ``tk.Text``.

One deliberate difference: the Tk window is opened lazily from the status bar,
long after the app started, so it replays ``app.serial_backlog`` on open to
show what happened before it existed. This widget is dock content built at
startup (``QtMainWindow._build_serial_dock``), so there is no gap to backfill
— its own ``_lines`` already *is* the whole session's history.

Everything arrives over the ``EventBus`` (``serial/rx``, ``serial/tx``,
``serial/note``, ``serial/state``), delivered on the Qt main thread by the
window's drain timer — nothing here may be called from the reader thread. See
CLAUDE.md §3.

The log is never re-ordered: ``_lines`` keeps every record, in arrival order,
forever (up to the ring cap); the filter and direction toggles hide records
without moving the ones that remain. ``matches()`` is the single predicate,
applied on arrival, on re-render, and by ``dump()`` — always against the
board's own text, never the rendered ``<-``/``->``/``--`` prefix or a
timestamp that is only sometimes shown.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Any

from PySide6.QtCore import Qt, QTimer  # ty: ignore[unresolved-import]
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor  # ty: ignore[unresolved-import]
from PySide6.QtWidgets import (  # ty: ignore[unresolved-import]
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

# Copied verbatim from ``ui/serial_monitor.py`` rather than imported — qtui
# imports nothing from the Tk package, which needs tkinter to load at all.
# ``tests/unit/qtui/test_qt_drift_pins.py`` pins the two copies together.

# The Arduino IDE's ladder, and its default.
BAUD_RATES = (300, 1200, 2400, 4800, 9600, 19200, 38400, 57600, 74880, 115200, 230400, 250000)
DEFAULT_BAUD = 9600

# Label → what actually goes on the wire after the typed text.
LINE_ENDINGS: dict[str, str] = {
    "No line ending": "",
    "New Line": "\n",
    "Carriage Return": "\r",
    "Both NL & CR": "\r\n",
}
DEFAULT_LINE_ENDING = "New Line"

MAX_LINES = 4000  # scrollback cap; the oldest are dropped, not the newest — matches Tk
MAX_HISTORY = 100
# GNOME's file-chooser portal strips the parenthesized "(*.txt)" from the
# label it shows, leaving no visible pattern (JL live-testing). The
# Qt-parsed pattern in parens still has to stay for the picker to actually
# filter — see models_page.ZIP_FILTER for the same fix.
TEXT_FILTER = "Text files — *.txt (*.txt)"
# Typing in the filter box re-renders the whole scrollback, so coalesce
# keystrokes instead of doing it per character.
FILTER_DEBOUNCE_MS = 120

# Line kinds -> the palette role they print in and the prefix they carry.
KIND_ROLE = {"rx": "text", "tx": "update", "note": "text_muted"}
KIND_PREFIX = {"rx": "<- ", "tx": "-> ", "note": "-- "}

# Dark-theme values, used only if the host window has no live palette yet.
_FALLBACK = {
    "text": "#d4d4d4",
    "update": "#60a5fa",
    "text_muted": "#9a9a9a",
    "text_subtle": "#6f6f6f",
    "success": "#22c55e",
    "error": "#ef4444",
}


class _CommandEdit(QLineEdit):
    """A QLineEdit whose Up/Down walk the owning widget's command history."""

    def __init__(self, owner: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._owner = owner

    def keyPressEvent(self, event: Any) -> None:
        if event.key() == Qt.Key.Key_Up:
            self._owner._history_step(-1)
            return
        if event.key() == Qt.Key.Key_Down:
            self._owner._history_step(1)
            return
        super().keyPressEvent(event)


class SerialMonitorWidget(QWidget):
    """Live serial traffic: filtered, timestamped, pausable, saveable."""

    def __init__(self, win: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._win = win
        # (kind, epoch seconds, text) — the rendered scrollback, kept so a
        # timestamp toggle can re-render and Save… can dump exactly what's on
        # screen.
        self._lines: deque[tuple[str, float, str]] = deque(maxlen=MAX_LINES)
        self._held: deque[tuple[str, float, str]] = deque(maxlen=MAX_LINES)
        self._history: list[str] = []
        self._history_pos = 0
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(FILTER_DEBOUNCE_MS)
        self._filter_timer.timeout.connect(self._rerender)

        self._build_ui()
        self.apply_palette()

        win.bus.subscribe("serial/rx", self._on_rx)
        win.bus.subscribe("serial/tx", self._on_tx)
        win.bus.subscribe("serial/note", self._on_note)
        win.bus.subscribe("serial/state", self._on_state)

    # ----- construction ---------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)
        layout.addLayout(self._build_header_row())
        layout.addLayout(self._build_filter_row())

        # Same objectName as the dock content it replaces, so it inherits
        # qtui/theme.py's existing `QPlainTextEdit#serialLog` rule for free.
        self.output = QPlainTextEdit(self)
        self.output.setObjectName("serialLog")
        self.output.setReadOnly(True)
        self.output.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        # Ring-buffer semantics, the Qt way — mirrors the `_lines` deque cap,
        # so there's no need for Tk's manual `_trim`.
        self.output.setMaximumBlockCount(MAX_LINES)
        layout.addWidget(self.output, 1)

        layout.addLayout(self._build_send_row())

    def _build_header_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self._dot = QLabel("●", self)  # BLACK CIRCLE — mirrors the status-bar indicator
        row.addWidget(self._dot)
        self._header_label = QLabel("disconnected", self)
        row.addWidget(self._header_label)
        row.addStretch(1)

        self.autoscroll_check = QCheckBox("Autoscroll", self)
        self.autoscroll_check.setChecked(True)
        row.addWidget(self.autoscroll_check)

        self.timestamps_check = QCheckBox("Timestamps", self)
        self.timestamps_check.toggled.connect(self._rerender)
        row.addWidget(self.timestamps_check)

        self.pause_check = QCheckBox("Pause", self)
        self.pause_check.toggled.connect(self._on_pause_toggled)
        row.addWidget(self.pause_check)

        self.clear_button = QPushButton("Clear", self)
        self.clear_button.clicked.connect(self.clear)
        row.addWidget(self.clear_button)

        self.save_button = QPushButton("Save…", self)
        self.save_button.clicked.connect(self.save_to_file)
        row.addWidget(self.save_button)
        return row

    def _build_filter_row(self) -> QHBoxLayout:
        """Substring filter + per-direction toggles, over the whole scrollback.

        Filtering is a view, not a deletion: `_lines` keeps everything, so
        clearing the box brings the hidden traffic straight back.
        """
        row = QHBoxLayout()
        row.addWidget(QLabel("Filter", self))
        self.filter_edit = QLineEdit(self)
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self._schedule_rerender)
        row.addWidget(self.filter_edit, 1)

        self.show_kind_checks: dict[str, QCheckBox] = {}
        for kind, label in (("rx", "RX"), ("tx", "TX"), ("note", "Notes")):
            box = QCheckBox(label, self)
            box.setChecked(True)
            box.toggled.connect(self._rerender)
            self.show_kind_checks[kind] = box
            row.addWidget(box)

        self.count_label = QLabel("0 lines", self)
        row.addWidget(self.count_label)
        return row

    def _build_send_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.command_edit = _CommandEdit(self, self)
        self.command_edit.returnPressed.connect(self.send_command)
        row.addWidget(self.command_edit, 1)

        self.ending_combo = QComboBox(self)
        self.ending_combo.addItems(list(LINE_ENDINGS))
        self.ending_combo.setCurrentText(DEFAULT_LINE_ENDING)
        row.addWidget(self.ending_combo)

        self.send_button = QPushButton("Send", self)
        self.send_button.setObjectName("action")
        self.send_button.clicked.connect(self.send_command)
        row.addWidget(self.send_button)

        row.addWidget(QLabel("Baud", self))
        self.baud_combo = QComboBox(self)
        self.baud_combo.addItems([str(b) for b in BAUD_RATES])
        self.baud_combo.setCurrentText(str(self._configured_baud()))
        # `activated` fires only on a user pick, never on the setCurrentText
        # above — the Qt analogue of Tk's `<<ComboboxSelected>>`.
        self.baud_combo.activated.connect(self._on_baud_activated)
        row.addWidget(self.baud_combo)
        return row

    # ----- theme ------------------------------------------------------------

    def _role_color(self, role: str) -> str:
        palette = getattr(self._win, "palette_colors", None) or {}
        return str(palette.get(role) or _FALLBACK[role])

    def apply_palette(self) -> None:
        """Re-read colors after a theme switch.

        Nothing here is driven by the stylesheet (the tags baked into each
        rendered line, the connection dot), so a theme switch has to
        explicitly ask for this — the host's theme-apply path should call it,
        the same way the Tk monitor's `apply_palette` is called by name.
        """
        self.count_label.setStyleSheet(f"color: {self._role_color('text_muted')};")
        self.refresh_connection()
        self._rerender()

    # ----- connection state ---------------------------------------------------

    def _configured_baud(self) -> int:
        try:
            return int(self._win.config.serial.get("baud", DEFAULT_BAUD))
        except (AttributeError, TypeError, ValueError):
            return DEFAULT_BAUD

    def _current_port(self) -> str:
        broker = getattr(self._win, "broker", None)
        port = getattr(broker, "port", "") if broker is not None else ""
        if port:
            return str(port)
        try:
            return str(self._win.config.serial.get("port", "") or "")
        except AttributeError:
            return ""

    def refresh_connection(self) -> None:
        """Repaint the header from the host window's live broker."""
        broker = getattr(self._win, "broker", None)
        connected = bool(broker is not None and getattr(broker, "is_connected", False))
        port = self._current_port() or "no port"
        baud = int(getattr(broker, "baud", 0) or self._configured_baud())
        if connected:
            firmware = getattr(broker, "firmware_version", "") or "Unknown"
            self._header_label.setText(f"{port} @ {baud} — {firmware}")
        else:
            self._header_label.setText(f"{port} @ {baud} — disconnected")
        self._dot.setStyleSheet(f"color: {self._role_color('success' if connected else 'error')};")

    def _on_state(self, _payload: Any = None) -> None:
        self.refresh_connection()
        # Mirror the config's baud: a reconnect from Settings → Serial (which
        # posts serial/state) must not leave this picker showing the old speed.
        saved = str(self._configured_baud())
        if self.baud_combo.currentText() != saved:
            if self.baud_combo.findText(saved) < 0:
                self.baud_combo.addItem(saved)
            self.baud_combo.setCurrentText(saved)

    def _on_baud_activated(self, index: int) -> None:
        self._on_baud_changed(self.baud_combo.itemText(index))

    def _on_baud_changed(self, text: str) -> None:
        """Persist the new speed and re-open the port at it, IDE-style."""
        try:
            baud = int(text)
        except (TypeError, ValueError):
            return
        win = self._win
        broker_baud = getattr(getattr(win, "broker", None), "baud", None)
        if baud == self._configured_baud() and broker_baud == baud:
            return
        try:
            win.config.serial["baud"] = baud
            win.config.save()
        except Exception as exc:
            self._note(f"could not save baud: {exc}")
        port = self._current_port()
        self._note(f"baud set to {baud}")
        if port:
            win.connect_serial(port=port)
        self.refresh_connection()

    # ----- inbound --------------------------------------------------------

    def _on_rx(self, line: Any) -> None:
        self.append("rx", str(line))

    def _on_tx(self, line: Any) -> None:
        self.append("tx", str(line))

    def _on_note(self, line: Any) -> None:
        self.append("note", str(line))

    def _note(self, line: str) -> None:
        """Record a monitor-local remark (not board traffic)."""
        self.append("note", line)

    def append(self, kind: str, line: str, *, stamp: float | None = None) -> None:
        record = (kind, time.time() if stamp is None else stamp, line)
        if self.pause_check.isChecked():
            self._held.append(record)
            return
        self._lines.append(record)
        self._render(record)
        self._update_count()

    def _on_pause_toggled(self, checked: bool) -> None:
        if checked:
            return
        held, self._held = list(self._held), deque(maxlen=MAX_LINES)
        for record in held:
            self._lines.append(record)
            self._render(record)
        self._update_count()

    # ----- filtering --------------------------------------------------------

    def _schedule_rerender(self, _text: str) -> None:
        self._filter_timer.start()

    def matches(self, record: tuple[str, float, str]) -> bool:
        """Does this line survive the direction toggles and the filter box?

        Case-insensitive substring, matched against the text as the board
        sent it — not the rendered line, so a filter can't accidentally key
        off the `<-`/`->` prefix or a timestamp that is only sometimes shown.
        """
        kind, _stamp, line = record
        box = self.show_kind_checks.get(kind)
        if box is not None and not box.isChecked():
            return False
        needle = self.filter_edit.text().strip().lower()
        return not needle or needle in line.lower()

    def _shown_line_count(self) -> int:
        """How many lines the widget is actually displaying.

        `setMaximumBlockCount` self-trims the document, so reading it back
        (minus the always-present trailing empty block) is the count that's
        actually on screen — no separate bookkeeping to drift out of step.
        """
        return max(0, self.output.blockCount() - 1)

    def _update_count(self) -> None:
        total = len(self._lines)
        shown = self._shown_line_count()
        self.count_label.setText(f"{total} lines" if shown == total else f"{shown} of {total} lines")

    # ----- rendering --------------------------------------------------------

    def _render(self, record: tuple[str, float, str]) -> None:
        if not self.matches(record):
            return
        kind, stamp, line = record
        cursor = self.output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if self.timestamps_check.isChecked():
            stamp_fmt = QTextCharFormat()
            stamp_fmt.setForeground(QColor(self._role_color("text_subtle")))
            cursor.insertText(f"{time.strftime('%H:%M:%S', time.localtime(stamp))} ", stamp_fmt)
        line_fmt = QTextCharFormat()
        line_fmt.setForeground(QColor(self._role_color(KIND_ROLE.get(kind, "text"))))
        cursor.insertText(f"{KIND_PREFIX.get(kind, '')}{line}\n", line_fmt)
        if self.autoscroll_check.isChecked():
            bar = self.output.verticalScrollBar()
            bar.setValue(bar.maximum())

    def _rerender(self) -> None:
        self.output.clear()
        for record in list(self._lines):
            self._render(record)
        self._update_count()

    def clear(self) -> None:
        self._lines.clear()
        self.output.clear()
        self._update_count()

    def dump(self) -> str:
        """The scrollback as plain text — what's on screen, filter included."""
        stamps = self.timestamps_check.isChecked()
        out = []
        for record in self._lines:
            if not self.matches(record):
                continue
            kind, stamp, line = record
            prefix = f"{time.strftime('%H:%M:%S', time.localtime(stamp))} " if stamps else ""
            out.append(f"{prefix}{KIND_PREFIX.get(kind, '')}{line}")
        return "\n".join(out) + ("\n" if out else "")

    def _choose_save_path(self) -> str:
        """Broken out so tests can patch it instead of driving a real file dialog."""
        path, _filter = QFileDialog.getSaveFileName(self, "Save serial log", "", f"{TEXT_FILTER};;All files (*.*)")
        return path

    def save_to_file(self) -> None:
        path = self._choose_save_path()
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(self.dump())
        except OSError as exc:
            self._note(f"save failed: {exc}")
            return
        self._note(f"saved to {path}")

    # ----- outbound -----------------------------------------------------------

    def send_command(self) -> None:
        text = self.command_edit.text()
        if not text:
            return
        broker = getattr(self._win, "broker", None)
        if broker is None or not getattr(broker, "is_connected", False):
            self._note("not connected — nothing sent")
            return
        # The broker echoes the write through on_sent -> serial/tx, so the
        # line lands in the log the same way an auto-connect probe's does.
        broker.send_raw(text + LINE_ENDINGS.get(self.ending_combo.currentText(), "\n"))
        if not self._history or self._history[-1] != text:
            self._history.append(text)
            del self._history[:-MAX_HISTORY]
        self._history_pos = len(self._history)
        self.command_edit.setText("")

    def _history_step(self, delta: int) -> None:
        """Walk the command history; past the newest entry the field clears."""
        if not self._history:
            return
        self._history_pos = max(0, min(len(self._history), self._history_pos + delta))
        value = "" if self._history_pos >= len(self._history) else self._history[self._history_pos]
        self.command_edit.setText(value)
        self.command_edit.end(False)


def build_serial_monitor(win: Any) -> SerialMonitorWidget:
    return SerialMonitorWidget(win)
