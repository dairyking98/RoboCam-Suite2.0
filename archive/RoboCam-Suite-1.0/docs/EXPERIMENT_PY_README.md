# experiment.py - Automated Well-Plate Experiment Execution

## Overview

`experiment.py` is a GUI-based application for automating well-plate experiments with synchronized camera capture and laser stimulation. It provides a comprehensive interface for configuring and executing multi-well experiments for FluorCam, StentorCam, and other automated microscopy experiments under the RoboCam umbrella, with precise timing control, motion profiles, and data export capabilities.

## Functionality

### Core Purpose

The application automates the execution of well-plate experiments by:

1. **Automated Movement**: Moves a camera-equipped positioning stage to predefined well coordinates
2. **Synchronized Capture**: Records video or captures still images at each well position
3. **Laser Control**: Provides precise timing sequences for laser stimulation (OFF-ON-OFF pattern)
4. **Data Export**: Generates CSV files with well coordinates and metadata
5. **Configuration Management**: Saves and loads experiment configurations for reproducibility
6. **Simulation Modes**: Test workflows without hardware using `--simulate_3d` and `--simulate_cam` flags
   - `--simulate_3d`: Simulates 3D printer (movements update position tracking, but no actual hardware movement)
   - `--simulate_cam`: Simulates camera (capture operations are skipped, logged instead)

### Main Workflow

1. **Configuration**: User sets up well positions (X, Y coordinates), labels, timing sequences, camera settings, and motion parameters
2. **Sequence Generation**: Application builds a well sequence based on selected pattern (snake or raster)
3. **Execution**: For each well:
   - Moves to well position with configured motion profile
   - Starts video/still capture
   - Executes laser timing sequence (OFF → ON → OFF)
   - Stops recording and saves file with formatted name
4. **Monitoring**: Real-time status updates, timers, and progress tracking

## Features

### 1. Calibration-Based Well Selection

- **Calibration Loading**: Load saved 4-corner calibrations from `calibrations/`
- **Well Selection Window**: Separate window for selecting wells via checkboxes
  - Opens via "Select Cells" button (enabled when calibration is loaded)
  - Button is disabled when selection window is open
  - Scrollable grid ensures all wells are visible
  - All wells are checked by default
  - **Check All / Uncheck All Buttons**: Quick selection controls in the window
  - **Keyboard Shortcuts** (Smart Fill/Unfill Logic):
    - **Shift+Click**: Smart fill/unfill all wells in the same row
      - If clicked checkbox is checked and row is all checked: unfills (unchecks all) in row
      - If clicked checkbox is checked and row is not all checked: fills (checks all) in row
      - If clicked checkbox is unchecked and row is all unchecked: fills (checks all) in row
      - If clicked checkbox is unchecked and row has some checked: unfills (unchecks all) in row
    - **Ctrl+Click**: Smart fill/unfill all wells in the same column
      - If clicked checkbox is checked and column is all checked: unfills (unchecks all) in column
      - If clicked checkbox is checked and column is not all checked: fills (checks all) in column
      - If clicked checkbox is unchecked and column is all unchecked: fills (checks all) in column
      - If clicked checkbox is unchecked and column has some checked: unfills (unchecks all) in column
  - **GUI Instructions**: Helpful instructions displayed next to the grid explaining all interaction methods
- **Auto-Generated Labels**: Wells labeled automatically (A1, A2, ..., B1, B2, etc.)
- **Interpolated Positions**: All well positions calculated from 4-corner calibration
- **Z Value**: Automatically set from calibration interpolation (no manual entry)
- **Pattern Selection**: Choose between "snake →↙" (alternating row direction/zig-zag) or "raster →↓" (consistent direction/rectilinear, default)
- **Calibration Required**: Experiment cannot start without a loaded calibration
- **No Manual Entry**: Manual coordinate entry has been removed - calibration is required

### 2. GPIO Action Phases

