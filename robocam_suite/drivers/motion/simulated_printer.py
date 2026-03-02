"""
SimulatedPrinter — a stateful G-code interpreter for simulation mode.

Processes a realistic subset of Marlin-compatible G-code and returns
responses that match what a real printer would send over serial.

Supported commands
------------------
G0 / G1   — linear move (updates internal position, respects G90/G91)
G28       — home all axes (resets position to 0, 0, 0)
G90       — set absolute positioning mode
G91       — set relative positioning mode
M18 / M84 — disable steppers (acknowledged, no state change needed)
M114      — report current position in Marlin format
M400      — wait for moves to finish (instant in simulation)
M503      — report settings (returns a stub response)
M105      — report temperatures (returns stub temps)
*         — any other command returns "ok"

All commands return a string ending with "ok" to satisfy the serial
read loop in GCodeSerialMotionController.
"""
from __future__ import annotations

import re
import time

from robocam_suite.logger import setup_logger

logger = setup_logger()


class SimulatedPrinter:
    """
    A software model of a Marlin 3-D printer that processes G-code
    commands and maintains XYZ position state.

    Parameters
    ----------
    travel_speed_mm_s : float
        Simulated travel speed used to calculate realistic move delays.
        Defaults to 100 mm/s (6000 mm/min, a typical fast jog speed).
    home_delay_s : float
        Simulated delay for a G28 home sequence.
    """

    def __init__(
        self,
        travel_speed_mm_s: float = 100.0,
        home_delay_s: float = 2.0,
    ):
        self._x: float = 0.0
        self._y: float = 0.0
        self._z: float = 0.0
        self._absolute: bool = True          # G90 = absolute, G91 = relative
        self._steppers_enabled: bool = True
        self._travel_speed_mm_s = travel_speed_mm_s
        self._home_delay_s = home_delay_s
        logger.info("[SimPrinter] Simulated printer ready.")

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def send(self, command: str) -> str:
        """
        Process a single G-code command string and return the printer
        response as a string (always ends with a line containing "ok").

        Parameters
        ----------
        command : str
            Raw G-code command, e.g. ``"G0 X10 Y20"`` or ``"M114"``.

        Returns
        -------
        str
            Multi-line response string as a real Marlin printer would
            produce.  The final line is always ``"ok"``.
        """
        cmd = command.strip().upper()
        # Strip inline comments (semicolons)
        cmd = re.sub(r";.*$", "", cmd).strip()
        if not cmd:
            return "ok"

        # Dispatch on the primary word
        primary = cmd.split()[0]

        if primary in ("G0", "G1"):
            return self._handle_move(cmd)
        elif primary == "G28":
            return self._handle_home(cmd)
        elif primary == "G90":
            self._absolute = True
            logger.debug("[SimPrinter] Absolute positioning mode.")
            return "ok"
        elif primary == "G91":
            self._absolute = False
            logger.debug("[SimPrinter] Relative positioning mode.")
            return "ok"
        elif primary in ("M18", "M84"):
            self._steppers_enabled = False
            logger.info("[SimPrinter] Steppers disabled.")
            return "ok"
        elif primary == "M17":
            self._steppers_enabled = True
            logger.info("[SimPrinter] Steppers enabled.")
            return "ok"
        elif primary == "M114":
            return self._handle_m114()
        elif primary == "M400":
            # All moves are synchronous in simulation — nothing to wait for
            return "ok"
        elif primary == "M105":
            return "T:20.0 /0.0 B:20.0 /0.0 T0:20.0 /0.0 @:0 B@:0\nok"
        elif primary == "M503":
            return (
                "echo:  G21 ; Units in mm (mm)\n"
                "echo:  M149 C ; Units in Celsius\n"
                "echo:  M200 S0\n"
                "echo:  M92 X80.00 Y80.00 Z400.00 E93.00\n"
                "ok"
            )
        else:
            logger.debug(f"[SimPrinter] Unhandled command (returning ok): {cmd!r}")
            return "ok"

    @property
    def position(self) -> tuple[float, float, float]:
        """Current (X, Y, Z) position in mm."""
        return (self._x, self._y, self._z)

    # ------------------------------------------------------------------
    # Command handlers
    # ------------------------------------------------------------------

    def _handle_move(self, cmd: str) -> str:
        """Parse G0/G1 and update position, optionally with a delay."""
        x = self._parse_axis(cmd, "X")
        y = self._parse_axis(cmd, "Y")
        z = self._parse_axis(cmd, "Z")
        f = self._parse_axis(cmd, "F")  # feed rate in mm/min

        # Calculate distance for realistic delay
        dx = (x if x is not None else 0.0) if not self._absolute else (
            (x - self._x) if x is not None else 0.0
        )
        dy = (y if y is not None else 0.0) if not self._absolute else (
            (y - self._y) if y is not None else 0.0
        )
        dz = (z if z is not None else 0.0) if not self._absolute else (
            (z - self._z) if z is not None else 0.0
        )
        distance = (dx**2 + dy**2 + dz**2) ** 0.5

        # Update position
        if self._absolute:
            if x is not None:
                self._x = x
            if y is not None:
                self._y = y
            if z is not None:
                self._z = z
        else:
            if x is not None:
                self._x += x
            if y is not None:
                self._y += y
            if z is not None:
                self._z += z

        # Simulate travel time (capped at 5 s to keep UI responsive)
        speed_mm_s = (f / 60.0) if f else self._travel_speed_mm_s
        if speed_mm_s > 0 and distance > 0:
            delay = min(distance / speed_mm_s, 5.0)
            time.sleep(delay)

        logger.debug(
            f"[SimPrinter] Move → X:{self._x:.3f} Y:{self._y:.3f} Z:{self._z:.3f}"
        )
        return "ok"

    def _handle_home(self, cmd: str) -> str:
        """G28 — home all (or specified) axes."""
        # Simulate homing delay
        time.sleep(self._home_delay_s)
        axes = cmd.split()[1:]  # e.g. ["X", "Y"] or [] for all
        if not axes or "X" in axes:
            self._x = 0.0
        if not axes or "Y" in axes:
            self._y = 0.0
        if not axes or "Z" in axes:
            self._z = 0.0
        logger.info(f"[SimPrinter] Homed → X:{self._x} Y:{self._y} Z:{self._z}")
        return "ok"

    def _handle_m114(self) -> str:
        """
        M114 — report current position.

        Marlin format::

            X:10.00 Y:20.00 Z:5.00 E:0.00 Count X:800 Y:1600 Z:2000
            ok
        """
        response = (
            f"X:{self._x:.2f} Y:{self._y:.2f} Z:{self._z:.2f} E:0.00 "
            f"Count X:{int(self._x * 80)} Y:{int(self._y * 80)} Z:{int(self._z * 400)}\n"
            "ok"
        )
        logger.debug(f"[SimPrinter] M114 → {response.splitlines()[0]}")
        return response

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_axis(cmd: str, axis: str) -> float | None:
        """Extract the float value for a given axis letter from a G-code string."""
        match = re.search(rf"{axis}(-?[\d.]+)", cmd)
        return float(match.group(1)) if match else None
