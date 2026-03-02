# RoboCam-Suite 2.0

**A modular and extensible suite for controlling robotic camera systems for automated imaging experiments.**

This is a complete overhaul of the original RoboCam-Suite, redesigned from the ground up for modularity, cross-platform compatibility, and improved performance. The new architecture allows for easy extension with new hardware drivers, experiment types, and UI components.

## Key Features

- **Modular Architecture:** Core interfaces for cameras, motion controllers, and GPIO are separated from their concrete implementations.
- **Cross-Platform:** Designed to run on Windows, macOS, and Linux.
- **Virtual Environment Support:** Includes setup scripts for Windows, macOS, and Linux to automatically create a self-contained virtual environment.
- **Simulation Mode:** Run the entire suite without any physical hardware. `python main.py --simulate`
- **PySide6 GUI:** A modern and responsive graphical user interface built with PySide6.
- **Live Hardware Setup:** A dedicated Setup tab for live configuration of cameras, serial ports, and GPIO, with connection status indicators.
- **Session Persistence:** The UI state is automatically saved and restored on restart.
- **Named Presets:** Save and recall different experiment parameter sets for different setups.

## Getting Started

### 1. Install Drivers (if applicable)

Before using the software, ensure you have the necessary drivers installed for your hardware.

| Hardware | Platform | Driver Link |
|---|---|---|
| **Player One Camera** | Windows | [Player One Website](https://player-one-astronomy.com/service/software/) |
| **CH340 Serial Chip** | Windows, macOS | [SparkFun](https://learn.sparkfun.com/tutorials/how-to-install-ch340-drivers/all) |

*Many 3-D printers and Arduino clones use the **CH340** chip for USB-to-serial communication. If your device doesn't appear as a serial port, you likely need this driver.*

### 2. First-Time Software Setup

This project uses a Python virtual environment to manage its dependencies. Run the setup script for your platform **once** to create a `.venv` folder and install all requirements.

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

### 3. Activate the Environment

**Before every run**, you must **activate** the virtual environment in your terminal session.

- **Windows:**
  ```cmd
  .venv\Scripts\activate
  ```

- **macOS & Linux:**
  ```bash
  source .venv/bin/activate
  ```
  Your terminal prompt should now be prefixed with `(.venv)`.

### 4. Run the Application

With the virtual environment activated, launch the application.

**Normal Mode (with hardware):**
```bash
python main.py
```

**Simulation Mode (no hardware needed):**
```bash
python main.py --simulate
```

*In simulation mode, all hardware is emulated in software. This is useful for testing the UI or developing new features on a computer without any peripherals connected.*

### 5. Configure Your Hardware

Once the application is running, use the **Setup** tab to configure your hardware. Select your camera driver, serial ports, and baud rates. The settings are saved automatically and will be restored on the next launch.

## Developer Guide

For detailed information on the architecture, how to add new hardware drivers, and other development topics, please see the [Developer Guide](docs/DEVELOPER_GUIDE.md).
