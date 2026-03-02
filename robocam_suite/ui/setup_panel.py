"""
Setup Panel — hardware configuration and live connection status.

Camera device enumeration
--------------------------
The camera section lists every camera device detected on the system:
  - USB / built-in webcams via OpenCV (probes indices 0-9)
  - Player One Astronomy cameras via the official SDK (if installed)
  - Raspberry Pi camera via picamera2 (if running on a Pi)

On Windows, real device names are resolved via (in priority order):
  1. cv2-enumerate-cameras  (pip install cv2-enumerate-cameras)
  2. pygrabber               (pip install pygrabber)
  3. WMI                     (pip install wmi)
If none are installed, cameras fall back to "USB Camera (index N)" labels.

No camera preview is shown here; use the Calibration or Experiment tabs.
"""
from __future__ import annotations

import platform
import sys

import serial.tools.list_ports

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QGroupBox, QLabel, QPushButton, QComboBox, QSpinBox,
    QCheckBox, QScrollArea,
)
from PySide6.QtCore import Qt, QTimer, QThread, Signal

from robocam_suite.hw_manager import hw_manager
from robocam_suite.config.config_manager import config_manager
from robocam_suite.session_manager import session_manager
from robocam_suite.logger import setup_logger

logger = setup_logger()

PRINTER_BAUDRATES = [115200, 250000, 57600, 38400, 19200, 9600]
ARDUINO_BAUDRATES = [9600, 115200, 57600, 38400, 19200]


# ---------------------------------------------------------------------------
# Camera device enumeration (runs in a background thread to avoid blocking)
# ---------------------------------------------------------------------------

class _CameraEnumerator(QThread):
    """
    Probes for available camera devices in a background thread.
    Emits a list of (display_label, driver_key, device_id) tuples.
    """
    cameras_found = Signal(list)   # list of (label, driver, device_id)

    @staticmethod
    def _get_windows_camera_names() -> dict:
        """
        Return a dict mapping OpenCV index -> human-readable device name on Windows.
        Tries cv2-enumerate-cameras first (covers both Camera and Imaging Device
        classes), then pygrabber (DirectShow), then WMI as a last resort.
        Returns empty dict on failure so the caller can fall back gracefully.
        """
        # Method 1: cv2-enumerate-cameras — best, covers all DirectShow sources
        # including Imaging Devices (microscopes, scientific cameras, etc.)
        try:
            from cv2_enumerate_cameras import enumerate_cameras  # type: ignore
            return {info.index: info.name for info in enumerate_cameras()}
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"[CameraEnum] cv2-enumerate-cameras failed: {e}")

        # Method 2: pygrabber (DirectShow) — also covers Imaging Devices
        try:
            from pygrabber.dshow_graph import FilterGraph  # type: ignore
            graph = FilterGraph()
            names = graph.get_input_devices()
            return {i: name for i, name in enumerate(names)}
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"[CameraEnum] pygrabber failed: {e}")

        # Method 3: WMI — query both PNPClass="Camera" AND PNPClass="Image"
        # "Camera" covers webcams; "Image" covers WIA imaging devices
        # (microscope cameras, scanners, Player One, etc.)
        try:
            import wmi  # type: ignore
            c = wmi.WMI()
            names = {}
            idx = 0
            for pnp_class in ("Camera", "Image"):
                for cam in c.Win32_PnPEntity(PNPClass=pnp_class):
                    names[idx] = cam.Name
                    idx += 1
            if names:
                return names
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"[CameraEnum] WMI failed: {e}")

        return {}

    @staticmethod
    def _get_windows_imaging_devices() -> list:
        """
        Return a list of (name, pnp_device_id) for devices in the Windows
        'Image' device class (WIA — microscopes, scientific cameras, scanners).
        These are listed separately from OpenCV-accessible cameras because they
        may require a vendor SDK rather than a plain VideoCapture index.
        Returns empty list if WMI is unavailable or no devices found.
        """
        try:
            import wmi  # type: ignore
            c = wmi.WMI()
            devices = []
            for dev in c.Win32_PnPEntity(PNPClass="Image"):
                devices.append((dev.Name, dev.DeviceID))
            return devices
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"[CameraEnum] WMI imaging devices failed: {e}")
        return []

    def run(self):
        devices = []
        os_name = platform.system()

        # Pre-fetch Windows device names once (avoids repeated COM calls)
        win_names: dict = {}
        if os_name == "Windows":
            win_names = self._get_windows_camera_names()

        # --- OpenCV USB / built-in cameras ---
        try:
            import cv2
            for idx in range(10):
                cap = cv2.VideoCapture(idx)
                if cap is not None and cap.isOpened():
                    if os_name == "Windows":
                        raw = win_names.get(idx, "")
                        name = f"{raw} (index {idx})" if raw else f"USB Camera (index {idx})"
                    elif os_name == "Linux":
                        import os
                        v4l = f"/dev/video{idx}"
                        name = f"Video device {idx} ({v4l})" if os.path.exists(v4l) else f"Camera {idx}"
                    elif os_name == "Darwin":
                        name = f"Camera {idx} (AVFoundation)"
                    else:
                        name = f"Camera {idx}"
                    devices.append((name, "opencv", idx))
                    cap.release()
        except Exception as e:
            logger.debug(f"[CameraEnum] OpenCV probe failed: {e}")

        # --- Player One Astronomy cameras ---
        try:
            import PlayerOneCamera as poc  # type: ignore
            count = poc.POACameraCount()
            for i in range(count):
                info = poc.POAGetCameraProperties(i)
                label = f"PlayerOne — {info.cameraModelName.decode()} (index {i})"
                devices.append((label, "playerone", i))
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"[CameraEnum] PlayerOne probe failed: {e}")

        # --- Windows Imaging Devices (WIA class: microscopes, scientific cameras) ---
        # These are listed as informational entries; they may require a vendor SDK
        # (e.g. Player One SDK, ASCOM) rather than a plain OpenCV index.
        # We only add them if they are NOT already covered by the OpenCV probe above
        # (i.e. they don't open via cv2.VideoCapture).
        if os_name == "Windows":
            imaging_devs = self._get_windows_imaging_devices()
            # Build a set of names already found via OpenCV to avoid duplicates
            opencv_names_found = {d[0].split(" (index ")[0].strip() for d in devices
                                  if d[1] == "opencv"}
            for dev_name, dev_id in imaging_devs:
                if dev_name not in opencv_names_found:
                    label = f"{dev_name}  [Imaging Device — may need vendor SDK]"
                    devices.append((label, "imaging_device", dev_id))

        # --- Raspberry Pi camera via picamera2 ---
        try:
            from picamera2 import Picamera2  # type: ignore
            cams = Picamera2.global_camera_info()
            for i, info in enumerate(cams):
                model = info.get("Model", "Pi Camera")
                label = f"Raspberry Pi Camera — {model} (index {i})"
                devices.append((label, "picamera2", i))
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"[CameraEnum] Picamera2 probe failed: {e}")

        if not devices:
            devices.append(("No cameras detected", "opencv", 0))

        self.cameras_found.emit(devices)


