"""PySide6 spike shell, co-existing with the Tk UI in ``sorter/ui/``.

Launched with ``python -m sorter --qt`` (or ``CASESORTER_QT=1``); the default
launch is unchanged. Nothing under ``sorter/ui/`` is touched or imported except
``ui.theme``'s palettes, which this renders as QSS — so both UIs share one set
of colors and upstream Tk work keeps merging cleanly.

The non-UI layers are reused as-is: ``EventBus`` (drained by a 50 ms
``QTimer`` instead of ``root.after``, same threading contract — workers post,
the main thread dispatches), ``Camera``, and ``SerialBroker``.

Scope and rationale: docs/ui-modernization.md.
"""

from __future__ import annotations

import html
import sys
import threading
import traceback
from collections import deque
from collections.abc import Callable
from typing import Any

import numpy as np
from PySide6.QtCore import Qt, QTimer, QUrl  # ty: ignore[unresolved-import]
from PySide6.QtGui import (  # ty: ignore[unresolved-import]
    QDesktopServices,
    QFontDatabase,
    QImage,
    QKeySequence,
    QPixmap,
)
from PySide6.QtWidgets import (  # ty: ignore[unresolved-import]
    QApplication,
    QButtonGroup,
    QComboBox,
    QDockWidget,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..control.events import EventBus
from ..control.run_controller import RunController
from ..hardware import serial_broker
from ..hardware.camera import Camera
from ..hardware.serial_emulator import EMULATED_PORT, EmulatorBroker
from ..ml import classifier, local_inference
from ..paths import app_data_dir
from ..ui.theme import (
    SETTING_CUSTOM_THEMES,
    SETTING_THEME,
    THEMES,
    load_custom_themes,
    resolve_theme,
    theme_names,
)
from .slot_grid import SlotGrid
from .theme import build_stylesheet

PREVIEW_FPS = 20
HEADER_HEIGHT = 56
SIDEBAR_WIDTH = 84
SERIAL_LOG_LINES = 500
PLACEHOLDER_TEXT = "Not ported to the Qt spike yet — launch without --qt for the full UI."

# Sidebar: (glyph, page name). Settings is pinned to the bottom, below the stretch.
ACTIVITIES = (("▶", "Sort"), ("🎓", "Train"), ("📦", "Models"), ("🌐", "Community"))
SETTINGS_ACTIVITY = ("⚙", "Settings")
SETTINGS_SECTIONS = ("Camera", "Serial", "Image Proc", "AI Config", "Updates", "Theme")
BAUD_CHOICES = (9600, 19200, 38400, 57600, 115200)
FEED_MAX = 12
FEED_EMPTY_TEXT = "Recent classifications will appear here."
TORCH_NOTICE = (
    "This model classifies locally, which needs PyTorch.\n\n"
    "The Qt spike has no installer yet — launch without --qt and press Start "
    "there once to install it."
)


class QtMainWindow(QMainWindow):
    def __init__(self, config: Any, *, auto_connect: bool = True) -> None:
        super().__init__()
        self.config = config
        self.db = getattr(config, "db", None)
        self.bus = EventBus()
        self._muted_labels: list[QLabel] = []
        # Set before the UI is built: the action row's enabled state reads them.
        self.broker: Any | None = None
        self.run_controller: RunController | None = None
        self._is_running = False
        self._feed_entries: deque[tuple[str, float, bool]] = deque(maxlen=FEED_MAX)

        load_custom_themes(self._load_setting(SETTING_CUSTOM_THEMES))
        self.theme_name = resolve_theme(self._load_setting(SETTING_THEME))
        self.palette_colors = THEMES[self.theme_name]

        self.setWindowTitle(f"AI Case Sorter - v{__version__} (Qt spike)")
        self._build_ui()
        self._apply_theme(self.theme_name)

        self.camera = Camera(
            device_index=int(config.camera.get("device_index", 0)),
            width=int(config.camera.get("width", 640)),
            height=int(config.camera.get("height", 480)),
        )

        self.bus.subscribe("status", self.set_status)
        self.bus.subscribe("serial/rx", lambda line: self._append_serial("<-", line))
        self.bus.subscribe("serial/tx", lambda line: self._append_serial("->", line))
        self.bus.subscribe("serial/note", lambda line: self._append_serial("--", line))
        # Run state comes from the controller's own events, never from the
        # button handlers — a run can also end on its own (error, package halt).
        self.bus.subscribe("run/started", lambda _p: self._set_running(True))
        self.bus.subscribe("run/stopped", lambda _p: self._set_running(False))
        self.bus.subscribe("run/status", self.set_status)
        self.bus.subscribe("run/error", lambda msg: self.set_status(f"Run error: {msg}"))
        self.bus.subscribe("run/result", self._on_run_result)
        self.bus.subscribe("run/history", self._on_run_history)
        self.bus.subscribe("run/assignment_changed", lambda _p: self.slot_grid.refresh_assignments())
        self.bus.subscribe("run/package_halt", self._on_package_halt)
        self._bus_timer = QTimer(self)
        self._bus_timer.timeout.connect(lambda: self.bus.drain(max_items=128))
        self._bus_timer.start(50)

        self._preview_timer = QTimer(self)
        self._preview_timer.timeout.connect(self._refresh_preview)
        self._preview_timer.start(int(1000 / PREVIEW_FPS))

        if auto_connect:
            self.start_camera()
            self._auto_connect_serial()

    # ----- construction -------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_header())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        self.pages = QStackedWidget(central)
        self._pages_by_name: dict[str, QWidget] = {}
        self._add_page("Sort", self._build_sort_page())
        for name in ("Train", "Models", "Community"):
            self._add_page(name, self._placeholder_page())
        self._add_page("Settings", self._build_settings_page())
        body.addWidget(self._build_sidebar())
        body.addWidget(self.pages, 1)
        layout.addLayout(body, 1)
        self.setCentralWidget(central)

        # The dock is built before the menus: View hosts its toggle action.
        self._build_serial_dock()
        self._build_menus()

        self._camera_state = ("Camera: disconnected", False)
        self._serial_state = ("Serial: disconnected", False)
        self.camera_label = QLabel(self)
        self.serial_label = QLabel(self)
        # Added left to right, so serial ends up rightmost — same order as the
        # Tk status bar.
        self.statusBar().addPermanentWidget(self.camera_label)
        self.statusBar().addPermanentWidget(self.serial_label)
        self._paint_indicators()
        self.set_status("Idle.")

    def _build_header(self) -> QWidget:
        header = QWidget(self)
        header.setObjectName("header")
        header.setFixedHeight(HEADER_HEIGHT)
        row = QHBoxLayout(header)
        row.setContentsMargins(18, 0, 12, 0)
        title = QLabel("AI Case Sorter", header)
        font = title.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 5)
        title.setFont(font)
        row.addWidget(title)
        row.addWidget(self._muted_label("Open Source Client", header))
        row.addStretch(1)
        return header

    def _muted_label(self, text: str, parent: QWidget | None = None) -> QLabel:
        """A label in the muted role — registered so a theme switch recolors it."""
        label = QLabel(text, parent)
        label.setStyleSheet(f"color: {self.palette_colors['text_muted']};")
        self._muted_labels.append(label)
        return label

    def _placeholder_page(self, text: str = PLACEHOLDER_TEXT) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        label = self._muted_label(text, page)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        layout.addWidget(label)
        return page

    def _add_page(self, name: str, page: QWidget) -> None:
        self._pages_by_name[name] = page
        self.pages.addWidget(page)

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget(self)
        sidebar.setObjectName("sidebar")
        column = QVBoxLayout(sidebar)
        column.setContentsMargins(6, 8, 6, 8)
        column.setSpacing(4)

        self.sidebar_buttons: dict[str, QToolButton] = {}
        # The group owns exclusivity; keep the reference or it is collected.
        self._sidebar_group = QButtonGroup(self)
        self._sidebar_group.setExclusive(True)
        for glyph, name in ACTIVITIES:
            column.addWidget(self._activity_button(sidebar, glyph, name))
        column.addStretch(1)
        column.addWidget(self._activity_button(sidebar, *SETTINGS_ACTIVITY))

        # Width follows the widest label's font metrics, not a constant — a
        # fixed pixel width clips "Community" on fonts wider than the dev box.
        metrics = sidebar.fontMetrics()
        widest = max(metrics.horizontalAdvance(name) for name in self.sidebar_buttons)
        sidebar.setFixedWidth(max(SIDEBAR_WIDTH, widest + 24))

        self.sidebar_buttons["Sort"].setChecked(True)
        self.show_page("Sort")
        return sidebar

    def _activity_button(self, parent: QWidget, glyph: str, name: str) -> QToolButton:
        button = QToolButton(parent)
        button.setText(f"{glyph}\n{name}")
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        button.setCheckable(True)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        button.clicked.connect(lambda _checked=False, page=name: self.show_page(page))
        self._sidebar_group.addButton(button)
        self.sidebar_buttons[name] = button
        return button

    def _build_sort_page(self) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(12, 12, 12, 12)
        column.setSpacing(10)

        actions = QHBoxLayout()
        self.action_buttons: dict[str, QPushButton] = {}
        for text, object_name, handler in (
            ("Start", "action", self.start_run),
            ("Stop", "danger", self.stop_run),
            ("Manual feed", "", self.manual_feed),
        ):
            button = QPushButton(text, page)
            if object_name:
                button.setObjectName(object_name)
            button.clicked.connect(handler)
            actions.addWidget(button)
            self.action_buttons[text] = button
        actions.addStretch(1)
        column.addLayout(actions)
        self._update_run_buttons()

        splitter = QSplitter(Qt.Orientation.Horizontal, page)
        self.preview_label = QLabel("No frame", splitter)
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Ignored + tiny minimum: the label must never report the pixmap as
        # its size hint, or each scaled frame grows the layout that the next
        # frame is scaled to — the window ratchets larger on every repaint.
        self.preview_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.preview_label.setMinimumSize(1, 1)
        # A video letterbox is black in every theme; not chrome, so not themed.
        self.preview_label.setStyleSheet("background-color: #000000; color: #808080;")
        splitter.addWidget(self.preview_label)
        self.slot_grid = SlotGrid(self.config, splitter)
        splitter.addWidget(self.slot_grid)
        splitter.setSizes([600, 400])
        column.addWidget(splitter, 1)

        self.feed_label = self._muted_label(FEED_EMPTY_TEXT, page)
        self.feed_label.setTextFormat(Qt.TextFormat.RichText)
        column.addWidget(self.feed_label)
        return page

    def _build_settings_page(self) -> QWidget:
        page = QWidget()
        row = QHBoxLayout(page)
        row.setContentsMargins(12, 12, 12, 12)
        row.setSpacing(12)
        self.settings_list = QListWidget(page)
        self.settings_list.setFixedWidth(160)
        self.settings_pages = QStackedWidget(page)
        builders = {"Theme": self._build_theme_section, "Serial": self._build_serial_section}
        for name in SETTINGS_SECTIONS:
            self.settings_list.addItem(name)
            build = builders.get(name)
            self.settings_pages.addWidget(build() if build else self._placeholder_page())
        self.settings_list.currentRowChanged.connect(self.settings_pages.setCurrentIndex)
        self.settings_list.setCurrentRow(0)
        row.addWidget(self.settings_list)
        row.addWidget(self.settings_pages, 1)
        return page

    def _build_theme_section(self) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(6)
        column.addWidget(QLabel("Theme", page))
        self.theme_combo = QComboBox(page)
        self.theme_combo.addItems(theme_names())
        self.theme_combo.setCurrentText(self.theme_name)
        # Connected last: setCurrentText must not count as the user choosing.
        self.theme_combo.currentTextChanged.connect(self.set_theme)
        self.theme_combo.setMaximumWidth(240)
        column.addWidget(self.theme_combo)
        column.addStretch(1)
        return page

    def _build_serial_section(self) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(8)

        form = QFormLayout()
        self.port_combo = QComboBox(page)
        self.port_combo.setMaximumWidth(240)
        self.baud_combo = QComboBox(page)
        self.baud_combo.setMaximumWidth(240)
        self.baud_combo.addItems([str(b) for b in BAUD_CHOICES])
        saved_baud = str(int(self.config.serial.get("baud", 9600)))
        if saved_baud not in [str(b) for b in BAUD_CHOICES]:
            self.baud_combo.addItem(saved_baud)
        self.baud_combo.setCurrentText(saved_baud)
        form.addRow("Port", self.port_combo)
        form.addRow("Baud", self.baud_combo)
        column.addLayout(form)

        buttons = QHBoxLayout()
        connect = QPushButton("Connect", page)
        connect.setObjectName("action")
        connect.clicked.connect(lambda: self.connect_serial())
        refresh = QPushButton("Refresh ports", page)
        refresh.clicked.connect(self.refresh_ports)
        buttons.addWidget(connect)
        buttons.addWidget(refresh)
        buttons.addStretch(1)
        column.addLayout(buttons)
        column.addWidget(
            self._muted_label(
                "The board's init settings are still the Tk Serial tab's job.",
                page,
            )
        )
        column.addStretch(1)
        self.refresh_ports()
        return page

    def refresh_ports(self) -> None:
        """Re-enumerate ports, keeping the current selection if it survived."""
        selected = self.port_combo.currentText() or (self.config.serial.get("port") or "").strip()
        ports = [*serial_broker.list_serial_ports(), EMULATED_PORT]
        self.port_combo.clear()
        self.port_combo.addItems(ports)
        if selected in ports:
            self.port_combo.setCurrentText(selected)

    def _build_serial_dock(self) -> None:
        self.serial_dock = QDockWidget("Serial Monitor", self)
        self.serial_dock.setObjectName("serialDock")
        self.serial_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        self.serial_log = QPlainTextEdit(self.serial_dock)
        self.serial_log.setObjectName("serialLog")
        self.serial_log.setReadOnly(True)
        self.serial_log.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        # Ring-buffer semantics, the QPlainTextEdit way — matches the Tk monitor's deque.
        self.serial_log.setMaximumBlockCount(SERIAL_LOG_LINES)
        self.serial_dock.setWidget(self.serial_log)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.serial_dock)

    def _build_menus(self) -> None:
        # menuBar().addMenu(str) hands the QMenu back with Python ownership; the
        # menus have to be kept alive here or shiboken deletes them.
        self.menus: dict[str, Any] = {}
        file_menu = self.menus["File"] = self.menuBar().addMenu("&File")
        open_data = file_menu.addAction("Open Data Folder")
        open_data.triggered.connect(self._open_data_folder)
        file_menu.addSeparator()
        quit_action = file_menu.addAction("Quit")
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)

        toggle = self.serial_dock.toggleViewAction()
        toggle.setText("Serial Monitor")
        self.menus["View"] = self.menuBar().addMenu("&View")
        self.menus["View"].addAction(toggle)

        self.menus["Help"] = self.menuBar().addMenu("&Help")
        about = self.menus["Help"].addAction("About")
        about.triggered.connect(self._show_about)

    # ----- navigation ---------------------------------------------------------

    def show_page(self, name: str) -> None:
        self.pages.setCurrentWidget(self._pages_by_name[name])
        if name == "Sort":
            # Assignments can have changed in Settings (or the Tk UI) since the
            # cards were last drawn; they are cheap to re-read and never cached.
            self.slot_grid.refresh_assignments()

    def _open_data_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(app_data_dir())))

    def _show_about(self) -> None:
        QMessageBox.about(self, "About", f"AI Case Sorter\nv{__version__}\nQt spike")

    def _append_serial(self, prefix: str, line: Any) -> None:
        self.serial_log.appendPlainText(f"{prefix} {str(line).rstrip()}")

    # ----- theme --------------------------------------------------------------

    def _load_setting(self, key: str) -> Any:
        """Read a settings row, or None if there's no DB / it can't be read."""
        if self.db is None:
            return None
        try:
            from ..data.repository import SettingsRepo

            return SettingsRepo(self.db).get(key)
        except Exception:
            return None

    def _save_setting(self, key: str, value: Any) -> None:
        if self.db is None:
            return
        try:
            from ..data.repository import SettingsRepo

            SettingsRepo(self.db).set(key, value)
        except Exception:
            # A preference that can't be persisted still applies this session.
            pass

    def set_theme(self, name: str) -> None:
        """Switch palettes live and remember the choice."""
        resolved = resolve_theme(name)
        self._apply_theme(resolved)
        self._save_setting(SETTING_THEME, resolved)

    def _apply_theme(self, name: str) -> None:
        self.theme_name = name
        self.palette_colors = THEMES[name]
        self.setStyleSheet(build_stylesheet(self.palette_colors))
        muted = f"color: {self.palette_colors['text_muted']};"
        for label in self._muted_labels:
            label.setStyleSheet(muted)
        # The feed's confidence colors are baked into its spans.
        self._render_feed()
        # Indicator dots carry state, not a palette role a stylesheet can reach.
        self._paint_indicators()

    # ----- status -------------------------------------------------------------

    def set_status(self, message: str) -> None:
        self.statusBar().showMessage(str(message))

    def _indicator_html(self, message: str, *, connected: bool) -> str:
        color = self.palette_colors["success" if connected else "error"]
        return f'<span style="color: {color};">●</span> {html.escape(str(message))}'

    def _paint_indicators(self) -> None:
        for label, (message, connected) in (
            (self.camera_label, self._camera_state),
            (self.serial_label, self._serial_state),
        ):
            label.setText(self._indicator_html(message, connected=connected))

    def _set_camera_indicator(self, message: str, *, connected: bool) -> None:
        self._camera_state = (message, connected)
        self._paint_indicators()

    def _set_serial_indicator(self, message: str, *, connected: bool) -> None:
        self._serial_state = (message, connected)
        self._paint_indicators()
        self.bus.post("serial/state", {"connected": connected, "message": message})

    # ----- camera -------------------------------------------------------------

    def start_camera(self) -> None:
        try:
            if self.camera.start_preview():
                self._set_camera_indicator(
                    f"Camera: connected ({self.camera.width}x{self.camera.height})",
                    connected=True,
                )
            else:
                self.set_status("Camera failed to start. Check the device index.")
                self._set_camera_indicator("Camera: failed to start", connected=False)
        except Exception as exc:
            self.set_status(f"Camera error: {exc}")
            self._set_camera_indicator("Camera: error", connected=False)

    @staticmethod
    def frame_to_image(frame: np.ndarray) -> QImage:
        """Wrap a BGR numpy frame as a QImage.

        ``QImage`` borrows the buffer it is handed, so the copy is what cuts
        the result loose from a frame the grab thread is about to overwrite.
        """
        buffer = np.ascontiguousarray(frame)
        height, width = buffer.shape[:2]
        image = QImage(buffer.data, width, height, buffer.strides[0], QImage.Format.Format_BGR888)
        return image.copy()

    def _refresh_preview(self) -> None:
        frame = self.camera.latest_frame()
        if frame is None:
            return
        pixmap = QPixmap.fromImage(self.frame_to_image(frame))
        self.preview_label.setPixmap(
            pixmap.scaled(
                self.preview_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    # ----- serial -------------------------------------------------------------

    def _auto_connect_serial(self) -> None:
        """Try the saved port first, then walk the rest until one handshakes.

        Trimmed copy of ``ui.app.MainWindow._auto_connect_serial`` — no run
        controller and no init-settings push in the spike.
        """
        saved_port = (self.config.serial.get("port") or "").strip()
        if saved_port == EMULATED_PORT:
            broker = EmulatorBroker()
            broker.try_open()
            self._after_connect(broker, EMULATED_PORT)
            return

        available = serial_broker.list_serial_ports()
        candidates: list[str] = []
        if saved_port and saved_port in available:
            candidates.append(saved_port)
        for port in available:
            if port not in candidates:
                candidates.append(port)

        if not candidates:
            self.set_status("No serial ports detected.")
            self._set_serial_indicator("Serial: no ports", connected=False)
            return

        baud = int(self.config.serial.get("baud", 9600))
        probe_timeout = float(self.config.serial.get("handshake_timeout_s", serial_broker.HANDSHAKE_READ_TIMEOUT_S))

        def _probe() -> tuple[Any, str] | tuple[None, None]:
            for port in candidates:
                self.bus.post("status", f"Auto-connect: probing {port}…")
                self.bus.post("serial/note", f"probing {port} @ {baud}…")
                broker = serial_broker.SerialBroker(
                    port=port,
                    baud=baud,
                    require_serial_ready=True,
                    handshake_timeout_s=probe_timeout,
                )
                # Listen *before* the handshake: whatever the board says to a
                # probe that fails is the only evidence of why it failed.
                self._attach_serial_listeners(broker)
                if broker.try_open():
                    broker.start()
                    return broker, port
                self.bus.post("serial/note", f"{port} did not handshake")
            return None, None

        self.set_status(f"Auto-connecting to serial — {len(candidates)} port(s) to try…")
        self.run_worker(
            _probe,
            on_done=self._finalize_auto_connect,
            on_error=lambda exc: self.set_status(f"Auto-connect error: {exc}"),
        )

    def _finalize_auto_connect(self, result: tuple[Any, str] | tuple[None, None]) -> None:
        broker, port = result
        if broker is None or port is None:
            self.set_status("No board responded on any port.")
            self._set_serial_indicator("Serial: no board found", connected=False)
            return
        self._after_connect(broker, port)

    def _attach_serial_listeners(self, broker: Any) -> None:
        """Fan a broker's traffic onto the bus, once — a second attach doubles every line."""
        if getattr(broker, "_bus_listeners_attached", False):
            return
        broker.on_received.append(lambda line: self.bus.post("serial/rx", line))
        broker.on_sent.append(lambda line: self.bus.post("serial/tx", line))
        broker._bus_listeners_attached = True

    def _after_connect(self, broker: Any, port: str, *, source: str = "auto") -> None:
        """Shared tail of both connect paths: listeners, persistence, controller."""
        self._attach_serial_listeners(broker)
        self.broker = broker
        baud = int(getattr(broker, "baud", self.config.serial.get("baud", 9600)))
        if port != (self.config.serial.get("port") or "") or baud != int(self.config.serial.get("baud", 9600)):
            self.config.serial["port"] = port
            self.config.serial["baud"] = baud
            self.config.save()
        self._set_serial_indicator(
            f"Serial: connected ({port} @ {getattr(broker, 'baud', '?')}) — {broker.firmware_version}",
            connected=True,
        )
        self.set_status(f"{'Auto-connected' if source == 'auto' else 'Connected'} to {port}.")
        self._rebuild_run_controller()

    def connect_serial(self, port: str | None = None) -> None:
        """Open one explicit port, chosen in Settings → Serial.

        Mirrors ``ui.app.MainWindow.connect_serial``: the emulator is opened
        inline (nothing blocks), a real port opens on a worker because
        ``try_open`` waits out the board's handshake.
        """
        if self.broker is not None:
            try:
                if self.run_controller is not None:
                    self.run_controller.stop()
                self.broker.stop()
            except Exception:
                pass
            self.broker = None
            self.run_controller = None
            self._update_run_buttons()

        if port is None:
            port = self.port_combo.currentText().strip()
        if not port:
            self.set_status("No port selected.")
            self._set_serial_indicator("Serial: no port selected", connected=False)
            return

        if port == EMULATED_PORT:
            broker: Any = EmulatorBroker()
            broker.try_open()
            self._after_connect(broker, port, source="manual")
            return

        baud = int(self.baud_combo.currentText() or self.config.serial.get("baud", 9600))
        broker = serial_broker.SerialBroker(port=port, baud=baud, require_serial_ready=True)
        # As in the probe: a failed open should still leave a trace in the monitor.
        self._attach_serial_listeners(broker)
        self.set_status(f"Connecting to {port}…")

        def _open() -> bool:
            if not broker.try_open():
                return False
            broker.start()
            return True

        def _done(opened: bool) -> None:
            if not opened:
                self.set_status(f"Failed to open {port}.")
                self._set_serial_indicator(f"Serial: failed to open {port}", connected=False)
                return
            self._after_connect(broker, port, source="manual")

        self.run_worker(
            _open,
            on_done=_done,
            on_error=lambda exc: self.set_status(f"Connect error: {exc}"),
        )

    # ----- run ----------------------------------------------------------------

    def _rebuild_run_controller(self) -> None:
        if self.broker is None:
            return
        self.run_controller = RunController(
            config=self.config,
            broker=self.broker,
            camera=self.camera,
            bus=self.bus,
            db=self.db,
        )
        self.slot_grid.refresh_assignments()
        self._update_run_buttons()

    def notify(self, title: str, text: str) -> None:
        """User-facing warning. Tests patch this — never let a modal open there."""
        QMessageBox.warning(self, title, text)

    def _ready_to_sort(self) -> RunController | None:
        """Preflight, in the Tk Run tab's order: board, checkpoint, torch.

        Each check is asked of the layer that owns the answer, so the Qt shell
        never re-derives the rule. Returns the controller when a run may start.
        """
        controller = self.run_controller
        if controller is None or self.broker is None:
            self.set_status("Connect to the board first (Settings → Serial).")
            return None
        problem = classifier.checkpoint_problem(self.db)
        if problem is not None:
            self.notify("Model not ready", problem)
            return None
        if classifier.uses_local_inference(self.db) and not local_inference.is_installed():
            self.notify("PyTorch required", TORCH_NOTICE)
            return None
        return controller

    def start_run(self) -> None:
        controller = self._ready_to_sort()
        if controller is None or self._is_running:
            return
        self.slot_grid.refresh_assignments()
        controller.start()

    def stop_run(self) -> None:
        if self.run_controller is not None:
            self.run_controller.stop()
            self.set_status("Stopping…")

    def manual_feed(self) -> None:
        controller = self._ready_to_sort()
        if controller is None or self._is_running:
            return
        # One cycle blocks on the board; the bus carries the result back.
        self.run_worker(controller.cycle_once)

    def _set_running(self, running: bool) -> None:
        self._is_running = running
        self._update_run_buttons()

    def _update_run_buttons(self) -> None:
        connected = self.broker is not None
        for name, enabled in (
            ("Start", connected and not self._is_running),
            ("Manual feed", connected and not self._is_running),
            ("Stop", self._is_running),
        ):
            button = self.action_buttons[name]
            button.setEnabled(enabled)
            button.setToolTip("" if connected else "Connect to the board first")

    def _on_run_result(self, result: Any) -> None:
        if not isinstance(result, dict) or not result.get("ok"):
            return
        self.slot_grid.increment(int(result.get("slot") or 0))

    def _on_run_history(self, payload: Any) -> None:
        """One classification for the recent-feed strip (newest first)."""
        if not isinstance(payload, dict):
            return
        confidence = float(payload.get("confidence", 0) or 0)
        floor = float(getattr(self.config, "run_confidence_floor", 0) or 0)
        self._feed_entries.appendleft(
            (str(payload.get("label") or "(empty)"), confidence, floor <= 0 or confidence >= floor)
        )
        self._render_feed()

    def _render_feed(self) -> None:
        if not self._feed_entries:
            self.feed_label.setText(FEED_EMPTY_TEXT)
            return
        parts = []
        for label, confidence, above_floor in self._feed_entries:
            color = self.palette_colors["success" if above_floor else "warning"]
            parts.append(f'{html.escape(label)} <span style="color: {color};">{confidence:.0f}%</span>')
        self.feed_label.setText(" &middot; ".join(parts))

    def _on_package_halt(self, payload: Any) -> None:
        label = (payload or {}).get("label") if isinstance(payload, dict) else None
        self.set_status(f"Run stopped — every slot for “{label or '?'}” is full.")

    # ----- worker dispatch ----------------------------------------------------

    def run_worker(
        self,
        fn: Callable[[], Any],
        *,
        on_done: Callable[[Any], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
    ) -> None:
        """Run `fn` in a daemon thread and post the result back via the bus.

        Workers must never touch widgets; the drain timer delivers the result
        on the main thread.
        """
        topic_done = f"worker/done/{id(fn)}"
        topic_err = f"worker/err/{id(fn)}"

        if on_done is not None:
            self.bus.subscribe(topic_done, on_done)
        if on_error is not None:
            self.bus.subscribe(topic_err, on_error)

        def _run() -> None:
            try:
                self.bus.post(topic_done, fn())
            except Exception as exc:
                traceback.print_exc()
                self.bus.post(topic_err, exc)

        threading.Thread(target=_run, daemon=True).start()

    # ----- lifecycle ----------------------------------------------------------

    def closeEvent(self, event: Any) -> None:
        try:
            if self.run_controller is not None:
                self.run_controller.stop()
        except Exception:
            pass
        try:
            if self.broker is not None:
                self.broker.stop()
        except Exception:
            pass
        try:
            self.camera.stop()
        except Exception:
            pass
        super().closeEvent(event)


def run_app(config: Any) -> int:
    app = QApplication.instance() or QApplication(sys.argv[:1])
    window = QtMainWindow(config)
    window.resize(1024, 768)
    window.show()
    return app.exec()
