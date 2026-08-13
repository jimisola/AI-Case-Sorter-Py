"""Render a theme palette (``qtui/palettes.py``) as a Qt stylesheet.

This module is the Qt half of what ``ui/theme.py::apply_theme`` does for ttk.
Every color comes from the palette argument; nothing here is hardcoded, so a
theme added or edited on either side themes the Qt shell too.

Key roles are documented in ``qtui/palettes.py``'s ``_DARK`` dict.
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
    "text_highlight": "#ffffff",
    "text_muted": "#9a9a9a",
    "text_subtle": "#6f6f6f",
    "text_inverse": "#121212",
    "accent": "#e0e0e0",
    "accent_dim": "#2e2e2e",
    "update": "#60a5fa",
    "update_hover": "#93c5fd",
    "update_press": "#3b82f6",
    "success": "#22c55e",
    "warning": "#f59e0b",
    "action": "#22c55e",
    "action_hover": "#4ade80",
    "action_press": "#16a34a",
    "danger": "#ef4444",
    "danger_hover": "#f87171",
    "danger_press": "#dc2626",
}


def build_stylesheet(palette: dict[str, str]) -> str:
    """QSS for one palette: window, header, sidebar, menus, dock, buttons, fields, status bar."""
    c = {**_FALLBACK, **{k: v for k, v in palette.items() if isinstance(v, str)}}
    return f"""
QMainWindow, QWidget {{
    background-color: {c["bg_window"]};
    color: {c["text"]};
}}

/* Unstyled, this is a few px of plain background — indistinguishable from
   the universal QWidget fill above, so a dock edge had nothing to grab. */
QMainWindow::separator {{
    background-color: {c["border"]};
    width: 5px;
    height: 5px;
}}
QMainWindow::separator:hover {{ background-color: {c["border_focus"]}; }}

/* The two label colors below are also what inks the activity icons — a
   stylesheet can't reach a QIcon, so app._paint_sidebar_icon renders them
   from the same two roles. Change one here and change it there. */
#sidebar {{ background-color: {c["bg_surface"]}; }}
#sidebar QToolButton {{
    background: transparent;
    color: {c["text_muted"]};
    border: none;
    border-radius: 3px;
    padding: 8px 2px;
}}
#sidebar QToolButton:hover {{ background-color: {c["bg_card_hover"]}; }}
#sidebar QToolButton:checked {{
    background-color: {c["bg_card_sel"]};
    color: {c["text_highlight"]};
}}
QMenuBar {{
    background-color: {c["bg_surface"]};
    color: {c["text"]};
}}
QMenuBar::item {{ background: transparent; padding: 4px 10px; }}
QMenuBar::item:selected {{ background-color: {c["bg_card_sel"]}; }}
QMenu {{
    background-color: {c["bg_card"]};
    color: {c["text"]};
    border: 1px solid {c["border"]};
}}
QMenu::item {{ padding: 4px 22px; }}
QMenu::item:selected {{
    background-color: {c["bg_card_sel"]};
    color: {c["text_highlight"]};
}}
QMenu::separator {{ height: 1px; background-color: {c["border"]}; margin: 4px 0; }}

/* Explicit background, not just on ::title: seen blank/transparent on Wayland
   after a float -> re-dock cycle, letting whatever sits behind the window
   show through the gaps between styled children (a known class of Qt/Wayland
   dock-widget repaint issue). QDockWidget > QWidget covers the content
   container Qt inserts around whatever widget was set on the dock. */
QDockWidget {{
    background-color: {c["bg_window"]};
    color: {c["text"]};
}}
QDockWidget > QWidget {{ background-color: {c["bg_window"]}; }}
QDockWidget::title {{
    background-color: {c["bg_surface"]};
    color: {c["text"]};
    padding: 5px 8px;
}}

QPlainTextEdit#serialLog {{
    background-color: {c["bg_input"]};
    color: {c["text"]};
    border: 1px solid {c["border"]};
}}

QListWidget {{
    background-color: {c["bg_input"]};
    color: {c["text"]};
    border: 1px solid {c["border"]};
}}
QListWidget::item {{ padding: 5px 8px; }}
QListWidget::item:selected {{
    background-color: {c["bg_card_sel"]};
    color: {c["text_highlight"]};
}}

QTreeWidget#modelTable, QTreeWidget#headstampTable {{
    background-color: {c["bg_input"]};
    color: {c["text"]};
    border: 1px solid {c["border"]};
}}
QTreeWidget#modelTable::item, QTreeWidget#headstampTable::item {{ padding: 4px 6px; }}
QTreeWidget#modelTable::item:selected, QTreeWidget#headstampTable::item:selected {{
    background-color: {c["bg_card_sel"]};
    color: {c["text_highlight"]};
}}
QTreeWidget#modelTable QHeaderView::section, QTreeWidget#headstampTable QHeaderView::section {{
    background-color: {c["bg_card"]};
    color: {c["text_muted"]};
    border: none;
    border-bottom: 1px solid {c["border"]};
    padding: 5px 6px;
}}
/* Per-row action buttons: the row is the item's own background, and a
   toolbar-sized button would make every row that tall. */
