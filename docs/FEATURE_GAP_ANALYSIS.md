# Feature Gap Analysis: RoboCam-Suite 1.0 vs 2.0

This document outlines the key features from the original 1.0 codebase that have not yet been implemented in the new 2.0 architecture. The analysis is based on a side-by-side review of all `*.py` files from the `archive/RoboCam-Suite-1.0/` directory against the current `robocam_suite/` source.

## High-Priority Missing Features

These features are critical for the application to be considered functionally complete and on par with the 1.0 version.

| Feature | 1.0 Implementation | 2.0 Status | Priority |
|---|---|---|---|
| **Save/Load Calibration** | `calibrate.py` used `filedialog.asksaveasfilename` and `filedialog.askopenfilename` to save/load the four corner points and well quantity to a JSON file. | **Missing.** The 2.0 `CalibrationPanel` has no UI for saving or loading. The `SessionManager` persists the values, but this is not the same as having named, shareable calibration files. | **Critical** |
| **Interactive Well Selection** | `stentorcam.py` had an `open_checkbox_window()` method that created a new `Toplevel` window with a grid of checkboxes corresponding to the well plate. This allowed users to run experiments on a subset of wells. | **Missing.** The 2.0 `ExperimentPanel` has no UI for well selection; it assumes all wells in the plate will be used. | **Critical** |
| **Live Calibration View** | The 1.0 `calibrate.py` was itself a preview window. The main `experiment.py` would instantiate `Calibrate` and pass it the camera object, so the user could see the live camera feed while jogging the machine to the corner points. | **Missing.** The 2.0 `CalibrationPanel` is currently "blind." It has the jog controls but no visual feedback, making it impossible to accurately set the corner points. | **High** |
| **Well Path Preview** | `calibrate.py` had a `preview_well_path()` method that would draw the calculated grid of well locations directly onto the `tkinter` preview window canvas. | **Missing.** The "Preview Path" button in the 2.0 `CalibrationPanel` is a stub and does nothing. | **High** |

## Medium-Priority Missing Features

These features are important for usability and a complete workflow but are not as critical as the high-priority items.

| Feature | 1.0 Implementation | 2.0 Status | Priority |
|---|---|---|---|
| **Video Recording in Experiments** | The 1.0 `experiment.py` would call `capture_manager.start_video_recording()` and `stop_video_recording()` for each well. | **Stubbed.** The 2.0 `Experiment` class has placeholder `camera.start_recording()` and `stop_recording()` calls that are commented out. The `QuickCaptureWidget` has recording logic, but it needs to be integrated into the main experiment loop. | **Medium** |
| **PlayerOne Camera Driver** | The 1.0 `playerone_camera.py` provided a full implementation for Player One cameras. | **Missing.** The 2.0 `SetupPanel` has "playerone" in the camera dropdown, but there is no corresponding `PlayerOneCamera` driver in `robocam_suite/drivers/camera/`. Selecting it will cause a crash. | **Medium** |
| **Arduino GPIO Sketch** | While not in the Python source, the project implies the existence of an Arduino sketch to handle serial commands for GPIO. This is not present in the 2.0 repository. | **Missing.** No `.ino` file is included in the repository. | **Medium** |

## Low-Priority Missing Features

These are minor features or nice-to-haves that were present in 1.0.

| Feature | 1.0 Implementation | 2.0 Status | Priority |
|---|---|---|---|
| **Advanced Well Selection** | The 1.0 `stentorcam.py` included logic for shift-clicking and control-clicking to select ranges or individual wells in the checkbox grid. | **N/A.** The entire well selection feature is missing. This would be an enhancement to the new implementation. | **Low** |
| **FPS Measurement Tool** | The 1.0 `preview_window.py` had a button to measure the actual camera frame rate. | **Missing.** This is less critical in 2.0 due to the more robust camera handling, but it was a useful diagnostic tool. | **Low** |
| **Detailed Status Bar** | The 1.0 `experiment.py` had a more detailed status bar that showed the current action (e.g., "Moving to well A1", "Recording..."). | **Partially Implemented.** The 2.0 UI has status indicators, but they are less verbose than in 1.0. | **Low** |
