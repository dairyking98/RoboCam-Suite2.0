"""
Setup Panel — hardware configuration and live connection status.

Lets the user:
  - Choose the camera driver (OpenCV index or PlayerOne) and test it.
  - Choose the serial port and baud rate for the 3-D printer.
  - Enable/disable the GPIO controller and configure its port.
  - See a live colour-coded status indicator for every device.
  - Connect / disconnect all hardware with a single button.

All settings are written back to default_config.json via ConfigManager
and also persisted in session.json via SessionManager so they survive
restarts.
"""

from __future__ import annotations

import serial.tools.list_ports

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QGroupBox, QLabel, QPushButton, QComboBox, QSpinBox,
    QCheckBox, QSizePolicy, QFrame,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPalette

from robocam_suite.hw_manager import hw_manager
from robocam_suite.config.config_manager import config_manager
from robocam_suite.session_manager import session_manager
from robocam_suite.logger import setup_logger

logger = setup_logger()

# Common 3-D printer baud rates in order of popularity
PRINTER_BAUDRATES = [115200, 250000, 57600, 38400, 19200, 9600]
ARDUINO_BAUDRATES = [9600, 115200, 57600, 38400, 19200]


def _status_label(text: str = "Unknown") -> QLabel:
    lbl = QLabel(text)
    lbl.setMinimumWidth(100)
    lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    return lbl


def _set_status(label: QLabel, connected: bool, disabled: bool = False):
    if disabled:
        label.setText("Disabled")
        label.setStyleSheet("color: gray; font-weight: bold;")
    elif connected:
        label.setText("Connected")
        label.setStyleSheet("color: green; font-weight: bold;")
    else:
        label.setText("Disconnected")
        label.setStyleSheet("color: red; font-weight: bold;")


