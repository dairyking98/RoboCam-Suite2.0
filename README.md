# RoboCam-Suite 2.0

**A modular and extensible suite for controlling robotic camera systems for automated imaging experiments.**

This is a complete overhaul of the original RoboCam-Suite, redesigned from the ground up for modularity, cross-platform compatibility, and improved performance. The new architecture allows for easy extension with new hardware drivers, experiment types, and UI components.

## Key Features

- **Modular Architecture:** Core interfaces for cameras, motion controllers, and GPIO are separated from their concrete implementations. This allows for easy swapping of hardware components.
- **Cross-Platform:** Designed to run on Windows, macOS, and Linux. Hardware access is abstracted to support platform-specific libraries.
- **Simulation Mode:** All hardware components can be run in a simulation mode, allowing for development and testing without physical hardware.
- **PySide6 GUI:** A modern and responsive graphical user interface built with PySide6, providing a user-friendly way to control the system.
- **Well-Plate Calibration:** A dedicated calibration panel allows for easy and accurate calibration of well-plate positions using bilinear interpolation.
- **Experiment Automation:** A flexible experiment engine allows for the creation and execution of automated imaging sequences.

## Project Structure

```
RoboCam-Suite2.0/
├── robocam_suite/
│   ├── core/               # Core abstract base classes for hardware
│   ├── drivers/            # Concrete hardware driver implementations
│   │   ├── camera/
│   │   ├── gpio/
│   │   └── motion/
│   ├── experiments/        # Experiment logic and well-plate generation
│   ├── ui/                 # PySide6 GUI components
│   ├── config/             # Configuration files and manager
│   ├── logger.py           # Logging setup
│   └── hw_manager.py       # Hardware manager for driver instantiation
├── archive/                # Original 1.0 source code
├── docs/                   # Project documentation
├── main.py                 # Main application entry point
└── requirements.txt        # Python dependencies
```

## Getting Started

1.  **Install Dependencies:**

    ```bash
    pip install -r requirements.txt
    ```

2.  **Configure Hardware:**

    Modify `robocam_suite/config/default_config.json` to match your hardware setup. You can select the appropriate drivers and specify connection parameters (e.g., serial ports, camera indices).

3.  **Run the Application:**

    ```bash
    python main.py
    ```

## Developer Guide

For detailed information on the architecture, how to add new hardware drivers, and other development topics, please see the [Developer Guide](docs/DEVELOPER_GUIDE.md).
