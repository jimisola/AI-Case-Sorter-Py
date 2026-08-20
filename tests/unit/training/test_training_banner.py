"""The training log's header block, read out of the trainer's source (#100).

`train_convnext.py` imports torch at module scope — deliberately, so its
Dataset classes can be pickled by Windows `spawn` workers — so this environment
cannot import it. What it *can* do is read it, which is enough to pin the thing
that actually rots: the configuration block quietly falling behind the settings
the Train page can send.

`tests/integration/test_training_banner.py` runs the same functions for real
where torch exists.
"""

from __future__ import annotations

import ast
from pathlib import Path

import sorter.training

# What the log has to state about a run, mirroring the block the Windows app
# prints (issue #100). A new training knob that reaches the trainer belongs
# here too — that is the whole point of the check below.
EXPECTED_CAPTIONS = {
    "Model",
    "Batch Size",
    "Initial LR",
    "Weight Decay",
    "Dropout",
    "Validation Split",
    "Full Dataset Training",
    "Image Size",
    "Freeze Backbone",
    "Focal Loss",
    "Stochastic Depth",
    "SWA",
    "Target Epochs",
}

# Every trainer argument, and where it shows up in the log. A new `--flag` has
# to be added to one side or the other, which is what makes the block hard to
# forget.
REPORTED_ARGS = {
    "--model_name",
    "--epochs",
    "--batch_size",
    "--lr",
    "--weight_decay",
    "--dropout",
    "--val_split",
    "--trainall",
    "--imgsize",
    "--freeze_backbone",
    "--use_focal_loss",
    "--focal_gamma",
    "--stochastic_depth_prob",
    "--use_swa",
    "--swa_start",
    "--swa_mode",
}
UNREPORTED_ARGS = {
    # Paths: the log is shared, and `manager` writes the command line into it
    # anyway — with the data root still in it, which the support bundle redacts.
    "--image_dir",
    "--output_model",
    # Reported by `main` itself, from the resolved value rather than the flag
    # (-1 means "decide from the CPU count").
    "--max_workers",
    # SWA scheduling detail: only meaningful once SWA is on, and the SWA line
    # already says when it starts and in which mode.
    "--swa_acc_threshold",
    "--swa_patience",
    "--swa_min_epoch",
}


def _tree() -> ast.Module:
    path = Path(sorter.training.__file__).parent / "train_convnext.py"
    return ast.parse(path.read_text(encoding="utf-8"))


def _function(name: str) -> ast.FunctionDef:
    for node in ast.walk(_tree()):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name}() is gone — did the banner move?")


def _captions() -> set[str]:
    """The left-hand labels of `_describe_config`'s settings list."""
    found = set()
    for node in ast.walk(_function("_describe_config")):
        if isinstance(node, ast.Tuple) and node.elts:
            first = node.elts[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                found.add(first.value)
    return found


def test_the_configuration_block_reports_every_expected_setting() -> None:
    assert EXPECTED_CAPTIONS <= _captions()


def test_every_trainer_argument_is_either_reported_or_listed_as_not() -> None:
    """A new `--flag` has to be added to the log, or excused here in writing."""
    flags: set[str] = set()
    for node in ast.walk(_tree()):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            flags.add(node.args[0].value)

    accounted = REPORTED_ARGS | UNREPORTED_ARGS
    assert flags == accounted, f"trainer options not accounted for in the log header: {sorted(flags ^ accounted)}"


def test_the_header_is_printed_before_the_dataset_is_loaded() -> None:
    """A log that opens with the failure says nothing about what was running."""
    main = _function("main")
    source = ast.unparse(main)
    header = source.index("_describe_device")
    dataset = source.index("FilenameLabelDataset")
    assert header < dataset