# ---------------------------------------------------------------------------
# Status helpers
# ---------------------------------------------------------------------------

def _status_label(text: str = "Unknown") -> QLabel:
    lbl = QLabel(text)
    lbl.setMinimumWidth(100)
    lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
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


# ---------------------------------------------------------------------------
# Setup Panel
# ---------------------------------------------------------------------------

class SetupPanel(QWidget):
    """Hardware configuration and live status panel."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hw = hw_manager
        self._cfg = config_manager
        self._session = session_manager
        # Stores (label, driver, device_id) for each detected camera
        self._camera_devices: list[tuple[str, str, int]] = []

        # Make the whole panel scrollable so it works on small screens
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        scroll.setWidget(inner)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        root = QVBoxLayout(inner)
        root.setSpacing(10)
        root.setContentsMargins(10, 10, 10, 10)

        root.addWidget(self._build_camera_group())
        root.addWidget(self._build_printer_group())
        root.addWidget(self._build_gpio_group())
        root.addWidget(self._build_status_group())
        root.addWidget(self._build_connect_group())
        root.addStretch()

        self._load_from_session()

        # Refresh serial port list and status every 2 s
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._refresh_status)
        self._poll_timer.start(2000)
        self._refresh_status()

        # Enumerate cameras in background immediately
        self._enumerate_cameras()

    # ------------------------------------------------------------------
    # Group builders
    # ------------------------------------------------------------------

    def _build_camera_group(self) -> QGroupBox:
        grp = QGroupBox("Camera")
        layout = QGridLayout(grp)

        layout.addWidget(QLabel("Detected device:"), 0, 0)
        self.cam_device_combo = QComboBox()
        self.cam_device_combo.setMinimumWidth(320)
        self.cam_device_combo.setToolTip(
            "Select a detected camera device.\n"
            "Click 'Scan for Cameras' to refresh the list.\n\n"
            "USB / Webcam — standard cameras via OpenCV (all platforms).\n"
            "PlayerOne   — Player One Astronomy USB cameras (SDK required).\n"
            "Raspberry Pi — Pi Camera Module via picamera2 (Pi only)."
        )
        layout.addWidget(self.cam_device_combo, 0, 1)

        self.cam_scan_btn = QPushButton("Scan for Cameras")
        self.cam_scan_btn.setToolTip(
            "Probe all camera indices and SDK devices.\n"
            "This may take a few seconds."
        )
        self.cam_scan_btn.clicked.connect(self._enumerate_cameras)
        layout.addWidget(self.cam_scan_btn, 0, 2)

        self.cam_scan_status = QLabel("Scanning…")
        self.cam_scan_status.setStyleSheet("color: gray; font-size: 10px;")
        layout.addWidget(self.cam_scan_status, 1, 0, 1, 3)

        # Image format
        layout.addWidget(QLabel("Image format:"), 2, 0)
        self.img_format_combo = QComboBox()
        for fmt in ["PNG", "TIFF", "JPEG"]:
            self.img_format_combo.addItem(fmt)
        self.img_format_combo.setToolTip(
            "File format for saved images (Quick Capture and Image Capture mode).\n"
            "PNG  \u2014 lossless, best for analysis.\n"
            "TIFF \u2014 lossless, maximum compatibility with ImageJ/Fiji.\n"
            "JPEG \u2014 lossy, smaller files."
        )
        layout.addWidget(self.img_format_combo, 2, 1, 1, 2)

        # Video format
        layout.addWidget(QLabel("Video format:"), 3, 0)
        self.vid_format_combo = QComboBox()
        for fmt in ["AVI (MJPG)", "AVI (XVID)", "MP4 (avc1)"]:
            self.vid_format_combo.addItem(fmt)
        self.vid_format_combo.setToolTip(
            "Container and codec for recorded video (Quick Capture and Video Capture mode).\n"
            "AVI (MJPG) \u2014 best cross-platform compatibility.\n"
            "AVI (XVID) \u2014 good compression, widely supported.\n"
            "MP4 (avc1) \u2014 H.264, smallest files; requires compatible OpenCV build."
        )
        layout.addWidget(self.vid_format_combo, 3, 1, 1, 2)

        self.cam_apply_btn = QPushButton("Apply & Reconnect Camera")
        self.cam_apply_btn.clicked.connect(self._apply_camera)
        layout.addWidget(self.cam_apply_btn, 4, 0, 1, 3)
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
    # Camera enumeration
    # ------------------------------------------------------------------

    def _enumerate_cameras(self):
        self.cam_scan_btn.setEnabled(False)
        self.cam_scan_status.setText("Scanning for cameras…")
        self._enumerator = _CameraEnumerator()
        self._enumerator.cameras_found.connect(self._on_cameras_found)
        self._enumerator.start()

    def _on_cameras_found(self, devices: list):
        self._camera_devices = devices
        current_text = self.cam_device_combo.currentText()
        self.cam_device_combo.clear()
        for label, driver, device_id in devices:
            self.cam_device_combo.addItem(label)

        # Try to restore previous selection
        idx = self.cam_device_combo.findText(current_text)
        if idx >= 0:
            self.cam_device_combo.setCurrentIndex(idx)

        count = sum(1 for _, d, _ in devices if d != "opencv" or True)
        real_count = sum(1 for lbl, _, _ in devices if "No cameras" not in lbl)
        self.cam_scan_status.setText(
            f"{real_count} device(s) found." if real_count else "No cameras detected."
        )
        self.cam_scan_btn.setEnabled(True)
        logger.info(f"[Setup] Camera scan complete: {devices}")

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
        sel_idx = self.cam_device_combo.currentIndex()
        if sel_idx < 0 or sel_idx >= len(self._camera_devices):
            return
        label, driver, device_id = self._camera_devices[sel_idx]
        self._cfg.update_section("camera", {"driver": driver, "camera_index": device_id})
        self._session.update_session("setup", {
            "camera_driver": driver,
            "camera_index": device_id,
            "camera_label": label,
        })
        self._hw._camera = None
        logger.info(f"Camera config updated: driver={driver}, device_id={device_id} ({label})")

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
        self._set_gpio_widgets_enabled(bool(state))

    def _set_gpio_widgets_enabled(self, enabled: bool):
        for w in (self.gpio_port_combo, self.gpio_baud_combo,
                  self.gpio_laser_pin_spin, self.gpio_apply_btn):
            w.setEnabled(enabled)

    # ------------------------------------------------------------------
    # Session restore
    # ------------------------------------------------------------------

    def _load_from_session(self):
        s = self._session.get_session("setup")

        # Camera — restore saved label if present; actual list populated after scan
        saved_label = s.get("camera_label", "")
        if saved_label:
            self.cam_device_combo.addItem(saved_label)
            self.cam_scan_status.setText("Previous device restored. Click 'Scan' to refresh.")

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
