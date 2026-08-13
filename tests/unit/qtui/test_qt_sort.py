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
        self.package_resets: list[object] = []

    def start(self) -> None:
        self.started += 1

    def stop(self) -> None:
        self.stopped += 1

    def cycle_once(self) -> dict:
        self.cycles += 1
        return {"ok": True, "slot": 0}

    def reset_package_counts(self) -> None:
        self.package_resets.append("all")

    def reset_package_slot(self, slot: int) -> None:
        self.package_resets.append(slot)


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


def test_a_card_never_shortens_its_headstamp_list(config, window_factory) -> None:
    # The card is how an operator knows what is in the bin, so the list is
    # always complete: it wraps and the card grows, never elides.
    names = [f"Headstamp {i:02d} with a long name" for i in range(12)]
    seed_model(config, dict.fromkeys(names, 1))

    grid = window_factory(config).slot_grid

    assert grid.cards[1].names_label.text() == ", ".join(names)
    assert grid.cards[1].names_label.wordWrap()
    assert grid.cards[1].sizeHint().height() > grid.cards[2].sizeHint().height()


def test_cards_advertise_that_they_are_editable(window) -> None:
    assert window.slot_grid.cards[1].edit_hint.text() == "✎ Click to edit"
    assert not window.slot_grid.cards[1].edit_hint.isHidden()
    assert window.slot_grid.cards[0].edit_hint.isHidden()  # the catch-all isn't
    assert "QFrame#slotCard:hover" in window.styleSheet()


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


def test_master_counter_tallies_only_sorted_cases(window) -> None:
    for result in (
        {"ok": True, "slot": 2},
        {"ok": True, "slot": 0},
        {"ok": False, "slot": 3, "error": "Sort timeout"},
    ):
        window.bus.post("run/result", result)
    window.bus.drain()

    assert window.master_count_label.text() == "2"


def test_counts_survive_a_stop_start(window) -> None:
    # Tk parity (JL): operators stop to clear a jam and restart mid-tray;
    # only the explicit resets clear the counters.
    window.bus.post("run/result", {"ok": True, "slot": 2})
    window.bus.drain()

    window.bus.post("run/stopped", None)
    window.bus.post("run/started", None)
    window.bus.drain()

    assert window.slot_grid.cards[2].count_label.text() == "1"
    assert window.master_count_label.text() == "1"


def test_reset_counts_clears_the_cards_and_the_batches(window, connected) -> None:
    window.bus.post("run/result", {"ok": True, "slot": 2})
    window.bus.drain()

    window.reset_counts()

    assert window.slot_grid.cards[2].count_label.text() == "0"
    assert window.master_count_label.text() == "0"
    assert connected.package_resets == ["all"]


# ----- package mode ----------------------------------------------------------


def test_package_cards_show_the_batch_target(window, config) -> None:
    config.set_run_package_size(25)

    window.package_check.setChecked(True)

    assert window.slot_grid.cards[1].package_label.text() == "/ 25"
    # The catch-all is never batched.
    assert window.slot_grid.cards[0].package_label.isHidden()


def test_a_full_batch_rings_and_reports(window, monkeypatch) -> None:
    beeps = []
    monkeypatch.setattr(window, "beep", lambda: beeps.append(True))

    window.bus.post("run/package_full", {"slot": 3, "label": "9mm FC", "count": 50})
    window.bus.drain()

    assert beeps == [True]
    assert window.statusBar().currentMessage() == "Slot 3 batch full (50). Reset it to refill."


def test_a_halted_run_says_how_to_resume(qapp, window, monkeypatch) -> None:
    monkeypatch.setattr(window, "beep", lambda: None)
    notices = []
    window.notify = lambda title, text: notices.append((title, text))

    window.bus.post("run/package_halt", {"label": "9mm FC"})
    window.bus.drain()
    qapp.processEvents()  # the dialog is queued out of the drain, Tk-parity

    message = window.statusBar().currentMessage()
    assert "9mm FC" in message
    assert "reset their counters" in message
    assert notices and notices[0][0] == "Package complete"


