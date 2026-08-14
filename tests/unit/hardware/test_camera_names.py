"""Friendly camera names: the V4L2 card-string cleanup (JL live-testing).

The kernel caps the card field at 32 bytes and drivers commonly fill it as
"<name>: <name>", so real hardware reports "USB 2.0 Camera: USB 2.0 Camera"
and, truncated, "Integrated RGB Camera: Integrat". The cleanup collapses the
self-repeat and nothing else — a tail that says something new must survive.
"""

from __future__ import annotations

import pytest

from sorter.hardware.camera import _clean_v4l2_name


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Truncated self-repeat (real sysfs output on JL's machine).
        ("Integrated RGB Camera: Integrat", "Integrated RGB Camera"),
        # Exact self-repeat (also real).
        ("USB 2.0 Camera: USB 2.0 Camera", "USB 2.0 Camera"),
        # Head truncated shorter than tail: keep the longer, complete side.
        ("Integrat: Integrated RGB Camera", "Integrated RGB Camera"),
        # Case differences are still a repeat.
        ("HD Webcam: HD WEBCAM", "HD Webcam"),
        # A tail that says something new is information, not a repeat.
        ("Sonix Technology: HD Webcam C310", "Sonix Technology: HD Webcam C310"),
        # No colon at all: untouched (modulo whitespace).
        ("Integrated Camera\n", "Integrated Camera"),
        # Degenerate halves fall back to the trimmed original.
        (": USB Camera", ": USB Camera"),
        ("USB Camera:", "USB Camera:"),
    ],
)
def test_clean_v4l2_name(raw: str, expected: str) -> None:
    assert _clean_v4l2_name(raw) == expected
