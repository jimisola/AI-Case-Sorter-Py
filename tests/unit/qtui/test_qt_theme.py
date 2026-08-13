"""Every palette has to survive the trip to QSS — no gaps, no format artifacts."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from sorter.qtui.palettes import BUILTIN_THEMES
from sorter.qtui.theme import build_stylesheet


@pytest.mark.parametrize("name", list(BUILTIN_THEMES))
def test_stylesheet_carries_the_palette(name: str) -> None:
    palette = BUILTIN_THEMES[name]
    qss = build_stylesheet(palette)

    assert isinstance(qss, str)
    for role in ("bg_window", "action", "danger"):
        assert palette[role] in qss, f"{name}: {role} missing from the stylesheet"


@pytest.mark.parametrize("name", list(BUILTIN_THEMES))
def test_stylesheet_is_well_formed(name: str) -> None:
    qss = build_stylesheet(BUILTIN_THEMES[name])

    assert qss.count("{") == qss.count("}")
    assert "{bg_" not in qss and "{c[" not in qss, "unsubstituted format placeholder"
    assert "None" not in qss


@pytest.mark.parametrize("name", list(BUILTIN_THEMES))
def test_settings_button_uses_the_update_role_not_action_or_danger(name: str) -> None:
    palette = BUILTIN_THEMES[name]
    qss = build_stylesheet(palette)

    assert f"#settingsButton {{ color: {palette['update']}; }}" in qss
    assert palette["update"] not in (palette["action"], palette["danger"])