def test_a_cards_reset_button_empties_just_that_bin(window, connected, config) -> None:
    window.package_check.setChecked(True)
    for slot in (1, 2):
        window.bus.post("run/result", {"ok": True, "slot": slot})
    window.bus.drain()

    window.slot_grid.cards[1].reset_button.click()

    assert window.slot_grid.cards[1].count_label.text() == "0"
    assert window.slot_grid.cards[2].count_label.text() == "1"
    assert connected.package_resets == [1]


# ----- cropped headstamp -----------------------------------------------------


def test_the_last_crop_is_shown_beside_the_preview(window) -> None:
    assert window.crop_label.pixmap().isNull()

    window.bus.post("run/history", history("9mm FC", 99.0))
    window.bus.drain()

    pixmap = window.crop_label.pixmap()
    assert not pixmap.isNull()
    assert max(pixmap.width(), pixmap.height()) == window.crop_label.width()


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


def test_start_routes_a_local_model_without_torch_through_the_gate(window, connected, monkeypatch) -> None:
    # The install gate replaced the launch-the-Tk-UI notice (#7).
    gate_calls = []
    monkeypatch.setattr(window, "ensure_torch", lambda proceed, **kw: gate_calls.append(kw.get("reason")) and False)
    monkeypatch.setattr(classifier, "checkpoint_problem", lambda _db: None)
    monkeypatch.setattr(classifier, "uses_local_inference", lambda _db: True)

    window.start_run()

    assert gate_calls == ["Sorting needs PyTorch"]
    assert connected.started == 0

    # Gate satisfied (torch present) → the run starts.
    monkeypatch.setattr(window, "ensure_torch", lambda proceed, **kw: True)
    window.start_run()
    assert connected.started == 1


def test_start_refuses_ai_config_mode_without_credentials(window, connected, config, monkeypatch) -> None:
    notices = []
    monkeypatch.setattr(window, "notify", lambda title, text: notices.append(title))
    config.api["api_key"] = ""

    window.start_run()

    assert notices == ["AI not configured"]
    assert connected.started == 0


def test_a_local_model_does_not_need_ai_credentials(window, connected, config, monkeypatch) -> None:
    # The HTTP client is never reached, so an unset key is no reason to refuse.
    monkeypatch.setattr(window, "notify", lambda title, text: pytest.fail(title))
    monkeypatch.setattr(classifier, "uses_local_inference", lambda _db: True)
    monkeypatch.setattr(classifier, "checkpoint_problem", lambda _db: None)
    monkeypatch.setattr(local_inference, "is_installed", lambda: True)
    config.api["model"] = ""

    window.start_run()

    assert connected.started == 1


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
    assert window.run_button.isEnabled()
    assert window.run_button.text() == "Start"
    assert window.action_buttons["Manual feed"].isEnabled()


def test_run_events_own_the_button_state(window, connected) -> None:
    window.bus.post("run/started", None)
    window.bus.drain()

    # One button, both faces: the run's own events flip the label and the
    # palette role, never the click handler.
    assert window.run_button.text() == "Stop"
    assert window.run_button.objectName() == "danger"
    assert window.run_button.isEnabled()
    assert not window.action_buttons["Manual feed"].isEnabled()

    window.bus.post("run/stopped", None)
    window.bus.drain()

    assert window.run_button.text() == "Start"
    assert window.run_button.objectName() == "action"
    assert window.run_button.isEnabled()
    assert window.action_buttons["Manual feed"].isEnabled()


def test_the_toggle_starts_and_then_stops_the_run(window, connected) -> None:
    window.run_button.click()

    assert connected.started == 1

    # The controller's event is what puts the Stop face up; clicking it then
    # stops rather than starting a second run.
    window.bus.post("run/started", None)
    window.bus.drain()
    window.run_button.click()

    assert connected.stopped == 1
    assert connected.started == 1


def test_the_toggle_is_the_same_button_under_both_keys(window) -> None:
    assert window.action_buttons["Start/Stop"] is window.run_button


def test_run_error_reaches_the_status_bar(window) -> None:
    window.bus.post("run/error", "Sort timeout")
    window.bus.drain()

    assert window.statusBar().currentMessage() == "Run error: Sort timeout"


# ----- the active model owns the sidebar -------------------------------------


def mode_changed(window) -> None:
    window.bus.post("mode/changed", None)
    window.bus.drain()


