"""Themes for the OSS Client UI.

Centralises colors, fonts, and ttk styles so the rest of the app can stay
focused on layout. Every color lives in one of the palettes below; the
rest of the app reads the *live* ``PALETTE`` dict, which always holds the
selected theme's values.

**The role of each key is fixed; only its color changes per theme.** The
original theme (``"Dark"``) keeps its chrome — window, panels, cards,
inputs, borders, text — **neutral grayscale**: a flat luminance ladder
that gives the UI depth without bevels, relief, or a hue of its own,
reserving color for things that mean something (action buttons, status
text). The alternative themes tint the chrome, but they keep that
discipline internally: their surfaces stay a single low-saturation family
so the action buttons remain the most saturated thing on screen.

Adding a theme means copying ``_DARK`` and re-colouring it — every theme
must define exactly the same keys (``tests/test_theme.py`` enforces it).

Exported helpers:

* ``apply_theme(root, theme=...)`` — call once after the root is created,
  and again on every theme switch. Selects the palette, applies ttk styles,
  sets defaults for the legacy Tk widgets (Listbox / Text / Canvas), and
  returns the resolved fonts dict for callers that need to match.
* ``retheme_widgets(root, previous)`` — after a switch, repaint the classic
  Tk widgets that baked their colors in at construction time.
* ``paint_gradient(canvas, ...)`` — paint a vertical/horizontal linear
  gradient across the canvas. Used for the title bar.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk


# Settings key holding the user's chosen theme name (see repository.SettingsRepo).
SETTING_THEME = "ui.theme"


# The original theme, and the reference for every other palette's key set.
#
# Everything above the "Action colors" block is neutral gray (R == G == B):
# surfaces, borders, text, and the selection/focus tints. Only the action
# and status entries carry hue. If you add a color here, ask which of the
# two groups it belongs to — a new tinted surface breaks the contrast the
# colored buttons rely on.
_DARK = {
    # Backgrounds — neutral gray, darkest to lightest.
    "bg_window":     "#131313",   # app background / gradient bottom
    "bg_gradient_a": "#2f2f2f",   # title bar left
    "bg_gradient_b": "#0c0c0c",   # title bar right
    "bg_surface":    "#1c1c1c",   # panels — one step up from the window
    "bg_card":       "#272727",   # raised surfaces (slot cards, monitor log)
    "bg_card_hover": "#333333",   # card hover
    "bg_card_sel":   "#474747",   # selected card — lifted, still neutral
    "bg_input":      "#0b0b0b",   # deeper than window — entries, listbox, text

    # Borders / separators.
    "border":        "#3a3a3a",
    "border_focus":  "#8f8f8f",   # focus ring — brightness, not hue

    # Text.
    "text":          "#d4d4d4",
    "text_highlight": "#ffffff",  # emphasised values (Accent.TLabel)
    "text_muted":    "#9a9a9a",
    "text_subtle":   "#6f6f6f",
    "text_inverse":  "#121212",   # for text on light/action backgrounds

    # Neutral "accent" — section titles, focus, indicators, selection fills.
    # Kept gray on purpose: emphasis here comes from brightness so that the
    # action colors below stay the only saturated thing on screen.
    "accent":        "#e0e0e0",
    "accent_hover":  "#f2f2f2",
    "accent_press":  "#c2c2c2",
    "accent_dim":    "#2e2e2e",   # subtle button rest state

    # Action colors — buttons only. Green = primary/go, blue = update an
    # existing thing, red = stop/destructive. Picked at similar brightness so
    # they read as one family and carry dark text.
    "action":        "#22c55e",
    "action_hover":  "#4ade80",
    "action_press":  "#16a34a",
    "update":        "#60a5fa",
    "update_hover":  "#93c5fd",
    "update_press":  "#3b82f6",
    "danger":        "#ef4444",
    "danger_hover":  "#f87171",
    "danger_press":  "#dc2626",

    # Status colors — text and small indicators. `success` tracks `action`
    # and `error` tracks `danger` in every theme: they are the same idea
    # rendered as text instead of a button.
    "success":       "#22c55e",
    "success_dim":   "#14331f",   # muted green fill — e.g. applied auto-suggestions
    "warning":       "#f59e0b",
    "error":         "#ef4444",
}

# Daylight theme: the gray ladder inverted, so "lifted" reads as *darker*
# rather than brighter. The action colors are the darker 700-weight shades
# because they now sit against white and carry light text.
_LIGHT = {
    "bg_window":     "#eaeaea",
    "bg_gradient_a": "#fbfbfb",
    "bg_gradient_b": "#d4d4d4",
    "bg_surface":    "#f4f4f4",
    "bg_card":       "#ffffff",
    "bg_card_hover": "#ededed",
    "bg_card_sel":   "#d8d8d8",
    "bg_input":      "#fdfdfd",

    "border":        "#c2c2c2",
    "border_focus":  "#5b5b5b",

    "text":          "#1c1c1c",
    "text_highlight": "#000000",
    "text_muted":    "#565656",
    "text_subtle":   "#868686",
    "text_inverse":  "#fafafa",

    "accent":        "#3d3d3d",
    "accent_hover":  "#292929",
    "accent_press":  "#101010",
    "accent_dim":    "#e2e2e2",

    "action":        "#15803d",
    "action_hover":  "#16a34a",
    "action_press":  "#0f5f2e",
    "update":        "#1d4ed8",
    "update_hover":  "#2563eb",
    "update_press":  "#1e40af",
    "danger":        "#b91c1c",
    "danger_hover":  "#dc2626",
    "danger_press":  "#991b1b",

    "success":       "#15803d",
    "success_dim":   "#d5f0de",
    "warning":       "#b45309",
    "error":         "#b91c1c",
}

# Warm paper — the light theme's twin for people who find pure white harsh.
_SEPIA = {
    "bg_window":     "#e8dfcf",
    "bg_gradient_a": "#f6efe0",
    "bg_gradient_b": "#d3c6ae",
    "bg_surface":    "#f2ebdc",
    "bg_card":       "#fdf8ee",
    "bg_card_hover": "#eee5d3",
    "bg_card_sel":   "#dccfb6",
    "bg_input":      "#fffdf7",

    "border":        "#c3b498",
    "border_focus":  "#6b5b43",

    "text":          "#3a2f22",
    "text_highlight": "#1c150c",
    "text_muted":    "#6d5f4c",
    "text_subtle":   "#948673",
    "text_inverse":  "#fdf9f0",

    "accent":        "#5b4a34",
    "accent_hover":  "#453727",
    "accent_press":  "#2e2419",
    "accent_dim":    "#e0d6c1",

    "action":        "#46733a",
    "action_hover":  "#558a45",
    "action_press":  "#35592c",
    "update":        "#2f6690",
    "update_hover":  "#3d7fb0",
    "update_press":  "#255273",
    "danger":        "#a33232",
    "danger_hover":  "#c04040",
    "danger_press":  "#872828",

    "success":       "#46733a",
    "success_dim":   "#dbe8cf",
    "warning":       "#9a6b12",
    "error":         "#a33232",
}

# Deep navy chrome. The surfaces carry the hue, so the accent is pulled
# almost to white to keep selection fills legible.
_MIDNIGHT_BLUE = {
    "bg_window":     "#0b1220",
    "bg_gradient_a": "#1b2a4a",
    "bg_gradient_b": "#060b16",
    "bg_surface":    "#121c2e",
    "bg_card":       "#1a2740",
    "bg_card_hover": "#22334f",
    "bg_card_sel":   "#31456a",
    "bg_input":      "#070d18",

    "border":        "#2c3b57",
    "border_focus":  "#7ea2d8",

    "text":          "#d6e2f5",
    "text_highlight": "#ffffff",
    "text_muted":    "#93a6c4",
    "text_subtle":   "#6a7c99",
    "text_inverse":  "#0a1120",

    "accent":        "#cfe0fb",
    "accent_hover":  "#e8f1ff",
    "accent_press":  "#a9c4ea",
    "accent_dim":    "#22314d",

    "action":        "#22c55e",
    "action_hover":  "#4ade80",
    "action_press":  "#16a34a",
    "update":        "#60a5fa",
    "update_hover":  "#93c5fd",
    "update_press":  "#3b82f6",
    "danger":        "#ef4444",
    "danger_hover":  "#f87171",
    "danger_press":  "#dc2626",

    "success":       "#22c55e",
    "success_dim":   "#123a2a",
    "warning":       "#fbbf24",
    "error":         "#ef4444",
}

# Black and blood red. The one theme whose accent carries hue: section
# titles, selection fills and the focus ring are crimson, and the surfaces
# are near-black with just enough red in them to belong. Green still means
# go and the danger red stays a step brighter than the accent, so a Stop or
# a Delete button is still the loudest thing on screen.
_GOTHIC = {
    "bg_window":     "#0c0708",
    "bg_gradient_a": "#4a1116",
    "bg_gradient_b": "#080405",
    "bg_surface":    "#150e10",
    "bg_card":       "#1f1416",
    "bg_card_hover": "#2b1a1d",
    "bg_card_sel":   "#46181e",
    "bg_input":      "#070303",

    "border":        "#3a2226",
    "border_focus":  "#c0464e",

    "text":          "#e0d6d7",
    "text_highlight": "#ffffff",
    "text_muted":    "#a89597",
    "text_subtle":   "#7a686a",
    "text_inverse":  "#0b0607",

    "accent":        "#d13c45",
    "accent_hover":  "#e85860",
    "accent_press":  "#a52a31",
    "accent_dim":    "#2a1518",

    "action":        "#3fb950",
    "action_hover":  "#56d364",
    "action_press":  "#2ea043",
    "update":        "#5b82c4",
    "update_hover":  "#7ba0dd",
    "update_press":  "#45689f",
    "danger":        "#e5484d",
    "danger_hover":  "#ef6b6f",
    "danger_press":  "#c93c41",

    "success":       "#3fb950",
    "success_dim":   "#1b2a1e",
    "warning":       "#d29922",
    "error":         "#e5484d",
}

# Comic-book ink: black panel gutters, a cobalt title bar, gold and orange
# on top. The one theme where **gold, not green, is "go"** — an anime/comic
# palette has no green in it, and `success` tracks `action` by rule, so the
# connected indicator is gold here and the disconnected one stays red. Gold
# against red separates further than green against red for the most common
# form of colour blindness, and both dots sit beside their labels anyway.
_COMIC = {
    "bg_window":     "#0e1117",
    "bg_gradient_a": "#1b56b8",   # cobalt left — the comic panel's sky
    "bg_gradient_b": "#090c11",
    "bg_surface":    "#151a23",
    "bg_card":       "#1e2531",
    "bg_card_hover": "#29323f",
    "bg_card_sel":   "#26406d",   # selection lifts toward the cobalt
    "bg_input":      "#070a0e",

    "border":        "#2c3644",
    "border_focus":  "#ffd257",

    "text":          "#eef2f8",
    "text_highlight": "#ffffff",
    "text_muted":    "#a5b1c1",
    "text_subtle":   "#6f7c8d",
    "text_inverse":  "#0b0e13",

    "accent":        "#f2b01e",
    "accent_hover":  "#ffc74d",
    "accent_press":  "#cc9014",
    "accent_dim":    "#232c39",

    "action":        "#ffc219",
    "action_hover":  "#ffd451",
    "action_press":  "#e0a300",
    "update":        "#2f7fe0",
    "update_hover":  "#559bf0",
    "update_press":  "#1f63b8",
    "danger":        "#e5342a",
    "danger_hover":  "#f4574d",
    "danger_press":  "#c02318",

    "success":       "#ffc219",
    "success_dim":   "#3a2f08",
    "warning":       "#ff8a1f",
    "error":         "#e5342a",
}

# Display name → palette. Insertion order drives the picker's order.
THEMES: dict[str, dict[str, str]] = {
    "Dark": _DARK,
    "Light": _LIGHT,
    "Sepia": _SEPIA,
    "Midnight Blue": _MIDNIGHT_BLUE,
    "Gothic": _GOTHIC,
    "Comic Book": _COMIC,
}

DEFAULT_THEME = "Dark"

# Themes whose title bar gets a ben-day dot field printed over the gradient,
# and the ink to print it in. A theme that isn't listed here gets a plain
# gradient — the dots are a comic-book device, not a default. Pick an ink
# close to the gradient's dark end so the field fades out as the background
# darkens under it.
HALFTONE_INK = {
    "Comic Book": "#123a86",
}


def halftone_ink() -> str | None:
    """Dot colour for the current theme's title bar, or None for no dots."""
    return HALFTONE_INK.get(_current_theme)

