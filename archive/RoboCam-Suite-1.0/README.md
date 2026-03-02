# RoboCam-Suite

Robotic microscopy system for automated well-plate experiments using a 3D printer as a positioning stage, Raspberry Pi camera for imaging, and GPIO-controlled laser for stimulation.

## Overview

RoboCam-Suite is a scientific experiment automation system designed for FluorCam, StentorCam, and other automated microscopy experiments under the RoboCam umbrella. It provides precise robotic positioning, automated video/still capture, and laser control for biological experiments. The system consists of three main applications:

- **calibrate.py**: Manual positioning and calibration GUI for setting up well-plate coordinates
- **preview.py**: Sequential well alignment preview tool for verifying positions before experiments
- **experiment.py**: Automated experiment execution GUI with configurable timing sequences

## Features

- **Automated Well-Plate Scanning**: Navigate to multiple well positions automatically
- **High-Performance Camera Preview**: Native hardware-accelerated preview (DRM/QTGL) with FPS tracking
  - Configurable preview resolution (default: 800x600) and frame rate (default: 30 FPS)
  - Optimized for maximum performance with hardware acceleration
- **4-Corner Path Calibration**: Guided calibration procedure to account for angled well plates with automatic bilinear interpolation (properly handles rotation and skew)
- **Go to Coordinate**: Direct navigation to specific X, Y, Z coordinates in calibration mode
- **Video/Still Capture**: Record videos or capture still images at each well
  - **Multiple Capture Types**: Choose from multiple capture modes:
    - **Picamera2 (Color)**: Standard color capture using Picamera2 API
    - **Picamera2 (Grayscale)**: Grayscale capture using Picamera2 with YUV420 format
    - **Picamera2 (Grayscale - High FPS)**: High-FPS grayscale capture (100+ FPS) using Picamera2 with FFmpeg hardware encoding (requires ffmpeg)
    - **rpicam-vid (Grayscale - High FPS)**: High-FPS grayscale capture using rpicam-vid command-line tool (optional)
  - **Quick Capture**: Instant image or video capture in calibrate.py and preview.py
  - **Minimal Compression**: Video saved with lossless FFV1 codec for maximum data preservation
  - **Accurate FPS Recording**: FPS metadata embedded in H264 videos and saved in JSON metadata files
  - **Real-Time Playback**: Ensures videos play at correct speed for scientific velocity measurements
  - **FPS Metadata Files**: JSON metadata files saved alongside videos with FPS, resolution, and duration information
- **Laser Control**: GPIO-controlled laser with configurable timing sequences (OFF-ON-OFF)
- **Simulation Modes**: Test workflows without hardware using `--simulate_3d` and `--simulate_cam` flags
  - `--simulate_3d`: Simulates 3D printer (movements update position tracking, but no actual hardware movement)
  - `--simulate_cam`: Simulates camera (skips camera initialization and capture operations)
  - Perfect for testing experiment configurations and calibration procedures
- **Configurable Experiments**: JSON-based configuration for experiment parameters
- **Motion Configuration**: Separate feedrate and acceleration settings for preliminary and between-wells movements
- **Calibration-Based Experiments**: Load calibrations and select wells via checkbox grid
- **Preview Alignment Tool**: Sequential well position preview for alignment verification before experiments
- **Experiment Settings Export/Import**: Save and load experiment configurations with calibration validation
- **CSV Export**: Export well coordinates and labels for analysis
- **Configurable Timeouts**: Customizable timeouts for homing (default: 45s) and movement commands (default: 30s)

## Hardware Requirements

**Note: This software is designed for Raspberry Pi only and requires Raspberry Pi hardware.**

- **Raspberry Pi** (with Raspberry Pi OS)
- **Raspberry Pi Camera Module** (Picamera2 compatible)
- **3D Printer** (modified as positioning stage, G-code compatible)
- **GPIO Laser Module** (connected to GPIO pin, default: GPIO 21)
- **USB Serial Connection** to 3D printer (default baudrate: 115200)

## Software Requirements

**Note: This software requires Raspberry Pi OS and cannot run on Windows or macOS.**