def test_train_is_hidden_in_ai_config_mode(window) -> None:
    assert window.sidebar_buttons["Train"].isHidden()


def test_community_follows_auth_state(window) -> None:
    # Signed out (the fixture never constructs an AuthManager): hidden, and
    # the status-bar button offers sign-in.
    assert window.sidebar_buttons["Community"].isHidden()
    assert window.signin_button.text() == "Sign in"

    window.community_page.is_signed_in = lambda: True
    window._apply_auth_visibility()

    assert not window.sidebar_buttons["Community"].isHidden()
    assert window.signin_button.text() == "Sign out"


def test_identity_label_shows_the_display_name_next_to_sign_out(window) -> None:
    # The Community page used to carry its own "Signed in as ... [Sign out]"
    # row; identity now lives only in the status bar (JL live-testing).
    window.auth = types.SimpleNamespace(identity=lambda: ("Ada Lovelace", "ada@example.com"))
    window.community_page.is_signed_in = lambda: True

    window._apply_auth_visibility()

    assert not window.identity_label.isHidden()
    assert window.identity_label.text() == "Ada Lovelace"
    assert window.identity_label.toolTip() == "ada@example.com"


def test_identity_label_falls_back_to_email_with_no_name_claim(window) -> None:
    window.auth = types.SimpleNamespace(identity=lambda: (None, "ada@example.com"))
    window.community_page.is_signed_in = lambda: True

    window._apply_auth_visibility()

    assert window.identity_label.text() == "ada@example.com"


def test_identity_label_is_hidden_when_signed_out(window) -> None:
    window.auth = types.SimpleNamespace(identity=lambda: ("Ada Lovelace", "ada@example.com"))
    window.community_page.is_signed_in = lambda: False

    window._apply_auth_visibility()

    assert window.identity_label.isHidden()
    assert window.identity_label.text() == ""


def test_train_appears_for_a_model_this_user_owns(window, config) -> None:
    seed_model(config, {"9mm FC": 1})

    mode_changed(window)

    assert not window.sidebar_buttons["Train"].isHidden()


def test_train_stays_hidden_for_a_community_model(window, config) -> None:
    from sorter.data.repository import ModelRepo

    repo = ModelRepo(config.db)
    model = repo.get(seed_model(config, {"9mm FC": 1}))
    assert model is not None
    model.model_type = "CommunityManaged"
    repo.update(model)

    mode_changed(window)

    assert window.sidebar_buttons["Train"].isHidden()


def test_hiding_the_current_activity_falls_back_to_sort(window, config) -> None:
    seed_model(config, {"9mm FC": 1})
    mode_changed(window)
    window.sidebar_buttons["Train"].click()

    from sorter.data.repository import SettingsRepo

    SettingsRepo(config.db).clear_active_model()
    mode_changed(window)

    assert window.pages.currentWidget() is window._pages_by_name["Sort"]
    assert window.sidebar_buttons["Sort"].isChecked()


def test_a_model_switch_re_reads_the_slots_and_templates(window, config) -> None:
    window.bus.post("run/result", {"ok": True, "slot": 1})
    window.bus.drain()
    seed_model(config, {"9mm FC": 1})

    mode_changed(window)

    assert window.slot_grid.cards[1].names_label.text() == "9mm FC"
    assert window.slot_grid.cards[1].count_label.text() == "0"
    assert window.template_combo.currentText() == "Default"


# ----- Settings → Serial -----------------------------------------------------


# Port-combo ordering (Emulated first, USB before /dev/ttyS*) is pinned in
# test_qt_settings_serial.py, where the combo lives now.


def test_connecting_the_emulator_wires_the_run_controller(window, config) -> None:
    from sorter.data.config import Config

    window.connect_serial(EMULATED_PORT)

    assert isinstance(window.broker, EmulatorBroker)
    assert isinstance(window.run_controller, RunController)
    assert window.run_controller.broker is window.broker
    assert "connected" in window.serial_label.text()
    assert window.run_button.isEnabled()
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
    window.connect_serial(EMULATED_PORT)

    window.action_buttons["Manual feed"].click()

    assert drain_until(window, lambda: window.slot_grid.cards[2].count_label.text() == "1")
    assert "9mm FC" in window.feed_label.text()
    # The dock saw the exchange: the wheel command out, the board's ack back.
    log = window.serial_monitor.output.toPlainText()
    assert "-> xf:0" in log
    assert "<- done" in log


