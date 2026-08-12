"""Context-aware in-app help: renders ``docs/guide/*.md``, GitHub and in-app alike.

Single-source-of-truth docs: the same Markdown GitHub renders for
``docs/guide/`` is loaded here via ``QTextBrowser.setSource`` — verified in
PySide6 6.11.1 to auto-detect and render ``.md`` files with no extra
dependency, including relative links between pages (``setSearchPaths``) and
the browser's own back/forward history.

One gap found: Qt's markdown-to-richtext conversion never emits a named HTML
anchor for a heading — checked against ``QTextDocument.toHtml()``, and even a
literal ``<a name="...">`` written into the Markdown source doesn't survive
the conversion — so ``QTextBrowser.scrollToAnchor`` never has anything to
find (confirmed it *does* work, against a document built with real anchors
via ``setHtml``; the gap is specifically the Markdown path). Anchors are
resolved by hand instead: walk the rendered document's blocks for a heading
whose GitHub-style slug matches, then move the cursor there —
``setTextCursor`` alone was enough to scroll the view in this Qt build;
``ensureCursorVisible`` is kept as a belt-and-braces call.

``topic_for`` is the seam the app shell binds to F1 / Help menu: it turns
"where the user currently is" into a topic string this viewer understands.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QUrl  # ty: ignore[unresolved-import]
from PySide6.QtGui import QTextCursor  # ty: ignore[unresolved-import]
from PySide6.QtWidgets import (  # ty: ignore[unresolved-import]
    QHBoxLayout,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ..paths import app_root

DEFAULT_TOPIC = "index"

# page name -> topic, for pages whose topic doesn't depend on anything else.
# "Settings" isn't here: its topic also depends on settings_section.
_PAGE_TOPICS = {"Sort": "sort"}

_SLUG_STRIP_RE = re.compile(r"[^\w\s-]")
_SLUG_SPACE_RE = re.compile(r"\s+")


def _slugify(text: str) -> str:
    """GitHub-style heading anchor: lowercase, spaces to hyphens, punctuation dropped."""
    text = _SLUG_STRIP_RE.sub("", text.strip().lower())
    return _SLUG_SPACE_RE.sub("-", text)


def topic_for(page_name: str, settings_section: str | None = None) -> str:
    """Map the shell's current location to a help topic (``"page"`` or ``"page#anchor"``).

    A page this guide doesn't document yet falls back to the index rather
    than erroring — F1 should always open *something* useful.
    """
    if page_name == "Settings":
        return f"settings#{_slugify(settings_section)}" if settings_section else "settings"
    return _PAGE_TOPICS.get(page_name, DEFAULT_TOPIC)


class HelpWindow(QWidget):
    """Non-modal Markdown viewer over ``docs/guide/``. Caller owns the single instance."""

    def __init__(self, parent: QWidget | None = None, *, docs_root: Path | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle("AI Case Sorter Help")
        self.resize(640, 520)
        self._docs_root = docs_root if docs_root is not None else app_root() / "docs" / "guide"

        column = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        self._back_button = QPushButton("< Back", self)
        self._back_button.setEnabled(False)
        toolbar.addWidget(self._back_button)
        toolbar.addStretch(1)
        column.addLayout(toolbar)

        self.browser = QTextBrowser(self)
        # We route every navigation through show_topic ourselves (anchors need
        # the hand-rolled scroll above); Qt's own auto-open would bypass it.
        self.browser.setOpenLinks(False)
        self.browser.setSearchPaths([str(self._docs_root)])
        column.addWidget(self.browser, 1)

        self._back_button.clicked.connect(self.browser.backward)
        self.browser.backwardAvailable.connect(self._back_button.setEnabled)
        self.browser.anchorClicked.connect(self._on_anchor_clicked)

        self.show_topic(DEFAULT_TOPIC)

    # ----- navigation -----------------------------------------------------

    @property
    def current_page(self) -> str:
        """The page actually on screen, read off the browser rather than tracked by hand.

        Backward/forward navigate the browser's own history without going
        through ``show_topic``, so anything we tracked ourselves would go
        stale the moment a user clicks Back.
        """
        return Path(self.browser.source().toLocalFile()).stem or DEFAULT_TOPIC

    def show_topic(self, topic: str) -> None:
        """Load ``page`` (or ``page#anchor``); an unknown page falls back to index."""
        page, _, anchor = topic.partition("#")
        page = page or DEFAULT_TOPIC
        path = self._docs_root / f"{page}.md"
        if not path.is_file():
            path = self._docs_root / f"{DEFAULT_TOPIC}.md"
        self.browser.setSource(QUrl.fromLocalFile(str(path)))
        if anchor:
            self._scroll_to_anchor(anchor)

    def _scroll_to_anchor(self, anchor: str) -> bool:
        """Find the heading whose slug matches and move the cursor there.

        ``scrollToAnchor`` can't do this for a Markdown-loaded document — see
        the module docstring.
        """
        block = self.browser.document().begin()
        while block.isValid():
            if block.blockFormat().headingLevel() > 0 and _slugify(block.text()) == anchor:
                self.browser.setTextCursor(QTextCursor(block))
                self.browser.ensureCursorVisible()
                return True
            block = block.next()
        return False

    def _on_anchor_clicked(self, url: QUrl) -> None:
        """Route an internal link back through ``show_topic`` so anchors keep working.

        A real click resolves relative to the current page, so ``url`` is an
        absolute ``file://`` path (its stem is the target page) plus whatever
        fragment the link carried — including a same-page ``#anchor`` link,
        which Qt resolves against the current document's own path.
        """
        if url.scheme() not in ("", "file"):
            return  # an external link (http, mailto, ...): not ours to open
        local_path = url.toLocalFile()
        page = Path(local_path).stem if local_path else self.current_page
        anchor = url.fragment()
        self.show_topic(f"{page}#{anchor}" if anchor else page)


def build_help_window(win: Any, *, docs_root: Path | None = None) -> HelpWindow:
    """The app shell's single entry point — one instance, caller manages it."""
    return HelpWindow(win, docs_root=docs_root)
