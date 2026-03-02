"""
Player One Camera Module - Mars 662M and similar via Player One SDK.

Uses the Player One Camera SDK (libPlayerOne_camera.so on Linux) for cameras
that are not standard UVC (e.g. Mars 662M). Exposes the same interface as
USBCamera so preview and capture work with RoboCam-Suite.

Requires: Player One Linux SDK installed (see docs/PLAYER_ONE_MARS_SDK.md).
Optional: SDK Python folder in PLAYERONE_SDK_PYTHON or ~/PlayerOne_Camera_SDK_Linux_*/python
for high-level API; otherwise uses ctypes and the installed .so.

Author: RoboCam-Suite
"""

import os
import sys
import time
import glob
import ctypes
from typing import Optional, Tuple
import numpy as np
from robocam.logging_config import get_logger

logger = get_logger(__name__)

# Project root (RoboCam-Suite directory)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Full SDK in project root (e.g. PlayerOne_Camera_SDK_Linux_V3.10.0/python)
PLAYERONE_SDK_FULL_PYTHON = os.path.join(_PROJECT_ROOT, "PlayerOne_Camera_SDK_Linux_V3.10.0", "python")

# Mars 662M (and similar) supported resolutions
PLAYERONE_SUPPORTED_RESOLUTIONS = [
    (1936, 1100),
    (1920, 1080),
    (1280, 720),
]


def get_playerone_sdk_python_path() -> Optional[str]:
    """Return path to SDK python folder, or None if not found.
    Prefers: project root PlayerOne_Camera_SDK_Linux_*/python, then
    PLAYERONE_SDK_PYTHON, then ~/PlayerOne_Camera_SDK_Linux_*/python.
    """
    if os.path.isdir(PLAYERONE_SDK_FULL_PYTHON):
        return PLAYERONE_SDK_FULL_PYTHON
    try:
        for d in os.listdir(_PROJECT_ROOT):
            if d.startswith("PlayerOne_Camera_SDK_Linux_") and os.path.isdir(os.path.join(_PROJECT_ROOT, d)):
                py_path = os.path.join(_PROJECT_ROOT, d, "python")
                if os.path.isdir(py_path):
                    return py_path
    except Exception:
        pass
    path = os.environ.get("PLAYERONE_SDK_PYTHON")
    if path and os.path.isdir(path):
        return path
    default = os.path.expanduser("~/PlayerOne_Camera_SDK_Linux_V3.10.0/python")
    if os.path.isdir(default):
        return default
    try:
        candidates = glob.glob(os.path.expanduser("~/PlayerOne_Camera_SDK_Linux_*/python"))
        if candidates:
            return candidates[0]
    except Exception:
        pass
    logger.warning(
        "Player One SDK not found. Looked for: %s (exists=%s), PLAYERONE_SDK_PYTHON, ~/PlayerOne_*/python. "
        "On Linux run: bash scripts/populate_playerone_lib.sh",
        PLAYERONE_SDK_FULL_PYTHON,
        os.path.isdir(PLAYERONE_SDK_FULL_PYTHON),
    )
    return None


