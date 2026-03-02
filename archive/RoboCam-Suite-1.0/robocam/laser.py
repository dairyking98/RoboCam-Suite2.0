"""
Laser Control Module

Controls GPIO-connected laser module for experiment stimulation.
Requires Raspberry Pi GPIO hardware.

Author: RoboCam-Suite
"""

import RPi.GPIO as GPIO
from typing import Optional
from .config import get_config, Config
from .logging_config import get_logger

logger = get_logger(__name__)


class Laser:
    """
    GPIO-controlled laser module for experiment stimulation.
    
    Controls a laser connected to a GPIO pin. Default pin is GPIO 21.
    Blue wire is ground, green wire is live.
    
    Attributes:
        laser_pin (int): GPIO pin number for laser control
        ON: Constant for laser ON state (GPIO.HIGH)
        OFF: Constant for laser OFF state (GPIO.LOW)
    """
    
    ON = GPIO.HIGH
    OFF = GPIO.LOW

    def __init__(self, laser_pin: Optional[int] = None, config: Optional[Config] = None) -> None:
        """
        Initialize laser control on specified GPIO pin.
        
        Args:
            laser_pin: GPIO pin number (BCM numbering). If None, uses config default.
            config: Configuration object. If None, uses global config.
            
        Raises:
            RuntimeError: If GPIO initialization fails
            ValueError: If GPIO pin is invalid
            
        Note:
            Sets up GPIO pin as output and initializes laser to OFF state.
            Uses BCM pin numbering mode.
        """
        # Load configuration
        self.config: Config = config if config else get_config()
        laser_config = self.config.get_laser_config()
        
        # Laser settings
        self.laser_pin: int = laser_pin if laser_pin is not None else laser_config.get("gpio_pin", 21)
        
        # Validate GPIO pin
        if not (0 <= self.laser_pin <= 27):
            raise ValueError(f"Invalid GPIO pin: {self.laser_pin} (must be 0-27)")
        
        try:
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self.laser_pin, GPIO.OUT)
            default_state = laser_config.get("default_state", "OFF")
            initial_state = self.OFF if default_state.upper() == "OFF" else self.ON
            GPIO.output(self.laser_pin, initial_state)
        except Exception as e:
            raise RuntimeError(f"Failed to initialize laser on GPIO {self.laser_pin}: {e}") from e
        
    def switch(self, state: Optional[int] = None) -> None:
        """
        Turn laser ON or OFF.
        
        Args:
            state: Laser.ON or Laser.OFF, or GPIO.HIGH/GPIO.LOW
            
        Raises:
            RuntimeError: If GPIO operation fails
            ValueError: If state is invalid
            
        Note:
            Blue wire is ground, green wire is live.
        """
        if state is None:
            raise ValueError("Laser state must be specified (Laser.ON or Laser.OFF)")
        
        if state not in (self.ON, self.OFF, GPIO.HIGH, GPIO.LOW):
            raise ValueError(f"Invalid laser state: {state}")
        
        try:
            GPIO.output(self.laser_pin, state)
            state_name = "ON" if state in (self.ON, GPIO.HIGH) else "OFF"
            logger.info(f'Laser switched to {state_name}')
        except Exception as e:
            logger.error(f"Failed to switch laser: {e}")
            raise RuntimeError(f"Failed to switch laser: {e}") from e
