"""
Calibration Panel — jog the stage and record well-plate corner positions.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QGridLayout, QLabel, QLineEdit, QGroupBox,
    QButtonGroup, QRadioButton,
)
from PySide6.QtCore import Qt, QTimer

from robocam_suite.hw_manager import hw_manager
from robocam_suite.session_manager import session_manager
from robocam_suite.ui.quick_capture_widget import QuickCaptureWidget

# Preset step sizes shown as radio buttons (mm)
STEP_PRESETS = ["0.1", "0.5", "1.0", "5.0", "10.0"]


class CalibrationPanel(QWidget):
    """Jog controls, step-size selector, and corner recording for well-plate calibration."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.hw_manager = hw_manager
        self._session = session_manager

        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.addWidget(self._build_movement_group())
        root.addWidget(self._build_calibration_group())
        root.addWidget(QuickCaptureWidget("Quick Capture"))
        root.addStretch()

        # Restore persisted step size and corners
        self._load_from_session()

        # Position display refresh
        self._pos_timer = QTimer(self)
        self._pos_timer.timeout.connect(self._update_position_display)
        self._pos_timer.start(500)

    # ------------------------------------------------------------------
    # Group builders
    # ------------------------------------------------------------------

    def _build_movement_group(self) -> QGroupBox:
        grp = QGroupBox("Movement Controls")
        layout = QGridLayout(grp)

        # Current position display
        pos_row = QHBoxLayout()
        pos_row.addWidget(QLabel("Position —"))
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

        # Z jog (separate column)
        self.z_plus_btn = QPushButton("Z+")
        self.z_plus_btn.setToolTip("Move stage up (+Z).")
        layout.addWidget(self.z_plus_btn, 1, 3)

        self.z_minus_btn = QPushButton("Z-")
        self.z_minus_btn.setToolTip("Move stage down (-Z).")
        layout.addWidget(self.z_minus_btn, 3, 3)

        # Step size — radio buttons + custom entry
        step_grp = QGroupBox("Step Size (mm)")
        step_grp.setToolTip(
            "Distance the stage moves per button press.\n"
            "Use small steps (0.1–0.5 mm) for fine positioning over a well,\n"
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
        self.step_size_input.setFixedWidth(60)
        self.step_size_input.setToolTip("Enter any custom step size in mm.")
        step_layout.addWidget(self.step_size_input)

        # Sync radio → custom field
        self._step_btn_group.buttonClicked.connect(
            lambda btn: self.step_size_input.setText(btn.text())
        )
        # Sync custom field → deselect radios
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
            "Jog the stage to each corner of the well plate and press the corresponding\n"
            "button to record that position. The suite uses bilinear interpolation across\n"
            "all four corners to calculate the exact position of every well."
        )
        layout = QGridLayout(grp)

        self.corners: dict = {}
        for i, name in enumerate(["Upper-Left", "Lower-Left", "Upper-Right", "Lower-Right"]):
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

        self.generate_path_btn = QPushButton("Preview Well Plate Path")
        self.generate_path_btn.setToolTip(
            "Generate and display the ordered list of well positions based on the four corners.\n"
            "Requires all four corners to be set."
        )
        layout.addWidget(self.generate_path_btn, 4, 0, 1, 4)

        return grp

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _move(self, axis: str, direction: int):
        try:
            step = float(self.step_size_input.text())
            self.hw_manager.get_motion_controller().move_relative(**{axis: direction * step})
            self._update_position_display()
        except Exception as e:
            print(f"[Calibration] Move error: {e}")

    def _home(self):
        try:
            self.hw_manager.get_motion_controller().home()
            self._update_position_display()
        except Exception as e:
            print(f"[Calibration] Home error: {e}")

    def _set_corner(self, name: str):
        try:
            pos = self.hw_manager.get_motion_controller().get_current_position()
            self.corners[name]["position"] = pos
            self.corners[name]["label"].setText(
                f"X:{pos[0]:.2f}  Y:{pos[1]:.2f}  Z:{pos[2]:.2f}"
            )
            self.corners[name]["label"].setStyleSheet("color: green;")
            # Persist corners in session
            session_corners = {
                k: v["position"] for k, v in self.corners.items()
            }
            self._session.update_session("calibration", {"corners": session_corners})
        except Exception as e:
            print(f"[Calibration] Set corner error: {e}")

    def _on_custom_step_edited(self, text: str):
        """Deselect all radio buttons when the user types a custom value."""
        checked = self._step_btn_group.checkedButton()
        if checked and checked.text() != text:
            self._step_btn_group.setExclusive(False)
            checked.setChecked(False)
            self._step_btn_group.setExclusive(True)
        # Persist step size
        self._session.update_session("calibration", {"step_size": text})

    def _update_position_display(self):
        try:
            pos = self.hw_manager.get_motion_controller().get_current_position()
            self.x_pos_label.setText(f"{pos[0]:.2f}")
            self.y_pos_label.setText(f"{pos[1]:.2f}")
            self.z_pos_label.setText(f"{pos[2]:.2f}")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Public accessor used by ExperimentPanel
    # ------------------------------------------------------------------

    def get_corners(self) -> dict:
        return {k: v["position"] for k, v in self.corners.items()}

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