- Python 3.7 or higher
- Raspberry Pi OS (required - not compatible with Windows/macOS)
- System dependencies (installed via apt):
  - `python3-libcamera` (required for picamera2)
  - `ffmpeg` (required for Picamera2 high-FPS capture with hardware encoding)
  - `raspberrypi-userland` (contains `raspividyuv` command-line tool for high-FPS grayscale capture, optional)
  - `libcap-dev` (required to build python-prctl)
  - `python3-dev` (required to build Python packages)
  - `build-essential` (required to build Python packages)
- Required Python packages (see `requirements.txt`)
- RPi.GPIO library (installed via system package manager on Raspberry Pi)

**Note**: The setup script automatically installs system dependencies. The virtual environment is created with `--system-site-packages` to access system-installed packages like `python3-libcamera`.

## Installation

### Quick Setup

**Note: This software is designed for Raspberry Pi OS (Linux) only. All commands assume Raspberry Pi hardware and operating system.**

1. Clone or download this repository:
```bash
git clone <repository-url>
cd RoboCam-Suite
```

2. Run the setup script to create a virtual environment and install dependencies:
```bash
chmod +x setup.sh
./setup.sh
```

3. The setup script will:
   - Check for Python 3.x
   - Check for and install required system dependencies (`python3-libcamera`, `ffmpeg`, `raspberrypi-userland`, `libcap-dev`, `python3-dev`, `build-essential`)
   - Verify `ffmpeg` command is available (for Picamera2 high-FPS capture with hardware encoding)
   - Verify `raspividyuv` command is available (for high-FPS grayscale capture mode, optional)
   - Create a virtual environment in `venv/` with system site packages enabled (to access system-installed packages like `python3-libcamera`)
   - Install all required Python dependencies
   - Create configuration directories
   - Set up template configuration files

### Manual Installation

1. Install system dependencies:
```bash
sudo apt-get update
sudo apt-get install -y python3-libcamera ffmpeg raspberrypi-userland libcap-dev python3-dev build-essential
```

**Note**: The `raspberrypi-userland` package contains the `raspividyuv` command-line tool, which is required for the "raspividyuv (Grayscale - High FPS)" capture mode. 

**Important**: On newer Raspberry Pi OS versions (using libcamera), the `raspberrypi-userland` package may not be available in repositories. In this case:
- The setup script will detect this and provide instructions
- You can build from source if you need the legacy camera tools:
  ```bash
  git clone https://github.com/raspberrypi/userland.git
  cd userland
  ./buildme
  ```
- Alternatively, use "Picamera2 (Grayscale)" capture mode, which works on all systems
- If the command is installed but not in PATH, it may be at `/opt/vc/bin/raspividyuv`. Create a symlink:
  ```bash
  sudo ln -s /opt/vc/bin/raspividyuv /usr/local/bin/raspividyuv
  ```

2. Create a virtual environment with system site packages (required to access `python3-libcamera`):
```bash
python3 -m venv --system-site-packages venv
source venv/bin/activate
```

**Note**: The `--system-site-packages` flag is required so the virtual environment can access system-installed packages like `python3-libcamera`, which is needed by `picamera2`.

3. Install dependencies:
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

4. Create configuration directories:
```bash
mkdir -p calibrations
mkdir -p config/templates
```

## Quick Start

### Starting the Calibration Application

```bash
./start_calibrate.sh
# Or manually:
source venv/bin/activate
python calibrate.py
# Or with simulation modes (no hardware required):
python calibrate.py --simulate_3d  # Simulate 3D printer only
python calibrate.py --simulate_cam  # Simulate camera only
python calibrate.py --simulate_3d --simulate_cam  # Simulate both
```

### Starting the Preview Application

```bash
./start_preview.sh
# Or manually:
source venv/bin/activate
python preview.py
# Or with backend selection:
python preview.py --backend auto
# Or with simulation modes (no hardware required):
python preview.py --simulate_3d  # Simulate 3D printer only
python preview.py --simulate_cam  # Simulate camera only (no preview window)
python preview.py --simulate_3d --simulate_cam  # Simulate both
```

### Starting the Experiment Application

```bash
./start_experiment.sh
# Or manually:
source venv/bin/activate
python experiment.py
# Or with simulation modes (no hardware required):
python experiment.py --simulate_3d  # Simulate 3D printer only
python experiment.py --simulate_cam  # Simulate camera only
python experiment.py --simulate_3d --simulate_cam  # Simulate both
```

## Usage

### Calibration (calibrate.py)

