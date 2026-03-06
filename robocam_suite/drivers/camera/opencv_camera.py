import cv2
import numpy as np
from typing import Optional, Tuple

from robocam_suite.core.camera import Camera

class OpenCVCamera(Camera):
    """A camera implementation using OpenCV's VideoCapture."""

    def __init__(self, config: Optional[dict] = None, simulate: bool = False):
        self._config = config or {}
        self._simulate = simulate
        self._camera_index = self._config.get("camera_index", 0)
        self._capture: Optional[cv2.VideoCapture] = None
        self._resolution = (640, 480)
        self._fps = 30.0

        if self._simulate:
            print("OpenCVCamera running in SIMULATION MODE")

    def connect(self) -> None:
        if self._simulate:
            self._capture = True # Simulate connection
            return

        if self.is_connected:
            return

        self._capture = cv2.VideoCapture(self._camera_index)
        if not self._capture.isOpened():
            self._capture = None
            raise ConnectionError(f"Could not open camera at index {self._camera_index}")
        
        self.set_resolution(self._config.get("resolution", self._resolution))
        self.set_fps(self._config.get("fps", self._fps))
        print(f"Connected to OpenCV camera at index {self._camera_index}")

    def disconnect(self) -> None:
        if self._simulate:
            self._capture = None
            return

        if self._capture:
            self._capture.release()
            self._capture = None
            print("Disconnected from OpenCV camera.")

    def start_capture(self) -> None:
        # VideoCapture starts capturing on creation, so this is a no-op
        pass

    def stop_capture(self) -> None:
        # VideoCapture stops on release, handled in disconnect
        pass

    def read_frame(self) -> Optional[np.ndarray]:
        if self._simulate:
            return np.zeros((self._resolution[1], self._resolution[0], 3), dtype=np.uint8)

        if not self.is_connected:
            return None

        ret, frame = self._capture.read()
        if not ret:
            return None
        return frame

    def get_resolution(self) -> Tuple[int, int]:
        if self._simulate:
            return self._resolution
        
        if not self.is_connected:
            return (0,0)

        width = int(self._capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(self._capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        return (width, height)

    def set_resolution(self, resolution: Tuple[int, int]) -> None:
        self._resolution = resolution
        if self.is_connected and not self._simulate:
            self._capture.set(cv2.CAP_PROP_FRAME_WIDTH, resolution[0])
            self._capture.set(cv2.CAP_PROP_FRAME_HEIGHT, resolution[1])

    def get_fps(self) -> float:
        if self._simulate:
            return self._fps

        if not self.is_connected:
            return 0.0

        return self._capture.get(cv2.CAP_PROP_FPS)

    def set_fps(self, fps: float) -> None:
        self._fps = fps
        if self.is_connected and not self._simulate:
            self._capture.set(cv2.CAP_PROP_FPS, fps)

    def get_supported_resolutions(self) -> list[Tuple[int, int]]:
        """Return common standard resolutions for OpenCV cameras."""
        return [
            (640, 480),
            (800, 600),
            (1024, 768),
            (1280, 720),
            (1280, 960),
            (1920, 1080)
        ]

    @property
    def is_connected(self) -> bool:
        if self._simulate:
            return self._capture is not None
        return self._capture is not None and self._capture.isOpened()
