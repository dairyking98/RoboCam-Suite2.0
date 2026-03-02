from robocam_suite.core.gpio_controller import GPIOController
from robocam_suite.logger import setup_logger

logger = setup_logger()

class NullGPIOController(GPIOController):
    """
    A no-op GPIO controller used when no GPIO device is present.

    All commands are silently accepted and logged at DEBUG level.
    This allows the rest of the application to function normally
    without any GPIO hardware connected.
    """

    def connect(self) -> None:
        logger.debug("NullGPIOController: connect() called — no GPIO hardware in use.")

    def disconnect(self) -> None:
        logger.debug("NullGPIOController: disconnect() called — no GPIO hardware in use.")

    def set_pin_mode(self, pin: int, mode: str) -> None:
        logger.debug(f"NullGPIOController: set_pin_mode(pin={pin}, mode={mode}) — ignored.")

    def write_pin(self, pin: int, value: bool) -> None:
        logger.debug(f"NullGPIOController: write_pin(pin={pin}, value={value}) — ignored.")

    def read_pin(self, pin: int) -> bool:
        logger.debug(f"NullGPIOController: read_pin(pin={pin}) — returning False.")
        return False

    @property
    def is_connected(self) -> bool:
        return True  # Always report as "connected" so callers never block
