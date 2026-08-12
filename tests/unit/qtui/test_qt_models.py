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
pytest.importorskip("tkinter")  # sorter.ui.theme (the palettes) imports it

from sorter import paths
from sorter.data.config import Config
from sorter.data.models import Model
from sorter.data.repository import CartridgeRepo, HeadstampRepo, ModelRepo, SettingsRepo
from sorter.qtui.dialog_model_editor import ModelEditorDialog
from sorter.qtui.models_page import (
    ACTIVE_MARK,
    AI_CONFIG_NAME,
    AI_CONFIG_SENTINEL_ID,
    COLUMNS,
    FILTER_TYPE_COMMUNITY,
    FOREIGN_NOTICE,
)

from .conftest import drain_until, seed_model


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


def make_model(config: Any, name: str, **fields: Any) -> Model:
    cartridge = CartridgeRepo(config.db).list()[0]
    return ModelRepo(config.db).create(Model(name=name, cartridge_id=cartridge.id, **fields))


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

    assert not page.buttons["Activate"].isEnabled()

    select(page, AI_CONFIG_SENTINEL_ID)
    assert page.buttons["Activate"].isEnabled()


def test_the_ai_row_has_no_model_actions(page) -> None:
    select(page, AI_CONFIG_SENTINEL_ID)

    assert not any(page.buttons[name].isEnabled() for name in ("Edit…", "Export…", "Delete"))


# ----- ownership -------------------------------------------------------------


def test_a_community_download_is_read_only_and_not_trainable(page, config) -> None:
    make_model(config, "Someone else's", model_type="CommunityManaged", community_model_uid="uid-9")
    page.refresh()
    select_name(page, "Someone else's")

    assert cell(page, names(page).index("Someone else's"), "Type") == "Community (read-only)"
    assert page.hint_label.text() == FOREIGN_NOTICE
    assert not page.buttons["Images…"].isEnabled()
    # Everything that isn't about training the model stays available.
    assert all(page.buttons[name].isEnabled() for name in ("Edit…", "Export…", "Delete"))


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
    dialog.fb_mode_combo.setCurrentText("On Run Complete")

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
