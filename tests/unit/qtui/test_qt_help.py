"""In-app help viewer: topic mapping, Markdown rendering, and doc integrity.

Offscreen, no display. ``show_topic``/anchor-click tests load the REAL
``docs/guide/`` files — that's the point: they double as an end-to-end proof
that the same Markdown GitHub renders also renders (and navigates) inside the
app. The docs-integrity test is the other half of that guarantee: every
relative link and anchor in ``docs/guide`` has to actually resolve, or
GitHub's rendering and the in-app rendering would silently disagree.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QUrl

from sorter.qtui.help_viewer import HelpWindow, _slugify, build_help_window, topic_for

DOCS_GUIDE = Path(__file__).resolve().parents[3] / "docs" / "guide"


def _pump(qapp) -> None:
    qapp.processEvents()


# ----- topic_for ------------------------------------------------------------


@pytest.mark.parametrize(
    ("page_name", "settings_section", "expected"),
    [
        ("Sort", None, "sort"),
        ("Settings", "Serial", "settings#serial"),
        ("Settings", "Camera", "settings#camera"),
        ("Settings", "Image Processing", "settings#image-processing"),
        ("Settings", None, "settings"),
        ("Train", None, "index"),
        ("Models", None, "index"),
        ("Community", None, "index"),
        ("", None, "index"),
        ("Sort", "Serial", "sort"),  # non-Settings pages ignore the section arg
    ],
)
def test_topic_for_maps_location_to_topic(page_name, settings_section, expected) -> None:
    assert topic_for(page_name, settings_section) == expected


# ----- show_topic against the real docs --------------------------------------


@pytest.fixture
def help_window(qapp):
    window = HelpWindow(None)
    window.resize(320, 140)  # small viewport: anchor scroll tests need real overflow
    window.show()
    yield window
    window.close()


def test_show_topic_loads_real_sort_page(help_window, qapp) -> None:
    help_window.show_topic("sort")
    _pump(qapp)
    assert "Sort dashboard" in help_window.browser.toPlainText()
    assert help_window.current_page == "sort"


def test_show_topic_loads_real_settings_page(help_window, qapp) -> None:
    help_window.show_topic("settings")
    _pump(qapp)
    text = help_window.browser.toPlainText()
    assert "Serial" in text
    assert "Camera" in text


def test_unknown_topic_falls_back_to_index(help_window, qapp) -> None:
    help_window.show_topic("this-topic-does-not-exist")
    _pump(qapp)
    assert help_window.current_page == "index"
    assert "Qt UI Guide" in help_window.browser.toPlainText()


def test_anchor_scroll_actually_moves(help_window, qapp) -> None:
    help_window.show_topic("settings")
    _pump(qapp)
    top_scroll = help_window.browser.verticalScrollBar().value()

    help_window.show_topic("settings#camera")
    _pump(qapp)
    camera_scroll = help_window.browser.verticalScrollBar().value()

    # "## Camera" is the later heading, so jumping to it must scroll further
    # down than the untouched top of the same page.
    assert camera_scroll > top_scroll


def test_clicking_a_relative_link_navigates_to_the_other_page(help_window, qapp) -> None:
    help_window.show_topic("index")
    _pump(qapp)

    # "Trigger anchorClicked programmatically" — the URL a real click on
    # `[Settings → Serial](settings.md#serial)` resolves to: an absolute
    # file:// path plus the fragment, exactly as verified against a live
    # QTest.mouseClick in the exploration for this module.
    target = QUrl.fromLocalFile(str(DOCS_GUIDE / "settings.md"))
    target.setFragment("serial")
    help_window._on_anchor_clicked(target)
    _pump(qapp)

    assert help_window.current_page == "settings"
    assert "Serial" in help_window.browser.toPlainText()


def test_back_button_returns_to_the_previous_page(help_window, qapp) -> None:
    help_window.show_topic("index")
    _pump(qapp)
    help_window.show_topic("sort")
    _pump(qapp)
    assert help_window.current_page == "sort"
    assert help_window._back_button.isEnabled()

    help_window._back_button.click()
    _pump(qapp)

    # current_page reads the browser's own source, not a hand-tracked field,
    # specifically so Back (which bypasses show_topic) reports correctly.
    assert help_window.current_page == "index"


def test_build_help_window_returns_a_working_viewer(qapp) -> None:
    window = build_help_window(None)
    try:
        window.show()
        _pump(qapp)
        assert "Qt UI Guide" in window.browser.toPlainText()
    finally:
        window.close()


# ----- docs-root override (tests must not depend on the real docs/) ---------


def test_docs_root_override_reads_tmp_files(qapp, tmp_path) -> None:
    (tmp_path / "index.md").write_text("# Tmp Index\n\n[Elsewhere](elsewhere.md#target)\n")
    (tmp_path / "elsewhere.md").write_text("# Elsewhere\n\n## Target\n\nfound it\n")

    window = HelpWindow(None, docs_root=tmp_path)
    window.resize(320, 140)
    window.show()
    try:
        _pump(qapp)
        assert "Tmp Index" in window.browser.toPlainText()

        window.show_topic("elsewhere#target")
        _pump(qapp)
        assert window.current_page == "elsewhere"
        assert "found it" in window.browser.toPlainText()
    finally:
        window.close()


def test_docs_root_override_falls_back_to_its_own_index(qapp, tmp_path) -> None:
    (tmp_path / "index.md").write_text("# Only Page\n\nNothing else here.\n")

    window = HelpWindow(None, docs_root=tmp_path)
    window.show()
    try:
        _pump(qapp)
        window.show_topic("nope")
        _pump(qapp)
        assert "Only Page" in window.browser.toPlainText()
    finally:
        window.close()


# ----- docs integrity: every link and anchor in docs/guide resolves ---------

_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$", re.MULTILINE)


def _headings(text: str) -> set[str]:
    return {_slugify(m.group(2)) for m in _HEADING_RE.finditer(text)}


def _md_files() -> list[Path]:
    assert DOCS_GUIDE.is_dir(), f"expected {DOCS_GUIDE} to exist"
    return sorted(DOCS_GUIDE.glob("*.md"))


@pytest.mark.parametrize("md_file", _md_files(), ids=lambda p: p.name)
def test_every_relative_link_and_anchor_resolves(md_file: Path) -> None:
    text = md_file.read_text()
    for link in _LINK_RE.findall(text):
        if link.startswith(("http://", "https://", "mailto:")):
            continue  # not ours to validate
        page, _, anchor = link.partition("#")

        target = DOCS_GUIDE / page if page else md_file
        assert target.is_file(), f"{md_file.name}: link {link!r} has no target file"

        if anchor:
            target_headings = _headings(target.read_text())
            assert anchor in target_headings, (
                f"{md_file.name}: link {link!r}'s anchor {anchor!r} matches no "
                f"heading in {target.name} (have {sorted(target_headings)})"
            )
