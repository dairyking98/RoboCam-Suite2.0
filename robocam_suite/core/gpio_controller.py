from abc import ABC, abstractmethod

class GPIOController(ABC):
    """Abstract base class for all GPIO controller implementations."""

    @abstractmethod
    def connect(self) -> None:
        """Connect to the GPIO hardware."""
        pass

    @abstractmethod
    def disconnect(self) -> None:
        """Disconnect from the GPIO hardware."""
        pass

    @abstractmethod
    def set_pin_mode(self, pin: int, mode: str) -> None:
        """Set the mode for a specific GPIO pin (e.g., 'output', 'input')."""
        pass

    @abstractmethod
    def write_pin(self, pin: int, value: bool) -> None:
        """Write a digital value (True for HIGH, False for LOW) to a GPIO pin."""
        pass

    @abstractmethod
    def read_pin(self, pin: int) -> bool:
        """Read the digital value of a GPIO pin."""
        pass

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Return True if the GPIO controller is connected."""
        pass
