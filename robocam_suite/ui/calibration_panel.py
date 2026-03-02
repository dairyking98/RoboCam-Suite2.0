"""
Calibration Panel — jog the stage, record well-plate corners, preview the
well path, and save/load calibration files.

Layout (left-to-right split)
-----------------------------
LEFT  : live camera preview with well-path overlay
RIGHT : movement controls, corner recording, save/load, quick capture
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QGridLayout, QLabel, QLineEdit, QGroupBox,
    QButtonGroup, QRadioButton, QSplitter,
    QFileDialog, QMessageBox, QSpinBox,
)
from PySide6.QtCore import Qt, QTimer, QThread, Signal
from PySide6.QtGui import QImage, QPixmap, QPainter, QPen, QColor, QFont

import cv2
import numpy as np

from robocam_suite.hw_manager import hw_manager
from robocam_suite.session_manager import session_manager
from robocam_suite.ui.quick_capture_widget import QuickCaptureWidget
from robocam_suite.logger import setup_logger

logger = setup_logger()

# Preset step sizes shown as radio buttons (mm)
STEP_PRESETS = ["0.1", "0.5", "1.0", "5.0", "10.0"]

# Corner order expected by WellPlate
CORNER_NAMES = ["Upper-Left", "Lower-Left", "Upper-Right", "Lower-Right"]


# ---------------------------------------------------------------------------
# Camera frame grabber thread
# ---------------------------------------------------------------------------

class _FrameGrabber(QThread):
    """Grabs camera frames in a background thread and emits them as QImages."""
    frame_ready = Signal(QImage)

    def __init__(self, fps: int = 15):
        super().__init__()
        self._fps = fps
        self._running = False

    def stop(self):
        self._running = False

    def run(self):
        self._running = True
        interval_ms = max(1, int(1000 / self._fps))
        camera = hw_manager.get_camera()
        while self._running:
            try:
                if camera.is_connected:
                    frame = camera.read_frame()
                    if frame is not None:
                        # Convert BGR → RGB
                        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        h, w, ch = rgb.shape
                        qimg = QImage(rgb.data.tobytes(), w, h, ch * w, QImage.Format.Format_RGB888)
                        self.frame_ready.emit(qimg.copy())
            except Exception:
                pass
            self.msleep(interval_ms)


# ---------------------------------------------------------------------------
# Camera preview widget with well-path overlay
# ---------------------------------------------------------------------------

class _CameraPreview(QWidget):
    """Displays live camera frames and overlays the computed well-path grid."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 240)
        self._pixmap: Optional[QPixmap] = None
        self._well_points: list[tuple[float, float]] = []   # normalised 0-1 coords
        self._corner_norms: list[tuple[float, float]] = []  # normalised corner positions
        self._no_camera_label = QLabel("Camera not connected", self)
        self._no_camera_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._no_camera_label.setStyleSheet("color: gray; font-size: 13px;")
        layout = QVBoxLayout(self)
        layout.addWidget(self._no_camera_label)

    def update_frame(self, qimg: QImage):
        self._pixmap = QPixmap.fromImage(qimg)
        self._no_camera_label.hide()
        self.update()

    def set_well_overlay(self, well_norms: list[tuple[float, float]],
                         corner_norms: list[tuple[float, float]]):
        """Set normalised (0-1) well and corner positions for overlay drawing."""
        self._well_points = well_norms
        self._corner_norms = corner_norms
        self.update()

    def clear_overlay(self):
        self._well_points = []
        self._corner_norms = []
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()

        if self._pixmap:
            scaled = self._pixmap.scaled(
                w, h,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            x_off = (w - scaled.width()) // 2
            y_off = (h - scaled.height()) // 2
            painter.drawPixmap(x_off, y_off, scaled)

            # Draw corner markers (yellow squares)
            pen = QPen(QColor(255, 220, 0), 2)
            painter.setPen(pen)
            for nx, ny in self._corner_norms:
                px = x_off + int(nx * scaled.width())
                py = y_off + int(ny * scaled.height())
                painter.drawRect(px - 6, py - 6, 12, 12)

            # Draw well positions (cyan circles)
            pen = QPen(QColor(0, 220, 255), 1)
            painter.setPen(pen)
            for nx, ny in self._well_points:
                px = x_off + int(nx * scaled.width())
                py = y_off + int(ny * scaled.height())
                painter.drawEllipse(px - 4, py - 4, 8, 8)
        else:
            painter.fillRect(0, 0, w, h, QColor(30, 30, 30))

        painter.end()


# ---------------------------------------------------------------------------
# Main CalibrationPanel
# ---------------------------------------------------------------------------

class CalibrationPanel(QWidget):
    """
    Jog controls, corner recording, live camera preview, well-path overlay,
    and save/load calibration files.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.hw_manager = hw_manager
        self._session = session_manager

        # Build layout: camera preview on the left, controls on the right
        splitter = QSplitter(Qt.Orientation.Horizontal, self)

        # --- Left: camera preview ---
        self._preview = _CameraPreview()
        splitter.addWidget(self._preview)

        # --- Right: controls in a scroll area ---
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setSpacing(8)
        right_layout.addWidget(self._build_movement_group())
        right_layout.addWidget(self._build_calibration_group())
        right_layout.addWidget(self._build_save_load_group())
        right_layout.addWidget(QuickCaptureWidget("Quick Capture"))
        right_layout.addStretch()
        splitter.addWidget(right)

        splitter.setSizes([400, 350])
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(splitter)

        # Restore persisted step size and corners
        self._load_from_session()

        # Position display refresh (500 ms)
        self._pos_timer = QTimer(self)
        self._pos_timer.timeout.connect(self._update_position_display)
        self._pos_timer.start(500)

        # Camera frame grabber
        self._grabber = _FrameGrabber(fps=15)
        self._grabber.frame_ready.connect(self._preview.update_frame)
        self._grabber.start()

    def closeEvent(self, event):
        self._grabber.stop()
        self._grabber.wait(1000)
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # Group builders
    # ------------------------------------------------------------------

    def _build_movement_group(self) -> QGroupBox:
        grp = QGroupBox("Movement Controls")
        layout = QGridLayout(grp)

        # Current position display
        pos_row = QHBoxLayout()
        pos_row.addWidget(QLabel("X:"))
        self.x_pos_label = QLabel("0.00")
        pos_row.addWidget(self.x_pos_label)
        pos_row.addWidget(QLabel("Y:"))
        self.y_pos_label = QLabel("0.00")
        pos_row.addWidget(self.y_pos_label)
        pos_row.addWidget(QLabel("Z:"))
        self.z_pos_label = QLabel("0.00")
        pos_row.addWidget(self.z_pos_label)
        pos_row.addStretch()
        layout.addLayout(pos_row, 0, 0, 1, 5)

        # XY jog pad
        self.y_plus_btn = QPushButton("Y+")
        self.y_plus_btn.setToolTip("Move stage in the +Y direction by the selected step size.")
        layout.addWidget(self.y_plus_btn, 1, 1)

        self.x_minus_btn = QPushButton("X-")
        self.x_minus_btn.setToolTip("Move stage in the -X direction.")
        layout.addWidget(self.x_minus_btn, 2, 0)

        self.home_btn = QPushButton("Home")
        self.home_btn.setToolTip("Send G28 — home all axes to their endstops.")
        layout.addWidget(self.home_btn, 2, 1)

        self.x_plus_btn = QPushButton("X+")
        self.x_plus_btn.setToolTip("Move stage in the +X direction.")
        layout.addWidget(self.x_plus_btn, 2, 2)

        self.y_minus_btn = QPushButton("Y-")
        self.y_minus_btn.setToolTip("Move stage in the -Y direction.")
        layout.addWidget(self.y_minus_btn, 3, 1)

        # Z jog
        self.z_plus_btn = QPushButton("Z+")
        self.z_plus_btn.setToolTip("Move stage up (+Z).")
        layout.addWidget(self.z_plus_btn, 1, 3)

        self.z_minus_btn = QPushButton("Z-")
        self.z_minus_btn.setToolTip("Move stage down (-Z).")
        layout.addWidget(self.z_minus_btn, 3, 3)

        # Step size
        step_grp = QGroupBox("Step Size (mm)")
        step_layout = QHBoxLayout(step_grp)
        self._step_btn_group = QButtonGroup(self)
        for i, val in enumerate(STEP_PRESETS):
            rb = QRadioButton(val)
            rb.setObjectName(f"step_{val}")
            self._step_btn_group.addButton(rb, i)
            step_layout.addWidget(rb)
            if val == "1.0":
                rb.setChecked(True)
        step_layout.addWidget(QLabel("Custom:"))
        self.step_size_input = QLineEdit("1.0")
        self.step_size_input.setFixedWidth(55)
        self.step_size_input.setToolTip("Enter any custom step size in mm.")
        step_layout.addWidget(self.step_size_input)
        self._step_btn_group.buttonClicked.connect(
            lambda btn: self.step_size_input.setText(btn.text())
        )
        self.step_size_input.textEdited.connect(self._on_custom_step_edited)
        layout.addWidget(step_grp, 4, 0, 1, 5)

        # Connect jog buttons
        self.y_plus_btn.clicked.connect(lambda: self._move("y", 1))
        self.y_minus_btn.clicked.connect(lambda: self._move("y", -1))
        self.x_plus_btn.clicked.connect(lambda: self._move("x", 1))
        self.x_minus_btn.clicked.connect(lambda: self._move("x", -1))
        self.z_plus_btn.clicked.connect(lambda: self._move("z", 1))
        self.z_minus_btn.clicked.connect(lambda: self._move("z", -1))
        self.home_btn.clicked.connect(self._home)

        return grp

    def _build_calibration_group(self) -> QGroupBox:
        grp = QGroupBox("Well-Plate Corner Calibration")
        grp.setToolTip(
            "Jog the stage to each corner of the well plate and press the\n"
            "corresponding button to record that position.\n"
            "The suite uses bilinear interpolation to calculate every well position."
        )
        layout = QGridLayout(grp)

        self.corners: dict = {}
        for i, name in enumerate(CORNER_NAMES):
            row, col = divmod(i, 2)
            layout.addWidget(QLabel(f"{name}:"), row * 2, col * 2)
            pos_label = QLabel("Not Set")
            pos_label.setStyleSheet("color: gray;")
            layout.addWidget(pos_label, row * 2, col * 2 + 1)
            set_btn = QPushButton(f"Set {name}")
            set_btn.setToolTip(
                f"Record the current stage position as the {name} corner of the well plate."
            )
            layout.addWidget(set_btn, row * 2 + 1, col * 2, 1, 2)
            self.corners[name] = {"label": pos_label, "button": set_btn, "position": None}
            set_btn.clicked.connect(lambda checked=False, n=name: self._set_corner(n))

        # Well quantity inputs for path preview
        qty_row = QHBoxLayout()
        qty_row.addWidget(QLabel("Columns (X):"))
        self.cols_spin = QSpinBox()
        self.cols_spin.setRange(1, 48)
        self.cols_spin.setValue(12)
        self.cols_spin.setToolTip("Number of wells along the X axis (columns).")
        qty_row.addWidget(self.cols_spin)
        qty_row.addWidget(QLabel("Rows (Y):"))
        self.rows_spin = QSpinBox()
        self.rows_spin.setRange(1, 32)
        self.rows_spin.setValue(8)
        self.rows_spin.setToolTip("Number of wells along the Y axis (rows).")
        qty_row.addWidget(self.rows_spin)
        layout.addLayout(qty_row, 4, 0, 1, 4)

        self.generate_path_btn = QPushButton("Preview Well Plate Path")
        self.generate_path_btn.setToolTip(
            "Compute and overlay the well positions on the camera preview.\n"
            "Requires all four corners to be set."
        )
        self.generate_path_btn.clicked.connect(self._preview_path)
        layout.addWidget(self.generate_path_btn, 5, 0, 1, 4)

        self.clear_overlay_btn = QPushButton("Clear Overlay")
        self.clear_overlay_btn.setToolTip("Remove the well-path overlay from the camera preview.")
        self.clear_overlay_btn.clicked.connect(self._preview.clear_overlay)
        layout.addWidget(self.clear_overlay_btn, 6, 0, 1, 4)

        return grp

    def _build_save_load_group(self) -> QGroupBox:
        grp = QGroupBox("Calibration File")
        grp.setToolTip(
            "Save the four corner positions to a JSON file so you can reload\n"
            "them later without re-calibrating. Useful when you have multiple\n"
            "well-plate formats or experimental setups."
        )
        layout = QHBoxLayout(grp)

        save_btn = QPushButton("Save Calibration…")
        save_btn.setToolTip("Save the current corner positions to a .json file.")
        save_btn.clicked.connect(self._save_calibration)
        layout.addWidget(save_btn)

        load_btn = QPushButton("Load Calibration…")
        load_btn.setToolTip("Load corner positions from a previously saved .json file.")
        load_btn.clicked.connect(self._load_calibration)
        layout.addWidget(load_btn)

        self._cal_status_label = QLabel("")
        self._cal_status_label.setStyleSheet("font-size: 10px; color: gray;")
        layout.addWidget(self._cal_status_label, stretch=1)

        return grp

    # ------------------------------------------------------------------
    # Actions — movement
    # ------------------------------------------------------------------

    def _move(self, axis: str, direction: int):
        try:
            step = float(self.step_size_input.text())
            self.hw_manager.get_motion_controller().move_relative(**{axis: direction * step})
            self._update_position_display()
        except Exception as e:
            logger.warning(f"[Calibration] Move error: {e}")

    def _home(self):
        try:
            self.hw_manager.get_motion_controller().home()
            self._update_position_display()
        except Exception as e:
            logger.warning(f"[Calibration] Home error: {e}")

    def _set_corner(self, name: str):
        try:
            pos = self.hw_manager.get_motion_controller().get_current_position()
            self.corners[name]["position"] = list(pos)
            self.corners[name]["label"].setText(
                f"X:{pos[0]:.2f}  Y:{pos[1]:.2f}  Z:{pos[2]:.2f}"
            )
            self.corners[name]["label"].setStyleSheet("color: green;")
            self._persist_corners()
        except Exception as e:
            logger.warning(f"[Calibration] Set corner error: {e}")

    # ------------------------------------------------------------------
    # Actions — path preview
    # ------------------------------------------------------------------

    def _preview_path(self):
        """Compute well positions and overlay them on the camera preview."""
        corners = [self.corners[n]["position"] for n in CORNER_NAMES]
        if any(c is None for c in corners):
            QMessageBox.warning(
                self, "Corners Not Set",
                "Please set all four corner positions before previewing the path."
            )
            return

        cols = self.cols_spin.value()
        rows = self.rows_spin.value()

        # Compute all well positions using bilinear interpolation
        ul, ll, ur, lr = corners
        well_positions = []
        for row_i in range(rows):
            for col_j in range(cols):
                u = col_j / (cols - 1) if cols > 1 else 0.0
                v = row_i / (rows - 1) if rows > 1 else 0.0
                top_x = ul[0] + u * (ur[0] - ul[0])
                top_y = ul[1] + u * (ur[1] - ul[1])
                bot_x = ll[0] + u * (lr[0] - ll[0])
                bot_y = ll[1] + u * (lr[1] - ll[1])
                x = top_x + v * (bot_x - top_x)
                y = top_y + v * (bot_y - top_y)
                well_positions.append((x, y))

        # Normalise to 0-1 range for overlay drawing
        all_x = [p[0] for p in well_positions] + [c[0] for c in corners]
        all_y = [p[1] for p in well_positions] + [c[1] for c in corners]
        min_x, max_x = min(all_x), max(all_x)
        min_y, max_y = min(all_y), max(all_y)
        span_x = max_x - min_x or 1.0
        span_y = max_y - min_y or 1.0

        def norm(px, py):
            return ((px - min_x) / span_x, (py - min_y) / span_y)

        well_norms = [norm(x, y) for x, y in well_positions]
        corner_norms = [norm(c[0], c[1]) for c in corners]

        self._preview.set_well_overlay(well_norms, corner_norms)
        logger.info(f"[Calibration] Path preview: {rows}×{cols} = {len(well_positions)} wells.")

    # ------------------------------------------------------------------
    # Actions — save / load calibration
    # ------------------------------------------------------------------

    def _save_calibration(self):
        corners = {n: self.corners[n]["position"] for n in CORNER_NAMES}
        if any(v is None for v in corners.values()):
            QMessageBox.warning(
                self, "Incomplete Calibration",
                "Please set all four corner positions before saving."
            )
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Save Calibration",
            str(Path.home() / "Documents" / "robocam_calibration.json"),
            "JSON Files (*.json)"
        )
        if not path:
            return

        data = {
            "corners": corners,
            "cols": self.cols_spin.value(),
            "rows": self.rows_spin.value(),
        }
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            self._cal_status_label.setText(f"Saved: {Path(path).name}")
            self._cal_status_label.setStyleSheet("font-size: 10px; color: green;")
            logger.info(f"[Calibration] Saved to {path}")
        except OSError as e:
            QMessageBox.critical(self, "Save Error", str(e))

    def _load_calibration(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Calibration",
            str(Path.home() / "Documents"),
            "JSON Files (*.json)"
        )
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            QMessageBox.critical(self, "Load Error", str(e))
            return

        corners = data.get("corners", {})
        for name in CORNER_NAMES:
            pos = corners.get(name)
            if pos is not None:
                self.corners[name]["position"] = pos
                self.corners[name]["label"].setText(
                    f"X:{pos[0]:.2f}  Y:{pos[1]:.2f}  Z:{pos[2]:.2f}"
                )
                self.corners[name]["label"].setStyleSheet("color: green;")

        if "cols" in data:
            self.cols_spin.setValue(int(data["cols"]))
        if "rows" in data:
            self.rows_spin.setValue(int(data["rows"]))

        self._persist_corners()
        self._cal_status_label.setText(f"Loaded: {Path(path).name}")
        self._cal_status_label.setStyleSheet("font-size: 10px; color: green;")
        logger.info(f"[Calibration] Loaded from {path}")

    # ------------------------------------------------------------------
    # Public accessor used by ExperimentPanel
    # ------------------------------------------------------------------

    def get_corners(self) -> dict:
        return {k: v["position"] for k, v in self.corners.items()}

    def get_well_dimensions(self) -> tuple[int, int]:
        """Return (cols, rows) from the calibration spinners."""
        return self.cols_spin.value(), self.rows_spin.value()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _on_custom_step_edited(self, text: str):
        checked = self._step_btn_group.checkedButton()
        if checked and checked.text() != text:
            self._step_btn_group.setExclusive(False)
            checked.setChecked(False)
            self._step_btn_group.setExclusive(True)
        self._session.update_session("calibration", {"step_size": text})

    def _update_position_display(self):
        try:
            pos = self.hw_manager.get_motion_controller().get_current_position()
            self.x_pos_label.setText(f"{pos[0]:.2f}")
            self.y_pos_label.setText(f"{pos[1]:.2f}")
            self.z_pos_label.setText(f"{pos[2]:.2f}")
        except Exception:
            pass

    def _persist_corners(self):
        session_corners = {k: v["position"] for k, v in self.corners.items()}
        self._session.update_session("calibration", {"corners": session_corners})

    # ------------------------------------------------------------------
    # Session restore
    # ------------------------------------------------------------------

    def _load_from_session(self):
        s = self._session.get_session("calibration")

        # Step size
        step = s.get("step_size", "1.0")
        self.step_size_input.setText(step)
        for btn in self._step_btn_group.buttons():
            if btn.text() == step:
                btn.setChecked(True)
                break

        # Corners
        saved_corners = s.get("corners", {})
        for name, pos in saved_corners.items():
            if pos is not None and name in self.corners:
                self.corners[name]["position"] = pos
                self.corners[name]["label"].setText(
                    f"X:{pos[0]:.2f}  Y:{pos[1]:.2f}  Z:{pos[2]:.2f}"
                )
                self.corners[name]["label"].setStyleSheet("color: green;")

        # Well dimensions
        cols = s.get("cols", 12)
        rows = s.get("rows", 8)
        self.cols_spin.setValue(int(cols))
        self.rows_spin.setValue(int(rows))
