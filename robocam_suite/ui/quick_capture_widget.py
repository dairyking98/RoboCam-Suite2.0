"""
QuickCaptureWidget — a compact, reusable widget for on-demand image and
video capture.  Designed to be embedded in both the Calibration and
Manual Control panels.

Features
--------
- **Capture Image** : captures a single frame and saves it.
- **Start Recording** / **Stop Recording** : two separate buttons that are
  mutually enabled/disabled so the state is always unambiguous.
- Output folder is configurable; defaults to ``~/Documents/RoboCam/captures/``.
- A small gray italic status label shows the last saved file path.
- Recording runs in a background QThread so the GUI stays responsive.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import cv2

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton,
    QLabel, QGroupBox, QFileDialog,
)
from PySide6.QtCore import Qt, QThread, Signal

from robocam_suite.hw_manager import hw_manager
from robocam_suite.logger import setup_logger

logger = setup_logger()


def _default_capture_dir() -> Path:
    """Return a writable default directory for captured files."""
    capture_dir = Path.home() / "Documents" / "RoboCam" / "captures"
    capture_dir.mkdir(parents=True, exist_ok=True)
    return capture_dir


# ---------------------------------------------------------------------------
# Background video recorder thread (open-ended — stopped by caller)
# ---------------------------------------------------------------------------

class _VideoRecorderThread(QThread):
    """Records video frames from the camera until stop() is called."""

    finished = Signal(str)   # emits the saved file path
    error    = Signal(str)   # emits an error message

    def __init__(self, output_path: str, fps: float = 30.0):
        super().__init__()
        self.output_path = output_path
        self.fps = fps
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        camera = hw_manager.get_camera()
        if not camera.is_connected:
            self.error.emit("Camera is not connected.")
            return

        # Use the actual camera resolution for the video writer
        w, h = camera.get_resolution()
        if w == 0 or h == 0:
            # Fallback to frame shape if resolution is unknown
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

        try:
            writer.write(first_frame)
            while not self._stop:
                frame = camera.read_frame()
                if frame is not None:
                    writer.write(frame)
                self.msleep(int(1000 / self.fps))
        finally:
            writer.release()

        self.finished.emit(self.output_path)


# ---------------------------------------------------------------------------
# Public widget
# ---------------------------------------------------------------------------

class QuickCaptureWidget(QGroupBox):
    """
    Compact group-box widget with:
      - Capture Image button
      - Start Recording / Stop Recording buttons (mutually exclusive)
      - Gray italic save-folder path label with a … folder-picker button
      - Status label
    """

    def __init__(self, label: str = "Quick Capture", parent=None):
        super().__init__(label, parent)
        self._capture_dir = _default_capture_dir()
        self._recorder: _VideoRecorderThread | None = None

        layout = QVBoxLayout(self)
        layout.setSpacing(4)
        layout.setContentsMargins(6, 6, 6, 6)

        # Row 1 — image capture
        self.capture_image_btn = QPushButton("Capture Image")
        self.capture_image_btn.setToolTip(
            "Grab a single frame from the camera and save it as an image file."
        )
        self.capture_image_btn.clicked.connect(self._capture_image)
        layout.addWidget(self.capture_image_btn)

        # Row 2 — video start / stop (two separate buttons)
        vid_row = QHBoxLayout()
        self.start_record_btn = QPushButton("Start Recording")
        self.start_record_btn.setToolTip("Begin recording video from the camera.")
        self.start_record_btn.clicked.connect(self._start_recording)
        vid_row.addWidget(self.start_record_btn)

        self.stop_record_btn = QPushButton("Stop Recording")
        self.stop_record_btn.setToolTip("Stop the current video recording and save the file.")
        self.stop_record_btn.setEnabled(False)   # disabled until recording starts
        self.stop_record_btn.clicked.connect(self._stop_recording)
        vid_row.addWidget(self.stop_record_btn)
        layout.addLayout(vid_row)

        # Row 3 — save folder (gray italic label + … button)
        folder_row = QHBoxLayout()
        self.folder_label = QLabel(str(self._capture_dir))
        self.folder_label.setStyleSheet(
            "font-size: 10px; color: #888; font-style: italic;"
        )
        self.folder_label.setToolTip("Current save folder for captured images and videos.")
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

    def _start_recording(self):
        camera = hw_manager.get_camera()
        if not camera.is_connected:
            self._set_status("Camera not connected.", error=True)
            return

        # Pause the live preview if we are inside a panel that has one
        # This prevents SDK resource contention and improves framerate.
        parent_panel = self.parent()
        while parent_panel and not hasattr(parent_panel, '_grabber'):
            parent_panel = parent_panel.parent()
        
        if parent_panel and hasattr(parent_panel, '_grabber'):
            parent_panel._grabber.set_paused(True)
            logger.info("[QuickCapture] Paused live preview for recording.")

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"video_{ts}.avi"
        filepath = str(self._capture_dir / filename)

        self._recorder = _VideoRecorderThread(filepath)
        self._recorder.finished.connect(self._on_video_finished)
        self._recorder.error.connect(lambda msg: self._set_status(msg, error=True))
        self._recorder.start()

        self.start_record_btn.setEnabled(False)
        self.stop_record_btn.setEnabled(True)
        self.capture_image_btn.setEnabled(False)
        self._set_status(f"Recording → {filename} …")
        logger.info(f"[QuickCapture] Video recording started: {filepath}")

    def _stop_recording(self):
        if self._recorder and self._recorder.isRunning():
            self._recorder.stop()
            self._recorder.wait(3000)
        
        # Resume live preview
        parent_panel = self.parent()
        while parent_panel and not hasattr(parent_panel, '_grabber'):
            parent_panel = parent_panel.parent()
        
        if parent_panel and hasattr(parent_panel, '_grabber'):
            parent_panel._grabber.set_paused(False)
            logger.info("[QuickCapture] Resumed live preview after recording.")

        self._reset_record_buttons()
        self._set_status("Recording stopped.")

    def _on_video_finished(self, path: str):
        self._reset_record_buttons()
        filename = os.path.basename(path)
        self._set_status(f"Saved: {filename}")
        logger.info(f"[QuickCapture] Video saved to {path}")
        self._recorder = None

    def _reset_record_buttons(self):
        self.start_record_btn.setEnabled(True)
        self.stop_record_btn.setEnabled(False)
        self.capture_image_btn.setEnabled(True)

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

    # ------------------------------------------------------------------
    # Status helper
    # ------------------------------------------------------------------

    def _set_status(self, msg: str, error: bool = False):
        self.status_label.setText(msg)
        self.status_label.setStyleSheet(
            "font-size: 10px; color: red;" if error else "font-size: 10px; color: green;"
        )
