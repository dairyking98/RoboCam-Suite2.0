"""
Experiment engine — executes a well-plate imaging sequence.

Supports:
- Running on a subset of wells (selected_well_indices from ExperimentPanel).
- Threaded video recording per well using OpenCV VideoWriter.
- Graceful stop at the end of the current well.
"""
import os
import time
import csv
import threading
from datetime import datetime
from typing import List, Tuple, Dict, Any, Optional

import cv2

from robocam_suite.hw_manager import HardwareManager
from robocam_suite.experiments.well_plate import WellPlate
from robocam_suite.logger import setup_logger

logger = setup_logger()


class _WellRecorder:
    """
    Records video from the camera into a file in a background thread.
    Starts immediately on construction; call stop() to finish.
    """

    def __init__(self, camera, output_path: str, fps: float = 30.0):
        self._camera = camera
        self._output_path = output_path
        self._fps = fps
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        # Grab one frame to determine resolution
        first_frame = None
        for _ in range(10):
            first_frame = self._camera.read_frame()
            if first_frame is not None:
                break
            time.sleep(0.05)

        if first_frame is None:
            logger.error("[WellRecorder] Could not read a frame — skipping recording.")
            return

        h, w = first_frame.shape[:2]
        fourcc = cv2.VideoWriter_fourcc(*"MJPG")
        writer = cv2.VideoWriter(self._output_path, fourcc, self._fps, (w, h))

        if not writer.isOpened():
            logger.error(f"[WellRecorder] Could not open VideoWriter for {self._output_path}")
            return

        writer.write(first_frame)
        try:
            while not self._stop_event.is_set():
                frame = self._camera.read_frame()
                if frame is not None:
                    writer.write(frame)
                else:
                    time.sleep(1.0 / self._fps)
        finally:
            writer.release()
            logger.info(f"[WellRecorder] Saved {self._output_path}")

    def stop(self):
        self._stop_event.set()
        self._thread.join(timeout=5.0)


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

        # Determine which wells to visit
        full_path = self.well_plate.get_path()
        selected_indices = self.params.get("selected_well_indices", None)
        if selected_indices is not None:
            path_to_run = [(idx, full_path[idx]) for idx in selected_indices if idx < len(full_path)]
            logger.info(
                f"Running on {len(path_to_run)} of {len(full_path)} wells (subset selected)."
            )
        else:
            path_to_run = list(enumerate(full_path))
            logger.info(f"Running on all {len(path_to_run)} wells.")

        try:
            for well_num, (path_idx, position) in enumerate(path_to_run):
                if self._stop_requested:
                    logger.info("Experiment stop requested.")
                    break

                well_label = f"well_{path_idx + 1}"
                logger.info(
                    f"[{well_num + 1}/{len(path_to_run)}] {well_label} → "
                    f"X:{position[0]:.2f} Y:{position[1]:.2f} Z:{position[2]:.2f}"
                )

                # 1. Move to well position
                motion_controller.move_absolute(
                    x=position[0], y=position[1], z=position[2]
                )

                # 2. Pre-laser settle delay
                time.sleep(self.params.get("pre_laser_delay", 0.5))

                # 3. Start video recording
                video_filename = os.path.join(self.output_dir, f"{well_label}.avi")
                recorder: Optional[_WellRecorder] = None
                if camera.is_connected:
                    recorder = _WellRecorder(camera, video_filename)
                    logger.info(f"Recording started → {video_filename}")
                else:
                    logger.warning("[Experiment] Camera not connected — skipping recording.")

                # 4. Turn laser on
                gpio_controller.write_pin(laser_pin, True)
                time.sleep(self.params.get("laser_on_duration", 1.0))

                # 5. Wait for the rest of the recording duration
                remaining = self.params.get("recording_duration", 5.0) - \
                            self.params.get("laser_on_duration", 1.0)
                if remaining > 0:
                    time.sleep(remaining)

                # 6. Turn laser off and stop recording
                gpio_controller.write_pin(laser_pin, False)
                if recorder:
                    recorder.stop()
                    logger.info(f"Recording finished → {video_filename}")

                # 7. Post-well delay
                time.sleep(self.params.get("post_well_delay", 0.5))

        except Exception as e:
            logger.error(f"An error occurred during the experiment: {e}", exc_info=True)
        finally:
            # Ensure laser is always off when we exit
            try:
                gpio_controller.write_pin(laser_pin, False)
            except Exception:
                pass
            self.is_running = False
            logger.info("Experiment finished.")

    def stop(self):
        """Requests the experiment to stop gracefully after the current well."""
        self._stop_requested = True

    def _save_well_plate_csv(self):
        """Saves the full well plate coordinates to a CSV file."""
        csv_path = os.path.join(self.output_dir, "well_plate_coordinates.csv")
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["well_index", "x", "y", "z"])
            for i, pos in enumerate(self.well_plate.get_path()):
                writer.writerow([i + 1, pos[0], pos[1], pos[2]])
        logger.info(f"Saved well plate coordinates to {csv_path}")
