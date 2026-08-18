"""A real checkpoint round trip: the payload stays readable under `weights_only`.

`tests/unit/ml/test_checkpoint_env.py` pins the invariant by reading the
trainer's source, which is all that is possible where torch is absent by design
(the `[ml]` extra). This is the other half, and the only one that can actually
prove it: with torch installed, write the payload the trainer writes and open it
the way `local_inference._load` does.

The two failures it exists to catch both look like nothing until a user hits
them — a value torch's `weights_only=True` allowlist refuses (the checkpoint
becomes unopenable everywhere), and a numpy object slipping in (it opens fine
here and raises `ModuleNotFoundError: numpy._core` on anyone running numpy 1.x).
See issue #77.

Skips when torch isn't installed, like every other integration test skips
without its external tool.
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.integration]

torch = pytest.importorskip("torch", reason="needs the [ml] extra")
pytest.importorskip("torchvision", reason="needs the [ml] extra")

from sorter.ml.local_inference import checkpoint_env as read_env  # noqa: E402
from sorter.training.train_convnext import checkpoint_env  # noqa: E402


def _payload() -> dict:
    """The trainer's payload shape, with a one-parameter stand-in state_dict."""
    return {
        "model_state_dict": {"classifier.2.weight": torch.zeros(2, 3)},
        "classes": ["9mm FC", "223 REM"],
        "base": "convnext_tiny",
        "image_size": 480,
        "val_acc": 0.94,
        "val_loss": 0.21,
        **checkpoint_env(),
    }


def test_the_env_helper_reports_the_running_stack() -> None:
    env = checkpoint_env()

    assert env["torch_version"] == str(torch.__version__)
    assert set(env) == {"torch_version", "torchvision_version", "numpy_version"}
    assert all(isinstance(value, str) and value for value in env.values())


def test_the_payload_round_trips_under_weights_only(tmp_path) -> None:
    path = tmp_path / "model.pth"
    torch.save(_payload(), path)

    # Exactly how `_load` opens an untrusted checkpoint. A value outside
    # torch's allowlist fails here, which is the point.
    loaded = torch.load(str(path), map_location="cpu", weights_only=True)

    assert loaded["classes"] == ["9mm FC", "223 REM"]
    assert read_env(loaded) == checkpoint_env()


def test_every_value_is_a_tensor_or_a_python_primitive(tmp_path) -> None:
    """numpy 2 renamed `numpy.core`, and `weights_only=True` permits arrays —
    so a numpy value here loads fine and breaks on numpy 1.x machines only.

    Checked after a real save/load rather than on the dict we built, so a type
    torch converts on the way through is caught as what comes back out.
    """
    path = tmp_path / "model.pth"
    torch.save(_payload(), path)
    loaded = torch.load(str(path), map_location="cpu", weights_only=True)

    def _check(value: object, where: str) -> None:
        if isinstance(value, torch.Tensor):
            return
        if isinstance(value, str | int | float | bool | type(None)):
            assert type(value).__module__ == "builtins", f"{where}: {type(value)!r} is not a Python primitive"
            return
        if isinstance(value, dict):
            for key, item in value.items():
                _check(key, f"{where}.{key}")
                _check(item, f"{where}.{key}")
            return
        if isinstance(value, list | tuple):
            for i, item in enumerate(value):
                _check(item, f"{where}[{i}]")
            return
        raise AssertionError(f"{where}: {type(value)!r} is neither a tensor nor a Python primitive")

    _check(loaded, "payload")
