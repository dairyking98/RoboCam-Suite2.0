import robocam_suite.drivers.motion.gcode_serial_motion as gcode_serial_motion
import robocam_suite.drivers.gpio.arduino_serial_gpio as arduino_serial_gpio
import robocam_suite.drivers.camera.opencv_camera as opencv_camera
from robocam_suite.config.config_manager import config_manager
from robocam_suite.logger import setup_logger

logger = setup_logger()

class HardwareManager:
    """Manages the lifecycle of all hardware drivers."""

    def __init__(self):
        self._config = config_manager
        self._motion_controller = None
        self._camera = None
        self._gpio_controller = None

    def get_motion_controller(self):
        if self._motion_controller is None:
            mc_config = self._config.get_section("motion_controller")
            simulate = self._config.get_section("simulation").get("motion_controller", False)
            if mc_config.get("driver") == "gcode_serial":
                self._motion_controller = gcode_serial_motion.GCodeSerialMotionController(config=mc_config, simulate=simulate)
            else:
                raise ValueError(f"Unknown motion controller driver: {mc_config.get('driver')}")
        return self._motion_controller

    def get_camera(self):
        if self._camera is None:
            cam_config = self._config.get_section("camera")
            simulate = self._config.get_section("simulation").get("camera", False)
            if cam_config.get("driver") == "opencv":
                self._camera = opencv_camera.OpenCVCamera(config=cam_config, simulate=simulate)
            else:
                raise ValueError(f"Unknown camera driver: {cam_config.get('driver')}")
        return self._camera

    def get_gpio_controller(self):
        if self._gpio_controller is None:
            gpio_config = self._config.get_section("gpio_controller")
            simulate = self._config.get_section("simulation").get("gpio_controller", False)
            if gpio_config.get("driver") == "arduino_serial":
                self._gpio_controller = arduino_serial_gpio.ArduinoSerialGPIOController(config=gpio_config, simulate=simulate)
            else:
                raise ValueError(f"Unknown GPIO controller driver: {gpio_config.get('driver')}")
        return self._gpio_controller

    def connect_all(self):
        try:
            logger.info("Connecting to motion controller...")
            self.get_motion_controller().connect()
            logger.info("Connecting to camera...")
            self.get_camera().connect()
            logger.info("Connecting to GPIO controller...")
            self.get_gpio_controller().connect()
            logger.info("All hardware connected.")
        except Exception as e:
            logger.error(f"Failed to connect all hardware: {e}")
            self.disconnect_all()
            raise

    def disconnect_all(self):
        if self._motion_controller:
            self._motion_controller.disconnect()
        if self._camera:
            self._camera.disconnect()
        if self._gpio_controller:
            self._gpio_controller.disconnect()
        logger.info("All hardware disconnected.")

# Global hardware manager instance
hw_manager = HardwareManager()
