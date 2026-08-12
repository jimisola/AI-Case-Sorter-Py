"""Render a ``sorter.ui.theme`` palette as a Qt stylesheet.

The palettes stay where they are — one source of truth for both UIs — and this
module is the Qt half of what ``ui/theme.py::apply_theme`` does for ttk. Every
color comes from the palette argument; nothing here is hardcoded, so a theme
added or edited on the Tk side themes the Qt shell too.

Key roles are documented in ``ui/theme.py``'s ``_DARK`` dict.
"""

from __future__ import annotations

# Only these roles are read, so a palette that is missing one (a hand-edited
# settings row) falls back rather than raising mid-stylesheet.
_FALLBACK = {
    "bg_window": "#131313",
    "bg_surface": "#1c1c1c",
    "bg_card": "#272727",
    "bg_card_hover": "#333333",
    "bg_card_sel": "#474747",
    "bg_input": "#0b0b0b",
    "bg_gradient_a": "#2f2f2f",
    "bg_gradient_b": "#0c0c0c",
    "border": "#3a3a3a",
    "border_focus": "#8f8f8f",
    "text": "#d4d4d4",
    "text_muted": "#9a9a9a",
    "text_inverse": "#121212",
    "accent_dim": "#2e2e2e",
    "action": "#22c55e",
    "action_hover": "#4ade80",
    "action_press": "#16a34a",
    "danger": "#ef4444",
    "danger_hover": "#f87171",
    "danger_press": "#dc2626",
}


def build_stylesheet(palette: dict[str, str]) -> str:
    """QSS for one palette: window, header gradient, tabs, buttons, fields, status bar."""
    c = {**_FALLBACK, **{k: v for k, v in palette.items() if isinstance(v, str)}}
    return f"""
QMainWindow, QWidget {{
    background-color: {c["bg_window"]};
    color: {c["text"]};
}}

#header {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {c["bg_gradient_a"]}, stop:1 {c["bg_gradient_b"]});
}}
#header QLabel {{ background: transparent; }}

QTabWidget::pane {{
    background-color: {c["bg_surface"]};
    border: 1px solid {c["border"]};
    top: -1px;
}}
QTabBar::tab {{
    background-color: {c["bg_card"]};
    color: {c["text_muted"]};
    border: 1px solid {c["border"]};
    border-bottom: none;
    padding: 6px 16px;
    margin-right: 2px;
}}
QTabBar::tab:hover {{ background-color: {c["bg_card_hover"]}; }}
QTabBar::tab:selected {{
    background-color: {c["bg_card_sel"]};
    color: {c["text"]};
}}

QPushButton {{
    background-color: {c["accent_dim"]};
    color: {c["text"]};
    border: 1px solid {c["border"]};
    border-radius: 3px;
    padding: 5px 14px;
}}
QPushButton:hover {{ background-color: {c["bg_card_hover"]}; }}
QPushButton:disabled {{ color: {c["text_muted"]}; }}

QPushButton#action {{
    background-color: {c["action"]};
    color: {c["text_inverse"]};
    border-color: {c["action"]};
}}
QPushButton#action:hover {{
    background-color: {c["action_hover"]};
    border-color: {c["action_hover"]};
}}
QPushButton#action:pressed {{
    background-color: {c["action_press"]};
    border-color: {c["action_press"]};
}}

QPushButton#danger {{
    background-color: {c["danger"]};
    color: {c["text_inverse"]};
    border-color: {c["danger"]};
}}
QPushButton#danger:hover {{
    background-color: {c["danger_hover"]};
    border-color: {c["danger_hover"]};
}}
QPushButton#danger:pressed {{
    background-color: {c["danger_press"]};
    border-color: {c["danger_press"]};
}}

QComboBox, QLineEdit {{
    background-color: {c["bg_input"]};
    color: {c["text"]};
    border: 1px solid {c["border"]};
    border-radius: 3px;
    padding: 4px 8px;
    selection-background-color: {c["bg_card_sel"]};
    selection-color: {c["text"]};
}}
QComboBox:focus, QLineEdit:focus {{ border: 1px solid {c["border_focus"]}; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{
    background-color: {c["bg_card"]};
    color: {c["text"]};
    border: 1px solid {c["border"]};
    selection-background-color: {c["bg_card_sel"]};
    selection-color: {c["text"]};
}}

QStatusBar {{
    background-color: {c["bg_window"]};
    color: {c["text_muted"]};
}}
QStatusBar::item {{ border: none; }}
"""
