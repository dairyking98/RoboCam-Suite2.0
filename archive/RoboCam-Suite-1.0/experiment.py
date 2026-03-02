"""
Experiment Automation Application - Automated Well-Plate Experiment Execution

Provides a GUI for configuring and running automated well-plate experiments with:
- Configurable well positions and patterns
- Automated video/still capture at each well
- Laser control with timing sequences (OFF-ON-OFF)
- Motion configuration (feedrate and acceleration)
- CSV export of well coordinates

Author: RoboCam-Suite
"""

import os
import json
import threading
import time
import re
import csv
import subprocess
import glob
import tkinter as tk
from tkinter import filedialog
from datetime import datetime
from typing import Optional, Dict, List, Tuple, Any
from picamera2 import Picamera2
from picamera2.encoders import H264Encoder
from picamera2.outputs import FileOutput
from robocam.camera_backend import detect_camera
from robocam.robocam_ccc import RoboCam
from robocam.playerone_camera import PlayerOneCamera
from robocam.laser import Laser
from robocam.config import get_config
from robocam.logging_config import get_logger
from robocam.capture_interface import CaptureManager
from robocam.resolution_aspect import get_default_resolution_for_camera
from robocam.resolution_presets import (
    get_capture_resolution_presets,
    format_resolution_option,
    resolution_to_preset_option,
    parse_resolution_option,
)

logger = get_logger(__name__)

# Configuration constants
# CSV files are now named with format: {date}_{time}_{exp}_points.csv
EXPERIMENTS_FOLDER: str = "experiments"  # For exported experiment settings (profile JSON files)
OUTPUTS_FOLDER: str = "outputs"  # Base folder for experiment outputs
# Output folder structure: outputs/YYYYMMDD_{experiment_name}/ contains recordings and CSV
DEFAULT_RES: tuple[int, int] = (1920, 1080)
DEFAULT_FPS: float = 30.0
DEFAULT_EXPORT: str = "H264"


def ensure_directory_exists(folder_path: str) -> tuple[bool, str]:
    """
    Ensure a directory path exists, creating all intermediate directories if needed.
    
    Args:
        folder_path: Full path to the directory to create
        
    Returns:
        Tuple of (success: bool, error_message: str)
        If success is False, error_message contains a helpful error description
    """
    try:
        os.makedirs(folder_path, exist_ok=True)
        # Verify we can actually write to the directory
        test_file = os.path.join(folder_path, ".write_test")
        try:
            with open(test_file, 'w') as f:
                f.write("test")
            os.remove(test_file)
        except (PermissionError, OSError):
            return False, f"Directory '{folder_path}' exists but is not writable. Please check permissions."
        return True, ""
    except PermissionError:
        # Check which level failed
        path_parts = folder_path.strip('/').split('/')
        checked_path = '/'
        for part in path_parts:
            checked_path = os.path.join(checked_path, part)
            if not os.path.exists(checked_path):
                error_msg = f"Permission denied: Cannot create '{checked_path}'. "
                error_msg += f"Please create the directory structure manually or run with sudo:\n"
                error_msg += f"  sudo mkdir -p {folder_path} && sudo chmod 777 {folder_path}"
                return False, error_msg
            elif not os.access(checked_path, os.W_OK):
                error_msg = f"Permission denied: '{checked_path}' exists but is not writable. "
                error_msg += f"Please fix permissions with: sudo chmod 777 {checked_path}"
                return False, error_msg
        return False, f"Permission denied: Cannot create '{folder_path}'. Please check permissions."
    except OSError as e:
        return False, f"Error creating directory '{folder_path}': {e}. Please check permissions."


def format_hms(seconds: float) -> str:
    """
    Format seconds as HH:MM:SS string.
    
    Args:
        seconds: Time in seconds
        
    Returns:
        Formatted time string (e.g., "01:23:45")
    """
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def save_video_metadata(
    video_path: str,
    target_fps: float,
    resolution: Tuple[int, int],
    duration_seconds: float,
    format_type: str,
    well_label: str,
    timestamp: str,
    actual_fps: Optional[float] = None,
    actual_duration: Optional[float] = None
) -> None:
    """
    Save FPS and recording metadata to a JSON file alongside the video.
    
    This metadata is critical for accurate playback timing, especially for
    scientific velocity measurements.
    
    Args:
        video_path: Path to the video file
        target_fps: Target frames per second for recording
        resolution: Video resolution as (width, height)
        duration_seconds: Expected recording duration in seconds
        format_type: Video format ("H264")
        well_label: Well identifier (e.g., "A1")
        timestamp: Recording timestamp string
        actual_fps: Actual FPS achieved (calculated from actual duration if not provided)
        actual_duration: Actual recording duration in seconds (used to calculate actual_fps if provided)
    """
    try:
        # Create metadata filename by replacing video extension with _metadata.json
        base_path = os.path.splitext(video_path)[0]
        metadata_path = f"{base_path}_metadata.json"
        
        # Calculate actual FPS if actual_duration is provided but actual_fps is not
        if actual_duration is not None and actual_fps is None:
            # Calculate actual FPS based on expected frame count and actual duration
            expected_frame_count = target_fps * duration_seconds
            if actual_duration > 0:
                actual_fps = expected_frame_count / actual_duration
            else:
                actual_fps = target_fps  # Fallback to target if duration is invalid
        
        # Use target FPS as actual if actual not provided
        if actual_fps is None:
            actual_fps = target_fps
        
        metadata = {
            "target_fps": target_fps,
            "fps": actual_fps,  # Keep "fps" for backward compatibility, but it's now the actual FPS
            "actual_fps": actual_fps,
            "resolution": list(resolution),
            "duration_seconds": duration_seconds,
            "actual_duration_seconds": actual_duration if actual_duration is not None else duration_seconds,
            "format": format_type,
            "timestamp": timestamp,
            "well_label": well_label,
            "video_file": os.path.basename(video_path)
        }
        
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)
        
        logger.info(f"Saved video metadata: {metadata_path} (Target FPS: {target_fps}, Actual FPS: {actual_fps:.2f}, Duration: {duration_seconds}s)")
    except Exception as e:
        logger.error(f"Failed to save video metadata for {video_path}: {e}")


def convert_h264_to_mp4(h264_path: str, metadata_path: Optional[str] = None, fps: Optional[float] = None) -> bool:
    """
    Convert H264 file to MP4 using ffmpeg with accurate FPS from JSON metadata.
    
    Args:
        h264_path: Path to the input H264 file
        metadata_path: Optional path to JSON metadata file containing FPS information
        fps: Optional FPS value to use directly (overrides metadata if provided)
        
    Returns:
        True if conversion succeeded, False otherwise
    """
    try:
        if not os.path.exists(h264_path):
            logger.error(f"H264 file not found: {h264_path}")
            return False
        
        # Get FPS from metadata JSON if available
        actual_fps = fps
        if actual_fps is None and metadata_path and os.path.exists(metadata_path):
            try:
                with open(metadata_path, 'r') as f:
                    metadata = json.load(f)
                    # Try to get actual_fps first, then fps, then target_fps
                    actual_fps = metadata.get('actual_fps') or metadata.get('fps') or metadata.get('target_fps')
                    if actual_fps:
                        logger.info(f"Using FPS from metadata: {actual_fps}")
            except Exception as e:
                logger.warning(f"Failed to read FPS from metadata file {metadata_path}: {e}")
        
        # Generate MP4 output path
        mp4_path = os.path.splitext(h264_path)[0] + ".mp4"
        
        # Build ffmpeg command
        # Use -c copy to avoid re-encoding (fast, no quality loss)
        # The MP4 container format will provide proper metadata for accurate duration display
        # FPS information from metadata is logged but frame rate is already in H264 stream
        cmd = ["ffmpeg", "-y", "-i", h264_path, "-c", "copy", mp4_path]
        
        # Note: If explicit FPS metadata is needed in MP4, we could use:
        # cmd = ["ffmpeg", "-y", "-r", str(actual_fps), "-i", h264_path, "-c:v", "libx264", "-r", str(actual_fps), mp4_path]
        # But that would re-encode. For now, stream copy preserves existing FPS and creates proper container.
        
        logger.info(f"Converting H264 to MP4: {h264_path} -> {mp4_path}" + (f" (FPS: {actual_fps})" if actual_fps else ""))
        
        # Run ffmpeg
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=300  # 5 minute timeout per file
        )
        
        if result.returncode == 0:
            if os.path.exists(mp4_path):
                logger.info(f"Successfully converted to MP4: {mp4_path}")
                return True
            else:
                logger.error(f"Conversion reported success but MP4 file not found: {mp4_path}")
                return False
        else:
            logger.error(f"ffmpeg conversion failed for {h264_path}: {result.stderr}")
            return False
            
    except subprocess.TimeoutExpired:
        logger.error(f"Conversion timed out for {h264_path}")
        return False
    except Exception as e:
        logger.error(f"Error converting {h264_path} to MP4: {e}")
        return False


def convert_all_h264_in_folder(folder_path: str) -> Tuple[int, int]:
    """
    Convert all H264 files in a folder to MP4 using their metadata JSON files for accurate FPS.
    
    Args:
        folder_path: Path to folder containing H264 files
        
    Returns:
        Tuple of (success_count, total_count)
    """
    if not os.path.exists(folder_path):
        logger.error(f"Folder does not exist: {folder_path}")
        return (0, 0)
    
    # Find all H264 files
    h264_files = glob.glob(os.path.join(folder_path, "*.h264"))
    
    if not h264_files:
        logger.info(f"No H264 files found in {folder_path}")
        return (0, 0)
    
    logger.info(f"Found {len(h264_files)} H264 file(s) to convert in {folder_path}")
    
    success_count = 0
    for h264_path in h264_files:
        # Look for corresponding metadata JSON file
        base_path = os.path.splitext(h264_path)[0]
        metadata_path = f"{base_path}_metadata.json"
        
        if os.path.exists(metadata_path):
            if convert_h264_to_mp4(h264_path, metadata_path=metadata_path):
                success_count += 1
        else:
            # Try conversion without metadata (ffmpeg will use default FPS)
            logger.warning(f"No metadata file found for {h264_path}, converting without FPS info")
            if convert_h264_to_mp4(h264_path):
                success_count += 1
    
    logger.info(f"Conversion complete: {success_count}/{len(h264_files)} files converted successfully")
    return (success_count, len(h264_files))


