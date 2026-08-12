"""Chrome parity (increment 14): About/License, empty states, window/session
persistence, and the dock float/re-dock recovery hooks.

Everything here runs offscreen, no real modals (dialogs are constructed and
inspected directly — never ``.exec()``'d) and against a real SQLite-backed
``Config``, same conventions as test_qt_app.py / test_qt_sort.py.
"""

from __future__ import annotations

import os
import sys
import types

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("tkinter")  # sorter.ui.theme (the palettes) imports it

from PySide6.QtCore import Qt

from sorter.hardware.serial_emulator import EMULATED_PORT
from sorter.qtui.app import default_qpa_platform

from .conftest import seed_model

# ----- QT_QPA_PLATFORM default (no QApplication needed) -----------------------


def test_linux_defaults_to_xcb_with_a_wayland_fallback(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)

    default_qpa_platform()

    assert os.environ.get("QT_QPA_PLATFORM") == "xcb;wayland"


def test_an_explicit_choice_always_wins(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("QT_QPA_PLATFORM", "wayland")

    default_qpa_platform()

    assert os.environ.get("QT_QPA_PLATFORM") == "wayland"


def test_non_linux_platforms_are_left_alone(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)

    default_qpa_platform()

    assert os.environ.get("QT_QPA_PLATFORM") is None


# ----- About ------------------------------------------------------------------


def test_about_dialog_shows_identity_and_gpl_notice(window) -> None:
    from sorter import __version__
    from sorter.qtui.dialog_about import GPL_NOTICE, AboutDialog

    dialog = AboutDialog(window)

    labels_text = " ".join(child.text() for child in dialog.findChildren(type(dialog.version_label)) if child.text())
    assert "AI Case Sorter OSS" in labels_text
    assert __version__ in dialog.version_label.text()
    assert GPL_NOTICE.split("\n\n")[0] in labels_text


def test_about_dialog_has_no_firmware_line_without_a_broker(window) -> None:
    from sorter.qtui.dialog_about import AboutDialog

    dialog = AboutDialog(window)

    assert dialog.firmware_label is None


def test_about_dialog_shows_firmware_version_when_a_broker_is_live(window) -> None:
    from sorter.qtui.dialog_about import AboutDialog

    window.broker = types.SimpleNamespace(firmware_version="CS7.2-1.7")

    dialog = AboutDialog(window)

    assert dialog.firmware_label is not None
    assert "CS7.2-1.7" in dialog.firmware_label.text()


def test_about_dialog_links_cover_repo_firmware_issues_and_shop(window) -> None:
    from sorter.qtui.dialog_about import (
        FIRMWARE_REPO_URL,
        ISSUES_URL,
        REPO_URL,
        SHOP_URL,
        AboutDialog,
    )

    dialog = AboutDialog(window)

    html = " ".join(
        child.text() for child in dialog.findChildren(type(dialog.version_label)) if "href=" in child.text()
    )
    for url in (REPO_URL, FIRMWARE_REPO_URL, ISSUES_URL, SHOP_URL):
        assert url in html


def test_help_menu_opens_about_and_license(window) -> None:
    calls = []
    window._show_about = lambda: calls.append("about")
    window._show_license = lambda: calls.append("license")

    actions = {a.text(): a for a in window.menus["Help"].actions() if a.text()}
    actions["About"].trigger()
    actions["License"].trigger()

    assert calls == ["about", "license"]


# ----- License ------------------------------------------------------------


def test_license_dialog_loads_the_real_license(window) -> None:
    from sorter.qtui.dialog_about import LicenseDialog

    dialog = LicenseDialog(window)

    assert "GNU GENERAL PUBLIC LICENSE" in dialog.text_view.toPlainText()


def test_license_dialog_handles_a_missing_license_file(window, monkeypatch, tmp_path) -> None:
    import sorter.qtui.dialog_about as dialog_about

    monkeypatch.setattr(dialog_about, "app_root", lambda: tmp_path)

    dialog = dialog_about.LicenseDialog(window)

    assert "not found" in dialog.text_view.toPlainText()
    assert "GPL" in dialog.text_view.toPlainText() or "gpl" in dialog.text_view.toPlainText().lower()


# ----- Empty state ----------------------------------------------------------


def test_fresh_window_shows_the_empty_state(window) -> None:
    # No board, no camera, and the seeded default model has no headstamps.
    assert window.sort_stack.currentIndex() == 1


def test_empty_state_clears_once_serial_connects(window) -> None:
    window.connect_serial(EMULATED_PORT)

    assert window.sort_stack.currentIndex() == 0


def test_empty_state_clears_once_the_camera_connects(window) -> None:
    window._set_camera_indicator("Camera: connected (640x480)", connected=True)

    assert window.sort_stack.currentIndex() == 0


def test_empty_state_clears_once_something_is_assigned_even_disconnected(window, config) -> None:
    assert window.sort_stack.currentIndex() == 1

    seed_model(config, {"9mm FC": 1})
    window.bus.post("mode/changed", None)
    window.bus.drain()

    assert window.sort_stack.currentIndex() == 0


def test_empty_state_panel_links_to_settings_serial_and_camera(window) -> None:
    window.empty_state_board_button.click()
    assert window.settings_list.currentItem().text() == "Serial"
    assert window.pages.currentWidget() is window._pages_by_name["Settings"]

    window.sidebar_buttons["Sort"].click()
    window.empty_state_camera_button.click()
    assert window.settings_list.currentItem().text() == "Camera"


# ----- window/session polish --------------------------------------------------


def test_minimum_size_matches_the_tk_reference(window) -> None:
    assert (window.minimumWidth(), window.minimumHeight()) == (960, 660)


def test_close_does_not_prompt_during_a_run(window) -> None:
    # Tk parity (ui/app.py's _on_close): no confirmation, ever — see the
    # judgment-call register / this increment's report. A stand-in
    # controller is enough; nothing here needs a real board.
    window.run_controller = types.SimpleNamespace(stop=lambda: None)
    window.bus.post("run/started", None)
    window.bus.drain()

    calls = []
    window.notify = lambda *a, **k: calls.append(a)

    window.close()

    assert calls == []


# ----- window/session persistence ---------------------------------------------


def test_window_state_and_model_columns_persist_across_a_rebuild(window_factory, config, qapp) -> None:
    # isVisible() only reflects reality once the top-level is actually shown.
    first = window_factory(config)
    first.show()
    qapp.processEvents()
    first.models_page.tree.header().resizeSection(0, 321)
    first.history_dock.setVisible(True)
    qapp.processEvents()

    first.close()  # closeEvent saves ui.window_state + ui.models_columns
    qapp.processEvents()

    second = window_factory(config)
    second.show()
    qapp.processEvents()

    assert second.models_page.tree.header().sectionSize(0) == 321
    assert second.history_dock.isVisible()


def test_restore_ignores_a_malformed_setting(window_factory, config) -> None:
    from sorter.data.repository import SettingsRepo
    from sorter.qtui.app import SETTING_MODELS_COLUMNS, SETTING_WINDOW_STATE

    SettingsRepo(config.db).set(SETTING_WINDOW_STATE, "not valid base64!!")
    SettingsRepo(config.db).set(SETTING_MODELS_COLUMNS, 12345)  # wrong type entirely

    # Must not raise.
    window_factory(config)


# ----- dock float / re-dock recovery -------------------------------------------


@pytest.mark.parametrize("dock_name", ["serial_dock", "history_dock"])
def test_dock_top_level_change_schedules_a_recompute(window, qapp, dock_name: str) -> None:
    calls = []
    window._repaint_after_dock_transition = lambda: calls.append("x")
    dock = getattr(window, dock_name)

    dock.topLevelChanged.emit(True)
    qapp.processEvents()  # flush the QTimer.singleShot(0, ...)

    assert calls == ["x"]


@pytest.mark.parametrize("dock_name", ["serial_dock", "history_dock"])
def test_dock_location_change_schedules_a_recompute(window, qapp, dock_name: str) -> None:
    calls = []
    window._repaint_after_dock_transition = lambda: calls.append("x")
    dock = getattr(window, dock_name)

    dock.dockLocationChanged.emit(Qt.DockWidgetArea.LeftDockWidgetArea)
    qapp.processEvents()  # flush the QTimer.singleShot(0, ...)

    assert calls == ["x"]


@pytest.mark.parametrize("dock_name", ["serial_dock", "history_dock"])
def test_dock_visibility_change_schedules_a_collapse_check(window, qapp, dock_name: str) -> None:
    # Lighter than topLevelChanged/dockLocationChanged's handler on purpose:
    # visibilityChanged fires on ordinary show/hide (a window's own
    # construction included), so it must never carry the resize-nudge
    # fallback — see _watch_dock_transitions's docstring, point 3.
    calls = []
    window._restore_collapsed_docks = lambda: calls.append("x")
    dock = getattr(window, dock_name)

    dock.visibilityChanged.emit(True)
    qapp.processEvents()  # flush the QTimer.singleShot(0, ...)

    assert calls == ["x"]


def test_dock_transition_recompute_invalidates_the_layout(window, qapp) -> None:
    window.show()
    qapp.processEvents()
    layout = window.layout()
    calls = []
    original_invalidate = layout.invalidate

    def spy_invalidate() -> None:
        calls.append("invalidate")
        original_invalidate()

    layout.invalidate = spy_invalidate

    window._repaint_after_dock_transition()

    assert calls == ["invalidate"]


def test_dock_transition_nudge_restores_the_original_size(window, qapp) -> None:
    window.show()
    qapp.processEvents()
    original_size = window.size()

    window._repaint_after_dock_transition()
    qapp.processEvents()  # flush the queued restore

    assert window.size() == original_size


def test_collapsed_serial_dock_is_pushed_back_to_a_usable_height(window, qapp) -> None:
    from sorter.qtui.app import DOCK_RESTORED_SIZE_PX

    window.show()
    qapp.processEvents()
    calls = []
    window.resizeDocks = lambda docks, sizes, orientation: calls.append((docks, sizes, orientation))
    # The offscreen platform doesn't honor resizeDocks/resize() on a
    # QMainWindowLayout-managed dock (confirmed manually — geometry snaps
    # back on the next layout pass), so the collapse itself is simulated by
    # overriding height() rather than actually shrinking the dock; what's
    # asserted is that the restore logic fires with the right args. The
    # actual on-screen recovery is what JL verifies on real hardware.
    window.serial_dock.height = lambda: 10

    window._restore_collapsed_docks()

    assert calls == [([window.serial_dock], [DOCK_RESTORED_SIZE_PX], Qt.Orientation.Vertical)]


def test_collapsed_history_dock_is_pushed_back_to_a_usable_width(window, qapp) -> None:
    from sorter.qtui.app import DOCK_RESTORED_SIZE_PX

    window.show()
    window.history_dock.setVisible(True)
    qapp.processEvents()
    calls = []
    window.resizeDocks = lambda docks, sizes, orientation: calls.append((docks, sizes, orientation))
    window.history_dock.width = lambda: 10

    window._restore_collapsed_docks()

    assert calls == [([window.history_dock], [DOCK_RESTORED_SIZE_PX], Qt.Orientation.Horizontal)]


def test_a_dock_at_a_healthy_size_is_left_alone(window, qapp) -> None:
    window.show()
    qapp.processEvents()
    calls = []
    window.resizeDocks = lambda docks, sizes, orientation: calls.append((docks, sizes, orientation))

    window._restore_collapsed_docks()

    assert calls == []


def test_a_floating_dock_is_never_resized_by_the_restore(window, qapp) -> None:
    window.show()
    qapp.processEvents()
    window.serial_dock.setFloating(True)
    qapp.processEvents()
    calls = []
    window.resizeDocks = lambda docks, sizes, orientation: calls.append((docks, sizes, orientation))
    window.serial_dock.height = lambda: 10  # would trip the floor if docked

    window._restore_collapsed_docks()

    assert calls == []


def test_docks_stay_closable_movable_and_floatable(window) -> None:
    from PySide6.QtWidgets import QDockWidget

    expected = (
        QDockWidget.DockWidgetFeature.DockWidgetClosable
        | QDockWidget.DockWidgetFeature.DockWidgetMovable
        | QDockWidget.DockWidgetFeature.DockWidgetFloatable
    )
    assert window.serial_dock.features() == expected
    assert window.history_dock.features() == expected
