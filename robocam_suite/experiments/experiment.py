import os
import time
import csv
from datetime import datetime
from typing import List, Tuple, Dict, Any

from robocam_suite.hw_manager import HardwareManager
from robocam_suite.experiments.well_plate import WellPlate
from robocam_suite.logger import setup_logger

logger = setup_logger()

class Experiment:
    """Manages the execution of a well-plate experiment."""

    def __init__(self, hw_manager: HardwareManager, well_plate: WellPlate, params: Dict[str, Any]):
        self.hw_manager = hw_manager
        self.well_plate = well_plate
        self.params = params
        self.is_running = False
        self._stop_requested = False

        self.output_dir = self._create_output_directory()

    def _create_output_directory(self) -> str:
        base_dir = self.params.get("output_dir", "outputs")
        exp_name = self.params.get("name", "experiment")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dir_name = f"{timestamp}_{exp_name}"
        full_path = os.path.join(base_dir, dir_name)
        os.makedirs(full_path, exist_ok=True)
        logger.info(f"Created experiment output directory: {full_path}")
        return full_path

    def run(self):
        """Runs the entire experiment from start to finish."""
        if self.is_running:
            logger.warning("Experiment is already running.")
            return

        self.is_running = True
        self._stop_requested = False
        logger.info(f"Starting experiment: {self.params.get('name', 'Untitled')}")

        self._save_well_plate_csv()

        motion_controller = self.hw_manager.get_motion_controller()
        gpio_controller = self.hw_manager.get_gpio_controller()
        camera = self.hw_manager.get_camera()

        # Read laser pin from config; fall back to params, then to 21 as a last resort
        laser_pin = (
            self.hw_manager._config.get_section("gpio_controller").get("laser_pin")
            or self.params.get("laser_pin", 21)
        )
        if not self.hw_manager.gpio_enabled:
            logger.info(
                "GPIO is disabled — laser commands will be silently ignored by NullGPIOController."
            )

        try:
            for i, position in enumerate(self.well_plate.get_path()):
                if self._stop_requested:
                    logger.info("Experiment stop requested.")
                    break

                well_label = f"well_{i+1}"
                logger.info(f"Processing {well_label} at position {position}")

                # 1. Move to position
                motion_controller.move_absolute(x=position[0], y=position[1], z=position[2])

                # 2. Pre-laser delay
                time.sleep(self.params.get("pre_laser_delay", 0.5))

                # 3. Turn laser on
                gpio_controller.write_pin(laser_pin, True)
                time.sleep(self.params.get("laser_on_duration", 1.0))

                # 4. Start recording and wait
                video_filename = os.path.join(self.output_dir, f"{well_label}.avi")
                # This is a simplified recording logic. A real implementation would
                # use a threaded recorder to write frames from the camera.
                logger.info(f"Starting recording to {video_filename}")
                # camera.start_recording(video_filename)
                time.sleep(self.params.get("recording_duration", 5.0))
                # camera.stop_recording()
                logger.info("Finished recording.")

                # 5. Turn laser off
                gpio_controller.write_pin(laser_pin, False)

                # 6. Post-well delay
                time.sleep(self.params.get("post_well_delay", 0.5))

        except Exception as e:
            logger.error(f"An error occurred during the experiment: {e}")
        finally:
            # Ensure laser is off
            gpio_controller.write_pin(laser_pin, False)
            self.is_running = False
            logger.info("Experiment finished.")

    def stop(self):
        """Requests the experiment to stop gracefully."""
        self._stop_requested = True

    def _save_well_plate_csv(self):
        """Saves the well plate coordinates to a CSV file."""
        csv_path = os.path.join(self.output_dir, "well_plate_coordinates.csv")
        with open(csv_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["well_index", "x", "y", "z"])
            for i, pos in enumerate(self.well_plate.get_path()):
                writer.writerow([i+1, pos[0], pos[1], pos[2]])
        logger.info(f"Saved well plate coordinates to {csv_path}")