# The live palette. Modules do `from .theme import PALETTE` and index it at
# call time, so switching themes **mutates this dict in place** — rebinding
# the name here would leave every importer holding the old colors.
PALETTE: dict[str, str] = dict(THEMES[DEFAULT_THEME])

_current_theme = DEFAULT_THEME


def theme_names() -> list[str]:
    """Selectable theme names, in display order."""
    return list(THEMES)


def current_theme() -> str:
    """Name of the palette currently loaded into ``PALETTE``."""
    return _current_theme


def resolve_theme(name: str | None) -> str:
    """Map a stored/user-supplied name onto a real theme, case-insensitively."""
    if name:
        for known in THEMES:
            if known.casefold() == str(name).casefold():
                return known
    return DEFAULT_THEME


def set_palette(name: str | None) -> dict[str, str]:
    """Load a theme into ``PALETTE`` in place; returns the palette it replaced.

    The returned snapshot is what ``retheme_widgets`` needs to recognise the
    colors already baked into existing classic Tk widgets.
    """
    global _current_theme
    previous = dict(PALETTE)
    _current_theme = resolve_theme(name)
    PALETTE.clear()
    PALETTE.update(THEMES[_current_theme])
    return previous


def _pick_font(
    root: tk.Misc, candidates: list[str], fallback: str
) -> str:
    """Return the first font in candidates that's available on the host."""
    try:
        available = set(tkfont.families(root))
    except tk.TclError:
        return fallback
    for name in candidates:
        if name in available:
            return name
    return fallback


