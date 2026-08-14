"""The Models activity and its editor dialog, offscreen.

Everything runs against the real SQLite-backed ``Config`` from the shared qtui
conftest, with ``CASESORTER_DATA_DIR`` pointed at ``tmp_path`` — the page reads
image counts off disk and deletes a model's directory, so an unset data root
would have the tests rummaging in the developer's own library.

The dialog hooks (``confirm``, ``ask_open_path``, ``ask_save_path``,
``ask_text``, ``ask_import_choice``) are replaced everywhere; nothing modal
opens. The export/import tests are end-to-end on purpose: a real ZIP written to
``tmp_path`` and read back through ``model_io``, no IO layer mocked.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QHeaderView

from sorter import paths
from sorter.data.config import Config
from sorter.data.models import Model
from sorter.data.repository import CartridgeRepo, HeadstampRepo, ModelRepo, SettingsRepo
from sorter.qtui.dialog_model_editor import ModelEditorDialog
from sorter.qtui.models_page import (
    ACTION_BUTTON_HEIGHT,
    ACTION_BUTTON_WIDTH,
    ACTIONS_COLUMN,
    ACTIVE_MARK,
    AI_CONFIG_HINT,
    AI_CONFIG_NAME,
    AI_CONFIG_SENTINEL_ID,
    COLUMNS,
    FILTER_TYPE_COMMUNITY,
    FOREIGN_NOTICE,
    SELECT_HINT,
    TOOLTIP_ACTIVATE,
    TOOLTIP_ACTIVATE_AI,
    TOOLTIP_ACTIVE,
    TOOLTIP_ACTIVE_AI,
    TOOLTIP_DELETE,
    TOOLTIP_DELETE_ACTIVE,
    TOOLTIP_EDIT,
    ZIP_FILTER,
)

from .conftest import drain_until, seed_model

# Every column but the one holding the row's buttons, which carries no value.
DATA_COLUMNS = COLUMNS[:ACTIONS_COLUMN]


@pytest.fixture(autouse=True)
def _data_root(tmp_path: Path, monkeypatch) -> None:
    """Keep every path this page touches inside the test's tmp dir.

    Autouse so it lands before the ``config``/``window`` fixtures build
    anything; the assertion is the proof that it did — the page deletes model
    directories, and this suite must never reach the developer's own library.
    """
    monkeypatch.setenv("CASESORTER_DATA_DIR", str(tmp_path / "data"))
    assert paths.app_data_dir() == tmp_path / "data"


class _Recorder:
    """Stand-in for ``win.notify`` — a modal would hang the offscreen run."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def __call__(self, title: str, text: str) -> None:
        self.calls.append((title, text))

    @property
    def titles(self) -> list[str]:
        return [title for title, _text in self.calls]


@pytest.fixture
def page(window):
    win_page = window.models_page
    window.notify = _Recorder()
    win_page.confirm = lambda _title, _text: True
    win_page.ask_text = lambda _title, _label: pytest.fail("unexpected text prompt")
    win_page.ask_open_path = lambda _title: pytest.fail("unexpected open dialog")
    win_page.ask_save_path = lambda _title, _name: pytest.fail("unexpected save dialog")
    win_page.ask_import_choice = lambda _name: pytest.fail("unexpected import prompt")
    return win_page


# ----- helpers ---------------------------------------------------------------


def cell(page: Any, row: int, column: str) -> str:
    return page.tree.topLevelItem(row).text(COLUMNS.index(column))


def names(page: Any) -> list[str]:
    return [cell(page, row, "Model") for row in range(page.tree.topLevelItemCount())]


def active_names(page: Any) -> list[str]:
    return [
        cell(page, row, "Model")
        for row in range(page.tree.topLevelItemCount())
        if cell(page, row, "Active") == ACTIVE_MARK
    ]


def select_row(page: Any, index: int) -> None:
    item = page.tree.topLevelItem(index)
    assert item is not None, f"no row {index}"
    page.tree.setCurrentItem(item)


def select(page: Any, model_id: int) -> None:
    select_row(page, next(i for i, (row_id, _model) in enumerate(page._rows) if row_id == model_id))


def select_name(page: Any, name: str) -> None:
    select_row(page, names(page).index(name))


def row_actions(page: Any, model_id: int) -> Any:
    """A row's live action buttons — looked up fresh, never held across a sort."""
    widget = page.row_actions(model_id)
    assert widget is not None, f"no action buttons on row {model_id}"
    return widget


def make_model(config: Any, name: str, **fields: Any) -> Model:
    fields.setdefault("cartridge_id", CartridgeRepo(config.db).list()[0].id)
    return ModelRepo(config.db).create(Model(name=name, **fields))


def get_model(config: Any, model_id: int | None) -> Model:
    """The row as it is on disk now — never the page's or the test's copy."""
    assert model_id is not None
    model = ModelRepo(config.db).get(model_id)
    assert model is not None
    return model


def fresh_active_id(config: Any) -> int | None:
    """The active model as a *second* reader sees it — never the page's copy."""
    return SettingsRepo(Config(config.db).load().db).get_active_model_id()


# ----- the library table -----------------------------------------------------


