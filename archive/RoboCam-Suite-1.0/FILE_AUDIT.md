# File Audit - Non-Core Files

This document summarizes all files in the RoboCam-Suite project that are **NOT** related to `calibrate.py` or `experiment.py`, their purpose, and recommendations for what to do with them.

## Summary

The project contains many test scripts, experimental scripts, and utility files that appear to be from development/testing phases. Most of these are no longer relevant now that the main applications (`calibrate.py` and `experiment.py`) are functional.

---

## Root Directory Scripts

### Test/Development Scripts (Likely Obsolete)

#### `ccc_all_wells.py`
- **Purpose**: Test script that records videos at 12 hardcoded well positions with laser control (OFF-ON-OFF sequence, 30 seconds each)
- **Status**: Appears to be a development/test script
- **Recommendation**: **DELETE** or move to `scrap_code/` - functionality is now covered by `experiment.py`

#### `ccc_record_test.py`
- **Purpose**: Simple test script that records video at a fixed position with laser control (OFF-ON-OFF sequence)
- **Status**: Basic test script, no movement
- **Recommendation**: **DELETE** or move to `scrap_code/` - superseded by main applications

#### `ccc25day6.py`
- **Purpose**: GUI application that combines camera preview with printer control and experiment window. Appears to be an older/alternative version of the main applications
- **Status**: Duplicate functionality - seems like an early prototype
- **Recommendation**: **DELETE** - functionality is now properly implemented in `calibrate.py` and `experiment.py`

#### `fluorcam_photo_inplace.py`
- **Purpose**: Takes a single photo with laser turned on (no movement)
- **Status**: Simple utility script
- **Recommendation**: **DELETE** or move to `scrap_code/` - very specific use case, not part of main workflow

#### `photo_inplace.py`
- **Purpose**: Takes a single photo at current position (no movement, no laser)
- **Status**: Simple utility script
- **Recommendation**: **DELETE** or move to `scrap_code/` - basic functionality, not needed

#### `record_inplace.py`
- **Purpose**: Records video at current position without movement (45*3 = 135 seconds)
- **Status**: Simple test/utility script
- **Recommendation**: **DELETE** or move to `scrap_code/` - functionality covered by main apps

#### `scan_all_wells.py`
- **Purpose**: Scans all wells in an 8x6 well plate, taking photos at each position using `WellPlatePathGenerator`
- **Status**: Utility script using deprecated `robocam.robocam` (should use `robocam_ccc`)
- **Recommendation**: **DELETE** or move to `scrap_code/` - functionality is now in `experiment.py` with better GUI

#### `scan_select_wells.py`
- **Purpose**: Command-line script to scan user-specified wells. Takes user input for number of wells and coordinates, then takes photos with laser control
- **Status**: Utility script using deprecated `robocam.robocam`
- **Recommendation**: **DELETE** or move to `scrap_code/` - `experiment.py` provides better GUI-based well selection

#### `stentorcam_record_well_with_laser.py`
- **Purpose**: Records video at first well position with laser control (45s OFF, 45s ON, 45s OFF) using `StentorCam`
- **Status**: Test script for specific experiment pattern
- **Recommendation**: **DELETE** or move to `scrap_code/` - `experiment.py` handles this with configurable timing

#### `stentorcam_test.py`
- **Purpose**: Test script for `StentorCam` - records short videos (3s laser ON, 5s OFF) at each well in a 4x3 grid
- **Status**: Development/test script
- **Recommendation**: **DELETE** or move to `scrap_code/` - test script, not needed for production

#### `uv_stentorcam.py`
- **Purpose**: Records video at a single hardcoded well position (135 seconds total)
- **Status**: Simple test script
- **Recommendation**: **DELETE** or move to `scrap_code/` - very specific test case

---

## Compiled Binary

#### `a.out`
- **Purpose**: Compiled binary file (likely from C/C++ compilation)
- **Status**: Not part of Python project
- **Recommendation**: **DELETE** - should be in `.gitignore`, not tracked in repository

---

## Shell Scripts (KEEP - These are needed)

#### `setup.sh`
- **Purpose**: Sets up virtual environment, installs dependencies, creates config directories
- **Status**: **KEEP** - Essential for project setup
- **Recommendation**: **KEEP** - Required for installation

#### `start_calibrate.sh`
- **Purpose**: Launcher script for calibration application
- **Status**: **KEEP** - Referenced in README and documentation
- **Recommendation**: **KEEP** - Official launcher for calibrate.py

#### `start_experiment.sh`
- **Purpose**: Launcher script for experiment application
- **Status**: **KEEP** - Referenced in README and documentation
- **Recommendation**: **KEEP** - Official launcher for experiment.py

---

## Documentation Files (KEEP)

#### `README.md`
- **Purpose**: Main project documentation
- **Status**: **KEEP** - Essential documentation
- **Recommendation**: **KEEP**

