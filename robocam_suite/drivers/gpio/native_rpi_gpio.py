import logging
from typing import Optional

try:
    import RPi.GPIO as GPIO
except ImportError:
    GPIO = None

from robocam_suite.core.gpio_controller import GPIOController

logger = logging.getLogger(__name__)

class NativeRPiGPIOController(GPIOController):
    """GPIO controller that uses the built-in RPi.GPIO library."""

    def __init__(self, config: Optional[dict] = None, simulate: bool = False):
        self._config = config or {}
        self._simulate = simulate
        self._connected = False
        
        if GPIO is None and not self._simulate:
            logger.warning("RPi.GPIO library not found. NativeRPiGPIOController will fail.")

    def connect(self) -> None:
        if self._simulate:
            self._connected = True
            logger.info("[GPIO] Native RPi GPIO connected (SIMULATION)")
            return

        if GPIO is None:
            raise RuntimeError("RPi.GPIO library not found. Install it with 'sudo apt install python3-rpi.gpio'")

        try:
            # Use BCM pin numbering
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            self._connected = True
            logger.info("[GPIO] Native RPi GPIO connected (BCM mode)")
        except Exception as e:
            raise ConnectionError(f"Failed to initialize RPi GPIO: {e}")

    def disconnect(self) -> None:
        if self._connected:
            if not self._simulate and GPIO is not None:
                try:
                    GPIO.cleanup()
                except Exception:
                    pass
            self._connected = False
            logger.info("[GPIO] Native RPi GPIO disconnected")

    def set_pin_mode(self, pin: int, mode: str) -> None:
        if not self._connected:
            raise RuntimeError("GPIO not connected")
            
        if self._simulate:
            logger.debug(f"[GPIO] [SIM] Set pin {pin} mode to {mode}")
            return

        if mode.lower() == "output":
            GPIO.setup(pin, GPIO.OUT)
        elif mode.lower() == "input":
            GPIO.setup(pin, GPIO.IN)
        else:
            raise ValueError(f"Unsupported GPIO mode: {mode}")

    def write_pin(self, pin: int, value: bool) -> None:
        if not self._connected:
            raise RuntimeError("GPIO not connected")
            
        if self._simulate:
            logger.debug(f"[GPIO] [SIM] Write pin {pin} -> {value}")
            return

        # Ensure it's set as output first (idempotent in RPi.GPIO)
        GPIO.setup(pin, GPIO.OUT)
        GPIO.output(pin, GPIO.HIGH if value else GPIO.LOW)

    def read_pin(self, pin: int) -> bool:
        if not self._connected:
            raise RuntimeError("GPIO not connected")
            
        if self._simulate:
            return False

        GPIO.setup(pin, GPIO.IN)
        return bool(GPIO.input(pin))

    @property
    def is_connected(self) -> bool:
        return self._connected