def test_list_shows_the_ai_row_and_the_seeded_model(page, config) -> None:
    # A fresh DB seeds one cartridge + one model and starts in AI Config mode.
    seeded = ModelRepo(config.db).list()[0]

    assert names(page) == [AI_CONFIG_NAME, seeded.name]
    assert active_names(page) == [AI_CONFIG_NAME]


def test_rows_carry_the_facts_the_tk_cards_showed(page, config) -> None:
    model = make_model(config, "Range brass", model_mode="convnext_small")
    page.refresh()

    cartridge = CartridgeRepo(config.db).get(model.cartridge_id)
    assert cartridge is not None
    row = names(page).index("Range brass")
    assert cell(page, row, "Cartridge") == cartridge.name
    assert cell(page, row, "Type") == "Standard"
    assert cell(page, row, "Mode") == "convnext_small"
    assert cell(page, row, "Images") == "0"
    assert cell(page, row, "Trained") == "no"


def test_last_trained_renders_in_the_os_regional_format(page, config, monkeypatch) -> None:
    from PySide6.QtCore import QLocale

    from sorter.qtui import formatting

    monkeypatch.setattr(formatting, "_locale", lambda: QLocale("sv_SE"))
    make_model(config, "Range brass", last_training_date="2026-08-01 09:30")
    page.refresh()

    row = names(page).index("Range brass")
    # sv_SE's short format is exactly ISO/24h; a US-locale machine would
    # render "8/1/26 9:30 AM" for the same stored value — see
    # test_qt_formatting.py for that side of the contract.
    assert cell(page, row, "Last trained") == "2026-08-01 09:30"


def test_image_count_comes_off_disk(page, config) -> None:
    model = make_model(config, "With images")
    images = paths.model_images_dir(model.id)
    images.mkdir(parents=True, exist_ok=True)
    (images / "9mm FC__1.jpg").write_bytes(b"x")
    (images / "notes.txt").write_bytes(b"x")
    page.refresh()

    assert cell(page, names(page).index("With images"), "Images") == "1"


def test_the_active_model_is_marked(page, config) -> None:
    seed_model(config, {"9mm FC": 1}, name="Active one")
    page.refresh()

    assert active_names(page) == ["Active one"]


def test_search_filters_and_drops_the_ai_row(page, config) -> None:
    make_model(config, "Range brass")
    make_model(config, "Match prep")

    page.search_edit.setText("range")

    assert names(page) == ["Range brass"]


def test_search_for_ai_keeps_the_synthetic_row(page) -> None:
    page.search_edit.setText("ai")

    assert names(page) == [AI_CONFIG_NAME]


def test_type_filter_excludes_the_ai_row(page, config) -> None:
    make_model(config, "Shared one", community_model_uid="uid-1")

    page.type_combo.setCurrentText(FILTER_TYPE_COMMUNITY)

    assert names(page) == ["Shared one"]
    assert cell(page, 0, "Type") == "Community"


def test_cartridge_filter(page, config) -> None:
    other = CartridgeRepo(config.db).create(".223")
    ModelRepo(config.db).create(Model(name="Rifle", cartridge_id=other.id))
    page.refresh()

    page.cartridge_combo.setCurrentText(".223")

    # The AI row isn't a cartridge's model, so only the type filter hides it —
    # same rule as the Tk tab.
    assert names(page) == [AI_CONFIG_NAME, "Rifle"]


def test_zip_filter_label_survives_gnomes_paren_stripping() -> None:
    # GNOME's portal strips the "(*.zip)" Qt-pattern suffix from the label it
    # shows, so the human-readable half must carry its own, un-strippable
    # mention of the extension (JL live-testing).
    assert "*.zip" in ZIP_FILTER.split("(", 1)[0]
    assert ZIP_FILTER.endswith("(*.zip)")


# ----- column sorting ---------------------------------------------------------


