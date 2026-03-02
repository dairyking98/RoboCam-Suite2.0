"""
RoboCam Module - 3D Printer Control via G-code

This module provides control of a 3D printer (used as a positioning stage) via
G-code commands over serial communication. This is the preferred implementation
as it includes M400 wait commands for reliable movement completion.

Author: RoboCam-Suite
"""

import serial
import serial.tools.list_ports
import time
import sys
import re
from typing import Optional, Tuple
from picamera2 import Picamera2
from .config import get_config, Config
from .logging_config import get_logger

logger = get_logger(__name__)


class RoboCam:
    """
    Control interface for 3D printer used as robotic positioning stage.
    
    This class communicates with a 3D printer via serial G-code commands to control
    the X, Y, Z positioning of the print head (which holds the camera). This is the
    preferred implementation as it includes M400 wait commands for reliable operation.
    
    Attributes:
        baud_rate (int): Serial communication baud rate
        printer_on_serial (serial.Serial): Serial connection to printer
        X (float): Current X position in mm
        Y (float): Current Y position in mm
        Z (float): Current Z position in mm
    """
    
    def __init__(self, baudrate: Optional[int] = None, config: Optional[Config] = None, simulate_3d: bool = False) -> None:
        """
        Initialize RoboCam and connect to printer.
        
        Args:
            baudrate: Serial communication baud rate. If None, uses config default.
            config: Configuration object. If None, uses global config.
            simulate_3d: If True, skip printer connection and simulate movements (for testing without 3D printer hardware).
            
        Note:
            Automatically finds and connects to USB serial port.
            Sends M105 command to announce control and updates position.
            In simulation mode, skips serial connection and all movements just update position tracking.
            
        Raises:
            ConnectionError: If printer connection fails (only in non-simulation mode)
            serial.SerialException: If serial port cannot be opened (only in non-simulation mode)
        """
        # Load configuration
        self.config: Config = config if config else get_config()
        printer_config = self.config.get_printer_config()
        
        # Printer startup and settings
        self.baud_rate: int = baudrate if baudrate is not None else printer_config.get("baudrate", 115200)
        self.timeout: float = printer_config.get("timeout", 1.0)
        self.home_timeout: float = printer_config.get("home_timeout", 45.0)
        self.movement_wait_timeout: float = printer_config.get("movement_wait_timeout", 30.0)
        self.command_delay: float = printer_config.get("command_delay", 0.1)
        self.position_update_delay: float = printer_config.get("position_update_delay", 0.1)
        self.connection_retry_delay: float = printer_config.get("connection_retry_delay", 2.0)
        self.max_retries: int = printer_config.get("max_retries", 5)
        
        # Simulation mode flag (for 3D printer)
        self.simulate: bool = simulate_3d  # Keep for backward compatibility
        self.simulate_3d: bool = simulate_3d
        
        # Initialize position tracking
        self.X: Optional[float] = None
        self.Y: Optional[float] = None
        self.Z: Optional[float] = None
        self.printer_on_serial: Optional[serial.Serial] = None
        
        if self.simulate_3d:
            # Simulation mode: initialize position to origin
            logger.info("RoboCam running in 3D PRINTER SIMULATION MODE - no printer connection")
            self.X = 0.0
            self.Y = 0.0
            self.Z = 0.0
        else:
            # Connect to printer
            try:
                serial_port = self.find_serial_port()
                if serial_port:
                    self.printer_on_serial = self.wait_for_connection(serial_port)
                else:
                    raise ConnectionError("No serial port found. Check USB connection to printer.")
                
                # Test connection with M114 (position query) instead of M105
                # M105 (temperature query) can fail during startup, but M114 is more reliable
                logger.debug("DEBUG: Initialization - Testing connection with M114 position query...")
                try:
                    # Try M114 first - it's more reliable than M105 during startup
                    self.X, self.Y, self.Z = self.update_current_position()
                    logger.info("Connection verified - printer is ready")
                    logger.debug(f"DEBUG: Initialization - Position query successful: X={self.X}, Y={self.Y}, Z={self.Z}")
                except Exception as e:
                    logger.warning(f"Initial position query failed: {e}")
                    logger.debug("DEBUG: Initialization - Will retry position update...")
                    # Set position to None - will be updated on next successful query
                    self.X = None
                    self.Y = None
                    self.Z = None
                
                # Test M400 (wait for movement completion) - critical for reliable movements
                logger.debug("DEBUG: Initialization - Testing M400 (wait for movement completion)...")
                try:
                    # Test M400 by sending it with a short timeout
                    # M400 should respond quickly if supported, or timeout/error if not
                    logger.debug("DEBUG: Sending M400 test command...")
                    self.send_gcode("M400", timeout=5.0)  # 5 second timeout for test
                    logger.info("M400 wait command supported (firmware supports movement completion detection)")
                    self._m400_supported = True
                    logger.debug("DEBUG: M400 initialization successful - will use for movement completion")
                except (TimeoutError, RuntimeError) as e:
                    # M400 not supported or timed out
                    logger.warning(f"M400 command not supported or failed during initialization: {e}")
                    logger.warning("Firmware may not support M400 - will use delay-based fallback for movements")
                    self._m400_supported = False
                    logger.debug("DEBUG: M400 initialization failed - will use delay fallback")
                except Exception as e:
                    logger.warning(f"M400 test had unexpected error: {e}")
                    logger.warning("Assuming M400 not supported - will use delay-based fallback")
                    self._m400_supported = False
                
                # Optionally try M105 as a secondary test (but don't fail if it doesn't work)
                logger.debug("DEBUG: Initialization - Optionally testing M105 (temperature query)...")
                try:
                    self.send_gcode("M105", timeout=3.0)  # Shorter timeout for optional test
                    logger.debug("DEBUG: Initialization - M105 command successful (printer fully initialized)")
                except (TimeoutError, RuntimeError) as e:
                    # M105 may fail during startup or not be supported - this is OK
                    logger.debug(f"DEBUG: M105 optional test failed (this is OK): {e}")
                except Exception as e:
                    logger.debug(f"DEBUG: M105 optional test had error (this is OK): {e}")
                
                # Update position (if not already set above)
                if self.X is None or self.Y is None or self.Z is None:
                    logger.debug("DEBUG: Initialization - Updating current position (retry)...")
                    try:
                        self.X, self.Y, self.Z = self.update_current_position()
                        logger.debug(f"DEBUG: Initialization - Position updated: X={self.X}, Y={self.Y}, Z={self.Z}")
                    except Exception as e:
                        logger.warning(f"Failed to get initial position, but connection is established: {e}")
                        logger.debug("DEBUG: Initialization - Position update failed but continuing...")
                        # Set position to None - will be updated on next successful query
                        self.X = None
                        self.Y = None
                        self.Z = None
            except Exception as e:
                # Don't raise ConnectionError in simulation mode
                if self.simulate_3d:
                    logger.warning(f"3D printer simulation mode: Ignoring printer connection error: {e}")
                    # Set default position
                    self.X = 0.0
                    self.Y = 0.0
                    self.Z = 0.0
                else:
                    raise ConnectionError(f"Failed to initialize RoboCam: {e}") from e

    def send_gcode(self, command: str, timeout: Optional[float] = None) -> None:
        """
        Send a G-code command to the printer and wait for acknowledgment.
        
        Args:
            command: G-code command string to send (e.g., "G28", "G0 X10 Y20")
            timeout: Timeout in seconds. If None, uses config timeout.
            
        Raises:
            ConnectionError: If printer is not connected (only in non-simulation mode)
            serial.SerialException: If serial communication fails (only in non-simulation mode)
            TimeoutError: If printer doesn't respond within timeout (only in non-simulation mode)
            
        Note:
            Waits for "ok" response from printer before returning.
            Raises exception if printer responds with "error".
            In simulation mode, this is a no-op.
        """
        if self.simulate_3d:
            logger.debug(f'[3D PRINTER SIMULATION] G-code command: "{command}"')
            time.sleep(self.command_delay)  # Simulate command delay
            return
        
        if self.printer_on_serial is None:
            raise ConnectionError("Printer not connected. Cannot send G-code command.")
        
        if timeout is None:
            timeout = self.timeout
        
        logger.debug(f'DEBUG: send_gcode - Sending command: "{command}" (timeout={timeout}s)')
        logger.debug(f'DEBUG: send_gcode - Connection state: is_open={self.printer_on_serial.is_open}, bytes_waiting={self.printer_on_serial.in_waiting}')
        
        try:
            command_bytes = (command + '\n').encode('utf-8')
            logger.debug(f'DEBUG: send_gcode - Command bytes: {command_bytes.hex()} (length: {len(command_bytes)})')
            
            bytes_written = self.printer_on_serial.write(command_bytes)
            logger.debug(f'DEBUG: send_gcode - Wrote {bytes_written} bytes to serial port')
            self.printer_on_serial.flush()  # Ensure command is sent immediately
            logger.debug(f'DEBUG: send_gcode - Command flushed, waiting {self.command_delay}s for processing...')
            
            time.sleep(self.command_delay)  # Initial delay for command processing
            
            start_time = time.time()
            response_count = 0
            logger.debug(f'DEBUG: send_gcode - Starting response wait loop (timeout: {timeout}s)...')
            
            while True:
                elapsed = time.time() - start_time
                if elapsed > timeout:
                    logger.error(f'DEBUG: send_gcode - TIMEOUT after {elapsed:.2f}s waiting for response to "{command}"')
                    logger.error(f'DEBUG: send_gcode - Received {response_count} responses before timeout')
                    raise TimeoutError(f"G-code command '{command}' timed out after {timeout}s")
                
                bytes_waiting = self.printer_on_serial.in_waiting
                if bytes_waiting > 0:
                    response_count += 1
                    raw_response = self.printer_on_serial.readline()
                    try:
                        response = raw_response.decode('utf-8', errors='replace').strip()
                        logger.debug(f'DEBUG: send_gcode - Response #{response_count} ({elapsed:.3f}s): {repr(response)}')
                        logger.debug(f'DEBUG: send_gcode - Raw response hex: {raw_response.hex()}')
                    except Exception as e:
                        logger.warning(f'DEBUG: send_gcode - Failed to decode response: {e}, raw: {raw_response.hex()}')
                        continue
                    
                    if "ok" in response.lower():
                        logger.debug(f'DEBUG: send_gcode - Received "ok" response for "{command}" after {elapsed:.3f}s')
                        break
                    elif "error" in response.lower():
                        logger.error(f'DEBUG: send_gcode - Printer returned ERROR for "{command}": {response}')
                        raise RuntimeError(f"Printer error for command '{command}': {response}")
                    else:
                        logger.debug(f'DEBUG: send_gcode - Non-ok response (continuing to wait): {response}')
                else:
                    # Log periodically when waiting
                    if int(elapsed * 10) % 5 == 0:  # Every 0.5 seconds
                        logger.debug(f'DEBUG: send_gcode - Waiting for response... ({elapsed:.2f}s elapsed, {timeout - elapsed:.2f}s remaining)')
                
                time.sleep(0.01)  # Small delay to avoid busy waiting
                
        except serial.SerialException as e:
            logger.error(f'DEBUG: send_gcode - Serial exception: {type(e).__name__}: {e}')
            logger.exception("DEBUG: send_gcode - Serial exception details:")
            raise ConnectionError(f"Serial communication error: {e}") from e
        except TimeoutError:
            logger.error(f'DEBUG: send_gcode - TimeoutError for command "{command}"')
            raise
        except Exception as e:
            logger.error(f'DEBUG: send_gcode - Unexpected error: {type(e).__name__}: {e}')
            logger.exception("DEBUG: send_gcode - Exception details:")
            raise

    def find_serial_port(self) -> Optional[str]:
        """
        Find available USB serial port for printer connection.
        
        Returns:
            Device path of first available USB serial port, or None if none found.
            
        Note:
            Tests each USB port by attempting to open it. Returns the first
            port that can be opened successfully.
            
        Raises:
            serial.SerialException: If port enumeration fails
        """
        try:
            logger.debug("DEBUG: Starting serial port discovery...")
            ports = serial.tools.list_ports.comports()
            logger.debug(f"DEBUG: Found {len(ports)} total serial ports")
            
            for port in ports:
                logger.debug(f"DEBUG: Available port: {port.device} - {port.description} (VID:{port.vid}, PID:{port.pid})")
            
            usb_ports = [port for port in ports if 'USB' in port.description.upper()]
            logger.debug(f"DEBUG: Found {len(usb_ports)} USB serial ports")
            
            if not usb_ports:
                logger.warning("No USB serial ports found.")
                return None

            for usb_port in usb_ports:
                logger.debug(f"DEBUG: Testing USB port: {usb_port.device} ({usb_port.description})")
                logger.debug(f"DEBUG: Attempting to open port with baudrate={self.baud_rate}, timeout={self.timeout}s")
                try:
                    ser = serial.Serial(usb_port.device, self.baud_rate, timeout=self.timeout)
                    logger.debug(f"DEBUG: Successfully opened port {usb_port.device}")
                    logger.debug(f"DEBUG: Port settings: baudrate={ser.baudrate}, timeout={ser.timeout}, parity={ser.parity}")
                    ser.close()  # Close the port now that we know it works
                    logger.info(f"Selected port: {usb_port.device} - {usb_port.description}")
                    logger.debug(f"DEBUG: Port closed after test, returning port path")
                    return usb_port.device
                except serial.SerialException as e:
                    logger.warning(f"DEBUG: Failed to connect on {usb_port.device}: {e}")
                    continue

            logger.warning("No available ports responded.")
            return None
            
        except Exception as e:
            logger.error(f"Error finding serial port: {e}")
            logger.exception("DEBUG: Exception details:")
            return None

    def wait_for_connection(self, serial_port: str) -> serial.Serial:
        """
        Attempt to open a serial connection and wait until it is established.
        
        Args:
            serial_port: Device path of serial port to connect to
            
        Returns:
            Serial connection object
            
        Raises:
            ConnectionError: If connection fails after max retries
            serial.SerialException: If serial port cannot be opened
            
        Note:
            Retries connection with configurable delay and max retries.
            Waits 1 second after connection for printer to initialize.
        """
        logger.debug(f"DEBUG: wait_for_connection called for port: {serial_port}")
        logger.debug(f"DEBUG: Connection settings: baudrate={self.baud_rate}, timeout={self.timeout}s, max_retries={self.max_retries}")
        
        retries = 0
        while retries < self.max_retries:
            try:
                logger.debug(f"DEBUG: Attempt {retries + 1}/{self.max_retries}: Opening serial connection...")
                self.printer_on_serial = serial.Serial(
                    serial_port, 
                    self.baud_rate, 
                    timeout=self.timeout
                )
                logger.info(f"Connected to {serial_port} at {self.baud_rate} baud. Waiting for printer to initialize...")
                logger.debug(f"DEBUG: Serial connection opened successfully")
                logger.debug(f"DEBUG: Connection state - is_open: {self.printer_on_serial.is_open}, bytes_waiting: {self.printer_on_serial.in_waiting}")
                
                # Wait for printer to fully initialize (Marlin printers can take several seconds)
                # Allow time for all startup messages and SD card initialization to complete
                logger.debug("DEBUG: Waiting 5 seconds for printer initialization (allowing startup messages to complete)...")
                time.sleep(2)  # Initial wait
                
                # Dump any initial startup messages
                logger.debug("DEBUG: Dumping initial printer output...")
                self.dump_printer_output()
                
                # Wait a bit more and dump again (printer may still be initializing)
                logger.debug("DEBUG: Waiting additional 3 seconds for printer to complete initialization...")
                time.sleep(3)
                
                # Dump any remaining startup messages
                bytes_waiting = self.printer_on_serial.in_waiting
                logger.debug(f"DEBUG: After initialization wait, bytes waiting in buffer: {bytes_waiting}")
                if bytes_waiting > 0:
                    logger.debug("DEBUG: Dumping remaining printer output...")
                    self.dump_printer_output()
                
                logger.debug("DEBUG: Connection established successfully")
                return self.printer_on_serial
            except serial.SerialException as e:
                retries += 1
                logger.warning(f"DEBUG: Serial connection attempt {retries} failed: {type(e).__name__}: {e}")
                if retries >= self.max_retries:
                    logger.error(f"DEBUG: Max retries ({self.max_retries}) reached. Connection failed.")
                    raise ConnectionError(
                        f"Failed to connect to {serial_port} after {self.max_retries} attempts: {e}"
                    ) from e
                logger.info(f"Waiting for connection on {serial_port}... (attempt {retries}/{self.max_retries})")
                logger.debug(f"DEBUG: Waiting {self.connection_retry_delay}s before retry...")
                time.sleep(self.connection_retry_delay)
        
        raise ConnectionError(f"Failed to connect to {serial_port} after {self.max_retries} attempts")
                
    def wait_for_movement_completion(self, timeout: Optional[float] = None) -> None:
        """
        Wait for printer movement to complete.
        
        Args:
            timeout: Timeout in seconds. If None, uses movement_wait_timeout.
            
        Note:
            First tries M400 command. If M400 fails or times out (firmware may not support it),
            falls back to a calculated delay based on movement distance and speed.
            M114 position polling is NOT used as it reports projected position, not actual position.
        """
        if timeout is None:
            timeout = self.movement_wait_timeout
        
        # Track whether M400 is supported (should be set during initialization)
        # If not set yet, test it now (fallback for backwards compatibility)
        if not hasattr(self, '_m400_supported'):
            logger.debug("DEBUG: wait_for_movement_completion - M400 support not yet determined, testing now...")
            try:
                self.send_gcode("M400", timeout=5.0)
                self._m400_supported = True
                logger.debug("DEBUG: M400 support confirmed during movement")
            except Exception:
                self._m400_supported = False
                logger.debug("DEBUG: M400 not supported - using fallback")
        
        if self._m400_supported:
            # Try M400 first
            try:
                logger.debug("DEBUG: wait_for_movement_completion - Trying M400 command...")
                self.send_gcode("M400", timeout=timeout)
                logger.debug("DEBUG: wait_for_movement_completion - M400 successful")
                return
            except (TimeoutError, RuntimeError) as e:
                # M400 not supported or timed out - mark as unsupported and use fallback
                logger.warning(f"M400 command failed (firmware may not support it): {e}")
                logger.info("Falling back to delay-based method for movement completion")
                self._m400_supported = False
            except Exception as e:
                logger.warning(f"M400 command had unexpected error, using fallback: {e}")
                self._m400_supported = False
        
        # Fallback: Use a conservative delay if M400 is not supported
        # Since we can't reliably detect movement completion without M400,
        # we use a calculated delay based on movement parameters stored during the move
        # For now, use a conservative fixed delay as safety margin
        logger.debug("DEBUG: wait_for_movement_completion - Using delay-based fallback...")
        fallback_delay = min(timeout, 2.0)  # Wait up to 2 seconds or timeout, whichever is shorter
        logger.debug(f"DEBUG: wait_for_movement_completion - Waiting {fallback_delay}s as safety margin")
        time.sleep(fallback_delay)
        logger.debug("DEBUG: wait_for_movement_completion - Delay completed")
    
    def dump_printer_output(self) -> None:
        """
        Read and print all pending output from printer.
        
        Note:
            Clears the serial buffer by reading all available data.
            Useful after connection to clear startup messages.
        """
        bytes_read = 0
        lines_read = 0
        logger.debug(f"DEBUG: dump_printer_output - initial bytes waiting: {self.printer_on_serial.in_waiting}")
        
        while self.printer_on_serial.in_waiting > 0:  # Check if there's data waiting to be read
            try:
                raw_response = self.printer_on_serial.readline()
                bytes_read += len(raw_response)
                lines_read += 1
                response = raw_response.decode('utf-8', errors='replace').strip()
                logger.debug(f'DEBUG: Printer output line {lines_read}: {repr(response)} (raw: {raw_response.hex()})')
            except Exception as e:
                logger.warning(f"DEBUG: Error reading printer output: {e}")
                break
        
        if lines_read > 0:
            logger.debug(f"DEBUG: Dumped {lines_read} lines, {bytes_read} bytes total from printer buffer")
        else:
            logger.debug("DEBUG: No output to dump from printer")
    
    def set_acceleration(self, acceleration: float) -> None:
        """
        Set printer acceleration in mm/s².
        
        Args:
            acceleration: Acceleration value in mm/s² (must be > 0)
            
        Raises:
            ConnectionError: If printer is not connected (only in non-simulation mode)
            ValueError: If acceleration is invalid
            RuntimeError: If command fails (only in non-simulation mode)
            
        Note:
            Sends M204 S<acceleration> command to set acceleration.
            Some printers may use M204 P<acceleration> for print acceleration.
            This uses S parameter for general acceleration.
            In simulation mode, this is a no-op.
        """
        if acceleration <= 0:
            raise ValueError(f"Invalid acceleration: {acceleration} (must be > 0)")
        
        if self.simulate_3d:
            logger.info(f'[3D PRINTER SIMULATION] Acceleration set to {acceleration} mm/s²')
            return
        
        if self.printer_on_serial is None:
            raise ConnectionError("Printer not connected. Cannot set acceleration.")
        
        try:
            # M204 S sets acceleration in mm/s²
            # Some firmware may use M204 P for print acceleration, S for travel
            # Using S for general acceleration setting
            self.send_gcode(f"M204 S{acceleration}")
            logger.info(f'Acceleration set to {acceleration} mm/s²')
        except Exception as e:
            raise RuntimeError(f"Failed to set acceleration: {e}") from e
                
    def home(self) -> None:
        """
        Home the printer to origin (0, 0, 0).
        
        Raises:
            ConnectionError: If printer is not connected (only in non-simulation mode)
            RuntimeError: If homing command fails (only in non-simulation mode)
            TimeoutError: If homing times out (only in non-simulation mode)
            
        Note:
            Sends G28 command which homes all axes.
            Updates position after homing completes.
            In simulation mode, just resets position to (0, 0, 0).
        """
        if self.simulate_3d:
            logger.info('[3D PRINTER SIMULATION] Homing printer - resetting to origin')
            self.X = 0.0
            self.Y = 0.0
            self.Z = 0.0
            logger.info(f"[3D PRINTER SIMULATION] Printer homed. Reset positions to X: {self.X}, Y: {self.Y}, Z: {self.Z}")
            return
        
        logger.info('Homing Printer, please wait for the countdown to complete')
        try:
            self.send_gcode('G28', timeout=self.home_timeout)  # Use configurable home timeout
            # Update position after homing
            self.X, self.Y, self.Z = self.update_current_position()
            logger.info(f"Printer homed. Reset positions to X: {self.X}, Y: {self.Y}, Z: {self.Z}")
        except Exception as e:
            raise RuntimeError(f"Homing failed: {e}") from e

    def update_current_position(self) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        """
        Query printer for current position and update internal state.
        
        Returns:
            Tuple of (X, Y, Z) positions in mm, or (None, None, None) if unavailable.
            
        Raises:
            ConnectionError: If printer is not connected (only in non-simulation mode)
            TimeoutError: If position query times out (only in non-simulation mode)
            ValueError: If position cannot be parsed (only in non-simulation mode)
            
        Note:
            Sends M114 command to get current position.
            Parses response and updates self.X, self.Y, self.Z.
            In simulation mode, returns current tracked position.
        """
        if self.simulate_3d:
            logger.debug('[3D PRINTER SIMULATION] Updating current position')
            return self.X, self.Y, self.Z
        
        if self.printer_on_serial is None:
            raise ConnectionError("Printer not connected. Cannot update position.")
        
        logger.debug('Updating current position')
        
        try:
            # Manually sending command because send_gcode dumps all output before "ok" response
            command = "M114"
            self.printer_on_serial.write((command + '\n').encode('utf-8'))
            time.sleep(self.position_update_delay)
            
            # Parse printer's response with timeout
            start_time = time.time()
            response = ""
            while True:
                if time.time() - start_time > self.timeout:
                    raise TimeoutError(f"Position update timed out after {self.timeout}s")
                
                if self.printer_on_serial.in_waiting > 0:
                    response = self.printer_on_serial.readline().decode('utf-8').strip()
                    logger.debug(f'Printer response: {response}')
                    if response.startswith('X:'):
                        break
                
                time.sleep(0.01)
            
            # Parse position values
            position = {}
            matches = re.findall(r'(X|Y|Z):([0-9.-]+)', response)
            collected_axes = set()
            
            for axis, value in matches:
                try:
                    if axis not in collected_axes:
                        position[axis] = float(value)
                        collected_axes.add(axis)
                except ValueError as e:
                    logger.warning(f"Could not parse {axis} value '{value}': {e}")
                    continue
            
            if not position:
                raise ValueError(f"Could not parse position from response: {response}")
                    
            # Save XYZ values
            self.X = position.get('X', None)
            self.Y = position.get('Y', None)
            self.Z = position.get('Z', None)
            
            # Dump remaining printer output
            self.dump_printer_output()
            
            return position.get('X', None), position.get('Y', None), position.get('Z', None)
            
        except serial.SerialException as e:
            raise ConnectionError(f"Serial communication error during position update: {e}") from e
        
    def move_relative(self, X: Optional[float] = None, Y: Optional[float] = None, 
                     Z: Optional[float] = None, speed: Optional[float] = None) -> None:
        """
        Move the print head (camera) by a relative amount in millimeters.
        
        Args:
            X: Relative movement in X direction (mm). None to skip.
            Y: Relative movement in Y direction (mm). None to skip.
            Z: Relative movement in Z direction (mm). None to skip.
            speed: Movement speed in mm/min. None to use default.
            
        Raises:
            ConnectionError: If printer is not connected (only in non-simulation mode)
            RuntimeError: If movement command fails (only in non-simulation mode)
            ValueError: If position values are invalid
            
        Note:
            Uses G91 (relative positioning mode).
            Sends M400 to wait for movement completion before returning.
            Updates position after movement.
            In simulation mode, just updates internal position tracking.
        """
        # Validate that at least one axis is specified
        if X is None and Y is None and Z is None:
            raise ValueError("At least one axis (X, Y, or Z) must be specified for movement")
        
        if speed is not None and speed <= 0:
            raise ValueError(f"Invalid speed: {speed} (must be > 0)")
        
        if self.simulate_3d:
            # Update position tracking
            if X is not None:
                self.X = (self.X or 0.0) + X
            if Y is not None:
                self.Y = (self.Y or 0.0) + Y
            if Z is not None:
                self.Z = (self.Z or 0.0) + Z
            logger.debug(f'[3D PRINTER SIMULATION] Relative move to X:{self.X}, Y:{self.Y}, Z:{self.Z}')
            time.sleep(0.1)  # Simulate movement delay
            return
        
        if self.printer_on_serial is None:
            raise ConnectionError("Printer not connected. Cannot move.")
        
        logger.debug(f'Relative move to X:{X}, Y:{Y}, Z:{Z}')
        
        try:
            self.send_gcode('G91')
            command = "G0"

            if speed is not None:
                command += f" F{speed}"
            if X is not None:
                command += f" X{X}"
            if Y is not None:
                command += f" Y{Y}"
            if Z is not None:
                command += f" Z{Z}"

            self.send_gcode(command)
            self.wait_for_movement_completion(timeout=self.movement_wait_timeout)
            self.update_current_position()
        except Exception as e:
            raise RuntimeError(f"Relative movement failed: {e}") from e
            
    def move_absolute(self, X: Optional[float] = None, Y: Optional[float] = None,
                      Z: Optional[float] = None, speed: Optional[float] = None) -> None:
        """
        Move the print head (camera) to an absolute position in millimeters.
        
        Args:
            X: Absolute X position (mm). None to skip.
            Y: Absolute Y position (mm). None to skip.
            Z: Absolute Z position (mm). None to skip.
            speed: Movement speed in mm/min. None to use default.
            
        Raises:
            ConnectionError: If printer is not connected (only in non-simulation mode)
            RuntimeError: If movement command fails (only in non-simulation mode)
            ValueError: If position values are invalid
            
        Note:
            Uses G90 (absolute positioning mode).
            Sends M400 to wait for movement completion before returning.
            Updates position after movement.
            In simulation mode, just updates internal position tracking.
        """
        # Validate that at least one axis is specified
        if X is None and Y is None and Z is None:
            raise ValueError("At least one axis (X, Y, or Z) must be specified for movement")
        
        if speed is not None and speed <= 0:
            raise ValueError(f"Invalid speed: {speed} (must be > 0)")
        
        if self.simulate_3d:
            # Update position tracking
            if X is not None:
                self.X = X
            if Y is not None:
                self.Y = Y
            if Z is not None:
                self.Z = Z
            logger.debug(f'[3D PRINTER SIMULATION] Absolute move to X:{self.X}, Y:{self.Y}, Z:{self.Z}')
            time.sleep(0.1)  # Simulate movement delay
            return
        
        if self.printer_on_serial is None:
            raise ConnectionError("Printer not connected. Cannot move.")
        
        logger.debug(f'Absolute move to X:{X}, Y:{Y}, Z:{Z}')
        
        try:
            self.send_gcode('G90')
            command = "G0"

            if speed is not None:
                command += f" F{speed}"
            if X is not None:
                command += f" X{X}"
            if Y is not None:
                command += f" Y{Y}"
            if Z is not None:
                command += f" Z{Z}"

            self.send_gcode(command)
            self.wait_for_movement_completion(timeout=self.movement_wait_timeout)
            self.update_current_position()
        except Exception as e:
            raise RuntimeError(f"Absolute movement failed: {e}") from e
        
    
