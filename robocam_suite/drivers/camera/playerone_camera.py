"""
Player One Astronomy Camera Driver
====================================
Wraps the official ``pyPOACamera`` Python SDK (shipped inside the Player One
Camera SDK zip) to expose a Player One camera as a :class:`Camera`-compatible
object.

SDK installation
----------------
The ``pyPOACamera`` module is **not** on PyPI.  It ships as:

  ``python/pyPOACamera.py``   — pure-Python ctypes wrapper
  ``lib/x64/PlayerOneCamera.dll``  (Windows 64-bit)
  ``lib/x64/PlayerOneCamera.so``   (Linux 64-bit)

``setup.bat`` / ``setup.sh`` download the SDK zip from the Player One website
and extract those two files into ``vendor/playerone/`` inside the project root.
That directory is added to ``sys.path`` by :func:`_ensure_sdk_on_path` so that
``import pyPOACamera`` works without any manual steps.

Video-mode capture
------------------
The driver uses the SDK's *video mode* (``StartExposure(False)``) which
delivers a continuous frame stream.  ``read_frame()`` calls
``GetImageData()`` + ``ImageDataConvert()`` to return a BGR ``numpy`` array
compatible with the rest of the pipeline.
"""
from __future__ import annotations

import sys
import os
import time
import logging
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

from robocam_suite.core.camera import Camera

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SDK path bootstrap
# ---------------------------------------------------------------------------

def _ensure_sdk_on_path() -> bool:
    """Add ``vendor/playerone/`` to ``sys.path`` if it exists.

    Returns True if the directory was found (SDK may or may not import
    successfully — that is checked separately when the driver is instantiated).
    """
    # Resolve vendor dir relative to the project root (two levels above this file)
    here = Path(__file__).resolve()
    project_root = here.parent.parent.parent.parent  # robocam_suite/drivers/camera/ -> project root
    vendor_dir = project_root / "vendor" / "playerone"
    logger.info(f"[PlayerOne] _ensure_sdk_on_path: vendor_dir={vendor_dir} exists={vendor_dir.is_dir()}")
    if vendor_dir.is_dir():
        files = [f.name for f in vendor_dir.iterdir()]
        logger.info(f"[PlayerOne] vendor dir contents: {files}")
        if str(vendor_dir) not in sys.path:
            sys.path.insert(0, str(vendor_dir))
            logger.info(f"[PlayerOne] Added SDK path to sys.path: {vendor_dir}")
        else:
            logger.info(f"[PlayerOne] SDK path already in sys.path")
        return True
    else:
        logger.warning(f"[PlayerOne] vendor dir not found — run: python scripts/install_playerone_sdk.py")
        return False


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