def click_header(page: Any, column_name: str, window: Any = None) -> None:
    """A genuine mouse click on the header section, not ``.emit()`` on the
    signal — this is what proves click *delivery* (geometry, clickability)
    actually reaches the handler the way a real user's click does, not just
    that the handler is correct once invoked.

    Offscreen and unshown, a ``QHeaderView``'s section geometry
    (``sectionViewportPosition``) is occasionally stale on the first click
    a particular column receives — a real, shown app never has this
    problem, since painting the header at least once is unavoidable before
    a user can click it at all. Rather than a fragile "click every column
    in some order first" workaround, this verifies the click actually
    landed (against the page's own ``_sort_column``/``_sort_order`` —
    exactly what a click is supposed to change) and retries a bounded
    number of times against real state, so a genuine delivery failure still
    fails the test instead of being silently papered over.
    """
    if window is not None and window.pages.currentWidget() is not page and not window.isVisible():
        window.show()
        window.show_page("Models")
        QTest.qWait(0)
    header = page.tree.header()
    column = COLUMNS.index(column_name)

    def click_column(index: int) -> None:
        x = header.sectionViewportPosition(index) + header.sectionSize(index) // 2
        QTest.mouseClick(
            header.viewport(),
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            QPoint(x, header.height() // 2),
        )

    prev_column, prev_order = page._sort_column, page._sort_order
    if column == prev_column:
        expected_order = (
            Qt.SortOrder.DescendingOrder if prev_order == Qt.SortOrder.AscendingOrder else Qt.SortOrder.AscendingOrder
        )
    else:
        expected_order = Qt.SortOrder.AscendingOrder

    attempts = 6
    for _attempt in range(attempts):
        click_column(column)
        if page._sort_column == column and page._sort_order == expected_order:
            return
        # A neighbor click nudges the header into recomputing section
        # geometry before the retry.
        click_column(column - 1 if column else min(column + 1, len(COLUMNS) - 1))
    raise AssertionError(f"header click on {column_name!r} never registered after {attempts} attempts")


def synthetic_order(page: Any, wanted: tuple[str, ...]) -> list[str]:
    """The relative order of just the given model names among all rows."""
    shown = names(page)
    return [n for n in shown if n in wanted]


def test_images_column_sorts_numerically_not_lexically(page, window, config) -> None:
    # Lexical order would read "10" < "2" < "3"; numeric order must not.
    make_model(config, "Ten", trained_image_count=10)
    make_model(config, "Two", trained_image_count=2)
    make_model(config, "Three", trained_image_count=3)
    page.refresh()

    click_header(page, "Images", window)

    # Row 0 is the pinned AI row (blank Images cell); the rest sort numerically.
    values = [cell(page, row, "Images") for row in range(page.tree.topLevelItemCount())]
    assert values[0] == ""
    assert values[1:] == ["0", "2", "3", "10"]


def test_last_trained_column_sorts_chronologically(page, window, config) -> None:
    # The displayed text is locale-formatted (qtui.formatting), which
    # doesn't sort chronologically in general — the typed sort key must be
    # the raw stored date instead.
    make_model(config, "Newer", last_training_date="2026-08-10 09:00")
    make_model(config, "Older", last_training_date="2025-01-05 09:00")
    page.refresh()

    click_header(page, "Last trained", window)

    order = names(page)
    assert order.index("Older") < order.index("Newer")


def test_the_ai_row_stays_pinned_first_under_every_sort(page, window, config) -> None:
    make_model(config, "Zed model")
    make_model(config, "Alpha model")
    page.refresh()

    for column_name in DATA_COLUMNS:
        click_header(page, column_name, window)
        assert names(page)[0] == AI_CONFIG_NAME, f"AI row wasn't first after sorting by {column_name!r}"
        # Click again to flip to descending, same assertion.
        click_header(page, column_name, window)
        assert names(page)[0] == AI_CONFIG_NAME, f"AI row wasn't first descending-sorted by {column_name!r}"


def test_every_column_sorts_and_toggles_on_a_real_header_click(page, window, config) -> None:
    """EVERY column, via genuine mouse clicks (not signal.emit()): a first
    click sorts ascending, a second click on the same header reverses it.

    Three rows, each column given genuinely distinct values, so a column
    that silently didn't sort (or only "Model" secretly worked, as JL's
    live-testing once suggested) can't hide behind ties or coincidental
    build order.
    """
    # Three distinct cartridges, not just Bravo's — CartridgeRepo.list() (and
    # so make_model's default) orders alphabetically, and "223" sorts before
    # the seeded "9mm", so leaving Alpha/Charlie on the "default" cartridge
    # here would tie them with Bravo instead of splitting from it.
    cart_a = CartridgeRepo(config.db).create("223")
    cart_b = CartridgeRepo(config.db).create("22-250")
    cart_c = CartridgeRepo(config.db).create("6.5 CM")
    make_model(
        config,
        "Bravo",
        cartridge_id=cart_a.id,
        model_mode="convnext_tiny",
        trained_image_count=5,
        last_training_date="2025-06-01 08:00",
    )
    alpha = make_model(
        config,
        "Alpha",
        cartridge_id=cart_b.id,
        community_model_uid="uid-x",
        model_mode="convnext_small",
        trained_image_count=20,
        last_training_date="2026-01-01 08:00",
        model_path="/fake/checkpoint.pth",
    )
    make_model(
        config,
        "Charlie",
        cartridge_id=cart_c.id,
        model_type="ReadOnly",
        model_mode="convnext_base",
        trained_image_count=1,
        last_training_date="2024-01-01 08:00",
    )
    SettingsRepo(config.db).set_active_model_id(alpha.id)
    page.refresh()

    wanted = ("Bravo", "Alpha", "Charlie")
    # Distinct across all three: Model/Cartridge/Type/Mode/Images/Last trained.
    for column_name in ("Model", "Cartridge", "Type", "Mode", "Images", "Last trained"):
        click_header(page, column_name, window)
        ascending = synthetic_order(page, wanted)
        assert len(ascending) == 3, f"{column_name!r}: a synthetic row went missing after sorting"

        click_header(page, column_name, window)
        descending = synthetic_order(page, wanted)
        assert descending == list(reversed(ascending)), (
            f"{column_name!r} didn't reverse on a second (real) click: {ascending} -> {descending}"
        )

    # Active/Trained are inherently binary (only Alpha is active/trained),
    # so a full reversal isn't meaningful — assert the click groups the
    # lone true row to one end, and flips ends on the second click.
    for column_name in ("Active", "Trained"):
        click_header(page, column_name, window)
        first_click = synthetic_order(page, wanted)
        click_header(page, column_name, window)
        second_click = synthetic_order(page, wanted)
        assert "Alpha" in (first_click[0], first_click[-1]), f"{column_name!r} didn't group Alpha to an end"
        assert "Alpha" in (second_click[0], second_click[-1]), f"{column_name!r} didn't group Alpha to an end"
        assert (first_click[0] == "Alpha") != (second_click[0] == "Alpha"), (
            f"{column_name!r} didn't flip ends on the second click"
        )


def test_default_order_is_unchanged_until_a_header_is_clicked(page, config) -> None:
    seeded = ModelRepo(config.db).list()[0].name
    make_model(config, "Zed model")
    make_model(config, "Alpha model")

    page.refresh()

    # Same order `_filtered()` builds (cartridge, then case-insensitive name)
    # — no sort has been requested yet.
    assert names(page) == [AI_CONFIG_NAME, "Alpha model", seeded, "Zed model"]


def test_selection_survives_a_header_click_sort(page, window, config) -> None:
    target = make_model(config, "Zed model")
    make_model(config, "Alpha model")
    page.refresh()
    select(page, target.id)

    click_header(page, "Model", window)

    assert page.selected_id() == target.id


def test_column_resizing_stays_interactive_after_sorting_is_wired(page, window) -> None:
    header = page.tree.header()
    click_header(page, "Model", window)

    for column in range(len(DATA_COLUMNS)):
        assert header.sectionResizeMode(column) == QHeaderView.ResizeMode.Interactive
    # The buttons' column is the one exception: it holds exactly their width.
    assert header.sectionResizeMode(ACTIONS_COLUMN) == QHeaderView.ResizeMode.Fixed


def test_clicking_the_actions_header_sorts_nothing(page, window, config) -> None:
    make_model(config, "Zed model")
    make_model(config, "Alpha model")
    page.refresh()
    before = names(page)

    header = page.tree.header()
    x = header.sectionViewportPosition(ACTIONS_COLUMN) + header.sectionSize(ACTIONS_COLUMN) // 2
    QTest.mouseClick(
        header.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(x, header.height() // 2),
    )

    assert page._sort_column is None
    assert names(page) == before


# ----- activation ------------------------------------------------------------


def test_activate_flips_the_setting_and_posts_mode_changed(page, window, config) -> None:
    model = make_model(config, "Range brass")
    page.refresh()
    posted: list[Any] = []
    window.bus.subscribe("mode/changed", posted.append)
    select(page, model.id)

    page.activate_selected()

    assert fresh_active_id(config) == model.id
    assert drain_until(window, lambda: posted == [{"active_model_id": model.id}])
    assert active_names(page) == ["Range brass"]
    # The window reacts to the same event the Tk tab posts: Train is for a
    # local model this user owns.
    assert not window.sidebar_buttons["Train"].isHidden()


def test_activating_the_ai_row_returns_to_ai_config_mode(page, window, config) -> None:
    seed_model(config, {"9mm FC": 1}, name="Local")
    page.refresh()
    select(page, AI_CONFIG_SENTINEL_ID)

    page.activate_selected()

    assert fresh_active_id(config) is None
    assert active_names(page) == [AI_CONFIG_NAME]
    assert drain_until(window, lambda: window.sidebar_buttons["Train"].isHidden())


def test_activate_is_disabled_for_the_row_that_is_already_active(page, config) -> None:
    model = make_model(config, "Range brass")
    page.refresh()
    select(page, model.id)
    page.activate_selected()

    active = row_actions(page, model.id)
    assert not active.activate_button.isEnabled()
    assert active.activate_button.toolTip() == TOOLTIP_ACTIVE
    # The row that isn't active still offers it — the AI row included.
    ai = row_actions(page, AI_CONFIG_SENTINEL_ID)
    assert ai.activate_button.isEnabled()
    assert ai.activate_button.toolTip() == TOOLTIP_ACTIVATE_AI


def test_the_ai_row_has_no_model_actions(page) -> None:
    select(page, AI_CONFIG_SENTINEL_ID)

    assert not page.buttons["Export…"].isEnabled()


# ----- the row's own action buttons -------------------------------------------


def test_every_model_row_carries_three_fixed_size_buttons(page, config) -> None:
    model = make_model(config, "Range brass")
    page.refresh()

    widget = row_actions(page, model.id)
    assert [b.text() for b in widget.buttons()] == ["✓", "✎", "×"]
    # Fixed in BOTH dimensions: a glyph or state change must not resize a
    # button, its column, or the row under it (community_page.py's finding).
    for button in widget.buttons():
        assert button.size().toTuple() == (ACTION_BUTTON_WIDTH, ACTION_BUTTON_HEIGHT)
        assert button.minimumSize() == button.maximumSize()
    assert [b.toolTip() for b in widget.buttons()] == [TOOLTIP_ACTIVATE, TOOLTIP_EDIT, TOOLTIP_DELETE]
    assert widget.delete_button.objectName() == "danger"


def test_the_ai_row_offers_only_activation(page) -> None:
    widget = row_actions(page, AI_CONFIG_SENTINEL_ID)

    assert [b.text() for b in widget.buttons()] == ["✓"]
    assert widget.edit_button is None and widget.delete_button is None
    # It is the active mode on a fresh DB, so its one button says so.
    assert not widget.activate_button.isEnabled()
    assert widget.activate_button.toolTip() == TOOLTIP_ACTIVE_AI


def test_a_row_button_activates_its_own_row_not_the_selected_one(page, window, config) -> None:
    target = make_model(config, "Range brass")
    other = make_model(config, "Match prep")
    page.refresh()
    select(page, other.id)

    row_actions(page, target.id).activate_button.click()

    assert fresh_active_id(config) == target.id
    assert active_names(page) == ["Range brass"]
    assert drain_until(window, lambda: not window.sidebar_buttons["Train"].isHidden())


def test_the_ai_rows_button_returns_to_ai_config_mode(page, window, config) -> None:
    seed_model(config, {"9mm FC": 1}, name="Local")
    page.refresh()

    row_actions(page, AI_CONFIG_SENTINEL_ID).activate_button.click()

    assert fresh_active_id(config) is None
    assert active_names(page) == [AI_CONFIG_NAME]
    assert drain_until(window, lambda: window.sidebar_buttons["Train"].isHidden())


def test_the_active_rows_delete_button_is_disabled(page, config, window) -> None:
    """Mirrors ``ModelRepo.delete``'s own refusal, which ``_delete`` never
    overrides (it passes no replacement) — so the button can't open a confirm
    that is bound to fail. ``test_delete_refuses_the_active_model`` is the
    other half: the repo really does refuse."""
    model_id = seed_model(config, {"9mm FC": 1}, name="Active one")
    other = make_model(config, "Spare")
    page.refresh()

    active = row_actions(page, model_id)
    assert not active.delete_button.isEnabled()
    assert active.delete_button.toolTip() == TOOLTIP_DELETE_ACTIVE
    # Editing the active model is fine, and every other row deletes normally.
    assert active.edit_button.isEnabled()
    assert row_actions(page, other.id).delete_button.isEnabled()
    assert row_actions(page, other.id).delete_button.toolTip() == TOOLTIP_DELETE
    assert window.notify.calls == []


def test_a_row_delete_goes_through_the_same_confirm_seam(page, window, config) -> None:
    model = make_model(config, "Doomed")
    page.refresh()
    asked: list[tuple[str, str]] = []

    def refuse(title: str, text: str) -> bool:
        asked.append((title, text))
        return False

    page.confirm = refuse
    row_actions(page, model.id).delete_button.click()

    assert [title for title, _text in asked] == ["Confirm delete"]
    assert "Doomed" in asked[0][1]
    assert ModelRepo(config.db).get(model.id) is not None

    page.confirm = lambda _title, _text: True
    row_actions(page, model.id).delete_button.click()

    assert ModelRepo(config.db).get(model.id) is None
    assert "Doomed" not in names(page)
    assert drain_until(window, lambda: not paths.model_dir(model.id).exists())


def test_a_row_edit_button_opens_the_editor_for_its_own_row(page, config, monkeypatch) -> None:
    from sorter.qtui import models_page as module

    opened: list[Model | None] = []

    class StubDialog:
        def __init__(self, _db: Any, existing: Model | None = None, parent: Any = None) -> None:
            opened.append(existing)

        def exec(self) -> int:
            return 0

    monkeypatch.setattr(module, "ModelEditorDialog", StubDialog)
    target = make_model(config, "Range brass")
    other = make_model(config, "Match prep")
    page.refresh()
    select(page, other.id)

    row_actions(page, target.id).edit_button.click()

    assert [m.id for m in opened if m is not None] == [target.id]
    # The clicked row becomes the selection, so the bar below follows it too.
    assert page.selected_id() == target.id


def test_a_row_button_still_targets_its_own_model_after_a_sort(page, window, config) -> None:
    """``_pin_ai_row`` takes a row out of the tree and puts it back, which
    destroys its item widget — the buttons must be re-installed, and still
    bound to the row they sit in, after any header click."""
    zed = make_model(config, "Zed model")
    make_model(config, "Alpha model")
    page.refresh()

    click_header(page, "Model", window)  # ascending: Alpha, seeded, Zed
    click_header(page, "Model", window)  # descending: Zed, seeded, Alpha
    assert names(page)[0] == AI_CONFIG_NAME  # still pinned
    assert names(page)[1] == "Zed model"

    row_actions(page, zed.id).activate_button.click()

    assert fresh_active_id(config) == zed.id
    assert active_names(page) == ["Zed model"]


def test_the_row_buttons_stand_down_while_an_archive_is_in_flight(page, config) -> None:
    model = make_model(config, "Range brass")
    page.refresh()

    page._set_busy(True)
    assert not any(b.isEnabled() for b in row_actions(page, model.id).buttons())

    page._set_busy(False)
    assert all(b.isEnabled() for b in row_actions(page, model.id).buttons())


def test_the_bottom_bar_is_only_the_selection_scoped_actions(page) -> None:
    # Activate/Edit/Delete belong to a row and moved into it; what's left is
    # scoped to the selection. No danger or action role remains down here.
    assert list(page.buttons) == ["Images…", "Headstamps…", "Evaluate…", "Export…"]
    assert [b.objectName() for b in page.buttons.values()] == ["", "", "", ""]


def test_the_actions_column_holds_exactly_its_buttons(page, config) -> None:
    model = make_model(config, "Range brass")
    page._columns_sized = False
    page.refresh()

    widget = row_actions(page, model.id)
    # resizeColumnToContents measures cell text, never item widgets, so the
    # autosize pass must not be what decides this column's width.
    assert page.tree.header().sectionSize(ACTIONS_COLUMN) >= widget.sizeHint().width()
    assert page.tree.header().sectionSize(ACTIONS_COLUMN) >= 3 * ACTION_BUTTON_WIDTH


# ----- ownership -------------------------------------------------------------


def test_a_community_download_is_read_only_and_not_trainable(page, config) -> None:
    model = make_model(config, "Someone else's", model_type="CommunityManaged", community_model_uid="uid-9")
    page.refresh()
    select_name(page, "Someone else's")

    assert cell(page, names(page).index("Someone else's"), "Type") == "Community (read-only)"
    assert page.hint_label.text() == FOREIGN_NOTICE
    assert not page.buttons["Images…"].isEnabled()
    # Everything that isn't about training the model stays available.
    assert page.buttons["Export…"].isEnabled()
    assert all(b.isEnabled() for b in row_actions(page, model.id).buttons())


def test_a_model_you_shared_yourself_stays_yours(page, config) -> None:
    # A UID means "exists in the community", not "isn't yours" (CLAUDE.md §5).
    make_model(config, "Mine", community_model_uid="uid-2")
    page.refresh()
    select_name(page, "Mine")
    page.set_images_hook(lambda _model: None)

    assert cell(page, names(page).index("Mine"), "Type") == "Community"
    assert page.buttons["Images…"].isEnabled()


def test_the_images_button_appears_only_once_a_browser_is_attached(window, config) -> None:
    # The window wires the browser at build, so exercise the module contract
    # on a fresh, unwired page.
    from sorter.qtui.models_page import build_models_page

    page = build_models_page(window)
    opened: list[Any] = []
    make_model(config, "Range brass")
    page.refresh()
    select_name(page, "Range brass")

    assert page.buttons["Images…"].isHidden()

    page.set_images_hook(opened.append)
    page.images_selected()

    assert not page.buttons["Images…"].isHidden()
    assert [m.name for m in opened] == ["Range brass"]


# ----- create / edit ---------------------------------------------------------


def editor(page, existing: Model | None = None) -> tuple[ModelEditorDialog, _Recorder]:
    """The dialog plus the recorder standing in for its ``notify``."""
    dialog = ModelEditorDialog(page.db, existing=existing, parent=page)
    recorder = _Recorder()
    dialog.notify = recorder
    return dialog, recorder


def test_the_editor_creates_a_model(page, config) -> None:
    dialog, notified = editor(page)
    dialog.name_edit.setText("  Range brass  ")
    dialog.mode_combo.setCurrentText("convnext_small")
    dialog.primer_spin.setValue(120)
    dialog.hide_primer_check.setChecked(False)

    dialog.save()
    page.refresh()

    assert notified.calls == []
    saved = get_model(config, dialog.saved_id)
    assert (saved.name, saved.model_mode, saved.primer_mask_size, saved.hide_primer) == (
        "Range brass",
        "convnext_small",
        120,
        False,
    )
    assert saved.training_config.model_name == "convnext_small"
    assert "Range brass" in names(page)


def test_the_editor_edits_in_place(page, config) -> None:
    model = make_model(config, "Old name")
    other = CartridgeRepo(config.db).create(".223")

    dialog, notified = editor(page, model)
    dialog.name_edit.setText("New name")
    dialog.cartridge_combo.setCurrentText(".223")
    dialog.save()
    page.refresh()

    assert notified.calls == []
    saved = get_model(config, model.id)
    assert (saved.name, saved.cartridge_id) == ("New name", other.id)
    assert ModelRepo(config.db).list() and "Old name" not in names(page)


def test_the_editor_refuses_an_empty_name(page, config) -> None:
    before = len(ModelRepo(config.db).list())
    dialog, notified = editor(page)
    dialog.name_edit.setText("   ")

    dialog.save()

    assert dialog.saved_id is None
    assert notified.titles == ["Missing name"]
    assert len(ModelRepo(config.db).list()) == before


def test_the_feedback_box_is_only_built_for_community_models(page, config) -> None:
    plain = make_model(config, "Mine")
    linked = make_model(config, "Downloaded", model_type="CommunityManaged", community_model_uid="uid-3")

    assert not hasattr(editor(page, plain)[0], "fb_enabled_check")
    assert not hasattr(editor(page)[0], "fb_enabled_check")
    assert hasattr(editor(page, linked)[0], "fb_enabled_check")


def test_the_feedback_opt_in_saves_but_the_floor_is_the_publishers(page, config) -> None:
    model = make_model(
        config,
        "Downloaded",
        model_type="CommunityManaged",
        community_model_uid="uid-4",
        feedback_loop_confidence_floor=88,
    )
    dialog, notified = editor(page, model)
    dialog.fb_enabled_check.setChecked(True)
    dialog.fb_mode_combo.setCurrentText("On run complete")

    dialog.save()

    assert notified.calls == []
    saved = get_model(config, model.id)
    assert saved.feedback_loop_enabled
    assert saved.feedback_loop_upload_mode == "OnRunComplete"
    assert saved.feedback_loop_confidence_floor == 88


def test_new_cartridge_refuses_a_duplicate(page, config, window) -> None:
    existing = CartridgeRepo(config.db).list()[0].name
    page.ask_text = lambda _title, _label: existing

    page.new_cartridge()

    assert window.notify.titles == ["Duplicate"]
    assert len(CartridgeRepo(config.db).list()) == 1


def test_new_cartridge_adds_one(page, config) -> None:
    page.ask_text = lambda _title, _label: " .223 "

    page.new_cartridge()

    assert sorted(c.name for c in CartridgeRepo(config.db).list()) == [".223", "9mm"]
    assert ".223" in [page.cartridge_combo.itemText(i) for i in range(page.cartridge_combo.count())]


# ----- delete ----------------------------------------------------------------


def test_delete_refuses_the_last_model_in_a_cartridge(page, config, window) -> None:
    seeded = ModelRepo(config.db).list()[0]
    select(page, seeded.id)

    page.delete_selected()

    assert window.notify.titles == ["Cannot delete"]
    assert ModelRepo(config.db).get(seeded.id) is not None


def test_delete_refuses_the_active_model(page, config, window) -> None:
    model_id = seed_model(config, {"9mm FC": 1}, name="Active one")
    page.refresh()
    select(page, model_id)

    page.delete_selected()

    assert window.notify.titles == ["Cannot delete"]
    assert ModelRepo(config.db).get(model_id) is not None


def test_delete_needs_the_confirmation(page, config) -> None:
    model = make_model(config, "Doomed")
    page.refresh()
    select(page, model.id)
    page.confirm = lambda _title, _text: False

    page.delete_selected()

    assert ModelRepo(config.db).get(model.id) is not None


def test_delete_removes_the_row_and_its_directory(page, window, config) -> None:
    model = make_model(config, "Doomed")
    images = paths.model_images_dir(model.id)
    images.mkdir(parents=True, exist_ok=True)
    (images / "9mm FC__1.jpg").write_bytes(b"x")
    page.refresh()
    select(page, model.id)

    page.delete_selected()

    assert ModelRepo(config.db).get(model.id) is None
    assert "Doomed" not in names(page)
    # The directory goes on a worker, so give it a moment to land.
    assert drain_until(window, lambda: not paths.model_dir(model.id).exists())


# ----- export / import (end to end, real archives) ---------------------------


def seed_exportable(config: Any, name: str, **fields: Any) -> Model:
    """A model with a headstamp, a training image and a checkpoint on disk."""
    model = make_model(config, name, **fields)
    HeadstampRepo(config.db).add(model.id, "9mm FC", 1)
    images = paths.model_images_dir(model.id)
    images.mkdir(parents=True, exist_ok=True)
    (images / "9mm FC__1.jpg").write_bytes(b"jpeg-ish")
    trained = paths.model_trained_dir(model.id)
    trained.mkdir(parents=True, exist_ok=True)
    checkpoint = trained / f"{model.id}.pth"
    checkpoint.write_bytes(b"not-really-a-checkpoint")
    model.model_path = str(checkpoint)
    ModelRepo(config.db).update(model)
    return get_model(config, model.id)


def export_to(page, window, model: Model, dest: Path) -> Path:
    page.refresh()
    select(page, model.id)
    page.ask_save_path = lambda _title, _name: str(dest)
    page.export_selected()
    assert drain_until(window, dest.exists), "export worker never finished"
    return dest


def import_from(page, window, archive: Path, choice: str | None = None) -> None:
    page.ask_open_path = lambda _title: str(archive)
    page.ask_import_choice = lambda _name: choice if choice is not None else pytest.fail("unexpected prompt")
    before = len(window.notify.calls)
    page.import_archive()
    assert drain_until(window, lambda: len(window.notify.calls) > before), "import worker never finished"


def test_export_writes_a_real_archive(page, window, config, tmp_path) -> None:
    import zipfile

    model = seed_exportable(config, "Range brass")

    archive = export_to(page, window, model, tmp_path / "range.zip")

    with zipfile.ZipFile(archive) as zf:
        entries = set(zf.namelist())
    assert "manifest.json" in entries
    assert f"model/{model.id}.pth" in entries
    assert "images/9mm FC__1.jpg" in entries
    assert window.notify.titles == ["Export complete"]


def test_importing_an_installed_community_archive_updates_it_in_place(page, window, config, tmp_path) -> None:
    model = seed_exportable(config, "Shared", community_model_uid="uid-round-trip")
    archive = export_to(page, window, model, tmp_path / "shared.zip")
    # Diverge the installed row from the archive, and rename it the way a user
    # would: the update must refresh the model but keep the local name.
    model.model_version = 99
    model.name = "My copy"
    ModelRepo(config.db).update(model)
    page.refresh()

    import_from(page, window, archive, choice="update")

    installed = [m for m in ModelRepo(config.db).list() if m.community_model_uid == "uid-round-trip"]
    assert [m.id for m in installed] == [model.id], "the archive added a row instead of updating one"
    assert installed[0].model_version == 1, "the installed row wasn't refreshed from the archive"
    assert installed[0].name == "My copy", "the update overwrote the name the user gave it"
    assert names(page).count("My copy") == 1


def test_the_same_archive_can_be_imported_as_a_separate_copy(page, window, config, tmp_path) -> None:
    model = seed_exportable(config, "Shared", community_model_uid="uid-round-trip")
    archive = export_to(page, window, model, tmp_path / "shared.zip")

    import_from(page, window, archive, choice="copy")

    rows = sorted(
        (m for m in ModelRepo(config.db).list() if m.community_model_uid == "uid-round-trip"),
        key=lambda m: m.id,
    )
    assert [m.name for m in rows] == ["Shared", "Shared (2)"]
    # The copy is a model of its own: its own directory, its own checkpoint.
    copy = rows[1]
    assert copy.id != model.id
    assert copy.model_path is not None and Path(copy.model_path).exists()
    assert [h.name for h in HeadstampRepo(config.db).list_for_model(copy.id)] == ["9mm FC"]


def test_declining_the_update_prompt_imports_nothing(page, window, config, tmp_path) -> None:
    model = seed_exportable(config, "Shared", community_model_uid="uid-round-trip")
    archive = export_to(page, window, model, tmp_path / "shared.zip")
    page.ask_open_path = lambda _title: str(archive)
    page.ask_import_choice = lambda _name: "cancel"

    page.import_archive()

    assert [m.name for m in ModelRepo(config.db).list() if m.name.startswith("Shared")] == ["Shared"]


def test_the_security_notice_can_refuse_an_import(page, window, config, tmp_path) -> None:
    model = seed_exportable(config, "Shared")
    archive = export_to(page, window, model, tmp_path / "shared.zip")
    page.ask_open_path = lambda _title: str(archive)
    page.confirm = lambda _title, _text: False

    page.import_archive()

    assert [m.name for m in ModelRepo(config.db).list() if m.name.startswith("Shared")] == ["Shared"]


def test_a_plain_archive_imports_as_a_new_trainable_model(page, window, config, tmp_path) -> None:
    # No community UID: nothing to update, so no prompt — and the import is
    # the user's own model, which must stay trainable.
    model = seed_exportable(config, "Range brass")
    archive = export_to(page, window, model, tmp_path / "range.zip")

    import_from(page, window, archive)

    imported = next(m for m in ModelRepo(config.db).list() if m.name == "Range brass (2)")
    assert imported.id != model.id
    assert imported.model_type == "Standard"


def test_a_broken_archive_reports_instead_of_raising(page, window, tmp_path) -> None:
    broken = tmp_path / "broken.zip"
    broken.write_bytes(b"not a zip at all")
    page.ask_open_path = lambda _title: str(broken)

    page.import_archive()

    assert drain_until(window, lambda: window.notify.titles == ["Import failed"])


def test_restoring_saved_column_widths_keeps_headers_sortable(page, window, config) -> None:
    """Regression (JL live-testing): ``QHeaderView.restoreState`` also restores
    clickable/indicator-shown — and a blob saved by a pre-sorting build
    restores them *off*, which killed header-click sorting in the real app
    while every test (none of which restored saved state) stayed green.
    """
    from PySide6.QtWidgets import QTreeWidget

    legacy = QTreeWidget()
    legacy.setColumnCount(len(COLUMNS))
    legacy.setHeaderLabels(list(COLUMNS))
    assert not legacy.header().sectionsClickable()  # what the old build saved
    blob = bytes(legacy.header().saveState().data())

    assert page.restore_header_state(blob)

    header = page.tree.header()
    assert header.sectionsClickable()
    assert header.isSortIndicatorShown()
    seed_model(config, {"9mm FC": 1}, name="Bravo")
    seed_model(config, {"9mm FC": 1}, name="Alpha")
    page.refresh()
    click_header(page, "Model", window)
    assert names(page)[0] == "Use AI Config"  # pinned row survives the sort
    assert names(page)[1] == "Alpha"


# ----- column sizing ---------------------------------------------------------


def test_typical_values_are_not_elided_at_the_default_widths(page, config) -> None:
    # The two that clipped (JL live-testing): "8/8/26 7:06 P…" and "convnext_…".
    make_model(config, "Range brass", model_mode="convnext_small", last_training_date="2026-12-28 23:59")
    # The window's construction-time refresh already autosized (and latched
    # _columns_sized); reset so this refresh sizes for the new, longer row —
    # the same first-sight sizing a fresh launch gives it.
    page._columns_sized = False
    page.refresh()

    header = page.tree.header()
    for column in ("Mode", "Last trained"):
        index = COLUMNS.index(column)
        # Compare against the view's own computed content width, not raw font
        # advances: the delegate-vs-fontMetrics offset is platform-dependent
        # (a Linux-tuned pixel allowance failed on Windows CI). Section wider
        # than the delegate's need = nothing to elide, and strictly wider
        # proves COLUMN_PADDING was actually applied.
        assert header.sectionSize(index) > page.tree.sizeHintForColumn(index)


def test_the_user_can_still_drag_the_columns(page) -> None:
    assert page.tree.header().sectionResizeMode(0) == QHeaderView.ResizeMode.Interactive


# ----- the AI row explains itself --------------------------------------------


def test_the_ai_row_carries_its_explanation_as_a_tooltip(page) -> None:
    row = page.tree.topLevelItem(names(page).index(AI_CONFIG_NAME))

    assert [row.toolTip(i) for i in range(len(COLUMNS))] == [AI_CONFIG_HINT] * len(COLUMNS)


def test_the_hint_line_is_left_to_what_a_row_cannot_carry(page, config) -> None:
    select(page, AI_CONFIG_SENTINEL_ID)

    assert page.hint_label.text() == SELECT_HINT  # not the AI text, twice over

    make_model(config, "Someone else's", model_type="CommunityManaged")
    page.refresh()
    select_name(page, "Someone else's")

    assert page.hint_label.text() == FOREIGN_NOTICE