class SetupPanel(QWidget):
    """Hardware configuration and live status panel."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hw = hw_manager
        self._cfg = config_manager
        self._session = session_manager

        root = QVBoxLayout(self)
        root.setSpacing(10)

        root.addWidget(self._build_camera_group())
        root.addWidget(self._build_printer_group())
        root.addWidget(self._build_gpio_group())
        root.addWidget(self._build_status_group())
        root.addWidget(self._build_connect_group())
        root.addStretch()

        # Populate fields from persisted session
        self._load_from_session()

        # Refresh serial port lists and status every 2 s
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._refresh_status)
        self._poll_timer.start(2000)
        self._refresh_status()

    # ------------------------------------------------------------------
    # Group builders
    # ------------------------------------------------------------------

    def _build_camera_group(self) -> QGroupBox:
        grp = QGroupBox("Camera")
        layout = QGridLayout(grp)

        layout.addWidget(QLabel("Driver:"), 0, 0)
        self.cam_driver_combo = QComboBox()
        self.cam_driver_combo.addItems(["opencv", "playerone"])
        self.cam_driver_combo.setToolTip(
            "opencv  — standard USB / built-in webcam via OpenCV (works on all platforms).\n"
            "playerone — Player One Astronomy USB camera via the official SDK."
        )
        layout.addWidget(self.cam_driver_combo, 0, 1)

        layout.addWidget(QLabel("Camera index (OpenCV):"), 1, 0)
        self.cam_index_spin = QSpinBox()
        self.cam_index_spin.setRange(0, 9)
        self.cam_index_spin.setToolTip(
            "Index of the USB camera as seen by OpenCV.\n"
            "0 = first camera, 1 = second, etc."
        )
        layout.addWidget(self.cam_index_spin, 1, 1)

        self.cam_apply_btn = QPushButton("Apply & Reconnect Camera")
        self.cam_apply_btn.clicked.connect(self._apply_camera)
        layout.addWidget(self.cam_apply_btn, 2, 0, 1, 2)
        return grp

    def _build_printer_group(self) -> QGroupBox:
        grp = QGroupBox("3-D Printer (Motion Controller)")
        layout = QGridLayout(grp)

        layout.addWidget(QLabel("Serial port:"), 0, 0)
        self.printer_port_combo = QComboBox()
        self.printer_port_combo.setEditable(True)
        self.printer_port_combo.setToolTip(
            "Serial port the printer is connected to.\n"
            "Windows: COM3, COM4, …\n"
            "Linux:   /dev/ttyUSB0, /dev/ttyACM0, …\n"
            "macOS:   /dev/cu.usbmodem…\n"
            "Leave as 'auto' to let the driver scan all ports."
        )
        layout.addWidget(self.printer_port_combo, 0, 1)

        refresh_btn = QPushButton("↺")
        refresh_btn.setFixedWidth(30)
        refresh_btn.setToolTip("Refresh the list of available serial ports.")
        refresh_btn.clicked.connect(self._refresh_printer_ports)
        layout.addWidget(refresh_btn, 0, 2)

        layout.addWidget(QLabel("Baud rate:"), 1, 0)
        self.printer_baud_combo = QComboBox()
        for b in PRINTER_BAUDRATES:
            self.printer_baud_combo.addItem(str(b), b)
        self.printer_baud_combo.setToolTip(
            "Must match the baud rate configured in your printer's firmware.\n"
            "Creality / Monoprice / Prusa: 115200\n"
            "Older RepRap / Marlin builds:  250000"
        )
        layout.addWidget(self.printer_baud_combo, 1, 1)

        self.printer_apply_btn = QPushButton("Apply & Reconnect Printer")
        self.printer_apply_btn.clicked.connect(self._apply_printer)
        layout.addWidget(self.printer_apply_btn, 2, 0, 1, 3)
        return grp

    def _build_gpio_group(self) -> QGroupBox:
        grp = QGroupBox("GPIO Controller (Arduino / laser)")
        layout = QGridLayout(grp)

        self.gpio_enabled_chk = QCheckBox("Enable GPIO controller")
        self.gpio_enabled_chk.setToolTip(
            "Enable only when an Arduino (or similar) is physically connected.\n"
            "When disabled, laser commands are silently ignored."
        )
        self.gpio_enabled_chk.stateChanged.connect(self._on_gpio_enabled_changed)
        layout.addWidget(self.gpio_enabled_chk, 0, 0, 1, 3)

        layout.addWidget(QLabel("Serial port:"), 1, 0)
        self.gpio_port_combo = QComboBox()
        self.gpio_port_combo.setEditable(True)
        layout.addWidget(self.gpio_port_combo, 1, 1)

        gpio_refresh_btn = QPushButton("↺")
        gpio_refresh_btn.setFixedWidth(30)
        gpio_refresh_btn.setToolTip("Refresh the list of available serial ports.")
        gpio_refresh_btn.clicked.connect(self._refresh_gpio_ports)
        layout.addWidget(gpio_refresh_btn, 1, 2)

        layout.addWidget(QLabel("Baud rate:"), 2, 0)
        self.gpio_baud_combo = QComboBox()
        for b in ARDUINO_BAUDRATES:
            self.gpio_baud_combo.addItem(str(b), b)
        self.gpio_baud_combo.setToolTip(
            "Must match the baud rate in the Arduino sketch (default 9600)."
        )
        layout.addWidget(self.gpio_baud_combo, 2, 1)

        layout.addWidget(QLabel("Laser pin:"), 3, 0)
        self.gpio_laser_pin_spin = QSpinBox()
        self.gpio_laser_pin_spin.setRange(0, 53)
        self.gpio_laser_pin_spin.setToolTip(
            "Arduino digital pin number connected to the laser module."
        )
        layout.addWidget(self.gpio_laser_pin_spin, 3, 1)

        self.gpio_apply_btn = QPushButton("Apply & Reconnect GPIO")
        self.gpio_apply_btn.clicked.connect(self._apply_gpio)
        layout.addWidget(self.gpio_apply_btn, 4, 0, 1, 3)

        self._set_gpio_widgets_enabled(False)
        return grp

    def _build_status_group(self) -> QGroupBox:
        grp = QGroupBox("Hardware Status")
        layout = QGridLayout(grp)

        layout.addWidget(QLabel("3-D Printer:"), 0, 0)
        self.printer_status_lbl = _status_label()
        layout.addWidget(self.printer_status_lbl, 0, 1)

        layout.addWidget(QLabel("Camera:"), 1, 0)
        self.camera_status_lbl = _status_label()
        layout.addWidget(self.camera_status_lbl, 1, 1)

        layout.addWidget(QLabel("GPIO / Arduino:"), 2, 0)
        self.gpio_status_lbl = _status_label()
        layout.addWidget(self.gpio_status_lbl, 2, 1)

        return grp

    def _build_connect_group(self) -> QGroupBox:
        grp = QGroupBox("Connection")
        layout = QHBoxLayout(grp)

        self.connect_all_btn = QPushButton("Connect All")
        self.connect_all_btn.setToolTip("Attempt to connect all configured hardware devices.")
        self.connect_all_btn.clicked.connect(self._connect_all)
        layout.addWidget(self.connect_all_btn)

        self.disconnect_all_btn = QPushButton("Disconnect All")
        self.disconnect_all_btn.setToolTip("Disconnect all hardware devices.")
        self.disconnect_all_btn.clicked.connect(self._disconnect_all)
        layout.addWidget(self.disconnect_all_btn)

        return grp

    # ------------------------------------------------------------------
    # Port list helpers
    # ------------------------------------------------------------------

    def _available_ports(self) -> list[str]:
        ports = ["auto"] + [p.device for p in serial.tools.list_ports.comports()]
        return ports

    def _refresh_printer_ports(self):
        current = self.printer_port_combo.currentText()
        self.printer_port_combo.clear()
        self.printer_port_combo.addItems(self._available_ports())
        idx = self.printer_port_combo.findText(current)
        if idx >= 0:
            self.printer_port_combo.setCurrentIndex(idx)

    def _refresh_gpio_ports(self):
        current = self.gpio_port_combo.currentText()
        self.gpio_port_combo.clear()
        self.gpio_port_combo.addItems(self._available_ports())
        idx = self.gpio_port_combo.findText(current)
        if idx >= 0:
            self.gpio_port_combo.setCurrentIndex(idx)

    # ------------------------------------------------------------------
    # Apply handlers
    # ------------------------------------------------------------------

    def _apply_camera(self):
        driver = self.cam_driver_combo.currentText()
        index = self.cam_index_spin.value()
        self._cfg.update_section("camera", {"driver": driver, "camera_index": index})
        self._session.update_session("setup", {"camera_driver": driver, "camera_index": index})
        # Reset the cached instance so the next get_camera() picks up new config
        self._hw._camera = None
        logger.info(f"Camera config updated: driver={driver}, index={index}")

    def _apply_printer(self):
        port = self.printer_port_combo.currentText() or "auto"
        baud = int(self.printer_baud_combo.currentData() or 115200)
        self._cfg.update_section("motion_controller", {"port": port, "baudrate": baud})
        self._session.update_session("setup", {"motion_port": port, "motion_baudrate": baud})
        self._hw._motion_controller = None
        logger.info(f"Printer config updated: port={port}, baudrate={baud}")

    def _apply_gpio(self):
        enabled = self.gpio_enabled_chk.isChecked()
        port = self.gpio_port_combo.currentText() or "auto"
        baud = int(self.gpio_baud_combo.currentData() or 9600)
        laser_pin = self.gpio_laser_pin_spin.value()
        self._cfg.update_section("gpio_controller", {
            "enabled": enabled, "port": port,
            "baudrate": baud, "laser_pin": laser_pin,
        })
        self._session.update_session("setup", {
            "gpio_enabled": enabled, "gpio_port": port,
            "gpio_baudrate": baud, "gpio_laser_pin": laser_pin,
        })
        self._hw._gpio_controller = None
        logger.info(f"GPIO config updated: enabled={enabled}, port={port}, baud={baud}, pin={laser_pin}")

    def _connect_all(self):
        try:
            self._hw.connect_all()
        except Exception as e:
            logger.error(f"Connect all failed: {e}")
        self._refresh_status()

    def _disconnect_all(self):
        self._hw.disconnect_all()
        self._refresh_status()

    # ------------------------------------------------------------------
    # Status refresh
    # ------------------------------------------------------------------

    def _refresh_status(self):
        try:
            _set_status(self.printer_status_lbl, self._hw.get_motion_controller().is_connected)
        except Exception:
            _set_status(self.printer_status_lbl, False)

        try:
            _set_status(self.camera_status_lbl, self._hw.get_camera().is_connected)
        except Exception:
            _set_status(self.camera_status_lbl, False)

        gpio_enabled = self._hw.gpio_enabled
        try:
            _set_status(self.gpio_status_lbl, self._hw.get_gpio_controller().is_connected,
                        disabled=not gpio_enabled)
        except Exception:
            _set_status(self.gpio_status_lbl, False, disabled=not gpio_enabled)

    # ------------------------------------------------------------------
    # GPIO enable/disable toggle
    # ------------------------------------------------------------------

    def _on_gpio_enabled_changed(self, state):
        self._set_gpio_widgets_enabled(state == Qt.Checked.value)

    def _set_gpio_widgets_enabled(self, enabled: bool):
        for w in (self.gpio_port_combo, self.gpio_baud_combo,
                  self.gpio_laser_pin_spin, self.gpio_apply_btn):
            w.setEnabled(enabled)

    # ------------------------------------------------------------------
    # Session restore
    # ------------------------------------------------------------------

    def _load_from_session(self):
        s = self._session.get_session("setup")

        # Camera
        idx = self.cam_driver_combo.findText(s.get("camera_driver", "opencv"))
        if idx >= 0:
            self.cam_driver_combo.setCurrentIndex(idx)
        self.cam_index_spin.setValue(s.get("camera_index", 0))

        # Printer ports
        self._refresh_printer_ports()
        port = s.get("motion_port", "auto")
        pidx = self.printer_port_combo.findText(port)
        if pidx >= 0:
            self.printer_port_combo.setCurrentIndex(pidx)
        else:
            self.printer_port_combo.setCurrentText(port)
        baud_str = str(s.get("motion_baudrate", 115200))
        bidx = self.printer_baud_combo.findText(baud_str)
        if bidx >= 0:
            self.printer_baud_combo.setCurrentIndex(bidx)

        # GPIO
        gpio_enabled = s.get("gpio_enabled", False)
        self.gpio_enabled_chk.setChecked(gpio_enabled)
        self._set_gpio_widgets_enabled(gpio_enabled)
        self._refresh_gpio_ports()
        gport = s.get("gpio_port", "auto")
        gpidx = self.gpio_port_combo.findText(gport)
        if gpidx >= 0:
            self.gpio_port_combo.setCurrentIndex(gpidx)
        else:
            self.gpio_port_combo.setCurrentText(gport)
        gbaud_str = str(s.get("gpio_baudrate", 9600))
        gbidx = self.gpio_baud_combo.findText(gbaud_str)
        if gbidx >= 0:
            self.gpio_baud_combo.setCurrentIndex(gbidx)
        self.gpio_laser_pin_spin.setValue(s.get("gpio_laser_pin", 21))
