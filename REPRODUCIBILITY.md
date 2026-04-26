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

## 13. Fix for AttributeError: 'NoneType' object has no attribute 'experiment_started'

**Problem:** An `AttributeError` occurred because `ExperimentPanel` was attempting to connect signals to `self.experiment_runner` in its `__init__` method. However, `self.experiment_runner` is only instantiated when an experiment is started (i.e., when `_start_experiment` is called), leading to a `NoneType` error at application startup.

**Solution:**
1.  **Delayed Signal Connection:** The signal connections for `experiment_started` and `experiment_finished` were moved from `ExperimentPanel.__init__` to the `_start_experiment` method. This ensures that these connections are only established after `self.experiment_runner` has been properly instantiated.

**Verification:**
1.  **Start the RoboCam-Suite UI**: Confirm that the application launches without any `AttributeError` related to `experiment_runner`.
2.  **Run an Experiment**: Start and stop an experiment to ensure that the recording overlay and tab locking/unlocking functionality work as expected, confirming that the signals are now correctly connected when the experiment runner is active.

## 14. Fix for AttributeError: '_LivePreview' object has no attribute '_is_experiment_active'

**Problem:** An `AttributeError` occurred during the `paintEvent` of `_LivePreview` because the `_is_experiment_active` attribute was not initialized in the `__init__` method. This caused the application to crash or display errors whenever the widget attempted to repaint.

**Solution:**
1.  **Initialized Attribute:** Added `self._is_experiment_active = False` to the `_LivePreview.__init__` method to ensure the attribute exists from the moment the widget is created.

**Verification:**
1.  **Start the RoboCam-Suite UI**: Confirm that the application launches and the "Experiment" tab's live preview renders without any `AttributeError` in the console or logs.
2.  **Run an Experiment**: Verify that the "● RECORDING" overlay appears correctly when an experiment starts and disappears when it finishes.

## 15. Fix for Live Preview Not Working (AttributeError in _LivePreview)

**Problem:** The live preview stopped working due to an `AttributeError: 
'_LivePreview' object has no attribute '_is_experiment_active'` during the `paintEvent`.
This was caused by the `_is_experiment_active` attribute not being initialized in the `_LivePreview` class's `__init__` method.

**Solution:**
1.  **Initialize `_is_experiment_active`**: Added `self._is_experiment_active = False` to the `_LivePreview.__init__` method to ensure the attribute is always present upon object creation.

**Verification:**
1.  **Start the RoboCam-Suite UI**: Confirm that the application launches and the live camera preview is displayed correctly in the "Calibration" and "Experiment" tabs.
2.  **Run an Experiment**: Verify that the "● RECORDING" overlay appears and disappears as expected during an experiment, confirming that `_is_experiment_active` is being correctly updated.

## 16. Fix for Live Preview Not Working (Laser Indicator Interference)

**Problem:** The live preview was not working, likely due to the laser ON indicator being drawn directly onto the frames before they were sent to the live preview. This could interfere with the `QImage` conversion or `paintEvent` in the `_LivePreview` widget.

**Solution:**
1.  **Relocated Laser Indicator Drawing:** The logic for drawing the laser ON indicator (`cv2.putText`) was moved within the `_WellRecorder._run` method. It now operates on a *copy* of the frame (`frame_to_write`) specifically for video recording, ensuring that the original `frame` emitted to the live preview (`_emit_proxy(frame)`) remains unmodified.

**Verification:**
1.  **Start the RoboCam-Suite UI**: Confirm that the application launches and the live camera preview is displayed correctly in the "Calibration" and "Experiment" tabs.
2.  **Run a Video Experiment with Laser Activation**: Start a video capture experiment where the laser is programmed to turn ON.
3.  **Verify Live Preview**: Observe the live preview during the experiment. The asterisk (`*`) laser ON indicator should *not* be visible in the live preview.
4.  **Verify Recorded Video**: After the experiment, open the recorded AVI file. Confirm that the asterisk (`*`) laser ON indicator *is* visible in the top-left corner of the video frames when the laser was active.

## 17. Default Camera Settings, Laser Indicator, and FPS Adjustment Re-implementation

**Problem:** The live preview was not working due to an extremely low exposure setting (1ms). Additionally, the laser ON indicator was interfering with the live preview, and the FPS adjustment needed to be re-implemented carefully.

