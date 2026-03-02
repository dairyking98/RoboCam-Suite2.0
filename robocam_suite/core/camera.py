from abc import ABC, abstractmethod
from typing import Optional, Tuple, Any
import numpy as np

class Camera(ABC):
    """Abstract base class for all camera implementations."""

    @abstractmethod
    def connect(self) -> None:
        """Connect to the camera device."""
        pass

    @abstractmethod
    def disconnect(self) -> None:
        """Disconnect from the camera device."""
        pass

    @abstractmethod
    def start_capture(self) -> None:
        """Begin the capture stream."""
        pass

    @abstractmethod
    def stop_capture(self) -> None:
        """Stop the capture stream."""
        pass

    @abstractmethod
    def read_frame(self) -> Optional[np.ndarray]:
        """Read a single frame from the camera.

        Returns:
            A numpy array representing the image frame, or None if a frame
            could not be read.
        """
        pass

    @abstractmethod
    def get_resolution(self) -> Tuple[int, int]:
        """Get the current camera resolution (width, height)."""
        pass

    @abstractmethod
    def set_resolution(self, resolution: Tuple[int, int]) -> None:
        """Set the camera resolution."""
        pass

    @abstractmethod
    def get_fps(self) -> float:
        """Get the current frames per second setting."""
        pass

    @abstractmethod
    def set_fps(self, fps: float) -> None:
        """Set the frames per second."""
        pass

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Return True if the camera is connected."""
        pass