- **Adjustable Action List**: Configure custom GPIO action sequences with GUI-friendly controls
  - **Default Phase**: Always starts with one GPIO OFF phase (default: 30 seconds)
  - **Add Actions**: Click "Add Action" button to add additional phases
  - **Action Types**: Each phase can be set to "GPIO ON" or "GPIO OFF"
  - **Time Entry**: Each phase has its own time entry field (in seconds)
  - **Phase Management**: 
    - Phase numbers are automatically updated (Phase 1, Phase 2, etc.)
    - Delete button available for all phases except the first (which cannot be removed)
    - Minimum of one phase required
- **Flexible Sequences**: Create any combination of ON/OFF phases with custom durations
  - Example: OFF (30s) → ON (20s) → OFF (10s) → ON (5s) → OFF (15s)
  - Example: OFF (30s) → ON (60s) → OFF (30s) (traditional three-phase)
- **Pause/Resume**: Pause experiment execution at any time
- **Stop Control**: Emergency stop with automatic laser shutdown and recording termination

### 3. Camera Settings

- **Resolution**: Configurable X and Y resolution (default: 1920x1080)
- **Frame Rate**: Adjustable TARGET FPS (default: 30.0)
  - **Target vs Actual FPS**: The GUI displays "TARGET FPS" - the desired frame rate
  - **Actual FPS Tracking**: System calculates and records the actual FPS achieved during recording
  - **FPS Accuracy**: Actual FPS is properly embedded in H264 videos and saved in metadata files
  - **Real-Time Playback**: Ensures accurate playback duration for scientific velocity measurements
  - **FPS Logging**: System logs actual vs expected recording duration and calculates actual FPS to detect FPS issues
- **Export Formats**:
  - **H264**: Video encoding with high bitrate (50 Mbps)
    - FPS metadata embedded directly in video file
    - Ensures accurate playback duration
- **Pre-Recording Delay**: Configurable delay before video recording starts (default: 0.5 seconds)
  - Allows vibrations from printer movement to settle before recording begins
  - Configurable via `hardware.camera.pre_recording_delay` in `config/default_config.json`
  - Applies to video recording mode (H264)
- **FPS Metadata Files**: JSON metadata files automatically saved alongside each video recording
  - Format: `{video_filename}_metadata.json`
  - Contains target FPS, actual FPS, resolution, duration, format, timestamp, and well label
  - **Target FPS**: The FPS value set in the GUI (desired frame rate)
  - **Actual FPS**: The actual frame rate achieved during recording (calculated from actual duration)
  - Critical for accurate playback
  - If the camera cannot achieve the target FPS, the actual FPS will be recorded in the metadata

### 4. Motion Configuration

- **Motion Profiles**: Select from predefined motion configuration files:
  - `default.json`: Balanced speed and precision
  - `fast.json`: Optimized for speed
  - `precise.json`: Optimized for precision
- **Preliminary Settings**: Separate feedrate and acceleration for homing/initial movements
- **Between-Wells Settings**: Separate feedrate and acceleration for well-to-well movements
- **Automatic Application**: Motion settings are automatically applied based on movement phase

### 5. File Management

- **Experiment Name**: Name identifier for the experiment (default: "exp")
  - Used in filename generation to identify the experiment
  - Replaces the `{exp}` placeholder in the filename format
- **Filename Format**: Fixed format `{date}_{time}_{experiment_name}_{y}{x}.{ext}`
  - `{date}`: Date (YYYYMMDD format, e.g., "20241215")
  - `{time}`: Timestamp (HHMMSS format, e.g., "143022")
  - `{experiment_name}`: Experiment name from the "Experiment Name" field
  - `{y}`: Row letter (e.g., "A", "B", "C")
  - `{x}`: Column number (e.g., "1", "2", "3")
  - `{ext}`: File extension based on export type (`.h264`)
  - Example: `20241215_143022_exp_B2.h264`
