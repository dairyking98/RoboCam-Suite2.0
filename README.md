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
  This installs the core dependencies **plus** the Windows camera extras (`cv2-enumerate-cameras` and `wmi`) that enable real device names in the camera list and detection of WIA Imaging Devices (scanners, scientific cameras).

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

## Troubleshooting

### Camera shows as "USB Camera (index 0)" instead of its real name

On Windows, RoboCam-Suite resolves real device names (e.g. "Iriun Webcam", "ELP USB Camera") by querying the DirectShow or WMI device registry. This requires the `cv2-enumerate-cameras` package, which is installed automatically by `setup.bat` but is **not** installed by the cross-platform `pip install -e .` command alone.

If you see generic labels, install the Windows extras manually:

```cmd
.venv\Scripts\activate
pip install cv2-enumerate-cameras wmi
```

Then click **Scan for Cameras** in the Setup tab to refresh the list.

### Imaging Devices (scanners, WIA cameras) not appearing in the camera list

Devices listed under **Imaging devices** in Windows Device Manager (e.g. an Epson scanner, a WIA-class microscope camera) are enumerated via the `wmi` package. Install it as shown above, then scan again.

> **Note:** WIA Imaging Devices that do not expose a DirectShow/MSMF video stream cannot be opened with `cv2.VideoCapture`. They will appear in the list with the label `[Imaging Device — may need vendor SDK]`. To capture images from such devices you will need the manufacturer's SDK (e.g. the EPSON Scan SDK, the Player One SDK, or an ASCOM driver).

### Camera list is empty after scanning

1. Ensure the camera is physically connected and recognised by the OS (check Device Manager on Windows).
2. On Linux, verify your user is in the `video` group: `sudo usermod -aG video $USER` (log out and back in).
3. On macOS, grant camera permission to the terminal application in **System Settings → Privacy & Security → Camera**.
4. Try running in simulation mode (`python main.py --simulate`) to confirm the application itself is working.

### Serial port not found / printer not connecting

- On Windows, install the CH340 driver if your printer uses a CH340 USB-serial chip (link in the driver table above).
- On Linux/macOS, the port is typically `/dev/ttyUSB0` or `/dev/tty.usbserial-*`. Check with `ls /dev/tty*` before and after plugging in the printer.
- Ensure no other application (e.g. PrusaSlicer, OctoPrint) is holding the port open.
- Try a lower baud rate (115200 is standard for Marlin; some boards use 250000).
