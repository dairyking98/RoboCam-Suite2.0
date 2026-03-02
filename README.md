# RoboCam-Suite 2.0

**A modular and extensible suite for controlling robotic camera systems for automated imaging experiments.**

This is a complete overhaul of the original RoboCam-Suite, redesigned from the ground up for modularity, cross-platform compatibility, and improved performance. The new architecture allows for easy extension with new hardware drivers, experiment types, and UI components.

## Key Features

- **Modular Architecture:** Core interfaces for cameras, motion controllers, and GPIO are separated from their concrete implementations.
- **Cross-Platform:** Designed to run on Windows, macOS, and Linux.
- **Virtual Environment Support:** Includes setup scripts for Windows, macOS, and Linux to automatically create a self-contained virtual environment.
- **Simulation Mode:** All hardware components can be run in a simulation mode, allowing for development and testing without physical hardware.
- **PySide6 GUI:** A modern and responsive graphical user interface built with PySide6.
- **Well-Plate Calibration:** A dedicated calibration panel allows for easy and accurate calibration of well-plate positions.
- **Experiment Automation:** A flexible experiment engine allows for the creation and execution of automated imaging sequences.

## Getting Started

This project uses a Python virtual environment to manage its dependencies. Follow the steps for your operating system to get set up.

### 1. First-Time Setup

Run the setup script for your platform. This will create a virtual environment in a `.venv` folder and install all required dependencies.

- **Windows:**
  Open Command Prompt and run:
  ```cmd
  setup.bat
  ```

- **macOS & Linux:**
  Open a terminal and run:
  ```bash
  bash setup.sh
  ```

### 2. Activate the Environment

Before running the application, you must **activate** the virtual environment in your terminal session.

- **Windows:**
  ```cmd
  .venv\Scripts\activate
  ```

- **macOS & Linux:**
  ```bash
  source .venv/bin/activate
  ```
  Your terminal prompt should now be prefixed with `(.venv)`.

### 3. Configure Your Hardware

Modify `robocam_suite/config/default_config.json` to match your hardware setup. You can select the appropriate drivers and specify connection parameters (e.g., serial ports, baud rates, camera indices).

See the comments inside the config file for guidance on common settings.

### 4. Run the Application

With the virtual environment activated, launch the application:

```bash
python main.py
```

Alternatively, you can run it as an installed package:

```bash
python -m robocam_suite
```

## Developer Guide

For detailed information on the architecture, how to add new hardware drivers, and other development topics, please see the [Developer Guide](docs/DEVELOPER_GUIDE.md).