1. Launch the calibration application:
   ```bash
   ./start_calibrate.sh
   # Or: python calibrate.py --backend auto
   # Or: python calibrate.py --simulate_3d  # Test without 3D printer
   # Or: python calibrate.py --simulate_cam  # Test without camera
   ```

2. Two windows will open:
   - **Camera Preview Window**: Native hardware-accelerated preview (high performance)
   - **Controls Window**: Movement controls, position display, and FPS monitoring

3. Use the controls window to:
   - Navigate to well positions using directional buttons
   - Adjust step size (0.1 mm, 1.0 mm, or 10.0 mm)
   - **Go to Coordinate**: Enter X, Y, Z coordinates and click "Go" to move directly to that position
   - Home the printer using the "Home" button (timeout: 90 seconds / 1.5 minutes, configurable)
   - Monitor position and preview FPS

4. Use the camera preview window to visually align with wells

5. Record positions for calibration (see User Guide for 4-corner calibration)

**Preview Backends**: Use `--backend auto` (default), `qtgl`, `drm`, or `null` for headless mode

**Simulation Modes**: 
- `--simulate_3d`: Run without 3D printer hardware. Movements are simulated (position tracking updates without actual hardware movement).
- `--simulate_cam`: Run without camera hardware. Skips camera initialization (no preview window).
- Window title shows "[3D PRINTER SIM]" and/or "[CAMERA SIM]" when active.

### Preview Alignment Check (preview.py)

1. Launch the preview application:
   ```bash
   source venv/bin/activate
   python preview.py
   # Or: python preview.py --backend auto
   # Or: python preview.py --simulate_3d  # Test without 3D printer
   # Or: python preview.py --simulate_cam  # Test without camera (no preview window)
   ```

2. Two windows will open:
   - **Camera Preview Window**: Native hardware-accelerated preview (high performance)
   - **Controls Window**: Well display, navigation controls, and status display

3. Load wells:
   - Select source type: "Calibration File" or "Experiment Save File"
   - Click "Load" and select the appropriate file
   - For calibration files: All wells are loaded
   - For experiment save files: Only checked wells from the experiment are loaded

4. Choose view mode (optional):
   - Use "View:" dropdown to switch between "list" and "graphical" views
   - **List View**: Scrollable list of wells (default)
   - **Graphical View**: Visual grid of wells arranged in x×y layout
     - Click any well button to navigate directly
     - When loaded from experiment: irrelevant wells are grayed out
     - Window automatically resizes to fit the grid

5. Home the printer (optional):
   - Click "Home Printer" button if you want to start from origin
   - Navigation works from current position - homing is not required

6. Navigate through wells:
   - **List View**: Click on a well in the list to select it, then click "Go to Selected"
   - **Graphical View**: Click directly on any well button to navigate to it
   - Use "Previous" and "Next" buttons for sequential navigation (works in both views)
   - Use camera preview to verify alignment at each position

6. Verify alignment before running experiments

**Preview Backends**: Use `--backend auto` (default), `qtgl`, `drm`, or `null` for headless mode

**Simulation Modes**: 
- `--simulate_3d`: Run without 3D printer hardware. Movements are simulated (position tracking updates without actual hardware movement).
- `--simulate_cam`: Run without camera hardware. Skips camera initialization (no preview window).
- Window title shows "[3D PRINTER SIM]" and/or "[CAMERA SIM]" when active.

### Experiment Setup (experiment.py)

1. Launch the experiment application:
   ```bash
   ./start_experiment.sh
   # Or: python experiment.py
   # Or: python experiment.py --simulate_3d  # Test without 3D printer
   # Or: python experiment.py --simulate_cam  # Test without camera
   ```
2. Click "Open Experiment" to open the experiment configuration window
3. **Load Calibration** (Required):
   - Select a calibration from the dropdown (calibrations saved from calibrate.py)
   - Calibration must be loaded before experiment can start
   - Checkbox grid will appear showing all available wells
4. **Select Wells**:
   - Use checkboxes to select which wells to include in experiment
   - All wells are checked by default
   - Uncheck wells you want to skip
5. Configure GPIO action phases:
   - By default, one GPIO OFF phase is present (30 seconds)
   - Click "Add Action" to add more phases
   - For each phase, select "GPIO ON" or "GPIO OFF" and enter duration in seconds
   - Example: OFF (30s) → ON (20s) → OFF (10s)
