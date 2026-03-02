# Planned Changes

This document tracks the phased implementation plan for RoboCam-Suite improvements.

## Phase 1: Documentation & Setup Scripts (Immediate)

Status: **IN PROGRESS**

### Completed ✅
- [x] Create README.md with setup and usage
- [x] Create setup.sh script for venv and dependency installation
- [x] Create start_experiment.sh launcher script
- [x] Create start_calibrate.sh launcher script
- [x] Create requirements.txt with version pinning
- [x] Create USER_GUIDE.md with step-by-step procedures
- [x] Create ROOM_FOR_IMPROVEMENT.md
- [x] Create PLANNED_CHANGES.md (this file)
- [x] Create .gitignore file

### Remaining
- [ ] Add docstrings to all modules and classes
- [ ] Document configuration file format in detail
- [ ] Add type hints to function signatures
- [ ] Create DEVELOPER_GUIDE.md

---

## Phase 2: GUI Consistency & FPS Optimization (HIGH PRIORITY)

Status: **MOSTLY COMPLETE** (FPS optimization done, GUI consistency pending)

### Tasks
- [x] Adopt native Picamera2 preview for calibrate.py (raspi_preview method)
- [x] Add FPS tracking and display in calibrate.py
- [x] Create camera_preview utility module with preview backend selection
- [ ] Standardize GUI appearance and layout between calibrate.py and experiment.py
- [x] Create separate camera configurations for preview vs recording
- [x] Optimize camera buffer settings for maximum FPS (buffer_count=2)
- [x] Preview disabled during recording (no GUI preview needed)
- [x] Video capture runs in separate thread (already implemented)
- [ ] Use dedicated Picamera2 instance/stream for video recording (optional, for further optimization)
- [ ] Implement video capture in separate process (optional, for further optimization)
- [ ] Ensure consistent button styling, fonts, and window layouts
- [ ] Add consistent status indicators and progress bars
- [ ] Create shared GUI style module

### Dependencies
- Requires Phase 1 completion for documentation baseline

### Completed
- Native preview implementation in calibrate.py using hardware-accelerated backends (DRM/QTGL)
- FPS tracking with FPSTracker class
- Automatic backend selection based on desktop session
- Separate preview window for high-performance camera display
- Optimized recording configuration in experiment.py (buffer_count=2)
- Preview disabled during recording to maximize FPS
- Separate camera configurations for preview vs recording

---

## Phase 3: 4-Corner Path Calibration (HIGH PRIORITY)

Status: **COMPLETED** ✅

### Tasks
- [x] Implement 4-corner calibration workflow in calibrate.py GUI
- [x] Add guided navigation to 4 corner positions (upper-left, lower-left, upper-right, lower-right)
- [x] Record and store corner positions with visual confirmation
- [x] Add GUI for specifying grid divisions (width x depth)
- [x] Implement/interpolate well positions from 4 corners (accounting for angles)
- [x] Save/load calibration profiles as JSON
- [x] Integrate with WellPlatePathGenerator
- [x] Validate calculated positions
- [x] Integrate calibration loading into experiment.py
- [x] Add checkbox grid for well selection
- [x] Implement calibration validation (blocking)
- [x] Add experiment settings export/import with calibration validation

### Completed
- 4-corner calibration GUI section in calibrate.py
- Coordinate recording buttons for all 4 corners
- Automatic label generation (A1, A2, ..., B1, B2, ...)
- Interpolation using WellPlatePathGenerator with Z-axis support
- Calibration save to calibrations/ directory
- Calibration loading in experiment.py
- Checkbox grid for well selection
- Mandatory calibration validation (blocks experiment start)
- Experiment settings export/import with calibration file validation
- Sequence building from selected wells with snake/raster patterns

### Dependencies
- Completed independently

---

## Phase 4: Motion Configuration System (HIGH PRIORITY)

Status: **COMPLETED**

### Tasks
- [x] Create motion configuration file structure (JSON)
- [x] Add preliminary_feedrate and preliminary_acceleration settings
- [x] Add between_wells_feedrate and between_wells_acceleration settings
- [x] Create motion configuration profiles in config/motion_config.json
- [x] Add configuration file selector in experiment.py GUI
- [x] Implement G-code acceleration commands (M204) in robocam_ccc.py
- [x] Add set_acceleration method to RoboCam class
- [x] Update experiment.py to use preliminary settings for homing/initial moves
- [x] Update experiment.py to use between-wells settings for well-to-well moves
- [x] Display current motion settings in GUI
- [x] Add GUI fields for feedrate override (optional)
- [ ] Add configuration file validation (basic validation done, could be enhanced)

### Completed
- Motion configuration templates created (default.json, fast.json, precise.json)
- set_acceleration() method added to RoboCam with M204 G-code support
- Motion config selector and display in experiment.py GUI
- Automatic application of preliminary settings before homing
- Automatic application of between-wells settings for well movements
- Feedrate override support maintained for backward compatibility

