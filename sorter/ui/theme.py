"""Modern dark theme for the OSS Client UI.

Centralises colors, fonts, and ttk styles so the rest of the app can stay
focused on layout. The chrome — window, panels, cards, inputs, borders,
text — is **neutral grayscale**: a flat luminance ladder that gives the UI
depth without bevels, relief, or a hue of its own. Color is reserved for
things that mean something: action buttons (green = go / primary,
red = stop / destructive) and status text (success / warning / error).
Keeping the surfaces colorless means a green Start or a red Stop is the
only saturated thing on screen, so it reads instantly.

Two helpers are exported:

* ``apply_theme(root)`` — call once after the root is created. Applies
  ttk styles, sets default fonts on the legacy Tk widgets (Listbox / Text
  / Canvas), and returns the resolved fonts dict for callers that need to
  match.
* ``paint_gradient(canvas, ...)`` — paint a vertical/horizontal linear
  gradient across the canvas. Used for the title bar.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk


# Color palette — single source of truth.
#
# Everything above the "Action colors" block is neutral gray (R == G == B):
# surfaces, borders, text, and the selection/focus tints. Only the action
# and status entries carry hue. If you add a color here, ask which of the
# two groups it belongs to — a new tinted surface breaks the contrast the
# colored buttons rely on.
PALETTE = {
    # Backgrounds — neutral gray, darkest to lightest.
    "bg_window":     "#131313",   # app background / gradient bottom
    "bg_gradient_a": "#2e2e2e",   # title bar left
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
    "text_inverse":  "#131313",   # for text on light/action backgrounds

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

    # Status colors — text and small indicators.
    "success":       "#22c55e",
    "success_dim":   "#14331f",   # muted green fill — e.g. applied auto-suggestions
    "warning":       "#f59e0b",
    "error":         "#ef4444",
}


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


def apply_theme(root: tk.Tk) -> dict[str, tuple]:
    """Apply the modern dark theme to the given root. Returns the fonts dict."""
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


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
