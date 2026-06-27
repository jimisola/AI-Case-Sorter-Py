"""Tests for the training dataset helpers."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from sorter.training.dataset import (
    class_counts,
    dotnet_ticks,
    parse_label,
    save_training_image,
    training_filename,
)


def test_dotnet_ticks_for_known_date() -> None:
    """`new DateTime(2026,1,1,0,0,0,DateTimeKind.Utc).Ticks` == 639_028_224_000_000_000."""
    when = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    assert dotnet_ticks(when) == 639_028_224_000_000_000


def test_dotnet_ticks_at_unix_epoch_matches_known_offset() -> None:
    """1970-01-01 UTC must produce exactly the .NET Unix-epoch ticks constant."""
    when = datetime(1970, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    assert dotnet_ticks(when) == 621_355_968_000_000_000


def test_filename_round_trip() -> None:
    fname = training_filename("Federal_45ACP")
    assert "__" in fname
    assert parse_label(fname) == "Federal_45ACP"


def test_parse_label_returns_none_for_legacy_names() -> None:
    assert parse_label("plainfile.jpg") is None


def test_save_training_image_writes_atomically(tmp_path: Path) -> None:
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    dest = save_training_image(img, tmp_path / "train", "FOO")
    assert dest.exists()
    assert dest.parent == tmp_path / "train"
    assert dest.suffix == ".jpg"
    assert parse_label(dest.name) == "FOO"


def test_save_training_image_rejects_empty_label(tmp_path: Path) -> None:
    img = np.zeros((10, 10, 3), dtype=np.uint8)
    with pytest.raises(ValueError):
        save_training_image(img, tmp_path / "train", "")


def test_class_counts_groups_by_label(tmp_path: Path) -> None:
    d = tmp_path / "train"
    d.mkdir()
    (d / "FOO__1.jpg").write_bytes(b"x")
    (d / "FOO__2.jpg").write_bytes(b"x")
    (d / "BAR__3.png").write_bytes(b"x")
    (d / "junk.txt").write_bytes(b"x")
    (d / "no_label.jpg").write_bytes(b"x")
    counts = class_counts(d)
    assert counts == {"FOO": 2, "BAR": 1}