- **Save Folder**: Output files are saved to `outputs/YYYYMMDD_{experiment_name}/` (not configurable via GUI)
  - The application automatically creates the directory if it doesn't exist
  - Each experiment run gets its own subfolder with date prefix in `outputs/`
  - Format: `outputs/YYYYMMDD_{experiment_name}/` where YYYYMMDD is the date when experiment starts
  - Provides detailed error messages if directory creation fails
  - Verifies write permissions before starting experiments
- **CSV Export**: Automatic generation of CSV file with format `{date}_{time}_{exp}_points.csv` containing well coordinates in `outputs/YYYYMMDD_{experiment_name}/`
- **FPS Metadata Files**: JSON metadata files automatically saved alongside each video recording
  - Format: `{video_filename}_metadata.json`
  - Example: `20241215_143022_exp_B2.h264` → `20241215_143022_exp_B2_metadata.json`
  - Contains: target FPS, actual FPS, resolution, duration, actual duration, format, timestamp, well label, and video filename
  - **Target FPS**: The FPS value set in the GUI (desired frame rate)
  - **Actual FPS**: The actual frame rate achieved during recording (calculated from actual duration)
  - Critical for accurate playback timing, especially for MJPEG files
  - Used for scientific velocity measurements requiring precise timing
  - If the camera cannot achieve the target FPS, the actual FPS will be recorded in the metadata
  - **Metadata JSON Format Example**:
    ```json
    {
      "target_fps": 30.0,
      "fps": 29.8,
      "actual_fps": 29.8,
      "resolution": [1920, 1080],
      "duration_seconds": 60.0,
      "actual_duration_seconds": 60.4,
      "format": "H264",
      "timestamp": "20241215_143022",
      "well_label": "B2",
      "video_file": "20241215_143022_exp_B2.h264"
    }
    ```
    - `target_fps`: The FPS value set in the GUI (desired frame rate)
    - `fps`: Actual FPS (kept for backward compatibility)
    - `actual_fps`: The actual FPS achieved during recording (calculated from actual duration)
    - `actual_duration_seconds`: The actual recording duration (used to calculate actual_fps)
- **Experiment Settings Export**: Save complete experiment configuration to JSON with format `{date}_{time}_{exp}_profile.json` directly to `experiments/` folder (no file dialog)
- **Experiment Settings Load**: Load settings from dropdown (similar to calibration dropdown) - selects from `experiments/` folder
- **Experiment Settings Import**: Load saved configurations with calibration validation

### 6. Configuration Persistence

- **Default Values**: Window initializes with default settings (1920x1080, 30 FPS, H264, etc.)
- **Experiment Settings Export**: Export complete configuration including calibration reference
- **Experiment Settings Import**: Load saved configurations with automatic calibration validation
- **No Auto-Save**: Settings are not automatically saved - use export/import for persistence

### 7. GUI Window Behavior

- **Smart Resizing**: The window automatically resizes only when content would be cut off
- **Consistent Size**: Window size is maintained when adjusting parameters (resolution, FPS, etc.)
- **User Resizing**: Users can manually resize the window as needed
- **Minimum Size**: Window has a minimum size to ensure all essential controls are visible
- **Scrollable Content**: Action phases section uses a scrollbar when many phases are added
- **Well Selection Window**: Separate window for well selection automatically sizes to fit content, but preserves user-resized dimensions if larger

### 7. Real-Time Monitoring

- **Status Display**: Current well, movement status, and capture progress
  - Shows detailed progress: "Moving to well X at (Y, Z)", "Recording - OFF for Xs", etc.
  - Displays errors and completion messages
- **Recording Indicator**: Flashing button that indicates when video recording is active
  - Gray when idle
  - Red/dark red flashing during recording
- **Timers**:
  - **Duration**: Total estimated experiment time
  - **Elapsed**: Time since experiment start
  - **Remaining**: Estimated time to completion
- **Live Preview**: Example filename preview as settings change

