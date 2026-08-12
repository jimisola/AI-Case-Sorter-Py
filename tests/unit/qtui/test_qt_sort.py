"""The Sort dashboard: slot cards, live counts, the recent feed, and the run.

Everything here runs offscreen against a real SQLite-backed ``Config`` and,
where a board is needed, the in-process serial emulator — no display, no
hardware, no network.
"""

from __future__ import annotations

import types

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("tkinter")  # sorter.ui.theme (the palettes) imports it

from sorter.control.run_controller import RunController
from sorter.hardware.serial_emulator import EMULATED_PORT, EmulatorBroker
from sorter.ml import classifier, local_inference
from sorter.qtui.app import FEED_MAX
from sorter.qtui.slot_grid import CATCH_ALL_HINT, EMPTY_HINT

from .conftest import drain_until, seed_model


class FakeBroker:
    port = "COM-fake"
    baud = 9600
    firmware_version = "Fake-1.0"
    is_connected = True

    def stop(self) -> None:
        pass


class FakeController:
    def __init__(self) -> None:
        self.started = 0
        self.stopped = 0
        self.cycles = 0

    def start(self) -> None:
        self.started += 1

    def stop(self) -> None:
        self.stopped += 1

    def cycle_once(self) -> dict:
        self.cycles += 1
        return {"ok": True, "slot": 0}


@pytest.fixture
def connected(window):
    """A window holding a stand-in board and controller (no run loop)."""
    controller = FakeController()
    window.broker = FakeBroker()
    window.run_controller = controller
    window._update_run_buttons()
    return controller


def history(label: str, confidence: float, slot: int = 1) -> dict:
    """A ``run/history`` payload as ``RunController._post_history`` builds it."""
    return {
        "image": np.zeros((480, 480, 3), np.uint8),
        "label": label,
        "parent": None,
        "confidence": confidence,
        "slot": slot,
    }


# ----- slot cards ------------------------------------------------------------


def test_slot_cards_cover_every_slot_including_the_catch_all(window) -> None:
    cards = window.slot_grid.cards

    assert sorted(cards) == list(range(8))  # serial.slot_quantity default
    assert cards[0].title_label.text() == "Catch-All"
    assert cards[0].names_label.text() == CATCH_ALL_HINT
    assert cards[3].title_label.text() == "Slot #3"


def test_slot_count_follows_the_serial_setting(config, window_factory) -> None:
    config.serial["slot_quantity"] = 4

    cards = window_factory(config).slot_grid.cards

    assert sorted(cards) == [0, 1, 2, 3]


def test_slot_cards_show_the_active_models_assignments(config, window_factory) -> None:
    seed_model(config, {"9mm FC": 1, ".223 LC": 2, "45 ACP": 1})

    cards = window_factory(config).slot_grid.cards

    assert cards[1].names_label.text() == "45 ACP, 9mm FC"  # case-folded sort
    assert cards[2].names_label.text() == ".223 LC"
    assert cards[3].names_label.text() == EMPTY_HINT


def test_slot_cards_follow_ai_config_headstamps(config, window) -> None:
    # No active model: headstamps live in a settings key, and the grid must go
    # through Config for them exactly like the model-scoped case.
    config.add_headstamp("9mm RP", 3)

    window.slot_grid.refresh_assignments()

    assert window.slot_grid.cards[3].names_label.text() == "9mm RP"


def test_returning_to_sort_re_reads_the_assignments(config, window) -> None:
    window.sidebar_buttons["Settings"].click()
    config.add_headstamp("9mm RP", 3)

    window.sidebar_buttons["Sort"].click()

    assert window.slot_grid.cards[3].names_label.text() == "9mm RP"


def test_refresh_picks_up_a_reassignment(config, window) -> None:
    config.add_headstamp("9mm RP", 3)
    window.slot_grid.refresh_assignments()

    config.set_headstamp_slot("9mm RP", 5)
    window.slot_grid.refresh_assignments()

    assert window.slot_grid.cards[3].names_label.text() == EMPTY_HINT
    assert window.slot_grid.cards[5].names_label.text() == "9mm RP"


# ----- live counts -----------------------------------------------------------


def test_sorted_case_increments_its_card(window) -> None:
    for _ in range(2):
        window.bus.post("run/result", {"ok": True, "slot": 2, "label": "9mm"})
    window.bus.drain()

    assert window.slot_grid.cards[2].count_label.text() == "2"
    assert window.slot_grid.cards[1].count_label.text() == "0"


def test_below_floor_case_counts_against_the_catch_all(window) -> None:
    window.bus.post("run/result", {"ok": True, "slot": 0, "label": "9mm"})
    window.bus.drain()

    assert window.slot_grid.cards[0].count_label.text() == "1"


def test_failed_cycle_is_not_counted(window) -> None:
    window.bus.post("run/result", {"ok": False, "slot": 2, "error": "Sort timeout"})
    window.bus.drain()

    assert window.slot_grid.cards[2].count_label.text() == "0"


# ----- recent-classification feed --------------------------------------------


def test_feed_lists_newest_first(window) -> None:
    for label in ("9mm", ".223", "45 ACP"):
        window.bus.post("run/history", history(label, 99.0))
    window.bus.drain()

    text = window.feed_label.text()
    assert text.index("45 ACP") < text.index(".223") < text.index("9mm")


def test_feed_caps_what_it_shows(window) -> None:
    for index in range(FEED_MAX + 5):
        window.bus.post("run/history", history(f"hs{index}", 99.0))
    window.bus.drain()

    text = window.feed_label.text()
    assert text.count("99%") == FEED_MAX
    assert "hs0" not in text  # the oldest fell off the end
    assert f"hs{FEED_MAX + 4}" in text