6. Select pattern: "snake →↙" (zig-zag) or "raster →↓" (rectilinear, default)
7. Configure camera settings:
   - Resolution (X and Y)
   - FPS
   - Export type (H264)
8. Set feedrate override (optional, mm/min)
9. Select motion configuration file (for feed/acceleration settings)
10. Set experiment name (files use format: `{date}_{time}_{experiment_name}_{y}{x}.{ext}`)
11. **Export/Load Settings** (Optional):
    - Click "Export" to save current configuration directly to `experiments/` folder
    - Select from "Experiment Settings" dropdown to load saved configuration (similar to calibration dropdown)
    - Click "Refresh" to update the list of available settings
    - Calibration file must exist for import to succeed
12. Click "Run" to start the experiment

### Configuration Files

#### Calibration Files (calibrations/*.json)

Calibration files are automatically saved with a date and time prefix in format `YYYYMMDD_HHMMSS` (e.g., `20241215_143022_well_plate_8x6.json`). They store 4-corner calibration data with interpolated well positions:

```json
{
  "name": "well_plate_8x6",
  "upper_left": [8.0, 150.0, 157.0],
  "lower_left": [6.1, 77.7, 157.0],
  "upper_right": [98.1, 143.4, 157.0],
  "lower_right": [97.1, 78.7, 157.0],
  "x_quantity": 8,
  "y_quantity": 6,
  "interpolated_positions": [[8.0, 150.0, 157.0], [19.0, 150.0, 157.0], ...],
  "labels": ["A1", "A2", "A3", ..., "F8"]
}
```

#### Experiment Settings Export

Users can export experiment settings to JSON files for reuse. The filename format is `{date}_{time}_{exp}_profile.json` where:
- `{date}`: Date in YYYYMMDD format (e.g., "20241215")
- `{time}`: Time in HHMMSS format (e.g., "143022")
- `{exp}`: Experiment name from the "Experiment Name" field

Example: `20241215_143022_exp_profile.json`

```json
{
  "calibration_file": "20240115_143022_well_plate_8x6.json",
  "selected_wells": ["A1", "A2", "B1", "B3"],
  "action_phases": [
    {"action": "GPIO OFF", "time": 30.0},
    {"action": "GPIO ON", "time": 20.0},
    {"action": "GPIO OFF", "time": 10.0}
  ],
  "resolution": [1920, 1080],
  "fps": 30.0,
  "export_type": "H264",
  "quality": 85,
  "motion_config_profile": "default",
  "experiment_name": "exp",
  "pattern": "raster →↓"
}
```

#### Motion Configuration (config/motion_config.json)

Motion profiles define feedrate and acceleration settings for different use cases. All profiles are stored in a single file `config/motion_config.json`:

```json
{
  "default": {
    "name": "Default Profile",
    "description": "Balanced speed and precision for general use",
    "preliminary": {
      "feedrate": 3000,
      "acceleration": 500
    },
    "between_wells": {
      "feedrate": 1200,
      "acceleration": 300
    }
  },
  "precise": {
    "name": "Precise Profile",
    "description": "Lower speed and acceleration for maximum precision",
    "preliminary": {
      "feedrate": 2000,
      "acceleration": 300
    },
    "between_wells": {
      "feedrate": 3000,
      "acceleration": 500
    }
  },
  "fast": {
    "name": "Fast Profile",
    "description": "Maximum speed for rapid well-to-well movements",
    "preliminary": {
      "feedrate": 5000,
      "acceleration": 1000
    },
    "between_wells": {
      "feedrate": 8000,
      "acceleration": 1500
    }
  }
}
```

- **preliminary**: Used for homing and initial positioning moves
- **between_wells**: Used for movements between wells during experiment

Available profiles in `config/motion_config.json`:
- **default**: Balanced speed and precision
- **precise**: Lower speed/acceleration for maximum precision
- **fast**: High speed/acceleration for rapid experiments

## File Naming

Files are automatically named using a fixed format: `{date}_{time}_{experiment_name}_{y}{x}.{ext}`

The format includes:
- `{date}`: Date in YYYYMMDD format (e.g., "20241215", "20240103")
- `{time}`: Timestamp in HHMMSS format (e.g., "143022", "091530")
- `{experiment_name}`: Experiment name from "Experiment Name" field (default: "exp")
- `{y}`: Row letter (e.g., "A", "B", "C")
- `{x}`: Column number (e.g., "1", "2", "3")
- `{ext}`: File extension based on export type (`.h264`)

