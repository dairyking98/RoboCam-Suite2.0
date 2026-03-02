import serial
import serial.tools.list_ports
import time
from typing import Optional

from robocam_suite.core.gpio_controller import GPIOController

class ArduinoSerialGPIOController(GPIOController):
    """GPIO controller that sends commands to an Arduino over serial."""

    def __init__(self, config: Optional[dict] = None, simulate: bool = False):
        self._config = config or {}
        self._simulate = simulate
        self._serial_port: Optional[serial.Serial] = None

        if self._simulate:
            print("ArduinoSerialGPIOController running in SIMULATION MODE")

    def connect(self) -> None:
        if self._simulate:
            self._serial_port = True  # Simulate connection
            return

        if self.is_connected:
            return

        port_name = self._find_serial_port()
        if not port_name:
            raise ConnectionError("Could not find a serial port for the GPIO controller.")

        try:
            self._serial_port = serial.Serial(
                port=port_name,
                baudrate=self._config.get("baudrate", 9600),
                timeout=self._config.get("timeout", 1.0)
            )
            time.sleep(2) # Wait for Arduino to reset
            print(f"Connected to GPIO controller on {port_name}")
        except serial.SerialException as e:
            raise ConnectionError(f"Failed to connect to GPIO controller on {port_name}: {e}") from e

    def disconnect(self) -> None:
        if self._simulate:
            self._serial_port = None
            return

        if self._serial_port:
            self._serial_port.close()
            self._serial_port = None
            print("Disconnected from GPIO controller.")

    def set_pin_mode(self, pin: int, mode: str) -> None:
        # This would be implemented in the Arduino sketch
        pass

    def write_pin(self, pin: int, value: bool) -> None:
        command = f"{pin},{1 if value else 0}\n"
        self._send_command(command)

    def read_pin(self, pin: int) -> bool:
        # This would require a more complex serial protocol
        raise NotImplementedError("Reading pins is not yet implemented.")

    @property
    def is_connected(self) -> bool:
        if self._simulate:
            return self._serial_port is not None
        return self._serial_port is not None and self._serial_port.is_open

    def _find_serial_port(self) -> Optional[str]:
        ports = serial.tools.list_ports.comports()
        for port in ports:
            if "Arduino" in port.description or "CH340" in port.description:
                return port.device
        return None

    def _send_command(self, command: str):
        if self._simulate:
            print(f"[SIM] Sending GPIO command: {command.strip()}")
            return

        if not self.is_connected:
            raise ConnectionError("GPIO controller is not connected.")

        self._serial_port.write(command.encode('utf-8'))
        # Simple fire-and-forget protocol for now
