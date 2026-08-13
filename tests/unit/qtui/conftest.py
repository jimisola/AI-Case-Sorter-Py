"""Shared offscreen fixtures for the Qt spike tests.

Every window here is built against a REAL SQLite-backed ``Config`` on a temp
dir — the Sort dashboard reads slot assignments straight out of it, so a stub
config would only test the stub.
"""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

# Must be set before anything constructs a QApplication.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# Marks the few tests whose event-loop pump takes an access violation inside
# Qt's offscreen plugin on the *Windows CI runner only* (deterministic across
# many runs; survived rich-text removal, timer shutdown on close, per-test
# DeferredDelete flushing and receiver-bound worker slots — all kept, each
# correct hygiene on its own). The poison detonates at whichever real pump
# runs first, so skipping one site moves the crash to the next; the class is
# marked instead. An offscreen-runner artifact, not an app bug — the real
# Windows app runs the native windows platform plugin, and Linux (offscreen)
# pins the same behaviors green. Revisit on PySide6 upgrades.
skip_win32_pump_av = pytest.mark.skipif(
    sys.platform == "win32",
    reason="Qt offscreen event pump takes an access violation on the Windows CI runner",
)


@pytest.fixture(scope="session")
def qapp():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _collect_between_tests():
    """Override the repo-wide forced gc between tests (tests/conftest.py).

    That fixture exists for Tk: Variables only die in the cyclic collector,
    and one finalized on a worker thread calls into Tcl from the wrong
    thread. Nothing in this directory makes Tk objects, so the reason does
    not apply — and forcing the collector over half-torn-down Qt widget
    trees is actively harmful: shiboken wrappers finalize against C++
    objects mid-teardown, which reproducibly corrupted the heap on the
    Windows CI runner (0xc0000374), and flushing deferred deletions first
    only moved the crash to Linux. Qt test suites (pytest-qt included) run
    without forced collection; so do these.

    What DOES run here: a DeferredDelete-only flush. Almost no test pumps
    Qt's event loop (``drain_until`` drains only the bus), so deleteLater
    work from every test otherwise piles up until the suite's rare
    ``processEvents()`` call flushes hundreds of tests' worth at once —
    which is where the Windows runner took a deterministic access
    violation. Flushing per test keeps that backlog at one test's worth.
    Deliberately NOT a generic ``processEvents()``: delivering arbitrary
    queued events into half-torn windows is what segfaulted Linux when
    that was tried.
    """
    yield
    try:
        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QApplication
    except ImportError:  # no [qt] extra: the test modules all skip anyway
        return
    app = QApplication.instance()
    if app is not None:
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)


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