## Logic Behind the Implementation

### Architecture

The application follows an object-oriented design with a main `ExperimentWindow` class that manages:

- **GUI Components**: Tkinter-based interface with organized sections
- **Hardware Control**: Integration with `RoboCam` (printer control) and `Laser` (GPIO control)
- **Camera Management**: Picamera2 instance for video/still capture
- **Threading**: Separate execution thread to prevent GUI blocking

### Sequence Generation Logic

When using calibration:
```python
# Get selected wells from checkboxes
selected_wells = [label for label, var in well_checkboxes.items() if var.get()]

# Map labels to interpolated positions
label_to_pos = {label: pos for label, pos in zip(labels, interpolated_positions)}

# Build sequence from selected wells
for label in selected_wells:
    pos = label_to_pos[label]
    # Extract row/column for pattern sorting
    row_num = ord(label[0]) - ord('A')
    col_num = int(label[1:]) - 1
    selected_positions.append((pos[0], pos[1], pos[2], label, row_num, col_num))

# Sort by pattern
pattern = pattern_var.get()
# Extract pattern name (handles both "snake"/"raster" and "snake →↙"/"raster →↓" formats)
if pattern.startswith("snake"):
    pattern = "snake"
elif pattern.startswith("raster"):
    pattern = "raster"

if pattern == "snake":
    # Snake: alternate row direction (zig-zag pattern)
    selected_positions.sort(key=lambda x: (x[4], x[5] if x[4] % 2 == 0 else -x[5]))
else:  # raster (default)
    # Raster: consistent direction (rectilinear pattern)
    selected_positions.sort(key=lambda x: (x[4], x[5]))
```

**Note**: Manual coordinate entry has been removed. All well positions must come from calibration files.

### Motion Control Logic

1. **Preliminary Phase** (before homing):
   - Loads preliminary feedrate and acceleration from motion config
   - Applies acceleration via `M204` G-code command
   - Executes homing sequence

2. **Between-Wells Phase** (well movements):
   - Switches to between-wells feedrate and acceleration
   - Applies acceleration settings
   - Uses between-wells feedrate from motion configuration
   - Moves to each well position with `move_absolute()`

### Camera Configuration Logic

The application uses separate camera configurations for different phases:

1. **Preview Configuration** (if needed):
   - Lower resolution (640x480) for GUI display
   - Optimized for real-time preview

2. **Recording Configuration**:
   - Full resolution as specified by user
   - Frame rate control via `FrameRate` parameter
   - Optimized buffer settings (`buffer_count=2`) for maximum FPS
   - Preview disabled during recording to maximize performance
   - Pre-recording delay applied before starting video capture (configurable via `hardware.camera.pre_recording_delay`)

3. **Encoder Configuration**:
   - **H264**: `H264Encoder(bitrate=50_000_000, fps=fps)` - FPS parameter ensures metadata is written to video
   - **MJPEG**: `JpegEncoder(q=quality)` - FPS metadata saved in separate JSON file
   - FPS value passed to encoder to ensure accurate playback duration

4. **FPS Metadata Management**:
   - Metadata files saved automatically after each recording
   - Contains target FPS, actual FPS, resolution, duration, actual duration, format, timestamp, and well label
   - Calculates actual FPS from actual recording duration: `actual_fps = (target_fps × expected_duration) / actual_duration`
   - Logs actual vs expected duration to detect FPS issues
   - Warns if duration differs significantly (more than 5% or 1 second)
   - If camera cannot achieve target FPS, actual FPS is recorded in metadata for accurate playback

### Timing Sequence Logic

For each well (video modes only):

```python
move_to_well_position()
wait(1 second)  # Movement settling time
wait(pre_recording_delay)  # Vibration settling time (configurable, default: 0.5s)
start_recording()
for action, phase_time in action_phases:
    state = 1 if action == "GPIO ON" else 0
    laser.switch(state)
    wait(phase_time seconds)
stop_recording()
```

