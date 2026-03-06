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
    QCheckBox, QScrollArea, QTextEdit, QSizePolicy,
    QDoubleSpinBox, QFrame,
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
# Player One SDK path bootstrap
# ---------------------------------------------------------------------------

def _ensure_poa_path() -> Optional[str]:
    """Add vendor/playerone/ to sys.path so pyPOACamera can be imported.

    The directory is expected at ``<project_root>/vendor/playerone/``.
    This function is idempotent — it only adds the path once.
    Returns the path to the vendor directory if it exists, else None.
    """
    import sys
    from pathlib import Path
    # This file lives at robocam_suite/ui/setup_panel.py
    # Project root is therefore three levels up.
    project_root = Path(__file__).resolve().parent.parent.parent
    vendor_dir = project_root / "vendor" / "playerone"
    logger.info(f"[PlayerOne] vendor dir: {vendor_dir} | exists={vendor_dir.is_dir()}")
    if vendor_dir.is_dir():
        # List files so we can confirm DLL/so is present
        files = [f.name for f in vendor_dir.iterdir()]
        logger.info(f"[PlayerOne] vendor dir contents: {files}")
        if str(vendor_dir) not in sys.path:
            sys.path.insert(0, str(vendor_dir))
            logger.info(f"[PlayerOne] SDK path added to sys.path: {vendor_dir}")
        else:
            logger.info(f"[PlayerOne] SDK path already in sys.path: {vendor_dir}")
        return str(vendor_dir)
    else:
        logger.warning(f"[PlayerOne] vendor dir not found — SDK not installed. Run: python scripts/install_playerone_sdk.py")
        return None


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

        Tries three methods in order:
          1. cv2-enumerate-cameras  — returns devices with backend=700 (WIA)
          2. WMI Win32_PnPEntity    — PNPClass="Image"
          3. WMI Win32_PnPEntity    — PNPClass="Camera" (catches some scanners)
        Returns empty list if all methods fail or no devices found.
        """
        seen: set = set()
        devices: list = []

        # Method 1: cv2-enumerate-cameras — enumerates WIA devices as backend 700
        try:
            from cv2_enumerate_cameras import enumerate_cameras, CAP_MSMF  # type: ignore
            # Backend 700 = CAP_MSMF on Windows; WIA scanners appear here with
            # index -1 or a non-standard index.  We collect any entry whose name
            # is not already in the OpenCV VideoCapture list (checked later).
            for info in enumerate_cameras(CAP_MSMF):
                key = info.name.strip().lower()
                if key and key not in seen:
                    seen.add(key)
                    devices.append((info.name.strip(), f"cv2enum:{info.index}"))
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"[CameraEnum] cv2-enumerate-cameras imaging scan failed: {e}")

        # Method 2: WMI PNPClass="Image" — scanners, WIA microscopes, etc.
        try:
            import wmi  # type: ignore
            c = wmi.WMI()
            for dev in c.Win32_PnPEntity(PNPClass="Image"):
                if not dev.Name:
                    continue
                key = dev.Name.strip().lower()
                if key not in seen:
                    seen.add(key)
                    devices.append((dev.Name.strip(), dev.DeviceID or ""))
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"[CameraEnum] WMI imaging devices failed: {e}")

        return devices

    def run(self):
        devices = []
        try:
            self._run_inner(devices)
        except Exception as e:
            logger.error(f"[CameraEnum] Unexpected error during camera scan: {e}", exc_info=True)
        if not devices:
            devices.append(("No cameras detected", "opencv", 0))
        self.cameras_found.emit(devices)

    def _run_inner(self, devices: list):  # noqa: C901
        os_name = platform.system()

        # Pre-fetch Windows device names once (avoids repeated COM calls)
        win_names: dict = {}
        if os_name == "Windows":
            win_names = self._get_windows_camera_names()

        # --- Raspberry Pi HQ Camera (via picamera2) ---
        if os_name == "Linux":
            try:
                # Use the same robust check as in the driver
                from robocam_suite.drivers.camera.picamera2_camera import _get_picamera2_class
                Picamera2 = _get_picamera2_class()
                
                # Also check for common libcamera/picamera2 video devices
                import os
                has_v4l2_pisp = os.path.exists("/dev/video0") or os.path.exists("/dev/media0")
                
                if Picamera2 is not None or has_v4l2_pisp:
                    logger.info(f"[CameraEnum] Picamera2/libcamera detected (lib={Picamera2 is not None}, dev={has_v4l2_pisp})")
                    devices.append(("Raspberry Pi HQ Camera (picamera2)", "picamera2", 0))
                else:
                    logger.debug("[CameraEnum] Picamera2/libcamera not detected.")
            except Exception as e:
                logger.debug(f"[CameraEnum] Picamera2 probe failed: {e}")

        # --- OpenCV USB / built-in cameras ---
        # On Windows we use the MSMF backend explicitly to avoid the OrbbecSDK
        # (obsensor) backend probing every index and printing noisy errors.
        try:
            import cv2
            _backend = cv2.CAP_MSMF if os_name == "Windows" else cv2.CAP_ANY
            for idx in range(10):
                cap = cv2.VideoCapture(idx, _backend)
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

        # --- Player One Astronomy cameras (via pyPOACamera SDK) ---
        # The SDK ships as vendor/playerone/pyPOACamera.py + PlayerOneCamera.dll.
        # _ensure_poa_path() adds that directory to sys.path so the import works.
        logger.info("[CameraEnum] Starting Player One SDK probe...")
        try:
            poa_dir = _ensure_poa_path()
            
            # Patch the wrapper for Linux/RPi if it's the default one
            if poa_dir:
                wrapper_path = os.path.join(poa_dir, "pyPOACamera.py")
                if os.path.exists(wrapper_path):
                    try:
                        with open(wrapper_path, 'r') as f:
                            content = f.read()
                        
                        # If the wrapper is the default one that only looks for .dll
                        if 'LoadLibrary("./PlayerOneCamera.dll")' in content:
                            logger.info("[CameraEnum] Patching Player One SDK wrapper for Linux/RPi...")
                            # Replace the hardcoded .dll path with a more flexible one
                            new_content = content.replace(
                                'dll = cdll.LoadLibrary("./PlayerOneCamera.dll")',
                                'import os, platform; lib_name = "libPlayerOneCamera.so" if platform.system() == "Linux" else "PlayerOneCamera.dll"; dll = cdll.LoadLibrary(os.path.join(os.path.dirname(__file__), lib_name))'
                            )
                            with open(wrapper_path, 'w') as f:
                                f.write(new_content)
                    except Exception as e:
                        logger.warning(f"[CameraEnum] Failed to patch Player One wrapper: {e}")

            logger.info("[CameraEnum] Attempting: import pyPOACamera")
            import pyPOACamera as poa  # type: ignore
            logger.info("[CameraEnum] pyPOACamera imported successfully")
            count = poa.GetCameraCount()
            logger.info(f"[CameraEnum] PlayerOne camera count: {count}")
            for i in range(count):
                err, props = poa.GetCameraProperties(i)
                if err != poa.POAErrors.POA_OK:
                    logger.warning(f"[CameraEnum] GetCameraProperties({i}) failed: {err}")
                    continue
                model = props.cameraModelName.decode(errors="replace").strip()
                label = f"PlayerOne — {model} (index {i})"
                logger.info(f"[CameraEnum] Found PlayerOne camera: {label}")
                devices.append((label, "playerone", i))
        except ImportError as e:
            logger.warning(f"[CameraEnum] pyPOACamera import failed (SDK not installed or DLL missing): {e}")
        except Exception as e:
            logger.error(f"[CameraEnum] PlayerOne probe failed: {e}", exc_info=True)

        # --- Windows Imaging Devices (WIA class: microscopes, scientific cameras) ---
        # WMI lists devices like the POA MARS 662M under PNPClass="Image" even
        # though they are fully accessible via cv2.VideoCapture.  We therefore
        # cross-reference each WIA device against the OpenCV-probed list:
        #
        #   * If the device name matches an already-found OpenCV entry, skip it
        #     (it is already listed with the correct driver=opencv and index).
        #   * If the device name appears in win_names (resolved by
        #     cv2-enumerate-cameras / pygrabber) but was NOT opened by the
        #     VideoCapture loop (e.g. the camera was at an index > 9, or it
        #     failed to open but is still enumerable), add it as driver=opencv
        #     with the index from win_names so the hardware manager can connect it.
        #   * Otherwise add it as driver=imaging_device with the PnP device ID
        #     and a note that a vendor SDK may be required.
        if os_name == "Windows":
            try:
                imaging_devs = self._get_windows_imaging_devices()

                # Build lookup structures from the OpenCV probe results.
                opencv_names_lower = {
                    d[0].split(" (index ")[0].strip().lower()
                    for d in devices if d[1] == "opencv"
                }
                # Also build a lower-case set from playerone entries so we
                # don't add a WIA duplicate for a camera already found via SDK.
                playerone_names_lower = {
                    d[0].split(" (index ")[0].strip().lower()
                    for d in devices if d[1] == "playerone"
                }
                # Reverse map: lower-case name -> OpenCV index (from win_names)
                win_names_lower_to_idx = {
                    v.strip().lower(): k for k, v in win_names.items()
                }

                for dev_name, dev_id in imaging_devs:
                    dev_lower = dev_name.strip().lower()

                    # Already listed via OpenCV probe — skip.
                    already_listed = any(
                        dev_lower in ocv or ocv in dev_lower
                        for ocv in opencv_names_lower
                    )
                    if already_listed:
                        continue

                    # Already listed via Player One SDK probe — skip.
                    already_poa = any(
                        dev_lower in poa or poa in dev_lower
                        for poa in playerone_names_lower
                    )
                    if already_poa:
                        continue

                    # Known to cv2-enumerate-cameras/win_names but not yet opened —
                    # promote to driver=opencv so the hardware manager can open it.
                    if dev_lower in win_names_lower_to_idx:
                        opencv_idx = win_names_lower_to_idx[dev_lower]
                        label = f"{dev_name.strip()} (index {opencv_idx})"
                        devices.append((label, "opencv", opencv_idx))
                    else:
                        # Truly WIA-only (scanner, ASCOM device, etc.)
                        label = f"{dev_name.strip()}  [Imaging Device — may need vendor SDK]"
                        devices.append((label, "imaging_device", dev_id))
            except Exception as e:
                logger.warning(f"[CameraEnum] Windows Imaging Devices scan failed: {e}")

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

        # ("No cameras detected" fallback and cameras_found.emit are handled
        #  in run() after _run_inner returns.)


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
        root.addWidget(self._build_printer_profiles_group())
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
        
        # Automatic camera scan on startup
        QTimer.singleShot(500, self._enumerate_cameras)

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
        
        # Force Reset button (Pi only)
        import platform
        if platform.system() == "Linux":
            self.cam_reset_btn = QPushButton("Force Reset Camera")
            self.cam_reset_btn.setToolTip("Kill zombie processes holding the camera lock (Pi only)")
            self.cam_reset_btn.clicked.connect(self._on_force_reset_camera)
            # Use a horizontal layout for the buttons to keep them together
            btn_layout = QHBoxLayout()
            btn_layout.addWidget(self.cam_scan_btn)
            btn_layout.addWidget(self.cam_reset_btn)
            layout.addLayout(btn_layout, 0, 2)
        else:
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

    def _build_printer_profiles_group(self) -> QGroupBox:
        """Feed-rate, acceleration, and jerk profile editor with sliders."""
        from robocam_suite.ui.profile_slider import ProfileSliderRow, ProfileSliderPair

        grp = QGroupBox("3-D Printer \u2014 Motion Profiles")
        grp.setToolTip(
            "Read the current feed-rate, acceleration, and jerk settings from\n"
            "the printer (via M503), edit them with the sliders, then Apply.\n"
            "The orange triangle on each slider marks the firmware default.\n"
            "X and Y are paired; check \u2018Link X=Y\u2019 to move them together."
        )
        outer = QVBoxLayout(grp)
        outer.setSpacing(6)

        # ---- action buttons row ----
        btn_row = QHBoxLayout()
        self._profiles_read_btn = QPushButton("Read from Printer")
        self._profiles_read_btn.setToolTip(
            "Query M503 and populate all sliders with the current printer values.\n"
            "Also called automatically when the printer connects."
        )
        self._profiles_read_btn.clicked.connect(self._read_profiles)
        btn_row.addWidget(self._profiles_read_btn)

        self._profiles_apply_btn = QPushButton("Apply to Printer")
        self._profiles_apply_btn.setToolTip(
            "Send M203/M201/M204/M205 with the current slider values\n"
            "and save to EEPROM (M500)."
        )
        self._profiles_apply_btn.clicked.connect(self._apply_profiles)
        btn_row.addWidget(self._profiles_apply_btn)

        self._profiles_reset_btn = QPushButton("Reset to Defaults")
        self._profiles_reset_btn.setToolTip(
            "Restore all sliders to the values last read from the printer\n"
            "without sending any commands."
        )
        self._profiles_reset_btn.clicked.connect(self._reset_profiles)
        btn_row.addWidget(self._profiles_reset_btn)
        outer.addLayout(btn_row)

        # ---- status label ----
        self._profiles_status = QLabel(
            "Not read \u2014 connect the printer or click \u2018Read from Printer\u2019."
        )
        self._profiles_status.setStyleSheet("font-size: 10px; color: #888; font-style: italic;")
        outer.addWidget(self._profiles_status)

        # Storage
        self._profile_sliders: dict = {}   # key -> ProfileSliderRow or ProfileSliderPair
        self._profile_defaults: dict = {}  # key -> float

        def _row(key, label, lo, hi, step=1.0, dec=1, suffix=" mm/s"):
            r = ProfileSliderRow(label, lo, hi, step=step, decimals=dec, suffix=suffix)
            r.setEnabled(False)
            self._profile_sliders[key] = r
            return r

        def _pair(key_x, key_y, lo, hi, step=1.0, dec=1, suffix=" mm/s"):
            p = ProfileSliderPair(lo, hi, step=step, decimals=dec, suffix=suffix)
            p.setEnabled(False)
            self._profile_sliders[key_x] = p   # pair stored under x key
            self._profile_sliders["__pair_" + key_x] = key_y  # marker
            return p

        # ---- Max Feed Rates (M203) ----
        sec1 = QGroupBox("Max Feed Rates  (M203, mm/s)")
        v1 = QVBoxLayout(sec1)
        v1.setSpacing(2)
        self._feed_xy = _pair("max_feed_x", "max_feed_y", 0, 2000, step=5.0, dec=1)
        self._feed_xy.setToolTip("Maximum XY feed rate (M203 X… Y…).")
        v1.addWidget(self._feed_xy)
        v1.addWidget(_row("max_feed_z", "Z:", 0, 50, step=0.5, dec=1,
                          suffix=" mm/s"))
        outer.addWidget(sec1)

        # ---- Acceleration (M201 + M204) ----
        sec2 = QGroupBox("Acceleration  (M201 max / M204 travel, mm/s\u00b2)")
        v2 = QVBoxLayout(sec2)
        v2.setSpacing(2)
        self._accel_xy = _pair("max_accel_x", "max_accel_y", 0, 5000, step=50.0, dec=0,
                               suffix=" mm/s\u00b2")
        self._accel_xy.setToolTip("Maximum XY acceleration (M201 X\u2026 Y\u2026).")
        v2.addWidget(self._accel_xy)
        v2.addWidget(_row("max_accel_z", "Max Z:",  0, 500,   step=5.0,  dec=0, suffix=" mm/s\u00b2"))
        v2.addWidget(_row("accel_travel", "Travel:", 0, 5000,  step=50.0, dec=0, suffix=" mm/s\u00b2"))
        outer.addWidget(sec2)

        # ---- Jerk (M205) ----
        sec3 = QGroupBox("Jerk  (M205, mm/s)")
        v3 = QVBoxLayout(sec3)
        v3.setSpacing(2)
        self._jerk_xy = _pair("jerk_x", "jerk_y", 0, 30, step=0.5, dec=1)
        self._jerk_xy.setToolTip("XY jerk limit (M205 X… Y…).")
        v3.addWidget(self._jerk_xy)
        v3.addWidget(_row("jerk_z", "Z:", 0, 5,  step=0.1, dec=2))
        outer.addWidget(sec3)

        return grp

    def _populate_profiles(self, profiles: dict):
        """Internal: fill sliders from a profiles dict and mark defaults."""
        from robocam_suite.ui.profile_slider import ProfileSliderPair
        self._profile_defaults = dict(profiles)

        # Pairs: max_feed_x/y, max_accel_x/y, jerk_x/y
        pairs = [
            ("max_feed_x",  "max_feed_y",  self._feed_xy),
            ("max_accel_x", "max_accel_y", self._accel_xy),
            ("jerk_x",      "jerk_y",      self._jerk_xy),
        ]
        for kx, ky, widget in pairs:
            vx = profiles.get(kx)
            vy = profiles.get(ky)
            if vx is not None and vy is not None:
                widget.set_values(float(vx), float(vy))
                widget.set_defaults(float(vx), float(vy))
                widget.setEnabled(True)

        # Single rows
        single_keys = [
            "max_feed_z",
            "max_accel_z", "accel_travel",
            "jerk_z",
        ]
        for key in single_keys:
            val = profiles.get(key)
            widget = self._profile_sliders.get(key)
            if val is not None and widget is not None:
                widget.set_value(float(val))
                widget.set_default(float(val))
                widget.setEnabled(True)

    def _read_profiles(self):
        """Query M503, populate sliders, and store defaults."""
        try:
            mc = self._hw.get_motion_controller()
            if not mc.is_connected:
                self._profiles_status.setText("Error: printer not connected.")
                self._profiles_status.setStyleSheet("font-size: 10px; color: red;")
                return
            profiles = mc.read_profiles()
        except Exception as e:
            self._profiles_status.setText(f"Error reading profiles: {e}")
            self._profiles_status.setStyleSheet("font-size: 10px; color: red;")
            return

        if not profiles:
            self._profiles_status.setText("No profile data returned by printer.")
            self._profiles_status.setStyleSheet("font-size: 10px; color: orange;")
            return

        self._populate_profiles(profiles)
        # Push profiles into the motion controller so moves use the new feed rates.
        try:
            mc.set_profiles(profiles)
        except Exception:
            pass
        self._profiles_status.setText(
            "Values read from printer. Adjust sliders and click \u2018Apply to Printer\u2019."
        )
        self._profiles_status.setStyleSheet("font-size: 10px; color: green;")

    def _apply_profiles(self):
        """Send current slider values to the printer."""
        try:
            mc = self._hw.get_motion_controller()
            if not mc.is_connected:
                self._profiles_status.setText("Error: printer not connected.")
                self._profiles_status.setStyleSheet("font-size: 10px; color: red;")
                return

            # Collect values from pairs and single rows
            profiles: dict = {}
            pairs = [
                ("max_feed_x",  "max_feed_y",  self._feed_xy),
                ("max_accel_x", "max_accel_y", self._accel_xy),
                ("jerk_x",      "jerk_y",      self._jerk_xy),
            ]
            for kx, ky, widget in pairs:
                if widget.isEnabled():
                    profiles[kx] = widget.x_value()
                    profiles[ky] = widget.y_value()

            single_keys = [
                "max_feed_z",
                "max_accel_z", "accel_travel",
                "jerk_z",
            ]
            for key in single_keys:
                widget = self._profile_sliders.get(key)
                if widget is not None and widget.isEnabled():
                    profiles[key] = widget.value()

            mc.apply_profiles(profiles)
            # Keep the in-memory profiles in sync.
            mc.set_profiles(profiles)
            self._profiles_status.setText("Profiles applied and saved to EEPROM (M500).")
            self._profiles_status.setStyleSheet("font-size: 10px; color: green;")
        except Exception as e:
            self._profiles_status.setText(f"Error applying profiles: {e}")
            self._profiles_status.setStyleSheet("font-size: 10px; color: red;")

    def _reset_profiles(self):
        """Restore sliders to the last-read values."""
        if not self._profile_defaults:
            self._profiles_status.setText("Nothing to reset \u2014 read from printer first.")
            self._profiles_status.setStyleSheet("font-size: 10px; color: orange;")
            return
        self._populate_profiles(self._profile_defaults)
        self._profiles_status.setText("Reset to last-read values.")
        self._profiles_status.setStyleSheet("font-size: 10px; color: #888;")

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

    def _on_force_reset_camera(self) -> None:
        """Attempt to release camera resources by killing zombie processes."""
        from robocam_suite.drivers.camera.picamera2_camera import Picamera2Camera
        from PySide6.QtWidgets import QMessageBox
        
        reply = QMessageBox.question(
            self, "Force Reset Camera",
            "This will attempt to kill all other processes holding the camera lock.\n"
            "It may cause a temporary flicker or app hang.\n\n"
            "Proceed?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            success = Picamera2Camera.force_reset()
            if success:
                QMessageBox.information(self, "Success", "Force reset commands sent.\nPlease try scanning and connecting again.")
            else:
                QMessageBox.warning(self, "Failed", "Force reset failed. You may need to run 'pkill -9 libcamera' manually.")

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

        # imaging_device entries that survived deduplication are truly WIA-only
        # (e.g. scanners) and cannot be opened by OpenCV.  Show a warning and
        # do nothing so the hardware manager is not left in a broken state.
        if driver == "imaging_device":
            from PySide6.QtWidgets import QMessageBox
            # Check if this looks like a Player One camera so we can give
            # a more specific fix instruction.
            label_lower = label.lower()
            is_poa = any(k in label_lower for k in ("player one", "playerone", "poa", "mars", "neptune", "uranus", "saturn", "jupiter"))
            if is_poa:
                extra = (
                    "This looks like a Player One camera.\n\n"
                    "The Player One SDK has not been installed yet.  "
                    "Run the following command in your project directory, "
                    "then re-scan:\n\n"
                    "    python scripts\\install_playerone_sdk.py"
                )
            else:
                extra = (
                    "To use this device you need the manufacturer\u2019s SDK "
                    "(e.g. EPSON Scan SDK or an ASCOM driver)."
                )
            QMessageBox.warning(
                self,
                "Vendor SDK Required",
                f"“{label}” is a WIA Imaging Device that cannot be opened "
                f"directly by OpenCV.\n\n{extra}",
            )
            return

        # Disconnect the existing camera instance so the next get_camera() call
        # creates a fresh one with the updated config.
        if self._hw._camera is not None:
            try:
                self._hw._camera.disconnect()
            except Exception:
                pass
            self._hw._camera = None

        self._cfg.update_section("camera", {"driver": driver, "camera_index": device_id})
        self._session.update_session("setup", {
            "camera_driver": driver,
            "camera_index": device_id,
            "camera_label": label,
        })
        logger.info(f"Camera config updated: driver={driver}, device_id={device_id} ({label})")

        # Reconnect with the new settings.
        try:
            self._hw.get_camera().connect()
            logger.info("[Setup] Camera reconnected successfully.")
        except Exception as e:
            logger.error(f"[Setup] Camera reconnect failed: {e}")
        self._refresh_status()

    def _apply_printer(self):
        port = self.printer_port_combo.currentText() or "auto"
        baud = int(self.printer_baud_combo.currentData() or 115200)

        # Disconnect existing instance before replacing it.
        if self._hw._motion_controller is not None:
            try:
                self._hw._motion_controller.disconnect()
            except Exception:
                pass
            self._hw._motion_controller = None

        self._cfg.update_section("motion_controller", {"port": port, "baudrate": baud})
        self._session.update_session("setup", {"motion_port": port, "motion_baudrate": baud})
        logger.info(f"Printer config updated: port={port}, baudrate={baud}")

        # Reconnect with the new settings.
        try:
            self._hw.get_motion_controller().connect()
            logger.info("[Setup] Printer reconnected successfully.")
            # Auto-read motion profiles now that the printer is connected.
            try:
                self._read_profiles()
            except Exception as pe:
                logger.warning(f"[Setup] Auto-read profiles after connect failed: {pe}")
        except Exception as e:
            logger.error(f"[Setup] Printer reconnect failed: {e}")
        self._refresh_status()

    def _apply_gpio(self):
        enabled = self.gpio_enabled_chk.isChecked()
        port = self.gpio_port_combo.currentText() or "auto"
        baud = int(self.gpio_baud_combo.currentData() or 9600)
        laser_pin = self.gpio_laser_pin_spin.value()

        # Disconnect existing instance before replacing it.
        if self._hw._gpio_controller is not None:
            try:
                self._hw._gpio_controller.disconnect()
            except Exception:
                pass
            self._hw._gpio_controller = None

        self._cfg.update_section("gpio_controller", {
            "enabled": enabled, "port": port,
            "baudrate": baud, "laser_pin": laser_pin,
        })
        self._session.update_session("setup", {
            "gpio_enabled": enabled, "gpio_port": port,
            "gpio_baudrate": baud, "gpio_laser_pin": laser_pin,
        })
        logger.info(f"GPIO config updated: enabled={enabled}, port={port}, baud={baud}, pin={laser_pin}")

        # Reconnect with the new settings.
        try:
            self._hw.get_gpio_controller().connect()
            logger.info("[Setup] GPIO reconnected successfully.")
        except Exception as e:
            logger.error(f"[Setup] GPIO reconnect failed: {e}")
        self._refresh_status()

    def _connect_all(self):
        try:
            self._hw.connect_all()
        except Exception as e:
            logger.error(f"Connect all failed: {e}")
        self._refresh_status()
        # Auto-read motion profiles if the printer is now connected.
        try:
            if self._hw.get_motion_controller().is_connected:
                self._read_profiles()
        except Exception as pe:
            logger.warning(f"[Setup] Auto-read profiles after connect-all failed: {pe}")

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
