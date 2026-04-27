"""
Experiment engine — executes a well-plate imaging sequence.

Modes
-----
Video Capture (default)
    Per-well sequence:
        1. Move to well
        2. Dwell (settle) — laser OFF, recording starts
        3. Laser ON for `video_laser_on` seconds — recording continues
        4. Laser OFF for `video_laser_off_post` seconds — recording continues
        5. Stop recording
        6. Post-well delay before moving to next well

Image Capture
    Per-well sequence:
        1. Move to well
        2. Dwell (settle)
        3. Capture single image
        4. Post-well delay

Scan patterns
-------------
Raster  — left-to-right every row
Snake   — alternating direction each row (passed to WellPlate)
"""
import os
import time
import subprocess
import csv
import threading
from datetime import datetime
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional

import cv2

from robocam_suite.hw_manager import HardwareManager
from robocam_suite.experiments.well_plate import WellPlate
from robocam_suite.logger import setup_logger

logger = setup_logger()

MODE_VIDEO = "Video Capture"
MODE_IMAGE = "Image Capture"


# ---------------------------------------------------------------------------
# Video recorder helper
# ---------------------------------------------------------------------------

class _WellRecorder:
    """Records video from the camera into a file in a background thread."""

    def __init__(self, camera, hw_manager, output_path: str, fps: float = 30.0, on_proxy_frame=None):
        self._camera = camera
        self._output_path = Path(output_path)
        self._hw_manager = hw_manager
        self._fps = fps
        self._on_proxy_frame = on_proxy_frame
        self._stop_event = threading.Event()
        self._frames_captured = 0
        self._start_time = None
        self._end_time = None
        self._actual_fps = 0.0
        self._laser_events = [] # list of (timestamp, state)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def log_laser_event(self, state: bool):
        """Log a laser state change event with current recording time."""
        if self._start_time:
            elapsed = time.time() - self._start_time
            self._laser_events.append({
                "time_offset": round(elapsed, 3),
                "state": "ON" if state else "OFF",
                "frame_index": self._frames_captured
            })

    def _run(self):
        # Always capture the first frame to determine dimensions and ensure the stream is active
        first_frame = None
        for _ in range(20): # Try up to 20 times (1 second total) to get a valid frame
            first_frame = self._camera.read_frame()
            if first_frame is not None:
                break
            time.sleep(0.05)

        if first_frame is None:
            logger.error("[WellRecorder] Could not read a frame — skipping recording.")
            return

        h, w = first_frame.shape[:2]
        
        # Use MJPG for compatibility and lower CPU overhead on RPi
        fourcc = cv2.VideoWriter_fourcc(*"MJPG")
        writer = cv2.VideoWriter(self._output_path, fourcc, self._fps, (w, h))

        if not writer.isOpened():
            logger.error(f"[WellRecorder] Could not open VideoWriter for {self._output_path}")
            return

        self._start_time = time.time()
        
        try:
            # Write the initial frame we just captured
            writer.write(first_frame)
            self._frames_captured += 1
            
            # Emit first proxy frame
            self._emit_proxy(first_frame)
            
            # Emit proxy frame every N frames to target ~1-2 FPS
            proxy_interval = max(1, int(self._fps / 2))
            
            while not self._stop_event.is_set():
                frame = self._camera.read_frame()
                if frame is not None:
                    # Emit proxy frame (for live preview) before any modifications
                    if self._frames_captured % proxy_interval == 0:
                        self._emit_proxy(frame)

                    writer.write(frame)
                    self._frames_captured += 1
                
                # Dynamic sleep to maintain target FPS
                elapsed = time.time() - self._start_time
                expected = self._frames_captured / self._fps
                sleep_time = max(0, expected - elapsed)
                if sleep_time > 0:
                    time.sleep(sleep_time)
                    
        except Exception as e:
            logger.error(f"[WellRecorder] Error during recording: {e}")
        finally:
            self._end_time = time.time()
            writer.release()
            duration = self._end_time - self._start_time
            self._actual_fps = self._frames_captured / duration if duration > 0 else 0.0
            self._save_metadata()
            logger.info(f"[WellRecorder] Saved {self._output_path} ({self._frames_captured} frames, actual FPS: {self._actual_fps:.2f})")
            self._post_process_video()

    def _emit_proxy(self, frame):
        """Convert BGR frame to QImage and call the proxy callback."""
        if self._on_proxy_frame is None:
            return
        try:
            import cv2
            from PySide6.QtGui import QImage
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb.shape
            qimg = QImage(
                rgb.data.tobytes(), w, h, ch * w,
                QImage.Format.Format_RGB888
            )
            self._on_proxy_frame(qimg.copy())
        except Exception as e:
            logger.debug(f"[_WellRecorder] Proxy emit error: {e}")

    def _save_metadata(self):
        """Save a JSON metadata file alongside the video."""
        meta_path = self._output_path.parent / (self._output_path.stem + "_metadata.json")
        duration = (self._end_time - self._start_time) if self._start_time and self._end_time else 0
        
        import json
        metadata = {
            "video_file": str(self._output_path.name),
            "frames_captured": self._frames_captured,
            "duration_seconds": round(self._end_time - self._start_time, 3),
            "fps_target": self._fps,
            "fps_actual": round(self._actual_fps, 2),
            "timestamp": datetime.now().isoformat(),
            "resolution": list(self._camera.get_resolution()),
            "laser_events": self._laser_events
        }
        
        try:
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2)
            logger.info(f"[WellRecorder] Metadata saved to {meta_path}")
        except Exception as e:
            logger.error(f"[WellRecorder] Failed to save metadata: {e}")

    def stop(self):
        self._stop_event.set()

    def _post_process_video(self):
        """
        Post-processes the video to:
        1. Add a visual '● LASER' indicator based on logged events.
        2. Adjust the file metadata to match the actual captured FPS.
        """
        if self._frames_captured == 0:
            return

        temp_output_path = self._output_path.with_name(f"temp_{self._output_path.name}")
        
        # 1. Build the ffmpeg filter for the laser indicator
        # We use 'drawtext' to show a red dot and 'LASER' text during ON intervals.
        # Intervals are [time_offset_on, time_offset_off].
        filter_parts = []
        on_start = None
        
        for event in self._laser_events:
            if event["state"] == "ON":
                on_start = event["time_offset"]
            elif event["state"] == "OFF" and on_start is not None:
                on_end = event["time_offset"]
                # Add a red circle and text
                # circle: \u25CF (UTF-8 circle)
                filter_parts.append(
                    f"drawtext=text='● LASER':fontcolor=red:fontsize=24:x=w-120:y=40:"
                    f"enable='between(t,{on_start},{on_end})'"
                )
                on_start = None
        
        # If still ON at the end of recording
        if on_start is not None:
            filter_parts.append(
                f"drawtext=text='● LASER':fontcolor=red:fontsize=24:x=w-120:y=40:"
                f"enable='gt(t,{on_start})'"
            )

        # 2. Build the command
        command = ["ffmpeg", "-y", "-i", str(self._output_path)]
        
        if filter_parts:
            # Join filters with commas
            video_filter = ",".join(filter_parts)
            command += ["-vf", video_filter]
        
        # Set the output FPS to the actual measured FPS
        fps_to_use = self._actual_fps if self._actual_fps > 0 else self._fps
        command += ["-r", str(fps_to_use)]
        
        # Re-encode to ensure filters are applied and FPS is baked in
        # We use libx264 for better compatibility if available, else mpeg4
        command += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23", str(temp_output_path)]

        logger.info(f"[WellRecorder] Post-processing {self._output_path} (FPS: {fps_to_use:.2f}, Laser filters: {len(filter_parts)})")
        
        try:
            result = subprocess.run(command, check=True, capture_output=True, text=True)
            os.replace(temp_output_path, self._output_path)
            logger.info(f"[WellRecorder] Post-processing complete for {self._output_path}")
        except subprocess.CalledProcessError as e:
            logger.error(f"[WellRecorder] ffmpeg failed: {e.stderr}")
            # If libx264 fails (e.g. not installed), try a simpler copy-based FPS fix if no filters
            if not filter_parts:
                self._fallback_fps_fix()
        except Exception as e:
            logger.error(f"[WellRecorder] Error during post-processing: {e}")

    def _fallback_fps_fix(self):
        """Simple FPS header fix without re-encoding."""
        temp_output_path = self._output_path.with_name(f"fallback_{self._output_path.name}")
        command = [
            "ffmpeg", "-y", "-i", str(self._output_path),
            "-r", str(self._actual_fps), "-c", "copy", str(temp_output_path)
        ]
        try:
            subprocess.run(command, check=True, capture_output=True)
            os.replace(temp_output_path, self._output_path)
            logger.info(f"[WellRecorder] Fallback FPS fix applied to {self._output_path}")
        except Exception as e:
            logger.error(f"[WellRecorder] Fallback FPS fix failed: {e}")


