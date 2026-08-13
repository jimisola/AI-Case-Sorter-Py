"""PySide6 spike shell, co-existing with the Tk UI in ``sorter/ui/``.

Launched with ``python -m sorter --qt`` (or ``CASESORTER_QT=1``); the default
launch is unchanged. Nothing under ``sorter/ui/`` is touched or imported at
all: the palettes come from ``qtui/palettes.py``, a drift-pinned copy of
``ui/theme.py``'s palette half, which this renders as QSS — so both UIs share
one set of colors without the Qt UI needing tkinter installed.

The non-UI layers are reused as-is: ``EventBus`` (drained by a 50 ms
``QTimer`` instead of ``root.after``, same threading contract — workers post,
the main thread dispatches), ``Camera``, and ``SerialBroker``.

Scope and rationale: docs/ui-modernization.md.
"""

from __future__ import annotations

import base64
import html
import itertools
import os
import sys
import threading
import traceback
from collections import deque
from collections.abc import Callable
from typing import Any

import numpy as np
from PySide6.QtCore import QByteArray, Qt, QTimer, QUrl  # ty: ignore[unresolved-import]
from PySide6.QtGui import (  # ty: ignore[unresolved-import]
    QDesktopServices,
    QImage,
    QKeySequence,
    QPixmap,
)
from PySide6.QtWidgets import (  # ty: ignore[unresolved-import]
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDockWidget,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from .. import __version__
from ..control.events import EventBus
from ..control.run_controller import RunController
from ..hardware import serial_broker
from ..hardware.camera import Camera
from ..hardware.serial_emulator import EMULATED_PORT, EmulatorBroker
from ..ml import classifier
from ..paths import app_data_dir
from .community_page import build_community_page
from .dialog_slot_assign import CATCH_ALL_HINT, SlotAssignDialog
from .dialog_template import EditTemplateDialog, NewTemplateDialog
from .help_viewer import build_help_window, topic_for
from .history_view import build_history_view
from .models_page import build_models_page
from .palettes import (
    SETTING_CUSTOM_THEMES,
    SETTING_THEME,
    THEMES,
    load_custom_themes,
    resolve_theme,
    theme_names,
)
from .serial_monitor import build_serial_monitor
from .settings_ai import build_ai_section
from .settings_camera import build_camera_section
from .settings_imageproc import build_imageproc_section
from .settings_serial import build_serial_section
from .slot_grid import SlotGrid
from .theme import build_stylesheet
from .torch_gate import TorchGate
from .train_page import build_train_page

PREVIEW_FPS = 20
CROP_SIZE = 132
SIDEBAR_WIDTH = 84
PLACEHOLDER_TEXT = "Not ported to the Qt spike yet — launch without --qt for the full UI."

# Sidebar: (glyph, page name). Settings is pinned to the bottom, below the stretch.
ACTIVITIES = (("▶", "Sort"), ("🎓", "Train"), ("📦", "Models"), ("🌐", "Community"))
SETTINGS_ACTIVITY = ("⚙", "Settings")
SETTINGS_SECTIONS = ("Camera", "Serial", "Image Processing", "AI Config", "Theme")
BAUD_CHOICES = (9600, 19200, 38400, 57600, 115200)
FEED_MAX = 12
FEED_EMPTY_TEXT = "Recent classifications will appear here."

# Run options (Tk reference: tab_run.py's run_opts frame). Same config keys,
# same semantics — just grouped into one popover instead of three rows.
STORE_IMAGES_LABELS = {
    "none": "None",
    "above": "Above Confidence Floor",
    "below": "Below Confidence Floor",
    "all": "All Images",
}
STORE_IMAGES_BY_LABEL = {label: mode for mode, label in STORE_IMAGES_LABELS.items()}
STORE_IMAGES_WARNING_TITLE = "Store images enabled"
STORE_IMAGES_WARNING_TEXT = (
    "Classified run images will be saved under the active model's run_images "
    "folder. This can use significant disk space over time."
)

EMPTY_STATE_TITLE = "Nothing connected yet"
EMPTY_STATE_HINT = "Connect a board and a camera to start sorting."

# Persisted window/session state (JL, increment 14): dock layout + the model
# table's column widths, the same _load_setting/_save_setting pattern used
# for the theme choice.
SETTING_WINDOW_STATE = "ui.window_state"
SETTING_MODELS_COLUMNS = "ui.models_columns"

# Tk parity (ui/app.py): minsize(960, 660).
MIN_WINDOW_SIZE = (960, 660)

# A double-click re-dock (or the View toggle) can leave a dock collapsed to
# near-zero size — visible per its toggle action, but unusable. Below this
# floor, _restore_collapsed_docks pushes it back out to a usable size.
DOCK_COLLAPSE_FLOOR_PX = 120
DOCK_RESTORED_SIZE_PX = 240


class QtMainWindow(QMainWindow):
    def __init__(self, config: Any, *, auto_connect: bool = True) -> None:
        super().__init__()
        self.config = config
        self.db = getattr(config, "db", None)
        self.bus = EventBus()
        self._worker_tokens = itertools.count()
        self._muted_labels: list[QLabel] = []
        # Set before the UI is built: the action row's enabled state reads them.
        self.broker: Any | None = None
        self.run_controller: RunController | None = None
        self._is_running = False
        self._master_count = 0
        self._templates: list[Any] = []
        self._feed_entries: deque[tuple[str, float, bool]] = deque(maxlen=FEED_MAX)
        # Tk parity: the store-images disk-usage notice shows once per session.
        self._store_warning_shown = False

        self.setMinimumSize(*MIN_WINDOW_SIZE)

        load_custom_themes(self._load_setting(SETTING_CUSTOM_THEMES))
        self.theme_name = resolve_theme(self._load_setting(SETTING_THEME))
        self.palette_colors = THEMES[self.theme_name]

        # Before _build_ui: the Camera settings page reads it at construction.
        # Constructing a Camera does not open the device.
        self.camera = Camera(
            device_index=int(config.camera.get("device_index", 0)),
            width=int(config.camera.get("width", 640)),
            height=int(config.camera.get("height", 480)),
        )

        # The one sanctioned front door for anything needing local inference.
        self.ensure_torch = TorchGate(self)

        self.setWindowTitle(f"AI Case Sorter OSS - v{__version__} (Qt) · GPL-3.0")
        self._build_ui()
        self._apply_theme(self.theme_name)
        self._restore_window_state()

        self.bus.subscribe("status", self.set_status)
        # Run state comes from the controller's own events, never from the
        # button handlers — a run can also end on its own (error, package halt).
        self.bus.subscribe("run/started", lambda _p: self._on_run_started())
        self.bus.subscribe("run/stopped", lambda _p: self._set_running(False))
        self.bus.subscribe("run/status", self.set_status)
        self.bus.subscribe("run/error", lambda msg: self.set_status(f"Run error: {msg}"))
        self.bus.subscribe("run/result", self._on_run_result)
        self.bus.subscribe("run/history", self._on_run_history)
        self.bus.subscribe("run/assignment_changed", lambda _p: self._refresh_sort_grid())
        self.bus.subscribe("run/package_full", self._on_package_full)
        self.bus.subscribe("run/package_halt", self._on_package_halt)
        # Headstamps, templates and the Train activity are all scoped to the
        # active model, so a mode switch re-reads every one of them.
        self.bus.subscribe("mode/changed", lambda _p: self._on_mode_changed())
        self._bus_timer = QTimer(self)
        self._bus_timer.timeout.connect(lambda: self.bus.drain(max_items=128))
        self._bus_timer.start(50)

        self._preview_timer = QTimer(self)
        self._preview_timer.timeout.connect(self._refresh_preview)
        self._preview_timer.start(int(1000 / PREVIEW_FPS))

        self.auth: Any | None = None
        self._update_info: Any | None = None
        self._pending_update: Any | None = None
        if auto_connect:
            # Tk parity: a returning signed-in user finds Community present at
            # launch. Reads the token cache only; never constructed in tests.
            try:
                from ..community.auth import AuthManager

                self.auth = AuthManager()
            except Exception:
                self.auth = None
            self.community_page.refresh_auth_state()
            self.start_camera()
            self._auto_connect_serial()
            QTimer.singleShot(2500, self._startup_update_check)
        self._apply_auth_visibility()

    # ----- construction -------------------------------------------------------

    def _build_ui(self) -> None:
        # Set before any page is built: show_page("Sort") (from the sidebar's
        # own construction, below) already reaches _update_sort_empty_state.
        self._camera_state = ("Camera: disconnected", False)
        self._serial_state = ("Serial: disconnected", False)

        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        self.pages = QStackedWidget(central)
        self._pages_by_name: dict[str, QWidget] = {}
        self._add_page("Sort", self._build_sort_page())
        self._add_page("Train", self._build_train_page())
        self._add_page("Models", self._build_models_page())
        self._add_page("Community", self._build_community_page())
        self._add_page("Settings", self._build_settings_page())
        body.addWidget(self._build_sidebar())
        body.addWidget(self.pages, 1)
        layout.addLayout(body, 1)
        self.setCentralWidget(central)

        # Docks are built before the menus: View hosts their toggle actions.
        self._build_serial_dock()
        self._build_history_dock()
        self._build_help_dock()
        self._build_menus()

        self.camera_label = QLabel(self)
        self.serial_label = QLabel(self)
        # Added left to right, so serial ends up rightmost — same order as the
        # Tk status bar.
        self.statusBar().addPermanentWidget(self.camera_label)
        self.statusBar().addPermanentWidget(self.serial_label)
        # Rightmost pair, Tk order: update affordance (hidden until there is
        # something to do — Help menu is the always-reachable route), sign-in.
        self.update_button = QPushButton(self)
        self.update_button.setObjectName("update")
        self.update_button.clicked.connect(lambda: self.open_update_dialog())
        self.update_button.hide()
        self.statusBar().addPermanentWidget(self.update_button)
        # Community identity — the only surface for it now (JL): the
        # Community page used to carry its own "Signed in as ... [Sign out]"
        # row, which duplicated this button and wasted a row for nothing else
        # the page needed. Hidden until signed in; text/tooltip filled by
        # _apply_auth_visibility.
        self.identity_label = self._muted_label("", self)
        self.identity_label.hide()
        self.statusBar().addPermanentWidget(self.identity_label)
        self.signin_button = QPushButton("Sign in", self)
        self.signin_button.clicked.connect(self._on_signin_clicked)
        self.statusBar().addPermanentWidget(self.signin_button)
        self._paint_indicators()
        self._apply_mode_visibility()
        self.set_status("Idle.")

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
        # The gear was easy to miss at the sidebar's default muted color (JL
        # live-testing) — theme.py colors this objectName with the palette's
        # "update" blue ("adjust something installed"), not action-green or
        # danger-red.
        self.sidebar_buttons["Settings"].setObjectName("settingsButton")

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
        column.addLayout(self._build_action_row(page))
        column.addLayout(self._build_template_bar(page))

        splitter = QSplitter(Qt.Orientation.Horizontal, page)
        splitter.addWidget(self._build_preview_column(splitter))
        splitter.addWidget(self._build_grid_column(splitter))
        splitter.setSizes([600, 400])

        # Index 0 is the working dashboard, 1 the first-run guided panel — see
        # _update_sort_empty_state. Nothing computes the initial state here:
        # _paint_indicators() (called once _build_ui finishes) does that.
        self.sort_stack = QStackedWidget(page)
        self.sort_stack.addWidget(splitter)
        self.sort_stack.addWidget(self._build_empty_state_panel(page))
        column.addWidget(self.sort_stack, 1)

        self.feed_label = self._muted_label(FEED_EMPTY_TEXT, page)
        self.feed_label.setTextFormat(Qt.TextFormat.RichText)
        column.addWidget(self.feed_label)
        return page

    def _build_grid_column(self, parent: QWidget) -> QWidget:
        """The slot grid, with the run counter/reset anchored above it.

        JL (follow-up to the run-options move): the counter and reset button
        felt orphaned floating on the action row — they belong with what
        they count, not with Start/Stop/Manual feed.
        """
        holder = QWidget(parent)
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(6)

        header = QHBoxLayout()
        header.addWidget(self._muted_label("Slots", holder))
        header.addStretch(1)
        header.addWidget(self._muted_label("Sorted this run", holder))
        self.master_count_label = QLabel("0", holder)
        self.master_count_label.setObjectName("masterCount")
        header.addWidget(self.master_count_label)
        reset = QPushButton("Reset counts", holder)
        reset.clicked.connect(self.reset_counts)
        header.addWidget(reset)
        column.addLayout(header)

        self.slot_grid = SlotGrid(self.config, holder)
        self.slot_grid.slot_clicked.connect(lambda slot: self.open_slot_editor(slot))
        self.slot_grid.slot_reset.connect(lambda slot: self.reset_slot_count(slot))
        column.addWidget(self.slot_grid, 1)
        return holder

    def _build_empty_state_panel(self, page: QWidget) -> QWidget:
        """First-run guidance in place of a grid nothing has configured yet."""
        panel = QWidget(page)
        column = QVBoxLayout(panel)
        column.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.setSpacing(10)

        title = QLabel(EMPTY_STATE_TITLE, panel)
        title.setObjectName("emptyStateTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(title)
        hint = self._muted_label(EMPTY_STATE_HINT, panel)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(hint)

        self.empty_state_board_button = QPushButton("Connect a board — Settings → Serial", panel)
        self.empty_state_board_button.clicked.connect(lambda: self._open_settings_section("Serial"))
        column.addWidget(self.empty_state_board_button)

        self.empty_state_camera_button = QPushButton("Connect a camera — Settings → Camera", panel)
        self.empty_state_camera_button.clicked.connect(lambda: self._open_settings_section("Camera"))
        column.addWidget(self.empty_state_camera_button)
        return panel

    def _open_settings_section(self, name: str) -> None:
        self.sidebar_buttons["Settings"].setChecked(True)
        self.show_page("Settings")
        items = self.settings_list.findItems(name, Qt.MatchFlag.MatchExactly)
        if items:
            self.settings_list.setCurrentItem(items[0])

    def _refresh_sort_grid(self) -> None:
        """Assignments changed (bus event, template swap, mode switch, edit)."""
        self.slot_grid.refresh_assignments()
        self._update_sort_empty_state()

    def _update_sort_empty_state(self) -> None:
        """No board, no camera, nothing routed anywhere yet -> the guided panel.

        Re-evaluated on every indicator paint (camera/serial connect changes)
        and every assignment change, never cached: any one of the three
        conditions clearing is enough to swap back to the real dashboard.
        """
        connected = self._camera_state[1] or self._serial_state[1]
        fresh_db = not any(int(h.get("slot", 0)) > 0 for h in self.config.headstamps)
        self.sort_stack.setCurrentIndex(1 if (not connected and fresh_db) else 0)

    def _build_action_row(self, page: QWidget) -> QHBoxLayout:
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
        # No dedicated row for this (JL) — was its own bar under the
        # template row. The run counter/reset live with the grid instead
        # (see `_build_grid_column`), not here.
        self.run_options_button = self._build_run_options_button(page)
        actions.addWidget(self.run_options_button)
        self._update_run_buttons()
        return actions

    def _build_template_bar(self, page: QWidget) -> QHBoxLayout:
        """Template things only — run configuration lives in its own group.

        JL, increment 14: consolidate everything that configures how a run
        behaves into one place (see ``_build_run_options_button``) instead
        of scattering it across the tab, as Tk does.
        """
        bar = QHBoxLayout()
        bar.addWidget(self._muted_label("Sorting template", page))
        self.template_combo = QComboBox(page)
        self.template_combo.setMinimumWidth(200)
        # `activated` is user-only, so repopulating the combo can't look like a switch.
        self.template_combo.activated.connect(self._on_template_selected)
        bar.addWidget(self.template_combo)
        for text, handler in (("+ New", self.new_template), ("✎ Edit", self.edit_template)):
            button = QPushButton(text, page)
            button.clicked.connect(handler)
            bar.addWidget(button)
        self.template_hint = self._muted_label("", page)
        bar.addWidget(self.template_hint)
        bar.addStretch(1)
        self._refresh_templates()
        return bar

    def _build_run_options_button(self, page: QWidget) -> QToolButton:
        """Everything that configures how a run behaves, in one popover.

        Tk reference: tab_run.py's run_opts frame plus its separate Package
        Mode / Batch Size rows — same Config keys and semantics throughout,
        just grouped compactly instead of stacked as five always-visible
        rows (JL, increment 14: package mode/batch moved here from the
        template bar, which now carries only template things).
        """
        button = QToolButton(page)
        button.setText("⚙ Run options")
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

        menu = QMenu(button)
        form_holder = QWidget(menu)
        form = QFormLayout(form_holder)
        form.setContentsMargins(10, 8, 10, 8)

        self.store_images_combo = QComboBox(form_holder)
        self.store_images_combo.addItems(list(STORE_IMAGES_LABELS.values()))
        self.store_images_combo.setCurrentText(STORE_IMAGES_LABELS.get(self.config.run_store_images, "None"))
        self.store_images_combo.currentTextChanged.connect(self._on_store_images_changed)
        form.addRow("Store images", self.store_images_combo)

        self.floor_spin = QSpinBox(form_holder)
        self.floor_spin.setRange(0, 100)
        self.floor_spin.setSuffix("%")
        self.floor_spin.setValue(int(self.config.run_confidence_floor))
        self.floor_spin.valueChanged.connect(self._on_floor_changed)
        form.addRow("Confidence floor", self.floor_spin)

        self.auto_select_check = QCheckBox("Automatically select trays", form_holder)
        self.auto_select_check.setChecked(bool(self.config.run_auto_select_trays))
        self.auto_select_check.toggled.connect(self._on_auto_select_toggled)
        form.addRow(self.auto_select_check)

        self.package_check = QCheckBox("Package mode", form_holder)
        self.package_check.setChecked(bool(self.config.run_package_mode))
        self.package_check.toggled.connect(self._on_package_mode_toggled)
        form.addRow(self.package_check)

        self.batch_caption = self._muted_label("Batch size", form_holder)
        self.batch_spin = QSpinBox(form_holder)
        self.batch_spin.setRange(1, 999999)
        self.batch_spin.setValue(int(self.config.run_package_size))
        self.batch_spin.valueChanged.connect(self._on_batch_size_changed)
        form.addRow(self.batch_caption, self.batch_spin)
        self._apply_package_visibility()

        action = QWidgetAction(menu)
        action.setDefaultWidget(form_holder)
        menu.addAction(action)
        button.setMenu(menu)
        return button

    def _on_store_images_changed(self, label: str) -> None:
        mode = STORE_IMAGES_BY_LABEL.get(label, "none")
        self.config.set_run_store_images(mode)
        if mode != "none" and not self._store_warning_shown:
            self._store_warning_shown = True
            self.notify(STORE_IMAGES_WARNING_TITLE, STORE_IMAGES_WARNING_TEXT)

    def _on_floor_changed(self, value: int) -> None:
        # The feed reads config.run_confidence_floor live on every run/history
        # event (_on_run_history) — no separate wiring needed for the coloring.
        self.config.set_run_confidence_floor(int(value))

    def _on_auto_select_toggled(self, checked: bool) -> None:
        self.config.set_run_auto_select_trays(bool(checked))

    def _build_preview_column(self, parent: QWidget) -> QWidget:
        holder = QWidget(parent)
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(6)
        self.preview_label = QLabel("No frame", holder)
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Ignored + tiny minimum: the label must never report the pixmap as
        # its size hint, or each scaled frame grows the layout that the next
        # frame is scaled to — the window ratchets larger on every repaint.
        self.preview_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.preview_label.setMinimumSize(1, 1)
        # A video letterbox is black in every theme; not chrome, so not themed.
        self.preview_label.setStyleSheet("background-color: #000000; color: #808080;")
        column.addWidget(self.preview_label, 1)

        crop_row = QHBoxLayout()
        crop_row.addWidget(self._muted_label("Last cropped", holder))
        self.crop_label = QLabel("—", holder)
        self.crop_label.setObjectName("cropPanel")
        self.crop_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Fixed: the crop is the classifier's actual input, shown at one size
        # so it never competes with the live preview for space.
        self.crop_label.setFixedSize(CROP_SIZE, CROP_SIZE)
        crop_row.addWidget(self.crop_label)
        crop_row.addStretch(1)
        column.addLayout(crop_row)
        return holder

    def _build_settings_page(self) -> QWidget:
        page = QWidget()
        row = QHBoxLayout(page)
        row.setContentsMargins(12, 12, 12, 12)
        row.setSpacing(12)
        self.settings_list = QListWidget(page)
        self.settings_list.setFixedWidth(160)
        self.settings_pages = QStackedWidget(page)
        builders = {
            "Theme": self._build_theme_section,
            "Serial": self._build_serial_page,
            "Camera": lambda: build_camera_section(self),
            "Image Processing": lambda: build_imageproc_section(self),
            "AI Config": self._build_ai_page,
        }
        for name in SETTINGS_SECTIONS:
            self.settings_list.addItem(name)
            build = builders.get(name)
            self.settings_pages.addWidget(build() if build else self._placeholder_page())
        self.settings_list.currentRowChanged.connect(self.settings_pages.setCurrentIndex)
        self.settings_list.setCurrentRow(0)
        row.addWidget(self.settings_list)
        row.addWidget(self.settings_pages, 1)
        return page

    def _build_train_page(self) -> QWidget:
        # Kept on self: mode/changed and navigating to the page both refresh it.
        self.train_page = build_train_page(self)
        return self.train_page

    def _build_models_page(self) -> QWidget:
        # Kept on self: mode/changed and navigating to the page both refresh it.
        self.models_page = build_models_page(self)
        self.models_page.set_images_hook(self._open_model_images)
        self.models_page.set_headstamps_hook(self._open_headstamps)
        self.models_page.set_evaluate_hook(self._open_evaluator)
        return self.models_page

    def open_help(self) -> None:
        """F1 / Help menu: the guide dock, opened at the current context's topic."""
        page = next(
            (name for name, w in self._pages_by_name.items() if w is self.pages.currentWidget()),
            "Sort",
        )
        section = None
        if page == "Settings":
            item = self.settings_list.currentItem()
            section = item.text() if item is not None else None
        self.help_view.show_topic(topic_for(page, section))
        self.help_dock.show()
        self.help_dock.raise_()

    def _open_model_images(self, model: Any) -> None:
        from .dialog_model_images import ModelImagesDialog

        ModelImagesDialog(self, self.config, model.id).exec()

    def _open_headstamps(self, model: Any) -> None:
        from .dialog_headstamps import HeadstampManagerDialog

        HeadstampManagerDialog(self, self.config, model.id, bus=self.bus).exec()

    def _open_evaluator(self, model: Any) -> None:
        from .dialog_model_evaluator import ModelEvaluatorDialog

        ModelEvaluatorDialog(self, self, model).exec()

    def _build_ai_page(self) -> QWidget:
        # Kept on self: mode/changed re-reads it (refresh_mode).
        self.ai_section = build_ai_section(self)
        return self.ai_section

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
        self.theme_edit_button = QPushButton("Edit theme…", page)
        self.theme_edit_button.setMaximumWidth(240)
        self.theme_edit_button.clicked.connect(self._open_theme_editor)
        column.addWidget(self.theme_edit_button)
        column.addStretch(1)
        return page

    def _open_theme_editor(self) -> None:
        from .dialog_theme_editor import ThemeEditorDialog

        ThemeEditorDialog(self, self).exec()

    def _build_serial_page(self) -> QWidget:
        # Kept on self for tests and the serial/state reactions it subscribes.
        self.serial_section = build_serial_section(self)
        return self.serial_section

    def _build_serial_dock(self) -> None:
        self.serial_dock = QDockWidget("Serial Monitor", self)
        self.serial_dock.setObjectName("serialDock")
        self.serial_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        # The monitor subscribes serial/* itself and keeps the full session
        # history — a dock that exists from startup needs no backlog replay.
        self.serial_monitor = build_serial_monitor(self)
        self.serial_dock.setWidget(self.serial_monitor)
        # Bottom, like Arduino IDE's monitor / VS Code's terminal (JL).
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.serial_dock)
        self._watch_dock_transitions(self.serial_dock)

    def _build_history_dock(self) -> None:
        self.history_dock = QDockWidget("History", self)
        self.history_dock.setObjectName("historyDock")
        self.history_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        self.history_view = build_history_view(self)
        self.history_dock.setWidget(self.history_view)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.history_dock)
        # Supplementary, so it starts out of the way; View re-opens it.
        self.history_dock.hide()
        self._watch_dock_transitions(self.history_dock)

    def _watch_dock_transitions(self, dock: QDockWidget) -> None:
        """Recompute layout and repaint after a float/re-dock.

        Investigated live against a real board (JL, screenshot-verified,
        Wayland). Two symptoms, two different causes, in the order they were
        found and ruled out:

        1. Widget fragments visibly mixing into the dock area — turned out to
           be cv2's bundled Qt plugins loading against PySide6 (scrubbed in
           ``__main__.py``); the QDockWidget background in theme.py and the
           repaint calls below stay as defense-in-depth, not the fix.
        2. On genuine PySide6, after a float -> re-dock the central widget
           keeps its pre-float (shrunken) geometry — a dead band appears
           between it and the dock, unowned by either, and the Sort page's
           slot grid grows a horizontal scrollbar. This is a layout-
           activation failure, not a paint gap: QMainWindowLayout doesn't
           always recompute the central widget's geometry on its own when a
           dock's top-level state changes.
        3. Double-clicking a floating dock's title re-docks it collapsed —
           zero height/width, invisible, while its View-menu toggle still
           shows checked. ``_restore_collapsed_docks`` covers this; also
           wired to ``visibilityChanged`` for the View-toggle show path,
           which can leave the same collapsed state — but through a lighter
           handler than topLevelChanged/dockLocationChanged's: unlike those
           two, ``visibilityChanged`` fires on perfectly ordinary show/hide
           (a fresh window's own construction included), so it must never
           carry the resize-nudge fallback below — that's a "normal
           operation" case the nudge is explicitly not for, and running it
           there was an earlier version of this fix's own bug (a stray +1px
           window-size leak caught by the offscreen test suite).
        """
        dock.topLevelChanged.connect(self._schedule_dock_repaint)
        dock.dockLocationChanged.connect(self._schedule_dock_repaint)
        dock.visibilityChanged.connect(self._schedule_collapse_check)

    def _schedule_dock_repaint(self, *_args: Any) -> None:
        # Deferred one event-loop turn: Qt hasn't finished the dock's own
        # transition (float/re-dock) at the moment the signal fires.
        QTimer.singleShot(0, self._repaint_after_dock_transition)

    def _schedule_collapse_check(self, *_args: Any) -> None:
        QTimer.singleShot(0, self._restore_collapsed_docks)

    def _repaint_after_dock_transition(self) -> None:
        """Force QMainWindowLayout to recompute, then repaint what it owns."""
        layout = self.layout()
        if layout is not None:
            layout.invalidate()
            layout.activate()
        central = self.centralWidget()
        if central is not None:
            central.updateGeometry()
            central.update()
        self.serial_dock.update()
        self.history_dock.update()
        self.update()
        self._restore_collapsed_docks()
        self._nudge_layout_recompute()

    def _restore_collapsed_docks(self) -> None:
        """Push a collapsed dock back out to a usable size.

        ``resizeDocks`` is the API that actually sticks against a
        QMainWindowLayout-managed dock — plain ``resize()``/
        ``setFixedHeight()`` don't. The orientation-per-dock mapping matches
        each dock's fixed starting area (bottom / right, see
        ``_build_serial_dock`` / ``_build_history_dock``): dragging a dock to
        a different area is a separate user action, not the collapse bug.
        """
        for dock, orientation in (
            (self.serial_dock, Qt.Orientation.Vertical),  # bottom area: height
            (self.history_dock, Qt.Orientation.Horizontal),  # right area: width
        ):
            if not dock.isVisible() or dock.isFloating():
                continue
            size = dock.height() if orientation == Qt.Orientation.Vertical else dock.width()
            if size < DOCK_COLLAPSE_FLOOR_PX:
                self.resizeDocks([dock], [DOCK_RESTORED_SIZE_PX], orientation)

    def _nudge_layout_recompute(self) -> None:
        """Belt-and-braces fallback: a 1px resize round-trip.

        ``invalidate()``/``activate()`` is the direct fix and should be
        enough on its own; this covers whatever it doesn't, on the
        (unverified offscreen) chance QMainWindowLayout still needs an
        actual size change to re-flow the central widget against a dock
        that just changed float state. Guarded to the dock-transition path
        only — never called during normal operation — and restores the
        original size on the next event-loop turn, so it's a one-frame
        nudge rather than a visible resize.
        """
        size = self.size()
        self.resize(size.width(), size.height() + 1)
        QTimer.singleShot(0, lambda: self.resize(size))

    def _build_community_page(self) -> QWidget:
        self.community_page = build_community_page(self)
        self.community_page.on_auth_changed = self._on_auth_changed
        return self.community_page

    def _apply_auth_visibility(self) -> None:
        signed_in = self.community_page.is_signed_in()
        self._set_activity_visible("Community", signed_in)
        self.signin_button.setText("Sign out" if signed_in else "Sign in")
        self._update_identity_label(signed_in)

    def _update_identity_label(self, signed_in: bool) -> None:
        """Display name (or email) next to the Sign out button, display-only.

        Read straight off the auth object's decoded claims — same source the
        removed Community-page banner used, not the community server's
        profile metadata, so this never blocks on a network call.
        ``existing_auth_manager()`` never constructs one (CLAUDE.md: building
        must not touch MSAL) — if ``signed_in`` is True one already exists.
        """
        if not signed_in:
            self.identity_label.hide()
            self.identity_label.setText("")
            self.identity_label.setToolTip("")
            return
        auth = self.community_page.existing_auth_manager()
        try:
            name, email = auth.identity() if auth is not None else (None, None)
        except Exception:
            name, email = None, None
        name = (name or "").strip()
        email = (email or "").strip()
        self.identity_label.setText(name or email or "(unknown)")
        self.identity_label.setToolTip(email)
        self.identity_label.show()

    def _on_auth_changed(self) -> None:
        self._apply_auth_visibility()

    def _on_signin_clicked(self) -> None:
        if self.community_page.is_signed_in():
            self.community_page.sign_out()
        else:
            self.community_page.open_login()

    # ----- updates ------------------------------------------------------------

    def open_update_dialog(self, *, check: bool = False) -> None:
        from .dialog_update import UpdateDialog

        self._update_dialog = UpdateDialog(
            self, info=self._update_info, app=self, pending=self._pending_update, check_on_open=check
        )
        self._update_dialog.open()

    def note_pending_update(self, pending: Any) -> None:
        self._pending_update = pending
        self.update_button.setText("Restart to update")
        self.update_button.show()

    def note_update_info(self, info: Any) -> None:
        self._update_info = info
        if self._pending_update is not None:
            return  # a staged update outranks a fresh finding
        if info is None:
            self.update_button.hide()
        else:
            self.update_button.setText(f"Update to {info.version}")
            self.update_button.show()

    def _startup_update_check(self) -> None:
        """Silent, Tk order: staged update first, then an opt-out-able check."""
        from ..update import updater

        pending = updater.pending_update()
        if pending is not None:
            self.note_pending_update(pending)
            return
        if updater.checks_disabled() or self._load_setting(updater.SETTING_CHECK_ON_STARTUP) is False:
            return
        self.run_worker(
            updater.check_for_update,
            on_done=self.note_update_info,
            on_error=lambda _exc: None,  # silent by design; Help menu re-checks loudly
        )

    def _build_help_dock(self) -> None:
        # A dock, not a free window (JL): pin the guide beside the work while
        # learning, toggle it away after.
        self.help_dock = QDockWidget("User Guide", self)
        self.help_dock.setObjectName("helpDock")
        self.help_view = build_help_window(self)
        self.help_dock.setWidget(self.help_view)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.help_dock)
        self.help_dock.hide()

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
        history_toggle = self.history_dock.toggleViewAction()
        history_toggle.setText("Classification History")
        self.menus["View"].addAction(history_toggle)
        help_toggle = self.help_dock.toggleViewAction()
        help_toggle.setText("User Guide Panel")
        self.menus["View"].addAction(help_toggle)

        self.menus["Help"] = self.menuBar().addMenu("&Help")
        guide = self.menus["Help"].addAction("User Guide")
        guide.setShortcut(QKeySequence.StandardKey.HelpContents)  # F1
        guide.triggered.connect(self.open_help)
        check = self.menus["Help"].addAction("Check for updates…")
        check.triggered.connect(lambda: self.open_update_dialog(check=True))
        self.menus["Help"].addSeparator()
        about = self.menus["Help"].addAction("About")
        about.triggered.connect(self._show_about)
        license_action = self.menus["Help"].addAction("License")
        license_action.triggered.connect(self._show_license)

    # ----- navigation ---------------------------------------------------------

    def show_page(self, name: str) -> None:
        self.pages.setCurrentWidget(self._pages_by_name[name])
        if name == "Sort":
            # Assignments can have changed in Settings (or the Tk UI) since the
            # cards were last drawn; they are cheap to re-read and never cached.
            self._refresh_sort_grid()
        elif name == "Models":
            self.models_page.refresh(announce=True)
        elif name == "Community":
            self.community_page.refresh_auth_state()
        elif name == "Train":
            # Headstamps and images change from the Models page, the Tk UI and
            # imports; the counts are read off disk every time, never cached.
            self.train_page.refresh()

    def _open_data_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(app_data_dir())))

    def _show_about(self) -> None:
        from .dialog_about import build_about_dialog

        build_about_dialog(self).exec()

    def _show_license(self) -> None:
        from .dialog_about import build_license_dialog

        build_license_dialog(self).exec()

    def open_slot_editor(self, slot: int) -> None:
        """Edit what routes to one slot. The catch-all isn't configurable."""
        if int(slot) == 0:
            self.set_status(CATCH_ALL_HINT)
            return
        dialog = SlotAssignDialog(self.config, int(slot), self)
        dialog.changed.connect(self._refresh_sort_grid)
        dialog.exec()
        self._refresh_sort_grid()

    def _refresh_templates(self) -> None:
        """Repopulate the combo for the active model + current run mode."""
        mode = self.config.slot_template_mode()
        self._templates = self.config.list_slot_templates(mode)
        active = self.config.active_slot_template(mode)
        self.template_combo.clear()
        self.template_combo.addItems([t.name for t in self._templates])
        for index, template in enumerate(self._templates):
            if template.id == active.id:
                self.template_combo.setCurrentIndex(index)
                break
        self.template_hint.setText("Package-mode layout" if mode == "package" else "")

    def _template_busy(self) -> bool:
        """Templates swap the whole layout, so keep them out of a live run."""
        if not self._is_running:
            return False
        self.notify(
            "Run in progress",
            "Stop the run before changing sorting templates — switching one reassigns every slot.",
        )
        return True

    def _on_template_selected(self, index: int) -> None:
        if index < 0 or index >= len(self._templates):
            return
        target = self._templates[index]
        if self._template_busy() or self.config.activate_slot_template(target.id) is None:
            self._refresh_templates()  # snap the combo back to the active one
            return
        self._after_template_change(f"Loaded sorting template “{target.name}”.")

    def new_template(self) -> None:
        if self._template_busy():
            return
        mode = self.config.slot_template_mode()
        dialog = NewTemplateDialog(self.config, mode, self.config.active_slot_template(mode).name, self)
        if dialog.exec() and dialog.created is not None:
            self._after_template_change(f"Created sorting template “{dialog.created.name}”.")

    def edit_template(self) -> None:
        if self._template_busy():
            return
        mode = self.config.slot_template_mode()
        dialog = EditTemplateDialog(
            self.config,
            self.config.active_slot_template(mode),
            can_delete=len(self.config.list_slot_templates(mode)) > 1,
            parent=self,
        )
        if dialog.exec():
            self._after_template_change("Sorting templates updated.")

    def _after_template_change(self, status: str) -> None:
        """Counters are per-layout: a slot may hold another headstamp now."""
        self._refresh_templates()
        self._clear_counts()
        self._refresh_sort_grid()
        self.set_status(status)

    def _apply_package_visibility(self) -> None:
        enabled = self.package_check.isChecked()
        self.batch_caption.setVisible(enabled)
        self.batch_spin.setVisible(enabled)

    def _on_package_mode_toggled(self, enabled: bool) -> None:
        self.config.set_run_package_mode(bool(enabled))
        self._apply_package_visibility()
        # Counts, assignments and templates are all mode-specific.
        self._clear_counts()
        self._refresh_templates()
        self._refresh_sort_grid()

    def _on_batch_size_changed(self, value: int) -> None:
        self.config.set_run_package_size(int(value))
        self._refresh_sort_grid()

    def _clear_counts(self) -> None:
        self.slot_grid.reset_counts()
        self._master_count = 0
        self.master_count_label.setText("0")

    def reset_counts(self) -> None:
        """Zero the dashboard's counters and the run's package batches."""
        self._clear_counts()
        reset = getattr(self.run_controller, "reset_package_counts", None)
        if reset is not None:
            reset()
        self.set_status("Counters reset.")

    def reset_slot_count(self, slot: int) -> None:
        """Package mode: empty one bin and let it refill while the run continues."""
        reset = getattr(self.run_controller, "reset_package_slot", None)
        if reset is not None:
            reset(int(slot))
        self.slot_grid.reset_slot(int(slot))
        self.set_status(f"Reset counter for slot {slot}.")

    # ----- active-model mode --------------------------------------------------

    def _active_model(self) -> Any | None:
        if self.db is None:
            return None
        from ..data.repository import ModelRepo, SettingsRepo

        model_id = SettingsRepo(self.db).get_active_model_id()
        return ModelRepo(self.db).get(model_id) if model_id is not None else None

    def _apply_mode_visibility(self) -> None:
        """Train is for a local model this user owns — see models.is_trainable."""
        from ..data.models import is_trainable

        self._set_activity_visible("Train", is_trainable(self._active_model()))

    def _set_activity_visible(self, name: str, visible: bool) -> None:
        button = self.sidebar_buttons[name]
        button.setVisible(visible)
        if not visible and self.pages.currentWidget() is self._pages_by_name[name]:
            self.sidebar_buttons["Sort"].setChecked(True)
            self.show_page("Sort")

    def _on_mode_changed(self) -> None:
        """The active model changed: everything scoped to it is re-read."""
        self._apply_mode_visibility()
        self._clear_counts()
        self._refresh_templates()
        self._refresh_sort_grid()
        self.ai_section.refresh_mode()
        # Everything on the Train page is scoped to the active model.
        self.train_page.refresh()
        # The library's active marker is the mode, spelled out per row.
        self.models_page.refresh()

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

    @staticmethod
    def _bytes_to_setting(data: bytes) -> str:
        """Base64 text: SettingsRepo stores JSON-encoded values, not raw bytes."""
        return base64.b64encode(bytes(data)).decode("ascii")

    @staticmethod
    def _setting_to_bytes(value: Any) -> bytes | None:
        if not isinstance(value, str) or not value:
            return None
        try:
            return base64.b64decode(value.encode("ascii"))
        except (ValueError, TypeError):
            return None

    def _restore_window_state(self) -> None:
        """Dock layout + the model table's column widths, from the last session."""
        state = self._setting_to_bytes(self._load_setting(SETTING_WINDOW_STATE))
        if state is not None:
            self.restoreState(QByteArray(state))
        columns = self._setting_to_bytes(self._load_setting(SETTING_MODELS_COLUMNS))
        if columns is not None:
            self.models_page.restore_header_state(columns)

    def _save_window_state(self) -> None:
        self._save_setting(SETTING_WINDOW_STATE, self._bytes_to_setting(bytes(self.saveState().data())))
        self._save_setting(SETTING_MODELS_COLUMNS, self._bytes_to_setting(self.models_page.header_state()))

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
        # Colors baked into rich text / per-line paints need a hand re-render.
        self._render_feed()
        if hasattr(self, "serial_monitor"):
            self.serial_monitor.apply_palette()
        if hasattr(self, "history_view"):
            self.history_view.apply_palette()
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
        # Every camera/serial connect-state change can flip the Sort page
        # between the guided empty state and the real dashboard.
        self._update_sort_empty_state()

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
        # Tk pushes the board init settings from its shared connect tail too,
        # so auto-connect and the Settings page behave alike.
        if self.config.serial.get("init_on_startup", False):
            settings = dict(self.config.serial.get("init_settings", {}))
            if settings:
                self.run_worker(
                    lambda: broker.update_init_settings(settings),
                    on_done=lambda _r: self.set_status(f"Connected to {port}. Init settings pushed."),
                    on_error=lambda err: self.set_status(f"Init push failed: {err}"),
                )

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
            port = (self.config.serial.get("port") or "").strip()
        if not port:
            self.set_status("No port selected.")
            self._set_serial_indicator("Serial: no port selected", connected=False)
            return

        if port == EMULATED_PORT:
            broker: Any = EmulatorBroker()
            broker.try_open()
            self._after_connect(broker, port, source="manual")
            return

        baud = int(self.config.serial.get("baud", 9600))
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
        self._refresh_sort_grid()
        self._update_run_buttons()

    def notify(self, title: str, text: str) -> None:
        """User-facing warning. Tests patch this — never let a modal open there."""
        QMessageBox.warning(self, title, text)

    def _ai_credentials_missing(self) -> bool:
        """AI Config mode can't classify without an API key and a model name.

        Scoped to that mode: a local model never touches the HTTP client, so
        an unset key there is no reason to refuse a run.
        """
        if classifier.uses_local_inference(self.db):
            return False
        api = self.config.api
        return not (api.get("api_key") and api.get("model"))

    def _ready_to_sort(self) -> RunController | None:
        """Preflight, in the Tk Run tab's order: board, AI config, checkpoint, torch.

        Each check is asked of the layer that owns the answer, so the Qt shell
        never re-derives the rule. Returns the controller when a run may start.
        """
        controller = self.run_controller
        if controller is None or self.broker is None:
            self.set_status("Connect to the board first (Settings → Serial).")
            return None
        if self._ai_credentials_missing():
            self.notify(
                "AI not configured",
                "Set the endpoint, API key and model on the AI Config page first.",
            )
            return None
        problem = classifier.checkpoint_problem(self.db)
        if problem is not None:
            self.notify("Model not ready", problem)
            return None
        if classifier.uses_local_inference(self.db) and not self.ensure_torch(
            self.start_run, reason="Sorting needs PyTorch"
        ):
            # The gate re-enters start_run after a successful install.
            return None
        return controller

    def start_run(self) -> None:
        controller = self._ready_to_sort()
        if controller is None or self._is_running:
            return
        self._refresh_sort_grid()
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

    def _on_run_started(self) -> None:
        # Counts survive Stop/Start on purpose (Tk parity): operators stop to
        # clear a jam and restart mid-tray. Only the explicit resets clear.
        self._set_running(True)

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
        # The Train page's Feed drives the same board.
        train_page = getattr(self, "train_page", None)
        if train_page is not None:
            train_page.refresh_connection()

    def _on_run_result(self, result: Any) -> None:
        # `run/result` carries a slot even for a failed cycle, so `ok` is what
        # decides whether a case actually landed anywhere.
        if not isinstance(result, dict) or not result.get("ok"):
            return
        self.slot_grid.increment(int(result.get("slot") or 0))
        self._master_count += 1
        self.master_count_label.setText(str(self._master_count))

    def _on_run_history(self, payload: Any) -> None:
        """One classification for the recent-feed strip (newest first) + its crop."""
        if not isinstance(payload, dict):
            return
        self._show_crop(payload.get("image"))
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

    def _show_crop(self, image: Any) -> None:
        """The headstamp as the classifier saw it, at a fixed size."""
        if not isinstance(image, np.ndarray) or image.size == 0:
            return
        pixmap = QPixmap.fromImage(self.frame_to_image(image))
        self.crop_label.setPixmap(
            pixmap.scaled(
                self.crop_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def beep(self) -> None:
        """Non-blocking batch-complete tone. Best-effort — never fails a handler."""
        try:
            QApplication.beep()
        except Exception:
            pass

    def _on_package_full(self, payload: Any) -> None:
        data = payload if isinstance(payload, dict) else {}
        self.beep()
        self.set_status(f"Slot {data.get('slot')} batch full ({data.get('count')}). Reset it to refill.")

    def _on_package_halt(self, payload: Any) -> None:
        label = (payload or {}).get("label") if isinstance(payload, dict) else None
        self.beep()
        message = (
            f"Run stopped — every slot for “{label or '?'}” is full. "
            "Empty the bins, reset their counters, then Start again."
        )
        self.set_status(message)
        # Tk shows a dialog here and operators rely on it. Queued single-shot:
        # a modal straight from a bus handler would re-enter the drain.
        QTimer.singleShot(0, lambda: self.notify("Package complete", message))

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
        # A monotonic token, never id(fn): CPython reuses freed addresses, so
        # two sequential workers can share an id — and with the subscriptions
        # left in place, the second worker's result would also be delivered to
        # the first worker's stale callback (a cartridge list arriving in a
        # username handler, in practice).
        token = next(self._worker_tokens)
        topic_done = f"worker/done/{token}"
        topic_err = f"worker/err/{token}"

        def _deliver_done(payload: Any) -> None:
            _unsubscribe()
            if on_done is not None:
                on_done(payload)

        def _deliver_err(exc: Any) -> None:
            _unsubscribe()
            if on_error is not None:
                on_error(exc)

        def _unsubscribe() -> None:
            self.bus.unsubscribe(topic_done, _deliver_done)
            self.bus.unsubscribe(topic_err, _deliver_err)

        self.bus.subscribe(topic_done, _deliver_done)
        self.bus.subscribe(topic_err, _deliver_err)

        def _run() -> None:
            try:
                self.bus.post(topic_done, fn())
            except Exception as exc:
                traceback.print_exc()
                self.bus.post(topic_err, exc)

        threading.Thread(target=_run, daemon=True).start()

    # ----- lifecycle ----------------------------------------------------------

    def closeEvent(self, event: Any) -> None:
        # No confirm-on-close while a run is active: Tk's own _on_close
        # (ui/app.py) doesn't ask either — it just stops the controller and
        # destroys the window. Mirrored here rather than adding a prompt Tk
        # never had.
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
        try:
            self._save_window_state()
        except Exception:
            # A preference that can't be persisted must never block shutdown.
            pass
        super().closeEvent(event)


def default_qpa_platform() -> None:
    """Linux: prefer XCB (XWayland) over native Wayland.

    A floated ``QDockWidget`` is frozen under native Wayland — JL hit this
    live (release a floating dock and it can no longer be moved or resized):
    a frameless top-level window can't ask a Wayland compositor to move/
    resize it, an upstream Qt/Wayland limitation, not something fixable in
    application code. XCB via XWayland doesn't have the gap.

    ``setdefault`` so an explicit ``QT_QPA_PLATFORM`` (env, or a test's
    ``offscreen``) always wins. The semicolon list, never a bare ``"xcb"``:
    Qt tries entries left to right, so this still falls back to native
    Wayland on a box missing an XWayland dependency (JL hit
    ``libxcb-cursor0`` missing) instead of failing to start.
    """
    if sys.platform.startswith("linux"):
        os.environ.setdefault("QT_QPA_PLATFORM", "xcb;wayland")


def run_app(config: Any) -> int:
    default_qpa_platform()
    app = QApplication.instance() or QApplication(sys.argv[:1])
    window = QtMainWindow(config)
    window.resize(1024, 768)
    window.show()
    return app.exec()