# ----- run options (Tk reference: tab_run.py's run_opts frame) ---------------


def test_run_options_reflect_the_config_defaults(window, config) -> None:
    assert window.floor_spin.value() == config.run_confidence_floor
    assert window.store_images_combo.currentText() == "None"
    assert window.auto_select_check.isChecked() == config.run_auto_select_trays


def test_confidence_floor_control_persists_and_colors_the_feed(window, config) -> None:
    window.floor_spin.setValue(80)

    assert config.run_confidence_floor == 80

    window.bus.post("run/history", history("9mm", 92.0))
    window.bus.post("run/history", history("unknown", 41.0))
    window.bus.drain()

    text = window.feed_label.text()
    assert f'<span style="color: {window.palette_colors["success"]};">92%' in text
    assert f'<span style="color: {window.palette_colors["warning"]};">41%' in text


def test_store_images_control_persists_and_warns_once_per_session(window, config) -> None:
    notices = []
    window.notify = lambda title, text: notices.append(title)

    window.store_images_combo.setCurrentText("Above Confidence Floor")
    assert config.run_store_images == "above"
    assert notices == ["Store images enabled"]

    window.store_images_combo.setCurrentText("All Images")
    assert config.run_store_images == "all"
    assert notices == ["Store images enabled"]  # not a second time

    window.store_images_combo.setCurrentText("None")
    assert config.run_store_images == "none"


def test_auto_select_control_persists(window, config) -> None:
    window.auto_select_check.setChecked(True)
    assert config.run_auto_select_trays is True

    window.auto_select_check.setChecked(False)
    assert config.run_auto_select_trays is False


# ----- the action row --------------------------------------------------------


def action_row(window):
    """The one row the run controls and the template picker share."""
    column = window._pages_by_name["Sort"].layout()
    for index in range(column.count()):
        row = column.itemAt(index).layout()
        if row is not None and any(row.itemAt(i).widget() is window.run_button for i in range(row.count())):
            return row
    raise AssertionError("the run button is not on any row of the Sort page")


def row_widgets(row) -> list:
    return [row.itemAt(i).widget() for i in range(row.count())]


def test_the_run_controls_and_the_template_picker_share_one_row(window) -> None:
    row = action_row(window)
    widgets = row_widgets(row)

    for widget in (
        window.action_buttons["Manual feed"],
        window.run_options_button,
        window.template_combo,
        window.template_new_button,
        window.template_edit_button,
    ):
        assert widget in widgets

    # And it is the only row above the splitter — the standalone template bar
    # is gone, not merely emptied.
    column = window._pages_by_name["Sort"].layout()
    assert sum(1 for i in range(column.count()) if column.itemAt(i).layout() is not None) == 1


def test_the_template_edits_are_compact_and_explain_themselves(window) -> None:
    assert window.template_new_button.toolTip() == "New template…"
    assert window.template_edit_button.toolTip() == "Edit template…"
    assert window.template_combo.maximumWidth() <= 240


# ----- a camera that isn't there ---------------------------------------------


def test_the_preview_says_where_to_fix_a_dead_camera(window) -> None:
    window._set_camera_indicator("Camera: failed to start", connected=False)

    text = window.preview_label.text()
    assert "No camera feed" in text
    assert "open Camera settings" in text

    window.preview_label.linkActivated.emit("#camera")

    assert window.pages.currentWidget() is window._pages_by_name["Settings"]
    assert window.settings_list.currentItem().text() == "Camera"


def test_a_failed_camera_start_reaches_the_status_bar(window) -> None:
    window.camera = types.SimpleNamespace(
        start_preview=lambda: False,
        latest_frame=lambda: None,
        stop=lambda: None,
        width=640,
        height=480,
    )

    window.start_camera()
    window.bus.drain()

    assert "Settings" in window.statusBar().currentMessage()
    assert "Camera" in window.statusBar().currentMessage()
    assert window._camera_state[1] is False
