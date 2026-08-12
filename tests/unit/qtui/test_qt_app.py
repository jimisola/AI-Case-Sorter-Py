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


def test_tabs(window) -> None:
    titles = [window.tabs.tabText(i) for i in range(window.tabs.count())]
    assert titles == ["Run", "Camera", "Serial"]


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