**Note**: The pre-recording delay is applied after movement to the well position to allow vibrations from the printer movement to settle before video recording begins. This ensures the first frames of the recording are not affected by mechanical vibrations.

The system iterates through all configured action phases in order, switching the GPIO state and waiting for the specified duration for each phase. This allows for fully customizable sequences beyond the traditional OFF-ON-OFF pattern.

**Example Sequences**:
- **Traditional**: OFF (30s) → ON (20s) → OFF (10s)
- **Extended**: OFF (30s) → ON (20s) → OFF (10s) → ON (5s) → OFF (15s)
- **Simple**: OFF (30s) only
- **Multiple Pulses**: OFF (10s) → ON (5s) → OFF (5s) → ON (5s) → OFF (10s)

For JPEG mode:
- Single capture at well position (no timing sequence)

### Error Handling

- **Input Validation**: Type checking and range validation for all user inputs
- **Hardware Errors**: Try-except blocks around all hardware operations
- **Graceful Degradation**: Continues operation when non-critical errors occur
- **User Feedback**: Clear error messages displayed in status label

### Threading Model

- **Main Thread**: GUI event loop (tkinter)
- **Execution Thread**: Experiment run loop (daemon thread)
  - Prevents GUI freezing during long operations
  - Allows pause/stop control from GUI
  - Automatic cleanup on application exit

### Action Phase Validation

Action phases are validated before experiment execution:
- At least one phase must be configured
- All phases must have valid time values (non-negative numbers)
- Time values are parsed as floats (supports decimals)
- Invalid phases are skipped during execution (with warning)

## Suggested Improvements

### High Priority

1. **4-Corner Path Calibration Integration** ✅ **COMPLETED**
   - ✅ Import well positions from calibration workflow
   - ✅ Eliminate manual coordinate entry (fully removed - calibration required)
   - ✅ Support for angled well plates
   - ✅ Separate well selection window with "Select Cells" button
   - ✅ Checkbox grid with Check All/Uncheck All buttons
   - ✅ Shift+Click and Ctrl+Click shortcuts with smart fill/unfill logic based on checkbox and row/column state
   - ✅ GUI instructions displayed in selection window

2. **GUI Consistency**
   - Standardize button styles and fonts with `calibrate.py`
   - Create shared GUI style module
   - Unified status indicators and progress bars

3. **Experiment Templates**
   - Save/load experiment presets
   - Quick selection of common configurations
   - Template library for different well plate types

4. **Resume Interrupted Experiments**
   - Save progress to file
   - Resume from last completed well
   - Skip already-captured wells on restart

5. **Enhanced Error Recovery**
   - Automatic retry for transient failures
   - Movement validation before capture
   - Position verification after movement

### Medium Priority

6. **Progress Persistence**
   - Save experiment state periodically
   - Recovery from crashes
   - Experiment history log

7. **Validation Before Execution**
   - Preview well sequence
   - Validate all positions are reachable
   - Check disk space availability
   - Verify camera and hardware connectivity

8. **Keyboard Shortcuts**
   - Space: Pause/Resume
   - Escape: Stop
   - Enter: Start (when configured)

9. **FPS Display**
   - Real-time FPS during recording
   - Average FPS per well
   - FPS statistics in status

10. **Enhanced CSV Export**
    - Include timing information
    - Add metadata (resolution, FPS, export type)
    - Include file paths for each well

### Low Priority

11. **Multi-Well Time-Lapse**
    - Return to wells multiple times
    - Configurable intervals
    - Time-lapse sequence generation

12. **Focus Stacking**
    - Multiple Z positions per well
    - Automatic focus stacking
    - Depth-of-field enhancement

