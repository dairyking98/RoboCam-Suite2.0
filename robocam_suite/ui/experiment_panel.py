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
    QScrollArea, QSplitter, QButtonGroup, QRadioButton,
    QStackedWidget,
)
from PySide6.QtCore import Qt, QThread, Signal, QSize
from PySide6.QtGui import QImage, QPixmap, QPainter, QColor, QMouseEvent

import cv2

from robocam_suite.hw_manager import hw_manager
from robocam_suite.experiments.experiment import Experiment
from robocam_suite.experiments.well_plate import WellPlate
from robocam_suite.session_manager import session_manager
from robocam_suite.logger import setup_logger

logger = setup_logger()

CORNER_NAMES = ["Upper-Left", "Lower-Left", "Upper-Right", "Lower-Right"]

STATUS_STYLE = "font-size: 10px; color: #888;"
LABEL_STYLE  = "font-size: 10px; color: #888; font-style: italic;"


def _default_preset_dir() -> Path:
    d = Path.home() / "Documents" / "RoboCam" / "experiment_presets"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# Camera frame grabber
# ---------------------------------------------------------------------------

class _FrameGrabber(QThread):
    frame_ready = Signal(QImage)

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
        while self._running:
            try:
                if camera.is_connected:
                    frame = camera.read_frame()
                    if frame is not None:
                        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        h, w, ch = rgb.shape
                        qimg = QImage(
                            rgb.data.tobytes(), w, h, ch * w,
                            QImage.Format.Format_RGB888
                        )
                        self.frame_ready.emit(qimg.copy())
            except Exception:
                pass
            self.msleep(interval_ms)


class _LivePreview(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 240)
        self._pixmap: Optional[QPixmap] = None
        lbl = QLabel("Camera not connected", self)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet("color: gray; font-size: 13px;")
        self._no_cam_lbl = lbl
        layout = QVBoxLayout(self)
        layout.addWidget(lbl)

    def update_frame(self, qimg: QImage):
        self._pixmap = QPixmap.fromImage(qimg)
        self._no_cam_lbl.hide()
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

    def run(self):
        self.experiment.run()
        self.finished.emit()

    def stop(self):
        self.experiment.stop()


# ---------------------------------------------------------------------------
# Well toggle button — supports drag-to-toggle via mouse tracking
# ---------------------------------------------------------------------------

class _WellButton(QPushButton):
    """Emits enter_while_pressed when the mouse enters it during a drag."""
    enter_while_pressed = Signal(int, int)

    SEL_STYLE = (
        "background-color: #2a7ae2; color: white; border: 1px solid #1a5ab2; "
        "border-radius: 3px; font-size: 9px; padding: 1px;"
    )
    DESEL_STYLE = (
        "background-color: #555; color: #aaa; border: 1px solid #333; "
        "border-radius: 3px; font-size: 9px; padding: 1px;"
    )

    def __init__(self, label: str, row: int, col: int, parent=None):
        super().__init__(label, parent)
        self._row = row
        self._col = col
        self._selected = True
        self.setFixedSize(36, 24)
        self._apply_style()
        self.setMouseTracking(True)

    def _apply_style(self):
        self.setStyleSheet(self.SEL_STYLE if self._selected else self.DESEL_STYLE)

    @property
    def is_selected(self) -> bool:
        return self._selected

    def set_selected(self, value: bool):
        if self._selected == value:
            return
        self._selected = value
        self._apply_style()

    def enterEvent(self, event):
        from PySide6.QtWidgets import QApplication
        if QApplication.mouseButtons() & Qt.MouseButton.LeftButton:
            self.enter_while_pressed.emit(self._row, self._col)
        super().enterEvent(event)


# ---------------------------------------------------------------------------
# Well grid inner widget — sizes to content so it anchors to the top
# ---------------------------------------------------------------------------

