"""The training log's header, run for real (#100).

`tests/unit/training/test_training_banner.py` reads the trainer's source, which
is all that is possible where torch is absent by design. This runs the two
functions, which is the only way to find out that they raise — `_describe_device`
touches `torch.version`, `torch.backends.cudnn` and, on a GPU box, four
`torch.cuda` calls that do not exist on a CPU build.

Skips without torch, like every other integration test skips without its tool.
The CUDA branch only runs where there is a CUDA device; on this project's CI
there never is, so that half is verified by whoever has the hardware.
"""

from __future__ import annotations

import argparse

import pytest

pytestmark = [pytest.mark.integration]

torch = pytest.importorskip("torch", reason="needs the [ml] extra")
pytest.importorskip("torchvision", reason="needs the [ml] extra")

from sorter.training.train_convnext import _describe_config, _describe_device  # noqa: E402


def _args(**overrides) -> argparse.Namespace:
    base = dict(
        model_name="convnext_small",
        epochs=12,
        batch_size=8,
        lr=0.0002,
        weight_decay=0.0001,
        dropout=0.0,
        val_split=0.2,
        trainall=True,
        imgsize=480,
        freeze_backbone=False,
        use_focal_loss=False,
        focal_gamma=1.0,
        stochastic_depth_prob=-1.0,
        use_swa=False,
        swa_start=0.75,
        swa_mode="scheduled",
    )
    base.update(overrides)
    return argparse.Namespace(**base)


def test_the_environment_block_names_the_stack_and_the_device() -> None:
    lines = _describe_device(torch.device("cpu"))
    text = "\n".join(lines)

    assert str(torch.__version__) in text
    assert "[INFO] Device: CPU" in text
    assert "CUDA available:" in text
    # The CPU branch has to say so — a four-hour run on the CPU is the single
    # most useful thing this block can tell someone.
    assert "much slower" in text


def test_the_device_block_matches_the_device_it_is_given() -> None:
    if not torch.cuda.is_available():
        pytest.skip("no CUDA device on this machine")
    text = "\n".join(_describe_device(torch.device("cuda")))
    assert "[INFO] Device: CUDA" in text
    assert "Detected GPU:" in text
    assert "compute sm_" in text


def test_the_configuration_block_reads_like_the_windows_apps() -> None:
    lines = _describe_config(_args())

    assert lines[0] == "[INFO] Configuration:"
    body = "\n".join(lines[1:])
    assert "Model: convnext_small" in body
    assert "Batch Size: 8" in body
    assert "Image Size: 480x480" in body
    assert "Full Dataset Training: True" in body
    assert "Target Epochs: 12" in body
    # Every line under the heading is indented, as the Windows app's is.
    assert all(line.startswith("       ") for line in lines[1:])


def test_the_optional_features_read_as_off_rather_than_vanishing() -> None:
    """Absence has to be visible: "SWA: False" answers a question, a missing
    line just looks like the log is incomplete."""
    body = "\n".join(_describe_config(_args()))
    assert "Focal Loss: False" in body
    assert "SWA: False" in body
    assert "Stochastic Depth: torchvision default" in body

    on = "\n".join(_describe_config(_args(use_swa=True, use_focal_loss=True, stochastic_depth_prob=0.2)))
    assert "SWA: from 75% (scheduled)" in on
    assert "Focal Loss: gamma 1.0" in on
    assert "Stochastic Depth: 0.2" in on