def get_fonts(root: tk.Misc) -> dict[str, tuple]:
    """Pick a modern UI font and matching monospace font for the host."""
    family = _pick_font(
        root,
        [
            "Inter", "SF Pro Text", "Segoe UI", "Helvetica Neue",
            "Cantarell", "Ubuntu", "Noto Sans", "DejaVu Sans",
        ],
        fallback="TkDefaultFont",
    )
    mono = _pick_font(
        root,
        [
            "JetBrains Mono", "Cascadia Code", "Fira Code",
            "Consolas", "Menlo", "DejaVu Sans Mono",
        ],
        fallback="TkFixedFont",
    )
    return {
        "default":      (family, 10),
        "body":         (family, 10),
        "bold":         (family, 10, "bold"),
        "header":       (family, 12, "bold"),
        "title":        (family, 18, "bold"),
        "selected_tab": (family, 11, "bold"),
        "small":        (family, 9),
        "mono":         (mono, 10),
    }


def _colored_button(
    style: ttk.Style,
    name: str,
    fonts: dict[str, tuple],
    *,
    rest: str,
    hover: str,
    press: str,
) -> None:
    """Configure a solid-fill action button (the app's only colored controls).

    clam draws a button's edge from bordercolor/darkcolor/lightcolor, so all
    three track the fill or the button reads as outlined.
    """
    style.configure(
        name,
        background=rest,
        foreground=PALETTE["text_inverse"],
        bordercolor=rest,
        darkcolor=rest,
        lightcolor=rest,
        focuscolor=PALETTE["text_inverse"],
        font=fonts["bold"],
    )
    fill = [
        ("pressed", press),
        ("active", hover),
        ("disabled", PALETTE["bg_surface"]),
    ]
    style.map(
        name,
        background=fill,
        bordercolor=fill,
        darkcolor=fill,
        lightcolor=fill,
        foreground=[("disabled", PALETTE["text_subtle"])],
    )


