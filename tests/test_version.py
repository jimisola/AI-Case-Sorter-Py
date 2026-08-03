"""Tests for sorter.__version__'s three-way fallback chain.

The logic runs at import time (a module-level try/except in
sorter/__init__.py, the standard hatch-vcs idiom), so each branch is
exercised by controlling what's importable and reloading the module --
not by calling a function. Whatever sorter/_version.py happens to exist on
disk when the suite runs (a real build leaves one; it's gitignored, so its
presence is not guaranteed) is deliberately not relied on either way --
every test controls its own inputs via sys.modules and monkeypatch.
"""

from __future__ import annotations

import importlib
import sys
from importlib.metadata import PackageNotFoundError
from types import ModuleType

import pytest

import sorter


@pytest.fixture(autouse=True)
def _restore_sorter_after():
    """Reloading sorter mutates real global state (sys.modules); always put
    it back to a normal, real import afterward so later tests in the same
    process see the genuine module, not a test's stand-in."""
    yield
    sys.modules.pop("sorter._version", None)
    importlib.reload(sorter)


def test_prefers_the_generated_version_file(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_version_module = ModuleType("sorter._version")
    fake_version_module.__version__ = "1.2.3"
    monkeypatch.setitem(sys.modules, "sorter._version", fake_version_module)

    importlib.reload(sorter)

    assert sorter.__version__ == "1.2.3"


def test_falls_back_to_installed_package_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "sorter._version", None)  # import sorter._version -> ImportError
    monkeypatch.setattr("importlib.metadata.version", lambda _name: "4.5.6")

    importlib.reload(sorter)

    assert sorter.__version__ == "4.5.6"


def test_falls_back_to_a_literal_placeholder_when_nothing_is_available(monkeypatch: pytest.MonkeyPatch) -> None:
    """The genuine "never built, never installed" case -- a plain git clone
    with `uv run python main.py` and no build ever having happened."""
    monkeypatch.setitem(sys.modules, "sorter._version", None)

    def _raise(_name: str) -> str:
        raise PackageNotFoundError("ai-case-sorter-py")

    monkeypatch.setattr("importlib.metadata.version", _raise)

    importlib.reload(sorter)

    assert sorter.__version__ == "0.0.0+unknown"
