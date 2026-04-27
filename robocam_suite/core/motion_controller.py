from abc import ABC, abstractmethod
from typing import Optional, Tuple

class MotionController(ABC):
    """Abstract base class for all motion controller implementations."""

    @abstractmethod
    def connect(self) -> None:
        """Connect to the motion control hardware."""
        pass

    @abstractmethod
    def disconnect(self) -> None:
        """Disconnect from the motion control hardware."""
        pass

    @abstractmethod
    def home(self) -> None:
        """Home all axes of the motion controller."""
        pass

    @abstractmethod
    def move_absolute(self, x: Optional[float] = None, y: Optional[float] = None, z: Optional[float] = None, speed: Optional[float] = None) -> None:
        """Move to an absolute position."""
        pass

    @abstractmethod
    def move_relative(self, x: Optional[float] = None, y: Optional[float] = None, z: Optional[float] = None, speed: Optional[float] = None) -> None:
        """Move to a position relative to the current one."""
        pass

    @abstractmethod
    def get_current_position(self) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        """Get the current (X, Y, Z) position."""
        pass

    def send_raw(self, command: str) -> str:
        """
        Send a raw G-code command string and return the response.

        Provides an escape hatch for commands not covered by the
        higher-level interface (e.g. M18 to disable steppers, M503
        to read EEPROM settings).  The default implementation is a
        no-op so subclasses are not forced to override it.
        """
        return ""

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Return True if the motion controller is connected."""
        pass

    @abstractmethod
    def is_homed(self) -> bool:
        """Return True if the motion controller has been homed."""
        pass
