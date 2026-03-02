# RoboCam-Suite Developer Guide

Technical documentation for developers working on or extending the RoboCam-Suite codebase. RoboCam-Suite supports FluorCam, StentorCam, and other automated microscopy experiments under the RoboCam umbrella.

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Module Dependencies](#module-dependencies)
3. [Hardware Communication](#hardware-communication)
4. [Extension Points](#extension-points)
5. [Code Style Guidelines](#code-style-guidelines)

## Architecture Overview

### System Components

```
┌─────────────────────────────────────────────────────────┐
│                    Application Layer                    │
│  ┌──────────────┐              ┌──────────────────┐    │
│  │ calibrate.py │              │  experiment.py   │    │
│  │  (GUI)       │              │     (GUI)        │    │
│  └──────┬───────┘              └────────┬─────────┘    │
└─────────┼─────────────────────────────────┼──────────────┘
          │                                 │
          └──────────────┬──────────────────┘
                         │
┌────────────────────────┼────────────────────────────────┐
│              robocam Package (Core Modules)              │
│  ┌──────────────┐  ┌──────────┐  ┌──────────────┐      │
│  │ robocam_ccc  │  │  laser   │  │ pihqcamera   │      │
│  │  (G-code)    │  │  (GPIO)  │  │  (Camera)    │      │
│  └──────────────┘  └──────────┘  └──────────────┘      │
│                                                          │
│  ┌──────────────────────────────────────────────┐      │
│  │         stentorcam (Extended)                 │      │
│  │  - Movement limits                            │      │
│  │  - WellPlatePathGenerator                     │      │
│  └──────────────────────────────────────────────┘      │
└──────────────────────────────────────────────────────────┘
          │              │              │
          ▼              ▼              ▼
    ┌─────────┐   ┌─────────┐   ┌─────────┐
    │ Printer │   │  Laser   │   │ Camera  │
    │ (Serial)│   │  (GPIO)  │   │(Picam2) │
    └─────────┘   └─────────┘   └─────────┘
```

### Design Principles

1. **Separation of Concerns**: GUI, hardware control, and configuration are separated
2. **Hardware Abstraction**: Hardware-specific code is isolated in modules
3. **Configuration-Driven**: Settings loaded from JSON files
4. **Thread Safety**: Experiment execution runs in separate thread

## Module Dependencies

### Core Dependencies

- **tkinter**: GUI framework (standard library)
- **picamera2**: Raspberry Pi camera control
- **pyserial**: Serial communication with 3D printer
- **RPi.GPIO**: GPIO control for laser (Raspberry Pi only)
- **opencv-python**: Image processing for preview (calibrate.py)

### Internal Dependencies

```
experiment.py
  ├── robocam.robocam_ccc (RoboCam)
  └── robocam.laser (Laser)

calibrate.py
  └── robocam.robocam_ccc (RoboCam)

robocam.stentorcam
  └── robocam.robocam_ccc (RoboCam)
```

### Import Guidelines

- **Always use `robocam_ccc`**: The preferred implementation with M400 wait commands
- **Avoid `robocam.robocam`**: Deprecated, will be removed
- **Use package imports**: `from robocam import RoboCam` (via __init__.py)

## Hardware Communication

### G-code Protocol

The system communicates with 3D printers using standard G-code commands:

**Common Commands**:
- `G28`: Home all axes
- `G90`: Absolute positioning mode
- `G91`: Relative positioning mode
- `G0 X<val> Y<val> Z<val> F<speed>`: Rapid movement
- `M114`: Get current position
- `M400`: Wait for all moves to complete
- `M204 S<accel>`: Set acceleration (to be implemented)

**Response Format**:
- Printer responds with "ok" for successful commands
- Position responses: `X:123.45 Y:67.89 Z:12.34`
- Error responses: `error: <message>`

### Serial Communication

- **Baudrate**: Default 115200 (configurable via `hardware.printer.baudrate`)
- **Default Timeout**: 1 second (configurable via `hardware.printer.timeout`)
- **Home Timeout**: 90 seconds / 1.5 minutes (configurable via `hardware.printer.home_timeout`)
  - Used for G28 homing command
  - Longer timeout allows printer to complete homing sequence
- **Movement Wait Timeout**: 30 seconds (configurable via `hardware.printer.movement_wait_timeout`)
  - Used for M400 wait-for-movement command
  - Allows longer movements to complete
- **Line Endings**: `\n` (LF)
- **Encoding**: UTF-8
- **Environment Variables**: Can override timeouts via `ROBOCAM_HOME_TIMEOUT`, `ROBOCAM_MOVEMENT_WAIT_TIMEOUT`

### GPIO Control

- **Pin Mode**: BCM numbering
- **Laser Pin**: Default GPIO 21 (configurable)
- **States**: `GPIO.HIGH` (ON), `GPIO.LOW` (OFF)

### Camera Control

The camera system supports multiple capture types through a unified interface:

- **Library**: Picamera2 (for standard capture)
- **Unified Interface**: `CaptureManager` (`robocam/capture_interface.py`)
- **Capture Types**:
  1. **Picamera2 (Color)**: Standard RGB capture via `PiHQCamera`
  2. **Picamera2 (Grayscale)**: YUV420 grayscale via `PiHQCamera` (grayscale=True)
  3. **raspividyuv (High FPS)**: Direct subprocess capture via `RaspividyuvCapture`

- **Preview Configuration**:
  - Resolution: 800x600 (default, configurable via `hardware.camera.preview_resolution`)
  - Frame Rate: 30.0 FPS (default, configurable via `hardware.camera.default_fps`)
  - Backend: DRM/QTGL (hardware-accelerated, auto-selected)
  - Buffer Count: 2 (optimized for maximum FPS)
- **Recording Configuration**:
  - Resolution: User-configurable (default: 1920x1080)
  - Frame Rate: User-configurable (default: 30.0 FPS)
  - Buffer Count: 2 (optimized for recording)
  - Codec: FFV1 (lossless) or MJPG (high-quality) for minimal compression
- **FPS Tracking**: Callback-based (may show lower value with hardware-accelerated preview)

**Usage Example**:
```python
from robocam.capture_interface import CaptureManager

capture = CaptureManager(
    capture_type="raspividyuv (Grayscale - High FPS)",
    resolution=(640, 480),
    fps=120.0
)
capture.start_video_recording("output.avi", codec="FFV1")
# Capture frames during recording
capture.capture_frame_for_video()
capture.stop_video_recording(codec="FFV1")
```

## Extension Points

### Adding New Hardware

1. **Create Hardware Module**:
   ```python
   # robocam/new_hardware.py
   class NewHardware:
       def __init__(self, config):
           # Initialize hardware
       def control_method(self):
           # Hardware control
   ```

2. **Update `robocam/__init__.py`**:
   ```python
   from .new_hardware import NewHardware
   __all__.append('NewHardware')
   ```

3. **Integrate in Applications**:
   ```python
   from robocam import NewHardware
   hardware = NewHardware(config)
   ```

### Adding New Experiment Types

1. **Extend ExperimentWindow**:
   - Add new configuration fields
   - Modify `run_loop()` for new behavior
   - Update config file structure

2. **Create Experiment Template**:
   - Add template JSON in `config/templates/`
   - Document template format

### Adding Motion Profiles

1. **Create Motion Profile**:
   ```json
   {
     "my_custom_profile": {
       "name": "My Custom Profile",
       "description": "Custom settings for my experiments",
       "preliminary": {
         "feedrate": 2000,
         "acceleration": 1000
       },
       "between_wells": {
         "feedrate": 1500,
         "acceleration": 800
       }
     }
   }
   ```

2. **Add to `config/motion_config.json`** (add as a new key in the JSON object alongside existing profiles)
3. **Select in experiment.py GUI** (profile will appear in dropdown after restart)

### Configuration File Structure

The configuration system uses JSON files in `config/default_config.json`:

```json
{
  "hardware": {
    "printer": {
      "baudrate": 115200,
      "timeout": 1.0,
      "home_timeout": 90.0,
      "movement_wait_timeout": 30.0,
      "command_delay": 0.1,
      "position_update_delay": 0.1,
      "connection_retry_delay": 2.0,
      "max_retries": 5
    },
    "laser": {
      "gpio_pin": 21,
      "default_state": "OFF"
    },
    "camera": {
      "preview_resolution": [800, 600],
      "default_fps": 30.0,
      "preview_backend": "auto",
      "pre_recording_delay": 0.5
    }
  },
  "paths": {
    "config_dir": "config",
    "motion_config_file": "config/motion_config.json",
    "calibration_dir": "calibrations",
    "experiment_config": "experiment_config.json"
  }
}
```

**Key Configuration Options**:

- **Printer Timeouts**:
  - `home_timeout`: Timeout for G28 homing command (default: 90.0 seconds / 1.5 minutes)
  - `movement_wait_timeout`: Timeout for M400 wait command (default: 30.0 seconds)
  - Can be overridden via environment variables: `ROBOCAM_HOME_TIMEOUT`, `ROBOCAM_MOVEMENT_WAIT_TIMEOUT`

- **Camera Settings**:
  - `preview_resolution`: Preview resolution [width, height] (default: [800, 600])
  - `default_fps`: Default frame rate for preview (default: 30.0)
  - `preview_backend`: Preview backend selection (default: "auto")
  - `pre_recording_delay`: Delay in seconds before starting video recording (default: 0.5)
    - Allows vibrations from printer movement to settle before recording begins
    - Applies to video recording mode (H264)

### Adding New Configuration

1. **Update Config Class** (`robocam/config.py`):
   - Add new fields to `DEFAULT_CONFIG` dictionary
   - Add validation in `validate()` method
   - Add environment variable override in `_apply_env_overrides()` if needed

2. **Update Config File**:
   - Add fields to `config/default_config.json`
   - Update default values in `DEFAULT_CONFIG`

3. **Environment Variable Overrides**:
   - Format: `ROBOCAM_<UPPERCASE_KEY>`
   - Example: `ROBOCAM_HOME_TIMEOUT=60.0`
   - Add parsing in `_apply_env_overrides()` method

## Code Style Guidelines

### Type Hints

Always use type hints for function parameters and return values:

```python
def move_absolute(self, X: Optional[float] = None, 
                 Y: Optional[float] = None,
                 Z: Optional[float] = None,
                 speed: Optional[float] = None) -> None:
    """Move to absolute position."""
    pass
```

### Docstrings

Use Google-style docstrings:

```python
def method_name(self, param: type) -> return_type:
    """
    Brief description.
    
    Longer description if needed.
    
    Args:
        param: Parameter description
        
    Returns:
        Return value description
        
    Note:
        Additional notes or warnings
    """
    pass
```

### Error Handling

Use try-except blocks for hardware operations:

```python
try:
    self.printer_on_serial.write(command.encode())
except serial.SerialException as e:
    print(f"Serial error: {e}")
    # Handle error appropriately
```

### Logging

Replace print statements with proper logging (planned improvement):

```python
import logging
logger = logging.getLogger(__name__)
logger.info("Operation completed")
logger.error("Operation failed", exc_info=True)
```

### Constants

Define constants at module level:

```python
DEFAULT_BAUDRATE: int = 115200
DEFAULT_GPIO_PIN: int = 21
```

## File Organization

### Current Structure

```
RoboCam-Suite/
├── calibrate.py          # Calibration GUI
├── experiment.py         # Experiment automation GUI
├── robocam/              # Core modules
│   ├── __init__.py      # Package exports
│   ├── robocam_ccc.py   # Printer control (PREFERRED)
│   ├── robocam.py       # Printer control (DEPRECATED)
│   ├── laser.py         # GPIO laser control
│   ├── pihqcamera.py    # Camera wrapper
│   └── stentorcam.py    # Extended RoboCam
├── config/              # Configuration files
│   ├── motion_config.json # Motion profiles (all profiles in one file)
├── calibrations/        # 4-corner calibration files
├── experiments/         # Exported experiment settings (profile JSON files)
├── outputs/             # Experiment output files (organized by date and experiment name)
│   └── YYYYMMDD_{experiment_name}/  # Video recordings and CSV files for each experiment run
│   └── templates/       # Experiment templates
└── docs/                # Documentation
```

### Planned Structure

```
RoboCam-Suite/
├── scripts/             # Utility scripts (planned)
├── tests/               # Unit tests (planned)
└── ... (rest as above)
```

## Testing Strategy

### Unit Testing (Planned)

Test individual modules in isolation:

```python
# tests/test_robocam.py
def test_move_absolute():
    robocam = RoboCam(115200)
    # Mock serial connection
    robocam.move_absolute(X=10, Y=20, Z=5)
    # Assert position updated
```

### Hardware Simulation (Planned)

Create mock hardware for testing without physical devices:

```python
# tests/mock_hardware.py
class MockSerial:
    def write(self, data):
        # Simulate printer response
        pass
```

### Integration Testing (Planned)

Test complete workflows:

```python
# tests/test_experiment.py
def test_experiment_workflow():
    # Setup
    # Execute experiment
    # Verify outputs
```

## Performance Considerations

### Camera FPS Optimization

- **Separate Streams**: Use different Picamera2 instances for preview and recording
- **Buffer Management**: Optimize camera buffer sizes
- **Threading**: Run video capture in separate thread
- **Preview Reduction**: Lower preview FPS to prioritize recording

### Serial Communication

- **Command Batching**: Group related commands when possible
- **Timeout Handling**: Set appropriate timeouts
- **Error Recovery**: Implement retry logic for transient failures

### Memory Management

- **Frame Cleanup**: Release camera frames promptly
- **Thread Management**: Properly clean up threads
- **File Handling**: Close files immediately after use

## Debugging

### Common Issues

1. **Serial Connection Fails**:
   - Check USB connection
   - Verify baudrate matches printer
   - Check user permissions (dialout group)

2. **Camera Not Found**:
   - Enable camera in raspi-config
   - Check camera ribbon cable
   - Verify Picamera2 installation: `pip list | grep picamera2`
   - Verify system dependencies: `dpkg -l | grep python3-libcamera`
   - Ensure venv has system site packages: Check `venv/pyvenv.cfg` for `include-system-site-packages = true`
   - If missing, recreate venv: `rm -rf venv && python3 -m venv --system-site-packages venv`

3. **GPIO Errors**:
   - Check user permissions (gpio group)
   - Verify pin number
   - Check wiring

### Debug Tools

- **Print Logging**: Currently uses print statements (to be replaced with logging)
- **Status Labels**: GUI shows current operation status
- **Position Display**: Real-time position updates in calibrate.py

## Future Development

### Planned Features

1. ✅ **4-Corner Calibration**: Guided calibration workflow (COMPLETED)
2. ✅ **Motion Configuration**: Feedrate/acceleration profiles (COMPLETED)
3. ✅ **FPS Optimization**: Separate preview/recording streams (COMPLETED)
4. ✅ **Error Handling**: Comprehensive exception handling (COMPLETED)
5. ✅ **Logging System**: Replace print with proper logging (COMPLETED)
6. ✅ **Configuration Management**: Centralized config system (COMPLETED)
7. ⚠️ **GUI Consistency**: Standardize appearance across applications
8. ⚠️ **Testing Framework**: Unit and integration tests

### Contributing

When contributing:

1. Follow existing code style
2. Add docstrings to new functions/classes
3. Include type hints
4. Update documentation
5. Test with actual hardware when possible
6. Use `robocam_ccc.py` as the RoboCam implementation

## API Reference

### RoboCam Class

**Location**: `robocam.robocam_ccc.RoboCam`

**Methods**:
- `__init__(baudrate: int)`: Initialize and connect to printer
- `home() -> None`: Home printer to origin
- `move_absolute(X, Y, Z, speed) -> None`: Move to absolute position
- `move_relative(X, Y, Z, speed) -> None`: Move relative to current position
- `update_current_position() -> Tuple[float, float, float]`: Get current position
- `send_gcode(command: str) -> None`: Send G-code command

### Laser Class

**Location**: `robocam.laser.Laser`

**Methods**:
- `__init__(laser_pin: int)`: Initialize laser on GPIO pin
- `switch(state: int) -> None`: Turn laser ON/OFF

### PiHQCamera Class

**Location**: `robocam.pihqcamera.PiHQCamera`

**Methods**:
- `__init__(resolution, exposure, gain, ...)`: Initialize camera
- `take_photo_and_save(file_path) -> None`: Capture still image
- `start_recording_video(video_path) -> None`: Start video recording
- `stop_recording_video() -> None`: Stop video recording

### WellPlatePathGenerator Class

**Location**: `robocam.stentorcam.WellPlatePathGenerator`

**Methods**:
- `generate_path(width, depth, upper_left_loc, lower_left_loc, upper_right_loc, lower_right_loc) -> List[Tuple]`: Generate well positions from 4 corners using bilinear interpolation

**Interpolation Method**:
The bilinear interpolation works in three steps:
1. For each horizontal position, interpolates along the top edge (UL → UR)
2. For the same horizontal position, interpolates along the bottom edge (LL → LR)
3. Interpolates vertically between the top and bottom points

This properly accounts for rotation and skew by considering both horizontal and vertical components together, rather than treating X and Y independently.

**Usage**:
```python
from robocam.stentorcam import WellPlatePathGenerator

path = WellPlatePathGenerator.generate_path(
    width=8,
    depth=6,
    upper_left_loc=(8.0, 150.0, 157.0),
    lower_left_loc=(6.1, 77.7, 157.0),
    upper_right_loc=(98.1, 143.4, 157.0),
    lower_right_loc=(97.1, 78.7, 157.0)
)
# Returns list of (X, Y, Z) tuples for all wells
```

## Version History

- **v1.0** (Current): Initial implementation
  - Basic calibration and experiment GUIs
  - G-code printer control
  - GPIO laser control
  - Camera capture

## Related Documentation

- [USER_GUIDE.md](./USER_GUIDE.md): User procedures and workflows
- [CALIBRATE_PY_README.md](./CALIBRATE_PY_README.md): Calibration application documentation
- [EXPERIMENT_PY_README.md](./EXPERIMENT_PY_README.md): Experiment application documentation
- [CAMERA_ARCHITECTURE.md](./CAMERA_ARCHITECTURE.md): Camera system architecture
- [PLANNED_CHANGES.md](../PLANNED_CHANGES.md): Implementation roadmap
- [ROOM_FOR_IMPROVEMENT.md](../ROOM_FOR_IMPROVEMENT.md): Improvement opportunities

## Contact

For questions or contributions, see the main README.md.

