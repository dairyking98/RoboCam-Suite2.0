"""
Calibration Panel — jog the stage, record well-plate corners, and navigate wells.

Three-column layout
--------------------
Column 1 (large)  : Live camera preview — close-up of whatever the camera sees.
Column 2 (medium) : Movement controls, Go-To XYZ, corner calibration, save/load.
Column 3 (medium) : Well Map — compact clickable grid; click any well to go there.

Well-plate map
--------------
Generated after all four corners are set (or loaded from file).
Clicking any button moves the stage to that well's computed XYZ position.
The map is separate from the live camera feed.
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
    QSizePolicy, QCheckBox,
)
from PySide6.QtCore import Qt, QTimer, QThread, Signal
from PySide6.QtGui import QImage, QPixmap, QPainter, QColor

import cv2

from robocam_suite.hw_manager import hw_manager
from robocam_suite.session_manager import session_manager
from robocam_suite.ui.quick_capture_widget import QuickCaptureWidget
from robocam_suite.ui.well_grid import WellGrid
from robocam_suite.logger import setup_logger

logger = setup_logger()

STEP_PRESETS = ["0.1", "0.5", "1.0", "5.0", "10.0"]
CORNER_NAMES = ["Upper-Left", "Lower-Left", "Upper-Right", "Lower-Right"]


def _default_cal_dir() -> Path:
    return Path.home() / "Documents" / "RoboCam" / "calibrations"


# ---------------------------------------------------------------------------
# Camera frame grabber thread
# ---------------------------------------------------------------------------

class _FrameGrabber(QThread):
    frame_ready = Signal(QImage)
    camera_disconnected = Signal()   # emitted once when camera transitions to disconnected

    def __init__(self, fps: int = 15):
        super().__init__()
        self._fps = fps
        self._running = False
        self._paused = False

    def stop(self):
        self._running = False

    def set_paused(self, paused: bool):
        self._paused = paused
        logger.debug(f"[_FrameGrabber] {'Paused' if paused else 'Resumed'}")

    def run(self):
        self._running = True
        interval_ms = max(1, int(1000 / self._fps))
        _was_connected = False
        while self._running:
            if self._paused:
                self.msleep(100)
                continue
                
            try:
                camera = hw_manager.get_camera()
                if camera and camera.is_connected:
                    _was_connected = True
                    frame = camera.read_frame()
                    if frame is not None:
                        # If we just got a frame, we are definitely connected
                        _was_connected = True
                        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        h, w, ch = rgb.shape
                        qimg = QImage(
                            rgb.data.tobytes(), w, h, ch * w,
                            QImage.Format.Format_RGB888
                        )
                        self.frame_ready.emit(qimg.copy())
                else:
                    if _was_connected:
                        self.camera_disconnected.emit()
                        _was_connected = False
            except Exception:
                pass
            self.msleep(interval_ms)


# ---------------------------------------------------------------------------
# Live camera preview widget
# ---------------------------------------------------------------------------

class _LivePreview(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 240)
        self._pixmap: Optional[QPixmap] = None
        lbl = QLabel("No camera connected\n\nSelect a camera in Setup and click\nApply & Reconnect Camera", self)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet("color: #a0a0a0; font-size: 12px;")
        lbl.setWordWrap(True)
        self._no_cam_lbl = lbl
        layout = QVBoxLayout(self)
        layout.addWidget(lbl)

    def update_frame(self, qimg: QImage):
        self._pixmap = QPixmap.fromImage(qimg)
        self._no_cam_lbl.hide()
        self.update()

    def show_disconnected(self):
        """Re-show the 'no camera' label and clear the last frame."""
        self._pixmap = None
        self._no_cam_lbl.show()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        w, h = self.width(), self.height()
        
        # Draw background or last frame
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

        # If paused (recording), draw a semi-transparent overlay
        parent_panel = self.parent()
        while parent_panel and not hasattr(parent_panel, '_grabber'):
            parent_panel = parent_panel.parent()
        
        if parent_panel and hasattr(parent_panel, '_grabber') and parent_panel._grabber._paused:
            # Semi-transparent black overlay
            painter.fillRect(0, 0, w, h, QColor(0, 0, 0, 160))
            
            # Red "RECORDING" text
            painter.setPen(QColor(255, 50, 50))
            font = painter.font()
            font.setBold(True)
            font.setPointSize(24)
            painter.setFont(font)
            painter.drawText(0, 0, w, h, Qt.AlignmentFlag.AlignCenter, "● RECORDING\n(Preview Paused)")

        painter.end()


# ---------------------------------------------------------------------------
# Well-plate map widget  (compact clickable grid — NOT the camera feed)
# ---------------------------------------------------------------------------

class WellMapWidget(QGroupBox):
    """
    Compact grid for navigating to wells.  Uses the shared WellGrid in
    NAVIGATE mode — a single custom-painted widget, no QPushButton children.
    Clicking any cell emits well_clicked(x, y, z) with the computed position.
    """
    well_clicked = Signal(float, float, float)

    def __init__(self, parent=None):
        super().__init__("Well Map  (click to go to well)", parent)
        self.setToolTip(
            "Compact map of the well plate.\n"
            "Click any well to move the stage directly to that position.\n"
            "Generated automatically after all four corners are set."
        )
        self._positions: list[tuple[float, float, float]] = []
        self._rows = 0
        self._cols = 0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(4)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        outer.addWidget(self._scroll, stretch=1)

        self._placeholder = QLabel("Set all four corners\nor load a calibration\nto build the map.")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet("color: gray; font-size: 10px;")
        outer.addWidget(self._placeholder)

        self._grid: Optional[WellGrid] = None

    def build(self, rows: int, cols: int,
              positions: list[tuple[float, float, float]]):
        self._rows = rows
        self._cols = cols
        self._positions = positions
        self._placeholder.hide()

        if self._grid is not None:
            self._grid.well_clicked.disconnect()
            self._grid.deleteLater()

        self._grid = WellGrid(
            rows=rows, cols=cols,
            mode=WellGrid.Mode.NAVIGATE,
        )
        self._grid.well_clicked.connect(self._on_cell_clicked)
        self._scroll.setWidget(self._grid)

    def clear(self):
        if self._grid is not None:
            self._grid.well_clicked.disconnect()
            self._grid.deleteLater()
            self._grid = None
        self._positions = []
        self._scroll.setWidget(QWidget())  # blank
        self._placeholder.show()

    def _on_cell_clicked(self, row: int, col: int):
        idx = row * self._cols + col
        if 0 <= idx < len(self._positions):
            x, y, z = self._positions[idx]
            self.well_clicked.emit(x, y, z)


# ---------------------------------------------------------------------------
# Main CalibrationPanel
# ---------------------------------------------------------------------------

class CalibrationPanel(QWidget):
    """
    Three-column layout:
      Col 1 — Live camera preview (large)
      Col 2 — Movement controls + corner calibration + save/load
      Col 3 — Well map (full height)
    """

    corners_changed = Signal()  # emitted whenever any corner is set or calibration is loaded

    def __init__(self, parent=None):
        super().__init__(parent)
        self.hw_manager = hw_manager
        self._session = session_manager
        self._is_homed = False # Track homing status

        # Top-level horizontal splitter — three panes
        splitter = QSplitter(Qt.Orientation.Horizontal, self)

        # ---- Column 1: Live camera preview --------------------------------
        col1 = QWidget()
        col1_layout = QVBoxLayout(col1)
        col1_layout.setContentsMargins(0, 0, 4, 0)
        cam_label = QLabel("Live Camera Preview")
        cam_label.setStyleSheet("font-weight: bold; font-size: 11px;")
        col1_layout.addWidget(cam_label)
        self._live_preview = _LivePreview()
        col1_layout.addWidget(self._live_preview, stretch=1)
        splitter.addWidget(col1)

        # ---- Column 2: Controls (scrollable) ------------------------------
        col2_inner = QWidget()
        col2_layout = QVBoxLayout(col2_inner)
        col2_layout.setSpacing(6)
        col2_layout.setContentsMargins(4, 4, 4, 4)
        col2_layout.addWidget(self._build_movement_group())
        col2_layout.addWidget(self._build_camera_control_group())
        col2_layout.addWidget(self._build_calibration_group())
        col2_layout.addWidget(self._build_save_load_group())
        self.quick_capture = QuickCaptureWidget("Quick Capture")
        col2_layout.addWidget(self.quick_capture)
        col2_layout.addStretch()

        col2_scroll = QScrollArea()
        col2_scroll.setWidgetResizable(True)
        col2_scroll.setWidget(col2_inner)
        col2_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        splitter.addWidget(col2_scroll)

        # ---- Column 3: Well map (full height) -----------------------------
        col3 = QWidget()
        col3_layout = QVBoxLayout(col3)
        col3_layout.setContentsMargins(4, 4, 4, 4)
        col3_layout.setSpacing(4)

        self.well_map = WellMapWidget()
        self.well_map.well_clicked.connect(self._goto_xyz)
        col3_layout.addWidget(self.well_map, stretch=1)

        splitter.addWidget(col3)
        
        # Initial refresh of camera controls
        QTimer.singleShot(2000, self._refresh_camera_controls)

        # Proportions: camera gets ~45%, controls ~30%, map ~25%
        splitter.setSizes([540, 360, 300])
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 1)

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
        self._grabber.frame_ready.connect(lambda _: self.quick_capture._update_resolution_label())
        self._grabber.camera_disconnected.connect(self._live_preview.show_disconnected)
        self._grabber.camera_disconnected.connect(self.quick_capture._update_resolution_label)
        self._grabber.start()

        self._last_custom_step = "1.0"

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

        # Current position display
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
        # Custom radio button — selected automatically when user types a value
        self._custom_rb = QRadioButton("Custom:")
        self._custom_rb.setObjectName("step_custom")
        self._step_btn_group.addButton(self._custom_rb, len(STEP_PRESETS))
        step_layout.addWidget(self._custom_rb)
        self.step_size_input = QLineEdit("1.0")
        self.step_size_input.setFixedWidth(55)
        self.step_size_input.setToolTip("Enter any custom step size in mm.")
        step_layout.addWidget(self.step_size_input)
        
        # Clicking a preset radio → fill the text box with that value
        self._step_btn_group.buttonClicked.connect(self._on_step_btn_clicked)
        self.step_size_input.textEdited.connect(self._on_custom_step_edited)
        layout.addWidget(step_grp, 4, 0, 1, 5)

        # Go-To XYZ
        goto_grp = QGroupBox("Go To Position")
        goto_grp.setToolTip(
            "Enter absolute XYZ coordinates and press Go to move the stage\n"
            "directly to that position (G90 + G0 X… Y… Z…)."
        )
        goto_layout = QHBoxLayout(goto_grp)
        goto_layout.addWidget(QLabel("X:"))
        self.goto_x = QLineEdit("0.0")
        self.goto_x.setFixedWidth(55)
        goto_layout.addWidget(self.goto_x)
        goto_layout.addWidget(QLabel("Y:"))
        self.goto_y = QLineEdit("0.0")
        self.goto_y.setFixedWidth(55)
        goto_layout.addWidget(self.goto_y)
        goto_layout.addWidget(QLabel("Z:"))
        self.goto_z = QLineEdit("0.0")
        self.goto_z.setFixedWidth(55)
        goto_layout.addWidget(self.goto_z)
        self.goto_btn = QPushButton("Go")
        self.goto_btn.setToolTip("Move the stage to the entered XYZ coordinates.")
        self.goto_btn.setFixedWidth(40)
        self.goto_btn.clicked.connect(self._goto_position)
        goto_layout.addWidget(self.goto_btn)
        layout.addWidget(goto_grp, 5, 0, 1, 5)

        # Wire jog buttons
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
        layout.setSpacing(4)

        # Spatial arrangement:
        #   grid row 0 → Upper row  (Upper-Left col 0, Upper-Right col 1)
        #   grid row 1 → Lower row  (Lower-Left col 0, Lower-Right col 1)
        # Each corner occupies two layout rows: label+coords on top, button below.
        CORNER_POSITIONS = {
            "Upper-Left":  (0, 0),
            "Upper-Right": (0, 1),
            "Lower-Left":  (1, 0),
            "Lower-Right": (1, 1),
        }

        self.corners: dict = {}
        for name, (plate_row, plate_col) in CORNER_POSITIONS.items():
            grid_row = plate_row * 2   # label row
            grid_col = plate_col * 2   # label col (each corner is 2 cols wide)

            header = QHBoxLayout()
            header.addWidget(QLabel(f"{name}:"))
            pos_label = QLabel("Not Set")
            pos_label.setStyleSheet("color: gray;")
            header.addWidget(pos_label)
            header.addStretch()
            layout.addLayout(header, grid_row, grid_col, 1, 2)

            set_btn = QPushButton(f"Set {name}")
            set_btn.setToolTip(
                f"Record the current stage position as the {name} corner."
            )
            layout.addWidget(set_btn, grid_row + 1, grid_col, 1, 2)
            self.corners[name] = {"label": pos_label, "button": set_btn, "position": None}
            set_btn.clicked.connect(lambda checked=False, n=name: self._set_corner(n))

        qty_row = QHBoxLayout()
        qty_row.addWidget(QLabel("Columns (X):"))
        self.cols_spin = QSpinBox()
        self.cols_spin.setRange(0, 48)
        self.cols_spin.setValue(0)
        self.cols_spin.setToolTip("Number of wells along the X axis (columns).")
        qty_row.addWidget(self.cols_spin)
        qty_row.addWidget(QLabel("Rows (Y):"))
        self.rows_spin = QSpinBox()
        self.rows_spin.setRange(0, 32)
        self.rows_spin.setValue(0)
        self.rows_spin.setToolTip("Number of wells along the Y axis (rows).")
        qty_row.addWidget(self.rows_spin)
        layout.addLayout(qty_row, 4, 0, 1, 4)

        update_map_btn = QPushButton("Update Well Map")
        update_map_btn.setToolTip(
            "Recompute well positions from the current corners and dimensions\n"
            "and refresh the well map on the right."
        )
        update_map_btn.clicked.connect(self._on_update_well_map)
        layout.addWidget(update_map_btn, 5, 0, 1, 4)

        return grp

    def _build_camera_control_group(self) -> QGroupBox:
        grp = QGroupBox("Camera Controls")
        layout = QGridLayout(grp)
        layout.setSpacing(4)
        layout.setContentsMargins(6, 6, 6, 6)

        # Exposure
        layout.addWidget(QLabel("Exposure:"), 0, 0)
        exp_row = QHBoxLayout()
        self.exp_spin = QSpinBox()
        self.exp_spin.setRange(1, 2000) # 1ms to 2s
        self.exp_spin.setSingleStep(10)
        self.exp_spin.setSuffix(" ms")
        self.exp_spin.valueChanged.connect(self._on_camera_params_changed)
        exp_row.addWidget(self.exp_spin)
        
        self.auto_exp_check = QCheckBox("Auto")
        self.auto_exp_check.setToolTip("Enable hardware auto-exposure.")
        self.auto_exp_check.toggled.connect(self._on_camera_params_changed)
        exp_row.addWidget(self.auto_exp_check)
        layout.addLayout(exp_row, 0, 1)

        # Gain
        layout.addWidget(QLabel("Gain:"), 1, 0)
        gain_row = QHBoxLayout()
        self.gain_spin = QSpinBox()
        self.gain_spin.setRange(0, 1000)
        self.gain_spin.setSingleStep(10)
        self.gain_spin.valueChanged.connect(self._on_camera_params_changed)
        gain_row.addWidget(self.gain_spin)
        
        self.auto_gain_check = QCheckBox("Auto")
        self.auto_gain_check.setToolTip("Enable hardware auto-gain.")
        self.auto_gain_check.toggled.connect(self._on_camera_params_changed)
        gain_row.addWidget(self.auto_gain_check)
        layout.addLayout(gain_row, 1, 1)

        # Target Brightness
        layout.addWidget(QLabel("Target Brightness:"), 2, 0)
        self.brightness_spin = QSpinBox()
        self.brightness_spin.setRange(0, 255)
        self.brightness_spin.setValue(100)
        self.brightness_spin.setToolTip("Target brightness level for Auto Exposure/Gain.")
        self.brightness_spin.valueChanged.connect(self._on_camera_params_changed)
        layout.addWidget(self.brightness_spin, 2, 1)

        # USB Bandwidth
        layout.addWidget(QLabel("USB Bandwidth:"), 3, 0)
        self.bandwidth_spin = QSpinBox()
        self.bandwidth_spin.setRange(35, 100)
        self.bandwidth_spin.setValue(80)
        self.bandwidth_spin.setSuffix("%")
        self.bandwidth_spin.setToolTip("USB bandwidth limit (reduce if experiencing frame drops).")
        self.bandwidth_spin.valueChanged.connect(self._on_camera_params_changed)
        layout.addWidget(self.bandwidth_spin, 3, 1)

        # Hardware Binning
        self.binning_check = QCheckBox("Enable Hardware Binning (2x2)")
        self.binning_check.setToolTip("Combine 2x2 pixels to increase sensitivity (halves resolution).")
        self.binning_check.toggled.connect(self._on_camera_params_changed)
        layout.addWidget(self.binning_check, 4, 0, 1, 2)

        # Refresh button
        refresh_btn = QPushButton("Refresh Controls")
        refresh_btn.setToolTip("Read current settings from the camera.")
        refresh_btn.clicked.connect(self._refresh_camera_controls)
        layout.addWidget(refresh_btn, 5, 0, 1, 2)

        reset_btn = QPushButton("Reset to Defaults")
        reset_btn.setToolTip("Reset all camera controls to their default values.")
        reset_btn.clicked.connect(self._reset_camera_controls_to_defaults)
        layout.addWidget(reset_btn, 6, 0, 1, 2)

        return grp

    def _refresh_camera_controls(self):
        """
        Refresh the UI with the camera's current hardware settings, 
        OR apply the session's saved settings to the hardware if they differ.
        """
        camera = hw_manager.get_camera()
        if camera.is_connected:
            # If we just connected, we might want to PUSH our saved session settings 
            # to the hardware instead of pulling them from the hardware.
            # This ensures the camera starts with the user's last-known-good configuration.
            self._on_camera_params_changed()
            
            # Now block signals and refresh the UI values from the hardware 
            # (to confirm they were applied correctly)
            self.exp_spin.blockSignals(True)
            self.gain_spin.blockSignals(True)
            self.auto_exp_check.blockSignals(True)
            self.auto_gain_check.blockSignals(True)
            self.brightness_spin.blockSignals(True)
            self.bandwidth_spin.blockSignals(True)
            self.binning_check.blockSignals(True)
            
            try:
                # Basic controls
                # SDK uses microseconds, UI uses milliseconds
                self.exp_spin.setValue(int(camera.get_exposure() / 1000))
                self.gain_spin.setValue(int(camera.get_gain()))
                
                # Advanced controls
                if hasattr(camera, 'get_auto_exposure'):
                    self.auto_exp_check.setChecked(camera.get_auto_exposure())
                    self.auto_gain_check.setChecked(camera.get_auto_gain())
                    self.brightness_spin.setValue(camera.get_target_brightness())
                    self.bandwidth_spin.setValue(camera.get_usb_bandwidth())
                    self.binning_check.setChecked(camera.get_hardware_bin())
            except Exception as e:
                logger.warning(f"[Calibration] Refresh camera controls failed: {e}")
            
            self.exp_spin.blockSignals(False)
            self.gain_spin.blockSignals(False)
            self.auto_exp_check.blockSignals(False)
            self.auto_gain_check.blockSignals(False)
            self.brightness_spin.blockSignals(False)
            self.bandwidth_spin.blockSignals(False)
            self.binning_check.blockSignals(False)
    def _on_camera_params_changed(self):
        # Persist to session immediately so it\'s not lost
        self._session.update_session("camera_settings", {
            "exposure_ms": self.exp_spin.value(),
            "gain": self.gain_spin.value(),
            "auto_exposure": self.auto_exp_check.isChecked(),
            "auto_gain": self.auto_gain_check.isChecked(),
            "target_brightness": self.brightness_spin.value(),
            "usb_bandwidth": self.bandwidth_spin.value(),
            "hardware_bin": self.binning_check.isChecked(),
        })

        camera = hw_manager.get_camera()
        if camera.is_connected:
            try:
                # Basic controls
                camera.set_exposure(int(self.exp_spin.value() * 1000))
                camera.set_gain(int(self.gain_spin.value()))
                
                # Advanced controls
                if hasattr(camera, 'set_auto_exposure'):
                    camera.set_auto_exposure(self.auto_exp_check.isChecked())
                    camera.set_auto_gain(self.auto_gain_check.isChecked())
                    camera.set_target_brightness(int(self.brightness_spin.value()))
                    camera.set_usb_bandwidth(int(self.bandwidth_spin.value()))
                    camera.set_hardware_bin(self.binning_check.isChecked())
                    
                # Enable/disable spins based on auto state
                self.exp_spin.setEnabled(not self.auto_exp_check.isChecked())
                self.gain_spin.setEnabled(not self.auto_gain_check.isChecked())
            except Exception as e:
                logger.warning(f"[Calibration] Apply camera params failed: {e}")

    def _build_save_load_group(self) -> QGroupBox:
        grp = QGroupBox("Calibration File")
        grp.setToolTip(
            "Save the four corner positions to a JSON file so you can reload\n"
            "them later without re-calibrating."
        )
        root = QVBoxLayout(grp)
        root.setSpacing(3)
        root.setContentsMargins(6, 6, 6, 6)

        # Row 1 — buttons
        btn_row = QHBoxLayout()
        save_btn = QPushButton("Update \u0026 Save Calibration\u2026")
        save_btn.setToolTip(
            "Refresh the well map from current corners/dimensions, then\n"
            "save everything to a .json file."
        )
        save_btn.clicked.connect(self._save_calibration)
        btn_row.addWidget(save_btn)

        load_btn = QPushButton("Load Calibration\u2026")
        load_btn.setToolTip("Load corner positions from a previously saved .json file.")
        load_btn.clicked.connect(self._load_calibration)
        btn_row.addWidget(load_btn)

        update_map_btn = QPushButton("Update Well Map")
        update_map_btn.setToolTip("Force refresh the well map grid from current corners and dimensions.")
        update_map_btn.clicked.connect(self._rebuild_well_map)
        btn_row.addWidget(update_map_btn)
        
        root.addLayout(btn_row)

        # Row 2 — gray path label + ... folder button
        path_row = QHBoxLayout()
        self._cal_dir_label = QLabel(str(_default_cal_dir()))
        self._cal_dir_label.setStyleSheet(
            "font-size: 10px; color: #888; font-style: italic;"
        )
        self._cal_dir_label.setToolTip("Default folder for calibration files.")
        path_row.addWidget(self._cal_dir_label, stretch=1)

        cal_folder_btn = QPushButton("\u2026")
        cal_folder_btn.setFixedWidth(28)
        cal_folder_btn.setToolTip("Change the default calibration folder.")
        cal_folder_btn.clicked.connect(self._choose_cal_folder)
        path_row.addWidget(cal_folder_btn)
        root.addLayout(path_row)

        # Row 3 — status label
        self._cal_status_label = QLabel("")
        self._cal_status_label.setStyleSheet("font-size: 10px; color: green;")
        root.addWidget(self._cal_status_label)

        return grp

    # ------------------------------------------------------------------
    # Actions — movement
    # ------------------------------------------------------------------

    def _get_current_step_size(self) -> float:
        """Get the actual step size based on the selected radio button."""
        checked_btn = self._step_btn_group.checkedButton()
        if checked_btn and checked_btn != self._custom_rb:
            try:
                return float(checked_btn.text())
            except ValueError:
                pass
        
        # Fallback to custom input if "Custom" is selected or parsing fails
        try:
            return float(self.step_size_input.text())
        except ValueError:
            return 1.0

    def _move(self, axis: str, direction: int):
        try:
            step = self._get_current_step_size()
            mc = self.hw_manager.get_motion_controller()
            mc.move_relative(**{axis: direction * step})
            # Sync cache with live position so display is accurate after jog
            mc.query_current_position()
            self._update_position_display()
            self._is_homed = True
            self._set_movement_controls_enabled(True)
        except Exception as e:
            logger.warning(f"[Calibration] Move error: {e}")

    def _home(self):
        try:
            self.hw_manager.get_motion_controller().home()
            self._update_position_display()
        except Exception as e:
            logger.warning(f"[Calibration] Home error: {e}")

    def _goto_position(self):
        """Move to the entered XYZ position.

        If any axis field is left empty, the current stage position for that
        axis is used — matching the 1.0 behaviour where an empty field means
        "don't change this axis".
        """
        try:
            # Use cached position (no serial command) — just to fill empty fields
            current = self.hw_manager.get_motion_controller().get_current_position()
        except Exception as e:
            logger.warning(f"[Calibration] Could not read current position: {e}")
            current = (0.0, 0.0, 0.0)

        def _parse(text: str, fallback: float) -> float:
            stripped = text.strip()
            if stripped == "":
                return fallback
            return float(stripped)  # raises ValueError if invalid

        try:
            x = _parse(self.goto_x.text(), current[0])
            y = _parse(self.goto_y.text(), current[1])
            z = _parse(self.goto_z.text(), current[2])
        except ValueError:
            QMessageBox.warning(self, "Invalid Input",
                                "Please enter valid numeric values (or leave blank to keep current position).")
            return

        self._goto_xyz(x, y, z)

    def _goto_xyz(self, x: float, y: float, z: float):
        try:
            mc = self.hw_manager.get_motion_controller()
            mc.move_absolute(x=x, y=y, z=z)
            # Sync cache with live position so display is accurate after go-to
            mc.query_current_position()
            self.goto_x.setText(f"{x:.3f}")
            self.goto_y.setText(f"{y:.3f}")
            self.goto_z.setText(f"{z:.3f}")
            self._update_position_display()
            logger.info(f"[Calibration] Go-To → X:{x:.3f} Y:{y:.3f} Z:{z:.3f}")
        except Exception as e:
            logger.warning(f"[Calibration] Go-To error: {e}")

    def _set_corner(self, name: str):
        try:
            # Query live position from printer so the corner is accurate
            pos = self.hw_manager.get_motion_controller().query_current_position()
            self.corners[name]["position"] = list(pos)
            self.corners[name]["label"].setText(
                f"X:{pos[0]:.2f}  Y:{pos[1]:.2f}  Z:{pos[2]:.2f}"
            )
            self.corners[name]["label"].setStyleSheet("color: green;")
            self._persist_corners()
            # Auto-generate the well map whenever all four corners are now set
            self._try_auto_generate_well_map()
            self.corners_changed.emit()
        except Exception as e:
            logger.warning(f"[Calibration] Set corner error: {e}")

    # ------------------------------------------------------------------
    # Actions — well map
    # ------------------------------------------------------------------

    def _try_auto_generate_well_map(self):
        """Generate the well map silently if all four corners are set."""
        if all(self.corners[n]["position"] is not None for n in CORNER_NAMES):
            self._generate_well_map()

    def _on_update_well_map(self):
        """Explicit 'Update Well Map' button handler."""
        cols = self.cols_spin.value()
        rows = self.rows_spin.value()
        missing = [n for n in CORNER_NAMES if self.corners[n]["position"] is None]
        if missing:
            self._cal_status_label.setText(
                f"Cannot update map — corners not set: {', '.join(missing)}"
            )
            self._cal_status_label.setStyleSheet("font-size: 10px; color: red;")
            return
        if rows == 0 or cols == 0:
            self._cal_status_label.setText(
                "Cannot update map — set Rows and Columns first."
            )
            self._cal_status_label.setStyleSheet("font-size: 10px; color: red;")
            return
        self._generate_well_map()
        self._cal_status_label.setText(
            f"Well map updated: {rows} rows \u00d7 {cols} cols"
        )
        self._cal_status_label.setStyleSheet("font-size: 10px; color: green;")
        self.corners_changed.emit()

    def _compute_well_positions(self) -> Optional[list]:
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

    def _rebuild_well_map(self):
        """Force a rebuild of the well map from current corners and dimensions."""
        self._generate_well_map()
        self.corners_changed.emit()

    def _generate_well_map(self):
        positions = self._compute_well_positions()
        if positions is None:
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

    def _choose_cal_folder(self):
        """Let the user pick a different default calibration folder."""
        folder = QFileDialog.getExistingDirectory(
            self, "Select Calibration Folder",
            str(getattr(self, "_cal_dir", _default_cal_dir()))
        )
        if folder:
            self._cal_dir = Path(folder)
            self._cal_dir.mkdir(parents=True, exist_ok=True)
            self._cal_dir_label.setText(str(self._cal_dir))

    def _get_cal_dir(self) -> Path:
        """Return the active calibration directory (custom or default)."""
        d = getattr(self, "_cal_dir", _default_cal_dir())
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _save_calibration(self):
        corners = {n: self.corners[n]["position"] for n in CORNER_NAMES}
        if any(v is None for v in corners.values()):
            QMessageBox.warning(self, "Incomplete Calibration",
                                "Please set all four corner positions before saving.")
            return
        cal_dir = self._get_cal_dir()
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
            self._cal_status_label.setStyleSheet("font-size: 10px; color: #888;")
            logger.info(f"[Calibration] Saved to {path}")
            session_manager.update_session("calibration", {"last_calibration_path": str(path)})
        except OSError as e:
            QMessageBox.critical(self, "Save Error", str(e))

    def _load_calibration(self, path: Optional[Path] = None):
        if path is None:
            cal_dir = self._get_cal_dir()
            path, _ = QFileDialog.getOpenFileName(
                self, "Load Calibration",
                str(cal_dir),
                "JSON Files (*.json)"
            )
            if not path:
                # User cancelled, do not load anything and do not save a 'False' path
                session_manager.update_session("calibration", {"last_calibration_path": None})
                return False
            else:
            # Ensure path is a Path object if it came from session_manager as str
            path = Path(path)
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
        self._cal_status_label.setStyleSheet("font-size: 10px; color: #888;")
        logger.info(f"[Calibration] Loaded from {path}")
        self._generate_well_map()
        self.corners_changed.emit()

    # ------------------------------------------------------------------
    # Public accessors used by ExperimentPanel
    # ------------------------------------------------------------------

    def get_corners(self) -> dict:
        return {k: v["position"] for k, v in self.corners.items()}

    def get_well_dimensions(self) -> tuple[int, int]:
        """Return (cols, rows)."""
        return self.cols_spin.value(), self.rows_spin.value()

    def get_well_positions(self) -> Optional[list]:
        return self._compute_well_positions()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _on_step_btn_clicked(self, btn):
        """Preset radio clicked — keep custom input visible."""
        if btn is not self._custom_rb:
            # Preset selected - DONT change the input box so the user can still see their custom value
            self._session.update_session("calibration", {"step_size": btn.text()})
        else:
            # Re-selected "Custom"
            self._session.update_session("calibration", {"step_size": self.step_size_input.text()})

    def _on_custom_step_edited(self, text: str):
        """User typed in the custom field — auto-select the Custom radio button."""
        self._last_custom_step = text
        self._custom_rb.setChecked(True)
        self._session.update_session("calibration", {
            "step_size": text,
            "custom_step_size": text
        })

    def _update_position_display(self):
        try:
            mc = self.hw_manager.get_motion_controller()
            pos = mc.get_current_position()
            self.x_pos_label.setText(f"{pos[0]:.2f}")
            self.y_pos_label.setText(f"{pos[1]:.2f}")
            self.z_pos_label.setText(f"{pos[2]:.2f}")

            # Check if homed (not 0,0,0) and enable controls if not already
            if not self._is_homed and (pos[0] != 0.0 or pos[1] != 0.0 or pos[2] != 0.0):
                self._is_homed = True
                self._set_movement_controls_enabled(True)
                self._set_camera_controls_enabled(True)

        except Exception as e:
            logger.error(f"[CalibrationPanel] Error updating position display: {e}")
            self.x_pos_label.setText("ERR")
            self.y_pos_label.setText("ERR")
            self.z_pos_label.setText("ERR")
            
            # Show a small homing warning in the status label if at 0,0,0 on startup
            if mc.is_connected and pos == (0.0, 0.0, 0.0) and not self._is_homed:
                if not self._cal_status_label.text(): # Only set if no other message is present
                    self._cal_status_label.setStyleSheet("font-size: 10px; color: orange;")
                    self._cal_status_label.setText("Printer not homed. Please click 'Home' before moving.")
            elif self._is_homed and self._cal_status_label.text() == "Printer not homed. Please click 'Home' before moving.":
                self._cal_status_label.setStyleSheet("font-size: 10px; color: green;")
                self._cal_status_label.setText("")
        except Exception:
            pass

    def _persist_corners(self):
        session_corners = {k: v["position"] for k, v in self.corners.items()}
        self._session.update_session("calibration", {
            "corners": session_corners,
            "cols": self.cols_spin.value(),
            "rows": self.rows_spin.value(),
        })

    def _load_from_session(self):
        s = self._session.get_session("calibration")
        step = s.get("step_size", "1.0")

        camera_s = self._session.get_session("camera_settings")
        if camera_s:
            self.exp_spin.setValue(camera_s.get("exposure_ms", 20))
            self.gain_spin.setValue(camera_s.get("gain", 100))
            self.auto_exp_check.setChecked(camera_s.get("auto_exposure", False))
            self.auto_gain_check.setChecked(camera_s.get("auto_gain", False))
            self.brightness_spin.setValue(camera_s.get("target_brightness", 100))
            self.bandwidth_spin.setValue(camera_s.get("usb_bandwidth", 50))
            self.binning_check.setChecked(camera_s.get("hardware_bin", False))
        
        matched = False
        for btn in self._step_btn_group.buttons():
            if btn is not self._custom_rb and btn.text() == step:
                btn.setChecked(True)
                matched = True
                break
        
        if not matched:
            self._custom_rb.setChecked(True)
            self.step_size_input.setText(step)
            self._last_custom_step = step
        else:
            # If session loaded a preset, we still want to load the last custom step
            # into the input box so it's visible.
            custom_step = s.get("custom_step_size", "1.0")
            self.step_size_input.setText(custom_step)
            self._last_custom_step = custom_step
            


        # Load camera settings from session
        self.exp_spin.blockSignals(True)
        self.gain_spin.blockSignals(True)

        # Load last used calibration file
        last_cal_path = session_manager.get_session("calibration").get("last_calibration_path")
        if last_cal_path and last_cal_path != "None": # Check for both None and the string "None"
            logger.info(f"[Calibration] Auto-loading calibration from {last_cal_path}")
            self._load_calibration(Path(last_cal_path))

        # Initial check for homing status
        self._update_position_display()

        # Check initial printer position and enforce homing if at (0,0,0)
        initial_pos = self.hw_manager.get_motion_controller().get_current_position()
        if initial_pos == (0.0, 0.0, 0.0):
            self._set_movement_controls_enabled(False)
            self._set_camera_controls_enabled(False)
            self._cal_status_label.setText("<b style=\"color: red;\">Homing Required: Printer at (0,0,0). Please Home.</b>")
        else:
            self._set_movement_controls_enabled(True)
            self._set_camera_controls_enabled(True)
            self._cal_status_label.setText("Ready.")

    def _set_movement_controls_enabled(self, enabled: bool):
        self.y_plus_btn.setEnabled(enabled)
        self.x_minus_btn.setEnabled(enabled)
        self.x_plus_btn.setEnabled(enabled)
        self.y_minus_btn.setEnabled(enabled)
        self.z_plus_btn.setEnabled(enabled)
        self.z_minus_btn.setEnabled(enabled)
        self.step_size_input.setEnabled(enabled)
        self.goto_x.setEnabled(enabled)
        self.goto_y.setEnabled(enabled)
        self.goto_z.setEnabled(enabled)
        self.goto_btn.setEnabled(enabled)

        # Enable/disable all radio buttons in the step size group
        for btn in self._step_btn_group.buttons():
            btn.setEnabled(enabled)

        # The home button should always be enabled
        self.home_btn.setEnabled(True)

    def _set_camera_controls_enabled(self, enabled: bool):
        self.exp_spin.setEnabled(enabled)
        self.gain_spin.setEnabled(enabled)
        self.auto_exp_check.setEnabled(enabled)
        self.auto_gain_check.setEnabled(enabled)
        self.brightness_spin.setEnabled(enabled)
        self.bandwidth_spin.setEnabled(enabled)
        self.binning_check.setEnabled(enabled)

        # Re-apply auto-exposure/gain logic
        if enabled:
            self.exp_spin.setEnabled(not self.auto_exp_check.isChecked())
            self.gain_spin.setEnabled(not self.auto_gain_check.isChecked())

    def _reset_camera_controls_to_defaults(self):
        """Resets all camera control UI elements to their default values and applies them."""
        self.exp_spin.setValue(20) # Default 20ms
        self.gain_spin.setValue(100) # Default 100
        self.auto_exp_check.setChecked(False)
        self.auto_gain_check.setChecked(False)
        self.brightness_spin.setValue(100) # Default 100
        self.bandwidth_spin.setValue(80) # Default 80%
        self.binning_check.setChecked(False)
        
        # Force update the camera with default values
        self._on_camera_params_changed()
        logger.info("[Calibration] Camera controls reset to defaults.")


        # Attempt to auto-load the most recently saved calibration file;
        # only fall back to bare session values if no file is found.
        if not self._auto_load_latest_calibration():
            self.cols_spin.setValue(int(s.get("cols", 0)))
            self.rows_spin.setValue(int(s.get("rows", 0)))
            saved_corners = s.get("corners", {})
            for name, pos in saved_corners.items():
                if pos is not None and name in self.corners:
                    self.corners[name]["position"] = pos
                    self.corners[name]["label"].setText(
                        f"X:{pos[0]:.2f}  Y:{pos[1]:.2f}  Z:{pos[2]:.2f}"
                    )
                    self.corners[name]["label"].setStyleSheet("color: green;")
            
            self._generate_well_map()
            self.corners_changed.emit()

    def _auto_load_latest_calibration(self) -> bool:
        """Find the most recently modified .json file in the calibration
        directory and load it silently.  Returns True if a file was loaded."""
        cal_dir = _default_cal_dir()
        if not cal_dir.exists():
            return False
        json_files = sorted(
            cal_dir.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not json_files:
            return False
        path = json_files[0]
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(f"[Calibration] Auto-load failed for {path}: {e}")
            return False

        corners = data.get("corners", {})
        for name in CORNER_NAMES:
            pos = corners.get(name)
            if pos is not None:
                self.corners[name]["position"] = pos
                self.corners[name]["label"].setText(
                    f"X:{pos[0]:.2f}  Y:{pos[1]:.2f}  Z:{pos[2]:.2f}"
                )
                self.corners[name]["label"].setStyleSheet("color: green;")
            # Corners absent from the file are left as "Not Set" (no change)

        if "cols" in data:
            self.cols_spin.setValue(int(data["cols"]))
        if "rows" in data:
            self.rows_spin.setValue(int(data["rows"]))

        self._cal_status_label.setText(f"Loaded: {path.name}")
        self._cal_status_label.setStyleSheet("font-size: 10px; color: #888;")
        self._generate_well_map()
        self.corners_changed.emit()
        return True
