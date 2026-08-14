"""``sorter/qtui`` imports nothing from ``sorter/ui`` — and the copies stay copies.

The Qt UI must run in an environment that has PySide6 and no tkinter at all, so
the two things it used to import from the Tk package are now copied into it:
``ui/theme.py``'s palette half → ``qtui/palettes.py``, and
``ui/serial_monitor.py``'s four wire constants → ``qtui/serial_monitor.py``.

A copy that nothing checks is a copy that drifts, so this module pins them:
the shipped data by value, and every copied function by the **bytes of its
source**. A failure here means ``ui/`` moved — re-sync the copy from it (do not
"fix" the pin), and keep the copied region verbatim so the next re-sync is a
diff of two identical files.

Only ``test_no_qtui_module_imports_the_tk_package`` runs without tkinter; the
rest read ``sorter.ui`` and skip without it. PySide6 is only needed for the
serial constants, which live in a module that imports it.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from types import ModuleType

import pytest

from sorter.qtui import palettes

# Every function copied out of ui/theme.py, private helpers included.
COPIED_FUNCTIONS = (
    "custom_theme_names",
    "custom_theme_payload",
    "custom_themes_payload",
    "editable_roles",
    "is_custom_theme",
    "load_custom_themes",
    "normalize_palette",
    "register_custom_theme",
    "rename_custom_theme",
    "resolve_theme",
    "theme_names",
    "unique_theme_name",
    "unregister_custom_theme",
    "_is_hex_color",
)

# Module-level values copied verbatim.
COPIED_CONSTANTS = (
    "BUILTIN_THEMES",
    "CUSTOM_THEME_VERSION",
    "DEFAULT_THEME",
    "DERIVED_ROLES",
    "MAX_THEME_NAME",
    "SETTING_CUSTOM_THEMES",
    "SETTING_THEME",
)

RESYNC = "re-sync src/sorter/qtui/palettes.py from src/sorter/ui/theme.py"


@pytest.fixture(scope="module")
def tk_theme() -> ModuleType:
    pytest.importorskip("tkinter")  # ui/theme.py imports it at module level
    from sorter.ui import theme

    return theme


@pytest.fixture(scope="module")
def tk_serial() -> ModuleType:
    pytest.importorskip("tkinter")
    from sorter.ui import serial_monitor

    return serial_monitor


def test_copied_constants_are_identical(tk_theme: ModuleType) -> None:
    for name in COPIED_CONSTANTS:
        assert getattr(palettes, name) == getattr(tk_theme, name), f"{name} drifted — {RESYNC}"


def test_halftone_and_outline_options_are_identical(tk_theme: ModuleType) -> None:
    """The shipped entries only.

    Both registries also carry whatever user-made themes the running UI has
    registered, and those are per-UI now by design (each UI writes into its own
    copy; the ``ui.custom_themes`` settings row is what they actually share).
    """
    for name in ("HALFTONE_INK", "INK_OUTLINE"):
        ours = getattr(palettes, name)
        theirs = getattr(tk_theme, name)
        shipped = set(palettes.BUILTIN_THEMES)
        assert {k: v for k, v in ours.items() if k in shipped} == {k: v for k, v in theirs.items() if k in shipped}, (
            f"{name} drifted — {RESYNC}"
        )


def test_copied_functions_are_byte_identical(tk_theme: ModuleType) -> None:
    for name in COPIED_FUNCTIONS:
        ours = inspect.getsource(getattr(palettes, name))
        theirs = inspect.getsource(getattr(tk_theme, name))
        assert ours == theirs, f"{name}() drifted — {RESYNC}"


def test_every_registry_function_that_exists_in_ui_is_copied(tk_theme: ModuleType) -> None:
    """A new registry helper on the Tk side has to be copied or consciously skipped.

    The Qt UI's own module is the smaller of the two (it has no Tk painters), so
    the pin runs the other way: everything *here* must exist there.
    """
    ours = {
        name
        for name, value in vars(palettes).items()
        if inspect.isfunction(value) and value.__module__ == palettes.__name__
    }
    assert ours == set(COPIED_FUNCTIONS), f"a function in qtui/palettes.py is unpinned — {RESYNC}"
    assert ours <= set(vars(tk_theme)), f"a copied function is gone from ui/theme.py — {RESYNC}"


def test_serial_constants_are_identical(tk_serial: ModuleType) -> None:
    pytest.importorskip("PySide6")
    from sorter.qtui import serial_monitor as qt_serial

    for name in ("BAUD_RATES", "DEFAULT_BAUD", "DEFAULT_LINE_ENDING", "LINE_ENDINGS"):
        assert getattr(qt_serial, name) == getattr(tk_serial, name), (
            f"{name} drifted — re-sync src/sorter/qtui/serial_monitor.py from src/sorter/ui/serial_monitor.py"
        )


def test_no_qtui_module_imports_the_tk_package() -> None:
    """The reason the copies exist: a PySide6-only install has no tkinter."""
    package = Path(__file__).resolve().parents[3] / "src" / "sorter" / "qtui"
    offenders: list[str] = []
    for path in sorted(package.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                # level 2 == `from ..<module> import …`, i.e. a sibling of qtui.
                names = [f"sorter.{node.module}" if node.level == 2 else (node.module or "")]
            else:
                continue
            for name in names:
                if name == "tkinter" or name.startswith(("tkinter.", "sorter.ui")):
                    offenders.append(f"{path.name}: {name}")
    assert not offenders, "sorter/qtui must not import the Tk UI or tkinter: " + ", ".join(offenders)
