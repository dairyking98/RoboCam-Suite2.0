# RoboCam-Suite 2.0: Player One SDK Reproducibility Guide

This document outlines the steps taken to ensure the Player One Astronomy Camera SDK works correctly on a Raspberry Pi (ARM64 / aarch64).

## 1. System Dependencies
The Player One native library (`libPlayerOneCamera.so`) requires `libusb` for hardware communication. On Raspberry Pi OS, ensure it is installed:

```bash
sudo apt-get update
sudo apt-get install libusb-1.0-0
```

## 2. USB Permissions (udev rules)
By default, Linux users do not have permission to access raw USB devices. You must install the Player One udev rules:

```bash
# Copy the rules file from the vendor folder (extracted by the installer)
sudo cp vendor/playerone/99-player_one_astronomy.rules /etc/udev/rules.d/

# Reload the udev system
sudo udevadm control --reload-rules
sudo udevadm trigger
```
**Important:** Unplug the camera and plug it back in after applying these rules.

## 3. Automated SDK Installation
The `scripts/install_playerone_sdk.py` has been updated to handle the following automatically:

- **Architecture Detection**: It detects if the system is `x86_64`, `arm64` (aarch64), or `arm32` and extracts the corresponding library from the SDK archive.
- **Path Correction**: It prioritizes `lib/arm64/` for Raspberry Pi 4/5.
- **Automatic Patching**: It strips the original Windows-only `cdll.LoadLibrary("./PlayerOneCamera.dll")` from `pyPOACamera.py` and replaces it with a robust cross-platform loader.
- **Shared Library Loading**: The patch uses `RTLD_GLOBAL` and temporarily sets `LD_LIBRARY_PATH` to ensure dependencies like `libusb` are resolved correctly.

To reinstall or update the SDK:
```bash
rm -rf vendor/playerone
python3 scripts/install_playerone_sdk.py
```

## 4. Verification
A standalone debug script is provided to verify the camera connection without the full UI:

```bash
python3 test_playerone_capture.py
```
This script will:
1. Run diagnostics on the library architecture (should be `ARM aarch64`).
2. Check for missing system dependencies via `ldd`.
3. Attempt to capture 5 test frames (`test_frame.png`).
4. Record a 2-second test video (`test_video.avi`).

## 5. Troubleshooting
If `test_playerone_capture.py` fails with:
- **"No such file or directory" (OSError)**: Usually means an architecture mismatch (e.g., trying to run x86 code on ARM) or a missing dependency like `libusb`.
- **"Found 0 Player One camera(s)"**: Usually means the `udev` rules were not applied or the camera is not securely connected.
