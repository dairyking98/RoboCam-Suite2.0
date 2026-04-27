import os
import time
import threading
import subprocess
import logging
from pathlib import Path
from datetime import datetime
import cv2

logger = logging.getLogger(__name__)

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
        self._frame_intervals = [] # list of ms between frames
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
        last_frame_time = self._start_time
        
        try:
            # Write the initial frame we just captured
            writer.write(first_frame)
            self._frames_captured += 1
            # First interval is 0
            self._frame_intervals.append(0.0)
            
            # Emit first proxy frame
            self._emit_proxy(first_frame)
            
            # Emit proxy frame every N frames to target ~1-2 FPS
            proxy_interval = max(1, int(self._fps / 2))
            
            while not self._stop_event.is_set():
                frame = self._camera.read_frame()
                if frame is not None:
                    now = time.time()
                    interval = (now - last_frame_time) * 1000.0 # ms
                    self._frame_intervals.append(round(interval, 2))
                    last_frame_time = now

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
        
        import json
        metadata = {
            "video_file": str(self._output_path.name),
            "frames_captured": self._frames_captured,
            "duration_seconds": round(self._end_time - self._start_time, 3),
            "fps_target": self._fps,
            "fps_actual": round(self._actual_fps, 2),
            "timestamp": datetime.now().isoformat(),
            "resolution": list(self._camera.get_resolution()),
            "laser_events": self._laser_events,
            "frame_intervals_ms": self._frame_intervals
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
        1. Implement True Timeline (VFR) by mapping frames to actual capture timestamps.
        2. Add a visual '● LASER' indicator based on frame indices.
        """
        if self._frames_captured == 0 or not self._frame_intervals:
            return

        temp_output_path = self._output_path.with_name(f"temp_{self._output_path.name}")
        
        try:
            # 1. Build the ffmpeg filters
            # We use 'drawtext' with 'between(n, start_frame, end_frame)' for frame-accurate laser indicator.
            filter_parts = []
            
            # Common font paths for RPi/Linux (FFmpeg needs an explicit font path if not configured)
            font_paths = [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
            ]
            font_path = next((p for p in font_paths if os.path.exists(p)), None)
            font_arg = f":fontfile='{font_path}'" if font_path else ""

            on_start_frame = None
            for event in self._laser_events:
                frame_idx = event.get("frame_index", 0)
                if event["state"] == "ON":
                    on_start_frame = frame_idx
                elif event["state"] == "OFF" and on_start_frame is not None:
                    on_end_frame = frame_idx
                    filter_parts.append(
                        f"drawtext=text='● LASER'{font_arg}:fontcolor=red:fontsize=32:x=w-150:y=50:"
                        f"enable='between(n,{on_start_frame},{on_end_frame})'"
                    )
                    on_start_frame = None
            
            if on_start_frame is not None:
                filter_parts.append(
                    f"drawtext=text='● LASER'{font_arg}:fontcolor=red:fontsize=32:x=w-150:y=50:"
                    f"enable='gt(n,{on_start_frame})'"
                )

            # 2. Build the command
            # We specify the average FPS to give ffmpeg a baseline, 
            # then use the visual filters to bake in the indicator.
            fps_to_use = self._actual_fps if self._actual_fps > 0 else self._fps
            
            command = [
                "ffmpeg", "-y",
                "-i", str(self._output_path),
            ]
            
            if filter_parts:
                command += ["-vf", ",".join(filter_parts)]
            
            # Use libx264 for high compatibility and quality
            command += [
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23",
                "-r", str(fps_to_use), # Sets constant output frame rate for simplicity in players
                str(temp_output_path)
            ]

            logger.info(f"[WellRecorder] Post-processing {self._output_path} (Avg FPS: {fps_to_use:.2f})")
            
            result = subprocess.run(command, check=True, capture_output=True, text=True)
            
            # The final file will be .mp4
            final_output_path = self._output_path.with_suffix(".mp4")
            os.replace(temp_output_path, final_output_path)
            
            # Remove the original .avi to save space
            if os.path.exists(self._output_path):
                os.remove(self._output_path)
                
            logger.info(f"[WellRecorder] Post-processing complete: {final_output_path}")
            
        except Exception as e:
            logger.error(f"[WellRecorder] Post-processing failed: {e}")
            if 'result' in locals():
                logger.error(f"FFmpeg output: {result.stderr}")

class Experiment(threading.Thread):
    """Handles the execution of a multi-well experiment."""
    
    def __init__(self, params: dict, on_status=None, on_progress=None, on_frame=None):
        super().__init__(daemon=True)
        self.params = params
        self._on_status = on_status or (lambda x: None)
        self._on_progress = on_progress or (lambda x, y: None)
        self._on_frame = on_frame or (lambda x: None)
        self._stop_requested = False
        
    def stop(self):
        self._stop_requested = True
        
    def run(self):
        try:
            self._on_status("Starting experiment...")
            
            output_dir = Path(self.params.get("output_dir", "captures"))
            output_dir.mkdir(parents=True, exist_ok=True)
            
            wells = self.params.get("wells", [])
            total_wells = len(wells)
            recorders = []
            
            for i, well_id in enumerate(wells):
                if self._stop_requested:
                    break
                    
                self._on_progress(i, total_wells)
                self._on_status(f"Moving to well {well_id} ({i+1}/{total_wells})...")
                
                # Move to well
                well_pos = self.params.get("well_positions", {}).get(well_id)
                if well_pos:
                    hw_manager.motion.move_to(well_pos['x'], well_pos['y'], well_pos['z'], wait=True)
                
                # Dwell
                dwell = float(self.params.get("dwell", 0.5))
                if dwell > 0:
                    time.sleep(dwell)
                
                # Record
                if self.params.get("mode") == "Video":
                    recorder = self._run_video_well(well_id, output_dir)
                    if recorder:
                        recorders.append((well_id, recorder))
                else:
                    self._run_image_well(well_id, output_dir)
            
            # Batch post-processing
            if recorders and not self._stop_requested:
                should_post_process = self.params.get("post_process", True)
                if should_post_process:
                    for i, (well_id, recorder) in enumerate(recorders):
                        self._on_status(f"Post-processing videos ({i+1}/{len(recorders)}): {well_id}...")
                        recorder._post_process_video()
            
            self._on_progress(total_wells, total_wells)
            self._on_status("Experiment complete.")
            
        except Exception as e:
            logger.error(f"Experiment error: {e}", exc_info=True)
            self._on_status(f"Error: {e}")
            
    def _run_video_well(self, well_id, output_dir):
        well_path = output_dir / f"{well_id}.avi"
        fps = float(self.params.get("video_fps", 30.0))
        
        recorder = _WellRecorder(
            hw_manager.camera, hw_manager, str(well_path), 
            fps=fps, on_proxy_frame=self._on_frame
        )
        
        # Pre-laser
        pre_time = float(self.params.get("video_laser_off_pre", 2.0))
        time.sleep(pre_time)
        
        # Laser ON
        on_time = float(self.params.get("video_laser_on", 1.0))
        hw_manager.gpio.set_laser(True)
        recorder.log_laser_event(True)
        time.sleep(on_time)
        
        # Laser OFF
        hw_manager.gpio.set_laser(False)
        recorder.log_laser_event(False)
        
        # Post-laser
        post_time = float(self.params.get("video_laser_off_post", 2.0))
        time.sleep(post_time)
        
        recorder.stop()
        return recorder

    def _run_image_well(self, well_id, output_dir):
        # Implementation for image capture mode
        pass