Example: Experiment name "exp", well B2, captured at 14:30:22 on December 15th, 2024 → `20241215_143022_exp_B2.h264`

## Output Files

### CSV Export ({date}_{time}_{exp}_points.csv)

The experiment generates a CSV file with well coordinates in `outputs/YYYYMMDD_{experiment_name}/`. The filename format is `{date}_{time}_{exp}_points.csv` where:
- `{date}`: Date in YYYYMMDD format (e.g., "20241215")
- `{time}`: Time in HHMMSS format (e.g., "143022")
- `{exp}`: Experiment name from the "Experiment Name" field

Example: `outputs/20241215_exp/20241215_143022_exp_points.csv`

```csv
xlabel,ylabel,xval,yval,zval
2,B,66.6,107.1,86.4
5,B,93.6,107.1,86.4
...
```

### Video/Image Files

Videos or images are automatically saved to `outputs/YYYYMMDD_{experiment_name}/` with the fixed filename format, where:
- `YYYYMMDD` is the date when the experiment is run (e.g., "20241215")
- `{experiment_name}` is the value from the "Experiment Name" field

**FPS Metadata Files**: For each video recording, a JSON metadata file is automatically saved alongside the video with the format `{video_filename}_metadata.json`. This file contains:
- **FPS**: Frame rate used for recording (critical for accurate playback)
- **Resolution**: Video resolution (width, height)
- **Duration**: Expected recording duration in seconds
- **Format**: Video format (H264)
- **Timestamp**: Recording timestamp
- **Well Label**: Well identifier (e.g., "A1")

**Example metadata file** (`20241215_143022_exp_B2_metadata.json`):
```json
{
  "fps": 30.0,
  "resolution": [1920, 1080],
  "duration_seconds": 30.0,
  "format": "H264",
  "timestamp": "20241215_143022",
  "well_label": "B2",
  "video_file": "20241215_143022_exp_B2.h264"
}
```

**FPS Accuracy**:
- **H264 videos**: FPS metadata is embedded directly in the video file for accurate playback

**Directory Creation**: The application automatically creates the `outputs/YYYYMMDD_{experiment_name}/` directory if it doesn't exist. If you encounter permission errors, the application will identify the issue and provide specific fix instructions. To manually set up the directory:
```bash
mkdir -p outputs
chmod 777 outputs
```

### Experiment Settings Export

Exported experiment settings (profile JSON files) are saved to `experiments/` folder. The export happens automatically without a file dialog - files are named with format `{date}_{time}_{exp}_profile.json`.

## Configuration

### Configurable Settings

The system uses `config/default_config.json` for configuration. Key settings include:

#### Printer Settings

- **Timeouts**:
  - `home_timeout`: Timeout for homing command (default: 90.0 seconds / 1.5 minutes)
  - `movement_wait_timeout`: Timeout for movement completion (default: 30.0 seconds)
  - Can be overridden via environment variables: `ROBOCAM_HOME_TIMEOUT`, `ROBOCAM_MOVEMENT_WAIT_TIMEOUT`
- **Baudrate**: Serial communication baudrate (default: 115200)
- **Connection Settings**: Retry delays and max retries

#### Camera Settings

- **Preview Resolution**: Default 800x600 (configurable via `hardware.camera.preview_resolution`)
- **Frame Rate**: Default 30.0 FPS (configurable via `hardware.camera.default_fps`)
- **Preview Backend**: Auto-selected (configurable via `hardware.camera.preview_backend`)

#### Laser Settings

- **GPIO Pin**: Default GPIO 21 (configurable via `hardware.laser.gpio_pin`)
- **Default State**: OFF (configurable via `hardware.laser.default_state`)

### Environment Variable Overrides

You can override configuration values using environment variables:

```bash
export ROBOCAM_HOME_TIMEOUT=60.0
export ROBOCAM_MOVEMENT_WAIT_TIMEOUT=45.0
export ROBOCAM_BAUDRATE=9600
```

## Troubleshooting

### Installation Issues

- **Problem**: `setup.sh` fails with "Failed to build 'python-prctl'" or "You need to install libcap development headers"
- **Solution**: 
  - The setup script will now automatically detect and install missing system dependencies
  - If automatic installation fails, manually install: `sudo apt-get update && sudo apt-get install -y libcap-dev python3-dev build-essential`
  - Then re-run `./setup.sh` or use the quick fix: `./fix_dependencies.sh`

