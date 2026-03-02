from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QGridLayout, QLabel, QGroupBox
from PySide6.QtCore import Qt, QTimer
from robocam_suite.hw_manager import hw_manager


class ManualControlPanel(QWidget):
    """A widget for direct manual control of hardware components."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.hw_manager = hw_manager

        self.layout = QVBoxLayout(self)

        # General Controls
        general_group = QGroupBox("General Controls")
        general_layout = QHBoxLayout()
        general_group.setLayout(general_layout)
        self.layout.addWidget(general_group)

        self.home_all_btn = QPushButton("Home All Axes")
        general_layout.addWidget(self.home_all_btn)

        # Laser Control
        laser_group = QGroupBox("Laser Control")
        laser_layout = QVBoxLayout()
        laser_group.setLayout(laser_layout)
        self.layout.addWidget(laser_group)

        gpio_enabled = self.hw_manager.gpio_enabled
        if not gpio_enabled:
            self.gpio_notice_label = QLabel(
                "GPIO is disabled (gpio_controller.enabled = false in config).\n"
                "Laser controls are unavailable. Enable GPIO in the config file to use them."
            )
            self.gpio_notice_label.setStyleSheet("color: orange;")
            self.gpio_notice_label.setWordWrap(True)
            laser_layout.addWidget(self.gpio_notice_label)

        btn_row = QHBoxLayout()
        self.laser_on_btn = QPushButton("Laser ON")
        self.laser_off_btn = QPushButton("Laser OFF")
        self.laser_on_btn.setEnabled(gpio_enabled)
        self.laser_off_btn.setEnabled(gpio_enabled)
        btn_row.addWidget(self.laser_on_btn)
        btn_row.addWidget(self.laser_off_btn)
        laser_layout.addLayout(btn_row)

        # Hardware Status
        status_group = QGroupBox("Hardware Status")
        status_layout = QGridLayout()
        status_group.setLayout(status_layout)
        self.layout.addWidget(status_group)

        status_layout.addWidget(QLabel("Motion Controller:"), 0, 0)
        self.mc_status_label = QLabel("Disconnected")
        status_layout.addWidget(self.mc_status_label, 0, 1)

        status_layout.addWidget(QLabel("Camera:"), 1, 0)
        self.cam_status_label = QLabel("Disconnected")
        status_layout.addWidget(self.cam_status_label, 1, 1)

        status_layout.addWidget(QLabel("GPIO Controller:"), 2, 0)
        self.gpio_status_label = QLabel("Disabled" if not gpio_enabled else "Disconnected")
        self.gpio_status_label.setStyleSheet("color: gray" if not gpio_enabled else "color: red")
        status_layout.addWidget(self.gpio_status_label, 2, 1)

        self.layout.addStretch()

        # Connect signals
        self.home_all_btn.clicked.connect(self.home_all)
        self.laser_on_btn.clicked.connect(lambda: self.set_laser(True))
        self.laser_off_btn.clicked.connect(lambda: self.set_laser(False))

        # Status update timer — only poll connection status for enabled devices
        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self.update_status)
        self.status_timer.start(1000)
        self.update_status()

    def home_all(self):
        try:
            self.hw_manager.get_motion_controller().home()
        except Exception as e:
            print(f"Error homing: {e}")

    def set_laser(self, state: bool):
        try:
            laser_pin = self.hw_manager._config.get_section("gpio_controller").get("laser_pin", 21)
            self.hw_manager.get_gpio_controller().write_pin(laser_pin, state)
        except Exception as e:
            print(f"Error controlling laser: {e}")

    def update_status(self):
        try:
            mc_connected = self.hw_manager.get_motion_controller().is_connected
            self.mc_status_label.setText("Connected" if mc_connected else "Disconnected")
            self.mc_status_label.setStyleSheet("color: green" if mc_connected else "color: red")
        except Exception:
            pass

        try:
            cam_connected = self.hw_manager.get_camera().is_connected
            self.cam_status_label.setText("Connected" if cam_connected else "Disconnected")
            self.cam_status_label.setStyleSheet("color: green" if cam_connected else "color: red")
        except Exception:
            pass

        # Only update GPIO status if it is enabled; otherwise leave it as "Disabled"
        if self.hw_manager.gpio_enabled:
            try:
                gpio_connected = self.hw_manager.get_gpio_controller().is_connected
                self.gpio_status_label.setText("Connected" if gpio_connected else "Disconnected")
                self.gpio_status_label.setStyleSheet("color: green" if gpio_connected else "color: red")
            except Exception:
                pass
