"""Case Sorter Open Source Client package."""

# Single source of truth for the app version. `pyproject.toml` reads it via
# `[tool.setuptools.dynamic]`, and `sorter/updater.py` compares it against the
# latest GitHub release tag. Bump it in the same commit you tag a release.
__version__ = "0.1.0"
