"""
QuickCaptureWidget — a compact, reusable widget for on-demand image and
video capture.  Designed to be embedded in both the Calibration and
Manual Control panels.

Features
--------
- **Quick Image** : captures a single frame and saves it as a PNG.
- **Quick Video** : records for a user-specified number of seconds and
  saves it as an AVI (MJPG codec, works on all platforms without extra
  codecs).
- Output folder is configurable; defaults to ``~/Documents/RoboCam/captures/``.
- A small status label shows the last saved file path.
- Recording runs in a background QThread so the GUI stays responsive.
"""
from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton,
    QLabel, QSpinBox, QGroupBox, QFileDialog,
)
from PySide6.QtCore import Qt, QThread, Signal

from robocam_suite.hw_manager import hw_manager
from robocam_suite.logger import setup_logger

logger = setup_logger()


def _default_capture_dir() -> Path:
    """Return a writable default directory for captured files."""
    docs = Path.home() / "Documents"
    capture_dir = docs / "RoboCam" / "captures"
    capture_dir.mkdir(parents=True, exist_ok=True)
    return capture_dir


# ---------------------------------------------------------------------------
# Background video recorder thread
# ---------------------------------------------------------------------------

class _VideoRecorderThread(QThread):
    """Records video frames from the camera in a background thread."""

    finished = Signal(str)   # emits the saved file path
    error = Signal(str)      # emits an error message

    def __init__(self, output_path: str, duration_s: float, fps: float = 30.0):
        super().__init__()
        self.output_path = output_path
        self.duration_s = duration_s
        self.fps = fps
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        camera = hw_manager.get_camera()
        if not camera.is_connected:
            self.error.emit("Camera is not connected.")
            return

        # Grab one frame to determine resolution
        first_frame = camera.read_frame()
        if first_frame is None:
            self.error.emit("Could not read a frame from the camera.")
            return

        h, w = first_frame.shape[:2]
        fourcc = cv2.VideoWriter_fourcc(*"MJPG")
        writer = cv2.VideoWriter(self.output_path, fourcc, self.fps, (w, h))

        if not writer.isOpened():
            self.error.emit(f"Could not open video writer for {self.output_path}")
            return

        start = time.time()
        try:
            while not self._stop and (time.time() - start) < self.duration_s:
                frame = camera.read_frame()
                if frame is not None:
                    writer.write(frame)
                else:
                    time.sleep(1.0 / self.fps)
        finally:
            writer.release()

        self.finished.emit(self.output_path)


# ---------------------------------------------------------------------------
# Public widget
# ---------------------------------------------------------------------------