**Solution:**
1.  **Default Camera Settings:** Updated `robocam_suite/config/default_config.json` to set default exposure to 20ms (20000 microseconds), gain to 100, and target brightness to 100. USB bandwidth is not directly configurable via the OpenCV driver.
2.  **Laser ON Indicator Re-implementation:** The laser ON indicator logic in `_WellRecorder._run` (in `robocam_suite/experiments/experiment.py`) was modified to apply the asterisk (`*`) only to a *copy* of the frame (`frame_to_write`) that is written to the AVI file. The original frame is emitted to the live preview, ensuring no interference.
3.  **FPS Adjustment Re-implementation:** The `_actual_fps` calculation and its inclusion in the metadata (`_save_metadata` in `robocam_suite/experiments/experiment.py`) were re-implemented to accurately reflect the actual frames per second captured during recording.

**Verification:**
1.  **Start the RoboCam-Suite UI**: Confirm that the application launches and the live camera preview is displayed correctly in the "Calibration" and "Experiment" tabs with the new default settings.
2.  **Default Camera Settings**: Navigate to the camera settings in the UI and confirm that the default exposure is 20ms, gain is 100, and target brightness is 100.
3.  **Laser ON Indicator (Live Preview)**: Start a video capture experiment where the laser is programmed to turn ON. Observe the live preview during the experiment; the asterisk (`*`) laser ON indicator should *not* be visible.
4.  **Laser ON Indicator (Recorded Video)**: After the experiment, open the recorded AVI file. Confirm that the asterisk (`*`) laser ON indicator *is* visible in the top-left corner of the video frames when the laser was active.
5.  **FPS Adjustment**: After an experiment, locate the generated metadata file (`_metadata.json`) for the recorded video. Open it and verify that the `fps_actual` field is present and contains a reasonable value reflecting the actual capture rate. Play back the recorded AVI file and confirm that its duration matches the `duration_seconds` in the metadata.

## 18. Fix for AttributeError: 
'_WellRecorder' object has no attribute '_hw_manager' and 'str' object has no attribute 'name'

**Problem:**
1.  An `AttributeError: '_WellRecorder' object has no attribute '_hw_manager'` occurred because the `hw_manager` was not being passed to the `_WellRecorder` constructor.
2.  An `AttributeError: 'str' object has no attribute 'name'` occurred in `_save_metadata` because `self._output_path` was a string, not a `Path` object, which has a `.name` attribute.

**Solution:**
1.  **Pass `hw_manager` to `_WellRecorder`**: Modified the `_WellRecorder` constructor to accept `hw_manager` and stored it as `self._hw_manager`.
2.  **Convert `output_path` to `Path` object**: In `_WellRecorder.__init__`, `self._output_path` is now explicitly converted to a `pathlib.Path` object.

**Verification:**
1.  **Run an Experiment**: Start a video capture experiment.
2.  **Verify Recording**: Ensure the experiment runs without crashing and that video files are successfully recorded.
3.  **Check Metadata**: Open the generated metadata JSON file and confirm that `video_file` and other fields are correctly populated.

## 19. Camera Settings Persistence and Recall Fix

**Problem:** Camera control values (exposure, gain, auto-exposure, etc.) were not being saved upon program closure and were not recalled when the program was reopened.

**Solution:**
1.  **Dedicated Session Key:** Modified `_on_camera_params_changed` in `robocam_suite/ui/calibration_panel.py` to save all camera-related settings to a new, dedicated session key named `"camera_settings"` instead of mixing them with general `"calibration"` settings.
2.  **Load from Session:** Updated `_load_from_session` in `robocam_suite/ui/calibration_panel.py` to retrieve camera settings from the `"camera_settings"` session key and apply them to the respective UI elements (spin boxes and checkboxes) upon application startup.

**Verification:**
1.  **Launch Application:** Start RoboCam-Suite 2.0.
2.  **Adjust Camera Settings:** In the "Calibration" tab, modify the exposure, gain, and other camera settings to non-default values.
3.  **Close Application:** Close RoboCam-Suite 2.0.
4.  **Re-launch Application:** Open RoboCam-Suite 2.0 again.
5.  **Verify Settings:** Navigate to the "Calibration" tab and confirm that the camera settings previously set are now displayed in the UI and applied to the camera.
6.  **Reset to Defaults:** Click the "Reset to Defaults" button and confirm that settings revert to their default values (20ms exposure, 100 gain, 100 target brightness, etc.).

## 20. Fix for NullGPIOController and Metadata Path Handling

**Problem:**
1.  `AttributeError: 'NullGPIOController' object has no attribute 'get_laser_state'` occurred because the `NullGPIOController` (used when GPIO is disabled) was missing the `get_laser_state` method, which was being called by `_WellRecorder`.
2.  `AttributeError: 'PosixPath' object has no attribute 'rsplit'` occurred in `_save_metadata` because `self._output_path` was a `pathlib.Path` object, and `rsplit` is a string method.