### Dependencies
- Requires robocam_ccc.py modifications
- Can be done in parallel with other phases

---

## Phase 5: Code Quality (Short-term)

Status: **MOSTLY COMPLETE** (Core improvements done, dataclasses pending)

### Tasks
- [x] Standardize to robocam_ccc.py as primary (deprecate robocam.py)
- [x] Update main application imports to use robocam_ccc
- [x] Update robocam/__init__.py to export RoboCam from robocam_ccc
- [x] Add comprehensive error handling to RoboCam
- [x] Create configuration management module
- [x] Extract hardcoded values to config (baudrate, GPIO pin, timeouts)
- [x] Add error handling to Laser
- [x] Add error handling to Camera operations (partial)
- [x] Add user-friendly error messages in GUI (calibrate.py)
- [x] Add status indicators in calibrate.py
- [x] Add logging instead of print statements (robocam_ccc.py, laser.py, experiment.py core)
- [ ] Optimize camera configuration for maximum FPS capture
- [x] Add type hints throughout codebase (completed in previous phase)
- [ ] Use dataclasses for configuration objects

### Dependencies
- Should be done early to prevent technical debt

### Completed
- Configuration management system created (robocam/config.py, config/default_config.json)
- All hardcoded values extracted to config (baudrate, GPIO pin, timeouts, delays)
- Comprehensive error handling added to robocam_ccc.py (all methods)
- Error handling added to laser.py
- Error handling added to calibrate.py and experiment.py (partial)
- User-friendly error messages in calibrate.py GUI
- Status indicators in calibrate.py
- robocam.py deprecated with warnings
- Main applications use config system
- Logging system implemented (robocam/logging_config.py)
- Print statements replaced with logging in robocam_ccc.py, laser.py, experiment.py
- Log rotation and file-based logging configured

---

## Phase 6: Features (Medium-term)

Status: **PENDING**

### Tasks
- [ ] Implement general calibration save/load (beyond 4-corner)
- [ ] Add experiment templates
- [ ] Improve GUI error messages
- [ ] Add progress persistence
- [ ] Add experiment history/logging
- [ ] Implement resume interrupted experiments
- [ ] Add keyboard shortcuts
- [ ] Add FPS display in GUI

### Dependencies
- Builds on Phase 2 and Phase 5 improvements

---

## Phase 7: Testing & Reliability (Medium-term)

Status: **PENDING**

### Tasks
- [ ] Add unit tests for core modules
- [ ] Create hardware simulation layer
- [ ] Add integration tests
- [ ] Implement experiment validation
- [ ] Test 4-corner calibration with various angles and grid sizes
- [ ] Test motion configuration with different feed/acceleration settings
- [ ] Add automated regression testing
- [ ] Create test data sets

### Dependencies
- Requires stable API from earlier phases
- Hardware simulation needed for CI/CD

---

## Phase 8: Code Organization (Long-term)

Status: **PENDING**

### Tasks
- [ ] Reorganize project structure
- [ ] Move scripts to scripts/ directory
- [ ] Clean up scrap_code directory
- [ ] Create proper package exports
- [ ] Remove deprecated robocam.py file
- [ ] Separate core from applications
- [ ] Create proper module hierarchy

### Dependencies
- Can be done incrementally
- Low priority compared to functional improvements

---

## Implementation Strategy

### Parallel Work Streams

Some phases can be worked on in parallel:

1. **Stream A**: Documentation & Setup (Phase 1) ✅
2. **Stream B**: Motion Configuration (Phase 4) - Can start immediately
3. **Stream C**: Code Quality (Phase 5) - Should start early
4. **Stream D**: GUI & FPS (Phase 2) + 4-Corner (Phase 3) - Sequential

### Recommended Order

1. **Immediate**: Complete Phase 1, start Phase 5 (code quality)
2. **Next**: Phase 4 (motion config) - independent, high value
3. **Then**: Phase 2 (GUI/FPS) - critical for performance
4. **Followed by**: Phase 3 (4-corner) - major workflow improvement
5. **Finally**: Phases 6, 7, 8 - polish and organization

### Milestones

- **Milestone 1**: Basic documentation and setup complete ✅
- **Milestone 2**: Motion configuration system working
- **Milestone 3**: GUI consistent and FPS optimized
- **Milestone 4**: 4-corner calibration functional
- **Milestone 5**: Code quality improvements complete
- **Milestone 6**: All high-priority features implemented

---

## Notes

- Phases are not strictly sequential - some work can be done in parallel
- User feedback may change priorities
- Some tasks may be combined for efficiency
- Testing should be done incrementally, not just at the end
- Documentation should be updated as features are added

---

## Change Log

### 2025-01-XX
- Created initial planned changes document
- Phase 1 documentation tasks completed
- Setup scripts created and tested

