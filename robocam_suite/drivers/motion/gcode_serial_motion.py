"""
GCodeSerialMotionController — communicates with a 3-D printer over serial.

In simulation mode (``simulate=True``) all serial I/O is replaced by a
:class:`~robocam_suite.drivers.motion.simulated_printer.SimulatedPrinter`
instance that maintains full XYZ state and returns realistic Marlin-style
responses.  This means ``get_current_position()`` returns real tracked
coordinates, ``G28`` resets them to zero, and ``M18`` is acknowledged
correctly — exactly as a physical printer would behave.
"""
import serial
import serial.tools.list_ports
import time
import re
from typing import Optional, Tuple

from robocam_suite.core.motion_controller import MotionController
from robocam_suite.logger import setup_logger

logger = setup_logger()


class GCodeSerialMotionController(MotionController):
    """Motion controller that communicates with a 3-D printer via G-code over serial."""

    def __init__(self, config: Optional[dict] = None, simulate: bool = False):
        self._config = config or {}
        self._simulate = simulate
        self._serial_port: Optional[serial.Serial] = None
        self._position: Tuple[float, float, float] = (0.0, 0.0, 0.0)

        # In simulate mode, create a stateful virtual printer
        self._sim_printer = None
        if self._simulate:
            from robocam_suite.drivers.motion.simulated_printer import SimulatedPrinter
            self._sim_printer = SimulatedPrinter(
                travel_speed_mm_s=self._config.get("simulate_travel_speed_mm_s", 100.0),
                home_delay_s=self._config.get("simulate_home_delay_s", 1.0),
            )
            logger.info("[MotionCtrl] Running in SIMULATION MODE — using SimulatedPrinter.")

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self) -> None:
        if self._simulate:
            # Nothing to open — the SimulatedPrinter is always "connected"
            logger.info("[MotionCtrl] Simulated printer connected.")
            return

        if self.is_connected:
            return

        port_name = self._resolve_port()
        if not port_name:
            raise ConnectionError(
                "Could not find a serial port for the motion controller. "
                "Check that the printer is plugged in and that the correct port "
                "is set in the config (motion_controller.port)."
            )

        try:
            self._serial_port = serial.Serial(
                port=port_name,
                baudrate=self._config.get("baudrate", 115200),
                timeout=self._config.get("timeout", 1.0),
            )
            # Allow the printer's bootloader to finish initialising
            time.sleep(2)
            self._serial_port.reset_input_buffer()
            logger.info(f"[MotionCtrl] Connected to printer on {port_name}.")
        except serial.SerialException as e:
            raise ConnectionError(
                f"Failed to connect to motion controller on {port_name}: {e}"
            ) from e

    def disconnect(self) -> None:
        if self._simulate:
            logger.info("[MotionCtrl] Simulated printer disconnected.")
            return

        if self._serial_port and self._serial_port.is_open:
            self._serial_port.close()
            self._serial_port = None
            logger.info("[MotionCtrl] Disconnected from printer.")

    # ------------------------------------------------------------------
    # Motion commands
    # ------------------------------------------------------------------

    def home(self) -> None:
        self._send_gcode("G28", timeout=self._config.get("home_timeout", 90.0))
        self._wait_for_movement_to_finish()
        self._sync_position()

    def move_absolute(
        self,
        x: Optional[float] = None,
        y: Optional[float] = None,
        z: Optional[float] = None,
        speed: Optional[float] = None,
    ) -> None:
        self._send_gcode("G90")
        self._move(x, y, z, speed)

    def move_relative(
        self,
        x: Optional[float] = None,
        y: Optional[float] = None,
        z: Optional[float] = None,
        speed: Optional[float] = None,
    ) -> None:
        self._send_gcode("G91")
        self._move(x, y, z, speed)

    def get_current_position(self) -> Tuple[float, float, float]:
        """
        Query the printer for its current position via M114 and return
        (X, Y, Z) as floats.

        In simulation mode the position is read directly from the
        SimulatedPrinter's state, which is updated by every move command.
        """
        if self._simulate:
            self._position = self._sim_printer.position
            return self._position

        response = self._send_gcode("M114", read_response=True)
        match = re.search(r"X:([\d.]+)\s+Y:([\d.]+)\s+Z:([\d.]+)", response)
        if match:
            self._position = (
                float(match.group(1)),
                float(match.group(2)),
                float(match.group(3)),
            )
        return self._position

    def send_raw(self, command: str) -> str:
        """
        Send a raw G-code command and return the full response string.

        Examples::

            mc.send_raw("M18")   # Disable all stepper motors
            mc.send_raw("M503")  # Report EEPROM settings
            mc.send_raw("M119")  # Report endstop states
        """
        return self._send_gcode(command.strip(), read_response=True)

    # ------------------------------------------------------------------
    # Connection status
    # ------------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        if self._simulate:
            return self._sim_printer is not None
        return self._serial_port is not None and self._serial_port.is_open

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_port(self) -> Optional[str]:
        """Return the configured port, or auto-detect if set to 'auto'."""
        port = self._config.get("port", "auto")
        if port and port.lower() != "auto":
            return port
        # Auto-detect: look for common USB-serial chips used by printers
        for p in serial.tools.list_ports.comports():
            desc = (p.description or "").upper()
            if any(kw in desc for kw in ("USB", "CH340", "CH341", "ARDUINO", "MARLIN", "FTDI")):
                logger.info(f"[MotionCtrl] Auto-detected printer port: {p.device}")
                return p.device
        return None

    def _send_gcode(
        self,
        command: str,
        timeout: Optional[float] = None,
        read_response: bool = False,
    ) -> str:
        """
        Send one G-code command and collect the response.

        In simulate mode the command is forwarded to SimulatedPrinter.
        On real hardware it is written to the serial port and the
        response is read until an "ok" or "error" line is received.
        """
        if self._simulate:
            response = self._sim_printer.send(command)
            logger.debug(f"[SimPrinter ←] {command!r}  →  {response!r}")
            return response

        if not self.is_connected:
            raise ConnectionError("Motion controller is not connected.")

        self._serial_port.write((command + "\n").encode("utf-8"))

        start = time.time()
        lines: list[str] = []
        while True:
            raw = self._serial_port.readline()
            if not raw:
                if timeout and (time.time() - start) > timeout:
                    raise TimeoutError(
                        f"Timeout waiting for 'ok' from printer after {command!r}."
                    )
                continue
            line = raw.decode("utf-8", errors="replace").strip()
            if line:
                lines.append(line)
                if line.lower().startswith("ok"):
                    break
                if line.lower().startswith("error"):
                    raise RuntimeError(f"Printer error: {line}")
            if timeout and (time.time() - start) > timeout:
                raise TimeoutError(
                    f"Timeout waiting for 'ok' from printer after {command!r}."
                )

        return "\n".join(lines)

    def _move(
        self,
        x: Optional[float],
        y: Optional[float],
        z: Optional[float],
        speed: Optional[float],
    ) -> None:
        parts = ["G0"]
        if x is not None:
            parts.append(f"X{x:.4f}")
        if y is not None:
            parts.append(f"Y{y:.4f}")
        if z is not None:
            parts.append(f"Z{z:.4f}")
        if speed is not None:
            parts.append(f"F{speed:.1f}")
        self._send_gcode(" ".join(parts))
        self._wait_for_movement_to_finish()
        self._sync_position()

    def _wait_for_movement_to_finish(self) -> None:
        """Send M400 to block until all queued moves are complete."""
        self._send_gcode(
            "M400",
            timeout=self._config.get("movement_wait_timeout", 30.0),
        )

    def _sync_position(self) -> None:
        """Update the cached position from the printer."""
        self.get_current_position()