def apply_theme(root: tk.Tk, theme: str | None = None) -> dict[str, tuple]:
    """Apply a theme to the given root. Returns the fonts dict.

    Passing ``theme`` selects that palette first (unknown names fall back to
    the default). Safe to call repeatedly: ttk styles are reconfigured in
    place, so every ttk widget already on screen picks the new colors up.
    Classic Tk widgets don't — see ``retheme_widgets``.
    """
    if theme is not None:
        set_palette(theme)
    fonts = get_fonts(root)

    root.configure(bg=PALETTE["bg_window"])

    # Legacy Tk widgets (Listbox, Text, Canvas) don't pick up ttk styles —
    # set their defaults via the option database.
    root.option_add("*Listbox.background", PALETTE["bg_input"])
    root.option_add("*Listbox.foreground", PALETTE["text"])
    root.option_add("*Listbox.selectBackground", PALETTE["accent"])
    root.option_add("*Listbox.selectForeground", PALETTE["text_inverse"])
    root.option_add("*Listbox.borderWidth", 0)
    root.option_add("*Listbox.highlightThickness", 0)
    root.option_add("*Listbox.font", fonts["body"])
    root.option_add("*Listbox.activeStyle", "none")

    root.option_add("*Text.background", PALETTE["bg_input"])
    root.option_add("*Text.foreground", PALETTE["text"])
    root.option_add("*Text.insertBackground", PALETTE["accent"])
    root.option_add("*Text.selectBackground", PALETTE["accent_dim"])
    root.option_add("*Text.selectForeground", PALETTE["text"])
    root.option_add("*Text.borderWidth", 0)
    root.option_add("*Text.highlightThickness", 1)
    root.option_add("*Text.highlightBackground", PALETTE["border"])
    root.option_add("*Text.highlightColor", PALETTE["border_focus"])
    root.option_add("*Text.font", fonts["body"])

    style = ttk.Style(root)
    style.theme_use("clam")

    bg = PALETTE["bg_surface"]
    text = PALETTE["text"]
    accent = PALETTE["accent"]

    # ----- Frames ------------------------------------------------------------
    style.configure("TFrame", background=bg)
    style.configure("Window.TFrame", background=PALETTE["bg_window"])
    style.configure("Card.TFrame", background=PALETTE["bg_card"])
    style.configure("CardHover.TFrame", background=PALETTE["bg_card_hover"])
    style.configure("CardSel.TFrame", background=PALETTE["bg_card_sel"])
    style.configure("StatusBar.TFrame", background=PALETTE["bg_window"])

    # ----- Labels ------------------------------------------------------------
    style.configure(
        "TLabel",
        background=bg,
        foreground=text,
        font=fonts["body"],
    )
    style.configure(
        "Title.TLabel",
        background=PALETTE["bg_window"],
        foreground=PALETTE["text"],
        font=fonts["title"],
    )
    style.configure(
        "Subtitle.TLabel",
        background=PALETTE["bg_window"],
        foreground=PALETTE["text_muted"],
        font=fonts["small"],
    )
    style.configure(
        "Muted.TLabel",
        background=bg,
        foreground=PALETTE["text_muted"],
        font=fonts["body"],
    )
    style.configure(
        "Subtle.TLabel",
        background=bg,
        foreground=PALETTE["text_subtle"],
        font=fonts["small"],
    )
    style.configure(
        "Status.TLabel",
        background=PALETTE["bg_window"],
        foreground=PALETTE["text_muted"],
        font=fonts["small"],
    )
    style.configure(
        "Header.TLabel",
        background=bg,
        foreground=text,
        font=fonts["header"],
    )
    style.configure(
        "Accent.TLabel",
        background=bg,
        foreground=PALETTE["text_highlight"],
        font=fonts["bold"],
    )
    # Card-context labels.
    style.configure(
        "Card.TLabel",
        background=PALETTE["bg_card"],
        foreground=text,
        font=fonts["body"],
    )
    style.configure(
        "CardTitle.TLabel",
        background=PALETTE["bg_card"],
        foreground=text,
        font=fonts["bold"],
    )
    style.configure(
        "CardMuted.TLabel",
        background=PALETTE["bg_card"],
        foreground=PALETTE["text_muted"],
        font=fonts["body"],
    )
    style.configure(
        "CardSubtle.TLabel",
        background=PALETTE["bg_card"],
        foreground=PALETTE["text_subtle"],
        font=fonts["small"],
    )
    style.configure(
        "CardSel.TLabel",
        background=PALETTE["bg_card_sel"],
        foreground=text,
        font=fonts["body"],
    )
    style.configure(
        "CardSelTitle.TLabel",
        background=PALETTE["bg_card_sel"],
        foreground=PALETTE["text_highlight"],
        font=fonts["bold"],
    )
    style.configure(
        "CardSelMuted.TLabel",
        background=PALETTE["bg_card_sel"],
        foreground=PALETTE["text_muted"],
        font=fonts["body"],
    )
    style.configure(
        "CardSelSubtle.TLabel",
        background=PALETTE["bg_card_sel"],
        foreground=PALETTE["text_muted"],
        font=fonts["small"],
    )
    # Hover variant — used by slot cards on mouse-over.
    style.configure(
        "CardHoverTitle.TLabel",
        background=PALETTE["bg_card_hover"],
        foreground=text,
        font=fonts["bold"],
    )
    style.configure(
        "CardHoverMuted.TLabel",
        background=PALETTE["bg_card_hover"],
        foreground=PALETTE["text_muted"],
        font=fonts["body"],
    )
    style.configure(
        "CardHoverSubtle.TLabel",
        background=PALETTE["bg_card_hover"],
        foreground=PALETTE["text_subtle"],
        font=fonts["small"],
    )

    # ----- LabelFrame --------------------------------------------------------
    # Borderless — the colored label and bg-surface contrast against the
    # window already separate sections visually, no outline needed.
    style.configure(
        "TLabelframe",
        background=bg,
        bordercolor=bg,
        darkcolor=bg,
        lightcolor=bg,
        borderwidth=0,
        relief="flat",
    )
    style.configure(
        "TLabelframe.Label",
        background=bg,
        foreground=accent,
        font=fonts["bold"],
        padding=(4, 0),
    )

    # ----- Notebook ----------------------------------------------------------
    # Drop the focus ring (Notebook.focus) so we don't get a dotted box
    # around the active tab's text.
    style.layout("TNotebook.Tab", [
        ("Notebook.tab", {"sticky": "nswe", "children": [
            ("Notebook.padding", {"side": "top", "sticky": "nswe", "children": [
                ("Notebook.label", {"side": "top", "sticky": ""}),
            ]}),
        ]}),
    ])
    style.configure(
        "TNotebook",
        background=PALETTE["bg_window"],
        bordercolor=PALETTE["bg_window"],
        darkcolor=PALETTE["bg_window"],
        lightcolor=PALETTE["bg_window"],
        borderwidth=0,
        tabmargins=(12, 8, 12, 0),
    )
    style.configure(
        "TNotebook.Tab",
        background=PALETTE["bg_card"],
        foreground=PALETTE["text_muted"],
        bordercolor=PALETTE["bg_card"],
        darkcolor=PALETTE["bg_card"],
        lightcolor=PALETTE["bg_card"],
        padding=(16, 8),
        borderwidth=0,
        font=fonts["bold"],
    )
    # Selected tab is visually elevated: extra padding, blue-tinted bg,
    # bumped font. Hovered tab gets a subtle lift.
    style.map(
        "TNotebook.Tab",
        background=[
            ("selected", PALETTE["bg_card_sel"]),
            ("active", PALETTE["bg_card_hover"]),
        ],
        foreground=[
            ("selected", PALETTE["text"]),
            ("active", PALETTE["text"]),
        ],
        bordercolor=[
            ("selected", PALETTE["bg_card_sel"]),
            ("active", PALETTE["bg_card_hover"]),
        ],
        lightcolor=[
            ("selected", PALETTE["bg_card_sel"]),
            ("active", PALETTE["bg_card_hover"]),
        ],
        darkcolor=[
            ("selected", PALETTE["bg_card_sel"]),
            ("active", PALETTE["bg_card_hover"]),
        ],
        padding=[
            ("selected", (22, 12)),
        ],
        font=[
            ("selected", fonts["selected_tab"]),
        ],
        expand=[
            ("selected", (1, 1, 1, 0)),
        ],
    )

    # ----- Buttons -----------------------------------------------------------
    # Secondary buttons stay in the gray ladder — they lift on hover rather
    # than taking on a color, so the green/red action buttons keep their
    # meaning as the only saturated controls in the window.
    style.configure(
        "TButton",
        background=PALETTE["accent_dim"],
        foreground=text,
        bordercolor=PALETTE["accent_dim"],
        darkcolor=PALETTE["accent_dim"],
        lightcolor=PALETTE["accent_dim"],
        focuscolor=PALETTE["border_focus"],
        borderwidth=0,
        relief="flat",
        padding=(14, 7),
        font=fonts["body"],
    )
    _button_fill = [
        ("pressed", PALETTE["bg_card_sel"]),
        ("active", PALETTE["bg_card_hover"]),
        ("disabled", PALETTE["bg_surface"]),
    ]
    style.map(
        "TButton",
        background=_button_fill,
        bordercolor=_button_fill,
        darkcolor=_button_fill,
        lightcolor=_button_fill,
        foreground=[
            ("disabled", PALETTE["text_subtle"]),
            ("active", PALETTE["text_highlight"]),
        ],
    )

    # Primary / go button — the one colored control on most screens.
    _colored_button(
        style, "Accent.TButton", fonts,
        rest=PALETTE["action"],
        hover=PALETTE["action_hover"],
        press=PALETTE["action_press"],
    )

    # Update button — refreshing something already installed, as opposed to
    # the green "get me a new one" of a first download.
    _colored_button(
        style, "Update.TButton", fonts,
        rest=PALETTE["update"],
        hover=PALETTE["update_hover"],
        press=PALETTE["update_press"],
    )

    # Stop / destructive button — used while a run is active, and for Delete.
    _colored_button(
        style, "Danger.TButton", fonts,
        rest=PALETTE["danger"],
        hover=PALETTE["danger_hover"],
        press=PALETTE["danger_press"],
    )

    # ----- Entries / Spinboxes / Combobox -----------------------------------
    for widget in ("TEntry", "TSpinbox", "TCombobox"):
        style.configure(
            widget,
            fieldbackground=PALETTE["bg_input"],
            background=PALETTE["bg_input"],
            foreground=text,
            bordercolor=PALETTE["border"],
            darkcolor=PALETTE["border"],
            lightcolor=PALETTE["border"],
            insertcolor=accent,
            arrowcolor=PALETTE["text_muted"],
            padding=4,
        )
        style.map(
            widget,
            fieldbackground=[
                ("readonly", PALETTE["bg_input"]),
                ("disabled", PALETTE["bg_surface"]),
            ],
            foreground=[
                ("disabled", PALETTE["text_subtle"]),
            ],
            bordercolor=[("focus", PALETTE["border_focus"])],
            lightcolor=[("focus", PALETTE["border_focus"])],
            darkcolor=[("focus", PALETTE["border_focus"])],
            arrowcolor=[("active", accent)],
        )

    # Title-bar theme picker. Sits on the gradient rather than a panel, so it
    # borrows the card color to read as a control without drawing a border.
    _header_fill = PALETTE["bg_card"]
    style.configure(
        "Header.TCombobox",
        fieldbackground=_header_fill,
        background=_header_fill,
        foreground=text,
        bordercolor=_header_fill,
        darkcolor=_header_fill,
        lightcolor=_header_fill,
        arrowcolor=PALETTE["text_muted"],
        # Readonly comboboxes render their text through the selection colors;
        # matching them to the fill keeps the closed control from showing a
        # highlight bar whenever it holds focus.
        selectbackground=_header_fill,
        selectforeground=text,
        padding=(6, 2),
    )
    style.map(
        "Header.TCombobox",
        fieldbackground=[
            ("readonly", _header_fill),
            ("active", PALETTE["bg_card_hover"]),
        ],
        background=[("active", PALETTE["bg_card_hover"])],
        foreground=[("readonly", text)],
        selectbackground=[("readonly", _header_fill)],
        selectforeground=[("readonly", text)],
        bordercolor=[("focus", _header_fill)],
        lightcolor=[("focus", _header_fill)],
        darkcolor=[("focus", _header_fill)],
        arrowcolor=[("active", accent)],
    )

    # Combobox dropdown list (uses the option database).
    root.option_add("*TCombobox*Listbox.background", PALETTE["bg_card"])
    root.option_add("*TCombobox*Listbox.foreground", text)
    root.option_add("*TCombobox*Listbox.selectBackground", PALETTE["accent"])
    root.option_add("*TCombobox*Listbox.selectForeground", PALETTE["text_inverse"])
    root.option_add("*TCombobox*Listbox.borderWidth", 0)
    root.option_add("*TCombobox*Listbox.font", fonts["body"])

    # ----- Checkbutton / Radiobutton ----------------------------------------
    for widget in ("TCheckbutton", "TRadiobutton"):
        style.configure(
            widget,
            background=bg,
            foreground=text,
            focuscolor=accent,
            indicatorbackground=PALETTE["bg_input"],
            indicatorforeground=accent,
            indicatordiameter=12,
            font=fonts["body"],
            padding=2,
        )
        style.map(
            widget,
            background=[("active", bg)],
            indicatorbackground=[
                ("selected", accent),
                ("disabled", PALETTE["bg_surface"]),
            ],
            indicatorforeground=[
                ("selected", PALETTE["text_inverse"]),
            ],
            foreground=[
                ("disabled", PALETTE["text_subtle"]),
            ],
        )
    # Bold checkbutton — parent-group headers in the slot-details panel.
    style.configure(
        "Group.TCheckbutton",
        background=bg,
        foreground=text,
        focuscolor=accent,
        indicatorbackground=PALETTE["bg_input"],
        indicatorforeground=accent,
        indicatordiameter=12,
        font=fonts["bold"],
        padding=2,
    )
    style.map(
        "Group.TCheckbutton",
        background=[("active", bg)],
        indicatorbackground=[
            ("selected", accent),
            ("disabled", PALETTE["bg_surface"]),
        ],
        indicatorforeground=[("selected", PALETTE["text_inverse"])],
        foreground=[("disabled", PALETTE["text_subtle"])],
    )

    # Card-context check/radio that need to sit on PALETTE["bg_card"].
    for widget in ("Card.TCheckbutton", "Card.TRadiobutton"):
        style.configure(
            widget,
            background=PALETTE["bg_card"],
            foreground=text,
            focuscolor=accent,
            indicatorbackground=PALETTE["bg_input"],
            indicatorforeground=accent,
            font=fonts["body"],
        )
        style.map(
            widget,
            background=[("active", PALETTE["bg_card"])],
            indicatorbackground=[("selected", accent)],
            foreground=[("disabled", PALETTE["text_subtle"])],
        )

    # ----- Scale (slider) ---------------------------------------------------
    style.configure(
        "Horizontal.TScale",
        background=bg,
        troughcolor=PALETTE["bg_input"],
        sliderlength=18,
        bordercolor=PALETTE["border"],
        darkcolor=accent,
        lightcolor=accent,
        gripcount=0,
    )
    style.map(
        "Horizontal.TScale",
        background=[("active", bg)],
        troughcolor=[("active", PALETTE["bg_input"])],
    )

    # ----- Scrollbar --------------------------------------------------------
    for orient in ("Vertical.TScrollbar", "Horizontal.TScrollbar"):
        style.configure(
            orient,
            background=PALETTE["bg_card"],
            troughcolor=PALETTE["bg_window"],
            bordercolor=PALETTE["bg_window"],
            darkcolor=PALETTE["bg_card"],
            lightcolor=PALETTE["bg_card"],
            arrowcolor=PALETTE["text_muted"],
            borderwidth=0,
            relief="flat",
        )
        style.map(
            orient,
            background=[
                ("active", PALETTE["accent_dim"]),
                ("pressed", PALETTE["accent"]),
            ],
            arrowcolor=[("active", PALETTE["text"])],
        )

    # ----- Treeview ---------------------------------------------------------
    # Without an explicit style the clam Treeview renders light-grey, which
    # reads as a foreign element on the dark surface. Match the input fields.
    style.configure(
        "Treeview",
        background=PALETTE["bg_input"],
        fieldbackground=PALETTE["bg_input"],
        foreground=text,
        bordercolor=PALETTE["border"],
        darkcolor=PALETTE["bg_input"],
        lightcolor=PALETTE["bg_input"],
        borderwidth=0,
        relief="flat",
        rowheight=26,
        font=fonts["body"],
    )
    style.map(
        "Treeview",
        background=[("selected", PALETTE["accent"])],
        foreground=[("selected", PALETTE["text_inverse"])],
    )
    style.configure(
        "Treeview.Heading",
        background=PALETTE["bg_card"],
        foreground=PALETTE["text"],
        bordercolor=PALETTE["border"],
        darkcolor=PALETTE["bg_card"],
        lightcolor=PALETTE["bg_card"],
        relief="flat",
        padding=(8, 6),
        font=fonts["bold"],
    )
    style.map(
        "Treeview.Heading",
        background=[
            ("active", PALETTE["bg_card_hover"]),
            ("pressed", PALETTE["bg_card_sel"]),
        ],
        foreground=[("active", PALETTE["text"])],
    )

    # ----- Separator --------------------------------------------------------
    style.configure("TSeparator", background=PALETTE["border"])

    # ----- PanedWindow ------------------------------------------------------
    style.configure(
        "TPanedwindow",
        background=PALETTE["bg_window"],
    )
    style.configure(
        "Sash",
        background=PALETTE["bg_window"],
        bordercolor=PALETTE["bg_window"],
        gripcount=0,
        sashthickness=6,
    )

    return fonts


