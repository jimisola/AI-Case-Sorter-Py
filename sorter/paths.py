"""File-system locations.

The app is intentionally portable: everything it writes lives inside
``<app folder>/data/``, next to ``main.py``. Delete the folder, delete the
state. Layout:

    <app>/
    └── data/
        ├── config/
        │   ├── casesorter.db    ← SQLite database
        │   └── msal_cache.bin   ← MSAL token cache (chmod 0600 on POSIX)
        └── models/
            └── <model_id>/
                ├── images/          ← raw training images
                ├── run_images/      ← images captured during a run (opt-in)
                ├── feedback_images/ ← below-threshold community feedback queue
                ├── reports/         ← evaluator HTML reports
                └── trainedmodel/    ← <model_id>.pth (PyTorch zip archive)

A ``CASESORTER_DATA_DIR`` env var overrides the data root — used by tests
and operators who want the data on a different volume.
"""
from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "CaseSorter"


def _app_root() -> Path:
    """App folder (one level above ``sorter/``)."""
    return Path(__file__).resolve().parent.parent


def app_data_dir() -> Path:
    """Root for everything the app writes. Default: ``<app>/data``."""
    override = os.environ.get("CASESORTER_DATA_DIR")
    if override:
        return Path(override).expanduser()
    return _app_root() / "data"


def config_dir() -> Path:
    return app_data_dir() / "config"


def db_path() -> Path:
    return config_dir() / "casesorter.db"


def token_cache_path() -> Path:
    return config_dir() / "msal_cache.bin"


def models_dir() -> Path:
    """Root for all per-model folders."""
    return app_data_dir() / "models"


def export_temp_dir() -> Path:
    """App-local scratch folder for model export/share ZIPs.

    Kept inside the app's own data directory rather than the OS temp dir,
    which on Windows can be locked, cleaned mid-write, or otherwise
    unavailable. Created on demand by callers.
    """
    return app_data_dir() / "tmp"


def model_dir(model_id: int) -> Path:
    return models_dir() / str(model_id)


def model_images_dir(model_id: int) -> Path:
    return model_dir(model_id) / "images"


def model_run_images_dir(model_id: int) -> Path:
    """Where the run screen's optional 'Store Images' feature writes captures."""
    return model_dir(model_id) / "run_images"


def model_feedback_dir(model_id: int) -> Path:
    """Where below-threshold community feedback-loop captures are staged.

    This folder IS the feedback queue: files are uploaded then deleted (or
    dropped on failure). No database row mirrors them — polling this small
    folder is the source of truth for the OnRunComplete / Manual modes.
    """
    return model_dir(model_id) / "feedback_images"


def model_reports_dir(model_id: int) -> Path:
    """Where the model evaluator writes its HTML reports."""
    return model_dir(model_id) / "reports"


def model_trained_dir(model_id: int) -> Path:
    return model_dir(model_id) / "trainedmodel"


def model_trained_path(model_id: int) -> Path:
    """Conventional file path for the trained model checkpoint."""
    return model_trained_dir(model_id) / f"{model_id}.pth"


def ensure_directories() -> None:
    """Create every top-level directory if missing. Safe to call repeatedly."""
    for d in (app_data_dir(), config_dir(), models_dir()):
        d.mkdir(parents=True, exist_ok=True)


def ensure_model_subtree(model_id: int) -> None:
    """Create the `<model_id>/images` and `<model_id>/trainedmodel` dirs."""
    model_images_dir(model_id).mkdir(parents=True, exist_ok=True)
    model_trained_dir(model_id).mkdir(parents=True, exist_ok=True)
