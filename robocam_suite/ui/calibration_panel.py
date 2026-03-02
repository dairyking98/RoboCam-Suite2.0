"""
Calibration Panel — jog the stage, record well-plate corners, preview the
well path, and save/load calibration files.

Layout
------
Left (large)  : live camera preview — close-up of the current well position.
Right (narrow): movement controls, corner recording, well-plate map, save/load.

Well-plate map
--------------
A compact grid of small buttons, one per well, generated after all four corners
are set.  Clicking any button in the map moves the stage directly to that well.
This is separate from the live camera feed which always shows what the camera
sees right now.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QGridLayout, QLabel, QLineEdit, QGroupBox,
    QButtonGroup, QRadioButton, QSplitter,
    QFileDialog, QMessageBox, QSpinBox, QScrollArea,
    QSizePolicy,
)
from PySide6.QtCore import Qt, QTimer, QThread, Signal
from PySide6.QtGui import QImage, QPixmap, QPainter, QPen, QColor

import cv2

from robocam_suite.hw_manager import hw_manager
from robocam_suite.session_manager import session_manager
from robocam_suite.ui.quick_capture_widget import QuickCaptureWidget
from robocam_suite.logger import setup_logger

logger = setup_logger()

STEP_PRESETS = ["0.1", "0.5", "1.0", "5.0", "10.0"]
CORNER_NAMES = ["Upper-Left", "Lower-Left", "Upper-Right", "Lower-Right"]

# Default calibration save directory
def _default_cal_dir() -> Path:
    return Path.home() / "Documents" / "RoboCam" / "calibrations"


# ---------------------------------------------------------------------------
# Camera frame grabber thread
# ---------------------------------------------------------------------------

class _FrameGrabber(QThread):
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
                        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        h, w, ch = rgb.shape
                        qimg = QImage(
                            rgb.data.tobytes(), w, h, ch * w,
                            QImage.Format.Format_RGB888
                        )
                        self.frame_ready.emit(qimg.copy())
            except Exception:
                pass
            self.msleep(interval_ms)


# ---------------------------------------------------------------------------
# Live camera preview widget  (no overlay — just the raw feed)
# ---------------------------------------------------------------------------

class _LivePreview(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 300)
        self._pixmap: Optional[QPixmap] = None
        lbl = QLabel("Camera not connected", self)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet("color: gray; font-size: 13px;")
        self._no_cam_lbl = lbl
        layout = QVBoxLayout(self)
        layout.addWidget(lbl)

    def update_frame(self, qimg: QImage):
        self._pixmap = QPixmap.fromImage(qimg)
        self._no_cam_lbl.hide()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
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
        else:
            painter.fillRect(0, 0, w, h, QColor(30, 30, 30))
        painter.end()


# ---------------------------------------------------------------------------
# Well-plate map widget  (compact clickable grid — NOT the camera feed)
# ---------------------------------------------------------------------------

class _WellMapButton(QPushButton):
    IDLE_STYLE = (
        "background:#444; color:#ccc; border:1px solid #333; "
        "border-radius:2px; font-size:8px; padding:0px;"
    )
    HOVER_STYLE = (
        "background:#2a7ae2; color:white; border:1px solid #1a5ab2; "
        "border-radius:2px; font-size:8px; padding:0px;"
    )

    def __init__(self, label: str, parent=None):
        super().__init__(label, parent)
        self.setFixedSize(32, 20)
        self.setStyleSheet(self.IDLE_STYLE)
        self.setToolTip(f"Move stage to well {label}")

    def enterEvent(self, event):
        self.setStyleSheet(self.HOVER_STYLE)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setStyleSheet(self.IDLE_STYLE)
        super().leaveEvent(event)


class WellMapWidget(QGroupBox):
    """
    Compact grid of buttons representing the well plate.
    After calibration is complete, clicking any button moves the stage to
    that well's computed XYZ position.
    """

    well_clicked = Signal(float, float, float)   # emits (x, y, z) of the chosen well

    def __init__(self, parent=None):
        super().__init__("Well Map  (click to go to well)", parent)
        self.setToolTip(
            "Compact map of the well plate.\n"
            "Click any well to move the stage directly to that position.\n"
            "Generated automatically after all four corners are set."
        )
        self._layout = QGridLayout()
        self._layout.setSpacing(2)
        self._buttons: dict[tuple[int, int], _WellMapButton] = {}
        self._positions: dict[tuple[int, int], tuple[float, float, float]] = {}

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(180)
        inner = QWidget()
        inner.setLayout(self._layout)
        scroll.setWidget(inner)

        outer = QVBoxLayout(self)
        outer.addWidget(scroll)

        self._placeholder = QLabel("Set all four corners to generate the map.")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet("color: gray; font-size: 10px;")
        outer.addWidget(self._placeholder)

    def build(self, rows: int, cols: int,
              positions: list[tuple[float, float, float]]):
        """
        Build or rebuild the map grid.

        Parameters
        ----------
        rows, cols : int
            Well-plate dimensions.
        positions : list of (x, y, z)
            Flat list of positions in row-major order (len == rows * cols).
        """
        # Clear old buttons
        for btn in self._buttons.values():
            btn.deleteLater()
        self._buttons.clear()
        self._positions.clear()
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._placeholder.hide()

        # Column headers
        for col in range(cols):
            lbl = QLabel(str(col + 1))
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet("font-size: 8px; color: gray;")
            self._layout.addWidget(lbl, 0, col + 1)

        idx = 0
        for row in range(rows):
            row_letter = chr(ord("A") + row)
            hdr = QLabel(row_letter)
            hdr.setAlignment(Qt.AlignmentFlag.AlignCenter)
            hdr.setStyleSheet("font-size: 8px; color: gray;")
            self._layout.addWidget(hdr, row + 1, 0)

            for col in range(cols):
                label = f"{row_letter}{col + 1}"
                pos = positions[idx] if idx < len(positions) else (0.0, 0.0, 0.0)
                btn = _WellMapButton(label)
                btn.clicked.connect(
                    lambda checked=False, p=pos: self.well_clicked.emit(*p)
                )
                self._layout.addWidget(btn, row + 1, col + 1)
                self._buttons[(row, col)] = btn
                self._positions[(row, col)] = pos
                idx += 1

    def clear(self):
        for btn in self._buttons.values():
            btn.deleteLater()
        self._buttons.clear()
        self._positions.clear()
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._placeholder.show()


# ---------------------------------------------------------------------------
# Main CalibrationPanel
# ---------------------------------------------------------------------------

class CalibrationPanel(QWidget):
    """
    Jog controls, Go-To XYZ, corner recording, live camera preview,
    well-plate map, and save/load calibration files.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.hw_manager = hw_manager
        self._session = session_manager

        # ---- Top-level horizontal splitter --------------------------------
        splitter = QSplitter(Qt.Orientation.Horizontal, self)

        # LEFT — large live camera preview
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 4, 0)
        cam_label = QLabel("Live Camera Preview")
        cam_label.setStyleSheet("font-weight: bold; font-size: 11px;")
        left_layout.addWidget(cam_label)
        self._live_preview = _LivePreview()
        left_layout.addWidget(self._live_preview, stretch=1)
        splitter.addWidget(left)

        # RIGHT — controls
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setSpacing(6)
        right_layout.setContentsMargins(4, 0, 0, 0)
        right_layout.addWidget(self._build_movement_group())
        right_layout.addWidget(self._build_calibration_group())
        right_layout.addWidget(self._build_well_map_group())
        right_layout.addWidget(self._build_save_load_group())
        right_layout.addWidget(QuickCaptureWidget("Quick Capture"))
        right_layout.addStretch()

        # Make the right side scrollable
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setWidget(right)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        splitter.addWidget(right_scroll)

        splitter.setSizes([520, 380])
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(splitter)

        self._load_from_session()

        # Position refresh timer
        self._pos_timer = QTimer(self)
        self._pos_timer.timeout.connect(self._update_position_display)
        self._pos_timer.start(500)

        # Camera frame grabber
        self._grabber = _FrameGrabber(fps=15)
        self._grabber.frame_ready.connect(self._live_preview.update_frame)
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
        layout.setSpacing(4)

        # ---- Current position display ----
        pos_row = QHBoxLayout()
        pos_row.addWidget(QLabel("X:"))
        self.x_pos_label = QLabel("0.00")
        self.x_pos_label.setMinimumWidth(48)
        pos_row.addWidget(self.x_pos_label)
        pos_row.addWidget(QLabel("Y:"))
        self.y_pos_label = QLabel("0.00")
        self.y_pos_label.setMinimumWidth(48)
        pos_row.addWidget(self.y_pos_label)
        pos_row.addWidget(QLabel("Z:"))
        self.z_pos_label = QLabel("0.00")
        self.z_pos_label.setMinimumWidth(48)
        pos_row.addWidget(self.z_pos_label)
        pos_row.addStretch()
        layout.addLayout(pos_row, 0, 0, 1, 5)

        # ---- XY jog pad ----
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

        # ---- Z jog ----
        self.z_plus_btn = QPushButton("Z+")
        self.z_plus_btn.setToolTip("Move stage up (+Z).")
        layout.addWidget(self.z_plus_btn, 1, 3)

        self.z_minus_btn = QPushButton("Z-")
        self.z_minus_btn.setToolTip("Move stage down (-Z).")
        layout.addWidget(self.z_minus_btn, 3, 3)

        # ---- Step size ----
        step_grp = QGroupBox("Step Size (mm)")
        step_grp.setToolTip(
            "Distance the stage moves per button press.\n"
            "Use small steps (0.1–0.5 mm) for fine positioning,\n"
            "larger steps (5–10 mm) for coarse traversal."
        )
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

        # ---- Go-To XYZ ----
        goto_grp = QGroupBox("Go To Position")
        goto_grp.setToolTip(
            "Enter absolute XYZ coordinates and press Go to move the stage\n"
            "directly to that position (G0 absolute move)."
        )
        goto_layout = QHBoxLayout(goto_grp)
        goto_layout.addWidget(QLabel("X:"))
        self.goto_x = QLineEdit("0.0")
        self.goto_x.setFixedWidth(55)
        self.goto_x.setToolTip("Target X coordinate in mm.")
        goto_layout.addWidget(self.goto_x)
        goto_layout.addWidget(QLabel("Y:"))
        self.goto_y = QLineEdit("0.0")
        self.goto_y.setFixedWidth(55)
        self.goto_y.setToolTip("Target Y coordinate in mm.")
        goto_layout.addWidget(self.goto_y)
        goto_layout.addWidget(QLabel("Z:"))
        self.goto_z = QLineEdit("0.0")
        self.goto_z.setFixedWidth(55)
        self.goto_z.setToolTip("Target Z coordinate in mm.")
        goto_layout.addWidget(self.goto_z)
        self.goto_btn = QPushButton("Go")
        self.goto_btn.setToolTip(
            "Move the stage to the entered XYZ coordinates.\n"
            "Uses absolute positioning (G90 + G0 X… Y… Z…)."
        )
        self.goto_btn.setFixedWidth(40)
        self.goto_btn.clicked.connect(self._goto_position)
        goto_layout.addWidget(self.goto_btn)
        layout.addWidget(goto_grp, 5, 0, 1, 5)

        # ---- Wire jog buttons ----
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
                f"Record the current stage position as the {name} corner."
            )
            layout.addWidget(set_btn, row * 2 + 1, col * 2, 1, 2)
            self.corners[name] = {"label": pos_label, "button": set_btn, "position": None}
            set_btn.clicked.connect(lambda checked=False, n=name: self._set_corner(n))

        # Well quantity inputs
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

        return grp

    def _build_well_map_group(self) -> QWidget:
        """Build the compact well-plate map widget."""
        self.well_map = WellMapWidget()
        self.well_map.well_clicked.connect(self._goto_xyz)

        # Generate / Clear buttons
        btn_row = QHBoxLayout()
        gen_btn = QPushButton("Generate Well Map")
        gen_btn.setToolTip(
            "Compute all well positions from the four corners and display\n"
            "the clickable well map below. Requires all four corners to be set."
        )
        gen_btn.clicked.connect(self._generate_well_map)
        btn_row.addWidget(gen_btn)

        clear_btn = QPushButton("Clear Map")
        clear_btn.setToolTip("Remove the well map.")
        clear_btn.clicked.connect(self.well_map.clear)
        btn_row.addWidget(clear_btn)

        container = QWidget()
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.addLayout(btn_row)
        vbox.addWidget(self.well_map)
        return container

    def _build_save_load_group(self) -> QGroupBox:
        grp = QGroupBox("Calibration File")
        grp.setToolTip(
            "Save the four corner positions to a JSON file so you can reload\n"
            "them later without re-calibrating.\n"
            "Default save location: Documents/RoboCam/calibrations/"
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

    def _goto_position(self):
        """Move to the XYZ coordinates entered in the Go-To fields."""
        try:
            x = float(self.goto_x.text())
            y = float(self.goto_y.text())
            z = float(self.goto_z.text())
            self._goto_xyz(x, y, z)
        except ValueError:
            QMessageBox.warning(self, "Invalid Input",
                                "Please enter valid numeric values for X, Y, and Z.")

    def _goto_xyz(self, x: float, y: float, z: float):
        """Move the stage to an absolute XYZ position."""
        try:
            self.hw_manager.get_motion_controller().move_absolute(x=x, y=y, z=z)
            # Pre-fill the Go-To fields with the destination so the user can see where they went
            self.goto_x.setText(f"{x:.3f}")
            self.goto_y.setText(f"{y:.3f}")
            self.goto_z.setText(f"{z:.3f}")
            self._update_position_display()
            logger.info(f"[Calibration] Go-To → X:{x:.3f} Y:{y:.3f} Z:{z:.3f}")
        except Exception as e:
            logger.warning(f"[Calibration] Go-To error: {e}")

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
    # Actions — well map
    # ------------------------------------------------------------------

    def _compute_well_positions(self) -> Optional[list]:
        """Return a flat list of (x, y, z) for every well, or None if corners incomplete."""
        corners = [self.corners[n]["position"] for n in CORNER_NAMES]
        if any(c is None for c in corners):
            return None

        cols = self.cols_spin.value()
        rows = self.rows_spin.value()
        ul, ll, ur, lr = corners
        positions = []
        for row_i in range(rows):
            for col_j in range(cols):
                u = col_j / (cols - 1) if cols > 1 else 0.0
                v = row_i / (rows - 1) if rows > 1 else 0.0
                top_x = ul[0] + u * (ur[0] - ul[0])
                top_y = ul[1] + u * (ur[1] - ul[1])
                top_z = ul[2] + u * (ur[2] - ul[2])
                bot_x = ll[0] + u * (lr[0] - ll[0])
                bot_y = ll[1] + u * (lr[1] - ll[1])
                bot_z = ll[2] + u * (lr[2] - ll[2])
                x = top_x + v * (bot_x - top_x)
                y = top_y + v * (bot_y - top_y)
                z = top_z + v * (bot_z - top_z)
                positions.append((x, y, z))
        return positions

    def _generate_well_map(self):
        positions = self._compute_well_positions()
        if positions is None:
            QMessageBox.warning(
                self, "Corners Not Set",
                "Please set all four corner positions before generating the well map."
            )
            return
        self.well_map.build(
            rows=self.rows_spin.value(),
            cols=self.cols_spin.value(),
            positions=positions,
        )
        logger.info(
            f"[Calibration] Well map generated: "
            f"{self.rows_spin.value()}×{self.cols_spin.value()} = {len(positions)} wells."
        )

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

        cal_dir = _default_cal_dir()
        cal_dir.mkdir(parents=True, exist_ok=True)

        path, _ = QFileDialog.getSaveFileName(
            self, "Save Calibration",
            str(cal_dir / "calibration.json"),
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
        cal_dir = _default_cal_dir()
        cal_dir.mkdir(parents=True, exist_ok=True)

        path, _ = QFileDialog.getOpenFileName(
            self, "Load Calibration",
            str(cal_dir),
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

        # Auto-generate the well map after loading
        self._generate_well_map()

    # ------------------------------------------------------------------
    # Public accessors used by ExperimentPanel
    # ------------------------------------------------------------------

    def get_corners(self) -> dict:
        return {k: v["position"] for k, v in self.corners.items()}

    def get_well_dimensions(self) -> tuple[int, int]:
        """Return (cols, rows) from the calibration spinners."""
        return self.cols_spin.value(), self.rows_spin.value()

    def get_well_positions(self) -> Optional[list]:
        """Return computed well positions, or None if corners are not all set."""
        return self._compute_well_positions()

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
        self._session.update_session("calibration", {
            "corners": session_corners,
            "cols": self.cols_spin.value(),
            "rows": self.rows_spin.value(),
        })

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

        # Well dimensions
        self.cols_spin.setValue(int(s.get("cols", 12)))
        self.rows_spin.setValue(int(s.get("rows", 8)))

        # Corners
        saved_corners = s.get("corners", {})
        for name, pos in saved_corners.items():
            if pos is not None and name in self.corners:
                self.corners[name]["position"] = pos
                self.corners[name]["label"].setText(
                    f"X:{pos[0]:.2f}  Y:{pos[1]:.2f}  Z:{pos[2]:.2f}"
                )
                self.corners[name]["label"].setStyleSheet("color: green;")