# Color options carried by the classic Tk widgets we build (Label, Frame,
# Canvas, Text, Listbox, Menu). ttk widgets don't accept these — their colors
# come from the styles above — so a TclError on cget just means "skip".
_WIDGET_COLOR_OPTIONS = (
    "background",
    "foreground",
    "activebackground",
    "activeforeground",
    "disabledforeground",
    "highlightbackground",
    "highlightcolor",
    "insertbackground",
    "selectbackground",
    "selectforeground",
    "selectcolor",
    "troughcolor",
    "readonlybackground",
)


def _reverse_map(previous: dict[str, str]) -> dict[str, str]:
    """Map each color of the outgoing palette to its counterpart in ``PALETTE``.

    Keys are visited in palette order, so when two roles share a color (e.g.
    ``success`` mirrors ``action``) the first one wins — which is why the
    palettes keep those pairs identical in every theme.
    """
    mapping: dict[str, str] = {}
    for key, old in previous.items():
        new = PALETTE.get(key)
        if new is None:
            continue
        mapping.setdefault(old.lower(), new)
    return mapping


def retheme_widgets(widget: tk.Misc, previous: dict[str, str]) -> None:
    """Re-colour classic Tk widgets after a theme switch.

    ttk widgets follow their style and update themselves; a ``tk.Label`` or
    ``tk.Canvas`` built with ``bg=PALETTE["bg_card"]`` keeps the literal color
    it was given. Rather than ask every module to register a callback, this
    walks the widget tree (including open Toplevels) and translates any color
    that came from the outgoing palette into the same role's new color.
    Anything the app set to a color of its own — the monitor's snake borders,
    for instance — isn't in the map and is left alone.
    """
    mapping = _reverse_map(previous)
    if not mapping:
        return
    _retheme_tree(widget, mapping)


