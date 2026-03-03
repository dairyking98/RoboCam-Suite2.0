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
    QSizePolicy,
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

    def stop(self):
        self._running = False

    def run(self):
        self._running = True
        interval_ms = max(1, int(1000 / self._fps))
        camera = hw_manager.get_camera()
        _was_connected = False
        while self._running:
            try:
                if camera.is_connected:
                    _was_connected = True
                    frame = camera.read_frame()
                    if frame is not None:
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
        col2_layout.addWidget(self._build_calibration_group())
        col2_layout.addWidget(self._build_save_load_group())
        col2_layout.addWidget(QuickCaptureWidget("Quick Capture"))
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
        self._grabber.camera_disconnected.connect(self._live_preview.show_disconnected)
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

        return grp

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
        save_btn = QPushButton("Save Calibration\u2026")
        save_btn.setToolTip("Save the current corner positions to a .json file.")
        save_btn.clicked.connect(self._save_calibration)
        btn_row.addWidget(save_btn)

        load_btn = QPushButton("Load Calibration\u2026")
        load_btn.setToolTip("Load corner positions from a previously saved .json file.")
        load_btn.clicked.connect(self._load_calibration)
        btn_row.addWidget(load_btn)
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

    def _move(self, axis: str, direction: int):
        try:
            step = float(self.step_size_input.text())
            mc = self.hw_manager.get_motion_controller()
            mc.move_relative(**{axis: direction * step})
            # Sync cache with live position so display is accurate after jog
            mc.query_current_position()
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
        except OSError as e:
            QMessageBox.critical(self, "Save Error", str(e))

    def _load_calibration(self):
        cal_dir = self._get_cal_dir()
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
        """Preset radio clicked — update the text box unless it was the Custom button."""
        if btn is not self._custom_rb:
            self.step_size_input.setText(btn.text())
            self._session.update_session("calibration", {"step_size": btn.text()})

    def _on_custom_step_edited(self, text: str):
        """User typed in the custom field — auto-select the Custom radio button."""
        self._custom_rb.setChecked(True)
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

    def _load_from_session(self):
        s = self._session.get_session("calibration")
        step = s.get("step_size", "1.0")
        self.step_size_input.setText(step)
        matched = False
        for btn in self._step_btn_group.buttons():
            if btn is not self._custom_rb and btn.text() == step:
                btn.setChecked(True)
                matched = True
                break
        if not matched:
            self._custom_rb.setChecked(True)
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
