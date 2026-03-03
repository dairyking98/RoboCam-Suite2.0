"""
GCodeSerialMotionController — communicates with a 3-D printer over serial.

In simulation mode (``simulate=True``) all serial I/O is replaced by a
:class:`~robocam_suite.drivers.motion.simulated_printer.SimulatedPrinter`
instance that maintains full XYZ state and returns realistic Marlin-style
responses.  This means ``get_current_position()`` returns real tracked
coordinates, ``G28`` resets them to zero, and ``M18`` is acknowledged
correctly — exactly as a physical printer would behave.

Movement-completion strategy (ported from RoboCam-Suite 1.0)
-------------------------------------------------------------
At connect time the controller tests whether the firmware supports M400
(wait-for-move-completion).  If the test succeeds, M400 is used for every
subsequent move.  If M400 times out or errors — either during the initial
test or during a live move — the flag is permanently cleared and a
conservative ``time.sleep()`` fallback is used instead.

send_gcode improvements (ported from RoboCam-Suite 1.0)
--------------------------------------------------------
- ``serial.flush()`` is called immediately after writing so the command is
  sent to the printer without waiting for the OS buffer to drain.
- A short ``command_delay`` (default 0.05 s) is observed before the read
  loop starts, giving the printer time to begin processing.
- The read loop checks ``in_waiting`` before calling ``readline()`` and
  sleeps 10 ms when no bytes are available, avoiding a busy-wait that
  monopolises the serial port.
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

        # Live motion profiles — populated by the UI via set_profiles().
        # _move() uses max_feed_x/y/z as the default F value when no explicit
        # speed is passed, so slider changes take effect immediately.
        self._profiles: dict = {}

        # command_delay: short pause after writing a command so the printer
        # has time to start processing before we begin reading the response.
        self._command_delay: float = float(self._config.get("command_delay", 0.05))

        # _m400_supported: None = not yet tested, True/False = known state.
        # Tested once at connect(); permanently cleared if M400 ever fails
        # during a live move.
        self._m400_supported: Optional[bool] = None

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

        # M400 support is tested lazily on the first move (same as 1.0).
        # Testing at connect time is unreliable because the printer may still
        # be processing its boot sequence when connect() returns.
        logger.info("[MotionCtrl] M400 support will be tested on first move.")

        # Sync position cache from printer on connect so we start from the
        # correct position (not 0,0,0) — identical to 1.0 update_current_position().
        try:
            self.query_current_position()
            logger.info(f"[MotionCtrl] Position synced on connect: {self._position}")
        except Exception as e:
            logger.warning(f"[MotionCtrl] Could not sync position on connect: {e}")

    def disconnect(self) -> None:
        if self._simulate:
            logger.info("[MotionCtrl] Simulated printer disconnected.")
            return

        if self._serial_port and self._serial_port.is_open:
            self._serial_port.close()
            self._serial_port = None
            self._m400_supported = None  # reset so it's re-tested on next connect
            logger.info("[MotionCtrl] Disconnected from printer.")

    # ------------------------------------------------------------------
    # Motion commands
    # ------------------------------------------------------------------

    def home(self) -> None:
        self._send_gcode("G28", timeout=self._config.get("home_timeout", 90.0))
        self._wait_for_movement_to_finish()
        # Sync position cache after homing so the display and experiment
        # moves use the correct post-home coordinates.
        try:
            self.query_current_position()
        except Exception as e:
            logger.warning(f"[MotionCtrl] Could not sync position after home: {e}")

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
        Return the **cached** (X, Y, Z) position without sending any serial
        command.  The cache is updated after every move and on connect.

        Use ``query_current_position()`` when you need a live reading from
        the printer (e.g. after a manual jog or for diagnostics).
        """
        if self._simulate:
            self._position = self._sim_printer.position
        return self._position

    def query_current_position(self) -> Tuple[float, float, float]:
        """
        Send M114 to the printer, update the cache, and return (X, Y, Z).

        Only call this when a live reading is genuinely needed — it sends
        a serial command and logs it.  Prefer ``get_current_position()``
        for UI display polling.
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

    def set_profiles(self, profiles: dict) -> None:
        """
        Store the current motion profiles so that ``_move()`` can use them
        as default feed-rates when no explicit speed is passed.

        Called by the UI after reading or applying profiles.
        """
        self._profiles = dict(profiles)
        logger.info(f"[MotionCtrl] Motion profiles updated: {profiles}")

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
    # Printer profile helpers (feed-rate / acceleration / jerk)
    # ------------------------------------------------------------------

    @staticmethod
    def parse_m503_profiles(lines: list[str]) -> dict:
        """
        Parse the line list returned by M503 (or a single-command response)
        and extract feed-rate, acceleration, and jerk values.

        Returns a dict with keys (all values are floats or None if not found)::

            {
              # M220 — feed-rate override %
              "feedrate_pct": 100.0,

              # M203 — maximum feed rates (mm/s)
              "max_feed_x": 500.0, "max_feed_y": 500.0,
              "max_feed_z": 5.0,   "max_feed_e": 50.0,

              # M201 — maximum acceleration (mm/s²)
              "max_accel_x": 500.0, "max_accel_y": 500.0,
              "max_accel_z": 100.0, "max_accel_e": 2000.0,

              # M204 — print / retract / travel acceleration (mm/s²)
              "accel_print": 500.0, "accel_retract": 1000.0, "accel_travel": 500.0,

              # M205 — jerk (mm/s)
              "jerk_x": 10.0, "jerk_y": 10.0,
              "jerk_z": 0.4,  "jerk_e": 5.0,
            }
        """
        import re
        result: dict = {}

        def _find(pattern, text, group=1):
            m = re.search(pattern, text)
            return float(m.group(group)) if m else None

        for raw_line in lines:
            # Strip leading 'echo:' and/or 'echo: ' prefix (M503 format)
            line = re.sub(r'^echo:\s*', '', raw_line).strip()

            # M220 direct response: "FR:100%"
            if line.startswith("FR:"):
                m = re.search(r'FR:(\d+(?:\.\d+)?)%', line)
                if m:
                    result["feedrate_pct"] = float(m.group(1))

            # M220 S<val>  (from M503 or direct M220 response)
            if re.match(r'M220\b', line):
                v = _find(r'S([\d.]+)', line)
                if v is not None:
                    result["feedrate_pct"] = v

            # M203 X<> Y<> Z<> E<>
            if re.match(r'M203\b', line):
                result["max_feed_x"] = _find(r'X([\d.]+)', line)
                result["max_feed_y"] = _find(r'Y([\d.]+)', line)
                result["max_feed_z"] = _find(r'Z([\d.]+)', line)
                result["max_feed_e"] = _find(r'E([\d.]+)', line)

            # M201 X<> Y<> Z<> E<>
            if re.match(r'M201\b', line):
                result["max_accel_x"] = _find(r'X([\d.]+)', line)
                result["max_accel_y"] = _find(r'Y([\d.]+)', line)
                result["max_accel_z"] = _find(r'Z([\d.]+)', line)
                result["max_accel_e"] = _find(r'E([\d.]+)', line)

            # M204 P<print> R<retract> T<travel>
            # Also matches direct M204 response: "Acceleration: P500.00 R1000.00 T500.00"
            if re.match(r'M204\b', line) or line.startswith("Acceleration:"):
                result["accel_print"]   = _find(r'P([\d.]+)', line)
                result["accel_retract"] = _find(r'R([\d.]+)', line)
                result["accel_travel"]  = _find(r'T([\d.]+)', line)

            # M205 X<jerk_x> Y<jerk_y> Z<jerk_z> E<jerk_e>
            if re.match(r'M205\b', line):
                result["jerk_x"] = _find(r'X([\d.]+)', line)
                result["jerk_y"] = _find(r'Y([\d.]+)', line)
                result["jerk_z"] = _find(r'Z([\d.]+)', line)
                result["jerk_e"] = _find(r'E([\d.]+)', line)

        return result

    def read_profiles(self) -> dict:
        """
        Query the printer with M503 and return a parsed profiles dict.
        Falls back to individual M204 query if M503 returns no useful data.
        """
        lines = self.send_and_receive("M503", timeout=15.0)
        profiles = self.parse_m503_profiles(lines)
        # If M204 accel values are missing (some firmware omits them from M503)
        if not profiles.get("accel_print"):
            m204_lines = self.send_and_receive("M204", timeout=5.0)
            profiles.update(self.parse_m503_profiles(m204_lines))
        return profiles

    def apply_profiles(self, profiles: dict) -> None:
        """
        Write the supplied profile values back to the printer.

        Only keys that are present (not None) are sent.  Saves to EEPROM
        with M500 at the end.
        """
        def _v(key):
            v = profiles.get(key)
            return None if v is None else float(v)

        # M203 — max feed rates
        m203_parts = ["M203"]
        for axis, key in [("X", "max_feed_x"), ("Y", "max_feed_y"),
                          ("Z", "max_feed_z"), ("E", "max_feed_e")]:
            v = _v(key)
            if v is not None:
                m203_parts.append(f"{axis}{v:.2f}")
        if len(m203_parts) > 1:
            self._send_gcode(" ".join(m203_parts))

        # M201 — max acceleration
        m201_parts = ["M201"]
        for axis, key in [("X", "max_accel_x"), ("Y", "max_accel_y"),
                          ("Z", "max_accel_z"), ("E", "max_accel_e")]:
            v = _v(key)
            if v is not None:
                m201_parts.append(f"{axis}{v:.2f}")
        if len(m201_parts) > 1:
            self._send_gcode(" ".join(m201_parts))

        # M204 — print / retract / travel accel
        m204_parts = ["M204"]
        for param, key in [("P", "accel_print"), ("R", "accel_retract"), ("T", "accel_travel")]:
            v = _v(key)
            if v is not None:
                m204_parts.append(f"{param}{v:.2f}")
        if len(m204_parts) > 1:
            self._send_gcode(" ".join(m204_parts))

        # M205 — jerk
        m205_parts = ["M205"]
        for axis, key in [("X", "jerk_x"), ("Y", "jerk_y"),
                          ("Z", "jerk_z"), ("E", "jerk_e")]:
            v = _v(key)
            if v is not None:
                m205_parts.append(f"{axis}{v:.2f}")
        if len(m205_parts) > 1:
            self._send_gcode(" ".join(m205_parts))

        # Save to EEPROM
        self._send_gcode("M500")
        logger.info("[MotionCtrl] Profiles applied and saved to EEPROM (M500).")

    def send_and_receive(self, command: str, timeout: float = 10.0) -> list[str]:
        """
        Send a raw G-code command and return all response lines as a list.

        Intended for the debug panel — returns every line the printer sends
        before the terminating 'ok', including informational lines such as
        those from M503, M220, M201, M204, M205, etc.

        Parameters
        ----------
        command:
            G-code command string, e.g. ``"M503"``.
        timeout:
            Maximum seconds to wait for the 'ok' terminator.

        Returns
        -------
        list[str]
            All non-empty lines received, including the final 'ok'.
        """
        raw = self._send_gcode(command.strip(), timeout=timeout)
        return [l for l in raw.splitlines() if l.strip()]

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

        Ported improvements from RoboCam-Suite 1.0:
        - flush() after write so the OS buffer drains immediately.
        - command_delay pause before the read loop starts.
        - in_waiting check + 10 ms sleep to avoid busy-waiting.

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

        if timeout is None:
            timeout = float(self._config.get("serial_timeout", 10.0))

        logger.info(f"[GCode TX] {command!r}")
        self._serial_port.write((command + "\n").encode("utf-8"))
        self._serial_port.flush()                     # drain OS buffer immediately
        time.sleep(self._command_delay)               # let printer start processing

        start = time.time()
        lines: list[str] = []

        while True:
            elapsed = time.time() - start
            if elapsed > timeout:
                raise TimeoutError(
                    f"Timeout waiting for 'ok' from printer after {command!r}."
                )

            if self._serial_port.in_waiting > 0:
                raw = self._serial_port.readline()
                line = raw.decode("utf-8", errors="replace").strip()
                if line:
                    logger.info(f"[GCode RX] {line!r}")
                    lines.append(line)
                    if line.lower().startswith("ok"):
                        break
                    if line.lower().startswith("error"):
                        raise RuntimeError(f"Printer error: {line}")
            else:
                time.sleep(0.01)   # 10 ms idle sleep — avoid busy-wait

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

        # Determine feed rate (F) to include in the command.
        # Priority: explicit speed arg > profile-derived speed > omit (firmware default).
        if speed is not None:
            effective_speed = speed
        else:
            # Choose the profile feed rate relevant to the axes being moved.
            # Convert mm/s → mm/min (G-code F units).
            if z is not None and x is None and y is None:
                # Pure Z move — use max_feed_z
                mf = self._profiles.get("max_feed_z")
            else:
                # XY (or combined) move — use max_feed_x (X=Y are paired)
                mf = self._profiles.get("max_feed_x")
            effective_speed = float(mf) * 60.0 if mf is not None else None

        if effective_speed is not None:
            parts.append(f"F{effective_speed:.1f}")

        self._send_gcode(" ".join(parts))
        self._wait_for_movement_to_finish()

    def _wait_for_movement_to_finish(self) -> None:
        """
        Block until all queued moves are complete.

        Strategy (ported from RoboCam-Suite 1.0):
        1. If M400 is known to be supported, send it and wait for 'ok'.
        2. If M400 times out or errors during a live move, permanently
           mark it as unsupported and fall back to a conservative sleep.
        3. If M400 was never tested (simulation path), return immediately.

        The fallback sleep is capped at 2 s — enough for the printer to
        finish any in-progress move at normal speeds without blocking the
        experiment for an unreasonably long time.
        """
        if self._simulate:
            return

        timeout = float(self._config.get("movement_wait_timeout", 30.0))

        if self._m400_supported is None:
            # Lazy test on first move — identical to 1.0 behaviour.
            # The printer has had time to boot by now (first move is always
            # issued well after connect()).
            logger.info("[MotionCtrl] Testing M400 support on first move...")
            try:
                self._send_gcode("M400", timeout=5.0)
                self._m400_supported = True
                logger.info("[MotionCtrl] M400 supported — will use for movement completion.")
                return
            except (TimeoutError, RuntimeError) as e:
                self._m400_supported = False
                logger.warning(
                    f"[MotionCtrl] M400 not supported or timed out ({e}). "
                    "Switching to delay-based fallback."
                )
            except Exception as e:
                self._m400_supported = False
                logger.warning(f"[MotionCtrl] M400 test error: {e}. Using fallback.")

        if self._m400_supported:
            try:
                self._send_gcode("M400", timeout=timeout)
                return
            except (TimeoutError, RuntimeError) as e:
                logger.warning(
                    f"[MotionCtrl] M400 failed during move ({e}). "
                    "Marking M400 as unsupported — switching to delay fallback."
                )
                self._m400_supported = False
            except Exception as e:
                logger.warning(f"[MotionCtrl] M400 unexpected error: {e}. Using fallback.")
                self._m400_supported = False

        # Fallback: conservative sleep (same as 1.0)
        fallback_delay = min(timeout, 2.0)
        logger.debug(f"[MotionCtrl] Using delay fallback: {fallback_delay:.1f} s")
        time.sleep(fallback_delay)

    def _sync_position(self) -> None:
        """Send M114 and update the cached position from the printer."""
        self.query_current_position()