class PlayerOneCamera(Camera):
    """Camera driver for Player One Astronomy cameras using the official SDK.

    Parameters
    ----------
    config:
        Section dict from ``config_manager.get_section("camera")``.
        Relevant keys:

        ``camera_index`` (int, default 0)
            The SDK camera index (0 = first detected camera).
        ``exposure_us`` (int, default 20000)
            Initial exposure time in microseconds.
        ``gain`` (int, default 100)
            Initial gain value.
        ``resolution`` (list[int, int], default [1920, 1080])
            Desired capture resolution [width, height].  The SDK will use the
            nearest supported size.
        ``fps`` (float, default 30.0)
            Desired frame rate (used only for the ``get_fps`` / ``set_fps``
            interface; the SDK does not have a direct FPS setter).
    simulate:
        When True, the driver runs without any physical hardware.
    """

    def __init__(self, config: Optional[dict] = None, simulate: bool = False):
        self._config = config or {}
        self._simulate = simulate

        self._cam_index: int = int(self._config.get("camera_index", 0))
        self._cam_id: Optional[int] = None          # SDK camera ID (≠ index)
        self._opened: bool = False
        self._capturing: bool = False

        self._width: int = 0
        self._height: int = 0
        self._img_format = None                     # POAImgFormat enum value
        self._fps: float = float(self._config.get("fps", 30.0))

        # Buffer for GetImageData — allocated on connect
        self._buf: Optional[np.ndarray] = None

        self._poa = None                            # pyPOACamera module reference

        if self._simulate:
            logger.info("[PlayerOne] Running in SIMULATION MODE")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_sdk(self):
        """Import pyPOACamera, adding the vendor directory to sys.path first."""
        logger.info("[PlayerOne] _load_sdk: calling _ensure_sdk_on_path()")
        found = _ensure_sdk_on_path()
        if not found:
            raise ImportError("[PlayerOne] vendor/playerone/ directory not found. Run: python scripts/install_playerone_sdk.py")
        logger.info("[PlayerOne] _load_sdk: attempting import pyPOACamera")
        try:
            import pyPOACamera as poa  # type: ignore
            logger.info("[PlayerOne] _load_sdk: pyPOACamera imported OK")
            self._poa = poa
        except ImportError as e:
            logger.error(f"[PlayerOne] _load_sdk: import pyPOACamera failed: {e}")
            raise
        except OSError as e:
            logger.error(f"[PlayerOne] _load_sdk: DLL load failed (OSError): {e}")
            raise

    def _check(self, err, operation: str):
        """Raise RuntimeError if the SDK returned a non-OK error code."""
        poa = self._poa
        if err != poa.POAErrors.POA_OK:
            msg = f"[PlayerOne] {operation} failed: {poa.GetErrorString(err)}"
            logger.error(msg)
            raise RuntimeError(msg)

    # ------------------------------------------------------------------
    # Camera ABC implementation
    # ------------------------------------------------------------------

    def connect(self) -> None:
        if self._simulate:
            self._opened = True
            self._width, self._height = self._config.get("resolution", [1920, 1080])
            logger.info("[PlayerOne] Simulated connect OK")
            return

        if self.is_connected:
            return

        logger.info(f"[PlayerOne] connect(): cam_index={self._cam_index} config={self._config}")
        self._load_sdk()
        poa = self._poa

        logger.info("[PlayerOne] Calling GetCameraCount()")
        count = poa.GetCameraCount()
        logger.info(f"[PlayerOne] GetCameraCount() = {count}")
        if count == 0:
            raise ConnectionError("[PlayerOne] No Player One cameras detected.")
        if self._cam_index >= count:
            raise ConnectionError(
                f"[PlayerOne] Camera index {self._cam_index} out of range "
                f"(only {count} camera(s) found)."
            )

        logger.info(f"[PlayerOne] Calling GetCameraProperties({self._cam_index})")
        err, props = poa.GetCameraProperties(self._cam_index)
        if err != poa.POAErrors.POA_OK:
            raise ConnectionError(f"[PlayerOne] GetCameraProperties failed: {err}")
        self._cam_id = props.cameraID
        model = props.cameraModelName.decode(errors="replace")
        logger.info(f"[PlayerOne] Connecting to {model!r} | cameraID={self._cam_id} | "
                    f"maxRes={props.maxWidth}x{props.maxHeight} | bitDepth={props.bitDepth}")

        logger.info(f"[PlayerOne] Calling OpenCamera({self._cam_id})")
        self._check(poa.OpenCamera(self._cam_id), "OpenCamera")
        logger.info(f"[PlayerOne] Calling InitCamera({self._cam_id})")
        self._check(poa.InitCamera(self._cam_id), "InitCamera")
        self._opened = True
        logger.info("[PlayerOne] Camera opened and initialised")

        # Apply resolution from config
        desired_w, desired_h = self._config.get("resolution", [props.maxWidth, props.maxHeight])
        logger.info(f"[PlayerOne] Setting image size: {desired_w}x{desired_h}")
        self._check(
            poa.SetImageSize(self._cam_id, int(desired_w), int(desired_h)),
            "SetImageSize",
        )
        _, self._width, self._height = poa.GetImageSize(self._cam_id)  # returns (err, w, h)
        logger.info(f"[PlayerOne] Actual image size: {self._width}x{self._height}")

        # Choose RAW8 if available, else first supported format
        supported_fmts = props.imgFormats
        logger.info(f"[PlayerOne] Supported image formats: {supported_fmts}")
        preferred = [poa.POAImgFormat.POA_RAW8, poa.POAImgFormat.POA_MONO8]
        self._img_format = next(
            (f for f in preferred if f in supported_fmts),
            supported_fmts[0] if supported_fmts else poa.POAImgFormat.POA_RAW8,
        )
        logger.info(f"[PlayerOne] Selected image format: {self._img_format}")
        self._check(
            poa.SetImageFormat(self._cam_id, self._img_format),
            "SetImageFormat",
        )

        # Apply exposure and gain from config
        exp_us = int(self._config.get("exposure_us", 20_000))
        gain = int(self._config.get("gain", 100))
        logger.info(f"[PlayerOne] Setting exposure={exp_us}us gain={gain}")
        poa.SetExp(self._cam_id, exp_us, False)
        poa.SetGain(self._cam_id, gain, False)

        # Allocate image buffer
        bytes_per_pixel = 2 if self._img_format in (
            poa.POAImgFormat.POA_RAW16, poa.POAImgFormat.POA_MONO16
        ) else 1
        self._buf = np.zeros(self._width * self._height * bytes_per_pixel, dtype=np.uint8)

        logger.info(
            f"[PlayerOne] Connected: {model} | "
            f"{self._width}×{self._height} | format={self._img_format.name}"
        )

    def disconnect(self) -> None:
        if self._simulate:
            self._opened = False
            self._capturing = False
            return

        if self._capturing:
            self.stop_capture()

        if self._opened and self._cam_id is not None:
            try:
                self._poa.CloseCamera(self._cam_id)
            except Exception as e:
                logger.warning(f"[PlayerOne] CloseCamera error (ignored): {e}")
            self._opened = False
            self._cam_id = None
            logger.info("[PlayerOne] Disconnected.")

    def start_capture(self) -> None:
        if self._simulate:
            self._capturing = True
            return
        if not self.is_connected:
            raise RuntimeError("[PlayerOne] Cannot start capture: camera not connected.")
        if self._capturing:
            return
        # False = video mode (continuous)
        self._check(self._poa.StartExposure(self._cam_id, False), "StartExposure (video)")
        self._capturing = True
        logger.debug("[PlayerOne] Video capture started.")

    def stop_capture(self) -> None:
        if self._simulate:
            self._capturing = False
            return
        if self._capturing and self._cam_id is not None:
            try:
                self._poa.StopExposure(self._cam_id)
            except Exception as e:
                logger.warning(f"[PlayerOne] StopExposure error (ignored): {e}")
            self._capturing = False
            logger.debug("[PlayerOne] Video capture stopped.")

    def read_frame(self) -> Optional[np.ndarray]:
        if self._simulate:
            return np.zeros((self._height, self._width, 3), dtype=np.uint8)

        if not self._capturing:
            # Auto-start capture on first read_frame call
            self.start_capture()

        poa = self._poa

        # Poll until a frame is ready (timeout ~100 ms)
        deadline = time.monotonic() + 0.1
        while time.monotonic() < deadline:
            err, ready = poa.ImageReady(self._cam_id)
            if err == poa.POAErrors.POA_OK and ready:
                break
            time.sleep(0.005)
        else:
            return None  # No frame within timeout

        err = poa.GetImageData(self._cam_id, self._buf, 1000)
        if err != poa.POAErrors.POA_OK:
            return None

        frame = poa.ImageDataConvert(self._buf, self._height, self._width, self._img_format)

        # Ensure the frame is BGR uint8 for downstream compatibility
        if frame is None:
            return None
        if frame.dtype != np.uint8:
            # 16-bit → 8-bit (scale to full range)
            frame = (frame >> 8).astype(np.uint8)
        if frame.ndim == 2:
            # Mono or raw Bayer → convert to BGR
            import cv2
            if self._img_format in (poa.POAImgFormat.POA_RAW8, poa.POAImgFormat.POA_RAW16):
                frame = cv2.cvtColor(frame, cv2.COLOR_BAYER_RG2BGR)
            else:
                frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        return frame

    # ------------------------------------------------------------------
    # Resolution / FPS
    # ------------------------------------------------------------------

    def get_resolution(self) -> Tuple[int, int]:
        if self._simulate or not self.is_connected:
            return (self._width or 1920, self._height or 1080)
        _, w, h = self._poa.GetImageSize(self._cam_id)  # returns (err, w, h)
        return (w, h)

    def set_resolution(self, resolution: Tuple[int, int]) -> None:
        w, h = int(resolution[0]), int(resolution[1])
        if self._simulate:
            self._width, self._height = w, h
            return
        if self.is_connected:
            was_capturing = self._capturing
            if was_capturing:
                self.stop_capture()
            self._check(self._poa.SetImageSize(self._cam_id, w, h), "SetImageSize")
            _, self._width, self._height = self._poa.GetImageSize(self._cam_id)  # returns (err, w, h)
            # Re-allocate buffer
            bytes_per_pixel = 2 if self._img_format in (
                self._poa.POAImgFormat.POA_RAW16, self._poa.POAImgFormat.POA_MONO16
            ) else 1
            self._buf = np.zeros(self._width * self._height * bytes_per_pixel, dtype=np.uint8)
            if was_capturing:
                self.start_capture()

    def get_fps(self) -> float:
        return self._fps

    def set_fps(self, fps: float) -> None:
        self._fps = fps
        # The POA SDK does not have a direct FPS setter; frame rate is
        # implicitly controlled by exposure time.  We store the value for
        # informational purposes only.

    # ------------------------------------------------------------------
    # is_connected property
    # ------------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        if self._simulate:
            return self._opened
        return self._opened and self._cam_id is not None