class ExperimentWindow:
    """
    Experiment automation window for configuring and running well-plate experiments.
    
    Provides GUI for:
    - Configuring well positions (X, Y coordinates and labels)
    - Setting adjustable GPIO action phases (customizable ON/OFF sequences with durations)
    - Camera settings (resolution, FPS, export type)
    - Motion settings (feedrate, motion configuration)
    - File naming and save location
    - Running, pausing, and stopping experiments
    
    Attributes:
        parent (tk.Tk): Parent tkinter window
        picam2 (Picamera2): Camera instance
        robocam (RoboCam): Printer control instance
        laser (Laser): Laser control instance
        window (Optional[tk.Toplevel]): Experiment configuration window
        thread (Optional[threading.Thread]): Experiment execution thread
        running (bool): Experiment running state
        paused (bool): Experiment paused state
        start_ts (float): Experiment start timestamp
        total_time (float): Total experiment duration in seconds
        feedrate (float): Movement speed in mm/min
        laser_on (bool): Laser ON state
        recording (bool): Video recording state
        seq (List[Tuple]): Well sequence list
        z_val (float): Z coordinate (focus height)
    """
    
    def __init__(self, parent: tk.Tk, picam2: Optional[Picamera2], robocam: RoboCam,
                 usb_camera=None, simulate_3d: bool = False, simulate_cam: bool = False) -> None:
        """
        Initialize experiment window.

        Args:
            parent: Parent tkinter window
            picam2: Picamera2 instance (Pi HQ); None if using Player One or simulate_cam
            robocam: RoboCam instance for printer control
            usb_camera: PlayerOneCamera instance when Player One camera is used (e.g. Mars 662M)
            simulate_3d: If True, run in 3D printer simulation mode (for display purposes)
            simulate_cam: If True, run in camera simulation mode (no camera operations)
        """
        self.parent: tk.Tk = parent
        self.picam2: Optional[Picamera2] = picam2
        self.usb_camera = usb_camera
        self.robocam: RoboCam = robocam
        self.simulate_3d: bool = simulate_3d
        self.simulate_cam: bool = simulate_cam
        # Load config for laser GPIO pin and camera settings
        config = get_config()
        laser_pin = config.get("hardware.laser.gpio_pin", 21)
        self.laser: Laser = Laser(laser_pin, config)
        self.pre_recording_delay = config.get("hardware.camera.pre_recording_delay", 0.5)
        self.window: Optional[tk.Toplevel] = None
        self.thread: Optional[threading.Thread] = None
        self.running: bool = False
        self.paused: bool = False
        self.start_ts: float = 0.0
        self.total_time: float = 0.0
        self.feedrate: float = 100.0
        self.laser_on: bool = False
        self.recording: bool = False
        self.seq: List[Tuple[float, float, str, str]] = []
        self.z_val: float = 0.0
        self.recording_flash_state: bool = False
        self.recording_flash_job: Optional[str] = None
        # Motion configuration
        self.motion_config: Optional[Dict[str, Any]] = None
        self.preliminary_feedrate: float = 3000.0
        self.preliminary_acceleration: float = 500.0
        self.between_wells_feedrate: float = 5000.0
        self.between_wells_acceleration: float = 1000.0
        # Calibration data
        self.loaded_calibration: Optional[Dict[str, Any]] = None
        self.calibration_file: Optional[str] = None
        self.well_checkboxes: Dict[str, tk.BooleanVar] = {}
        self.checkbox_frame: Optional[tk.Frame] = None
        self.checkbox_widgets: Dict[str, tk.Checkbutton] = {}
        self.label_to_row_col: Dict[str, Tuple[int, int]] = {}
        self.checkbox_window: Optional[tk.Toplevel] = None
        self.select_cells_btn: Optional[tk.Button] = None
        self.window_size_locked: bool = False  # Flag to prevent automatic resizing after initial setup


    def save_csv(self) -> None:
        """
        Save well sequence to CSV file.
        
        Creates CSV file with columns: xlabel, ylabel, xval, yval, zval.
        Saves to outputs/YYYYMMDD_{experiment_name}/ with format: {date}_{time}_{exp}_points.csv
        
        Note:
            Only saves if sequence exists. Creates folder if it doesn't exist.
        """
        if not self.seq:
            return
        
        # Get experiment name and create output folder with date prefix
        experiment_name = self.experiment_name_ent.get().strip() or "exp"
        date_str = datetime.now().strftime("%Y%m%d")
        output_folder = os.path.join(OUTPUTS_FOLDER, f"{date_str}_{experiment_name}")
        
        success, error_msg = ensure_directory_exists(output_folder)
        if not success:
            logger.error(error_msg)
            if hasattr(self, 'status_lbl'):
                self.status_lbl.config(text=error_msg, fg="red")
            return
        
        # Generate filename with date, time, and experiment name
        date_time_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_filename = f"{date_time_str}_{experiment_name}_points.csv"
        csv_path: str = os.path.join(output_folder, csv_filename)
        
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["xlabel", "ylabel", "xval", "yval", "zval"])
            for x_val, y_val, x_lbl, y_lbl in self.seq:
                writer.writerow([x_lbl, y_lbl, x_val, y_val, self.z_val])
        self.status_lbl.config(text=f"CSV saved: {os.path.basename(csv_path)}")

    def open(self) -> None:
        """
        Open experiment configuration window.
        
        Creates or raises the experiment configuration window with all
        settings fields. Loads saved configuration if available.
        If called from __main__, uses the root window directly.
        """
        # If window already exists, just raise it
        if self.window and self.window.winfo_exists():
            self.window.lift()
            return

        # Use root window directly if this is the main window (no existing window and parent is empty)
        # Otherwise create a Toplevel for embedded use
        if (self.window is None and isinstance(self.parent, tk.Tk) and 
            len(self.parent.winfo_children()) == 0):
            w = self.parent
            title = "Experiment"
            sim_text = []
            if self.simulate_3d:
                sim_text.append("3D PRINTER SIM")
            if self.simulate_cam:
                sim_text.append("CAMERA SIM")
            if sim_text:
                title += f" [{' + '.join(sim_text)}]"
            w.title(title)
            self.window = w
        else:
            w = tk.Toplevel(self.parent)
            title = "Experiment"
            sim_text = []
            if self.simulate_3d:
                sim_text.append("3D PRINTER SIM")
            if self.simulate_cam:
                sim_text.append("CAMERA SIM")
            if sim_text:
                title += f" [{' + '.join(sim_text)}]"
            w.title(title)
            self.window = w

        def on_close():
            self.stop()
            self.save_csv()
            # Close checkbox window if open
            if self.checkbox_window and self.checkbox_window.winfo_exists():
                self.checkbox_window.destroy()
                self.checkbox_window = None
            if isinstance(w, tk.Toplevel):
                w.destroy()
                self.window = None
            else:
                # If using root window, quit the application
                self.parent.quit()
        w.protocol("WM_DELETE_WINDOW", on_close)

        # Set initial window width - height will be calculated after content is created
        INITIAL_WIDTH = 700
        w.geometry(f"{INITIAL_WIDTH}x400")  # Temporary height, will be updated
        w.minsize(600, 400)  # Minimum size to ensure usability
        w.resizable(True, True)  # Allow user to resize manually

        # Use window directly as container (no scrolling needed - window will size to fit)
        container = w

        # === SECTION 1: CALIBRATION ===
        calib_frame = tk.LabelFrame(container, text="Calibration", padx=5, pady=5)
        calib_frame.grid(row=0, column=0, columnspan=4, sticky="ew", padx=5, pady=5)
        calib_frame.grid_columnconfigure(1, weight=1)
        
        tk.Label(calib_frame, text="File:").grid(row=0, column=0, sticky="w", padx=2, pady=2)
        self.calibration_var = tk.StringVar(value="")
        calibration_frame = tk.Frame(calib_frame)
        calibration_frame.grid(row=0, column=1, columnspan=3, sticky="ew", padx=2, pady=2)
        
        calib_dir = "calibrations"
        calibrations = [""]
        if os.path.exists(calib_dir):
            calibrations.extend([f for f in os.listdir(calib_dir) if f.endswith(".json")])
        
        calibration_menu = tk.OptionMenu(calibration_frame, self.calibration_var, *calibrations, command=self.on_calibration_select)
        calibration_menu.pack(side=tk.LEFT, padx=2)
        
        tk.Button(calibration_frame, text="Refresh", command=self.refresh_calibrations).pack(side=tk.LEFT, padx=2)
        self.select_cells_btn = tk.Button(calibration_frame, text="Select Cells", command=self.open_checkbox_window, state="disabled")
        self.select_cells_btn.pack(side=tk.LEFT, padx=2)
        
        # Status label below the selection row
        self.calibration_status_label = tk.Label(calib_frame, text="No calibration loaded", fg="red", font=("Arial", 9), anchor="w")
        self.calibration_status_label.grid(row=1, column=0, columnspan=4, sticky="ew", padx=2, pady=2)

        # === SECTION 2: MODE SELECTOR ===
        mode_frame = tk.LabelFrame(container, text="Mode", padx=5, pady=5)
        mode_frame.grid(row=1, column=0, columnspan=4, sticky="ew", padx=5, pady=5)
        mode_frame.grid_columnconfigure(1, weight=1)
        
        tk.Label(mode_frame, text="Capture Mode:").grid(row=0, column=0, sticky="w", padx=2, pady=2)
        self.capture_mode_var = tk.StringVar(value="Video Capture")
        mode_menu = tk.OptionMenu(mode_frame, self.capture_mode_var, "Video Capture", "Image Capture", command=self.on_mode_change)
        mode_menu.grid(row=0, column=1, sticky="w", padx=2, pady=2)
        
        # Mode description label
        self.mode_description_label = tk.Label(
            mode_frame, 
            text="Video Capture: Records video with GPIO control during action phases", 
            fg="gray", 
            font=("Arial", 9), 
            anchor="w",
            wraplength=500
        )
        self.mode_description_label.grid(row=1, column=0, columnspan=4, sticky="ew", padx=2, pady=2)

        # === SECTION 3: ACTION PHASES ===
        phases_frame = tk.LabelFrame(container, text="Action Phases", padx=5, pady=5)
        phases_frame.grid(row=2, column=0, columnspan=4, sticky="ew", padx=5, pady=5)
        
        # Scrollable phases container
        phases_container = tk.Frame(phases_frame)
        phases_container.grid(row=0, column=0, columnspan=3, sticky="ew", padx=2, pady=2)
        
        self.phases_canvas = tk.Canvas(phases_container, height=90, highlightthickness=0)
        phases_scrollbar = tk.Scrollbar(phases_container, orient="vertical", command=self.phases_canvas.yview)
        self.action_phases_frame = tk.Frame(self.phases_canvas)
        
        def update_phases_scroll(event=None):
            self.phases_canvas.configure(scrollregion=self.phases_canvas.bbox("all"))
        
        self.action_phases_frame.bind("<Configure>", update_phases_scroll)
        self.phases_canvas.create_window((0, 0), window=self.action_phases_frame, anchor="nw")
        self.phases_canvas.configure(yscrollcommand=phases_scrollbar.set)
        
        self.phases_canvas.pack(side="left", fill="both", expand=True)
        phases_scrollbar.pack(side="right", fill="y")
        
        tk.Button(phases_frame, text="Add Action", command=self.add_action_phase).grid(row=0, column=3, padx=2, pady=2, sticky="n")
        
        self.action_phases = []
        self.add_action_phase("GPIO OFF", 30.0)  # Default: 30 seconds for Video Capture mode

        # === SECTION 4: CAMERA SETTINGS ===
        camera_frame = tk.LabelFrame(container, text="Camera Settings", padx=5, pady=5)
        camera_frame.grid(row=3, column=0, columnspan=4, sticky="ew", padx=5, pady=5)
        camera_frame.grid_columnconfigure(1, weight=1)
        camera_frame.grid_columnconfigure(3, weight=1)
        
        row = 0
        tk.Label(camera_frame, text="Pattern:").grid(row=row, column=0, sticky="w", padx=2, pady=2)
        self.pattern_var = tk.StringVar(value="raster →↓")
        tk.OptionMenu(camera_frame, self.pattern_var, "snake →↙", "raster →↓").grid(row=row, column=1, sticky="w", padx=2, pady=2)
        
        tk.Label(camera_frame, text="Experiment Name:").grid(row=row, column=2, sticky="w", padx=2, pady=2)
        self.experiment_name_ent = tk.Entry(camera_frame, width=20)
        self.experiment_name_ent.insert(0, "exp")
        self.experiment_name_ent.grid(row=row, column=3, sticky="ew", padx=2, pady=2)
        
        row += 1
        # Resolution: native presets only (no custom)
        is_pihq = self.usb_camera is None
        is_playerone = self.usb_camera is not None and type(self.usb_camera).__name__ == "PlayerOneCamera"
        self._resolution_presets = get_capture_resolution_presets(is_pihq, is_playerone)
        default_res = get_default_resolution_for_camera(is_pihq=is_pihq)
        initial_opt = resolution_to_preset_option(default_res, self._resolution_presets)
        self.resolution_var = tk.StringVar(value=initial_opt)
        tk.Label(camera_frame, text="Resolution:").grid(row=row, column=0, sticky="w", padx=2, pady=2)
        resolution_menu = tk.OptionMenu(
            camera_frame, self.resolution_var,
            *[format_resolution_option(w, h) for w, h in self._resolution_presets]
        )
        resolution_menu.grid(row=row, column=1, columnspan=2, sticky="w", padx=2, pady=2)
        
        row += 1
        tk.Label(camera_frame, text="Target FPS:").grid(row=row, column=0, sticky="w", padx=2, pady=2)
        self.fps_ent = tk.Entry(camera_frame, width=12)
        self.fps_ent.grid(row=row, column=1, sticky="w", padx=2, pady=2)
        self.fps_ent.insert(0, str(DEFAULT_FPS))
        
        tk.Label(camera_frame, text="Export Type:").grid(row=row, column=2, sticky="w", padx=2, pady=2)
        self.export_var = tk.StringVar(value=DEFAULT_EXPORT)
        # Create export type menu - will be updated based on capture mode
        export_menu_frame = tk.Frame(camera_frame)
        export_menu_frame.grid(row=row, column=3, sticky="w", padx=2, pady=2)
        self.export_menu = tk.OptionMenu(export_menu_frame, self.export_var, "H264")
        self.export_menu.pack(side=tk.LEFT)
        # Note: Command callback will be added in _update_export_type_options()
        self.export_menu_frame = export_menu_frame  # Store frame for later updates
        
        # Checkbox for MP4 conversion (only shown for Video Capture mode with H264)
        self.convert_to_mp4_var = tk.BooleanVar(value=True)  # Default ON
        self.convert_to_mp4_checkbox = tk.Checkbutton(
            camera_frame, 
            text="Convert to MP4 after experiment",
            variable=self.convert_to_mp4_var
        )
        self.convert_to_mp4_checkbox.grid(row=row, column=4, sticky="w", padx=2, pady=2)
        
        row += 1
        tk.Label(camera_frame, text="Capture Type:").grid(row=row, column=0, sticky="w", padx=2, pady=2)
        # Show Player One types when that backend is in use
        if self.usb_camera is not None:
            capture_types = CaptureManager.CAPTURE_TYPES_PLAYERONE
            default_capture = "Player One (Grayscale)"
        else:
            capture_types = CaptureManager.CAPTURE_TYPES
            default_capture = "Picamera2 (Color)"
        self.capture_type_var = tk.StringVar(value=default_capture)
        capture_type_menu = tk.OptionMenu(camera_frame, self.capture_type_var, *capture_types)
        capture_type_menu.grid(row=row, column=3, sticky="w", padx=2, pady=2)

        # === SECTION 5: MOTION SETTINGS ===
        motion_frame = tk.LabelFrame(container, text="Motion Settings", padx=5, pady=5)
        motion_frame.grid(row=4, column=0, columnspan=4, sticky="ew", padx=5, pady=5)
        motion_frame.grid_columnconfigure(1, weight=1)
        
        tk.Label(motion_frame, text="Profile:").grid(row=0, column=0, sticky="w", padx=2, pady=2)
        self.motion_config_var = tk.StringVar(value="default")
        motion_config_path = os.path.join("config", "motion_config.json")
        profiles = ["default"]
        if os.path.exists(motion_config_path):
            try:
                with open(motion_config_path, 'r') as f:
                    motion_config_data = json.load(f)
                    profiles = list(motion_config_data.keys())
            except Exception as e:
                logger.warning(f"Error loading motion config: {e}")
        motion_config_menu = tk.OptionMenu(motion_frame, self.motion_config_var, *profiles)
        motion_config_menu.grid(row=0, column=1, sticky="w", padx=2, pady=2)
        
        self.motion_info_label = tk.Label(motion_frame, text="Load config to see settings", fg="gray", font=("Arial", 9), anchor="w", wraplength=500)
        self.motion_info_label.grid(row=1, column=0, columnspan=4, sticky="ew", padx=2, pady=2)

        # === SECTION 6: EXPERIMENT SETTINGS ===
        exp_frame = tk.LabelFrame(container, text="Experiment Settings", padx=5, pady=5)
        exp_frame.grid(row=5, column=0, columnspan=4, sticky="ew", padx=5, pady=5)
        exp_frame.grid_columnconfigure(1, weight=1)
        
        tk.Label(exp_frame, text="File:").grid(row=0, column=0, sticky="w", padx=2, pady=2)
        self.experiment_settings_var = tk.StringVar(value="")
        exp_settings_frame = tk.Frame(exp_frame)
        exp_settings_frame.grid(row=0, column=1, columnspan=2, sticky="ew", padx=2, pady=2)
        
        exp_dir = EXPERIMENTS_FOLDER
        exp_settings = [""]
        if os.path.exists(exp_dir):
            exp_settings.extend([f for f in os.listdir(exp_dir) if f.endswith("_profile.json")])
        
        exp_settings_menu = tk.OptionMenu(exp_settings_frame, self.experiment_settings_var, *exp_settings, command=self.on_experiment_settings_select)
        exp_settings_menu.pack(side=tk.LEFT, padx=2)
        
        tk.Button(exp_settings_frame, text="Refresh", command=self.refresh_experiment_settings).pack(side=tk.LEFT, padx=2)
        tk.Button(exp_settings_frame, text="Export", command=self.export_experiment_settings).pack(side=tk.LEFT, padx=2)
        
        self.experiment_settings_status_label = tk.Label(exp_frame, text="No settings loaded", fg="red", font=("Arial", 9), wraplength=500, justify="left")
        self.experiment_settings_status_label.grid(row=1, column=0, columnspan=4, sticky="w", padx=2, pady=2)

        # === SECTION 7: STATUS & CONTROLS ===
        control_frame = tk.LabelFrame(container, text="Status & Controls", padx=5, pady=5)
        control_frame.grid(row=6, column=0, columnspan=4, sticky="ew", padx=5, pady=5)
        control_frame.grid_columnconfigure(1, weight=1)
        
        tk.Label(control_frame, text="Status:").grid(row=0, column=0, sticky="w", padx=2, pady=2)
        self.status_lbl = tk.Label(control_frame, text="Idle", anchor="w", wraplength=500)
        self.status_lbl.grid(row=0, column=1, columnspan=2, sticky="ew", padx=2, pady=2)
        
        self.recording_btn = tk.Button(control_frame, text="● REC", bg="gray", state="disabled", relief="flat", width=8)
        self.recording_btn.grid(row=0, column=3, padx=2, pady=2)
        
        button_frame = tk.Frame(control_frame)
        button_frame.grid(row=1, column=0, columnspan=4, pady=5)
        
        self.run_btn = tk.Button(button_frame, text="Run", command=self.start, width=10)
        self.run_btn.pack(side=tk.LEFT, padx=5)
        tk.Button(button_frame, text="Pause", command=self.pause, width=10).pack(side=tk.LEFT, padx=5)
        tk.Button(button_frame, text="Stop", command=self.stop, width=10).pack(side=tk.LEFT, padx=5)
        
        timer_frame = tk.Frame(control_frame)
        timer_frame.grid(row=2, column=0, columnspan=4, pady=5)
        
        tk.Label(timer_frame, text="Duration:").pack(side=tk.LEFT, padx=5)
        self.duration_lbl = tk.Label(timer_frame, text="00:00:00", font=("Courier", 10))
        self.duration_lbl.pack(side=tk.LEFT, padx=5)
        
        tk.Label(timer_frame, text="Elapsed:").pack(side=tk.LEFT, padx=5)
        self.elapsed_lbl = tk.Label(timer_frame, text="00:00:00", font=("Courier", 10))
        self.elapsed_lbl.pack(side=tk.LEFT, padx=5)
        
        tk.Label(timer_frame, text="Remaining:").pack(side=tk.LEFT, padx=5)
        self.remaining_lbl = tk.Label(timer_frame, text="00:00:00", font=("Courier", 10))
        self.remaining_lbl.pack(side=tk.LEFT, padx=5)
        
        # Configure container columns
        container.grid_columnconfigure(0, weight=1)
        container.grid_columnconfigure(1, weight=1)
        container.grid_columnconfigure(3, weight=1)
        
        # Calculate required window height based on content
        w.update_idletasks()
        
        # Get the required height of the content
        content_height = container.winfo_reqheight()
        
        # Add small padding for window chrome (title bar, borders) - typically ~40px
        window_chrome_height = 40
        
        # Calculate total required height
        required_height = content_height + window_chrome_height
        
        # Ensure minimum height
        required_height = max(required_height, 500)
        
        # Get current window width
        try:
            current_width = w.winfo_width()
            if current_width < 10:
                current_width = INITIAL_WIDTH
        except:
            current_width = INITIAL_WIDTH
        
        # Set window size to fit content vertically (no scrolling needed)
        w.geometry(f"{current_width}x{required_height}")
        
        # Store the size and lock it - prevent future automatic resizing
        self.initial_window_size = (current_width, required_height)
        self.window_size_locked = True
        
        # Track user manual resizing
        def on_window_configure(event):
            """Update stored window size when user manually resizes."""
            if event.widget == w and self.window_size_locked:
                try:
                    new_w = w.winfo_width()
                    new_h = w.winfo_height()
                    if new_w > 10 and new_h > 10:  # Valid size
                        self.initial_window_size = (new_w, new_h)
                except:
                    pass
        
        w.bind("<Configure>", on_window_configure)
        
        # Load and display motion config on selection change
        def update_motion_info(*args):
            """Update motion settings display when profile changes."""
            try:
                profile_name = self.motion_config_var.get()
                config_path = os.path.join("config", "motion_config.json")
                if os.path.exists(config_path):
                    with open(config_path, 'r') as f:
                        motion_config_data = json.load(f)
                    if profile_name in motion_config_data:
                        motion_cfg = motion_config_data[profile_name]
                        prelim = motion_cfg.get("preliminary", {})
                        between = motion_cfg.get("between_wells", {})
                        profile_display = motion_cfg.get("name", profile_name)
                        info = f"{profile_display}: Preliminary: {prelim.get('feedrate', 'N/A')} mm/min, {prelim.get('acceleration', 'N/A')} mm/s² | "
                        info += f"Between Wells: {between.get('feedrate', 'N/A')} mm/min, {between.get('acceleration', 'N/A')} mm/s²"
                        self.motion_info_label.config(text=info, fg="black")
                    else:
                        self.motion_info_label.config(text=f"Profile '{profile_name}' not found", fg="red")
                else:
                    self.motion_info_label.config(text="Config file not found", fg="red")
            except Exception as e:
                self.motion_info_label.config(text=f"Error loading config: {e}", fg="red")
        
        self.motion_config_var.trace("w", update_motion_info)
        update_motion_info()  # Initial load
        
        # Update run button state based on calibration
        self.update_run_button_state()

        # Live example filename
        def upd(e=None):
            exp_name = self.experiment_name_ent.get().strip() or "exp"
            date_str = datetime.now().strftime("%Y%m%d")
            output_folder = os.path.join(OUTPUTS_FOLDER, f"{date_str}_{exp_name}")
            ext = ".h264"  # H264 is the only export format
            # Use calibration labels if available, otherwise use placeholders
            if self.loaded_calibration and self.loaded_calibration.get("labels"):
                labels = self.loaded_calibration.get("labels", [])
                if labels:
                    first_label = labels[0]
                    x0 = first_label[1:] if len(first_label) > 1 else "1"  # Column number
                    y0 = first_label[0] if len(first_label) > 0 else "A"  # Row letter
                else:
                    x0 = "1"
                    y0 = "A"
            else:
                x0 = "1"
                y0 = "A"
            ts     = time.strftime("%H%M%S")
            ds     = date_str  # Use YYYYMMDD format
            fn = f"{ds}_{ts}_{exp_name}_{y0}{x0}{ext}"
            # Show just filename to keep it short
            full_path = f"Example: {fn}"
            self.status_lbl.config(text=full_path)

        for wgt in (self.experiment_name_ent, self.fps_ent):
            wgt.bind("<KeyRelease>", upd)
        self.resolution_var.trace_add("write", lambda *a: upd())
        self.export_var.trace_add("write", lambda *a: upd())
        # Also update when calibration changes
        if hasattr(self, 'calibration_var'):
            self.calibration_var.trace_add("write", lambda *a: upd())
        upd()
        
        # Initialize export type options and checkbox visibility
        if hasattr(self, '_update_export_type_options'):
            self._update_export_type_options()

        # Only set transient and grab if it's a Toplevel window
        if isinstance(w, tk.Toplevel):
            w.transient(self.parent)
            w.grab_set()
    
    def refresh_calibrations(self) -> None:
        """Refresh the list of available calibrations."""
        if not self.window:
            return
        
        calib_dir = "calibrations"
        calibrations = [""]
        if os.path.exists(calib_dir):
            calibrations.extend([f for f in os.listdir(calib_dir) if f.endswith(".json")])
        
        # Update the option menu (simplified - just update the variable)
        current = self.calibration_var.get()
        if current not in calibrations:
            self.calibration_var.set("")
            self.on_calibration_select("")
        else:
            self.calibration_var.set(current)
    
    def refresh_experiment_settings(self) -> None:
        """Refresh the list of available experiment settings."""
        if not self.window:
            return
        
        exp_dir = EXPERIMENTS_FOLDER
        exp_settings = [""]
        if os.path.exists(exp_dir):
            exp_settings.extend([f for f in os.listdir(exp_dir) if f.endswith("_profile.json")])
        
        # Update the option menu (simplified - just update the variable)
        current = self.experiment_settings_var.get()
        if current not in exp_settings:
            self.experiment_settings_var.set("")
            self.on_experiment_settings_select("")
        else:
            self.experiment_settings_var.set(current)
    
    def on_experiment_settings_select(self, filename: str) -> None:
        """
        Handle experiment settings selection from dropdown.
        
        Args:
            filename: Selected experiment settings filename (empty string if none)
        """
        if not filename or filename == "":
            # No settings selected
            self.experiment_settings_status_label.config(text="No settings loaded", fg="red")
            return
        
        try:
            # Load experiment settings file
            exp_path = os.path.join(EXPERIMENTS_FOLDER, filename)
            if not os.path.exists(exp_path):
                self.experiment_settings_status_label.config(
                    text=f"Error: File not found: {filename}",
                    fg="red"
                )
                return
            
            with open(exp_path, 'r') as f:
                settings = json.load(f)
            
            # Validate calibration file exists
            calib_file = settings.get("calibration_file")
            if not calib_file:
                self.experiment_settings_status_label.config(
                    text="Error: No calibration file reference in settings",
                    fg="red"
                )
                return
            
            calib_path = os.path.join("calibrations", calib_file)
            if not os.path.exists(calib_path):
                self.experiment_settings_status_label.config(
                    text=f"Error: Referenced calibration file '{calib_file}' not found.",
                    fg="red"
                )
                return
            
            # Load calibration
            self.calibration_var.set(calib_file)
            self.on_calibration_select(calib_file)
            
            # Wait a moment for calibration to load
            self.window.update()
            
            if not self.loaded_calibration:
                self.experiment_settings_status_label.config(text="Error: Failed to load calibration", fg="red")
                return
            
            # Restore settings
            selected_wells = settings.get("selected_wells", [])
            for label, var in self.well_checkboxes.items():
                var.set(label in selected_wells)
            
            # Load action phases
            phases_data = settings.get("action_phases", [{"action": "GPIO OFF", "time": 30.0}])
            # Clear all existing phases (remove from end to avoid index issues)
            while len(self.action_phases) > 1:
                self.remove_action_phase(len(self.action_phases) - 1)
            # Update first phase with loaded data
            if self.action_phases and phases_data:
                self.action_phases[0]["action_var"].set(phases_data[0].get("action", "GPIO OFF"))
                self.action_phases[0]["time_ent"].delete(0, tk.END)
                self.action_phases[0]["time_ent"].insert(0, str(phases_data[0].get("time", 30.0)))
            # Add remaining phases
            for phase_dict in phases_data[1:]:
                self.add_action_phase(phase_dict.get("action", "GPIO OFF"), phase_dict.get("time", 0.0))
            
            resolution = settings.get("resolution", list(DEFAULT_RES))
            res_tuple = (int(resolution[0]), int(resolution[1])) if len(resolution) >= 2 else get_default_resolution_for_camera(self._is_pihq_camera())
            self.resolution_var.set(resolution_to_preset_option(res_tuple, self._resolution_presets))
            
            self.fps_ent.delete(0, tk.END)
            self.fps_ent.insert(0, str(settings.get("fps", 30.0)))
            
            self.export_var.set(settings.get("export_type", "H264"))
            
            # Handle both old format (motion_config_file) and new format (motion_config_profile)
            motion_profile = settings.get("motion_config_profile") or settings.get("motion_config_file", "default")
            # If old format had .json extension, remove it
            if motion_profile.endswith(".json"):
                motion_profile = motion_profile[:-5]  # Remove .json
            self.motion_config_var.set(motion_profile)
            
            # Handle both old format (filename_scheme) and new format (experiment_name)
            experiment_name = settings.get("experiment_name")
            if not experiment_name:
                # Try to extract from old filename_scheme format if present
                old_scheme = settings.get("filename_scheme", "exp_{y}{x}_{time}_{date}")
                # Try to extract exp name from old scheme (default was "exp")
                if "exp" in old_scheme:
                    experiment_name = "exp"
                else:
                    experiment_name = "exp"
            self.experiment_name_ent.delete(0, tk.END)
            self.experiment_name_ent.insert(0, experiment_name)
            
            # Handle both old format (plain "snake"/"raster") and new format (with symbols)
            pattern_setting = settings.get("pattern", "raster →↓")
            if pattern_setting in ["snake", "raster"]:
                # Old format - add symbols
                pattern_setting = "snake →↙" if pattern_setting == "snake" else "raster →↓"
            self.pattern_var.set(pattern_setting)
            
            self.update_run_button_state()
            # Truncate filename if too long
            display_name = filename[:40] + "..." if len(filename) > 40 else filename
            self.experiment_settings_status_label.config(text=f"Loaded: {display_name}", fg="green")
            
        except Exception as e:
            logger.error(f"Error loading settings: {e}")
            error_msg = str(e)[:50] + "..." if len(str(e)) > 50 else str(e)
            self.experiment_settings_status_label.config(text=f"Error: {error_msg}", fg="red")
    
    def on_calibration_select(self, filename: str) -> None:
        """
        Handle calibration selection from dropdown.
        
        Args:
            filename: Selected calibration filename (empty string if none)
        """
        if not filename or filename == "":
            # No calibration selected
            self.loaded_calibration = None
            self.calibration_file = None
            self.calibration_status_label.config(text="No calibration loaded", fg="red")
            # Disable Select Cells button
            if self.select_cells_btn:
                self.select_cells_btn.config(state="disabled")
            # Close checkbox window if open
            if self.checkbox_window and self.checkbox_window.winfo_exists():
                self.checkbox_window.destroy()
                self.checkbox_window = None
            self.update_run_button_state()
            return
        
        try:
            # Load calibration file
            calib_path = os.path.join("calibrations", filename)
            if not os.path.exists(calib_path):
                self.calibration_status_label.config(
                    text=f"Error: File not found",
                    fg="red"
                )
                self.loaded_calibration = None
                self.calibration_file = None
                self.update_run_button_state()
                return
            
            with open(calib_path, 'r') as f:
                self.loaded_calibration = json.load(f)
            
            self.calibration_file = filename
            
            # Validate calibration structure
            required_fields = ["interpolated_positions", "labels", "x_quantity", "y_quantity"]
            if not all(field in self.loaded_calibration for field in required_fields):
                raise ValueError("Invalid calibration file format")
            
            # Update status - truncate long filenames
            num_wells = len(self.loaded_calibration.get("interpolated_positions", []))
            # Truncate filename if too long
            display_name = filename[:40] + "..." if len(filename) > 40 else filename
            status_text = f"Loaded: {display_name} ({num_wells} wells)"
            self.calibration_status_label.config(
                text=status_text,
                fg="green"
            )
            
            # Enable Select Cells button
            if self.select_cells_btn:
                self.select_cells_btn.config(state="normal")
            
            # Initialize checkboxes (all checked by default)
            self.initialize_checkboxes()
            
            self.update_run_button_state()
            
        except Exception as e:
            logger.error(f"Error loading calibration: {e}")
            error_msg = str(e)[:50] + "..." if len(str(e)) > 50 else str(e)
            self.calibration_status_label.config(
                text=f"Error: {error_msg}",
                fg="red"
            )
            self.loaded_calibration = None
            self.calibration_file = None
            # Disable Select Cells button
            if self.select_cells_btn:
                self.select_cells_btn.config(state="disabled")
            self.update_run_button_state()
    
    def initialize_checkboxes(self) -> None:
        """Initialize checkbox variables for all wells (all checked by default)."""
        if not self.loaded_calibration:
            return
        
        labels = self.loaded_calibration.get("labels", [])
        x_qty = self.loaded_calibration.get("x_quantity", 0)
        
        self.well_checkboxes = {}
        self.label_to_row_col = {}
        
        for i, label in enumerate(labels):
            var = tk.BooleanVar(value=True)  # All checked by default
            self.well_checkboxes[label] = var
            row = i // x_qty
            col = i % x_qty
            self.label_to_row_col[label] = (row, col)
    
    def open_checkbox_window(self) -> None:
        """Open separate window for checkbox selection."""
        if not self.loaded_calibration:
            return
        
        # If window already exists, just raise it
        if self.checkbox_window and self.checkbox_window.winfo_exists():
            self.checkbox_window.lift()
            return
        
        # Disable the button
        if self.select_cells_btn:
            self.select_cells_btn.config(state="disabled")
        
        # Create new window
        self.checkbox_window = tk.Toplevel(self.window if self.window else self.parent)
        self.checkbox_window.title("Select Wells")
        self.checkbox_window.transient(self.window if self.window else self.parent)
        
        def on_close():
            if self.checkbox_window:
                self.checkbox_window.destroy()
                self.checkbox_window = None
            # Re-enable the button
            if self.select_cells_btn:
                self.select_cells_btn.config(state="normal")
            self.update_run_button_state()
        
        self.checkbox_window.protocol("WM_DELETE_WINDOW", on_close)
        
        # Create checkbox grid in the new window
        self.create_checkbox_grid()
    
    def create_checkbox_grid(self) -> None:
        """Create checkbox grid for well selection in separate window."""
        if not self.loaded_calibration or not self.checkbox_window:
            return
        
        # Clear existing checkboxes
        for widget in self.checkbox_window.winfo_children():
            widget.destroy()
        
        self.checkbox_widgets = {}  # Store checkbox widgets for shift/ctrl click
        
        # Create main container frame
        main_frame = tk.Frame(self.checkbox_window, padx=10, pady=10)
        main_frame.pack(fill="both", expand=True)
        
        # Create button frame for check all/uncheck all
        button_frame = tk.Frame(main_frame)
        button_frame.pack(fill="x", pady=(0, 10))
        
        tk.Button(button_frame, text="Check All", command=self.check_all_wells).pack(side=tk.LEFT, padx=5)
        tk.Button(button_frame, text="Uncheck All", command=self.uncheck_all_wells).pack(side=tk.LEFT, padx=5)
        
        def close_window():
            if self.checkbox_window:
                self.checkbox_window.destroy()
                self.checkbox_window = None
            # Re-enable the button
            if self.select_cells_btn:
                self.select_cells_btn.config(state="normal")
            self.update_run_button_state()
        
        tk.Button(button_frame, text="Close", command=close_window).pack(side=tk.RIGHT, padx=5)
        
        # Create scrollable frame for checkboxes
        canvas_frame = tk.Frame(main_frame)
        canvas_frame.pack(fill="both", expand=True)
        
        canvas = tk.Canvas(canvas_frame, borderwidth=0)
        scrollbar_v = tk.Scrollbar(canvas_frame, orient="vertical", command=canvas.yview)
        scrollbar_h = tk.Scrollbar(canvas_frame, orient="horizontal", command=canvas.xview)
        
        self.checkbox_frame = tk.Frame(canvas)
        
        self.checkbox_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=self.checkbox_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar_v.set, xscrollcommand=scrollbar_h.set)
        
        # Grid layout for canvas and scrollbars
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar_v.grid(row=0, column=1, sticky="ns")
        scrollbar_h.grid(row=1, column=0, sticky="ew")
        
        canvas_frame.grid_rowconfigure(0, weight=1)
        canvas_frame.grid_columnconfigure(0, weight=1)
        
        # Get calibration data
        labels = self.loaded_calibration.get("labels", [])
        x_qty = self.loaded_calibration.get("x_quantity", 0)
        
        # Create checkboxes in grid layout
        for i, label in enumerate(labels):
            if label not in self.well_checkboxes:
                # Initialize if not already done
                var = tk.BooleanVar(value=True)
                self.well_checkboxes[label] = var
            else:
                var = self.well_checkboxes[label]
            
            row = i // x_qty
            col = i % x_qty
            
            # Create checkbox with custom click handler
            checkbox = tk.Checkbutton(
                self.checkbox_frame,
                text=label,
                variable=var,
                width=4,
                command=self.update_run_button_state  # Update state when toggled
            )
            checkbox.grid(row=row, column=col, padx=2, pady=2, sticky="w")
            self.checkbox_widgets[label] = checkbox
            
            # Bind shift-click and control-click
            # Use ButtonPress-1 which fires earlier, and check modifier state more reliably
            def make_click_handler(lbl, r, c, v, cb):
                def on_button_press(event):
                    # Check if shift or control is pressed
                    # event.state uses bit flags: Shift=0x1 (0x0001), Control=0x4 (0x0004)
                    # On Raspberry Pi (Linux), event.state bit flags are reliable
                    state = event.state
                    has_shift = bool(state & 0x0001)
                    has_control = bool(state & 0x0004)
                    
                    if has_shift or has_control:
                        # Get the state BEFORE tkinter processes the click and toggles the checkbox
                        checkbox_state = v.get()  # True = checked, False = unchecked
                        
                        # Assess row and column states
                        row_state = self.assess_row_state(r)
                        col_state = self.assess_column_state(c)
                        
                        # Temporarily remove the command callback to prevent the toggle
                        original_command = cb.cget('command')
                        cb.config(command=lambda: None)  # Temporarily disable
                        
                        # Determine action based on checkbox state, row state, and column state
                        if has_shift:
                            # Shift-click: operate on row
                            if checkbox_state:  # Checkbox is checked
                                if row_state == "all_checked":
                                    # State: checked, row: all checked, action: unfill row (uncheck all)
                                    self.uncheck_row(r)
                                else:
                                    # State: checked, row: not all checked, action: fill row (check all)
                                    self.check_row(r)
                            else:  # Checkbox is unchecked
                                if row_state == "all_unchecked":
                                    # State: unchecked, row: all unchecked, action: fill row (check all)
                                    self.check_row(r)
                                elif row_state == "some_checked":
                                    # State: unchecked, row: some checked, action: unfill row (uncheck all)
                                    self.uncheck_row(r)
                                else:  # row_state == "all_checked" (shouldn't happen if checkbox is unchecked)
                                    # Edge case: fill row
                                    self.check_row(r)
                        else:  # has_control
                            # Control-click: operate on column
                            if checkbox_state:  # Checkbox is checked
                                if col_state == "all_checked":
                                    # State: checked, column: all checked, action: unfill column (uncheck all)
                                    self.uncheck_column(c)
                                else:
                                    # State: checked, column: not all checked, action: fill column (check all)
                                    self.check_column(c)
                            else:  # Checkbox is unchecked
                                if col_state == "all_unchecked":
                                    # State: unchecked, column: all unchecked, action: fill column (check all)
                                    self.check_column(c)
                                elif col_state == "some_checked":
                                    # State: unchecked, column: some checked, action: unfill column (uncheck all)
                                    self.uncheck_column(c)
                                else:  # col_state == "all_checked" (shouldn't happen if checkbox is unchecked)
                                    # Edge case: fill column
                                    self.check_column(c)
                        
                        # Restore the command callback
                        def restore_command():
                            cb.config(command=original_command)
                            self.update_run_button_state()
                        
                        # Restore after event processing completes
                        self.checkbox_window.after_idle(restore_command)
                        
                        # Prevent the default checkbox toggle since we handled it via row/col action
                        return "break"
                return on_button_press
            
            # Bind to ButtonPress-1 which fires earlier than Button-1 (before checkbox processes click)
            checkbox.bind("<ButtonPress-1>", make_click_handler(label, row, col, var, checkbox), add="+")
        
        # Update instructions
        instructions_frame = tk.Frame(main_frame)
        instructions_frame.pack(fill="x", pady=(10, 0))
        instructions = (
            "Checkbox Controls:\n"
            "• Click: Toggle single well\n"
            "• Shift+Click: Smart fill/unfill row based on state\n"
            "• Ctrl+Click: Smart fill/unfill column based on state\n"
            "• Use buttons above to check/uncheck all"
        )
        instructions_label = tk.Label(instructions_frame, text=instructions, fg="gray", font=("Arial", 8), justify="left")
        instructions_label.pack(anchor="w")
        
        # Force update to get actual widget sizes
        self.checkbox_window.update_idletasks()
        
        # Calculate actual size needed based on widget requirements
        # Get checkbox frame required size (this includes all checkboxes)
        checkbox_frame_width = max(self.checkbox_frame.winfo_reqwidth(), 1)
        checkbox_frame_height = max(self.checkbox_frame.winfo_reqheight(), 1)
        
        # Get sizes of other components
        button_frame_height = max(button_frame.winfo_reqheight(), 1)
        instructions_height = max(instructions_label.winfo_reqheight(), 1)
        
        # Account for padding and margins
        window_padding_x = 20  # Main frame horizontal padding (padx * 2)
        window_padding_y = 20  # Main frame vertical padding (pady * 2)
        frame_spacing = 20  # Space between frames (pady values combined)
        scrollbar_width = 20  # Vertical scrollbar width
        horizontal_scrollbar_height = 20  # Horizontal scrollbar height
        
        # Determine maximum reasonable display size (to avoid windows that are too large)
        max_display_width = 1000  # Maximum width before horizontal scrolling
        max_display_height = 700  # Maximum height before vertical scrolling
        
        # Calculate if scrolling will be needed
        needs_horizontal_scroll = checkbox_frame_width > max_display_width
        needs_vertical_scroll = checkbox_frame_height > max_display_height
        
        # Calculate required window width
        if needs_horizontal_scroll:
            # Use max display width + scrollbar
            required_width = max_display_width + scrollbar_width + window_padding_x * 2
        else:
            # Use actual checkbox width + scrollbar space (always reserve space for scrollbar)
            required_width = checkbox_frame_width + scrollbar_width + window_padding_x * 2
        
        # Calculate required window height
        # Include: button frame + checkbox area (or max) + instructions + all spacing
        checkbox_display_height = min(checkbox_frame_height, max_display_height) if needs_vertical_scroll else checkbox_frame_height
        required_height = (
            button_frame_height +
            checkbox_display_height +
            instructions_height +
            frame_spacing * 3 +  # Space: after buttons, before instructions, plus margins
            window_padding_y * 2
        )
        
        # Add horizontal scrollbar height if needed
        if needs_horizontal_scroll:
            required_height += horizontal_scrollbar_height
        
        # Ensure minimum window size for usability
        min_width = 400
        min_height = 300
        required_width = max(int(required_width), min_width)
        required_height = max(int(required_height), min_height)
        
        # Get current window size (if window already exists and was resized by user)
        try:
            current_width = self.checkbox_window.winfo_width()
            current_height = self.checkbox_window.winfo_height()
            # If window is too small (less than 10x10, it's not yet displayed properly)
            if current_width < 10 or current_height < 10:
                current_width = required_width
                current_height = required_height
        except:
            current_width = required_width
            current_height = required_height
        
        # Set minimum size
        self.checkbox_window.minsize(min_width, min_height)
        
        # Only resize if current window is smaller than required
        if current_width < required_width or current_height < required_height:
            # Use required size
            final_width = required_width
            final_height = required_height
        else:
            # Preserve user-resized size if it's larger than required
            final_width = current_width
            final_height = current_height
        
        # Set window size
        self.checkbox_window.geometry(f"{final_width}x{final_height}")
        
        # Update canvas scroll region after widgets are created and window is sized
        self.checkbox_window.update_idletasks()
        canvas.configure(scrollregion=canvas.bbox("all"))
        
        # Center the window on screen if it was just created (not resized by user)
        try:
            self.checkbox_window.update_idletasks()
            screen_width = self.checkbox_window.winfo_screenwidth()
            screen_height = self.checkbox_window.winfo_screenheight()
            window_width = self.checkbox_window.winfo_width()
            window_height = self.checkbox_window.winfo_height()
            # Only center if we just resized (i.e., window was smaller than required)
            if current_width < required_width or current_height < required_height:
                x = max(0, (screen_width - window_width) // 2)
                y = max(0, (screen_height - window_height) // 2)
                self.checkbox_window.geometry(f"{window_width}x{window_height}+{x}+{y}")
        except:
            pass  # If positioning fails, just use default position
    
    def check_all_wells(self) -> None:
        """Check all wells."""
        for var in self.well_checkboxes.values():
            var.set(True)
        self.update_run_button_state()
    
    def uncheck_all_wells(self) -> None:
        """Uncheck all wells."""
        for var in self.well_checkboxes.values():
            var.set(False)
        self.update_run_button_state()
    
    def check_row(self, row: int) -> None:
        """Check all wells in the specified row."""
        x_qty = self.loaded_calibration.get("x_quantity", 0)
        for label, (r, c) in self.label_to_row_col.items():
            if r == row:
                self.well_checkboxes[label].set(True)
        self.update_run_button_state()
    
    def check_column(self, col: int) -> None:
        """Check all wells in the specified column."""
        for label, (r, c) in self.label_to_row_col.items():
            if c == col:
                self.well_checkboxes[label].set(True)
        self.update_run_button_state()
    
    def uncheck_row(self, row: int) -> None:
        """Uncheck all wells in the specified row."""
        x_qty = self.loaded_calibration.get("x_quantity", 0)
        for label, (r, c) in self.label_to_row_col.items():
            if r == row:
                self.well_checkboxes[label].set(False)
        self.update_run_button_state()
    
    def uncheck_column(self, col: int) -> None:
        """Uncheck all wells in the specified column."""
        for label, (r, c) in self.label_to_row_col.items():
            if c == col:
                self.well_checkboxes[label].set(False)
        self.update_run_button_state()
    
    def assess_row_state(self, row: int) -> str:
        """
        Assess the state of all checkboxes in a row.
        
        Args:
            row: Row number to assess
            
        Returns:
            "all_checked" if all checkboxes in row are checked,
            "all_unchecked" if all checkboxes in row are unchecked,
            "some_checked" if some (but not all) checkboxes are checked
        """
        checked_count = 0
        total_count = 0
        for label, (r, c) in self.label_to_row_col.items():
            if r == row:
                total_count += 1
                if self.well_checkboxes[label].get():
                    checked_count += 1
        
        if checked_count == 0:
            return "all_unchecked"
        elif checked_count == total_count:
            return "all_checked"
        else:
            return "some_checked"
    
    def assess_column_state(self, col: int) -> str:
        """
        Assess the state of all checkboxes in a column.
        
        Args:
            col: Column number to assess
            
        Returns:
            "all_checked" if all checkboxes in column are checked,
            "all_unchecked" if all checkboxes in column are unchecked,
            "some_checked" if some (but not all) checkboxes are checked
        """
        checked_count = 0
        total_count = 0
        for label, (r, c) in self.label_to_row_col.items():
            if c == col:
                total_count += 1
                if self.well_checkboxes[label].get():
                    checked_count += 1
        
        if checked_count == 0:
            return "all_unchecked"
        elif checked_count == total_count:
            return "all_checked"
        else:
            return "some_checked"
    
    def update_run_button_state(self) -> None:
        """Update Run button state based on calibration and well selection."""
        if not self.window:
            return
        
        if not self.loaded_calibration:
            self.run_btn.config(state="disabled")
            if hasattr(self, 'status_lbl'):
                self.status_lbl.config(text="No calibration loaded. Please load a calibration first.")
            return
        
        # Check if at least one well is selected
        selected_wells = [label for label, var in self.well_checkboxes.items() if var.get()]
        if not selected_wells:
            self.run_btn.config(state="disabled")
            if hasattr(self, 'status_lbl'):
                self.status_lbl.config(text="No wells selected. Select at least one well.")
            return
        
        # Enable run button
        self.run_btn.config(state="normal")
        if hasattr(self, 'status_lbl'):
            self.status_lbl.config(text=f"Ready - {len(selected_wells)} wells selected")
    
    def _is_pihq_camera(self) -> bool:
        """True if using Pi HQ camera (4:3), False if Player One / Mars 662M (16:9)."""
        return self.usb_camera is None  # Pi HQ when no external camera (incl. simulate_cam)
    
    def _get_resolution(self) -> Tuple[int, int]:
        """Return current capture resolution (width, height) from preset dropdown."""
        parsed = parse_resolution_option(self.resolution_var.get())
        if parsed is not None:
            return parsed
        if self._resolution_presets:
            return self._resolution_presets[0]
        return get_default_resolution_for_camera(self._is_pihq_camera())
    
    def on_mode_change(self, *args) -> None:
        """
        Handle mode change between Video Capture and Image Capture.
        Updates action phase options, description, and time entry visibility.
        """
        mode = self.capture_mode_var.get()
        
        # Update description
        if mode == "Video Capture":
            self.mode_description_label.config(
                text="Video Capture: Records video with GPIO control during action phases"
            )
            # Update existing action phases to only show GPIO options
            self._update_action_phase_options()
        else:  # Image Capture
            self.mode_description_label.config(
                text="Image Capture: Captures individual images with DELAY, CAPTURE IMAGE, and GPIO control options"
            )
            # Update existing action phases to show all options
            self._update_action_phase_options()
        
        # Update time entry visibility for all phases based on new mode
        for phase_data in self.action_phases:
            self._on_action_change(phase_data)
        
        # Update export type dropdown based on mode
        self._update_export_type_options()
    
    def _update_action_phase_options(self) -> None:
        """Update action dropdown options for all phases based on current mode."""
        mode = self.capture_mode_var.get() if hasattr(self, 'capture_mode_var') else "Video Capture"
        
        if mode == "Image Capture":
            action_options = ["GPIO ON", "GPIO OFF", "DELAY", "CAPTURE IMAGE"]
        else:  # Video Capture
            action_options = ["GPIO ON", "GPIO OFF"]
        
        # Update all existing action menus
        for phase_data in self.action_phases:
            current_action = phase_data["action_var"].get()
            action_menu = phase_data.get("action_menu")
            
            # Recreate the menu with new options
            if action_menu:
                action_menu.destroy()
            
            # Create callback to update time entry visibility
            def make_callback(pd=phase_data):
                def callback(*args):
                    self._on_action_change(pd, *args)
                return callback
            
            # Create new menu with updated options
            new_menu = tk.OptionMenu(
                phase_data["frame"], 
                phase_data["action_var"], 
                *action_options,
                command=make_callback()
            )
            new_menu.grid(row=0, column=1, padx=5)
            phase_data["action_menu"] = new_menu
            
            # If current action is not in new options, default to first option
            if current_action not in action_options:
                phase_data["action_var"].set(action_options[0])
            else:
                # Update time entry visibility for current action
                self._on_action_change(phase_data)
    
    def _update_export_type_options(self) -> None:
        """Update export type dropdown options based on capture mode."""
        mode = self.capture_mode_var.get() if hasattr(self, 'capture_mode_var') else "Video Capture"
        current_export = self.export_var.get()
        
        if mode == "Image Capture":
            # Image Capture mode: show image formats
            export_options = ["PNG", "JPEG"]
            default_export = "PNG"
        else:
            # Video Capture mode: show video formats
            export_options = ["H264"]
            default_export = "H264"
        
        # Destroy old menu
        if hasattr(self, 'export_menu'):
            self.export_menu.destroy()
        
        # Create new menu with updated options
        self.export_menu = tk.OptionMenu(self.export_menu_frame, self.export_var, *export_options, command=self._on_export_type_change)
        self.export_menu.pack(side=tk.LEFT)
        
        # Set to default if current value is not in new options
        if current_export not in export_options:
            self.export_var.set(default_export)
        
        # Update checkbox visibility
        self._update_convert_checkbox_visibility()
    
    def _on_export_type_change(self, *args) -> None:
        """Handle export type dropdown change."""
        self._update_convert_checkbox_visibility()
    
    def _update_convert_checkbox_visibility(self) -> None:
        """Update visibility of convert to MP4 checkbox based on mode and export type."""
        if not hasattr(self, 'convert_to_mp4_checkbox'):
            return
        
        mode = self.capture_mode_var.get() if hasattr(self, 'capture_mode_var') else "Video Capture"
        export_type = self.export_var.get() if hasattr(self, 'export_var') else "H264"
        
        # Only show checkbox for Video Capture mode with H264 export
        if mode == "Video Capture" and export_type == "H264":
            self.convert_to_mp4_checkbox.grid()
        else:
            self.convert_to_mp4_checkbox.grid_remove()
    
    def _on_action_change(self, phase_data: dict, *args) -> None:
        """Callback when action dropdown changes - show/hide time entry based on action type and mode."""
        action = phase_data["action_var"].get()
        time_ent = phase_data["time_ent"]
        time_label = phase_data.get("time_label")
        
        # Get current mode
        mode = self.capture_mode_var.get() if hasattr(self, 'capture_mode_var') else "Video Capture"
        
        if mode == "Image Capture":
            # Image Capture mode: Only DELAY shows time entry
            if action == "DELAY":
                if time_label:
                    time_label.grid(row=0, column=2, padx=5)
                time_ent.grid(row=0, column=3, padx=5)
            else:
                # Hide time entry for GPIO ON/OFF and CAPTURE IMAGE
                if time_label:
                    time_label.grid_remove()
                time_ent.grid_remove()
        else:
            # Video Capture mode: GPIO ON/OFF show time entry
            if action in ["GPIO ON", "GPIO OFF"]:
                if time_label:
                    time_label.grid(row=0, column=2, padx=5)
                time_ent.grid(row=0, column=3, padx=5)
            else:
                # Hide for any other actions (shouldn't happen in Video Capture, but just in case)
                if time_label:
                    time_label.grid_remove()
                time_ent.grid_remove()
    
    def add_action_phase(self, action: Optional[str] = None, time: Optional[float] = None) -> None:
        """
        Add a new action phase row to the GUI.
        
        Args:
            action: Action type. If None, defaults based on mode.
            time: Time in seconds (only used for DELAY). If None, defaults to 0.0.
        """
        if not self.action_phases_frame:
            return
        
        mode = self.capture_mode_var.get() if hasattr(self, 'capture_mode_var') else "Video Capture"
        
        if action is None:
            if mode == "Image Capture":
                action = "GPIO OFF"
            else:
                action = "GPIO OFF"
        if time is None:
            time = 0.0
        
        phase_num = len(self.action_phases) + 1
        
        # Create frame for this phase row
        phase_frame = tk.Frame(self.action_phases_frame)
        phase_frame.grid(row=len(self.action_phases), column=0, sticky="ew", padx=2, pady=2)
        
        # Phase number label
        phase_label = tk.Label(phase_frame, text=f"Phase {phase_num}:")
        phase_label.grid(row=0, column=0, padx=5)
        
        # Action dropdown - options depend on mode
        action_var = tk.StringVar(value=action)
        if mode == "Image Capture":
            action_options = ["GPIO ON", "GPIO OFF", "DELAY", "CAPTURE IMAGE"]
        else:  # Video Capture
            action_options = ["GPIO ON", "GPIO OFF"]
        
        # Create callback to update time entry visibility
        phase_data_for_callback = {}  # Will be populated below
        
        def make_callback():
            def callback(*args):
                self._on_action_change(phase_data_for_callback, *args)
            return callback
        
        action_menu = tk.OptionMenu(phase_frame, action_var, *action_options, command=make_callback())
        action_menu.grid(row=0, column=1, padx=5)
        
        # Time label and entry (initially hidden, shown only for DELAY)
        time_label = tk.Label(phase_frame, text="Time (s):")
        time_ent = tk.Entry(phase_frame, width=10)
        time_ent.insert(0, str(time))
        
        # Store phase data first (before callback)
        phase_data = {
            "frame": phase_frame,
            "phase_num": phase_num,
            "phase_label": phase_label,
            "action_var": action_var,
            "action_menu": action_menu,
            "time_label": time_label,
            "time_ent": time_ent,
            "delete_btn": None  # Will be set below
        }
        phase_data_for_callback.update(phase_data)
        
        # Delete button (disabled for first phase)
        delete_btn = tk.Button(
            phase_frame, 
            text="Delete", 
            command=lambda: self.remove_action_phase(phase_num - 1),
            state="normal" if phase_num > 1 else "disabled"
        )
        delete_btn.grid(row=0, column=4, padx=5)
        phase_data["delete_btn"] = delete_btn
        
        # Show/hide time entry based on initial action and mode
        if mode == "Image Capture":
            # Image Capture: Only DELAY shows time entry
            if action == "DELAY":
                time_label.grid(row=0, column=2, padx=5)
                time_ent.grid(row=0, column=3, padx=5)
            else:
                time_label.grid_remove()
                time_ent.grid_remove()
        else:
            # Video Capture: GPIO ON/OFF show time entry
            if action in ["GPIO ON", "GPIO OFF"]:
                time_label.grid(row=0, column=2, padx=5)
                time_ent.grid(row=0, column=3, padx=5)
            else:
                time_label.grid_remove()
                time_ent.grid_remove()
        
        self.action_phases.append(phase_data)
        
        # Update phase numbers for all phases
        self._update_phase_numbers()
        
        # Update scroll region after adding phase
        if hasattr(self, 'phases_canvas'):
            self.window.update_idletasks()
            self.phases_canvas.configure(scrollregion=self.phases_canvas.bbox("all"))
    
    def remove_action_phase(self, index: int) -> None:
        """
        Remove an action phase from the GUI.
        
        Args:
            index: Index of the phase to remove (0-based)
        """
        if index < 0 or index >= len(self.action_phases):
            return
        
        # Cannot remove first phase
        if index == 0:
            return
        
        # Destroy the frame and remove from list
        phase_data = self.action_phases[index]
        phase_data["frame"].destroy()
        self.action_phases.pop(index)
        
        # Update phase numbers
        self._update_phase_numbers()
        
        # Update scroll region after removing phase
        if hasattr(self, 'phases_canvas'):
            self.window.update_idletasks()
            self.phases_canvas.configure(scrollregion=self.phases_canvas.bbox("all"))
    
    def _update_phase_numbers(self) -> None:
        """Update phase number labels and delete button states."""
        for i, phase_data in enumerate(self.action_phases):
            phase_data["phase_num"] = i + 1
            # Update label
            phase_data["phase_label"].config(text=f"Phase {i + 1}:")
            # Update delete button state (disabled for first phase)
            phase_data["delete_btn"].config(state="normal" if i > 0 else "disabled")
            # Update delete button command to use correct index
            phase_data["delete_btn"].config(command=lambda idx=i: self.remove_action_phase(idx))
    
    def get_action_phases(self) -> List[Tuple[str, float]]:
        """
        Get list of action phases from GUI.
        
        Returns:
            List of (action, time) tuples where action can be:
            - Video Capture mode: "GPIO ON", "GPIO OFF" - time from time entry field
            - Image Capture mode: "GPIO ON", "GPIO OFF", "DELAY", "CAPTURE IMAGE"
              - Only DELAY has a time value from time entry
              - All others use 0.0 (instant)
        """
        mode = self.capture_mode_var.get() if hasattr(self, 'capture_mode_var') else "Video Capture"
        phases = []
        
        for phase_data in self.action_phases:
            action = phase_data["action_var"].get()
            
            if mode == "Video Capture":
                # Video Capture: GPIO actions use time from time entry
                if action in ["GPIO ON", "GPIO OFF"]:
                    time_str = phase_data["time_ent"].get().strip()
                    if not time_str:
                        logger.warning(f"{action} action has no time specified, skipping")
                        continue
                    try:
                        time_val = float(time_str)
                        if time_val < 0:
                            logger.warning(f"{action} action has negative time, skipping")
                            continue
                    except ValueError:
                        logger.warning(f"{action} action has invalid time: {time_str}, skipping")
                        continue
                else:
                    time_val = 0.0
            else:
                # Image Capture: Only DELAY uses time entry
                if action == "DELAY":
                    time_str = phase_data["time_ent"].get().strip()
                    if not time_str:
                        logger.warning(f"DELAY action has no time specified, skipping")
                        continue
                    try:
                        time_val = float(time_str)
                        if time_val < 0:
                            logger.warning(f"DELAY action has negative time, skipping")
                            continue
                    except ValueError:
                        logger.warning(f"DELAY action has invalid time: {time_str}, skipping")
                        continue
                else:
                    # All other actions are instant (no time entry)
                    time_val = 0.0
            
            phases.append((action, time_val))
        return phases
    
    def validate_action_phases(self) -> Tuple[bool, str]:
        """
        Validate that all action phases are valid.
        - Video Capture mode: GPIO actions require time
        - Image Capture mode: Only DELAY requires time
        
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not self.action_phases:
            return False, "At least one action phase is required"
        
        mode = self.capture_mode_var.get() if hasattr(self, 'capture_mode_var') else "Video Capture"
        
        for i, phase_data in enumerate(self.action_phases):
            action = phase_data["action_var"].get()
            
            if mode == "Video Capture":
                # Video Capture: GPIO actions require time entry
                if action in ["GPIO ON", "GPIO OFF"]:
                    time_str = phase_data["time_ent"].get().strip()
                    if not time_str:
                        return False, f"Phase {i + 1} ({action}) has no time specified"
                    try:
                        time_val = float(time_str)
                        if time_val < 0:
                            return False, f"Phase {i + 1} ({action}) has negative time"
                    except ValueError:
                        return False, f"Phase {i + 1} ({action}) has invalid time: {time_str}"
            else:
                # Image Capture: Only DELAY requires time entry
                if action == "DELAY":
                    time_str = phase_data["time_ent"].get().strip()
                    if not time_str:
                        return False, f"Phase {i + 1} (DELAY) has no time specified"
                    try:
                        time_val = float(time_str)
                        if time_val < 0:
                            return False, f"Phase {i + 1} (DELAY) has negative time"
                    except ValueError:
                        return False, f"Phase {i + 1} (DELAY) has invalid time: {time_str}"
                # All other actions are instant and don't need time validation
        
        return True, ""
    
    def export_experiment_settings(self) -> None:
        """Export current experiment settings to JSON file directly to experiments/ folder."""
        if not self.loaded_calibration:
            self.experiment_settings_status_label.config(text="Error: No calibration loaded. Cannot export settings.", fg="red")
            return
        
        # Get selected wells
        selected_wells = [label for label, var in self.well_checkboxes.items() if var.get()]
        if not selected_wells:
            self.experiment_settings_status_label.config(text="Error: No wells selected. Cannot export settings.", fg="red")
            return
        
        try:
            # Get action phases
            phases = self.get_action_phases()
            if not phases:
                raise ValueError("At least one action phase is required")
            
            # Validate phases
            is_valid, error_msg = self.validate_action_phases()
            if not is_valid:
                raise ValueError(error_msg)
            
            # Convert phases to list of dicts for export
            phases_data = [{"action": action, "time": time} for action, time in phases]
            
            settings = {
                "calibration_file": self.calibration_file,
                "selected_wells": selected_wells,
                "action_phases": phases_data,
                "resolution": list(self._get_resolution()),
                "fps": float(self.fps_ent.get().strip()),
                "export_type": self.export_var.get(),
                "motion_config_profile": self.motion_config_var.get(),
                "experiment_name": self.experiment_name_ent.get().strip(),
                "pattern": self.pattern_var.get()  # Stores format like "snake →↙" or "raster →↓"
            }
            
            # Ensure experiments folder exists
            success, error_msg = ensure_directory_exists(EXPERIMENTS_FOLDER)
            if not success:
                logger.error(error_msg)
                self.experiment_settings_status_label.config(text=error_msg, fg="red")
                return
            
            # Generate filename with date, time, and experiment name
            experiment_name = self.experiment_name_ent.get().strip() or "exp"
            date_time_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{date_time_str}_{experiment_name}_profile.json"
            filepath = os.path.join(EXPERIMENTS_FOLDER, filename)
            
            with open(filepath, 'w') as f:
                json.dump(settings, f, indent=2)
            
            # Truncate filename if too long
            display_name = filename[:40] + "..." if len(filename) > 40 else filename
            self.experiment_settings_status_label.config(text=f"Exported: {display_name}", fg="green")
            # Refresh the dropdown to include the new file
            self.refresh_experiment_settings()
            # Select the newly exported file
            self.experiment_settings_var.set(filename)
                
        except Exception as e:
            logger.error(f"Error exporting settings: {e}")
            error_msg = str(e)[:50] + "..." if len(str(e)) > 50 else str(e)
            self.experiment_settings_status_label.config(text=f"Error: {error_msg}", fg="red")
    

    def start(self) -> None:
        """
        Start the experiment.
        
        Validates inputs, configures camera, builds well sequence,
        and starts experiment execution in a separate thread.
        
        Note:
            - Requires calibration to be loaded (blocking)
            - Builds sequence from selected checkboxes
            - Uses interpolated positions from calibration
            - Requires 3 timing values (OFF, ON, OFF)
            - Builds sequence based on pattern (snake or raster)
            - Starts recording thread for video/still capture
        """
        if self.running:
            return
        
        # Check if running in simulation mode
        if self.simulate_3d or self.simulate_cam:
            sim_modes = []
            if self.simulate_3d:
                sim_modes.append("3D printer")
            if self.simulate_cam:
                sim_modes.append("camera")
            sim_text = " and ".join(sim_modes)
            error_msg = f"Unable to run experiment: Running in {sim_text} simulation mode"
            logger.error(error_msg)
            self.status_lbl.config(text=error_msg, fg="red")
            return
        
        # Validate calibration is loaded (blocking)
        if not self.loaded_calibration:
            logger.error("No calibration loaded")
            self.status_lbl.config(text="Error: No calibration loaded. Please load a calibration first.", fg="red")
            return
        
        # Get selected wells
        selected_wells = [label for label, var in self.well_checkboxes.items() if var.get()]
        if not selected_wells:
            logger.error("No wells selected")
            self.status_lbl.config(text="Error: No wells selected. Select at least one well.", fg="red")
            return
        
        try:
            # Get and validate action phases
            phases = self.get_action_phases()
            if not phases:
                logger.error("No action phases configured")
                self.status_lbl.config(text="Error: At least one action phase is required")
                return
            
            is_valid, error_msg = self.validate_action_phases()
            if not is_valid:
                logger.error(f"Invalid action phases: {error_msg}")
                self.status_lbl.config(text=f"Error: {error_msg}")
                return
            
            # Store phases for use in run_loop
            self.action_phases_list = phases
            
            # Get experiment name
            experiment_name = self.experiment_name_ent.get().strip() or "exp"
            
            # Get current date for folder and filename
            date_str = datetime.now().strftime("%Y%m%d")
            
            # Create output folder with date prefix: outputs/YYYYMMDD_experiment/
            output_folder = os.path.join(OUTPUTS_FOLDER, f"{date_str}_{experiment_name}")
            
            # Check directory permissions before parsing other inputs
            success, error_msg = ensure_directory_exists(output_folder)
            if not success:
                logger.error(error_msg)
                self.status_lbl.config(text=error_msg, fg="red")
                return
            
            # Get other settings (resolution from preset dropdown)
            try:
                res_x, res_y = self._get_resolution()
                fps = float(self.fps_ent.get().strip())
                export = self.export_var.get()
            except Exception as e:
                logger.error(f"Invalid inputs: {e}")
                self.status_lbl.config(text=f"Error: Invalid inputs - {e}")
                return
        except Exception as e:
            # Catch any unexpected errors in the try block above
            logger.error(f"Unexpected error: {e}")
            self.status_lbl.config(text=f"Error: {e}")
            return

        # Load motion configuration
        try:
            profile_name = self.motion_config_var.get()
            config_path = os.path.join("config", "motion_config.json")
            if os.path.exists(config_path):
                with open(config_path, 'r') as f:
                    motion_config_data = json.load(f)
                if profile_name in motion_config_data:
                    self.motion_config = motion_config_data[profile_name]
                    prelim = self.motion_config.get("preliminary", {})
                    between = self.motion_config.get("between_wells", {})
                    self.preliminary_feedrate = float(prelim.get("feedrate", 3000))
                    self.preliminary_acceleration = float(prelim.get("acceleration", 500))
                    self.between_wells_feedrate = float(between.get("feedrate", 5000))
                    self.between_wells_acceleration = float(between.get("acceleration", 1000))
                else:
                    # Use defaults if profile not found
                    logger.warning(f"Motion profile '{profile_name}' not found, using defaults")
                    self.motion_config = None
            else:
                # Use defaults if file not found
                logger.warning(f"Motion config file not found: {config_path}, using defaults")
                self.motion_config = None
        except Exception as e:
            logger.error(f"Error loading motion config: {e}, using defaults")
            self.motion_config = None

        # Get capture type and mode
        capture_type = self.capture_type_var.get()
        capture_mode = self.capture_mode_var.get() if hasattr(self, 'capture_mode_var') else "Video Capture"
        
        # Initialize capture manager if using high-FPS, Player One, or for Image Capture
        self.capture_manager: Optional[CaptureManager] = None
        if "High FPS" in capture_type:
            # Use capture manager for high-FPS modes
            try:
                self.capture_manager = CaptureManager(
                    capture_type=capture_type,
                    resolution=(res_x, res_y),
                    fps=fps
                )
                logger.info(f"Initialized {capture_type} capture manager: {res_x}x{res_y} @ {fps} FPS")
            except Exception as e:
                logger.error(f"Failed to initialize capture manager: {e}")
                self.status_lbl.config(text=f"Error: Failed to initialize {capture_type}", fg="red")
                return
        elif "Player One" in capture_type and self.usb_camera is not None and type(self.usb_camera).__name__ == "PlayerOneCamera":
            try:
                self.capture_manager = CaptureManager(
                    capture_type=capture_type,
                    resolution=(res_x, res_y),
                    fps=fps,
                    playerone_camera=self.usb_camera
                )
                logger.info(f"Initialized {capture_type} capture manager: {res_x}x{res_y} @ {fps} FPS")
            except Exception as e:
                logger.error(f"Failed to initialize capture manager: {e}")
                self.status_lbl.config(text=f"Error: Failed to initialize {capture_type}", fg="red")
                return
        else:
            # Use Picamera2 directly for Picamera2 modes
            if self.picam2 is None:
                logger.warning("Camera simulation mode: Skipping camera configuration")
                return
            
            if capture_mode == "Image Capture":
                # Configure for still image capture
                grayscale = "Grayscale" in capture_type
                if grayscale:
                    still_config = self.picam2.create_still_configuration(
                        main={'size': (res_x, res_y), 'format': 'YUV420'},
                        buffer_count=2
                    )
                else:
                    still_config = self.picam2.create_still_configuration(
                        main={'size': (res_x, res_y)},
                        buffer_count=2
                    )
                
                # Configure for still capture
                self.picam2.stop()
                self.picam2.configure(still_config)
                self.picam2.start()
                
                logger.info(f"Camera configured for image capture: {res_x}x{res_y} ({capture_type})")
            else:
                # Video Capture mode - configure for video recording
                preview_config = self.picam2.create_preview_configuration(
                    main={'size': (640, 480)},  # Lower resolution for preview
                    buffer_count=2
                )
                
                # Recording configuration optimized for maximum FPS
                grayscale = "Grayscale" in capture_type
                if grayscale:
                    video_config = self.picam2.create_video_configuration(
                        main={'size': (res_x, res_y), 'format': 'YUV420'},
                        controls={'FrameRate': fps},
                        buffer_count=2
                    )
                else:
                    video_config = self.picam2.create_video_configuration(
                        main={'size': (res_x, res_y)},
                        controls={'FrameRate': fps},
                        buffer_count=2  # Optimize buffer for recording
                    )
                
                # Configure for recording (preview not needed during experiment)
                self.picam2.stop()
                self.picam2.configure(video_config)
                self.picam2.start()
                
                logger.info(f"Camera configured for recording: {res_x}x{res_y} @ {fps} FPS ({capture_type})")

        # Select H264 encoder for video recording
        # Pass fps parameter to ensure FPS metadata is written to the H264 stream
        # This ensures accurate playback duration for scientific measurements
        # Note: fps parameter may not be supported in all picamera2 versions
        try:
            self.encoder = H264Encoder(bitrate=50_000_000, fps=fps)
        except TypeError:
            # Fallback for older picamera2 versions that don't support fps parameter
            logger.warning(f"H264Encoder doesn't support fps parameter, using default (fps will be in metadata JSON)")
            self.encoder = H264Encoder(bitrate=50_000_000)

        # Build sequence from calibration and selected wells
        interpolated_positions = self.loaded_calibration.get("interpolated_positions", [])
        labels = self.loaded_calibration.get("labels", [])
        
        # Create mapping from label to position
        label_to_pos = {}
        for i, label in enumerate(labels):
            if i < len(interpolated_positions):
                label_to_pos[label] = interpolated_positions[i]
        
        # Build sequence from selected wells
        selected_positions = []
        for label in selected_wells:
            if label in label_to_pos:
                pos = label_to_pos[label]
                # Extract row and column from label (e.g., "A1" -> row=0, col=0)
                row_letter = label[0]
                col_num = int(label[1:]) - 1
                row_num = ord(row_letter) - ord('A')
                selected_positions.append((pos[0], pos[1], pos[2], label, row_num, col_num))
        
        # Sort by pattern
        pattern = self.pattern_var.get()
        # Extract pattern name (handle both old format "snake"/"raster" and new format with symbols)
        if pattern.startswith("snake"):
            pattern = "snake"
        elif pattern.startswith("raster"):
            pattern = "raster"
        if pattern == "snake":
            # Snake pattern: alternate row direction
            selected_positions.sort(key=lambda x: (x[4], x[5] if x[4] % 2 == 0 else -x[5]))
        else:  # raster
            # Raster pattern: consistent direction
            selected_positions.sort(key=lambda x: (x[4], x[5]))
        
        # Build final sequence: (x, y, x_label, y_label)
        # Extract x_label and y_label from combined label
        self.seq = []
        for x, y, z, label, row_num, col_num in selected_positions:
            # Split label into row and column parts
            x_lbl = str(col_num + 1)  # Column number (1-based)
            y_lbl = label[0]  # Row letter
            self.seq.append((x, y, x_lbl, y_lbl))
        
        # Use Z from first position (all should be similar from interpolation)
        if selected_positions:
            self.z_val = selected_positions[0][2]  # Z from first position

        self.save_csv()
        # Calculate total time from all phases
        phase_total_time = sum(time for _, time in self.action_phases_list)
        self.total_time = len(self.seq) * phase_total_time
        self.duration_lbl.config(text=format_hms(self.total_time))
        self.start_ts, self.running, self.paused = time.time(), True, False

        def update_timers():
            if not self.running: return
            elapsed   = time.time() - self.start_ts
            remaining = max(0, self.total_time - elapsed)
            self.elapsed_lbl.config(text=format_hms(elapsed))
            self.remaining_lbl.config(text=format_hms(remaining))
            self.parent.after(200, update_timers)
        update_timers()

        def run_loop():
            # Store date_str and output_folder in closure for use in loop
            loop_date_str = date_str
            loop_output_folder = output_folder
            loop_experiment_name = experiment_name
            loop_capture_mode = self.capture_mode_var.get() if hasattr(self, 'capture_mode_var') else "Video Capture"
            
            # Apply preliminary motion settings before homing
            try:
                self.robocam.set_acceleration(self.preliminary_acceleration)
                logger.info(f"Applied preliminary acceleration: {self.preliminary_acceleration} mm/s²")
            except Exception as e:
                logger.warning(f"Could not set preliminary acceleration: {e}")
            
            try:
                self.status_lbl.config(text="Homing printer...")
                self.robocam.home()
                self.status_lbl.config(text="Homing complete")
            except Exception as e:
                logger.error(f"Homing failed: {e}")
                self.status_lbl.config(text=f"Error: Homing failed - {e}")
                self.running = False
                return
            
            # Apply between-wells motion settings for well movements
            try:
                self.robocam.set_acceleration(self.between_wells_acceleration)
                logger.info(f"Applied between-wells acceleration: {self.between_wells_acceleration} mm/s²")
            except Exception as e:
                logger.warning(f"Could not set between-wells acceleration: {e}")
            
            # Use between-wells feedrate from motion config
            use_feedrate = self.between_wells_feedrate
            
            for x_val, y_val, x_lbl, y_lbl in self.seq:
                if not self.running: break
                self.status_lbl.config(text=f"Moving to well {y_lbl}{x_lbl} at ({x_val:.2f}, {y_val:.2f})")
                try:
                    # Use Z value from calibration (stored in self.z_val)
                    self.robocam.move_absolute(X=x_val, Y=y_val, Z=self.z_val, speed=use_feedrate)
                    time.sleep(1)
                except Exception as e:
                    self.status_lbl.config(text=f"Error: Movement to {y_lbl}{x_lbl} failed - {e}")
                    self.running = False
                    break

                ts   = time.strftime("%H%M%S")
                ds   = loop_date_str  # Use YYYYMMDD format (set at start of experiment)
                
                # Ensure directory exists (should already be created, but double-check)
                success, error_msg = ensure_directory_exists(loop_output_folder)
                if not success:
                    logger.error(error_msg)
                    self.status_lbl.config(text=error_msg, fg="red")
                    self.running = False
                    break

                # Branch execution based on capture mode
                if loop_capture_mode == "Image Capture":
                    # === IMAGE CAPTURE MODE ===
                    # Wait for vibrations to settle
                    time.sleep(self.pre_recording_delay)
                    
                    # Track current GPIO state for image filenames
                    current_gpio_state = "OFF"  # Default to OFF
                    image_counter = 0
                    
                    # Execute action phases for image capture
                    for phase_idx, (action, phase_time) in enumerate(self.action_phases_list, 1):
                        if not self.running:
                            break
                        
                        logger.debug(f"Image Capture - Phase {phase_idx}: {action} for {phase_time}s")
                        
                        if action == "DELAY":
                            # Just wait for the specified time
                            self.status_lbl.config(text=f"Well {y_lbl}{x_lbl}: DELAY {phase_time}s (Phase {phase_idx}/{len(self.action_phases_list)})")
                            phase_start = time.time()
                            while time.time() - phase_start < phase_time and self.running:
                                time.sleep(0.05 if not self.paused else 0.1)
                        
                        elif action == "CAPTURE IMAGE":
                            # Capture image with GPIO state in filename
                            image_counter += 1
                            # Get export format from settings (default to PNG)
                            export_format = self.export_var.get() if hasattr(self, 'export_var') else "PNG"
                            ext = ".png" if export_format.upper() == "PNG" else ".jpg"
                            gpio_label = f"GPIO_{current_gpio_state}"
                            fname = f"{ds}_{ts}_{loop_experiment_name}_{y_lbl}{x_lbl}_{gpio_label}_img{image_counter}{ext}"
                            path = os.path.join(loop_output_folder, fname)
                            
                            self.status_lbl.config(text=f"Well {y_lbl}{x_lbl}: Capturing image {image_counter} (GPIO {current_gpio_state}) (Phase {phase_idx}/{len(self.action_phases_list)})")
                            
                            # Capture image using capture manager or picam2
                            try:
                                if self.capture_manager is not None:
                                    success = self.capture_manager.capture_image(path)
                                elif self.picam2 is not None:
                                    self.picam2.capture_file(path)
                                    success = True
                                else:
                                    logger.error("No camera available for image capture")
                                    success = False
                                
                                if success:
                                    logger.info(f"Captured image: {fname}")
                                    self.status_lbl.config(text=f"Well {y_lbl}{x_lbl}: Image {image_counter} saved")
                                else:
                                    logger.error(f"Failed to capture image: {fname}")
                                    self.status_lbl.config(text=f"Error: Failed to capture image {image_counter}", fg="red")
                            except Exception as e:
                                logger.error(f"Error capturing image: {e}")
                                self.status_lbl.config(text=f"Error capturing image: {e}", fg="red")
                        
                        elif action == "GPIO ON":
                            # Set GPIO ON (instant)
                            self.laser.switch(1)
                            self.laser_on = True
                            current_gpio_state = "ON"
                            self.status_lbl.config(text=f"Well {y_lbl}{x_lbl}: GPIO ON (Phase {phase_idx}/{len(self.action_phases_list)})")
                            # Instant action - no waiting
                        
                        elif action == "GPIO OFF":
                            # Set GPIO OFF (instant)
                            self.laser.switch(0)
                            self.laser_on = False
                            current_gpio_state = "OFF"
                            self.status_lbl.config(text=f"Well {y_lbl}{x_lbl}: GPIO OFF (Phase {phase_idx}/{len(self.action_phases_list)})")
                            # Instant action - no waiting
                        
                        else:
                            logger.warning(f"Unknown action in Image Capture mode: {action}")
                    
                    # Turn off GPIO at end of well if still on
                    if self.laser_on:
                        self.laser.switch(0)
                        self.laser_on = False
                    
                    self.status_lbl.config(text=f"Well {y_lbl}{x_lbl}: Done ({image_counter} images captured)")
                
                else:
                    # === VIDEO CAPTURE MODE (existing implementation) ===
                    use_playerone_capture = self.capture_manager is not None and "Player One" in self.capture_manager.get_capture_type()
                    ext = ".avi" if use_playerone_capture else ".h264"  # Player One uses AVI (FFV1); Pi HQ uses H264
                    fname = f"{ds}_{ts}_{loop_experiment_name}_{y_lbl}{x_lbl}{ext}"
                    path = os.path.join(loop_output_folder, fname)

                    # Video recording (H264)
                    # Calculate total expected duration from all phases
                    total_duration = sum(time for _, time in self.action_phases_list)
                    
                    # Wait for vibrations to settle before recording
                    time.sleep(self.pre_recording_delay)
                    
                    # Log recording start with FPS information
                    logger.info(f"Starting video recording: {fname} @ {fps} FPS, expected duration: {total_duration}s")
                    
                    recording_start_time = time.time()
                    
                    # Check if using capture manager (high-FPS or Player One) - frame buffering and encode on stop
                    use_capture_manager_video = (
                        self.capture_manager is not None
                        and ("High FPS" in self.capture_manager.get_capture_type() or "Player One" in self.capture_manager.get_capture_type())
                    )
                    if use_capture_manager_video:
                        # Use capture manager (high-FPS or Player One): buffer frames, encode on stop
                        codec = "FFV1"
                        success = self.capture_manager.start_video_recording(path, codec=codec)
                        if not success:
                            logger.error("Failed to start recording")
                            self.status_lbl.config(text="Recording failed", fg="red")
                            continue
                        self.recording = True
                        self.start_recording_flash()
                        for phase_idx, (action, phase_time) in enumerate(self.action_phases_list, 1):
                            if not self.running:
                                break
                            state = 1 if action == "GPIO ON" else 0
                            self.laser.switch(state)
                            self.laser_on = (state == 1)
                            phase_start = time.time()
                            action_name = "ON" if action == "GPIO ON" else "OFF"
                            self.status_lbl.config(text=f"Well {y_lbl}{x_lbl}: Recording - {action_name} for {phase_time}s (Phase {phase_idx}/{len(self.action_phases_list)})")
                            frame_interval = 1.0 / fps
                            last_frame_time = time.time()
                            while time.time() - phase_start < phase_time and self.running:
                                current_time = time.time()
                                if current_time - last_frame_time >= frame_interval:
                                    self.capture_manager.capture_frame_for_video()
                                    last_frame_time = current_time
                                time.sleep(0.01)
                        output_path = self.capture_manager.stop_video_recording(codec=codec)
                        if output_path is None:
                            logger.error("Failed to save video")
                            self.recording = False
                            self.stop_recording_flash()
                            continue
                    else:
                        # Use Picamera2 encoder-based recording
                        output_path = path  # For metadata; H264 path
                        output = FileOutput(path)
                        if self.picam2 is not None:
                            self.picam2.start_recording(self.encoder, output)
                        else:
                            logger.info(f"[CAMERA SIMULATION] Would start recording video to: {output.fileoutput}")
                        self.recording = True
                        self.start_recording_flash()

                        # Execute all action phases
                        for phase_idx, (action, phase_time) in enumerate(self.action_phases_list, 1):
                            if not self.running:
                                break
                            
                            # Determine GPIO state
                            state = 1 if action == "GPIO ON" else 0
                            self.laser.switch(state)
                            self.laser_on = (state == 1)
                            
                            # Wait for phase duration
                            phase_start = time.time()
                            action_name = "ON" if action == "GPIO ON" else "OFF"
                            self.status_lbl.config(text=f"Well {y_lbl}{x_lbl}: Recording - {action_name} for {phase_time}s (Phase {phase_idx}/{len(self.action_phases_list)})")
                            while time.time() - phase_start < phase_time and self.running:
                                time.sleep(0.05 if not self.paused else 0.1)

                        try:
                            if self.picam2 is not None:
                                self.picam2.stop_recording()
                            else:
                                logger.info("[CAMERA SIMULATION] Would stop recording")
                        except:
                            pass
                    
                    # Calculate actual recording duration and verify FPS
                    recording_end_time = time.time()
                    actual_duration = recording_end_time - recording_start_time
                    expected_duration = total_duration
                    duration_diff = abs(actual_duration - expected_duration)
                    
                    # Log actual vs expected duration
                    logger.info(f"Recording completed: {fname} - Actual duration: {actual_duration:.2f}s, Expected: {expected_duration:.2f}s, Difference: {duration_diff:.2f}s")
                    
                    # Warn if duration differs significantly (more than 5% or 1 second)
                    if duration_diff > max(0.05 * expected_duration, 1.0):
                        logger.warning(f"Recording duration mismatch for {fname}: Expected {expected_duration:.2f}s, got {actual_duration:.2f}s. "
                                     f"This may indicate FPS issues. Configured FPS: {fps}")
                    
                    # Save metadata file with FPS and recording information
                    well_label = f"{y_lbl}{x_lbl}"
                    timestamp_str = f"{ds}_{ts}"
                    # Use output_path if capture manager was used (high-FPS or Player One), otherwise use path
                    video_path_for_metadata = output_path if (self.capture_manager is not None and ("High FPS" in self.capture_manager.get_capture_type() or "Player One" in self.capture_manager.get_capture_type())) else path
                    save_video_metadata(
                        video_path=video_path_for_metadata,
                        target_fps=fps,
                        resolution=(res_x, res_y),
                        duration_seconds=expected_duration,
                        format_type=export,
                        well_label=well_label,
                        timestamp=timestamp_str,
                        actual_duration=actual_duration
                    )
                    
                    self.recording = False
                    self.stop_recording_flash()
                    self.status_lbl.config(text=f"Well {y_lbl}{x_lbl}: Done")

            self.running = False
            if self.recording:
                self.stop_recording_flash()
            self.status_lbl.config(text="Experiment completed")
            
            # Convert H264 to MP4 if enabled
            if (hasattr(self, 'convert_to_mp4_var') and self.convert_to_mp4_var.get() and
                loop_capture_mode == "Video Capture"):
                # Check if export type is H264
                export_type = self.export_var.get() if hasattr(self, 'export_var') else "H264"
                if export_type == "H264":
                    self.status_lbl.config(text="Experiment completed. Converting H264 to MP4...")
                    logger.info(f"Starting H264 to MP4 conversion for folder: {loop_output_folder}")
                    success_count, total_count = convert_all_h264_in_folder(loop_output_folder)
                    if success_count == total_count and total_count > 0:
                        self.status_lbl.config(text=f"Experiment completed. Converted {success_count} video(s) to MP4.")
                        logger.info(f"Successfully converted all {success_count} H264 file(s) to MP4")
                    elif success_count > 0:
                        self.status_lbl.config(text=f"Experiment completed. Converted {success_count}/{total_count} video(s) to MP4 (some failed).")
                        logger.warning(f"Partially converted: {success_count}/{total_count} H264 files to MP4")
                    elif total_count > 0:
                        self.status_lbl.config(text="Experiment completed. MP4 conversion failed (see logs).")
                        logger.error(f"Failed to convert H264 files to MP4")
                    else:
                        self.status_lbl.config(text="Experiment completed.")
                else:
                    self.status_lbl.config(text="Experiment completed.")
            else:
                self.status_lbl.config(text="Experiment completed.")

        self.thread = threading.Thread(target=run_loop, daemon=True)
        self.thread.start()

    def pause(self) -> None:
        """
        Pause or resume the experiment.
        
        Toggles pause state. When paused, movement and recording continue
        but timing loops wait longer between checks.
        """
        if self.running:
            self.paused = not self.paused

    def start_recording_flash(self) -> None:
        """Start flashing the recording button."""
        if not hasattr(self, 'recording_btn'):
            return
        self.recording_btn.config(state="normal", bg="red", text="● REC")
        self.recording_flash_state = True
        self.flash_recording_button()
    
    def stop_recording_flash(self) -> None:
        """Stop flashing the recording button."""
        if not hasattr(self, 'recording_btn'):
            return
        self.recording_flash_state = False
        if self.recording_flash_job:
            self.parent.after_cancel(self.recording_flash_job)
            self.recording_flash_job = None
        self.recording_btn.config(state="disabled", bg="gray", text="● REC")
    
    def flash_recording_button(self) -> None:
        """Flash the recording button between red and dark red."""
        if not self.recording_flash_state or not hasattr(self, 'recording_btn'):
            return
        if self.recording_btn.cget("bg") == "red":
            self.recording_btn.config(bg="darkred")
        else:
            self.recording_btn.config(bg="red")
        self.recording_flash_job = self.parent.after(500, self.flash_recording_button)
    
    def stop(self) -> None:
        """
        Stop the experiment.
        
        Stops experiment execution, turns off laser, and stops recording.
        Safe to call even if experiment is not running.
        """
        self.running = False
        if self.laser_on:
            try:
                self.laser.switch(0)
            except Exception:
                pass
            self.laser_on = False
        if self.recording:
            try:
                if self.capture_manager is not None and ("High FPS" in self.capture_manager.get_capture_type() or "Player One" in self.capture_manager.get_capture_type()):
                    self.capture_manager.stop_video_recording(codec="FFV1")
                elif self.picam2 is not None:
                    self.picam2.stop_recording()
            except Exception:
                pass
            self.recording = False
            self.stop_recording_flash()
        
        # Cleanup capture manager
        if hasattr(self, 'capture_manager') and self.capture_manager is not None:
            try:
                self.capture_manager.cleanup()
            except Exception as e:
                logger.warning(f"Error cleaning up capture manager: {e}")

if __name__ == "__main__":
    """
    Main entry point for experiment application.
    
    Opens the experiment configuration and execution interface directly.
    """
    import argparse
    
    parser = argparse.ArgumentParser(description="RoboCam Experiment - Automated well-plate experiment execution")
    parser.add_argument(
        "--simulate_3d",
        action="store_true",
        help="Run in 3D printer simulation mode (no printer connection, movements are simulated)"
    )
    parser.add_argument(
        "--simulate_cam",
        action="store_true",
        help="Run in camera simulation mode (no camera connection, capture operations are skipped)"
    )
    args = parser.parse_args()
    
    root: tk.Tk = tk.Tk()
    # Load config for baudrate
    config = get_config()
    baudrate = config.get("hardware.printer.baudrate", 115200)
    robocam: RoboCam = RoboCam(baudrate=baudrate, config=config, simulate_3d=args.simulate_3d)
    
    # Initialize camera: use first found (Pi HQ or Player One; only one in system at a time)
    picam2: Optional[Picamera2] = None
    usb_camera = None
    if args.simulate_cam:
        print("Camera simulation mode: Skipping camera initialization")
    else:
        backend = detect_camera()
        if backend == "pihq":
            picam2 = Picamera2()
            print("Camera started (Pi HQ)")
        elif isinstance(backend, tuple) and backend[0] == "playerone":
            usb_camera = PlayerOneCamera(resolution=(1920, 1080), fps=30.0, camera_index=backend[1])
            print("Camera started (Player One)")
        else:
            raise RuntimeError("No camera found. Connect a Raspberry Pi HQ camera or Player One (Mars 662M).")

    app: ExperimentWindow = ExperimentWindow(
        root, picam2, robocam,
        usb_camera=usb_camera,
        simulate_3d=args.simulate_3d, simulate_cam=args.simulate_cam
    )
    app.open()  # Open experiment window directly
    root.mainloop()
