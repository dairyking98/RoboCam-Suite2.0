# RoboCam-Suite 2.0 — Gap Analysis

**Last updated:** 2026-03-01

This document catalogues what is currently incomplete, partially implemented, or absent from the 2.0 codebase, ranked roughly by impact.

---

## Critical (blocks core functionality)

| Area | Gap | Notes |
|---|---|---|
| **Motion controller** | `send_raw()` is not yet defined on the `MotionController` ABC or the `GCodeSerialMotionController`. The "Disable Steppers" button calls it. | Add `send_raw(cmd: str)` to the ABC and implement it in the serial driver. |
| **Motion controller** | `get_current_position()` always returns `(0, 0, 0)` in simulation; the real driver needs to parse `M114` responses from the printer. | Implement `M114` response parsing in `GCodeSerialMotionController`. |
| **Camera recording** | `camera.start_recording()` / `stop_recording()` are stubbed out in the experiment engine with comments. No video is actually written. | Implement a threaded `VideoRecorder` class using `cv2.VideoWriter`. |
| **PlayerOne camera driver** | The driver stub exists in the archive but has not been ported to the 2.0 `Camera` ABC. The Setup tab exposes the option but selecting it will raise a `ValueError`. | Port `playerone_camera.py` from 1.0 and register it in `HardwareManager`. |
| **Picamera2 driver** | No Raspberry Pi camera driver exists in 2.0 yet. | Add a `Picamera2Camera` driver for users still running on Pi. |

---

## High (significantly degrades usability)

| Area | Gap | Notes |
|---|---|---|
| **Arduino GPIO firmware** | There is no companion Arduino sketch in the repository. The `ArduinoSerialGPIOController` expects a specific serial protocol, but no firmware is provided. | Write and commit a minimal Arduino sketch that accepts `PIN:STATE` commands. |
| **Experiment — output directory** | The output path is hard-coded to `outputs/` relative to the working directory. On Windows this may be inside `Program Files`. | Resolve to a user-writable path (e.g. `~/Documents/RoboCam/`) using `pathlib`. |
| **Error dialogs** | Errors are currently printed to the console. The user has no in-app notification when a move fails, a port disconnects, etc. | Add a `QMessageBox` or a persistent status-bar error display. |
| **Unit tests** | No test suite exists. The simulation mode makes this straightforward to add. | Add `pytest` tests for `WellPlate`, `SessionManager`, `ConfigManager`, and the null drivers. |

---

## Medium (quality-of-life improvements)

| Area | Gap | Notes |
|---|---|---|
| **Calibration — path preview** | The "Preview Well Plate Path" button in the Calibration tab is connected but does nothing. | Open a dialog or draw an overlay on the camera feed showing the computed well positions. |
| **Manual Control — Z jog** | The Z jog buttons exist but there is no Z position indicator or Z-specific step override. | Add a separate Z step size or re-use the shared step size with a clear label. |
| **Setup tab — camera preview test** | There is no "Test Camera" button; the user must close and reopen to see if the new camera index works. | Add a "Test" button that grabs a single frame and shows it in a small preview dialog. |
| **Setup tab — baud rate custom entry** | The baud rate combo only shows preset values. Non-standard printers may need a different rate. | Make the combo editable. |
| **Logging — user-visible log** | The log goes to the console only. A scrollable log widget in the UI would help diagnose issues. | Add a `QPlainTextEdit` log viewer, perhaps as a fifth tab. |
| **Config — per-user override file** | `local_config.json` is in `.gitignore` but `ConfigManager` does not yet load it. | Implement a config merge: `default_config.json` → `local_config.json`. |

---

## Low (future enhancements)

| Area | Gap | Notes |
|---|---|---|
| **Multi-channel / multi-laser** | Only a single laser pin is supported. | Generalise the GPIO layer to support multiple named output channels. |
| **Z-stack imaging** | No support for capturing images at multiple Z heights per well. | Add a Z-stack parameter group to the Experiment panel. |
| **Image capture mode** | Only video recording is planned; single-frame TIFF/PNG capture per well is not implemented. | Add a capture mode selector (video / single frame / burst). |
| **Experiment resume** | If the experiment crashes mid-run, there is no way to resume from the last completed well. | Persist a checkpoint file and add a "Resume" button. |
| **Dark mode / theming** | The UI uses the system default theme. | Add a stylesheet selector in Setup. |