def _retheme_tree(widget: tk.Misc, mapping: dict[str, str]) -> None:
    updates: dict[str, str] = {}
    for option in _WIDGET_COLOR_OPTIONS:
        try:
            value = str(widget.cget(option))
        except (tk.TclError, TypeError, AttributeError):
            continue
        new = mapping.get(value.lower())
        if new is not None and new.lower() != value.lower():
            updates[option] = new
    if updates:
        try:
            widget.configure(**updates)
        except tk.TclError:
            pass
    try:
        children = widget.winfo_children()
    except tk.TclError:
        return
    for child in children:
        _retheme_tree(child, mapping)


def paint_gradient(
    canvas: tk.Canvas,
    *,
    color_a: str,
    color_b: str,
    direction: str = "horizontal",
) -> None:
    """Paint a linear gradient across the canvas, replacing any prior gradient.

    Lines are tagged "gradient" so callers can repaint on resize by simply
    calling this function again.
    """
    canvas.delete("gradient")
    canvas.update_idletasks()
    width = canvas.winfo_width()
    height = canvas.winfo_height()
    if width < 2 or height < 2:
        return

    r1, g1, b1 = _hex_to_rgb(color_a)
    r2, g2, b2 = _hex_to_rgb(color_b)

    if direction == "horizontal":
        steps = width
        for i in range(steps):
            t = i / max(1, steps - 1)
            r = int(r1 + (r2 - r1) * t)
            g = int(g1 + (g2 - g1) * t)
            b = int(b1 + (b2 - b1) * t)
            canvas.create_line(
                i, 0, i, height,
                fill=f"#{r:02x}{g:02x}{b:02x}",
                tags="gradient",
            )
    else:
        steps = height
        for i in range(steps):
            t = i / max(1, steps - 1)
            r = int(r1 + (r2 - r1) * t)
            g = int(g1 + (g2 - g1) * t)
            b = int(b1 + (b2 - b1) * t)
            canvas.create_line(
                0, i, width, i,
                fill=f"#{r:02x}{g:02x}{b:02x}",
                tags="gradient",
            )
    canvas.tag_lower("gradient")