# ---------------------------------------------------------------------------
# Experiment engine
# ---------------------------------------------------------------------------

class Experiment:
    """Manages the execution of a well-plate experiment."""

    def __init__(
        self,
        hw_manager: HardwareManager,
        well_plate: WellPlate,
        params: Dict[str, Any],
        on_status=None,
        on_proxy_frame=None,
    ):
        self.hw_manager = hw_manager
        self.well_plate = well_plate
        self.params = params
        self.is_running = False
        self._stop_requested = False
        # on_status(msg: str) — optional callback for UI status updates
        self._on_status = on_status or (lambda msg: None)
        self._on_proxy_frame = on_proxy_frame
        self.output_dir = self._create_output_directory()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _create_output_directory(self) -> str:
        base = Path(self.params.get("output_dir", "")) or (
            Path.home() / "Documents" / "RoboCam" / "captures"
        )
        name = self.params.get("name", "experiment")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        full = base / f"{ts}_{name}"
        full.mkdir(parents=True, exist_ok=True)
        logger.info(f"[Experiment] Output directory: {full}")
        return str(full)

    # ------------------------------------------------------------------
    # Main run loop
    # ------------------------------------------------------------------

    def run(self):
        if self.is_running:
            logger.warning("[Experiment] Already running.")
            return

        self.is_running = True
        self._stop_requested = False
        mode = self.params.get("mode", MODE_VIDEO)
        pattern = self.params.get("pattern", WellPlate.PATTERN_RASTER)
        logger.info(
            f"[Experiment] Starting '{self.params.get('name', 'Untitled')}' "
            f"| mode={mode} | pattern={pattern}"
        )

        self._save_well_plate_csv()

        motion    = self.hw_manager.get_motion_controller()
        gpio      = self.hw_manager.get_gpio_controller()
        camera    = self.hw_manager.get_camera()

        laser_pin = (
            self.hw_manager._config.get_section("gpio_controller").get("laser_pin")
            or self.params.get("laser_pin", 21)
        )
        if not self.hw_manager.gpio_enabled:
            logger.info("[Experiment] GPIO disabled — laser commands silently ignored.")

        # Build the ordered well list respecting the selected subset
        full_labeled = self.well_plate.get_path_with_labels()
        selected  = self.params.get("selected_well_indices", None)
        if selected is not None:
            path_to_run = [(full_labeled[idx][0], full_labeled[idx][1])
                           for idx in selected if idx < len(full_labeled)]
        else:
            path_to_run = full_labeled
        logger.info(f"[Experiment] Visiting {len(path_to_run)} wells.")

        total = len(path_to_run)
        recorders = []
        try:
            for well_num, (well_id, position) in enumerate(path_to_run):
                if self._stop_requested:
                    logger.info("[Experiment] Stop requested — halting.")
                    self._on_status("Stopped.")
                    break

                well_label = f"well_{well_id}"
                move_msg = (
                    f"[{well_num + 1}/{total}] Moving to {well_id} — "
                    f"X:{position[0]:.2f} Y:{position[1]:.2f} Z:{position[2]:.2f}"
                )
                logger.info(move_msg)
                self._on_status(move_msg)

                motion.move_absolute(x=position[0], y=position[1], z=position[2])

                if mode == MODE_VIDEO:
                    recorder = self._run_video_well(well_label, camera, gpio, laser_pin, well_num + 1, total)
                    if recorder:
                        recorders.append((well_id, recorder))
                else:
                    self._run_image_well(well_label, camera, well_num + 1, total)

                time.sleep(float(self.params.get("post_well_delay", 0.0)))

            # Perform batch post-processing after all wells are recorded
            if recorders and not self._stop_requested:
                for i, (well_id, recorder) in enumerate(recorders):
                    self._on_status(f"Post-processing videos ({i+1}/{len(recorders)}): {well_id}…")
                    recorder._post_process_video()

        except Exception as e:
            logger.error(f"[Experiment] Error during run: {e}", exc_info=True)
            self._on_status(f"Error: {e}")
        finally:
            try:
                gpio.write_pin(laser_pin, False)
            except Exception:
                pass
            self.is_running = False
            logger.info("[Experiment] Finished.")
            self._on_status("Experiment finished.")

    # ------------------------------------------------------------------
    # Per-well handlers
    # ------------------------------------------------------------------

    def _sleep_check_stop(self, seconds: float):
        """Sleep for N seconds but check for stop requests every 100ms."""
        start = time.time()
        while time.time() - start < seconds:
            if self._stop_requested:
                raise InterruptedError("Stop requested")
            time.sleep(0.1)

    def _run_video_well(self, label: str, camera, gpio, laser_pin: int,
                         well_num: int = 0, total: int = 0):
        """
        Video capture sequence:
            dwell (laser OFF)  →  laser ON  →  laser OFF
            recording spans all three intervals.
        """
        dwell       = float(self.params.get("dwell",             0.5))
        off_pre     = float(self.params.get("video_laser_off_pre",  2.0))
        on_dur      = float(self.params.get("video_laser_on",       1.0))
        off_post    = float(self.params.get("video_laser_off_post", 2.0))
        gpio_enabled = self.hw_manager.gpio_enabled
        well_id = label.replace("well_", "")
        prefix = f"[{well_num}/{total}] " if total else ""

        video_path = os.path.join(self.output_dir, f"{label}.avi")
        recorder: Optional[_WellRecorder] = None

        try:
            # 1. Dwell — settle after move, laser off
            self._on_status(f"{prefix}Arrived at {well_id} — settling ({dwell:.1f}s)")
            self._sleep_check_stop(dwell)

            # 2. Start recording
            if camera.is_connected:
                self._on_status(f"{prefix}Recording {well_id} (laser off — {off_pre:.1f}s)")
                recorder = _WellRecorder(camera, self.hw_manager, video_path, on_proxy_frame=self._on_proxy_frame)
                logger.info(f"[Experiment] Recording → {video_path}")
            else:
                logger.warning("[Experiment] Camera not connected — skipping recording.")
                self._on_status(f"{prefix}Recording {well_id} — no camera")

            # 3. Pre-laser record (laser OFF)
            self._sleep_check_stop(off_pre)

            # 4. Laser ON
            if gpio_enabled:
                gpio.write_pin(laser_pin, True)
                if recorder:
                    recorder.log_laser_event(True)
                self._on_status(f"{prefix}Recording {well_id} (laser ON — {on_dur:.1f}s)")
            self._sleep_check_stop(on_dur)

            # 5. Laser OFF, post-laser record
            if gpio_enabled:
                gpio.write_pin(laser_pin, False)
                if recorder:
                    recorder.log_laser_event(False)
                self._on_status(f"{prefix}Recording {well_id} (laser off — {off_post:.1f}s)")
            self._sleep_check_stop(off_post)

        except InterruptedError:
            logger.info(f"[Experiment] Well {well_id} interrupted.")
        except Exception as e:
            logger.error(f"[Experiment] Error in well {well_id}: {e}")
        finally:
            try:
                gpio.write_pin(laser_pin, False)
            except Exception:
                pass
            if recorder:
                recorder.stop()
                recorder._thread.join(timeout=5.0)
                self._on_status(f"{prefix}Saved {well_id}.avi")
            
            return recorder

    def _run_image_well(self, label: str, camera,
                         well_num: int = 0, total: int = 0):
        """
        Capture a single frame at the current well position.
        """
        dwell = float(self.params.get("dwell", 0.5))
        well_id = label.replace("well_", "")
        prefix = f"[{well_num}/{total}] " if total else ""

        img_path = os.path.join(self.output_dir, f"{label}.jpg")

        try:
            # 1. Dwell — settle after move
            self._on_status(f"{prefix}Arrived at {well_id} — settling ({dwell:.1f}s)")
            self._sleep_check_stop(dwell)

            # 2. Capture
            if camera.is_connected:
                self._on_status(f"{prefix}Capturing {well_id}…")
                frame = camera.read_frame()
                if frame is not None:
                    cv2.imwrite(img_path, frame)
                    logger.info(f"[Experiment] Saved image → {img_path}")
                    self._on_status(f"{prefix}Saved {well_id}.jpg")
                else:
                    logger.error(f"[Experiment] Could not read frame for {well_id}")
                    self._on_status(f"{prefix}Capture failed for {well_id}")
            else:
                logger.warning("[Experiment] Camera not connected — skipping capture.")
                self._on_status(f"{prefix}Capture skipped for {well_id}")

        except InterruptedError:
            logger.info(f"[Experiment] Well {well_id} interrupted.")
        except Exception as e:
            logger.error(f"[Experiment] Error in well {well_id}: {e}")

    def _save_well_plate_csv(self):
        """Saves the well coordinates and metadata to a CSV in the output dir."""
        csv_path = os.path.join(self.output_dir, "well_plate_info.csv")
        try:
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["Well ID", "X", "Y", "Z"])
                for well_id, pos in self.well_plate.get_path_with_labels():
                    writer.writerow([well_id, f"{pos[0]:.3f}", f"{pos[1]:.3f}", f"{pos[2]:.3f}"])
            logger.info(f"[Experiment] Well plate CSV saved to {csv_path}")
        except Exception as e:
            logger.error(f"[Experiment] Failed to save CSV: {e}")

    def stop(self):
        """Request the experiment loop to stop."""
        self._stop_requested = True
