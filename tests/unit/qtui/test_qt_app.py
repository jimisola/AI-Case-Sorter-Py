"""The Qt shell, built and driven headless — no display, no Xvfb, no hardware.

This is the requirement-4 proof from docs/ui-modernization.md: real widgets on
the offscreen platform plugin, with the event bus doing the cross-thread work.
"""

from __future__ import annotations

import os
import types

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("tkinter")  # sorter.ui.theme (the palettes) imports it

# Must be set before anything constructs a QApplication.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

from sorter.qtui.app import QtMainWindow


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def config():
    return types.SimpleNamespace(
        camera={"device_index": 0, "width": 640, "height": 480},
        serial={"port": "", "baud": 9600},
        save=lambda: None,
        db=None,
    )


@pytest.fixture
def window(qapp, config):
    # auto_connect=False: constructing the shell must not open a camera or a port.
    win = QtMainWindow(config, auto_connect=False)
    yield win
    win.close()


def test_sidebar_activities(window) -> None:
    assert list(window.sidebar_buttons) == ["Sort", "Train", "Models", "Community", "Settings"]
    assert window.sidebar_buttons["Sort"].isChecked()
    assert window.pages.currentWidget() is window._pages_by_name["Sort"]


@pytest.mark.parametrize("name", ["Train", "Models", "Community", "Settings", "Sort"])
def test_sidebar_switches_pages(window, name: str) -> None:
    window.sidebar_buttons[name].click()

    assert window.pages.currentWidget() is window._pages_by_name[name]
    assert window.sidebar_buttons[name].isChecked()


def test_sidebar_fits_the_widest_label(window) -> None:
    # Regression: a fixed 84 px sidebar clipped "Community" on wider fonts.
    sidebar = window.sidebar_buttons["Sort"].parentWidget()
    widest = max(sidebar.fontMetrics().horizontalAdvance(n) for n in window.sidebar_buttons)

    assert sidebar.minimumWidth() >= widest + 24


def test_sort_actions_are_present_but_disabled(window) -> None:
    assert list(window.action_buttons) == ["Start", "Stop", "Manual feed"]
    assert not any(button.isEnabled() for button in window.action_buttons.values())


def test_serial_dock_logs_traffic(window) -> None:
    assert not window.serial_dock.isHidden()

    window.bus.post("serial/rx", "ok")
    window.bus.drain()

    assert "<- ok" in window.serial_log.toPlainText()


def test_menus(window) -> None:
    assert [a.text().replace("&", "") for a in window.menuBar().actions()] == [
        "File",
        "View",
        "Help",
    ]
    # window.menus, not action.menu(): the latter hands back a Python-owned
    # wrapper and destroys the C++ menu when the temporary is collected.
    assert [a.text() for a in window.menus["View"].actions()] == ["Serial Monitor"]
    assert window.serial_dock.toggleViewAction() in window.menus["View"].actions()


def test_theme_section_hosts_the_theme_combo(window) -> None:
    window.sidebar_buttons["Settings"].click()
    window.settings_list.setCurrentRow(window.settings_list.count() - 1)

    assert window.settings_list.currentItem().text() == "Theme"
    page = window.settings_pages.currentWidget()
    assert window.theme_combo.parentWidget() is page


def test_theme_switch_restyles_the_window(window) -> None:
    window.theme_combo.setCurrentText("Dark")
    dark = window.styleSheet()

    window.theme_combo.setCurrentText("Light")

    assert window.styleSheet() != dark
    assert window.theme_name == "Light"


def test_indicators_start_disconnected(window) -> None:
    assert "disconnected" in window.camera_label.text()
    assert "disconnected" in window.serial_label.text()


def test_serial_indicator_updates_and_announces(window) -> None:
    seen = []
    window.bus.subscribe("serial/state", seen.append)

    window._set_serial_indicator("Serial: connected (COM3)", connected=True)
    window.bus.drain()

    assert "connected (COM3)" in window.serial_label.text()
    assert seen == [{"connected": True, "message": "Serial: connected (COM3)"}]


def test_status_topic_reaches_the_status_bar(window) -> None:
    window.bus.post("status", "Auto-connect: probing COM3…")
    window.bus.drain()

    assert window.statusBar().currentMessage() == "Auto-connect: probing COM3…"


def test_bgr_frame_renders(window) -> None:
    frame = np.zeros((480, 640, 3), np.uint8)

    pixmap = QPixmap.fromImage(window.frame_to_image(frame))

    assert not pixmap.isNull()
    assert (pixmap.width(), pixmap.height()) == (640, 480)


def test_preview_frames_never_grow_the_window(qapp, window) -> None:
    # Regression: the scaled pixmap must not feed back into the layout's
    # minimum, or the window ratchets larger on every preview repaint.
    window.resize(1024, 768)
    window.show()
    qapp.processEvents()
    minimum_before = window.minimumSizeHint()
    size_before = window.size()

    frame = np.zeros((1080, 1920, 3), np.uint8)
    window.camera = types.SimpleNamespace(latest_frame=lambda: frame)
    for _ in range(3):
        window._refresh_preview()
        qapp.processEvents()

    assert window.minimumSizeHint() == minimum_before
    assert window.size() == size_before