def paint_halftone(
    canvas: tk.Canvas,
    *,
    color: str | None,
    spacing: int = 7,
    radius: float = 2.0,
    fade_end: float = 0.8,
) -> None:
    """Print a ben-day dot field across the canvas, replacing any prior one.

    The dots shrink from full size at the left edge to nothing by `fade_end`
    (a fraction of the width), which is how a comic screens a flat colour into
    the ink beside it. Rows are offset by half a step so the field reads as a
    proper halftone screen rather than a grid.

    `color=None` just clears the field, so a caller can hand it whatever
    ``halftone_ink()`` returns without branching.
    """
    canvas.delete("halftone")
    if color is None:
        return
    canvas.update_idletasks()
    width = canvas.winfo_width()
    height = canvas.winfo_height()
    if width < 2 or height < 2:
        return

    span = max(1.0, width * fade_end)
    for row in range(int(height / spacing) + 2):
        y = row * spacing + spacing / 2
        offset = spacing / 2 if row % 2 else 0.0
        for col in range(int(width / spacing) + 2):
            x = col * spacing + offset
            r = radius * (1.0 - x / span)
            if r < 0.6:
                break  # everything further right is smaller still
            canvas.create_oval(
                x - r, y - r, x + r, y + r,
                fill=color, outline="", tags="halftone",
            )


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
