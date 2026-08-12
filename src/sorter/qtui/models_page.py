"""Models activity — the model library.

Behavior reference: ``ui/tab_models.py``. Everything it can do is here (browse,
filter, create, edit, activate, delete, import/export ZIP, the synthetic
"Use AI Config" row), routed through the same repos, the same ``model_io``
calls and the same ``mode/changed`` post, so the two UIs agree on what a model
is and who owns it.

Layout is Qt-idiomatic rather than a transcription: one table of models with
an action row that follows the selection, instead of Tk's per-row card
buttons. The columns carry the same facts the cards did.

Three things worth knowing:

* **Ownership** (CLAUDE.md §5) decides what a row may do, and it is *not* the
  same question as "does this exist in the community" — see ``describe_type``.
* **Import can fork.** An archive whose community UID is already installed
  updates that model in place; the user is asked which they want before
  anything is written (Tk offers update-or-cancel; this adds "import as a
  copy", which ``model_io`` has always supported).
* Import and export run on ``run_worker`` — a model archive is a checkpoint
  plus every training image, so neither belongs on the UI thread.

``ask_open_path`` / ``ask_save_path`` / ``ask_text`` / ``ask_import_choice`` /
``confirm`` are instance attributes so tests can drive every action without a
native dialog.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt  # ty: ignore[unresolved-import]
from PySide6.QtWidgets import (  # ty: ignore[unresolved-import]
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import paths
from ..data.model_io import ExportMode, export_model, find_update_target, import_model
from ..data.models import Model, is_foreign_model, is_trainable
from ..data.repository import (
    CartridgeRepo,
    HeadstampRepo,
    ModelRepo,
    SettingsRepo,
)
from .dialog_model_editor import ModelEditorDialog

FILTER_TYPE_ALL = "All"
FILTER_TYPE_STANDARD = "Standard"
FILTER_TYPE_COMMUNITY = "Community"
FILTER_TYPE_READONLY = "Read-only"
TYPE_FILTERS = (FILTER_TYPE_ALL, FILTER_TYPE_STANDARD, FILTER_TYPE_COMMUNITY, FILTER_TYPE_READONLY)

# Sentinel id for the synthetic "Use AI Config" row, far below any rowid.
AI_CONFIG_SENTINEL_ID = -1
AI_CONFIG_NAME = "Use AI Config"
AI_CONFIG_HINT = "Route classification through the AI Config page (HTTP server)."

COLUMNS = ("Model", "Active", "Cartridge", "Type", "Mode", "Images", "Trained", "Last trained")
ACTIVE_MARK = "● ACTIVE"
EMPTY_VALUE = "—"
ZIP_FILTER = "Model archives (*.zip)"

IMPORT_SECURITY_TITLE = "Import model — security notice"
IMPORT_SECURITY_TEXT = (
    "A model archive contains a serialized neural network that is loaded with "
    "PyTorch. Loading a model can execute code embedded in the file, so only "
    "import models from sources you trust.\n\nImport this archive?"
)
UPDATE_TITLE = "Update installed model?"
FOREIGN_NOTICE = (
    "Downloaded from the community and managed by its publisher, so it can't be "
    "trained here. To build on it, export it and import the archive back as your own."
)
SELECT_HINT = "Select a model to activate, edit, export or delete it."


def describe_type(model: Model) -> str:
    """The Type column, verbatim from the Tk tab.

    A community *download* is the publisher's, so it reads "read-only" — the
    user's only clue as to why Train disappears when they activate it. A model
    the user shared themselves carries a UID but is still theirs.
    """
    is_community = bool(model.community_model_uid)
    is_readonly = is_foreign_model(model)
    if is_community and is_readonly:
        return "Community (read-only)"
    if is_community:
        return "Community"
    if is_readonly:
        return "Read-only"
    return "Standard"


def image_counts() -> dict[int, int]:
    """Training images actually on disk, per model id."""
    counts: dict[int, int] = {}
    base = paths.models_dir()
    if not base.exists():
        return counts
    for entry in base.iterdir():
        if not entry.is_dir() or not entry.name.isdigit():
            continue
        images_dir = entry / "images"
        if not images_dir.exists():
            counts[int(entry.name)] = 0
            continue
        counts[int(entry.name)] = sum(
            1 for f in images_dir.iterdir() if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg", ".png")
        )
    return counts


class ModelsPage(QWidget):
    """The library table plus its toolbar and selection-driven actions."""

    def __init__(self, win: Any) -> None:
        super().__init__()
        self._win = win
        self.db = win.db
        self.cartridges = CartridgeRepo(self.db)
        self.models = ModelRepo(self.db)
        self.headstamps = HeadstampRepo(self.db)
        self.settings = SettingsRepo(self.db)
        # Rows currently shown, in table order: (id, Model | None).
        self._rows: list[tuple[int, Model | None]] = []
        self._columns_sized = False
        self._busy = False

        # The training-image browser is increment 8's; until it attaches its
        # hook (`set_images_hook`) the button it drives isn't shown at all.
        self.open_images: Callable[[Model], None] | None = None

        # Replaceable hooks — a test never opens a native dialog.
        self.confirm: Callable[[str, str], bool] = self._ask
        self.ask_open_path: Callable[[str], str | None] = self._ask_open_path
        self.ask_save_path: Callable[[str, str], str | None] = self._ask_save_path
        self.ask_text: Callable[[str, str], str | None] = self._ask_text
        self.ask_import_choice: Callable[[str], str] = self._ask_import_choice

        column = QVBoxLayout(self)
        column.setContentsMargins(12, 12, 12, 12)
        column.setSpacing(8)
        column.addLayout(self._build_filter_bar())
        column.addWidget(self._build_table(), 1)
        self.hint_label = QLabel(SELECT_HINT, self)
        self.hint_label.setObjectName("rowHint")
        self.hint_label.setWordWrap(True)
        column.addWidget(self.hint_label)
        column.addLayout(self._build_action_row())

        self.refresh()

    # ----- construction -------------------------------------------------------

    def _build_filter_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Cartridge", self))
        self.cartridge_combo = QComboBox(self)
        self.cartridge_combo.setMinimumWidth(140)
        self.cartridge_combo.currentIndexChanged.connect(lambda _i: self.refresh())
        bar.addWidget(self.cartridge_combo)

        bar.addWidget(QLabel("Type", self))
        self.type_combo = QComboBox(self)
        self.type_combo.addItems(list(TYPE_FILTERS))
        self.type_combo.currentIndexChanged.connect(lambda _i: self.refresh())
        bar.addWidget(self.type_combo)

        self.search_edit = QLineEdit(self)
        self.search_edit.setPlaceholderText("Search models")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(lambda _t: self.refresh())
        bar.addWidget(self.search_edit, 1)

        for text, handler in (
            ("New cartridge", self.new_cartridge),
            ("New model", self.new_model),
            ("Import…", self.import_archive),
        ):
            button = QPushButton(text, self)
            button.clicked.connect(handler)
            bar.addWidget(button)
        return bar

    def _build_table(self) -> QTreeWidget:
        self.tree = QTreeWidget(self)
        self.tree.setObjectName("modelTable")
        self.tree.setColumnCount(len(COLUMNS))
        self.tree.setHeaderLabels(list(COLUMNS))
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(False)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        # Every column user-draggable (JL); contents-sized once on fill, then
        # the user's widths stick. A Stretch section can't be dragged.
        header = self.tree.header()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        self.tree.currentItemChanged.connect(lambda _cur, _prev: self._update_actions())
        return self.tree

    def _autosize_columns(self) -> None:
        if self._columns_sized:
            return  # only before the user has had a chance to drag them
        self._columns_sized = True
        for i in range(len(COLUMNS)):
            self.tree.resizeColumnToContents(i)
        self.tree.setColumnWidth(0, max(self.tree.columnWidth(0), 260))

    def _build_action_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.buttons: dict[str, QPushButton] = {}
        for text, object_name, handler in (
            ("Activate", "action", self.activate_selected),
            ("Edit…", "", self.edit_selected),
            ("Images…", "", self.images_selected),
            ("Export…", "", self.export_selected),
            ("Delete", "danger", self.delete_selected),
        ):
            button = QPushButton(text, self)
            if object_name:
                button.setObjectName(object_name)
            button.clicked.connect(handler)
            row.addWidget(button)
            self.buttons[text] = button
        self.buttons["Images…"].setVisible(False)
        row.addStretch(1)
        return row

    def set_images_hook(self, open_images: Callable[[Model], None] | None) -> None:
        """Attach the training-image browser (increment 8).

        The button appears only once something can answer it, so the page
        never shows an action that leads nowhere.
        """
        self.open_images = open_images
        self.buttons["Images…"].setVisible(open_images is not None)
        self._update_actions()

    # ----- data ---------------------------------------------------------------

    def refresh(self, *, announce: bool = False) -> None:
        """Re-read the library and redraw, keeping the selection where it can.

        Nothing is cached: the active model, the rows and the on-disk image
        counts are all read fresh, so an activation from anywhere (this page,
        the Tk UI, a community download) shows up on the next refresh.
        """
        selected = self.selected_id()
        self._refresh_cartridge_filter()

        active_id = self.settings.get_active_model_id()
        cart_by_id = {c.id: c.name for c in self.cartridges.list()}
        counts = image_counts()

        self.tree.clear()
        self._rows = []
        if self._show_ai_row():
            self._add_ai_row(active_id is None)
        for model in self._filtered(self.models.list(), cart_by_id):
            self._add_model_row(model, cart_by_id, counts, active=model.id == active_id)

        self._restore_selection(selected)
        self._autosize_columns()
        self._update_actions()
        if announce:
            self._announce_active(active_id)

    def _refresh_cartridge_filter(self) -> None:
        names = [FILTER_TYPE_ALL] + [c.name for c in self.cartridges.list()]
        if [self.cartridge_combo.itemText(i) for i in range(self.cartridge_combo.count())] == names:
            return
        current = self.cartridge_combo.currentText() or FILTER_TYPE_ALL
        blocked = self.cartridge_combo.blockSignals(True)
        self.cartridge_combo.clear()
        self.cartridge_combo.addItems(names)
        self.cartridge_combo.setCurrentText(current if current in names else FILTER_TYPE_ALL)
        self.cartridge_combo.blockSignals(blocked)

    def _show_ai_row(self) -> bool:
        """AI Config isn't Standard/Community/ReadOnly, so it only shows under "All"."""
        if self.type_combo.currentText() != FILTER_TYPE_ALL:
            return False
        search = self.search_edit.text().strip().lower()
        return not search or "ai" in search or "config" in search

    def _filtered(self, models: list[Model], cart_by_id: dict[int, str]) -> list[Model]:
        cart_filter = self.cartridge_combo.currentText() or FILTER_TYPE_ALL
        type_filter = self.type_combo.currentText()
        search = self.search_edit.text().strip().lower()

        def match_type(model: Model) -> bool:
            is_community = bool(model.community_model_uid)
            is_readonly = is_foreign_model(model)
            if type_filter == FILTER_TYPE_COMMUNITY:
                return is_community
            if type_filter == FILTER_TYPE_READONLY:
                return is_readonly and not is_community
            if type_filter == FILTER_TYPE_STANDARD:
                return not is_community and not is_readonly
            return True

        out = [
            m
            for m in models
            if (cart_filter == FILTER_TYPE_ALL or cart_by_id.get(m.cartridge_id, "") == cart_filter)
            and match_type(m)
            and (not search or search in (m.name or "").lower())
        ]
        out.sort(key=lambda m: (cart_by_id.get(m.cartridge_id, ""), m.name.lower()))
        return out

    def _add_row(self, values: list[str], model_id: int, model: Model | None) -> QTreeWidgetItem:
        item = QTreeWidgetItem(self.tree, values)
        item.setData(0, Qt.ItemDataRole.UserRole, model_id)
        self._rows.append((model_id, model))
        return item

    def _add_ai_row(self, active: bool) -> None:
        item = self._add_row(
            [AI_CONFIG_NAME, ACTIVE_MARK if active else "", EMPTY_VALUE, "AI Config", "HTTP", "", "", ""],
            AI_CONFIG_SENTINEL_ID,
            None,
        )
        item.setToolTip(0, AI_CONFIG_HINT)

    def _add_model_row(
        self,
        model: Model,
        cart_by_id: dict[int, str],
        counts: dict[int, int],
        *,
        active: bool,
    ) -> None:
        self._add_row(
            [
                model.name,
                ACTIVE_MARK if active else "",
                cart_by_id.get(model.cartridge_id, EMPTY_VALUE),
                describe_type(model),
                model.model_mode,
                str(counts.get(model.id, model.trained_image_count)),
                "yes" if model.model_path else "no",
                model.last_training_date or EMPTY_VALUE,
            ],
            model.id,
            model,
        )

    def _restore_selection(self, model_id: int | None) -> None:
        target = model_id if model_id is not None else AI_CONFIG_SENTINEL_ID
        index = next((i for i, (row_id, _m) in enumerate(self._rows) if row_id == target), 0)
        item = self.tree.topLevelItem(index)
        if item is not None:
            self.tree.setCurrentItem(item)

    # ----- selection ----------------------------------------------------------

    def selected_id(self) -> int | None:
        item = self.tree.currentItem()
        if item is None:
            return None
        return int(item.data(0, Qt.ItemDataRole.UserRole))

    def selected_model(self) -> Model | None:
        """The selected row's model, re-read from the DB (None for the AI row)."""
        model_id = self.selected_id()
        if model_id is None or model_id == AI_CONFIG_SENTINEL_ID:
            return None
        return self.models.get(model_id)

    def _update_actions(self) -> None:
        model_id = self.selected_id()
        is_ai_row = model_id == AI_CONFIG_SENTINEL_ID
        model = next((m for row_id, m in self._rows if row_id == model_id), None)
        active_id = self.settings.get_active_model_id()
        already_active = (active_id is None) if is_ai_row else (model is not None and model.id == active_id)
        real = model is not None and not self._busy

        self.buttons["Activate"].setEnabled((real or (is_ai_row and not self._busy)) and not already_active)
        for name in ("Edit…", "Export…", "Delete"):
            self.buttons[name].setEnabled(real)
        # A community model's training images are the publisher's: it can't be
        # trained here, so there is no training set to curate. (Tk leaves the
        # browser open for these; the Train tab then refuses.)
        self.buttons["Images…"].setEnabled(real and is_trainable(model))
        self.hint_label.setText(self._hint_for(model, is_ai_row))

    def _hint_for(self, model: Model | None, is_ai_row: bool) -> str:
        if is_ai_row:
            return AI_CONFIG_HINT
        if model is None:
            return SELECT_HINT
        if not is_trainable(model):
            return FOREIGN_NOTICE
        return SELECT_HINT

    # ----- activation ---------------------------------------------------------

    def activate_selected(self) -> None:
        model_id = self.selected_id()
        if model_id is None:
            return
        if model_id == AI_CONFIG_SENTINEL_ID:
            self.settings.clear_active_model()
            new_active: int | None = None
        else:
            if self.models.get(model_id) is None:
                self.refresh()
                return
            self.settings.set_active_model_id(model_id)
            new_active = model_id
        # Same order as the Tk tab: headstamps are model-scoped and read fresh,
        # so they are reloaded before anyone reacts to the mode change.
        self._win.config.reload_headstamps_for_active_model()
        self._win.bus.post("mode/changed", {"active_model_id": new_active})
        self.refresh(announce=True)

    def _announce_active(self, active_id: int | None) -> None:
        if active_id is None:
            self._win.set_status("Active mode: AI Config.")
            return
        model = self.models.get(active_id)
        if model is not None:
            self._win.set_status(f"Active model: {model.name} ({model.model_mode}).")

    # ----- create / edit / delete ---------------------------------------------

    def new_cartridge(self) -> None:
        name = (self.ask_text("New cartridge", "Cartridge name:") or "").strip()
        if not name:
            return
        if self.cartridges.find_by_name(name) is not None:
            self._win.notify("Duplicate", f"Cartridge '{name}' already exists.")
            return
        try:
            with self.db.transaction():
                self.cartridges.create(name)
        except Exception as exc:
            self._win.notify("Failed", str(exc))
            return
        self.refresh()
        self._win.set_status(f"Added cartridge '{name}'.")

    def new_model(self) -> None:
        if not self.cartridges.list():
            self._win.notify("Add a cartridge first", "Create a cartridge before creating a model.")
            return
        dialog = ModelEditorDialog(self.db, parent=self)
        if dialog.exec():
            self.refresh()
            self._win.set_status("Model created.")

    def edit_selected(self) -> None:
        model = self.selected_model()
        if model is None:
            return
        dialog = ModelEditorDialog(self.db, existing=model, parent=self)
        if dialog.exec():
            self.refresh()
            self._win.set_status(f"Saved '{model.name}'.")

    def images_selected(self) -> None:
        model = self.selected_model()
        if model is None or self.open_images is None:
            return
        self.open_images(model)

    def delete_selected(self) -> None:
        model = self.selected_model()
        if model is None:
            return
        if not self.confirm(
            "Confirm delete",
            f"Delete model '{model.name}' and all associated headstamps and training images?",
        ):
            return
        try:
            with self.db.transaction():
                self.models.delete(model.id)
        except ValueError as exc:
            # The repo owns the rules (last model in a cartridge, active model);
            # this only reports them.
            self._win.notify("Cannot delete", str(exc))
            return
        # The whole `<model_id>` subtree goes: images, feedback_images, checkpoint.
        directory = paths.model_dir(model.id)
        if directory.exists():
            self._win.run_worker(lambda: shutil.rmtree(directory, ignore_errors=True))
        self.refresh()
        self._win.set_status(f"Deleted '{model.name}'.")

    # ----- import / export ----------------------------------------------------

    def import_archive(self) -> None:
        raw = self.ask_open_path("Import model archive")
        if not raw:
            return
        if not self.confirm(IMPORT_SECURITY_TITLE, IMPORT_SECURITY_TEXT):
            return
        zip_path = str(raw)
        try:
            target = find_update_target(zip_path, db=self.db)
        except Exception:
            # A broken archive fails loudly in import_model; here it just
            # means "we can't tell", which is the same as "it's new".
            target = None

        update_existing = True
        if target is not None:
            choice = self.ask_import_choice(target.name)
            if choice not in ("update", "copy"):
                return
            update_existing = choice == "update"

        self._set_busy(True)
        self._win.set_status("Importing model archive…")
        self._win.run_worker(
            lambda: import_model(zip_path, db=self.db, update_existing=update_existing),
            on_done=lambda result: self._on_imported(result, target if update_existing else None),
            on_error=lambda exc: self._fail("Import failed", exc),
        )

    def _on_imported(self, result: tuple[int, int], target: Model | None) -> None:
        self._set_busy(False)
        _cartridge_id, model_id = result
        message = f'Updated "{target.name}".' if target is not None else f"Imported model #{model_id}."
        self.refresh()
        self._win.set_status(message)
        self._win.notify("Import complete", message)

    def export_selected(self) -> None:
        model = self.selected_model()
        if model is None:
            return
        cartridge = self.cartridges.get(model.cartridge_id)
        if cartridge is None:
            return
        raw = self.ask_save_path("Export model", f"{model.name}.zip".replace(" ", "_"))
        if not raw:
            return
        dest = str(raw)
        # Everything the worker touches is read here: it must not go near the
        # widgets, and the DB reads are cheap enough to do up front.
        headstamps = self.headstamps.list_for_model(model.id)
        model_file = Path(model.model_path) if model.model_path else None
        images_dir = paths.model_images_dir(model.id)
        cartridge_name = cartridge.name

        self._set_busy(True)
        self._win.set_status(f"Exporting '{model.name}'…")
        self._win.run_worker(
            lambda: export_model(
                dest,
                model,
                cartridge_name=cartridge_name,
                headstamps=headstamps,
                mode=ExportMode.MODEL_AND_IMAGES,
                model_file=model_file,
                images_dir=images_dir,
            ),
            on_done=self._on_exported,
            on_error=lambda exc: self._fail("Export failed", exc),
        )

    def _on_exported(self, written: Any) -> None:
        self._set_busy(False)
        self._win.set_status(f"Wrote {written}")
        self._win.notify("Export complete", f"Wrote {written}")

    def _fail(self, title: str, exc: Exception) -> None:
        self._set_busy(False)
        self._win.set_status(f"{title}: {exc}")
        self._win.notify(title, str(exc))

    def _set_busy(self, busy: bool) -> None:
        """One archive at a time — both directions rewrite the same tree."""
        self._busy = busy
        self._update_actions()

    # ----- dialog hooks -------------------------------------------------------

    def _ask(self, title: str, text: str) -> bool:
        return QMessageBox.question(self, title, text) == QMessageBox.StandardButton.Yes

    def _ask_text(self, title: str, label: str) -> str | None:
        text, ok = QInputDialog.getText(self, title, label)
        return text if ok else None

    def _ask_open_path(self, title: str) -> str | None:
        path, _filter = QFileDialog.getOpenFileName(self, title, "", f"{ZIP_FILTER};;All files (*)")
        return path or None

    def _ask_save_path(self, title: str, default_name: str) -> str | None:
        path, _filter = QFileDialog.getSaveFileName(self, title, default_name, ZIP_FILTER)
        return path or None

    def _ask_import_choice(self, name: str) -> str:
        """Update in place, import as a copy, or cancel.

        Tk asks update-or-cancel; ``import_model(update_existing=False)`` has
        always been able to keep both, and a user who wants to compare two
        versions of a community model had no way to say so.
        """
        box = QMessageBox(self)
        box.setWindowTitle(UPDATE_TITLE)
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(f'This archive is a copy of "{name}", which is already installed.')
        box.setInformativeText(
            "Update it in place — its trained model is replaced, and its slot "
            "assignments and sorting templates are kept — or import a separate copy."
        )
        update = box.addButton("Update installed", QMessageBox.ButtonRole.AcceptRole)
        copy = box.addButton("Import as copy", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        clicked = box.clickedButton()
        if clicked is update:
            return "update"
        if clicked is copy:
            return "copy"
        return "cancel"


def build_models_page(win: Any) -> ModelsPage:
    return ModelsPage(win)