- **Problem**: `ModuleNotFoundError: No module named 'picamera2'` when running scripts
- **Solution**:
  - Ensure the virtual environment is activated: `source venv/bin/activate`
  - Verify packages are installed: `pip list | grep picamera2`
  - If missing, install system dependencies (see above) and reinstall: `pip install -r requirements.txt`
  - Use the provided fix script: `chmod +x fix_dependencies.sh && ./fix_dependencies.sh`

- **Problem**: `ModuleNotFoundError: No module named 'libcamera'` when running scripts
- **Solution**:
  - Install the system package: `sudo apt-get install -y python3-libcamera`
  - This is a system-level package required by picamera2, not installable via pip
  - The virtual environment must be created with `--system-site-packages` to access system packages
  - If your venv was created without this flag, recreate it: `rm -rf venv && python3 -m venv --system-site-packages venv`
  - The updated setup script now checks for and installs this automatically
  - Or use the fix script: `chmod +x fix_dependencies.sh && ./fix_dependencies.sh` (automatically fixes venv)

### Serial Port Connection Issues

- **Problem**: Cannot connect to 3D printer
- **Solution**: 
  - Check USB connection
  - Verify baudrate matches printer settings (default: 115200)
  - Check serial port permissions: `sudo usermod -a -G dialout $USER`
  - Restart after adding user to dialout group

### Camera Not Found

- **Problem**: Camera initialization fails
- **Solution**:
  - Ensure camera is enabled: `sudo raspi-config` → Interface Options → Camera
  - Check camera connection
  - Verify Picamera2 is installed correctly

### ffmpeg Not Found