13. **Metadata Embedding** ✅ **COMPLETED**
   - ✅ JSON metadata sidecar files with target FPS, actual FPS, resolution, duration, actual duration, format, timestamp, and well label
   - ✅ Actual FPS metadata embedded in H264 videos
   - ✅ Actual FPS metadata saved in JSON files for MJPEG videos
   - ✅ Actual FPS calculated from actual recording duration if target FPS cannot be achieved
    - ⚠️ EXIF data for JPEG files (optional enhancement)
    - ⚠️ Embed experiment parameters directly in video files (optional enhancement)

14. **Remote Monitoring**
    - Web interface for status
    - Remote start/stop control
    - Real-time progress streaming

## Planned Improvements and Fixes

### Phase 2: GUI Consistency & FPS Optimization

**Status**: Mostly Complete

- ✅ Separate camera configurations for preview vs recording
- ✅ Optimized camera buffer settings (`buffer_count=2`)
- ✅ Preview disabled during recording
- ⚠️ Standardize GUI appearance with `calibrate.py` (pending)
- ⚠️ Consistent button styling and fonts (pending)
- ⚠️ Shared GUI style module (pending)

### Phase 3: 4-Corner Path Calibration

**Status**: Completed ✅

- ✅ Import well positions from calibration workflow
- ✅ Support for angled well plates
- ✅ Calibration loading and validation
- ✅ Checkbox grid for well selection
- ✅ Experiment settings export/import
- ✅ Automatic label generation
- ⚠️ Visual preview of well grid overlay (optional enhancement)

### Phase 4: Motion Configuration System

**Status**: Completed ✅

- ✅ Motion configuration file structure (JSON)
- ✅ Preliminary and between-wells settings
- ✅ Configuration file selector in GUI
- ✅ G-code acceleration commands (M204)
- ✅ Automatic application of motion settings
- ✅ Motion settings display in GUI

### Phase 5: Code Quality

**Status**: Mostly Complete

- ✅ Comprehensive error handling
- ✅ Type hints throughout
- ✅ Logging system implemented
- ✅ Configuration management
- ⚠️ Dataclasses for configuration objects (pending)

### Phase 6: Features

**Status**: Partially Complete

- ✅ Experiment settings export/import
- ⚠️ Experiment templates
- ⚠️ Experiment history/logging
- ⚠️ Resume interrupted experiments
- ⚠️ Progress persistence
- ⚠️ Keyboard shortcuts
- ⚠️ FPS display in GUI

### Phase 7: Testing & Reliability

**Status**: Pending

- ⚠️ Unit tests for core modules
- ⚠️ Hardware simulation layer
- ⚠️ Integration tests
- ⚠️ Experiment validation tests

## Usage Example

### Basic Workflow

1. **Launch Application**:
   ```bash
   python experiment.py
   # Or with simulation modes (no hardware required):
   python experiment.py --simulate_3d  # Simulate 3D printer only
   python experiment.py --simulate_cam  # Simulate camera only
   python experiment.py --simulate_3d --simulate_cam  # Simulate both
   ```

2. **Load Calibration** (Required):
   - Click "Open Experiment"
   - Select calibration from dropdown (e.g., "20241215_143022_well_plate_8x6.json" - files are automatically prefixed with date/time in format YYYYMMDD_HHMMSS)
   - Status should show "Loaded: 20241215_143022_well_plate_8x6.json (48 wells)"
   - "Select Cells" button will be enabled

3. **Select Wells**:
   - Click "Select Cells" button to open well selection window
   - Use checkboxes to select/deselect wells
   - All wells are checked by default
   - Uncheck wells to exclude from experiment
   - Use "Check All" or "Uncheck All" buttons for quick selection
   - **Shift+Click** a checkbox for smart row fill/unfill (see Smart Fill/Unfill Logic above)
   - **Ctrl+Click** a checkbox for smart column fill/unfill (see Smart Fill/Unfill Logic above)
   - Instructions are displayed next to the grid explaining all features

