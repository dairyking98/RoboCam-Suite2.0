from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QGridLayout, QLabel, QLineEdit, QGroupBox
from PySide6.QtCore import Qt, QTimer
from robocam_suite.hw_manager import hw_manager
from robocam_suite.experiments.well_plate import WellPlate

class CalibrationPanel(QWidget):
    """A widget for manual calibration and position recording."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.hw_manager = hw_manager

        self.layout = QVBoxLayout(self)

        # Movement Controls
        movement_group = QGroupBox("Movement Controls")
        movement_layout = QGridLayout()
        movement_group.setLayout(movement_layout)
        self.layout.addWidget(movement_group)

        # Position Display
        pos_layout = QHBoxLayout()
        pos_layout.addWidget(QLabel("X:"))
        self.x_pos_label = QLabel("0.00")
        pos_layout.addWidget(self.x_pos_label)
        pos_layout.addWidget(QLabel("Y:"))
        self.y_pos_label = QLabel("0.00")
        pos_layout.addWidget(self.y_pos_label)
        pos_layout.addWidget(QLabel("Z:"))
        self.z_pos_label = QLabel("0.00")
        pos_layout.addWidget(self.z_pos_label)
        movement_layout.addLayout(pos_layout, 0, 0, 1, 3)

        # Movement Buttons
        self.y_plus_btn = QPushButton("Y+")
        movement_layout.addWidget(self.y_plus_btn, 1, 1)
        self.x_minus_btn = QPushButton("X-")
        movement_layout.addWidget(self.x_minus_btn, 2, 0)
        self.home_btn = QPushButton("Home")
        movement_layout.addWidget(self.home_btn, 2, 1)
        self.x_plus_btn = QPushButton("X+")
        movement_layout.addWidget(self.x_plus_btn, 2, 2)
        self.y_minus_btn = QPushButton("Y-")
        movement_layout.addWidget(self.y_minus_btn, 3, 1)

        self.z_plus_btn = QPushButton("Z+")
        movement_layout.addWidget(self.z_plus_btn, 1, 3)
        self.z_minus_btn = QPushButton("Z-")
        movement_layout.addWidget(self.z_minus_btn, 3, 3)

        # Step Size
        step_layout = QHBoxLayout()
        step_layout.addWidget(QLabel("Step (mm):"))
        self.step_size_input = QLineEdit("1.0")
        step_layout.addWidget(self.step_size_input)
        movement_layout.addLayout(step_layout, 4, 0, 1, 3)

        # Calibration Points
        calib_group = QGroupBox("Calibration Points")
        calib_layout = QGridLayout()
        calib_group.setLayout(calib_layout)
        self.layout.addWidget(calib_group)

        self.corners = {}
        for i, name in enumerate(["Upper-Left", "Lower-Left", "Upper-Right", "Lower-Right"]):
            row, col = divmod(i, 2)
            calib_layout.addWidget(QLabel(f"{name}:"), row*2, col*2)
            pos_label = QLabel("Not Set")
            calib_layout.addWidget(pos_label, row*2, col*2 + 1)
            set_btn = QPushButton(f"Set {name}")
            calib_layout.addWidget(set_btn, row*2 + 1, col*2, 1, 2)
            self.corners[name] = {"label": pos_label, "button": set_btn, "position": None}

        self.generate_path_btn = QPushButton("Generate Well Plate Path")
        self.layout.addWidget(self.generate_path_btn)

        self.layout.addStretch()

        # Connect signals
        self.y_plus_btn.clicked.connect(lambda: self.move("y", 1))
        self.y_minus_btn.clicked.connect(lambda: self.move("y", -1))
        self.x_plus_btn.clicked.connect(lambda: self.move("x", 1))
        self.x_minus_btn.clicked.connect(lambda: self.move("x", -1))
        self.z_plus_btn.clicked.connect(lambda: self.move("z", 1))
        self.z_minus_btn.clicked.connect(lambda: self.move("z", -1))
        self.home_btn.clicked.connect(self.home)

        for name, corner in self.corners.items():
            corner["button"].clicked.connect(lambda checked=False, n=name: self.set_corner(n))

        # Position update timer
        self.pos_timer = QTimer(self)
        self.pos_timer.timeout.connect(self.update_position_display)
        self.pos_timer.start(500) # Update every 500ms

    def move(self, axis: str, direction: int):
        try:
            step_size = float(self.step_size_input.text())
            kwargs = {axis: direction * step_size}
            self.hw_manager.get_motion_controller().move_relative(**kwargs)
            self.update_position_display()
        except Exception as e:
            print(f"Error moving: {e}")

    def home(self):
        try:
            self.hw_manager.get_motion_controller().home()
            self.update_position_display()
        except Exception as e:
            print(f"Error homing: {e}")

    def set_corner(self, name: str):
        try:
            pos = self.hw_manager.get_motion_controller().get_current_position()
            self.corners[name]["position"] = pos
            self.corners[name]["label"].setText(f"X:{pos[0]:.2f} Y:{pos[1]:.2f} Z:{pos[2]:.2f}")
        except Exception as e:
            print(f"Error setting corner: {e}")

    def update_position_display(self):
        try:
            pos = self.hw_manager.get_motion_controller().get_current_position()
            self.x_pos_label.setText(f"{pos[0]:.2f}")
            self.y_pos_label.setText(f"{pos[1]:.2f}")
            self.z_pos_label.setText(f"{pos[2]:.2f}")
        except Exception as e:
            # This can happen if the controller is not connected yet
            pass
