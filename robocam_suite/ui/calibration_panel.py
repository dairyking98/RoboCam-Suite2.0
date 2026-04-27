import json
import logging
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QDoubleSpinBox, QGroupBox, QRadioButton, QButtonGroup, QFileDialog, QMessageBox, QComboBox, QCheckBox)
from PySide6.QtGui import QPainter, QColor
from robocam_suite.session_manager import session_manager

# from robocam_suite.ui.well_map_widget import WellMapWidget

logger = logging.getLogger(__name__)

from robocam_suite.ui.well_grid import WellGrid

class WellMapWidget(QWidget):
    well_clicked = Signal(float, float, float)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        
        self.grid = WellGrid(mode=WellGrid.Mode.NAVIGATE)
        self.grid.well_clicked.connect(self._on_grid_clicked)
        self.layout.addWidget(self.grid)
        
        self._rows = 0
        self._cols = 0
        self._tl = None
        self._tr = None
        self._bl = None
        self._br = None

    def set_well_grid(self, rows, cols, tl, tr, bl, br):
        self._rows = rows
        self._cols = cols
        self._tl = tl
        self._tr = tr
        self._bl = bl
        self._br = br
        self.grid.rebuild(rows, cols)

    def clear(self):
        self._rows = 0
        self._cols = 0
        self.grid.rebuild(0, 0)

    def _on_grid_clicked(self, r, c):
        if self._rows <= 0 or self._cols <= 0 or not self._tl:
            return
            
        # Bilinear interpolation
        u = c / (self._cols - 1) if self._cols > 1 else 0.5
        v = r / (self._rows - 1) if self._rows > 1 else 0.5
        
        x = (1-u)*(1-v)*self._tl[0] + u*(1-v)*self._tr[0] + (1-u)*v*self._bl[0] + u*v*self._br[0]
        y = (1-u)*(1-v)*self._tl[1] + u*(1-v)*self._tr[1] + (1-u)*v*self._bl[1] + u*v*self._br[1]
        z = (1-u)*(1-v)*self._tl[2] + u*(1-v)*self._tr[2] + (1-u)*v*self._bl[2] + u*v*self._br[2]
        
        self.well_clicked.emit(x, y, z)

CORNER_NAMES = ["Upper-Left", "Upper-Right", "Lower-Left", "Lower-Right"]
STEP_PRESETS = ["0.1", "1.0", "10.0", "100.0"]

