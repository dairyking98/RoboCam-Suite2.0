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

## 6. UI Refinements and Experiment Control

Recent updates have focused on improving the user interface and experiment control:

- **Decoupled Step Size UI**: The step size input field now retains custom values even when a preset is selected, allowing users to see their custom setting while using a preset. The redundant 'Active' step label has been removed for a cleaner interface.
- **Immediate Experiment Stop**: Experiments can now be stopped immediately (non-gracefully) by setting a stop flag, ensuring a quick halt to ongoing processes. This is crucial for safety and rapid iteration during experiments.

## 7. Homing Enforcement Verification

To verify the homing enforcement logic:

1.  **Start the RoboCam-Suite UI**: Ensure the application starts with the `CalibrationPanel` visible.
2.  **Observe Initial State**: Confirm that all movement controls (jog buttons, step size input, Go To Position fields) are disabled. The "Home" button should be the only active movement control.
3.  **Check Status Message**: Verify that a warning message, such as "Printer not homed. Please click 'Home' before moving.", is displayed in the status label.
4.  **Perform Homing**: Click the "Home" button. Observe that the printer performs its homing sequence.
5.  **Verify Controls Enabled**: After successful homing, all movement controls should become enabled, and the warning message should disappear.
6.  **Test Movement**: Attempt to jog the stage using the X, Y, or Z buttons to confirm movement is now possible.

## 8. Recording Overlay and Tab Locking Verification

To verify the recording overlay and tab locking functionality:

1.  **Start the RoboCam-Suite UI**: Navigate to the "Experiment" tab.
2.  **Start an Experiment**: Initiate an experiment using the controls in the "Experiment" tab.
3.  **Observe Live Preview**: Confirm that a semi-transparent black overlay with "● RECORDING" text appears over the live camera preview in the "Experiment" tab.
4.  **Verify Tab Locking**: Attempt to switch to the "Setup", "Calibration", and "Manual Control" tabs. Confirm that these tabs are disabled and cannot be selected while the experiment is running.
5.  **Stop Experiment**: Stop the ongoing experiment.
6.  **Verify Controls Restored**: Confirm that the "RECORDING" overlay disappears from the live preview and the "Setup", "Calibration", and "Manual Control" tabs become enabled again.

## 9. Dynamic FPS Adjustment Verification

To verify that recorded AVI files play back at their actual capture FPS:

1.  **Run an Experiment**: Conduct a video capture experiment in the RoboCam-Suite UI.
2.  **Locate Output Files**: After the experiment, navigate to the output directory (e.g., `~/Documents/RoboCam/captures/`). You should find an AVI file (e.g., `well_C3.avi`) and a corresponding JSON metadata file (e.g., `well_C3_metadata.json`).
3.  **Inspect Metadata**: Open the JSON metadata file and note the `fps_actual` value.
4.  **Play Video**: Open the AVI file using a video player (e.g., VLC Media Player, mpv). Observe the playback speed.
5.  **Verify Playback Speed**: Confirm that the video plays back at a speed consistent with the `fps_actual` value from the metadata. The video should not appear to speed up or slow down unnaturally due to an incorrect FPS header.
6.  **Check FFmpeg Logs**: Review the application logs (or console output if running directly) for messages indicating that FFmpeg was invoked and successfully corrected the video FPS.

## 10. Laser ON Indicator Verification

To verify the visual laser ON indicator on recorded video frames:

1.  **Configure Laser**: Ensure the laser is enabled and configured in the "Setup" tab.
2.  **Run a Video Experiment with Laser Activation**: Start a video capture experiment in the "Experiment" tab where the laser is programmed to turn ON for a duration (e.g., using the "Laser ON Duration" setting).
3.  **Locate Output Video**: After the experiment, find the recorded AVI file in the output directory.
4.  **Play Video**: Open the AVI file with a video player.
5.  **Observe Laser Indicator**: During the segments of the video where the laser was active, confirm that a white asterisk (`*`) is displayed in the top-left corner of the video frame. The asterisk should disappear when the laser is off.

## 11. Fix for AttributeError: 'CalibrationPanel' object has no attribute 'auto_exp_check'

**Problem:** An `AttributeError` occurred because `_set_movement_controls_enabled` was attempting to access camera control widgets (e.g., `self.auto_exp_check`) before they were initialized in `_build_camera_control_group`.

**Solution:**
1.  **Refactored Control Enabling:** Separated the enabling/disabling logic for movement controls and camera controls into two distinct methods: `_set_movement_controls_enabled` and `_set_camera_controls_enabled`.
2.  **Reordered Initialization:** Ensured that all UI building methods (`_build_movement_group`, `_build_camera_control_group`, etc.) are called within `CalibrationPanel.__init__` before any calls to `_set_movement_controls_enabled` or `_set_camera_controls_enabled`.
3.  **Conditional Enabling:** Camera controls are now explicitly disabled at startup and only enabled after the printer has been successfully homed, aligning with the 
homing enforcement.

**Verification:**
1.  **Start the RoboCam-Suite UI**: Confirm that the application launches without any `AttributeError` related to `auto_exp_check` or other camera control widgets.
2.  **Observe Initial State**: Verify that both movement controls and camera controls are initially disabled, and the "Home" button is the only active movement control.
3.  **Perform Homing**: Click the "Home" button. After successful homing, confirm that both movement controls and camera controls become enabled.

## 12. Camera Settings Persistence and Reset to Defaults Verification

To verify the camera settings persistence and the "Reset to Defaults" functionality:

1.  **Modify Camera Settings**: In the "Calibration" tab, adjust several camera settings (e.g., Exposure, Gain, Auto-Exposure, USB Bandwidth) to non-default values.
2.  **Close and Reopen Application**: Close the RoboCam-Suite application and then restart it.
3.  **Verify Persistent Settings**: Navigate back to the "Calibration" tab. Confirm that the camera settings you previously adjusted are still set to their last-used values, demonstrating persistence across sessions.
4.  **Test "Reset to Defaults"**: Click the "Reset to Defaults" button in the "Camera Controls" group. Observe that all camera settings immediately revert to their default values.
5.  **Verify Defaults Applied**: Confirm that the camera hardware also reflects these default settings (e.g., by observing the live preview or re-checking values if the camera provides a way to read them back).