**Solution:**
1.  **Add `get_laser_state` to `NullGPIOController`**: Implemented a `get_laser_state` method in `robocam_suite/drivers/gpio/null_gpio.py` that always returns `False`, ensuring compatibility when GPIO is disabled.
2.  **Correct `Path` object handling**: Modified `_save_metadata` in `robocam_suite/experiments/experiment.py` to correctly extract the filename stem and construct the metadata path using `pathlib.Path` methods (`.parent` and `.stem`) instead of string manipulation (`.rsplit`).

**Verification:**
1.  **Run an Experiment**: Start a video capture experiment with GPIO disabled.
2.  **Verify Recording**: Ensure the experiment runs without crashing and that video files are successfully recorded.
3.  **Check Metadata**: Open the generated metadata JSON file and confirm that `video_file` and other fields are correctly populated.

## 21. Re-implementation of Laser ON Indicator and Dynamic FPS Adjustment

**Problem:** Previous attempts to implement the laser ON indicator and dynamic FPS adjustment caused issues with the live preview. The laser indicator was being drawn on the live preview frames, and the FPS adjustment was not robust.

**Solution:**
1.  **Laser ON Indicator:** The laser ON indicator (asterisk `*`) is now drawn only on a *copy* of the frame (`frame_to_write`) that is specifically used for video recording in `_WellRecorder._run` (in `robocam_suite/experiments/experiment.py`). This ensures that the live preview (`_emit_proxy(frame)`) remains unaffected.
2.  **Dynamic FPS Adjustment:**
    *   The `_WellRecorder` class now calculates `_actual_fps` based on the number of frames captured and the actual duration of the recording.
    *   A new method `_post_process_video_fps` has been added to `_WellRecorder` which uses `ffmpeg` to rewrite the video file header with the `_actual_fps`. This ensures that the recorded AVI file plays back at the correct speed.
    *   The `subprocess` module was imported in `experiment.py` to execute `ffmpeg` commands.

**Verification:**
1.  **Run an Experiment:** Start a video capture experiment with the laser configured to turn ON during recording.
2.  **Live Preview:** Observe the live preview in the application. Confirm that the asterisk (`*`) laser ON indicator does *not* appear in the live preview.
3.  **Recorded Video (Laser Indicator):** After the experiment, open the recorded AVI file. Confirm that the asterisk (`*`) laser ON indicator *is* visible in the top-left corner of the video frames when the laser was active.
4.  **Recorded Video (FPS Adjustment):** Check the metadata JSON file (`_metadata.json`) generated alongside the video. Verify that `fps_actual` is present and reflects the actual capture rate. Play the recorded AVI file and confirm that its playback speed is accurate and matches the `duration_seconds` in the metadata.

## 22. Homing Enforcement on Startup and Automatic Calibration Loading

**Problem:**
1.  The system did not enforce homing if the printer started at (0,0,0), which could lead to unexpected movements or collisions.
2.  Users had to manually load calibration files after each startup, which was inconvenient.

**Solution:**
1.  **Homing Enforcement:** In `CalibrationPanel.__init__` (in `robocam_suite/ui/calibration_panel.py`), the initial printer position is now queried. If it is (0,0,0), movement and camera controls are disabled, and a warning message is displayed, requiring the user to home the printer before any operations.
2.  **Automatic Calibration Loading:**
    *   The `_save_calibration` method now saves the path of the successfully saved calibration file to the `session_manager` under the key `"last_calibration_path"`.
    *   The `_load_from_session` method in `CalibrationPanel` now checks for `"last_calibration_path"` in the `session_manager` on startup. If found, it automatically attempts to load the calibration file.
    *   The `_load_calibration` method has been refactored to accept an optional `path` argument, allowing it to be called directly with a file path for automatic loading, or to open a file dialog if no path is provided.

**Verification:**
1.  **Homing Enforcement:**
    *   Start the application with the printer in an unhomed state (or simulate it being at 0,0,0 if possible).
    *   Verify that movement and camera controls are disabled and a red warning message "Homing Required: Printer at (0,0,0). Please Home." is displayed.
    *   Perform a homing operation. Verify that the controls become enabled and the status message changes to "Ready."
2.  **Automatic Calibration Loading:**
    *   Load a calibration file manually using the "Load Calibration" button.
    *   Close and restart the application.
    *   Verify that the application automatically loads the last used calibration file, and the well map is displayed correctly.
