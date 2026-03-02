import serial
import serial.tools.list_ports
import time
import re
from typing import Optional, Tuple

from robocam_suite.core.motion_controller import MotionController

class GCodeSerialMotionController(MotionController):
    """Motion controller that communicates with a 3D printer via G-code over serial."""

    def __init__(self, config: Optional[dict] = None, simulate: bool = False):
        self._config = config or {}
        self._simulate = simulate
        self._serial_port: Optional[serial.Serial] = None
        self._position = (0.0, 0.0, 0.0)

        if self._simulate:
            print("GCodeSerialMotionController running in SIMULATION MODE")

    def connect(self) -> None:
        if self._simulate:
            self._serial_port = True  # Simulate connection
            return

        if self.is_connected:
            return

        port_name = self._find_serial_port()
        if not port_name:
            raise ConnectionError("Could not find a serial port for the motion controller.")

        try:
            self._serial_port = serial.Serial(
                port=port_name,
                baudrate=self._config.get("baudrate", 115200),
                timeout=self._config.get("timeout", 1.0)
            )
            # Wait for the printer to initialize
            time.sleep(2)
            self._serial_port.flushInput()
            print(f"Connected to motion controller on {port_name}")
        except serial.SerialException as e:
            raise ConnectionError(f"Failed to connect to motion controller on {port_name}: {e}") from e

    def disconnect(self) -> None:
        if self._simulate:
            self._serial_port = None
            return

        if self._serial_port:
            self._serial_port.close()
            self._serial_port = None
            print("Disconnected from motion controller.")

    def home(self) -> None:
        self._send_gcode("G28", timeout=self._config.get("home_timeout", 90.0))
        self._wait_for_movement_to_finish()
        self.get_current_position() # Update position after homing

    def move_absolute(self, x: Optional[float] = None, y: Optional[float] = None, z: Optional[float] = None, speed: Optional[float] = None) -> None:
        self._send_gcode("G90") # Set to absolute positioning
        self._move(x, y, z, speed)

    def move_relative(self, x: Optional[float] = None, y: Optional[float] = None, z: Optional[float] = None, speed: Optional[float] = None) -> None:
        self._send_gcode("G91") # Set to relative positioning
        self._move(x, y, z, speed)

    def get_current_position(self) -> Tuple[float, float, float]:
        if self._simulate:
            return self._position

        response = self._send_gcode("M114", read_response=True)
        match = re.search(r"X:([\d\.]+) Y:([\d\.]+) Z:([\d\.]+)", response)
        if match:
            self._position = (float(match.group(1)), float(match.group(2)), float(match.group(3)))
        return self._position

    @property
    def is_connected(self) -> bool:
        if self._simulate:
            return self._serial_port is not None
        return self._serial_port is not None and self._serial_port.is_open

    def _find_serial_port(self) -> Optional[str]:
        ports = serial.tools.list_ports.comports()
        for port in ports:
            # This logic might need to be more specific for different printer boards
            if "USB" in port.description or "CH340" in port.description or "Arduino" in port.description:
                return port.device
        return None

    def _send_gcode(self, command: str, timeout: Optional[float] = None, read_response: bool = False) -> str:
        if self._simulate:
            print(f"[SIM] Sending G-code: {command}")
            return "ok"

        if not self.is_connected:
            raise ConnectionError("Motion controller is not connected.")

        self._serial_port.write((command + '\n').encode('utf-8'))
        
        start_time = time.time()
        response_lines = []
        while True:
            line = self._serial_port.readline().decode('utf-8').strip()
            if line:
                response_lines.append(line)
                if line.startswith('ok'):
                    break
                if line.startswith('error'):
                    raise RuntimeError(f"Printer returned an error: {line}")
            if timeout and (time.time() - start_time) > timeout:
                raise TimeoutError(f"Timeout waiting for 'ok' from printer after sending '{command}'.")
        
        return "\n".join(response_lines)

    def _move(self, x: Optional[float], y: Optional[float], z: Optional[float], speed: Optional[float]) -> None:
        command = "G0"
        if x is not None:
            command += f" X{x}"
        if y is not None:
            command += f" Y{y}"
        if z is not None:
            command += f" Z{z}"
        if speed is not None:
            command += f" F{speed}"
        
        self._send_gcode(command)
        self._wait_for_movement_to_finish()
        self.get_current_position()

    def _wait_for_movement_to_finish(self):
        self._send_gcode("M400", timeout=self._config.get("movement_wait_timeout", 30.0))
