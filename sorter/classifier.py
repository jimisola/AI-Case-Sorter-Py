"""Dispatcher: pick local PyTorch inference or HTTP classify based on active model.

Called from `RunController` so the run loop doesn't need to know which backend
is active. Routing:
  - Active model has a `model_path` pointing to an existing file → local
  - Otherwise → HTTP via `api_client.classify`

`active_local_model` / `uses_local_inference` expose that routing decision on
its own so the UI can answer "is this action about to need PyTorch?" *before*
starting a run, without duplicating the rule. Keep them and `classify_active`
in lock-step — a gate that disagrees with the dispatcher either nags AI Config
users or lets a run die mid-feed.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from . import api_client, local_inference
from .db import Database
from .models import Model
from .repository import ModelRepo, SettingsRepo


def model_uses_local_inference(model: Model | None) -> bool:
    """True when `model` would be classified by local PyTorch inference."""
    return bool(
        model is not None
        and model.model_path
        and Path(model.model_path).exists()
    )


def active_local_model(db: Database | None) -> Model | None:
    """The active model iff it routes to local inference, else None.

    None covers every HTTP case: no database, AI Config mode (no active
    model), and an active model whose checkpoint is missing or not yet
    trained.
    """
    if db is None:
        return None
    active_id = SettingsRepo(db).get_active_model_id()
    if active_id is None:
        return None
    model = ModelRepo(db).get(active_id)
    return model if model_uses_local_inference(model) else None


def uses_local_inference(db: Database | None) -> bool:
    """True when the next `classify_active` call will need PyTorch."""
    return active_local_model(db) is not None


def classify_active(
    image_bgr: np.ndarray,
    headstamps: list[str],
    api_cfg: dict[str, Any],
    db: Database | None,
) -> tuple[str, float]:
    """Classify `image_bgr` using whichever backend the active model selects.

    Falls back to HTTP if `db` is None (used in tests that don't need
    a database).
    """
    model = active_local_model(db)
    if model is not None:
        # Pass the trained image size from the model record so imported
        # community models (often trained at 480) get the right resolution
        # at inference.
        image_size = (
            int(model.training_config.image_size)
            if model.training_config else None
        )
        return local_inference.classify(
            image_bgr, model.model_path, image_size=image_size,
        )

    return api_client.classify(image_bgr, headstamps, api_cfg)