def _ensure_pypoa_patched_for_linux(sdk_python_path: str) -> bool:
    """If on Linux, patch pyPOACamera.py to load .so instead of .dll. Idempotent. Returns True if patched or already ok."""
    if sys.platform == "win32":
        return True
    py_path = os.path.join(sdk_python_path, "pyPOACamera.py")
    if not os.path.isfile(py_path):
        return False
    try:
        with open(py_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        # Already patched: has platform check and .so load
        if "sys.platform" in content and "LoadLibrary" in content and ".so" in content:
            return True
        # Need to patch: still loading .dll only
        if "PlayerOneCamera.dll" not in content or "dll = cdll.LoadLibrary" not in content:
            return True
        # Ensure sys is imported near the top (after existing imports)
        if "import sys" not in content:
            content = content.replace(
                "from enum import Enum\n",
                "from enum import Enum\nimport sys\n",
                1,
            )
        # Replace the single-line LoadLibrary(.dll) with platform-specific block
        new_content = content
        for line in content.split("\n"):
            if "dll" in line and "LoadLibrary" in line and "PlayerOneCamera.dll" in line:
                # Replace this line with Linux/Windows branch
                replacement = (
                    'dll = (cdll.LoadLibrary("./PlayerOneCamera.dll") if sys.platform == "win32" '
                    'else cdll.LoadLibrary("libPlayerOneCamera.so"))'
                )
                new_content = content.replace(line, replacement, 1)
                break
        if new_content != content:
            with open(py_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(new_content)
            logger.info("Patched %s for Linux (.so load)", py_path)
        return True
    except Exception as e:
        logger.debug("Could not patch pyPOACamera.py: %s", e)
        return False


def get_playerone_camera_count() -> int:
    """Return number of connected Player One cameras (0 if SDK not available)."""
    sdk_path = get_playerone_sdk_python_path()
    if sdk_path is None:
        return 0
    _ensure_pypoa_patched_for_linux(sdk_path)
    try:
        prev = list(sys.path)
        if sdk_path not in sys.path:
            sys.path.insert(0, sdk_path)
        try:
            import pyPOACamera as poa  # type: ignore[import-not-found]
            count = poa.GetCameraCount()
            return int(count) if count is not None else 0
        finally:
            sys.path[:] = prev
    except Exception as e:
        logger.debug("Player One SDK not available: %s", e)
        return 0


class _DummyCap:
    """Dummy object so PreviewWindow's usb_camera.cap.isOpened() works."""
    def __init__(self, opened: bool):
        self._opened = opened
    def isOpened(self) -> bool:
        return self._opened


class PlayerOneCamera:
    """
    Camera interface for Player One Mars 662M (and similar) via SDK.

    Mirrors USBCamera interface: read_frame(), preset_resolution, fps,
    take_photo_and_save, start_recording_video, write_frame, stop_recording_video,
    release. Uses SDK Python bindings when available.
    """

    def __init__(
        self,
        resolution: Tuple[int, int] = (1920, 1080),
        fps: float = 30.0,
        camera_index: int = 0,
    ) -> None:
        self.preset_resolution: Tuple[int, int] = resolution
        self.fps: float = fps
        self.camera_index: int = camera_index
        self._opened: bool = False
        self._writer: Optional[object] = None
        self._recording_path: Optional[str] = None
        self._poa = None  # pyPOACamera module or ctypes wrapper
        self._camera_id: Optional[int] = None
        self._img_width: int = resolution[0]
        self._img_height: int = resolution[1]
        self._video_frames: list = []
        # For preview_window: same as OpenCV VideoCapture for duck typing
        self.cap: _DummyCap = _DummyCap(False)
        self._open()

    def _open(self) -> None:
        sdk_path = get_playerone_sdk_python_path()
        if sdk_path is None:
            raise RuntimeError(
                "Player One SDK Python not found. Set PLAYERONE_SDK_PYTHON to the SDK python folder "
                "(e.g. ~/PlayerOne_Camera_SDK_Linux_V3.10.0/python). See docs/PLAYER_ONE_MARS_SDK.md."
            )
        _ensure_pypoa_patched_for_linux(sdk_path)
        prev = list(sys.path)
        if sdk_path not in sys.path:
            sys.path.insert(0, sdk_path)
        try:
            import pyPOACamera as poa  # type: ignore[import-not-found]
            self._poa = poa
            count = poa.GetCameraCount()
            if not count or count <= self.camera_index:
                raise RuntimeError("No Player One camera at index %d (count=%s)" % (self.camera_index, count))
            # Get camera ID from properties (index != camera ID)
            err, props = poa.GetCameraProperties(self.camera_index)
            if err != poa.POAErrors.POA_OK:
                raise RuntimeError(
                    "GetCameraProperties failed: %s. "
                    "If you see 'libusb requires write access to USB device nodes', add a udev rule so the camera is accessible without root. "
                    "See docs/PLAYER_ONE_MARS_SDK.md step 3 (Mars 662M: vendor a0a0, product 6621). "
                    "Run: echo 'SUBSYSTEM==\"usb\", ATTRS{idVendor}==\"a0a0\", ATTRS{idProduct}==\"6621\", MODE=\"0666\"' | sudo tee /etc/udev/rules.d/99-playerone-mars662m.rules && sudo udevadm control --reload-rules && sudo udevadm trigger && unplug and replug the camera."
                ) from None
            self._camera_id = props.cameraID
            err = poa.OpenCamera(self._camera_id)
            if err != poa.POAErrors.POA_OK:
                raise RuntimeError(
                    "OpenCamera failed: %s. "
                    "Ensure USB permissions: see docs/PLAYER_ONE_MARS_SDK.md step 3 (udev rule for Mars 662M)."
                    % getattr(err, "name", err)
                ) from None
            err = poa.InitCamera(self._camera_id)
            if err != poa.POAErrors.POA_OK:
                raise RuntimeError(
                    "InitCamera failed: %s. "
                    "Ensure USB permissions: see docs/PLAYER_ONE_MARS_SDK.md step 3 (udev rule)."
                    % getattr(err, "name", err)
                ) from None
            # Set image size and format
            w, h = self.preset_resolution
            poa.SetImageStartPos(self._camera_id, 0, 0)
            poa.SetImageSize(self._camera_id, w, h)
            poa.SetImageBin(self._camera_id, 1)
            poa.SetImageFormat(self._camera_id, poa.POAImgFormat.POA_RAW8)
            self._img_width = w
            self._img_height = h
            self._opened = True
            self.cap = _DummyCap(True)
            logger.info("Player One camera opened: %dx%d", w, h)
        finally:
            sys.path[:] = prev

    def start(self) -> None:
        if not self._opened and self._poa is not None:
            self._open()

    def set_resolution(self, width: int, height: int) -> None:
        self.preset_resolution = (width, height)
        if self._opened and self._poa is not None:
            self._poa.SetImageSize(self._camera_id, width, height)
            self._img_width = width
            self._img_height = height

    def take_photo_and_save(self, file_path: Optional[str] = None) -> None:
        if file_path is None:
            file_path = "%s.png" % time.strftime("%Y%m%d_%H%M%S")
        frame = self.read_frame()
        if frame is None:
            raise RuntimeError("Failed to read frame from Player One camera")
        import cv2
        ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else "png"
        if ext in ("jpg", "jpeg"):
            cv2.imwrite(file_path, frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
        else:
            cv2.imwrite(file_path, frame)

    def capture_grayscale_frame(self) -> Optional[np.ndarray]:
        return self.read_frame()

    def read_frame(self) -> Optional[np.ndarray]:
        if not self._opened or self._poa is None:
            return None
        poa = self._poa
        cid = self._camera_id
        # Start exposure (video mode = True for continuous)
        poa.StartExposure(cid, True)
        # Wait for frame (short timeout)
        for _ in range(100):
            _err, ready = poa.ImageReady(cid)
            if ready:
                break
            time.sleep(0.01)
        else:
            return None
        # Get image data (SDK expects numpy array)
        w, h = self._img_width, self._img_height
        buf = np.zeros(w * h, dtype=np.uint8)
        err = poa.GetImageData(cid, buf, 500)
        if err != poa.POAErrors.POA_OK:
            return None
        return buf.reshape((h, w)).copy()

    def start_recording_video(self, video_path: Optional[str] = None, fps: Optional[float] = None) -> None:
        if video_path is None:
            video_path = "%s.avi" % time.strftime("%Y%m%d_%H%M%S")
        if not self._opened:
            raise RuntimeError("Player One camera not open")
        if self._writer is not None:
            self.stop_recording_video()
        self._video_frames = []
        self._recording_path = video_path
        logger.info("Player One recording started: %s", video_path)

    def stop_recording_video(self) -> None:
        if self._writer is not None:
            self._writer = None
        if self._recording_path and self._video_frames:
            import cv2
            w, h = self._img_width, self._img_height
            fourcc = cv2.VideoWriter_fourcc(*"MJPG")
            writer = cv2.VideoWriter(self._recording_path, fourcc, self.fps, (w, h), False)
            for f in self._video_frames:
                writer.write(f)
            writer.release()
            logger.info("Player One recording stopped: %s", self._recording_path)
        self._recording_path = None
        self._video_frames = []

    def write_frame(self, frame: np.ndarray) -> bool:
        if self._recording_path is None:
            return False
        self._video_frames.append(frame.copy())
        return True

    def release(self) -> None:
        if self._writer is not None or self._video_frames:
            self.stop_recording_video()
        if self._opened and self._poa is not None:
            try:
                self._poa.CloseCamera(self._camera_id)
            except Exception:
                pass
            self._opened = False
        self.cap = _DummyCap(False)
        self._poa = None
        logger.info("Player One camera released")