class QuickCaptureWidget(QGroupBox):
    """
    A compact group-box widget providing Quick Image and Quick Video buttons.

    Parameters
    ----------
    label : str
        Title shown on the group box border.
    parent : QWidget, optional
    """

    def __init__(self, label: str = "Quick Capture", parent=None):
        super().__init__(label, parent)
        self._capture_dir = _default_capture_dir()
        self._recorder: _VideoRecorderThread | None = None

        layout = QVBoxLayout(self)
        layout.setSpacing(4)

        # Row 1 — image capture
        img_row = QHBoxLayout()
        self.capture_image_btn = QPushButton("Capture Image")
        self.capture_image_btn.setToolTip(
            "Grab a single frame from the camera and save it as a PNG file.\n"
            f"Saved to: {self._capture_dir}"
        )
        self.capture_image_btn.clicked.connect(self._capture_image)
        img_row.addWidget(self.capture_image_btn)
        layout.addLayout(img_row)

        # Row 2 — video capture
        vid_row = QHBoxLayout()
        self.record_video_btn = QPushButton("Record Video")
        self.record_video_btn.setToolTip(
            "Record a video clip for the specified duration and save it as an AVI file."
        )
        self.record_video_btn.clicked.connect(self._toggle_video)
        vid_row.addWidget(self.record_video_btn)

        vid_row.addWidget(QLabel("Duration (s):"))
        self.duration_spin = QSpinBox()
        self.duration_spin.setRange(1, 3600)
        self.duration_spin.setValue(5)
        self.duration_spin.setToolTip("How many seconds to record.")
        self.duration_spin.setFixedWidth(60)
        vid_row.addWidget(self.duration_spin)
        layout.addLayout(vid_row)

        # Row 3 — output folder chooser
        folder_row = QHBoxLayout()
        self.folder_label = QLabel(str(self._capture_dir))
        self.folder_label.setStyleSheet("color: gray; font-size: 10px;")
        self.folder_label.setWordWrap(True)
        folder_row.addWidget(self.folder_label, stretch=1)
        folder_btn = QPushButton("…")
        folder_btn.setFixedWidth(28)
        folder_btn.setToolTip("Choose a different output folder.")
        folder_btn.clicked.connect(self._choose_folder)
        folder_row.addWidget(folder_btn)
        layout.addLayout(folder_row)

        # Row 4 — status
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("font-size: 10px;")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

    # ------------------------------------------------------------------
    # Image capture
    # ------------------------------------------------------------------

    def _capture_image(self):
        camera = hw_manager.get_camera()
        if not camera.is_connected:
            self._set_status("Camera not connected.", error=True)
            return

        frame = camera.read_frame()
        if frame is None:
            self._set_status("No frame available.", error=True)
            return

        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        filename = f"capture_{ts}.png"
        filepath = str(self._capture_dir / filename)

        try:
            cv2.imwrite(filepath, frame)
            self._set_status(f"Saved: {filename}")
            logger.info(f"[QuickCapture] Image saved to {filepath}")
        except Exception as e:
            self._set_status(f"Error saving image: {e}", error=True)
            logger.error(f"[QuickCapture] Image save error: {e}")

    # ------------------------------------------------------------------
    # Video capture
    # ------------------------------------------------------------------

    def _toggle_video(self):
        if self._recorder and self._recorder.isRunning():
            self._recorder.stop()
            self.record_video_btn.setText("Record Video")
            self._set_status("Recording stopped.")
        else:
            self._start_video()

    def _start_video(self):
        camera = hw_manager.get_camera()
        if not camera.is_connected:
            self._set_status("Camera not connected.", error=True)
            return

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"video_{ts}.avi"
        filepath = str(self._capture_dir / filename)
        duration = self.duration_spin.value()

        self._recorder = _VideoRecorderThread(filepath, duration_s=float(duration))
        self._recorder.finished.connect(self._on_video_finished)
        self._recorder.error.connect(lambda msg: self._set_status(msg, error=True))
        self._recorder.start()

        self.record_video_btn.setText("Stop Recording")
        self._set_status(f"Recording {duration}s → {filename} …")
        logger.info(f"[QuickCapture] Video recording started: {filepath}")

    def _on_video_finished(self, path: str):
        self.record_video_btn.setText("Record Video")
        filename = os.path.basename(path)
        self._set_status(f"Saved: {filename}")
        logger.info(f"[QuickCapture] Video saved to {path}")
        self._recorder = None

    # ------------------------------------------------------------------
    # Folder chooser
    # ------------------------------------------------------------------

    def _choose_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Select Output Folder", str(self._capture_dir)
        )
        if folder:
            self._capture_dir = Path(folder)
            self._capture_dir.mkdir(parents=True, exist_ok=True)
            self.folder_label.setText(str(self._capture_dir))
            self.capture_image_btn.setToolTip(
                f"Grab a single frame from the camera and save it as a PNG file.\n"
                f"Saved to: {self._capture_dir}"
            )

    # ------------------------------------------------------------------
    # Status helper
    # ------------------------------------------------------------------

    def _set_status(self, msg: str, error: bool = False):
        self.status_label.setText(msg)
        self.status_label.setStyleSheet(
            "font-size: 10px; color: red;" if error else "font-size: 10px; color: green;"
        )