class _WellGridInner(QWidget):
    """
    Inner widget for the well selection scroll area.
    Overrides sizeHint so the scroll area does not give it unlimited height,
    which caused the grid to float to the bottom of the viewport.
    """

    def __init__(self, rows: int, cols: int, parent=None):
        super().__init__(parent)
        self._rows = rows
        self._cols = cols

    def sizeHint(self) -> QSize:
        # 24px per button + 2px spacing + 20px header row + margins
        h = 20 + self._rows * 26 + 8
        w = 30 + self._cols * 38 + 8
        return QSize(w, h)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()


# ---------------------------------------------------------------------------
# Well selection widget — drag-to-toggle
# ---------------------------------------------------------------------------

class WellSelectionWidget(QGroupBox):
    """
    Interactive grid of toggle buttons.
    Drag behaviour: the first well touched in a drag determines the target
    state for the entire drag stroke (paint-bucket style).
    """

    def __init__(self, parent=None):
        super().__init__("Well Selection", parent)
        self.setToolTip(
            "Click and drag over wells to select or deselect them.\n"
            "The first well you touch sets the target state for the whole drag:\n"
            "  • If it was selected → the drag deselects all wells it passes over.\n"
            "  • If it was deselected → the drag selects all wells it passes over.\n\n"
            "Use Check All / Uncheck All / Invert for bulk operations.\n"
            "Click 'Sync from Calibration' to match the grid to your plate."
        )
        self._rows = 8
        self._cols = 12
        self._buttons: dict[tuple[int, int], _WellButton] = {}
        self._drag_target_state: Optional[bool] = None

        outer = QVBoxLayout(self)
        outer.setSpacing(4)
        outer.setContentsMargins(4, 4, 4, 4)

        # Toolbar
        toolbar = QHBoxLayout()
        check_all_btn = QPushButton("Check All")
        check_all_btn.setFixedHeight(24)
        check_all_btn.clicked.connect(self.check_all)
        toolbar.addWidget(check_all_btn)
        uncheck_all_btn = QPushButton("Uncheck All")
        uncheck_all_btn.setFixedHeight(24)
        uncheck_all_btn.clicked.connect(self.uncheck_all)
        toolbar.addWidget(uncheck_all_btn)
        invert_btn = QPushButton("Invert")
        invert_btn.setFixedHeight(24)
        invert_btn.clicked.connect(self.invert)
        toolbar.addWidget(invert_btn)
        self._count_label = QLabel("")
        self._count_label.setStyleSheet(STATUS_STYLE)
        toolbar.addWidget(self._count_label, stretch=1)
        outer.addLayout(toolbar)

        # Scroll area containing the grid
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        outer.addWidget(self._scroll, stretch=1)

        self._rebuild_grid()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def rebuild(self, rows: int, cols: int):
        old = {pos: btn.is_selected for pos, btn in self._buttons.items()}
        self._rows = rows
        self._cols = cols
        self._drag_target_state = None
        self._rebuild_grid(old)

    def check_all(self):
        for btn in self._buttons.values():
            btn.set_selected(True)
        self._update_count()

    def uncheck_all(self):
        for btn in self._buttons.values():
            btn.set_selected(False)
        self._update_count()

    def invert(self):
        for btn in self._buttons.values():
            btn.set_selected(not btn.is_selected)
        self._update_count()

    def get_selected_indices(self) -> list[int]:
        indices = []
        idx = 0
        for row in range(self._rows):
            for col in range(self._cols):
                if self._buttons[(row, col)].is_selected:
                    indices.append(idx)
                idx += 1
        return indices

    # ------------------------------------------------------------------
    # Grid construction
    # ------------------------------------------------------------------

    def _rebuild_grid(self, old: dict | None = None):
        # Disconnect and delete old buttons
        for btn in self._buttons.values():
            try:
                btn.enter_while_pressed.disconnect()
                btn.pressed.disconnect()
            except RuntimeError:
                pass
            btn.deleteLater()
        self._buttons.clear()

        # Build a new inner widget that sizes to its content
        inner = _WellGridInner(self._rows, self._cols)
        grid = QGridLayout(inner)
        grid.setSpacing(2)
        grid.setContentsMargins(4, 4, 4, 4)
        grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        # Column headers
        for col in range(self._cols):
            lbl = QLabel(str(col + 1))
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet("font-size: 9px; color: gray;")
            lbl.setFixedSize(36, 16)
            grid.addWidget(lbl, 0, col + 1)

        # Row headers + buttons
        for row in range(self._rows):
            row_letter = chr(ord("A") + row)
            hdr = QLabel(row_letter)
            hdr.setAlignment(Qt.AlignmentFlag.AlignCenter)
            hdr.setStyleSheet("font-size: 9px; color: gray;")
            hdr.setFixedSize(24, 24)
            grid.addWidget(hdr, row + 1, 0)

            for col in range(self._cols):
                label = f"{row_letter}{col + 1}"
                btn = _WellButton(label, row, col)
                if old is not None:
                    btn.set_selected(old.get((row, col), True))
                btn.pressed.connect(
                    lambda r=row, c=col: self._on_drag_start(r, c)
                )
                btn.enter_while_pressed.connect(self._on_drag_enter)
                grid.addWidget(btn, row + 1, col + 1)
                self._buttons[(row, col)] = btn

        self._scroll.setWidget(inner)
        self._update_count()

    # ------------------------------------------------------------------
    # Drag-to-toggle logic
    # ------------------------------------------------------------------

    def _on_drag_start(self, row: int, col: int):
        btn = self._buttons[(row, col)]
        self._drag_target_state = not btn.is_selected
        btn.set_selected(self._drag_target_state)
        self._update_count()

    def _on_drag_enter(self, row: int, col: int):
        if self._drag_target_state is None:
            return
        self._buttons[(row, col)].set_selected(self._drag_target_state)
        self._update_count()

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._drag_target_state = None
        super().mouseReleaseEvent(event)

    def _update_count(self):
        total = len(self._buttons)
        selected = sum(1 for b in self._buttons.values() if b.is_selected)
        self._count_label.setText(f"{selected}/{total} wells selected")


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

        self.well_selection = WellSelectionWidget()
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

        # Mode selector
        layout.addWidget(QLabel("Mode:"), 0, 0)
        self.mode_combo = QComboBox()
        self.mode_combo.addItems([self.MODE_VIDEO, self.MODE_IMAGE])
        self.mode_combo.setToolTip(
            "Video Capture: records a video at each well with laser stimulation.\n"
            "Image Capture: captures a single image at each well."
        )
        self.mode_combo.currentTextChanged.connect(self._on_mode_changed)
        layout.addWidget(self.mode_combo, 0, 1)

        # Scan pattern
        layout.addWidget(QLabel("Scan Pattern:"), 1, 0)
        self.pattern_combo = QComboBox()
        self.pattern_combo.addItems(["Raster", "Snake"])
        self.pattern_combo.setToolTip(
            "Raster: visits wells left-to-right on every row.\n"
            "Snake: alternates direction each row to minimise stage travel."
        )
        layout.addWidget(self.pattern_combo, 1, 1)

        # Experiment name
        layout.addWidget(QLabel("Experiment Name:"), 2, 0)
        self.exp_name_input = QLineEdit("my_experiment")
        self.exp_name_input.setToolTip(
            "A short label for this run.\n"
            "Used to name the output folder: YYYYMMDD_HHMMSS_<name>/"
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
            "Seconds to wait after arriving at a well before any action.\n"
            "Allows vibration from stage movement to settle.\n"
            "Typical: 0.3–1.0 s"
        )
        self.dwell_input.textChanged.connect(self._autosave)
        layout.addWidget(self.dwell_input, 0, 1)
        layout.addWidget(QLabel("Settle after move — laser OFF", grp), 0, 2)
        layout.itemAtPosition(0, 2).widget().setStyleSheet(LABEL_STYLE)

        return grp

    def _build_video_group(self) -> QGroupBox:
        """Parameters for Video Capture mode only."""
        self._video_grp = QGroupBox("Video Capture Settings")
        layout = QGridLayout(self._video_grp)
        layout.setColumnStretch(1, 1)
        layout.setSpacing(4)

        rows = [
            ("laser_off_pre",  "2.0",  "Pre-Laser Record (s):",
             "Seconds to record with the laser OFF before turning it on.\n"
             "Camera is recording throughout.\nTypical: 1.0–5.0 s"),
            ("laser_on",       "1.0",  "Laser ON Duration (s):",
             "How long the laser stays on (stimulation window).\n"
             "Camera is recording throughout.\nTypical: 0.5–5.0 s"),
            ("laser_off_post", "2.0",  "Post-Laser Record (s):",
             "Seconds to record with the laser OFF after turning it off.\n"
             "Camera is recording throughout.\nTypical: 1.0–5.0 s"),
        ]
        self._video_inputs: dict[str, QLineEdit] = {}
        labels_right = [
            "Laser OFF — recording",
            "Laser ON — recording",
            "Laser OFF — recording",
        ]
        for i, (key, default, label, tip) in enumerate(rows):
            layout.addWidget(QLabel(label), i, 0)
            edit = QLineEdit(default)
            edit.setToolTip(tip)
            edit.textChanged.connect(self._autosave)
            layout.addWidget(edit, i, 1)
            right_lbl = QLabel(labels_right[i])
            right_lbl.setStyleSheet(LABEL_STYLE)
            layout.addWidget(right_lbl, i, 2)
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
            "File format for captured images.\n"
            "PNG: lossless, good for most uses.\n"
            "TIFF: lossless, larger files, preferred for scientific imaging.\n"
            "JPEG: lossy, smallest files."
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
        layout = QHBoxLayout(grp)

        save_btn = QPushButton("Save Preset…")
        save_btn.setToolTip("Save the current experiment parameters to a JSON file.")
        save_btn.clicked.connect(self._save_preset)
        layout.addWidget(save_btn)

        load_btn = QPushButton("Load Preset…")
        load_btn.setToolTip("Load experiment parameters from a previously saved JSON file.")
        load_btn.clicked.connect(self._load_preset)
        layout.addWidget(load_btn)

        self._preset_status = QLabel("")
        self._preset_status.setStyleSheet(STATUS_STYLE)
        layout.addWidget(self._preset_status)

        layout.addStretch()
        return grp

    def _build_controls_group(self) -> QGroupBox:
        grp = QGroupBox("Run")
        layout = QVBoxLayout(grp)

        btn_row = QHBoxLayout()
        self.start_btn = QPushButton("Start Experiment")
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
        return grp

    # ------------------------------------------------------------------
    # Mode switching
    # ------------------------------------------------------------------

    def _on_mode_changed(self):
        is_video = self.mode_combo.currentText() == self.MODE_VIDEO
        self._video_grp.setVisible(is_video)
        self._image_grp.setVisible(not is_video)
        self._autosave()

    # ------------------------------------------------------------------
    # Calibration sync
    # ------------------------------------------------------------------

    def sync_from_calibration(self):
        """Called by MainWindow whenever calibration changes or on startup."""
        if self.calibration_panel is None:
            return
        cols, rows = self.calibration_panel.get_well_dimensions()
        self.well_selection.rebuild(rows, cols)
        logger.info(f"[Experiment] Synced well grid: {rows} rows × {cols} cols")

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

    def _save_preset(self):
        preset_dir = _default_preset_dir()
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
            self._preset_status.setStyleSheet(STATUS_STYLE)
            logger.info(f"[Experiment] Preset saved to {path}")
        except OSError as e:
            QMessageBox.critical(self, "Save Error", str(e))

    def _load_preset(self):
        preset_dir = _default_preset_dir()
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
            self._preset_status.setStyleSheet(STATUS_STYLE)
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
