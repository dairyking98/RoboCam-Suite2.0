import numpy as np
from typing import Optional, Tuple
import logging
import sys
import importlib.util

from robocam_suite.core.camera import Camera
from robocam_suite.logger import setup_logger

logger = setup_logger()

# Global variable to store the Picamera2 class if successfully imported
_Picamera2Class = None

def _get_picamera2_class():
    """Attempt to import Picamera2 class in a robust way."""
    global _Picamera2Class
    if _Picamera2Class is not None:
        return _Picamera2Class
    
    try:
        from picamera2 import Picamera2
        _Picamera2Class = Picamera2
        return _Picamera2Class
    except ImportError:
        # Try finding it if it's not in the standard path
        if importlib.util.find_spec("picamera2") is not None:
            try:
                import picamera2
                _Picamera2Class = picamera2.Picamera2
                return _Picamera2Class
            except:
                pass
    return None

class Picamera2Camera(Camera):
    """A camera implementation using Raspberry Pi's Picamera2 library."""

    def __init__(self, config: Optional[dict] = None, simulate: bool = False):
        self._config = config or {}
        self._simulate = simulate
        self._picamera2 = None
        self._resolution = self._config.get("resolution", (2028, 1520)) # HQ Camera default
        self._fps = self._config.get("fps", 30.0)
        self._is_running = False

        if self._simulate:
            logger.info("[Picamera2] Running in SIMULATION MODE")

    def connect(self) -> None:
        if self._simulate:
            self._picamera2 = True # type: ignore
            return

        if self.is_connected:
            return

        Picamera2 = _get_picamera2_class()
        if Picamera2 is None:
            raise ImportError("Picamera2 library not found. Ensure you are on a Raspberry Pi with libcamera-python installed.")

        # --- Device Busy Prevention ---
        # 1. Ensure any previous instance is closed
        if self._picamera2 is not None:
            try:
                self.disconnect()
            except:
                pass

        try:
            # We pass a camera index if available, default to 0. 
            cam_idx = self._config.get("camera_index", 0)
            logger.info(f"[Picamera2] Initializing camera {cam_idx}...")
            
            # 2. Add a small retry loop for 'Device Busy' errors
            import time
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    self._picamera2 = Picamera2(camera_num=cam_idx)
                    break
                except Exception as e:
                    if "busy" in str(e).lower() and attempt < max_retries - 1:
                        logger.warning(f"[Picamera2] Device busy, retrying in 1s... (Attempt {attempt+1}/{max_retries})")
                        time.sleep(1)
                    else:
                        raise e
            
            # Configure the camera
            config = self._picamera2.create_video_configuration(
                main={"size": self._resolution, "format": "XBGR8888"},
                fps=self._fps
            )
            self._picamera2.configure(config)
            self._picamera2.start()
            self._is_running = True
            logger.info(f"[Picamera2] Connected and started at {self._resolution} @ {self._fps} FPS")
        except Exception as e:
            if self._picamera2:
                try:
                    self._picamera2.close()
                except:
                    pass
            self._picamera2 = None
            self._is_running = False
            logger.error(f"[Picamera2] Failed to initialize: {e}")
            raise ConnectionError(f"Could not initialize Picamera2: {e}") from e

    def disconnect(self) -> None:
        if self._simulate:
            self._picamera2 = None
            return

        if self._picamera2:
            try:
                if self._is_running:
                    self._picamera2.stop()
                self._picamera2.close()
            except Exception as e:
                logger.error(f"[Picamera2] Error during disconnect: {e}")
            finally:
                self._picamera2 = None
                self._is_running = False
                logger.info("[Picamera2] Disconnected.")

    def start_capture(self) -> None:
        pass

    def stop_capture(self) -> None:
        pass

    def read_frame(self) -> Optional[np.ndarray]:
        if self._simulate:
            return np.zeros((self._resolution[1], self._resolution[0], 3), dtype=np.uint8)

        if not self.is_connected or not self._is_running:
            return None

        try:
            return self._picamera2.capture_array()
        except Exception as e:
            logger.error(f"[Picamera2] Failed to read frame: {e}")
            return None

    def get_resolution(self) -> Tuple[int, int]:
        return self._resolution

    def set_resolution(self, resolution: Tuple[int, int]) -> None:
        self._resolution = resolution
        if self.is_connected and not self._simulate:
            logger.info(f"[Picamera2] Updating resolution to {resolution}. Restarting camera...")
            self.disconnect()
            self.connect()

    def get_fps(self) -> float:
        return self._fps

    def set_fps(self, fps: float) -> None:
        self._fps = fps
        if self.is_connected and not self._simulate:
            logger.info(f"[Picamera2] Updating FPS to {fps}. Restarting camera...")
            self.disconnect()
            self.connect()

    @property
    def is_connected(self) -> bool:
        if self._simulate:
            return self._picamera2 is not None
        return self._picamera2 is not None
