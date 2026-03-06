try:
    from picamera2 import Picamera2
except ImportError:
    Picamera2 = None

import numpy as np
from typing import Optional, Tuple
import logging

from robocam_suite.core.camera import Camera
from robocam_suite.logger import setup_logger

logger = setup_logger()

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

        if Picamera2 is None:
            raise ImportError("Picamera2 library not found. Ensure you are on a Raspberry Pi with libcamera installed.")

        try:
            # We pass a camera index if available, default to 0. 
            # Some Pi boards have multiple camera ports.
            cam_idx = self._config.get("camera_index", 0)
            self._picamera2 = Picamera2(camera_num=cam_idx)
            
            # Use default video configuration as a starting point
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
        # Picamera2 is started during connect() in this implementation
        pass

    def stop_capture(self) -> None:
        # Picamera2 is stopped during disconnect()
        pass

    def read_frame(self) -> Optional[np.ndarray]:
        if self._simulate:
            return np.zeros((self._resolution[1], self._resolution[0], 3), dtype=np.uint8)

        if not self.is_connected or not self._is_running:
            return None

        try:
            # capture_array() returns a numpy array from the 'main' stream
            return self._picamera2.capture_array()
        except Exception as e:
            logger.error(f"[Picamera2] Failed to read frame: {e}")
            return None

    def get_resolution(self) -> Tuple[int, int]:
        return self._resolution

    def set_resolution(self, resolution: Tuple[int, int]) -> None:
        self._resolution = resolution
        if self.is_connected and not self._simulate:
            # Picamera2 requires a restart to change resolution
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