QWidget#rowActions {{ background: transparent; }}
QTreeWidget#modelTable QPushButton {{ padding: 2px 8px; }}

QFrame#slotCard {{
    background-color: {c["bg_card"]};
    border: 1px solid {c["border"]};
    border-radius: 6px;
}}
/* The whole card is a click target, so it lights up like one. */
QFrame#slotCard:hover {{ background-color: {c["bg_card_hover"]}; }}
/* The card's background would otherwise cascade into its labels' own fills. */
QFrame#slotCard QLabel {{ background: transparent; }}
QLabel#slotTitle {{ color: {c["text"]}; font-weight: bold; }}
QLabel#slotCount {{ color: {c["text_highlight"]}; font-size: 22px; font-weight: bold; }}
QLabel#slotPackage {{ color: {c["text_muted"]}; }}
QLabel#slotNames {{ color: {c["text_muted"]}; }}
QLabel#slotEdit {{ color: {c["text_subtle"]}; }}

QLabel#masterCount {{ color: {c["text_highlight"]}; font-size: 20px; font-weight: bold; }}
QLabel#cropPanel {{
    background-color: {c["bg_input"]};
    color: {c["text_muted"]};
    border: 1px solid {c["border"]};
}}
/* The Sort column's current-case line. The confidence colour is state (above
   or below the floor), so _paint_current_result sets it per widget. */
QLabel#currentHeadstamp {{ color: {c["text_highlight"]}; font-size: 18px; font-weight: bold; }}
QLabel#currentConfidence {{ font-size: 16px; font-weight: bold; }}

QDialog {{ background-color: {c["bg_window"]}; }}
QLabel#dialogHint, QLabel#rowHint {{ color: {c["text_muted"]}; }}
QCheckBox, QRadioButton {{ background: transparent; color: {c["text"]}; }}
QCheckBox:disabled, QRadioButton:disabled {{ color: {c["text_subtle"]}; }}
QSpinBox, QDoubleSpinBox {{
    background-color: {c["bg_input"]};
    color: {c["text"]};
    border: 1px solid {c["border"]};
    border-radius: 3px;
    padding: 3px 4px;
}}
QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {c["border_focus"]}; }}

QLabel#mutedLabel {{ color: {c["text_muted"]}; }}
QLabel#updateTitle {{ color: {c["text_highlight"]}; font-weight: bold; }}
QLabel#updateVersion {{ color: {c["accent"]}; }}

QTextBrowser {{
    background-color: {c["bg_input"]};
    color: {c["text"]};
    border: 1px solid {c["border"]};
    border-radius: 3px;
    padding: 6px;
}}
QLabel#aiResultLabel {{ color: {c["text_highlight"]}; font-weight: bold; }}

QFrame#thumbTile {{ border: 1px solid transparent; border-radius: 4px; }}
QFrame#thumbTile:hover {{ background-color: {c["bg_card_hover"]}; }}
QFrame#thumbTile[selected="true"] {{ border: 2px solid {c["accent"]}; }}
QFrame#thumbTile QLabel {{ background: transparent; }}
QLabel#thumbImage {{ background-color: {c["bg_input"]}; border-radius: 3px; }}
QLabel#thumbCaption {{ color: {c["text_muted"]}; font-size: 8pt; }}
QLabel#imagePreview {{
    background-color: {c["bg_input"]};
    border: 1px solid {c["border"]};
    border-radius: 4px;
}}

QPlainTextEdit {{
    background-color: {c["bg_input"]};
    color: {c["text"]};
    border: 1px solid {c["border"]};
    border-radius: 3px;
}}
QPlainTextEdit:focus {{ border-color: {c["border_focus"]}; }}

QGroupBox {{
    border: 1px solid {c["border"]};
    border-radius: 4px;
    margin-top: 10px;
    color: {c["text"]};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
    color: {c["text_muted"]};
}}

QSlider::groove:horizontal {{
    background-color: {c["bg_input"]};
    height: 4px;
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background-color: {c["accent"]};
    width: 14px;
    margin: -6px 0;
    border-radius: 7px;
}}

QProgressBar {{
    background-color: {c["bg_input"]};
    color: {c["text"]};
    border: 1px solid {c["border"]};
    border-radius: 3px;
    text-align: center;
}}
QProgressBar::chunk {{ background-color: {c["action"]}; border-radius: 2px; }}

QSplitter::handle {{ background-color: {c["border"]}; }}
QSplitter::handle:horizontal {{ width: 3px; }}
QSplitter::handle:vertical {{ height: 3px; }}

QToolTip {{
    background-color: {c["bg_card"]};
    color: {c["text"]};
    border: 1px solid {c["border"]};
}}

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

QPushButton#update {{
    background-color: {c["update"]};
    color: {c["text_inverse"]};
    border-color: {c["update"]};
}}
QPushButton#update:hover {{
    background-color: {c["update_hover"]};
    border-color: {c["update_hover"]};
}}
QPushButton#update:pressed {{
    background-color: {c["update_press"]};
    border-color: {c["update_press"]};
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
