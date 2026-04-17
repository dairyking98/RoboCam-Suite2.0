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
from PySide6.QtGui import QImage

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
    proxy_frame = Signal(QImage)  # emits a low-FPS frame for preview

    def __init__(self, output_path: str, fps: float = 30.0):
        super().__init__()
        self.output_path = output_path
        self.fps = fps
        self._stop = False
        self._start_time = None
        self._end_time = None
        self._frame_count = 0

    def stop(self):
        self._stop = True

    def run(self):
        import time
        import json
        camera = hw_manager.get_camera()
        if not camera.is_connected:
            self.error.emit("Camera is not connected.")
            return

        # Always capture the first frame to determine dimensions and ensure the stream is active
        first_frame = None
        for _ in range(20): # Try up to 20 times (2 seconds total) to get a valid frame
            first_frame = camera.read_frame()
            if first_frame is not None:
                break
            self.msleep(100)
            
        if first_frame is None:
            self.error.emit("Could not read a frame from the camera.")
            return

        h, w = first_frame.shape[:2]
        
        # Use MJPG for compatibility and lower CPU overhead on RPi
        fourcc = cv2.VideoWriter_fourcc(*"MJPG")
        writer = cv2.VideoWriter(self.output_path, fourcc, self.fps, (w, h))

        if not writer.isOpened():
            self.error.emit(f"Could not open video writer for {self.output_path}")
            return

        self._start_time = time.time()
        self._frame_count = 0
        
        try:
            # Write the initial frame we just captured
            writer.write(first_frame)
            self._frame_count += 1
            
            # Emit first proxy frame
            self._emit_proxy(first_frame)
            
            # Emit proxy frame every N frames to target ~1-2 FPS
            proxy_interval = max(1, int(self.fps / 2))
            
            while not self._stop:
                frame = camera.read_frame()
                if frame is not None:
                    writer.write(frame)
                    self._frame_count += 1
                    
                    if self._frame_count % proxy_interval == 0:
                        self._emit_proxy(frame)
                
                # Dynamic sleep to maintain target FPS
                elapsed = time.time() - self._start_time
                expected = self._frame_count / self.fps
                sleep_time = max(0, expected - elapsed)
                if sleep_time > 0:
                    self.msleep(int(sleep_time * 1000))
                else:
                    # If we are behind, don't sleep at all
                    pass
                    
        except Exception as e:
            self.error.emit(f"Recording error: {str(e)}")
        finally:
            self._end_time = time.time()
            writer.release()
            self._save_metadata()

        self.finished.emit(self.output_path)

    def _save_metadata(self):
        """Save a JSON metadata file alongside the video."""
        import json
        meta_path = self.output_path.rsplit(".", 1)[0] + "_metadata.json"
        duration = (self._end_time - self._start_time) if self._start_time and self._end_time else 0
        
        camera = hw_manager.get_camera()
        metadata = {
            "video_file": os.path.basename(self.output_path),
            "frames_captured": self._frame_count,
            "duration_seconds": round(duration, 3),
            "fps_target": self.fps,
            "fps_actual": round(self._frame_count / duration, 2) if duration > 0 else 0,
            "timestamp": datetime.now().isoformat(),
            "resolution": list(camera.get_resolution()) if camera.is_connected else []
        }
        
        try:
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2)
            logger.info(f"[QuickCapture] Metadata saved to {meta_path}")
        except Exception as e:
            logger.error(f"[QuickCapture] Failed to save metadata: {e}")

    def _emit_proxy(self, frame):
        """Convert BGR frame to QImage and emit for preview."""
        try:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb.shape
            qimg = QImage(
                rgb.data.tobytes(), w, h, ch * w,
                QImage.Format.Format_RGB888
            )
            self.proxy_frame.emit(qimg.copy())
        except Exception as e:
            logger.debug(f"[_VideoRecorderThread] Proxy emit error: {e}")


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

        # Row 4 — status & resolution
        status_layout = QHBoxLayout()
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("font-size: 10px;")
        self.status_label.setWordWrap(True)
        status_layout.addWidget(self.status_label, stretch=1)
        
        self.res_label = QLabel("")
        self.res_label.setStyleSheet("font-size: 10px; color: #888;")
        self.res_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        status_layout.addWidget(self.res_label)
        
        layout.addLayout(status_layout)
        
        # Initial resolution check
        self._update_resolution_label()

    def _update_resolution_label(self):
        camera = hw_manager.get_camera()
        if camera and camera.is_connected:
            res = camera.get_resolution()
            self.res_label.setText(f"{res[0]}x{res[1]} px")
        else:
            self.res_label.setText("")

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
        
        # Connect proxy frame to preview if available
        if parent_panel and hasattr(parent_panel, '_live_preview'):
            self._recorder.proxy_frame.connect(parent_panel._live_preview.update_frame)
            
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