4. **Configure GPIO Action Phases**:
   - By default, one GPIO OFF phase is present (30 seconds)
   - Click "Add Action" to add more phases
   - For each phase:
     - Select action: "GPIO ON" or "GPIO OFF" from dropdown
     - Enter time in seconds (e.g., 30.0, 20.5, etc.)
   - Example: Add phases for OFF (30s) → ON (20s) → OFF (10s)
   - Delete phases (except first) using the "Delete" button
   - Choose pattern: `snake →↙` (zig-zag) or `raster →↓` (rectilinear, default)
   - Enter experiment name (default: "exp")
   - Z value is automatically set from calibration

5. **Configure Camera**:
   - Resolution: `1920` x `1080` (default)
   - TARGET FPS: `30.0` (default) - this is the desired frame rate
   - Export type: `H264`, `MJPEG`, or `JPEG`
   - Note: If the camera cannot achieve the target FPS, the actual FPS will be calculated and saved in the metadata JSON file

6. **Configure Motion**:
   - Select motion config: `default.json`
   - Motion settings are automatically applied based on movement phase

7. **Run Experiment**:
   - Click "Run" to start
   - Monitor progress via status and timers
   - Use "Pause" to pause/resume
   - Use "Stop" to abort

### Experiment Settings Export Format

When exporting experiment settings:
```json
{
  "calibration_file": "20241215_143022_well_plate_8x6.json",
  "selected_wells": ["A1", "A2", "B1", "B3", "C2"],
  "action_phases": [
    {"action": "GPIO OFF", "time": 30.0},
    {"action": "GPIO ON", "time": 20.0},
    {"action": "GPIO OFF", "time": 10.0}
  ],
  "resolution": [1920, 1080],
  "fps": 30.0,  # Target FPS (actual FPS is calculated and saved in video metadata JSON)
  "export_type": "H264",
  "quality": 85,
  "motion_config_profile": "default",
  "experiment_name": "exp",
  "pattern": "snake"
}
```

**Note**: The old `times` format (3-value array) is no longer supported. All exported settings use the new `action_phases` format.

### Calibration File Format

Calibration files are saved in `calibrations/` with filenames automatically prefixed with date and time in format `YYYYMMDD_HHMMSS_{name}.json` (e.g., `20241215_143022_well_plate_8x6.json`):
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

### Motion Configuration Format