def test_feed_colors_confidence_against_the_floor(window, config) -> None:
    config.set_run_confidence_floor(80)

    window.bus.post("run/history", history("9mm", 92.0))
    window.bus.post("run/history", history("unknown", 41.0))
    window.bus.drain()

    text = window.feed_label.text()
    assert f'<span style="color: {window.palette_colors["success"]};">92%' in text
    assert f'<span style="color: {window.palette_colors["warning"]};">41%' in text


def test_feed_recolors_on_a_theme_switch(window) -> None:
    window.bus.post("run/history", history("9mm", 99.0))
    window.bus.drain()
    before = window.feed_label.text()

    window.set_theme("Comic Book")

    assert window.feed_label.text() != before
    assert window.palette_colors["success"] in window.feed_label.text()


# ----- start preflight -------------------------------------------------------


def test_start_without_a_board_says_so_and_starts_nothing(window, monkeypatch) -> None:
    notices = []
    monkeypatch.setattr(window, "notify", lambda title, text: notices.append(title))

    window.start_run()

    assert window.run_controller is None
    assert "Settings → Serial" in window.statusBar().currentMessage()
    assert notices == []


def test_start_refuses_a_model_without_a_checkpoint(window, connected, monkeypatch) -> None:
    notices = []
    monkeypatch.setattr(window, "notify", lambda title, text: notices.append((title, text)))
    monkeypatch.setattr(classifier, "checkpoint_problem", lambda _db: "no trained model file")

    window.start_run()

    assert notices == [("Model not ready", "no trained model file")]
    assert connected.started == 0


def test_start_refuses_a_local_model_without_torch(window, connected, monkeypatch) -> None:
    notices = []
    monkeypatch.setattr(window, "notify", lambda title, text: notices.append(title))
    monkeypatch.setattr(classifier, "checkpoint_problem", lambda _db: None)
    monkeypatch.setattr(classifier, "uses_local_inference", lambda _db: True)
    monkeypatch.setattr(local_inference, "is_installed", lambda: False)

    window.start_run()

    assert notices == ["PyTorch required"]
    assert connected.started == 0


def test_start_runs_the_controller_in_ai_config_mode(window, connected) -> None:
    # Fresh DB = AI Config mode: nothing local to check, so no notice.
    window.start_run()

    assert connected.started == 1


def test_stop_stops_the_controller(window, connected) -> None:
    window.stop_run()

    assert connected.stopped == 1


def test_manual_feed_runs_one_cycle_off_the_main_thread(window, connected) -> None:
    window.manual_feed()

    assert drain_until(window, lambda: connected.cycles == 1)


# ----- button state ----------------------------------------------------------


def test_actions_enable_once_a_board_is_present(window, connected) -> None:
    assert window.action_buttons["Start"].isEnabled()
    assert window.action_buttons["Manual feed"].isEnabled()
    assert not window.action_buttons["Stop"].isEnabled()


def test_run_events_own_the_button_state(window, connected) -> None:
    window.bus.post("run/started", None)
    window.bus.drain()

    assert not window.action_buttons["Start"].isEnabled()
    assert not window.action_buttons["Manual feed"].isEnabled()
    assert window.action_buttons["Stop"].isEnabled()

    window.bus.post("run/stopped", None)
    window.bus.drain()

    assert window.action_buttons["Start"].isEnabled()
    assert not window.action_buttons["Stop"].isEnabled()


def test_run_error_reaches_the_status_bar(window) -> None:
    window.bus.post("run/error", "Sort timeout")
    window.bus.drain()

    assert window.statusBar().currentMessage() == "Run error: Sort timeout"


# ----- Settings → Serial -----------------------------------------------------


def test_port_list_offers_the_emulator(window, monkeypatch) -> None:
    monkeypatch.setattr("sorter.hardware.serial_broker.list_serial_ports", lambda: ["COM7"])

    window.refresh_ports()

    ports = [window.port_combo.itemText(i) for i in range(window.port_combo.count())]
    assert ports == ["COM7", EMULATED_PORT]


def test_connecting_the_emulator_wires_the_run_controller(window, config) -> None:
    from sorter.data.config import Config

    window.port_combo.setCurrentText(EMULATED_PORT)
    window.connect_serial()

    assert isinstance(window.broker, EmulatorBroker)
    assert isinstance(window.run_controller, RunController)
    assert window.run_controller.broker is window.broker
    assert "connected" in window.serial_label.text()
    assert window.action_buttons["Start"].isEnabled()
    # Persisted, not just remembered in the in-memory section.
    assert Config(config.db).load().serial["port"] == EMULATED_PORT


def test_manual_feed_drives_the_emulator_end_to_end(window, config, monkeypatch) -> None:
    config.add_headstamp("9mm FC", 2)
    monkeypatch.setattr(classifier, "classify_active", lambda *a, **k: ("9mm FC", 99.0))
    # The controller captures the camera it is built with, so stub before connecting.
    window.camera = types.SimpleNamespace(
        capture_frame=lambda: np.zeros((480, 640, 3), np.uint8),
        latest_frame=lambda: None,
        stop=lambda: None,
    )
    window.port_combo.setCurrentText(EMULATED_PORT)
    window.connect_serial()

    window.action_buttons["Manual feed"].click()

    assert drain_until(window, lambda: window.slot_grid.cards[2].count_label.text() == "1")
    assert "9mm FC" in window.feed_label.text()
    # The dock saw the exchange: the wheel command out, the board's ack back.
    log = window.serial_log.toPlainText()
    assert "-> xf:0" in log
    assert "<- done" in log
