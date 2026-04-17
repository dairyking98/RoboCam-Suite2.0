"""
Experiment Panel — configure, select wells, and run well-plate imaging experiments.

Three-column layout
--------------------
Column 1 (large)  : Live camera preview.
Column 2 (medium) : Experiment parameters (mode-dependent), presets, run controls.
Column 3 (medium) : Well selection grid with drag-to-toggle interaction.

Experiment modes
----------------
Image Capture
    • Dwell period (settle after move)
    • Single image saved per well

Video Capture
    • Dwell period (laser OFF, camera recording)
    • Laser ON duration (camera still recording)
    • Post-laser period (laser OFF, camera still recording)
    Recording spans all three intervals.

Scan patterns
-------------
Raster  — left-to-right on every row (default)
Snake   — left-to-right on even rows, right-to-left on odd rows
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QGridLayout, QLabel, QLineEdit, QGroupBox,
    QComboBox, QFileDialog, QMessageBox,
    QScrollArea, QSplitter, QStackedWidget,
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QImage, QPixmap, QPainter, QColor

import cv2

from robocam_suite.hw_manager import hw_manager
from robocam_suite.experiments.experiment import Experiment
from robocam_suite.experiments.well_plate import WellPlate
from robocam_suite.session_manager import session_manager
from robocam_suite.ui.well_grid import WellGrid
from robocam_suite.logger import setup_logger

logger = setup_logger()

CORNER_NAMES = ["Upper-Left", "Lower-Left", "Upper-Right", "Lower-Right"]

STATUS_STYLE = "font-size: 10px; color: #888;"
LABEL_STYLE  = "font-size: 10px; color: #888; font-style: italic;"


def _default_preset_dir() -> Path:
    d = Path.home() / "Documents" / "RoboCam" / "experiment_presets"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _default_output_dir() -> Path:
    d = Path.home() / "Documents" / "RoboCam" / "captures"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# Camera frame grabber
# ---------------------------------------------------------------------------

class _FrameGrabber(QThread):
    frame_ready = Signal(QImage)
    camera_disconnected = Signal()   # emitted once when camera transitions to disconnected

    def __init__(self, fps: int = 15):
        super().__init__()
        self._fps = fps
        self._running = False

    def stop(self):
        self._running = False

    def run(self):
        self._running = True
        interval_ms = max(1, int(1000 / self._fps))
        camera = hw_manager.get_camera()
        _was_connected = False
        while self._running:
            try:
                if camera.is_connected:
                    _was_connected = True
                    frame = camera.read_frame()
                    if frame is not None:
                        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        h, w, ch = rgb.shape
                        qimg = QImage(
                            rgb.data.tobytes(), w, h, ch * w,
                            QImage.Format.Format_RGB888
                        )
                        self.frame_ready.emit(qimg.copy())
                else:
                    if _was_connected:
                        self.camera_disconnected.emit()
                        _was_connected = False
            except Exception:
                pass
            self.msleep(interval_ms)


class _LivePreview(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 240)
        self._pixmap: Optional[QPixmap] = None
        lbl = QLabel("No camera connected\n\nSelect a camera in Setup and click\nApply & Reconnect Camera", self)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet("color: #a0a0a0; font-size: 12px;")
        lbl.setWordWrap(True)
        self._no_cam_lbl = lbl
        layout = QVBoxLayout(self)
        layout.addWidget(lbl)

    def update_frame(self, qimg: QImage):
        self._pixmap = QPixmap.fromImage(qimg)
        self._no_cam_lbl.hide()
        self.update()

    def show_disconnected(self):
        """Re-show the 'no camera' label and clear the last frame."""
        self._pixmap = None
        self._no_cam_lbl.show()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        w, h = self.width(), self.height()
        if self._pixmap:
            scaled = self._pixmap.scaled(
                w, h,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            x_off = (w - scaled.width()) // 2
            y_off = (h - scaled.height()) // 2
            painter.drawPixmap(x_off, y_off, scaled)
        else:
            painter.fillRect(0, 0, w, h, QColor(30, 30, 30))
        painter.end()


# ---------------------------------------------------------------------------
# Background experiment runner
# ---------------------------------------------------------------------------

class _ExperimentRunner(QThread):
    progress = Signal(str)
    finished = Signal()

    def __init__(self, experiment: Experiment):
        super().__init__()
        self.experiment = experiment
        # Wire the experiment's on_status callback to emit progress signal
        self.experiment._on_status = lambda msg: self.progress.emit(msg)

    def run(self):
        self.experiment.run()
        self.finished.emit()

    def stop(self):
        self.experiment.stop()


# ---------------------------------------------------------------------------
# Well selection group — wraps WellGrid with toolbar
# ---------------------------------------------------------------------------

class _WellSelectionGroup(QGroupBox):
    """
    Wraps WellGrid (SELECT mode) with Check All / Uncheck All / Invert toolbar
    and a count label.
    """

    def __init__(self, parent=None):
        super().__init__("Well Selection", parent)
        self.setToolTip(
            "Click and drag over wells to select or deselect them.\n"
            "The first well you touch sets the target state for the whole drag:\n"
            "  \u2022 If it was selected \u2192 the drag deselects all wells it passes over.\n"
            "  \u2022 If it was deselected \u2192 the drag selects all wells it passes over."
        )

        outer = QVBoxLayout(self)
        outer.setSpacing(4)
        outer.setContentsMargins(4, 4, 4, 4)

        # Toolbar
        toolbar = QHBoxLayout()
        self._check_all_btn = QPushButton("Check All")
        self._check_all_btn.setFixedHeight(24)
        self._uncheck_all_btn = QPushButton("Uncheck All")
        self._uncheck_all_btn.setFixedHeight(24)
        self._invert_btn = QPushButton("Invert")
        self._invert_btn.setFixedHeight(24)
        self._count_label = QLabel("")
        self._count_label.setStyleSheet(STATUS_STYLE)

        toolbar.addWidget(self._check_all_btn)
        toolbar.addWidget(self._uncheck_all_btn)
        toolbar.addWidget(self._invert_btn)
        toolbar.addWidget(self._count_label, stretch=1)
        outer.addLayout(toolbar)

        # Placeholder shown when no calibration is loaded
        self._placeholder = QLabel(
            "No calibration loaded.\n"
            "Set all four corner positions in the Calibration tab first."
        )
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet("color: grey; font-style: italic;")
        outer.addWidget(self._placeholder, stretch=1)

        # Scroll area containing the WellGrid (hidden until calibration is ready)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setVisible(False)
        outer.addWidget(self._scroll, stretch=1)

        self._grid = WellGrid(rows=0, cols=0, mode=WellGrid.Mode.SELECT)
        self._grid.selection_changed.connect(self._update_count)
        self._scroll.setWidget(self._grid)

        self._check_all_btn.clicked.connect(self._grid.check_all)
        self._uncheck_all_btn.clicked.connect(self._grid.uncheck_all)
        self._invert_btn.clicked.connect(self._grid.invert)

        # Toolbar buttons disabled until calibration is loaded
        self._set_toolbar_enabled(False)
        self._update_count()

    def _set_toolbar_enabled(self, enabled: bool):
        self._check_all_btn.setEnabled(enabled)
        self._uncheck_all_btn.setEnabled(enabled)
        self._invert_btn.setEnabled(enabled)

    def rebuild(self, rows: int, cols: int):
        """Populate the grid with rows x cols wells and show it."""
        self._grid.rebuild(rows, cols)
        self._placeholder.setVisible(False)
        self._scroll.setVisible(True)
        self._set_toolbar_enabled(True)
        self._update_count()

    def clear_calibration(self):
        """Hide the grid and show the placeholder (calibration no longer valid)."""
        self._grid.rebuild(0, 0)
        self._scroll.setVisible(False)
        self._placeholder.setVisible(True)
        self._set_toolbar_enabled(False)
        self._update_count()

    def get_selected_indices(self) -> list[int]:
        return self._grid.get_selected_indices()

    def _update_count(self):
        sel = self._grid.selected_count()
        tot = self._grid.total_count()
        self._count_label.setText(f"{sel}/{tot} wells selected")


# ---------------------------------------------------------------------------
# Main panel
# ---------------------------------------------------------------------------

class ExperimentPanel(QWidget):
    """Three-column experiment panel: live preview | settings | well selection."""

    MODE_VIDEO = "Video Capture"
    MODE_IMAGE = "Image Capture"

    def __init__(self, parent=None, calibration_panel=None):
        super().__init__(parent)
        self.calibration_panel = calibration_panel
        self.experiment_runner: Optional[_ExperimentRunner] = None
        self._session = session_manager

        splitter = QSplitter(Qt.Orientation.Horizontal, self)

        # ---- Column 1: Live camera preview --------------------------------
        col1 = QWidget()
        col1_layout = QVBoxLayout(col1)
        col1_layout.setContentsMargins(0, 0, 4, 0)
        cam_label = QLabel("Live Camera Preview")
        cam_label.setStyleSheet("font-weight: bold; font-size: 11px;")
        col1_layout.addWidget(cam_label)
        self._live_preview = _LivePreview()
        col1_layout.addWidget(self._live_preview, stretch=1)
        splitter.addWidget(col1)

        # ---- Column 2: Settings (scrollable) ------------------------------
        col2_inner = QWidget()
        col2_layout = QVBoxLayout(col2_inner)
        col2_layout.setSpacing(6)
        col2_layout.setContentsMargins(4, 4, 4, 4)
        col2_layout.addWidget(self._build_mode_group())
        col2_layout.addWidget(self._build_common_group())
        col2_layout.addWidget(self._build_video_group())
        col2_layout.addWidget(self._build_image_group())
        col2_layout.addWidget(self._build_presets_group())
        col2_layout.addWidget(self._build_controls_group())
        col2_layout.addStretch()

        col2_scroll = QScrollArea()
        col2_scroll.setWidgetResizable(True)
        col2_scroll.setWidget(col2_inner)
        col2_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        splitter.addWidget(col2_scroll)

        # ---- Column 3: Well selection -------------------------------------
        col3 = QWidget()
        col3_layout = QVBoxLayout(col3)
        col3_layout.setContentsMargins(4, 4, 4, 4)
        col3_layout.setSpacing(4)

        self.well_selection = _WellSelectionGroup()
        col3_layout.addWidget(self.well_selection, stretch=1)
        splitter.addWidget(col3)

        splitter.setSizes([480, 360, 360])
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 1)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(splitter)

        self._load_from_session()
        self._on_mode_changed()   # apply initial visibility

        # Camera frame grabber
        self._grabber = _FrameGrabber(fps=15)
        self._grabber.frame_ready.connect(self._live_preview.update_frame)
        self._grabber.camera_disconnected.connect(self._live_preview.show_disconnected)
        self._grabber.start()

    def closeEvent(self, event):
        self._grabber.stop()
        self._grabber.wait(1000)
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # Group builders
    # ------------------------------------------------------------------

    def _build_mode_group(self) -> QGroupBox:
        grp = QGroupBox("Experiment Mode & Scan Pattern")
        layout = QGridLayout(grp)
        layout.setSpacing(6)

        layout.addWidget(QLabel("Mode:"), 0, 0)
        self.mode_combo = QComboBox()
        self.mode_combo.addItems([self.MODE_VIDEO, self.MODE_IMAGE])
        self.mode_combo.setToolTip(
            "Video Capture: records a continuous video at each well.\n"
            "The recording spans three phases:\n"
            "  1. Pre-laser period  (laser OFF)\n"
            "  2. Laser ON duration\n"
            "  3. Post-laser period (laser OFF)\n\n"
            "Image Capture: captures a single still image at each well\n"
            "after the dwell period. No laser stimulation."
        )
        self.mode_combo.currentTextChanged.connect(self._on_mode_changed)
        layout.addWidget(self.mode_combo, 0, 1)

        layout.addWidget(QLabel("Scan Pattern:"), 1, 0)
        self.pattern_combo = QComboBox()
        self.pattern_combo.addItems(["Raster", "Snake"])
        self.pattern_combo.setToolTip(
            "Raster: visits wells left-to-right on every row.\n"
            "  A1 → A2 → … → A12 → B1 → B2 → …\n\n"
            "Snake: alternates direction each row to minimise total\n"
            "stage travel distance.\n"
            "  A1 → A2 → … → A12 → B12 → B11 → … → B1 → C1 → …"
        )
        layout.addWidget(self.pattern_combo, 1, 1)

        layout.addWidget(QLabel("Experiment Name:"), 2, 0)
        self.exp_name_input = QLineEdit("my_experiment")
        self.exp_name_input.setToolTip(
            "A short label for this run.\n"
            "Used to name the output folder:\n"
            "  Documents/RoboCam/captures/YYYYMMDD_HHMMSS_<name>/"
        )
        self.exp_name_input.textChanged.connect(self._autosave)
        layout.addWidget(self.exp_name_input, 2, 1)

        return grp

    def _build_common_group(self) -> QGroupBox:
        """Parameters common to both modes."""
        grp = QGroupBox("Timing")
        layout = QGridLayout(grp)
        layout.setColumnStretch(1, 1)
        layout.setSpacing(4)

        layout.addWidget(QLabel("Dwell Period (s):"), 0, 0)
        self.dwell_input = QLineEdit("0.5")
        self.dwell_input.setToolTip(
            "How long to wait after the stage arrives at a well before\n"
            "any capture or laser action begins.\n\n"
            "Purpose: allows mechanical vibration from the stage move\n"
            "to settle so images are not blurred.\n\n"
            "The laser is OFF and the camera is NOT recording during\n"
            "this period.\n\n"
            "Typical values: 0.3–1.0 s\n"
            "For sensitive samples or heavy stages: 1.0–2.0 s"
        )
        self.dwell_input.textChanged.connect(self._autosave)
        layout.addWidget(self.dwell_input, 0, 1)

        return grp

    def _build_video_group(self) -> QGroupBox:
        """Parameters for Video Capture mode only."""
        self._video_grp = QGroupBox("Video Capture Settings")
        layout = QGridLayout(self._video_grp)
        layout.setColumnStretch(1, 1)
        layout.setSpacing(4)

        rows = [
            (
                "laser_off_pre", "2.0", "Pre-Laser Record (s):",
                "Duration of the baseline recording window BEFORE the laser turns on.\n\n"
                "The camera is recording and the laser is OFF.\n"
                "Use this to capture the resting state of the sample.\n\n"
                "Typical values: 1.0–5.0 s\n"
                "Shorter values reduce file size; longer values give more\n"
                "baseline data for analysis."
            ),
            (
                "laser_on", "1.0", "Laser ON Duration (s):",
                "How long the laser stays on (the stimulation window).\n\n"
                "The camera is recording throughout this period.\n"
                "Laser turns on at the start and off at the end.\n\n"
                "Typical values: 0.5–5.0 s\n"
                "Depends on your experimental protocol."
            ),
            (
                "laser_off_post", "2.0", "Post-Laser Record (s):",
                "Duration of the recovery recording window AFTER the laser turns off.\n\n"
                "The camera is recording and the laser is OFF.\n"
                "Use this to capture the sample's response after stimulation.\n\n"
                "Typical values: 1.0–10.0 s\n"
                "Longer values capture slower biological responses."
            ),
        ]
        self._video_inputs: dict[str, QLineEdit] = {}
        for i, (key, default, label, tip) in enumerate(rows):
            layout.addWidget(QLabel(label), i, 0)
            edit = QLineEdit(default)
            edit.setToolTip(tip)
            edit.textChanged.connect(self._autosave)
            layout.addWidget(edit, i, 1)
            self._video_inputs[key] = edit

        return self._video_grp

    def _build_image_group(self) -> QGroupBox:
        """Parameters for Image Capture mode only."""
        self._image_grp = QGroupBox("Image Capture Settings")
        layout = QGridLayout(self._image_grp)
        layout.setColumnStretch(1, 1)
        layout.setSpacing(4)

        layout.addWidget(QLabel("Image Format:"), 0, 0)
        self.image_format_combo = QComboBox()
        self.image_format_combo.addItems(["PNG", "TIFF", "JPEG"])
        self.image_format_combo.setToolTip(
            "File format for captured images.\n\n"
            "PNG  — Lossless compression. Good general-purpose choice.\n"
            "       Smaller files than TIFF.\n\n"
            "TIFF — Lossless, uncompressed. Preferred for scientific\n"
            "       imaging and downstream analysis pipelines.\n"
            "       Largest file size.\n\n"
            "JPEG — Lossy compression. Smallest files but introduces\n"
            "       compression artefacts. Not recommended for\n"
            "       quantitative analysis."
        )
        self.image_format_combo.currentTextChanged.connect(self._autosave)
        layout.addWidget(self.image_format_combo, 0, 1)

        return self._image_grp

    def _build_presets_group(self) -> QGroupBox:
        grp = QGroupBox("Experiment Preset")
        grp.setToolTip(
            "Save the current parameters to a JSON file or load a previously saved preset.\n"
            "Default location: Documents/RoboCam/experiment_presets/"
        )
        layout = QVBoxLayout(grp)
        layout.setSpacing(4)

        btn_row = QHBoxLayout()
        save_btn = QPushButton("Save Preset…")
        save_btn.setToolTip("Save the current experiment parameters to a JSON file.")
        save_btn.clicked.connect(self._save_preset)
        btn_row.addWidget(save_btn)

        load_btn = QPushButton("Load Preset…")
        load_btn.setToolTip("Load experiment parameters from a previously saved JSON file.")
        load_btn.clicked.connect(self._load_preset)
        btn_row.addWidget(load_btn)

        self._preset_status = QLabel("")
        self._preset_status.setStyleSheet(STATUS_STYLE)
        btn_row.addWidget(self._preset_status, stretch=1)
        layout.addLayout(btn_row)

        # Gray path label + ... folder button below the buttons
        path_row = QHBoxLayout()
        self._preset_dir_label = QLabel(str(_default_preset_dir()))
        self._preset_dir_label.setStyleSheet(LABEL_STYLE)
        self._preset_dir_label.setWordWrap(True)
        self._preset_dir_label.setToolTip("Default folder for experiment preset files.")
        path_row.addWidget(self._preset_dir_label, stretch=1)

        preset_folder_btn = QPushButton("\u2026")
        preset_folder_btn.setFixedWidth(28)
        preset_folder_btn.setToolTip("Change the default preset folder.")
        preset_folder_btn.clicked.connect(self._choose_preset_folder)
        path_row.addWidget(preset_folder_btn)
        layout.addLayout(path_row)

        return grp

    def _build_controls_group(self) -> QGroupBox:
        grp = QGroupBox("Run")
        layout = QVBoxLayout(grp)

        btn_row = QHBoxLayout()
        self.start_btn = QPushButton("Start Experiment")
        self.start_btn.setEnabled(False)  # Disabled until calibration is synced
        self.start_btn.setToolTip(
            "Begin the automated imaging sequence.\n"
            "Requires all four well-plate corners to be set in the Calibration tab.\n"
            "Only selected (blue) wells will be visited."
        )
        self.stop_btn = QPushButton("Stop Experiment")
        self.stop_btn.setToolTip("Request a graceful stop after the current well finishes.")
        self.stop_btn.setEnabled(False)
        btn_row.addWidget(self.start_btn)
        btn_row.addWidget(self.stop_btn)
        layout.addLayout(btn_row)

        self.status_label = QLabel("Status: Idle")
        self.status_label.setStyleSheet(STATUS_STYLE)
        layout.addWidget(self.status_label)

        self.start_btn.clicked.connect(self._start_experiment)
        self.stop_btn.clicked.connect(self._stop_experiment)

        # Output folder row
        out_row = QHBoxLayout()
        self._output_dir_label = QLabel(str(_default_output_dir()))
        self._output_dir_label.setStyleSheet(LABEL_STYLE)
        self._output_dir_label.setWordWrap(True)
        self._output_dir_label.setToolTip("Folder where experiment captures will be saved.")
        out_row.addWidget(self._output_dir_label, stretch=1)

        output_folder_btn = QPushButton("\u2026")
        output_folder_btn.setFixedWidth(28)
        output_folder_btn.setToolTip("Change the output folder for captured images and videos.")
        output_folder_btn.clicked.connect(self._choose_output_folder)
        out_row.addWidget(output_folder_btn)

        open_folder_btn = QPushButton("Open")
        open_folder_btn.setFixedWidth(44)
        open_folder_btn.setToolTip("Open the output folder in Explorer.")
        open_folder_btn.clicked.connect(self._open_output_folder)
        out_row.addWidget(open_folder_btn)
        layout.addLayout(out_row)

        return grp

    # ------------------------------------------------------------------
    # Mode switching
    # ------------------------------------------------------------------

    def _on_mode_changed(self):
        mode = self.mode_combo.currentText()
        self._video_grp.setVisible(mode == self.MODE_VIDEO)
        self._image_grp.setVisible(mode == self.MODE_IMAGE)
        self._autosave()

    # ------------------------------------------------------------------
    # Calibration sync
    # ------------------------------------------------------------------

    def sync_from_calibration(self):
        """Called by MainWindow whenever calibration changes or on startup."""
        if self.calibration_panel is None:
            self.well_selection.clear_calibration()
            self.start_btn.setEnabled(False)
            return

        corners = self.calibration_panel.get_corners()
        # A valid calibration requires all 4 corners to be set AND non-zero
        all_set = all(corners.get(name) is not None for name in CORNER_NAMES)
        
        # Simple heuristic: if all corners are exactly (0,0,0), it's likely just initialized session data
        all_zero = False
        if all_set:
            corners_list = [corners.get(n) for n in CORNER_NAMES]
            if all(c == (0.0, 0.0, 0.0) or c == [0.0, 0.0, 0.0] for c in corners_list):
                all_zero = True

        cols, rows = self.calibration_panel.get_well_dimensions()
        
        if not all_set or all_zero or rows == 0 or cols == 0:
            self.well_selection.clear_calibration()
            self.start_btn.setEnabled(False)
            self.start_btn.setToolTip("Please complete calibration in the Calibration tab first.")
            if not all_set:
                logger.info("[Experiment] Calibration incomplete — well grid cleared.")
            elif all_zero:
                logger.info("[Experiment] All corners are 0,0,0 — assuming uncalibrated.")
            else:
                logger.info("[Experiment] Well dimensions not set — well grid cleared.")
            return

        self.well_selection.rebuild(rows, cols)
        self.start_btn.setEnabled(True)
        self.start_btn.setToolTip("Begin the automated imaging sequence.")
        logger.info(f"[Experiment] Synced well grid: {rows} rows \u00d7 {cols} cols")
    # ------------------------------------------------------------------
    # Experiment control
    # ------------------------------------------------------------------

    def _start_experiment(self):
        if self.calibration_panel is None:
            self.status_label.setText("Status: Error — Calibration panel not found.")
            return

        corners = []
        for name in CORNER_NAMES:
            pos = self.calibration_panel.get_corners().get(name)
            if pos is None:
                self.status_label.setText(f"Status: Error — Corner '{name}' not set.")
                return
            corners.append(pos)

        cols, rows = self.calibration_panel.get_well_dimensions()
        selected_indices = self.well_selection.get_selected_indices()
        if not selected_indices:
            QMessageBox.warning(self, "No Wells Selected",
                                "Please select at least one well before starting.")
            return

        try:
            params = self._current_values()
            params["selected_well_indices"] = selected_indices
            well_plate = WellPlate(width=cols, depth=rows, corners=corners)
            experiment = Experiment(hw_manager, well_plate, params)
        except Exception as e:
            self.status_label.setText(f"Status: Error — {e}")
            return

        self.experiment_runner = _ExperimentRunner(experiment)
        self.experiment_runner.finished.connect(self._on_experiment_finished)
        self.experiment_runner.progress.connect(
            lambda msg: self.status_label.setText(f"Status: {msg}")
        )
        self.experiment_runner.start()
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.status_label.setText(f"Status: Running… ({len(selected_indices)} wells)")

    def _stop_experiment(self):
        if self.experiment_runner and self.experiment_runner.isRunning():
            self.experiment_runner.stop()
            self.status_label.setText("Status: Stopping…")

    def _on_experiment_finished(self):
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_label.setText("Status: Finished.")
        self.experiment_runner = None

    # ------------------------------------------------------------------
    # Presets
    # ------------------------------------------------------------------

    def _current_values(self) -> dict:
        d = {
            "name":         self.exp_name_input.text(),
            "mode":         self.mode_combo.currentText(),
            "pattern":      self.pattern_combo.currentText(),
            "dwell":        self.dwell_input.text(),
            "image_format": self.image_format_combo.currentText(),
            "output_dir":   str(self._get_output_dir()),
        }
        for k, edit in self._video_inputs.items():
            d[f"video_{k}"] = edit.text()
        return d

    def _apply_values(self, d: dict):
        self.exp_name_input.setText(d.get("name", "my_experiment"))
        mode = d.get("mode", self.MODE_VIDEO)
        idx = self.mode_combo.findText(mode)
        if idx >= 0:
            self.mode_combo.setCurrentIndex(idx)
        pat = d.get("pattern", "Raster")
        idx = self.pattern_combo.findText(pat)
        if idx >= 0:
            self.pattern_combo.setCurrentIndex(idx)
        self.dwell_input.setText(d.get("dwell", "0.5"))
        fmt = d.get("image_format", "PNG")
        idx = self.image_format_combo.findText(fmt)
        if idx >= 0:
            self.image_format_combo.setCurrentIndex(idx)
        for k, edit in self._video_inputs.items():
            if f"video_{k}" in d:
                edit.setText(str(d[f"video_{k}"]))

    def _choose_preset_folder(self):
        """Let the user pick a different preset folder."""
        folder = QFileDialog.getExistingDirectory(
            self, "Select Preset Folder",
            str(getattr(self, "_preset_dir", _default_preset_dir()))
        )
        if folder:
            self._preset_dir = Path(folder)
            self._preset_dir.mkdir(parents=True, exist_ok=True)
            self._preset_dir_label.setText(str(self._preset_dir))

    def _get_preset_dir(self) -> Path:
        d = getattr(self, "_preset_dir", _default_preset_dir())
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _choose_output_folder(self):
        """Let the user pick a different output folder for experiment captures."""
        folder = QFileDialog.getExistingDirectory(
            self, "Select Output Folder",
            str(getattr(self, "_output_dir", _default_output_dir()))
        )
        if folder:
            self._output_dir = Path(folder)
            self._output_dir.mkdir(parents=True, exist_ok=True)
            self._output_dir_label.setText(str(self._output_dir))

    def _get_output_dir(self) -> Path:
        d = getattr(self, "_output_dir", _default_output_dir())
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _open_output_folder(self):
        """Open the output folder in the system file explorer."""
        import subprocess, sys
        folder = self._get_output_dir()
        if sys.platform == "win32":
            subprocess.Popen(["explorer", str(folder)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)])
        else:
            subprocess.Popen(["xdg-open", str(folder)])

    def _save_preset(self):
        preset_dir = self._get_preset_dir()
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Experiment Preset",
            str(preset_dir / "preset.json"),
            "JSON Files (*.json)"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._current_values(), f, indent=2)
            self._preset_status.setText(f"Saved: {Path(path).name}")
            logger.info(f"[Experiment] Preset saved to {path}")
        except OSError as e:
            QMessageBox.critical(self, "Save Error", str(e))

    def _load_preset(self):
        preset_dir = self._get_preset_dir()
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Experiment Preset",
            str(preset_dir),
            "JSON Files (*.json)"
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._apply_values(data)
            self._preset_status.setText(f"Loaded: {Path(path).name}")
            logger.info(f"[Experiment] Preset loaded from {path}")
        except (OSError, json.JSONDecodeError) as e:
            QMessageBox.critical(self, "Load Error", str(e))

    # ------------------------------------------------------------------
    # Session persistence
    # ------------------------------------------------------------------

    def _autosave(self):
        self._session.update_session("experiment", self._current_values())

    def _load_from_session(self):
        s = self._session.get_session("experiment")
        self._apply_values(s)