- **Problem**: "FFmpeg executable not found" error when using Picamera2 (Grayscale - High FPS) capture mode
- **Note**: FFmpeg is often **already installed** on Raspberry Pi OS. Check first: `ffmpeg -version`
- **Solution**:
  - **Check if already installed**: `ffmpeg -version` (if it works, you're all set!)
  - **Automatic**: The setup script (`./setup.sh`) automatically detects and installs ffmpeg if missing
  - **Manual installation** (if needed): 
    ```bash
    sudo apt-get update
    sudo apt-get install -y ffmpeg
    ```
  - **Verify installation**: `ffmpeg -version`
  - **Check hardware encoder**: `ffmpeg -encoders | grep v4l2m2m` (should show h264_v4l2m2m)
  - **Note**: ffmpeg is required for hardware-accelerated video encoding in high-FPS capture mode. Without it, the `record_with_ffmpeg()` method will fail.
  - **Detailed guide**: See [FFMPEG_INSTALLATION.md](docs/FFMPEG_INSTALLATION.md) for complete installation and troubleshooting guide

### rpicam-vid Not Found

- **Problem**: "rpicam-vid command not found" error when using high-FPS capture mode
- **Solution**:
  - Install `libcamera-apps`: `sudo apt-get install -y libcamera-apps`
  - Verify installation: `rpicam-vid --help`
  - **Alternative**: Use "Picamera2 (Grayscale - High FPS)" capture mode instead (recommended, requires ffmpeg)
  - **Note**: rpicam-vid is optional. Picamera2 high-FPS mode is the recommended approach.

### GPIO Permission Issues

- **Problem**: Cannot control laser (GPIO errors)
- **Solution**:
  - Run with sudo (not recommended for production)
  - Add user to gpio group: `sudo usermod -a -G gpio $USER`
  - Restart after adding user to gpio group

### Low FPS During Recording

- **Problem**: Video recording FPS is lower than expected
- **Solution**:
  - Reduce preview resolution
  - Use separate camera streams for preview and recording (planned feature)
  - Check available CPU/memory resources
  - Reduce recording resolution if necessary
  - Check logs for FPS warnings - the system logs actual vs expected duration to help identify FPS issues

### Video Playback Duration Mismatch

- **Problem**: Videos play faster/slower than expected, or duration doesn't match recording time
- **Solution**:
  - **H264 videos**: FPS metadata is embedded in the video - most players should use it automatically
  - Verify the metadata file exists alongside your video file
  - Check application logs for FPS warnings during recording

### Printer Not Responding

- **Problem**: G-code commands not executed
- **Solution**:
  - Check serial connection
  - Verify printer is powered on and ready
  - Check for error messages in printer display
  - Ensure M400 wait commands are supported (use robocam_ccc.py)

## Shell Scripts

### setup.sh

Sets up the virtual environment and installs dependencies:
```bash
./setup.sh
```

The script will automatically detect and install required system dependencies (`python3-libcamera`, `libcap-dev`, `python3-dev`, `build-essential`) if they are missing. It creates the virtual environment with `--system-site-packages` to access system-installed packages like `python3-libcamera`.

### fix_dependencies.sh

Quick fix script for installation issues. Use this if setup.sh failed:
```bash
chmod +x fix_dependencies.sh
./fix_dependencies.sh
```

This script installs system dependencies and reinstalls Python packages in the virtual environment.

### start_calibrate.sh

Launches the calibration application:
```bash
./start_calibrate.sh
```

### start_preview.sh

Launches the preview application:
```bash
./start_preview.sh
```

### start_experiment.sh

Launches the experiment application:
```bash
./start_experiment.sh
```

## Project Structure

```
RoboCam-Suite/
├── calibrate.py              # Calibration GUI application
├── preview.py                # Preview alignment check tool
├── experiment.py             # Experiment automation GUI
├── setup.sh                  # Setup script
├── start_calibrate.sh        # Calibration launcher
├── start_preview.sh          # Preview launcher
├── start_experiment.sh       # Experiment launcher
├── requirements.txt          # Python dependencies
├── robocam/                  # Core modules
│   ├── __init__.py
│   ├── robocam_ccc.py       # RoboCam implementation (preferred)
│   ├── robocam.py           # RoboCam implementation (deprecated)
│   ├── laser.py             # GPIO laser control
│   ├── pihqcamera.py        # Camera wrapper
│   └── stentorcam.py        # StentorCam with well plate support
├── config/                   # Configuration files
│   ├── motion_config.json    # Motion configuration profiles
│   └── templates/            # Experiment templates
├── calibrations/             # Saved 4-corner calibrations
├── experiments/              # Exported experiment settings (profile JSON files)
└── outputs/                  # Experiment output files (organized by date and experiment name)
    └── YYYYMMDD_{experiment_name}/    # Video recordings and CSV files for each experiment run
└── docs/                     # Documentation
    ├── USER_GUIDE.md         # User guide
    ├── DEVELOPER_GUIDE.md    # Developer guide
    ├── CALIBRATE_PY_README.md # calibrate.py documentation
    ├── EXPERIMENT_PY_README.md # experiment.py documentation
    └── CAMERA_ARCHITECTURE.md # Camera system architecture
```

## Documentation

Comprehensive documentation is available in the `docs/` directory:

- **[USER_GUIDE.md](docs/USER_GUIDE.md)**: Complete user guide with step-by-step procedures
- **[CALIBRATE_PY_README.md](docs/CALIBRATE_PY_README.md)**: Detailed documentation for calibrate.py
- **[PREVIEW_PY_README.md](docs/PREVIEW_PY_README.md)**: Detailed documentation for preview.py
- **[EXPERIMENT_PY_README.md](docs/EXPERIMENT_PY_README.md)**: Detailed documentation for experiment.py
- **[DEVELOPER_GUIDE.md](docs/DEVELOPER_GUIDE.md)**: Development guidelines and architecture
- **[CAMERA_ARCHITECTURE.md](docs/CAMERA_ARCHITECTURE.md)**: Camera system technical details
- **[FFMPEG_INSTALLATION.md](docs/FFMPEG_INSTALLATION.md)**: Complete FFmpeg installation and troubleshooting guide
- **[PLANNED_CHANGES.md](PLANNED_CHANGES.md)**: Implementation roadmap
- **[ROOM_FOR_IMPROVEMENT.md](ROOM_FOR_IMPROVEMENT.md)**: Improvement opportunities

## Contributing

When contributing to this project:

1. Follow existing code style
2. Add docstrings to new functions/classes
3. Update documentation for new features
4. Test with actual hardware when possible
5. Use `robocam_ccc.py` as the primary RoboCam implementation

## License

[Specify your license here]

## Authors

[Specify authors here]

## Acknowledgments

- Picamera2 library for Raspberry Pi camera support
- Marlin/RepRap G-code compatibility for 3D printer control