All motion profiles are stored in `config/motion_config.json`. Each profile has the following structure:

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
  "precise": { ... },
  "fast": { ... }
}
```

- **name**: Display name for the profile
- **description**: Description of the profile's characteristics
- **preliminary**: Settings for homing and initial positioning moves
- **between_wells**: Settings for movements between wells during experiments

## Dependencies

- **tkinter**: GUI framework (usually included with Python)
- **picamera2**: Raspberry Pi camera control
- **robocam.robocam_ccc**: Printer control via G-code
- **robocam.laser**: GPIO laser control
- **robocam.config**: Configuration management
- **robocam.logging_config**: Logging system

## Technical Details

### Camera Configuration

- **Preview Config**: `640x480`, 2 buffers (if preview needed)
- **Recording Config**: User-specified resolution, user-specified FPS, 2 buffers
- **Encoder Selection**:
  - H264: `H264Encoder(bitrate=50_000_000, fps=fps)` - FPS parameter ensures metadata embedding
- **FPS Metadata**: JSON files saved alongside videos with target FPS, actual FPS, resolution, duration, actual duration, format, timestamp, and well label
  - Actual FPS is calculated from actual recording duration if it differs from target FPS

### Motion Control

- **G-code Commands**:
  - `G28`: Homing
  - `G0 X Y Z`: Absolute movement
  - `M204 P A`: Set acceleration (P=print, A=value)
  - `M400`: Wait for movement completion

### Threading

- **Main Thread**: Tkinter event loop, GUI updates
- **Execution Thread**: Experiment run loop (daemon=True)
- **Timer Updates**: `parent.after(200, update_timers)` for non-blocking updates

### File Naming

- **Placeholders**: `{x}`, `{y}`, `{time}`, `{date}`
- **Time Format**: `%H%M%S` (e.g., "143022")
- **Date Format**: `%Y%m%d` (e.g., "20241215")
- **Extension**: Based on export type (`.h264`, `.mjpeg`, `.jpeg`)

## Troubleshooting

### Common Issues

1. **"Permission denied: Cannot create directory"**
   - **Symptom**: Error message when starting experiment or saving CSV
   - **Cause**: Insufficient permissions to create `outputs/` directory or subdirectories
   - **Solution**:
     ```bash
     # Create directory with proper permissions
     mkdir -p outputs
     chmod 777 outputs
     ```
   - **Alternative**: Run the application with sudo (not recommended for production):
     ```bash
     sudo python experiment.py
     ```
   - The application identifies the issue and provides specific fix instructions

2. **"Directory exists but is not writable"**
   - **Symptom**: Directory exists but files cannot be saved
   - **Cause**: Directory lacks write permissions
   - **Solution**: Fix permissions for the directory:
     ```bash
     chmod 777 outputs
     ```

3. **"At least one action phase is required"**
   - Ensure at least one GPIO action phase is configured
   - The first phase cannot be deleted

4. **"Phase X has invalid time"**
   - Ensure all phase time entries contain valid numbers
   - Time values must be non-negative
   - Supports decimal values (e.g., 30.5)

2. **"Homing failed"**
   - Check printer connection
   - Verify serial port is accessible
   - Check printer is powered on

3. **"Movement failed"**
   - Verify well positions are within printer bounds
   - Check for mechanical obstructions
   - Verify motion configuration is valid

4. **Low FPS during recording**
   - Reduce resolution
   - Lower FPS setting
   - Check SD card write speed
   - Ensure preview is disabled during recording
   - Check application logs for FPS warnings - system logs actual vs expected duration

5. **Video playback duration doesn't match recording time**
   - **H264**: Actual FPS metadata is embedded - most players should use it automatically
   - Verify metadata file exists alongside video: `{video_filename}_metadata.json`
   - Check logs for FPS warnings during recording
   - **Important**: Use `actual_fps` from metadata JSON (not `target_fps`) for accurate playback

5. **First frames of video are blurry or affected by vibration**
   - Increase `pre_recording_delay` in `config/default_config.json`
   - Default is 0.5 seconds; try 1.0 or 1.5 seconds for heavier setups
   - The delay allows vibrations from printer movement to settle before recording

5. **Files not saving**
   - **Save folder permissions**: Check that `outputs/` is writable
     - The application automatically creates the directory structure if it doesn't exist
     - If creation fails, check error message for specific issue
     - Fix with: `mkdir -p outputs && chmod 777 outputs`
   - Verify disk space availability
   - Check filename scheme is valid

6. **"No calibration loaded" error**
   - Load a calibration from the dropdown before starting experiment
   - Create calibration in calibrate.py if none exist
   - Check that calibration file exists in `calibrations/`

7. **"Referenced calibration file not found" (on import)**
   - Ensure the calibration file referenced in exported settings exists
   - Re-create the calibration if it was deleted
   - Check file path in exported settings JSON

## Related Documentation

- [USER_GUIDE.md](./USER_GUIDE.md): Step-by-step user procedures
- [CALIBRATE_PY_README.md](./CALIBRATE_PY_README.md): Calibration application documentation
- [DEVELOPER_GUIDE.md](./DEVELOPER_GUIDE.md): Development guidelines
- [CAMERA_ARCHITECTURE.md](./CAMERA_ARCHITECTURE.md): Camera system architecture
- [PLANNED_CHANGES.md](../PLANNED_CHANGES.md): Implementation roadmap
- [ROOM_FOR_IMPROVEMENT.md](../ROOM_FOR_IMPROVEMENT.md): Improvement opportunities

## Author

RoboCam-Suite

## License

See main project LICENSE file.