class CalibrationPanel(QWidget):
    corners_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        from robocam_suite.hw_manager import hw_manager
        self.hw_manager = hw_manager
        self._is_homed = False

        self.corners = {
            "Upper-Left": {"position": None, "label": QLabel("Not Set")},
            "Upper-Right": {"position": None, "label": QLabel("Not Set")},
            "Lower-Left": {"position": None, "label": QLabel("Not Set")},
            "Lower-Right": {"position": None, "label": QLabel("Not Set")},
        }

        self.init_ui()
        self._load_from_session()

        # Timer to periodically update position display
        self.position_timer = QTimer(self)
        self.position_timer.setInterval(1000)  # 1 second
        self.position_timer.timeout.connect(self._update_position_display)
        self.position_timer.start()

    def init_ui(self):
        main_layout = QVBoxLayout()

        # Status Label
        self._cal_status_label = QLabel("Initializing...")
        self._cal_status_label.setStyleSheet("font-size: 10px; color: #888;")
        main_layout.addWidget(self._cal_status_label)

        # Movement Group
        main_layout.addWidget(self._build_movement_group())

        # Camera Control Group
        main_layout.addWidget(self._build_camera_control_group())

        # Corner Setting Group
        main_layout.addWidget(self._build_corner_setting_group())

        # Well Map Group
        main_layout.addWidget(self._build_well_map_group())

        # Save/Load Calibration Group
        main_layout.addWidget(self._build_save_load_group())

        self.setLayout(main_layout)

    def _build_movement_group(self):
        group = QGroupBox("Movement")
        layout = QVBoxLayout()

        # Current Position Display
        pos_layout = QHBoxLayout()
        pos_layout.addWidget(QLabel("Current Position:"))
        self.x_pos_label = QLabel("X: --")
        self.y_pos_label = QLabel("Y: --")
        self.z_pos_label = QLabel("Z: --")
        pos_layout.addWidget(self.x_pos_label)
        pos_layout.addWidget(self.y_pos_label)
        pos_layout.addWidget(self.z_pos_label)
        layout.addLayout(pos_layout)

        # Homing Button
        self.home_btn = QPushButton("Home Printer")
        self.home_btn.clicked.connect(self._on_home_clicked)
        layout.addWidget(self.home_btn)

        # Step Size
        step_layout = QHBoxLayout()
        step_layout.addWidget(QLabel("Step Size:"))
        self.step_size_group = QButtonGroup(self)
        self._custom_rb = QRadioButton("Custom")
        self.step_size_input = QDoubleSpinBox()
        self.step_size_input.setRange(0.001, 1000.0)
        self.step_size_input.setSingleStep(0.1)
        self.step_size_input.setDecimals(3)
        self.step_size_input.valueChanged.connect(lambda v: self._on_custom_step_edited(str(v)))

        for preset in STEP_PRESETS:
            rb = QRadioButton(preset)
            self.step_size_group.addButton(rb)
            step_layout.addWidget(rb)
            rb.clicked.connect(lambda checked, b=rb: self._on_step_btn_clicked(b))

        self.step_size_group.addButton(self._custom_rb)
        step_layout.addWidget(self._custom_rb)
        step_layout.addWidget(self.step_size_input)
        layout.addLayout(step_layout)

        # Movement Buttons
        grid_layout = QVBoxLayout()
        btn_size = 40

        # Y movement
        y_layout = QHBoxLayout()
        y_layout.addStretch()
        self.y_plus_btn = QPushButton("Y+")
        self.y_plus_btn.setFixedSize(btn_size, btn_size)
        self.y_plus_btn.clicked.connect(lambda: self.hw_manager.get_motion_controller().move_y(self.step_size_input.value()))
        y_layout.addWidget(self.y_plus_btn)
        y_layout.addStretch()
        grid_layout.addLayout(y_layout)

        # X movement
        x_layout = QHBoxLayout()
        self.x_minus_btn = QPushButton("X-")
        self.x_minus_btn.setFixedSize(btn_size, btn_size)
        self.x_minus_btn.clicked.connect(lambda: self.hw_manager.get_motion_controller().move_x(-self.step_size_input.value()))
        x_layout.addWidget(self.x_minus_btn)
        x_layout.addStretch()
        self.x_plus_btn = QPushButton("X+")
        self.x_plus_btn.setFixedSize(btn_size, btn_size)
        self.x_plus_btn.clicked.connect(lambda: self.hw_manager.get_motion_controller().move_x(self.step_size_input.value()))
        x_layout.addWidget(self.x_plus_btn)
        grid_layout.addLayout(x_layout)

        # Y movement
        y_layout_neg = QHBoxLayout()
        y_layout_neg.addStretch()
        self.y_minus_btn = QPushButton("Y-")
        self.y_minus_btn.setFixedSize(btn_size, btn_size)
        self.y_minus_btn.clicked.connect(lambda: self.hw_manager.get_motion_controller().move_y(-self.step_size_input.value()))
        y_layout_neg.addWidget(self.y_minus_btn)
        y_layout_neg.addStretch()
        grid_layout.addLayout(y_layout_neg)

        layout.addLayout(grid_layout)

        # Z movement
        z_layout = QHBoxLayout()
        z_layout.addWidget(QLabel("Z-Axis:"))
        self.z_minus_btn = QPushButton("Z-")
        self.z_minus_btn.setFixedSize(btn_size, btn_size)
        self.z_minus_btn.clicked.connect(lambda: self.hw_manager.get_motion_controller().move_z(-self.step_size_input.value()))
        z_layout.addWidget(self.z_minus_btn)
        self.z_plus_btn = QPushButton("Z+")
        self.z_plus_btn.setFixedSize(btn_size, btn_size)
        self.z_plus_btn.clicked.connect(lambda: self.hw_manager.get_motion_controller().move_z(self.step_size_input.value()))
        z_layout.addWidget(self.z_plus_btn)
        layout.addLayout(z_layout)

        # Go to XYZ
        go_to_layout = QHBoxLayout()
        go_to_layout.addWidget(QLabel("Go to:"))
        self.x_go_to_input = QDoubleSpinBox()
        self.x_go_to_input.setRange(-1000.0, 1000.0)
        self.y_go_to_input = QDoubleSpinBox()
        self.y_go_to_input.setRange(-1000.0, 1000.0)
        self.z_go_to_input = QDoubleSpinBox()
        self.z_go_to_input.setRange(-1000.0, 1000.0)
        go_to_layout.addWidget(self.x_go_to_input)
        go_to_layout.addWidget(self.y_go_to_input)
        go_to_layout.addWidget(self.z_go_to_input)
        self.go_to_xyz_btn = QPushButton("Go")
        self.go_to_xyz_btn.clicked.connect(self._on_go_to_xyz_clicked)
        go_to_layout.addWidget(self.go_to_xyz_btn)
        layout.addLayout(go_to_layout)

        group.setLayout(layout)
        return group

    def _build_camera_control_group(self):
        group = QGroupBox("Camera Controls")
        layout = QVBoxLayout()

        # Auto Exposure
        self.auto_exp_check = QCheckBox("Auto Exposure")
        self.auto_exp_check.clicked.connect(self._on_camera_params_changed)
        layout.addWidget(self.auto_exp_check)

        # Exposure
        exp_layout = QHBoxLayout()
        exp_layout.addWidget(QLabel("Exposure (us):"))
        self.exp_spin = QDoubleSpinBox()
        self.exp_spin.setRange(1.0, 1000000.0) # 1us to 1s
        self.exp_spin.setSingleStep(1000.0)
        self.exp_spin.setDecimals(0)
        self.exp_spin.valueChanged.connect(self._on_camera_params_changed)
        exp_layout.addWidget(self.exp_spin)
        layout.addLayout(exp_layout)

        # Gain
        gain_layout = QHBoxLayout()
        gain_layout.addWidget(QLabel("Gain:"))
        self.gain_spin = QDoubleSpinBox()
        self.gain_spin.setRange(0.0, 1000.0)
        self.gain_spin.setSingleStep(1.0)
        self.gain_spin.setDecimals(0)
        self.gain_spin.valueChanged.connect(self._on_camera_params_changed)
        gain_layout.addWidget(self.gain_spin)
        layout.addLayout(gain_layout)

        # Target Brightness
        brightness_layout = QHBoxLayout()
        brightness_layout.addWidget(QLabel("Target Brightness:"))
        self.brightness_spin = QDoubleSpinBox()
        self.brightness_spin.setRange(0.0, 255.0)
        self.brightness_spin.setSingleStep(1.0)
        self.brightness_spin.setDecimals(0)
        self.brightness_spin.valueChanged.connect(self._on_camera_params_changed)
        brightness_layout.addWidget(self.brightness_spin)
        layout.addLayout(brightness_layout)

        # USB Bandwidth
        usb_layout = QHBoxLayout()
        usb_layout.addWidget(QLabel("USB Bandwidth (%):"))
        self.usb_bandwidth_spin = QDoubleSpinBox()
        self.usb_bandwidth_spin.setRange(0.0, 100.0)
        self.usb_bandwidth_spin.setSingleStep(1.0)
        self.usb_bandwidth_spin.setDecimals(0)
        self.usb_bandwidth_spin.valueChanged.connect(self._on_camera_params_changed)
        usb_layout.addWidget(self.usb_bandwidth_spin)
        layout.addLayout(usb_layout)

        # Hardware Binning
        binning_layout = QHBoxLayout()
        binning_layout.addWidget(QLabel("HW Binning:"))
        self.hw_binning_combo = QComboBox()
        self.hw_binning_combo.addItems([str(x) for x in [1, 2, 3, 4]]) # Common binning values
        self.hw_binning_combo.currentIndexChanged.connect(self._on_camera_params_changed)
        binning_layout.addWidget(self.hw_binning_combo)
        layout.addLayout(binning_layout)

        # Reset to Defaults Button
        self.reset_camera_btn = QPushButton("Reset to Defaults")
        self.reset_camera_btn.clicked.connect(self._on_reset_camera_clicked)
        layout.addWidget(self.reset_camera_btn)

        group.setLayout(layout)
        return group

    def _build_corner_setting_group(self):
        group = QGroupBox("Corner Setting")
        layout = QVBoxLayout()

        for name in CORNER_NAMES:
            corner_layout = QHBoxLayout()
            btn = QPushButton(f"Set {name.replace('_', ' ').title()}")
            btn.clicked.connect(lambda checked, n=name: self._on_set_corner_clicked(n))
            corner_layout.addWidget(btn)
            corner_layout.addWidget(self.corners[name]["label"])
            layout.addLayout(corner_layout)

        self.clear_corners_btn = QPushButton("Clear All Corners")
        self.clear_corners_btn.clicked.connect(self._on_clear_corners_clicked)
        layout.addWidget(self.clear_corners_btn)

        group.setLayout(layout)
        return group

    def _build_well_map_group(self):
        group = QGroupBox("Well Map")
        layout = QVBoxLayout()

        # Rows and Columns
        grid_layout = QHBoxLayout()
        grid_layout.addWidget(QLabel("Rows:"))
        self.rows_spin = QDoubleSpinBox()
        self.rows_spin.setRange(1.0, 100.0)
        self.rows_spin.setSingleStep(1.0)
        self.rows_spin.setDecimals(0)
        self.rows_spin.valueChanged.connect(self._generate_well_map)
        grid_layout.addWidget(self.rows_spin)

        grid_layout.addWidget(QLabel("Cols:"))
        self.cols_spin = QDoubleSpinBox()
        self.cols_spin.setRange(1.0, 100.0)
        self.cols_spin.setSingleStep(1.0)
        self.cols_spin.setDecimals(0)
        self.cols_spin.valueChanged.connect(self._generate_well_map)
        grid_layout.addWidget(self.cols_spin)
        layout.addLayout(grid_layout)

        self.well_map_widget = WellMapWidget()
        # Connection moved to MainWindow or connected here
        self.well_map_widget.well_clicked.connect(self._on_well_map_clicked)
        layout.addWidget(self.well_map_widget)

        group.setLayout(layout)
        return group

    def _build_save_load_group(self):
        group = QGroupBox("Calibration File")
        layout = QVBoxLayout()

        load_save_layout = QHBoxLayout()
        self.load_cal_btn = QPushButton("Load Calibration")
        self.load_cal_btn.clicked.connect(self._on_load_cal_clicked)
        load_save_layout.addWidget(self.load_cal_btn)

        self.save_cal_btn = QPushButton("Save Calibration")
        self.save_cal_btn.clicked.connect(self._on_save_cal_clicked)
        load_save_layout.addWidget(self.save_cal_btn)
        layout.addLayout(load_save_layout)

        group.setLayout(layout)
        return group

    def _generate_well_map(self):
        # Update the well map widget with current corners and dimensions
        corners_set = all(c["position"] is not None for c in self.corners.values())
        if corners_set:
            self.well_map_widget.set_well_grid(
                int(self.rows_spin.value()),
                int(self.cols_spin.value()),
                self.corners["Upper-Left"]["position"],
                self.corners["Upper-Right"]["position"],
                self.corners["Lower-Left"]["position"],
                self.corners["Lower-Right"]["position"],
            )
        else:
            self.well_map_widget.clear()
        self.corners_changed.emit()

    def _persist_corners(self):
        corners_data = {
            name: self.corners[name]["position"]
            for name in CORNER_NAMES
            if self.corners[name]["position"] is not None
        }
        session_manager.update_session("calibration", {"corners": corners_data})

    def _save_calibration(self):
        cal_dir = self._get_cal_dir()
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Calibration",
            str(cal_dir / "calibration.json"),
            "JSON Files (*.json)"
        )
        if not path:
            return

        data = {
            "corners": {name: self.corners[name]["position"] for name in CORNER_NAMES if self.corners[name]["position"] is not None},
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
            selected_path, _ = QFileDialog.getOpenFileName(
                self, "Load Calibration",
                str(cal_dir),
                "JSON Files (*.json)"
            )
            if not selected_path:
                # User cancelled, do not load anything and do not save a 'False' path
                session_manager.update_session("calibration", {"last_calibration_path": None})
                return False
            path = Path(selected_path)
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
        session_manager.update_session("calibration", {"last_calibration_path": str(path)})
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

    def _compute_well_positions(self) -> Optional[list]:
        corners_set = all(c["position"] is not None for c in self.corners.values())
        if not corners_set:
            return None
        # Simplified bilinear interpolation for well positions
        tl = self.corners["Upper-Left"]["position"]
        tr = self.corners["Upper-Right"]["position"]
        bl = self.corners["Lower-Left"]["position"]
        br = self.corners["Lower-Right"]["position"]
        rows = int(self.rows_spin.value())
        cols = int(self.cols_spin.value())
        positions = []
        for r in range(rows):
            for c in range(cols):
                u = c / (cols - 1) if cols > 1 else 0.5
                v = r / (rows - 1) if rows > 1 else 0.5
                x = (1-u)*(1-v)*tl[0] + u*(1-v)*tr[0] + (1-u)*v*bl[0] + u*v*br[0]
                y = (1-u)*(1-v)*tl[1] + u*(1-v)*tr[1] + (1-u)*v*bl[1] + u*v*br[1]
                z = (1-u)*(1-v)*tl[2] + u*(1-v)*tr[2] + (1-u)*v*bl[2] + u*v*br[2]
                positions.append((x, y, z))
        return positions

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _on_step_btn_clicked(self, btn):
        """Preset radio clicked — keep custom input visible."""
        if btn is not self._custom_rb:
            # Preset selected - DONT change the input box so the user can still see their custom value
            session_manager.update_session("calibration", {"step_size": btn.text()})
        else:
            # Re-selected "Custom"
            session_manager.update_session("calibration", {"step_size": str(self.step_size_input.value())})

    def _on_custom_step_edited(self, text: str):
        """User typed in the custom field — auto-select the Custom radio button."""
        self._last_custom_step = text
        self._custom_rb.setChecked(True)
        session_manager.update_session("calibration", {
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

            # Update homing status
            is_homed = mc.is_homed()
            if is_homed:
                if not self._is_homed:
                    self._is_homed = True
                    self._cal_status_label.setText("Ready.")
                    self._cal_status_label.setStyleSheet("font-size: 10px; color: #888;")
                    self._set_movement_controls_enabled(True)
                    self._set_camera_controls_enabled(True)
            else:
                self._is_homed = False
                self._cal_status_label.setText("<b style=\"color: red;\">Printer Not Homed.</b>")
                self._cal_status_label.setStyleSheet("font-size: 10px; color: red;")
                self._set_movement_controls_enabled(False)
                self._set_camera_controls_enabled(False)

        except Exception as e:
            logger.error(f"[Calibration] Error updating position display: {e}")
            self.x_pos_label.setText("ERR")
            self.y_pos_label.setText("ERR")
            self.z_pos_label.setText("ERR")
            self._cal_status_label.setText("<b style=\"color: red;\">Printer Disconnected.</b>")
            self._cal_status_label.setStyleSheet("font-size: 10px; color: red;")
            self._set_movement_controls_enabled(False)
            self._set_camera_controls_enabled(False)

    def _set_movement_controls_enabled(self, enabled: bool):
        self.y_plus_btn.setEnabled(enabled)
        self.x_minus_btn.setEnabled(enabled)
        self.x_plus_btn.setEnabled(enabled)
        self.y_minus_btn.setEnabled(enabled)
        self.z_plus_btn.setEnabled(enabled)
        self.z_minus_btn.setEnabled(enabled)
        self.home_btn.setEnabled(True) # Always allow homing
        self.go_to_xyz_btn.setEnabled(enabled)
        # Fix button names based on UI building methods
        if hasattr(self, 'clear_corners_btn'): self.clear_corners_btn.setEnabled(enabled)
        if hasattr(self, 'load_cal_btn'): self.load_cal_btn.setEnabled(enabled)
        if hasattr(self, 'save_cal_btn'): self.save_cal_btn.setEnabled(enabled)
        if hasattr(self, 'well_map_widget'): self.well_map_widget.setEnabled(enabled)

    def _set_camera_controls_enabled(self, enabled: bool):
        self.auto_exp_check.setEnabled(enabled)
        self.exp_spin.setEnabled(enabled)
        self.gain_spin.setEnabled(enabled)
        self.brightness_spin.setEnabled(enabled)
        self.usb_bandwidth_spin.setEnabled(enabled)
        self.hw_binning_combo.setEnabled(enabled)
        self.reset_camera_btn.setEnabled(enabled)

    def _get_cal_dir(self) -> Path:
        cal_dir = Path.home() / "Documents" / "RoboCam" / "calibrations" # Default to user's Documents/RoboCam/calibrations
        cal_dir.mkdir(parents=True, exist_ok=True)
        return cal_dir

    def _on_home_clicked(self):
        logger.info("[Calibration] Homing printer...")
        self.hw_manager.get_motion_controller().home()
        self._is_homed = True
        self._update_position_display()
        self._set_movement_controls_enabled(True)
        self._set_camera_controls_enabled(True)
        self._cal_status_label.setText("Ready.")
        self._cal_status_label.setStyleSheet("font-size: 10px; color: green;")

    def _on_set_corner_clicked(self, corner_name: str):
        pos = self.hw_manager.get_motion_controller().get_current_position()
        self.corners[corner_name]["position"] = pos
        self.corners[corner_name]["label"].setText(
            f"X:{pos[0]:.2f}  Y:{pos[1]:.2f}  Z:{pos[2]:.2f}"
        )
        self.corners[corner_name]["label"].setStyleSheet("color: green;")
        self._persist_corners()
        self.corners_changed.emit()

    def _on_clear_corners_clicked(self):
        for name in CORNER_NAMES:
            self.corners[name]["position"] = None
            self.corners[name]["label"].setText("Not Set")
            self.corners[name]["label"].setStyleSheet("color: #888;")
        self._persist_corners()
        self.corners_changed.emit()
        self.well_map_widget.clear()

    def _on_go_to_xyz_clicked(self):
        x = self.x_go_to_input.value()
        y = self.y_go_to_input.value()
        z = self.z_go_to_input.value()
        self.hw_manager.get_motion_controller().move_to(x, y, z)
        self._update_position_display()

    def _on_well_map_clicked(self, x: float, y: float, z: float):
        self.hw_manager.get_motion_controller().move_to(x, y, z)
        self._update_position_display()

    def _on_load_cal_clicked(self):
        self._load_calibration()

    def _on_save_cal_clicked(self):
        self._save_calibration()

    def _on_reset_camera_clicked(self):
        logger.info("[Calibration] Resetting camera controls to defaults...")
        self.hw_manager.get_camera().reset_to_defaults()
        self._load_camera_settings_from_hw()
        self._on_camera_params_changed() # Trigger session save

    def _load_camera_settings_from_hw(self):
        camera = self.hw_manager.get_camera()
        if camera and camera.is_connected:
            self.auto_exp_check.blockSignals(True)
            self.exp_spin.blockSignals(True)
            self.gain_spin.blockSignals(True)
            self.brightness_spin.blockSignals(True)
            self.usb_bandwidth_spin.blockSignals(True)
            self.hw_binning_combo.blockSignals(True)

            self.auto_exp_check.setChecked(camera.get_auto_exposure())
            self.exp_spin.setValue(camera.get_exposure())
            self.gain_spin.setValue(camera.get_gain())
            self.brightness_spin.setValue(camera.get_target_brightness())
            self.usb_bandwidth_spin.setValue(camera.get_usb_bandwidth())
            self.hw_binning_combo.setCurrentText(str(camera.get_hw_binning()))

            self.auto_exp_check.blockSignals(False)
            self.exp_spin.blockSignals(False)
            self.gain_spin.blockSignals(False)
            self.brightness_spin.blockSignals(False)
            self.usb_bandwidth_spin.blockSignals(False)
            self.hw_binning_combo.blockSignals(False)

    def _refresh_camera_controls(self):
        """Update UI to match hardware state. Called when camera connects."""
        self._load_camera_settings_from_hw()

    def _on_camera_params_changed(self):
        camera = self.hw_manager.get_camera()
        if camera and camera.is_connected:
            camera.set_auto_exposure(self.auto_exp_check.isChecked())
            camera.set_exposure(self.exp_spin.value())
            camera.set_gain(self.gain_spin.value())
            camera.set_target_brightness(self.brightness_spin.value())
            camera.set_usb_bandwidth(self.usb_bandwidth_spin.value())
            camera.set_hw_binning(int(self.hw_binning_combo.currentText()))

            # Save all camera settings to session
            camera_settings = {
                "auto_exposure": self.auto_exp_check.isChecked(),
                "exposure": self.exp_spin.value(),
                "gain": self.gain_spin.value(),
                "target_brightness": self.brightness_spin.value(),
                "usb_bandwidth": self.usb_bandwidth_spin.value(),
                "hw_binning": int(self.hw_binning_combo.currentText()),
            }
            session_manager.update_session("calibration", {"camera_settings": camera_settings})

    def _load_from_session(self):
        # Load step size from session
        s = session_manager.get_session("calibration")
        step_size = s.get("step_size", "1.0")
        custom_step = s.get("custom_step_size", "1.0")

        if step_size in STEP_PRESETS:
            for rb in self.step_size_group.buttons():
                if rb.text() == step_size:
                    rb.setChecked(True)
                    break
        else:
            self._custom_rb.setChecked(True)
            self.step_size_input.setValue(float(custom_step))

        self._last_custom_step = custom_step

        # Load camera settings from session
        self.auto_exp_check.blockSignals(True)
        self.exp_spin.blockSignals(True)
        self.gain_spin.blockSignals(True)
        self.brightness_spin.blockSignals(True)
        self.usb_bandwidth_spin.blockSignals(True)
        self.hw_binning_combo.blockSignals(True)

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

        # Load camera settings from session and apply to UI
        camera_settings = session_manager.get_session("calibration").get("camera_settings", {})
        if camera_settings:
            self.auto_exp_check.setChecked(camera_settings.get("auto_exposure", False))
            self.exp_spin.setValue(camera_settings.get("exposure", 20000))
            self.gain_spin.setValue(camera_settings.get("gain", 100))
            self.brightness_spin.setValue(camera_settings.get("target_brightness", 100))
            self.usb_bandwidth_spin.setValue(camera_settings.get("usb_bandwidth", 50))
            self.hw_binning_combo.setCurrentText(str(camera_settings.get("hw_binning", 1)))

        self.auto_exp_check.blockSignals(False)
        self.exp_spin.blockSignals(False)
        self.gain_spin.blockSignals(False)
        self.brightness_spin.blockSignals(False)
        self.usb_bandwidth_spin.blockSignals(False)
        self.hw_binning_combo.blockSignals(False)