#### `PLANNED_CHANGES.md`
- **Purpose**: Tracks planned improvements and implementation phases
- **Status**: **KEEP** - Project planning document
- **Recommendation**: **KEEP**

#### `ROOM_FOR_IMPROVEMENT.md`
- **Purpose**: Tracks areas for improvement and technical debt
- **Status**: **KEEP** - Project planning document
- **Recommendation**: **KEEP**

---

## scrap_code/ Directory

This directory contains experimental/test scripts that are clearly marked as scrap code.

#### `scrap_code/blink_laser.py`
- **Purpose**: Simple GPIO test script to blink laser on GPIO pin 18 (1s on/off, then 10s on/off cycles)
- **Status**: Test script
- **Recommendation**: **KEEP in scrap_code/** - Useful reference for GPIO testing

#### `scrap_code/laser_test.py`
- **Purpose**: Tests laser functionality (3 cycles of 3s ON, 1s OFF) on GPIO pin 16
- **Status**: Test script
- **Recommendation**: **KEEP in scrap_code/** - Useful reference for laser testing

#### `scrap_code/stentorcam_test.py`
- **Purpose**: Tests StentorCam with 4x3 well plate, records short videos with laser control
- **Status**: Test script
- **Recommendation**: **KEEP in scrap_code/** - Useful reference for StentorCam testing

#### `scrap_code/traverse-all-wells.py`
- **Purpose**: Moves to all wells in 8x6 grid without taking photos/videos (just movement test)
- **Status**: Test script
- **Recommendation**: **KEEP in scrap_code/** - Useful reference for path generation testing

#### `scrap_code/uv_stentorcam.py`
- **Purpose**: Records video at single hardcoded position (135 seconds)
- **Status**: Test script
- **Recommendation**: **KEEP in scrap_code/** - Already in scrap_code, fine to leave

---

## robocam/ Package (KEEP - Core functionality)

All files in `robocam/` are part of the core package and should be kept:
- `__init__.py` - Package exports
- `robocam_ccc.py` - Preferred RoboCam implementation
- `robocam.py` - Deprecated but still referenced (marked for removal in Phase 8)
- `laser.py` - GPIO laser control
- `pihqcamera.py` - Camera wrapper
- `stentorcam.py` - Extended RoboCam with well plate support
- `camera_preview.py` - Preview utilities
- `config.py` - Configuration management
- `logging_config.py` - Logging setup

---

## config/ Directory (KEEP - Configuration files)

All configuration files should be kept:
- `default_config.json` - Default configuration
- `motion_config.json` - Motion configuration profiles (all profiles in one file)

---

## docs/ Directory (KEEP - Documentation)

All documentation files should be kept.

---

## Recommendations Summary

### Files MOVED to scrap_code/ (Completed ✅)
1. `ccc_all_wells.py` - Test script, functionality in experiment.py
2. `ccc_record_test.py` - Test script
3. `ccc25day6.py` - Old prototype GUI
4. `fluorcam_photo_inplace.py` - Utility script
5. `photo_inplace.py` - Utility script
6. `record_inplace.py` - Test script
7. `scan_all_wells.py` - Utility script, functionality in experiment.py
8. `scan_select_wells.py` - Utility script, functionality in experiment.py
9. `stentorcam_record_well_with_laser.py` - Test script
10. `stentorcam_test.py` - Test script
11. `uv_stentorcam.py` - Test script
12. `a.out` - Compiled binary (should not be in repo)

**Status**: All files have been moved to `scrap_code/` directory to preserve them for reference while cleaning up the root directory.

### Files to KEEP
- All shell scripts (`setup.sh`, `start_calibrate.sh`, `start_experiment.sh`)
- All documentation files (`README.md`, `PLANNED_CHANGES.md`, `ROOM_FOR_IMPROVEMENT.md`)
- All files in `robocam/` package
- All files in `config/` directory
- All files in `docs/` directory
- All files in `scrap_code/` (already marked as scrap, useful for reference)

### Files Moved to scrap_code/
All obsolete root-level scripts have been moved to `scrap_code/` to preserve them for reference while cleaning up the root directory.

---

## Notes

- Many of the test scripts use the deprecated `robocam.robocam` instead of `robocam.robocam_ccc`
- Several scripts have hardcoded coordinates that are specific to particular experiments
- The `ccc25day6.py` file appears to be an early prototype that duplicates functionality now in `calibrate.py` and `experiment.py`
- Most test scripts implement functionality that is now available through the main GUI applications with better configuration options

---

## Action Items

1. ~~**Immediate**: Delete `a.out` (compiled binary should not be in repo)~~ ✅ **COMPLETED** - Moved to scrap_code/
2. ~~**Cleanup**: Delete or move obsolete test scripts from root directory~~ ✅ **COMPLETED** - All moved to scrap_code/
3. **Optional**: Consider adding `a.out` to `.gitignore` to prevent compiled binaries from being tracked
4. **Documentation**: Update README if any of these scripts were referenced (they don't appear to be)

