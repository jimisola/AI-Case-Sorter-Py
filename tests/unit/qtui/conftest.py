"""Shared offscreen fixtures for the Qt spike tests.

Every window here is built against a REAL SQLite-backed ``Config`` on a temp
dir — the Sort dashboard reads slot assignments straight out of it, so a stub
config would only test the stub.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

# Must be set before anything constructs a QApplication.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qapp():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def config(tmp_path: Path):
    from sorter.data.config import Config
    from sorter.data.db import Database

    db = Database(tmp_path / "casesorter.db")
    db.ensure_initialized()
    return Config(db).load()


@pytest.fixture
def window_factory(qapp) -> Any:
    """Build a window on a given config; every one is closed at teardown."""
    from sorter.qtui.app import QtMainWindow

    windows = []

    def _make(cfg: Any) -> Any:
        # auto_connect=False: constructing the shell must not open a camera or a port.
        window = QtMainWindow(cfg, auto_connect=False)
        windows.append(window)
        return window

    yield _make
    for window in windows:
        window.close()


@pytest.fixture
def window(window_factory, config):
    return window_factory(config)


def seed_model(config: Any, assignments: dict[str, int], *, name: str = "Test model") -> int:
    """Create a model, activate it, and assign headstamps to slots."""
    from sorter.data.models import Model
    from sorter.data.repository import CartridgeRepo, HeadstampRepo, ModelRepo, SettingsRepo

    cartridge = CartridgeRepo(config.db).list()[0]
    model = ModelRepo(config.db).create(Model(name=name, cartridge_id=cartridge.id))
    headstamps = HeadstampRepo(config.db)
    for headstamp, slot in assignments.items():
        headstamps.add(model.id, headstamp, slot)
    SettingsRepo(config.db).set_active_model_id(model.id)
    return model.id


def drain_until(window: Any, predicate: Callable[[], bool], timeout_s: float = 5.0) -> bool:
    """Pump the bus on this thread until ``predicate`` holds (or time runs out).

    The worker/broker threads post; only the main thread may dispatch, so this
    is the test-side stand-in for the drain QTimer.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        window.bus.drain()
        if predicate():
            return True
        time.sleep(0.01)
    window.bus.drain()
    return predicate()
