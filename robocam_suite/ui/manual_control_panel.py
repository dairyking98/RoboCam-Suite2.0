"""
Manual Control Panel — direct hardware control outside of an experiment.
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QGridLayout, QLabel, QGroupBox, QLineEdit, QTextEdit,
    QSizePolicy,
)
from PySide6.QtCore import Qt, QTimer
from robocam_suite.hw_manager import hw_manager
from robocam_suite.ui.quick_capture_widget import QuickCaptureWidget


class ManualControlPanel(QWidget):
    """A widget for direct manual control of hardware components."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.hw_manager = hw_manager

        root = QVBoxLayout(self)
        root.setSpacing(8)

        root.addWidget(self._build_general_group())
        root.addWidget(self._build_laser_group())
        root.addWidget(self._build_gcode_group())
        root.addWidget(self._build_status_group())
        root.addWidget(QuickCaptureWidget("Quick Capture"))
        root.addStretch()

        # Status refresh every second
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_status)
        self._timer.start(1000)
        self._refresh_status()

    # ------------------------------------------------------------------
    # Group builders
    # ------------------------------------------------------------------

    def _build_general_group(self) -> QGroupBox:
        grp = QGroupBox("General Controls")
        layout = QHBoxLayout(grp)

        self.home_all_btn = QPushButton("Home All Axes")
        self.home_all_btn.setToolTip(
            "Send G28 to the printer, homing all axes (X, Y, Z) to their endstops."
        )
        self.home_all_btn.clicked.connect(self._home_all)
        layout.addWidget(self.home_all_btn)

        self.disable_steppers_btn = QPushButton("Disable Steppers")
        self.disable_steppers_btn.setToolTip(
            "Send M84 to the printer, cutting power to all stepper motors.\n"
            "This lets you move the axes by hand without fighting the motors.\n"
            "The printer will need to be re-homed before the next move."
        )
        self.disable_steppers_btn.clicked.connect(self._disable_steppers)
        layout.addWidget(self.disable_steppers_btn)

        return grp

    def _build_laser_group(self) -> QGroupBox:
        grp = QGroupBox("Laser Control")
        layout = QVBoxLayout(grp)

        gpio_enabled = self.hw_manager.gpio_enabled
        if not gpio_enabled:
            notice = QLabel(
                "GPIO is disabled — enable it in the Setup tab to use laser controls."
            )
            notice.setStyleSheet("color: orange;")
            notice.setWordWrap(True)
            layout.addWidget(notice)

        btn_row = QHBoxLayout()
        self.laser_on_btn = QPushButton("Laser ON")
        self.laser_on_btn.setToolTip("Turn the laser on (sets the configured laser pin HIGH).")
        self.laser_off_btn = QPushButton("Laser OFF")
        self.laser_off_btn.setToolTip("Turn the laser off (sets the configured laser pin LOW).")
        self.laser_on_btn.setEnabled(gpio_enabled)
        self.laser_off_btn.setEnabled(gpio_enabled)
        self.laser_on_btn.clicked.connect(lambda: self._set_laser(True))
        self.laser_off_btn.clicked.connect(lambda: self._set_laser(False))
        btn_row.addWidget(self.laser_on_btn)
        btn_row.addWidget(self.laser_off_btn)
        layout.addLayout(btn_row)

        return grp

    def _build_gcode_group(self) -> QGroupBox:
        grp = QGroupBox("Manual G-code Sender")
        layout = QVBoxLayout(grp)

        input_row = QHBoxLayout()
        self.gcode_input = QLineEdit()
        self.gcode_input.setPlaceholderText("Enter G-code (e.g. G0 X10, M114, M503)...")
        self.gcode_input.returnPressed.connect(self._send_custom_gcode)
        input_row.addWidget(self.gcode_input)

        send_btn = QPushButton("Send")
        send_btn.clicked.connect(self._send_custom_gcode)
        input_row.addWidget(send_btn)

        clear_btn = QPushButton("Clear Log")
        clear_btn.clicked.connect(lambda: self.gcode_log.clear())
        input_row.addWidget(clear_btn)
        layout.addLayout(input_row)

        self.gcode_log = QTextEdit()
        self.gcode_log.setReadOnly(True)
        self.gcode_log.setFont(self.gcode_log.font().__class__("Courier New", 9))
        self.gcode_log.setMinimumHeight(100)
        self.gcode_log.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.gcode_log)

        return grp

    def _build_status_group(self) -> QGroupBox:
        grp = QGroupBox("Hardware Status")
        layout = QGridLayout(grp)

        layout.addWidget(QLabel("3-D Printer:"), 0, 0)
        self.mc_status_label = QLabel("Disconnected")
        layout.addWidget(self.mc_status_label, 0, 1)

        layout.addWidget(QLabel("Position:"), 1, 0)
        self.pos_label = QLabel("Disconnected")
        self.pos_label.setStyleSheet("font-family: monospace;")
        layout.addWidget(self.pos_label, 1, 1)

        layout.addWidget(QLabel("Camera:"), 2, 0)
        self.cam_status_label = QLabel("Disconnected")
        layout.addWidget(self.cam_status_label, 2, 1)

        layout.addWidget(QLabel("GPIO / Arduino:"), 3, 0)
        gpio_enabled = self.hw_manager.gpio_enabled
        self.gpio_status_label = QLabel("Disabled" if not gpio_enabled else "Disconnected")
        self.gpio_status_label.setStyleSheet("color: gray" if not gpio_enabled else "color: red")
        layout.addWidget(self.gpio_status_label, 3, 1)

        return grp

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _home_all(self):
        try:
            self.hw_manager.get_motion_controller().home()
        except Exception as e:
            print(f"[ManualControl] Home error: {e}")

    def _disable_steppers(self):
        try:
            mc = self.hw_manager.get_motion_controller()
            # M18 disables all stepper motors (equivalent to M84 on most firmware)
            mc.send_raw("M18")
        except Exception as e:
            print(f"[ManualControl] Disable steppers error: {e}")

    def _set_laser(self, state: bool):
        try:
            laser_pin = self.hw_manager._config.get_section("gpio_controller").get("laser_pin", 21)
            self.hw_manager.get_gpio_controller().write_pin(laser_pin, state)
        except Exception as e:
            print(f"[ManualControl] Laser error: {e}")

    def _send_custom_gcode(self):
        cmd = self.gcode_input.text().strip()
        if not cmd:
            return
        self.gcode_input.clear()
        try:
            mc = self.hw_manager.get_motion_controller()
            if not mc.is_connected:
                self.gcode_log.append("[Error] Printer not connected.")
                return
            
            # Use the low-level send_and_receive if available, else send_raw
            self.gcode_log.append(f">>> {cmd}")
            if hasattr(mc, "send_and_receive"):
                response_lines = mc.send_and_receive(cmd)
                for line in response_lines:
                    self.gcode_log.append(f"    {line}")
            else:
                response = mc.send_raw(cmd)
                if response:
                    for line in response.splitlines():
                        self.gcode_log.append(f"    {line}")
            self.gcode_log.append("")
            
            # If the command was a move or home, sync position
            if any(c in cmd.upper() for c in ("G0", "G1", "G28", "G92")):
                mc.query_current_position()
                self._refresh_status()
        except Exception as e:
            self.gcode_log.append(f"[Error] {e}")

    # ------------------------------------------------------------------
    # Status refresh
    # ------------------------------------------------------------------

    def _refresh_status(self):
        try:
            mc = self.hw_manager.get_motion_controller()
            ok = mc.is_connected
            self.mc_status_label.setText("Connected" if ok else "Disconnected")
            self.mc_status_label.setStyleSheet("color: green" if ok else "color: red")
            
            if ok:
                # Use cached position (no serial polling)
                pos = mc.get_current_position()
                if pos == (0.0, 0.0, 0.0):
                    # Position might be unhomed at startup
                    self.pos_label.setText("X: 0.00  Y: 0.00  Z: 0.00 (Homing recommended)")
                    self.pos_label.setStyleSheet("font-family: monospace; color: orange;")
                else:
                    self.pos_label.setText(f"X: {pos[0]:.2f}  Y: {pos[1]:.2f}  Z: {pos[2]:.2f}")
                    self.pos_label.setStyleSheet("font-family: monospace; font-weight: bold; color: black;")
            else:
                self.pos_label.setText("X: ---  Y: ---  Z: ---")
                self.pos_label.setStyleSheet("font-family: monospace; color: gray;")
        except Exception:
            pass

        try:
            ok = self.hw_manager.get_camera().is_connected
            self.cam_status_label.setText("Connected" if ok else "Disconnected")
            self.cam_status_label.setStyleSheet("color: green" if ok else "color: red")
        except Exception:
            pass

        if self.hw_manager.gpio_enabled:
            try:
                ok = self.hw_manager.get_gpio_controller().is_connected
                self.gpio_status_label.setText("Connected" if ok else "Disconnected")
                self.gpio_status_label.setStyleSheet("color: green" if ok else "color: red")
            except Exception:
                pass
