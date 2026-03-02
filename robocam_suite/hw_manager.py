import robocam_suite.drivers.motion.gcode_serial_motion as gcode_serial_motion
import robocam_suite.drivers.gpio.arduino_serial_gpio as arduino_serial_gpio
import robocam_suite.drivers.gpio.null_gpio as null_gpio
import robocam_suite.drivers.camera.opencv_camera as opencv_camera
from robocam_suite.config.config_manager import config_manager
from robocam_suite.logger import setup_logger

logger = setup_logger()


class HardwareManager:
    """
    Manages the lifecycle of all hardware drivers.

    Hardware is instantiated lazily on first access. The GPIO controller
    is entirely optional: when ``gpio_controller.enabled`` is ``false``
    in the configuration, a :class:`NullGPIOController` is used instead
    so the rest of the application can run without any GPIO device.
    """

    def __init__(self):
        self._config = config_manager
        self._motion_controller = None
        self._camera = None
        self._gpio_controller = None

    # ------------------------------------------------------------------
    # Motion Controller
    # ------------------------------------------------------------------

    def get_motion_controller(self):
        if self._motion_controller is None:
            mc_config = self._config.get_section("motion_controller")
            simulate = self._config.get_section("simulation").get("motion_controller", False)
            driver = mc_config.get("driver")
            if driver == "gcode_serial":
                self._motion_controller = gcode_serial_motion.GCodeSerialMotionController(
                    config=mc_config, simulate=simulate
                )
            else:
                raise ValueError(f"Unknown motion controller driver: {driver!r}")
        return self._motion_controller

    # ------------------------------------------------------------------
    # Camera
    # ------------------------------------------------------------------

    def get_camera(self):
        if self._camera is None:
            cam_config = self._config.get_section("camera")
            simulate = self._config.get_section("simulation").get("camera", False)
            driver = cam_config.get("driver")
            if driver == "opencv":
                self._camera = opencv_camera.OpenCVCamera(config=cam_config, simulate=simulate)
            else:
                raise ValueError(f"Unknown camera driver: {driver!r}")
        return self._camera

    # ------------------------------------------------------------------
    # GPIO Controller
    # ------------------------------------------------------------------

    def get_gpio_controller(self):
        if self._gpio_controller is None:
            gpio_config = self._config.get_section("gpio_controller")
            enabled = gpio_config.get("enabled", False)
            simulate = self._config.get_section("simulation").get("gpio_controller", False)

            if not enabled and not simulate:
                # No GPIO hardware — use the silent no-op controller
                logger.info(
                    "GPIO controller is disabled in config (gpio_controller.enabled=false). "
                    "Using NullGPIOController — laser and GPIO commands will be silently ignored."
                )
                self._gpio_controller = null_gpio.NullGPIOController()
            else:
                driver = gpio_config.get("driver")
                if driver == "arduino_serial":
                    self._gpio_controller = arduino_serial_gpio.ArduinoSerialGPIOController(
                        config=gpio_config, simulate=simulate
                    )
                else:
                    raise ValueError(f"Unknown GPIO controller driver: {driver!r}")

        return self._gpio_controller

    @property
    def gpio_enabled(self) -> bool:
        """Returns True if a real (or simulated) GPIO device is configured."""
        gpio_config = self._config.get_section("gpio_controller")
        simulate = self._config.get_section("simulation").get("gpio_controller", False)
        return gpio_config.get("enabled", False) or simulate

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------

    def connect_all(self):
        """Connect all configured hardware devices.

        Each device is connected independently.  A failure on one device is
        logged but does **not** disconnect the others that already succeeded.
        Raises the last exception encountered (if any) so callers can detect
        that at least one device failed to connect.
        """
        errors = []

        logger.info("Connecting to motion controller...")
        try:
            self.get_motion_controller().connect()
        except Exception as e:
            logger.error(f"[HW] Motion controller connect failed: {e}")
            errors.append(e)

        logger.info("Connecting to camera...")
        try:
            self.get_camera().connect()
        except Exception as e:
            logger.error(f"[HW] Camera connect failed: {e}")
            errors.append(e)

        logger.info("Connecting to GPIO controller...")
        try:
            self.get_gpio_controller().connect()
        except Exception as e:
            logger.error(f"[HW] GPIO controller connect failed: {e}")
            errors.append(e)

        if errors:
            logger.warning(f"[HW] {len(errors)} device(s) failed to connect (see errors above).")
            raise errors[-1]   # re-raise last error so callers know something failed
        else:
            logger.info("All hardware connected.")

    def disconnect_all(self):
        """Disconnect all hardware devices that were previously connected."""
        if self._motion_controller:
            self._motion_controller.disconnect()
        if self._camera:
            self._camera.disconnect()
        if self._gpio_controller:
            self._gpio_controller.disconnect()
        logger.info("All hardware disconnected.")


# Global hardware manager instance
hw_manager = HardwareManager()
