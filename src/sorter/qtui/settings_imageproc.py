"""Settings -> Image Proc page: Hough tuning, primer mask, LED, before/after preview.

Behavior + ranges reference: ``sorter/ui/tab_imageproc.py`` (the ``NumericField``
bounds there are the source of truth for the spin-box ranges below) and
``sorter/hardware/image_proc.py`` for the processing pipeline itself.

Deviation from the Tk tab, deliberate: the Tk tab only commits a parameter
change to ``Config`` when "Save" (or "Capture Image", which calls save() first)
is clicked. This page persists each control on change instead — no separate
Save step — and reprocesses the last-captured frame against it. Line-scan
strategy stays dormant here too, same as Tk (``crop_headstamp`` always picks Hough).
"""

from __future__ import annotations

from typing import Any

import numpy as np
from PySide6.QtCore import Qt, QTimer  # ty: ignore[unresolved-import]
from PySide6.QtGui import QPixmap  # ty: ignore[unresolved-import]
from PySide6.QtWidgets import (  # ty: ignore[unresolved-import]
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..hardware.image_proc import (
    HoughParams,
    apply_primer_mask,
    crop_headstamp,
    hough_detect,
    overlay_detection,
)

PRIMER_MODES: tuple[tuple[str, str], ...] = (
    ("None", "none"),
    ("Keep primer area only", "use"),
    ("Hide primer", "hide"),
)
LED_DEBOUNCE_MS = 500
LED_RECAPTURE_DELAY_MS = 200


class ImageProcSection(QWidget):
    """Hough + primer + LED controls, and a before/after preview. State on ``self``."""

    def __init__(self, win: Any) -> None:
        super().__init__()
        self._win = win
        self._raw_frame: np.ndarray | None = None
        self._led_pending_value: int | None = None
        self._led_last_sent: int | None = None

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(8)

        column.addWidget(self._build_hough_group())
        column.addWidget(self._build_primer_group())
        column.addWidget(self._build_led_group())
        column.addLayout(self._build_actions_row())
        column.addLayout(self._build_preview_row(), 1)

        self._led_timer = QTimer(self)
        self._led_timer.setSingleShot(True)
        self._led_timer.timeout.connect(self._apply_led)

    # ----- Hough group -----------------------------------------------------

    def _build_hough_group(self) -> QGroupBox:
        box = QGroupBox("Configuration", self)
        grid = QGridLayout(box)
        h = self._win.config.image_proc.get("hough", {})

        self.dp_spin = QDoubleSpinBox(box)
        self.dp_spin.setRange(1, 10)
        self.dp_spin.setSingleStep(0.5)
        self.dp_spin.setValue(float(h.get("dp", 2.0)))

        self.min_dist_spin = QSpinBox(box)
        self.min_dist_spin.setRange(1, 4000)
        self.min_dist_spin.setValue(int(h.get("min_dist", 500)))

        self.param1_spin = QSpinBox(box)
        self.param1_spin.setRange(1, 500)
        self.param1_spin.setValue(int(h.get("param1", 100)))

        self.param2_spin = QSpinBox(box)
        self.param2_spin.setRange(1, 500)
        self.param2_spin.setValue(int(h.get("param2", 60)))

        self.min_radius_spin = QSpinBox(box)
        self.min_radius_spin.setRange(1, 4000)
        self.min_radius_spin.setValue(int(h.get("min_radius", 150)))

        self.max_radius_spin = QSpinBox(box)
        self.max_radius_spin.setRange(1, 4000)
        self.max_radius_spin.setValue(int(h.get("max_radius", 250)))

        fields = (
            ("Accumulator scale (dp)", self.dp_spin),
            ("Min center separation (px)", self.min_dist_spin),
            ("Edge strength (param1)", self.param1_spin),
            ("Detection threshold (param2)", self.param2_spin),
            ("Min case radius (px)", self.min_radius_spin),
            ("Max case radius (px)", self.max_radius_spin),
        )
        for idx, (label, widget) in enumerate(fields):
            grid.addWidget(QLabel(label, box), idx // 3, (idx % 3) * 2)
            grid.addWidget(widget, idx // 3, (idx % 3) * 2 + 1)
            widget.valueChanged.connect(self._on_hough_changed)
        return box

    def _on_hough_changed(self, _value: Any = None) -> None:
        cfg = self._win.config.image_proc
        cfg["strategy"] = "hough"
        cfg["hough"] = {
            "dp": float(self.dp_spin.value()),
            "min_dist": int(self.min_dist_spin.value()),
            "param1": float(self.param1_spin.value()),
            "param2": float(self.param2_spin.value()),
            "min_radius": int(self.min_radius_spin.value()),
            "max_radius": int(self.max_radius_spin.value()),
        }
        self._win.config.save()
        self._reprocess()

    # ----- Primer group ------------------------------------------------------

    def _build_primer_group(self) -> QGroupBox:
        box = QGroupBox("Primer mask", self)
        row = QHBoxLayout(box)
        ip = self._win.config.image_proc

        self.primer_mode_combo = QComboBox(box)
        for label, value in PRIMER_MODES:
            self.primer_mode_combo.addItem(label, value)
        saved_mode = ip.get("primer_mode", "hide")
        match = next((i for i, (_l, v) in enumerate(PRIMER_MODES) if v == saved_mode), 2)
        self.primer_mode_combo.setCurrentIndex(match)
        row.addWidget(self.primer_mode_combo)

        row.addWidget(QLabel("Primer radius (px)", box))
        self.primer_radius_spin = QSpinBox(box)
        self.primer_radius_spin.setRange(1, 240)
        self.primer_radius_spin.setValue(int(ip.get("primer_radius", 135)))
        row.addWidget(self.primer_radius_spin)
        row.addStretch(1)

        self.primer_mode_combo.currentIndexChanged.connect(self._on_primer_changed)
        self.primer_radius_spin.valueChanged.connect(self._on_primer_changed)
        return box

    def _on_primer_changed(self, _value: Any = None) -> None:
        cfg = self._win.config.image_proc
        cfg["primer_mode"] = self.primer_mode_combo.currentData()
        cfg["primer_radius"] = int(self.primer_radius_spin.value())
        self._win.config.save()
        self._reprocess()

    # ----- LED group -----------------------------------------------------------

    def _build_led_group(self) -> QGroupBox:
        box = QGroupBox("Camera LED brightness", self)
        column = QVBoxLayout(box)
        init_settings = self._win.config.serial.get("init_settings", {})
        initial = int(init_settings.get("cameraledlevel", 130))

        self.led_slider = QSlider(Qt.Orientation.Horizontal, box)
        self.led_slider.setRange(1, 255)
        self.led_slider.setValue(initial)
        column.addWidget(self.led_slider)

        row = QFormLayout()
        self.led_value_label = QLabel(str(initial), box)
        row.addRow("Value", self.led_value_label)
        column.addLayout(row)
        column.addWidget(QLabel(f"(sends cameraledlevel:N once idle for {LED_DEBOUNCE_MS} ms)", box))

        self.led_slider.valueChanged.connect(self._on_led_changed)
        return box

    def _on_led_changed(self, value: int) -> None:
        self.led_value_label.setText(str(value))
        self._led_pending_value = int(value)
        self._led_timer.stop()
        self._led_timer.start(LED_DEBOUNCE_MS)

    def _apply_led(self) -> None:
        value = self._led_pending_value
        if value is None or value == self._led_last_sent:
            return
        self._led_last_sent = value
        # Persist immediately so a restart picks up the same brightness.
        init_settings = dict(self._win.config.serial.get("init_settings", {}))
        init_settings["cameraledlevel"] = value
        self._win.config.serial["init_settings"] = init_settings
        self._win.config.save()

        broker = self._win.broker
        if broker is None or not getattr(broker, "is_connected", False):
            self._win.set_status(f"Camera LED level = {value} (saved; not connected).")
            return
        try:
            broker.send_command(f"cameraledlevel:{value}")
            self._win.set_status(f"Camera LED level → {value}.")
            # Give the LED + camera a moment to settle, then show the new brightness.
            QTimer.singleShot(LED_RECAPTURE_DELAY_MS, self.capture)
        except Exception as exc:
            self._win.set_status(f"LED send failed: {exc}")

    # ----- actions + preview -----------------------------------------------

    def _build_actions_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.capture_button = QPushButton("Capture", self)
        self.capture_button.setObjectName("action")
        self.capture_button.clicked.connect(self.capture)
        row.addWidget(self.capture_button)
        row.addStretch(1)
        return row

    def _build_preview_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.raw_preview_label = self._preview_label()
        row.addWidget(self.raw_preview_label, 1)
        arrow = QLabel("→", self)
        row.addWidget(arrow)
        self.processed_preview_label = self._preview_label()
        row.addWidget(self.processed_preview_label, 1)
        return row

    def _preview_label(self) -> QLabel:
        label = QLabel("No frame", self)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Ignored + tiny minimum, same reasoning as the Sort preview: a fixed
        # size hint from the pixmap would ratchet the layout on every frame.
        label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        label.setMinimumSize(1, 1)
        label.setStyleSheet("background-color: #000000; color: #808080;")
        return label

    def capture(self) -> None:
        self._win.run_worker(
            self._win.camera.capture_frame,
            on_done=self._on_captured,
            on_error=self._on_capture_error,
        )

    def _on_captured(self, frame: np.ndarray | None) -> None:
        if frame is None:
            self._win.set_status("No camera frame available.")
            return
        self._raw_frame = frame
        self._reprocess()

    def _on_capture_error(self, exc: Exception) -> None:
        self._win.set_status(f"Capture failed: {exc}")

    def _reprocess(self) -> None:
        """Re-run the pipeline against the last captured frame — no re-capture."""
        if self._raw_frame is None:
            return
        cfg = self._win.config.image_proc
        params = HoughParams.from_dict(cfg.get("hough", {}))
        detection = hough_detect(self._raw_frame, params)
        preview = overlay_detection(self._raw_frame, detection)
        if detection is None:
            self._win.set_status("No circle detected within radius bounds.")
        else:
            cx, cy, r = detection
            self._win.set_status(f"Detected circle: r={r:.0f} px at ({cx:.0f}, {cy:.0f}).")

        cropped = crop_headstamp(self._raw_frame, cfg)
        cropped = apply_primer_mask(cropped, self.primer_mode_combo.currentData(), int(self.primer_radius_spin.value()))
        self._show(self.raw_preview_label, preview)
        self._show(self.processed_preview_label, cropped)

    def _show(self, label: QLabel, frame: np.ndarray) -> None:
        pixmap = QPixmap.fromImage(self._win.frame_to_image(frame))
        label.setPixmap(
            pixmap.scaled(label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        )


def build_imageproc_section(win: Any) -> ImageProcSection:
    return ImageProcSection(win)
