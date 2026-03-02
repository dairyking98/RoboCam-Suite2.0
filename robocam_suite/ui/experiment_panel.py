"""
Experiment Panel — configure, select wells, and run well-plate imaging experiments.

Three-column layout
--------------------
Column 1 (large)  : Live camera preview — same feed as Calibration tab.
Column 2 (medium) : Experiment parameters, presets, and run controls.
Column 3 (medium) : Well selection grid with drag-to-toggle interaction.

Well selection interaction
--------------------------
- Click and drag over wells to toggle them.
- The target state is determined by the FIRST well touched in each drag:
    if it was selected → the drag deselects all wells it passes over.
    if it was deselected → the drag selects all wells it passes over.
- This mirrors the behaviour of painting tools in image editors.
- Check All / Uncheck All / Invert buttons are also available.
- Well dimensions are synced from the Calibration tab.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QGridLayout, QLabel, QLineEdit, QGroupBox,
    QComboBox, QInputDialog, QMessageBox,
    QScrollArea, QSplitter, QSizePolicy,
)
from PySide6.QtCore import Qt, QThread, Signal, QPoint
from PySide6.QtGui import QImage, QPixmap, QPainter, QColor, QMouseEvent

import cv2

from robocam_suite.hw_manager import hw_manager
from robocam_suite.experiments.experiment import Experiment
from robocam_suite.experiments.well_plate import WellPlate
from robocam_suite.session_manager import session_manager
from robocam_suite.logger import setup_logger

logger = setup_logger()

CORNER_NAMES = ["Upper-Left", "Lower-Left", "Upper-Right", "Lower-Right"]


def _default_preset_dir() -> Path:
    d = Path.home() / "Documents" / "RoboCam" / "experiment_presets"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# Camera frame grabber (shared pattern with CalibrationPanel)
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
    """
    A well toggle button that emits enter_while_pressed(row, col) when the
    mouse enters it while the left button is held down.  The parent widget
    uses this to implement drag-to-paint selection.
    """
    enter_while_pressed = Signal(int, int)

    SELECTED_STYLE = (
        "background-color: #2a7ae2; color: white; border: 1px solid #1a5ab2; "
        "border-radius: 3px; font-size: 9px; padding: 1px;"
    )
    DESELECTED_STYLE = (
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
        # Track mouse so enterEvent fires even during drag
        self.setMouseTracking(True)

    def _apply_style(self):
        self.setStyleSheet(
            self.SELECTED_STYLE if self._selected else self.DESELECTED_STYLE
        )

    @property
    def is_selected(self) -> bool:
        return self._selected

    def set_selected(self, value: bool):
        if self._selected == value:
            return
        self._selected = value
        self._apply_style()

    def enterEvent(self, event):
        # Check if left mouse button is held anywhere in the application
        from PySide6.QtWidgets import QApplication
        if QApplication.mouseButtons() & Qt.MouseButton.LeftButton:
            self.enter_while_pressed.emit(self._row, self._col)
        super().enterEvent(event)


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
        self._drag_target_state: Optional[bool] = None  # None = no drag in progress

        outer = QVBoxLayout(self)
        outer.setSpacing(4)
        outer.setContentsMargins(4, 4, 4, 4)

        # Toolbar
        toolbar = QHBoxLayout()
        check_all_btn = QPushButton("Check All")
        check_all_btn.clicked.connect(self.check_all)
        toolbar.addWidget(check_all_btn)
        uncheck_all_btn = QPushButton("Uncheck All")
        uncheck_all_btn.clicked.connect(self.uncheck_all)
        toolbar.addWidget(uncheck_all_btn)
        invert_btn = QPushButton("Invert")
        invert_btn.clicked.connect(self.invert)
        toolbar.addWidget(invert_btn)
        self._count_label = QLabel("")
        self._count_label.setStyleSheet("font-size: 10px; color: gray;")
        toolbar.addWidget(self._count_label, stretch=1)
        outer.addLayout(toolbar)

        # Scrollable grid
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._grid_widget = QWidget()
        self._grid_layout = QGridLayout(self._grid_widget)
        self._grid_layout.setSpacing(2)
        self._grid_layout.setContentsMargins(2, 2, 2, 2)
        scroll.setWidget(self._grid_widget)
        outer.addWidget(scroll, stretch=1)

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

    def get_selected_labels(self) -> list[str]:
        return [
            self._buttons[(r, c)].text()
            for r in range(self._rows)
            for c in range(self._cols)
            if self._buttons[(r, c)].is_selected
        ]

    # ------------------------------------------------------------------
    # Grid construction
    # ------------------------------------------------------------------

    def _rebuild_grid(self, old: dict | None = None):
        for btn in self._buttons.values():
            try:
                btn.enter_while_pressed.disconnect()
                btn.pressed.disconnect()
            except RuntimeError:
                pass
            btn.deleteLater()
        self._buttons.clear()

        while self._grid_layout.count():
            item = self._grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Column headers
        for col in range(self._cols):
            lbl = QLabel(str(col + 1))
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet("font-size: 9px; color: gray;")
            self._grid_layout.addWidget(lbl, 0, col + 1)

        # Row headers + buttons
        for row in range(self._rows):
            row_letter = chr(ord("A") + row)
            hdr = QLabel(row_letter)
            hdr.setAlignment(Qt.AlignmentFlag.AlignCenter)
            hdr.setStyleSheet("font-size: 9px; color: gray;")
            self._grid_layout.addWidget(hdr, row + 1, 0)

            for col in range(self._cols):
                label = f"{row_letter}{col + 1}"
                btn = _WellButton(label, row, col)
                if old is not None:
                    btn.set_selected(old.get((row, col), True))
                # pressed fires when the button is first clicked — starts a drag
                btn.pressed.connect(
                    lambda r=row, c=col: self._on_drag_start(r, c)
                )
                # enter_while_pressed fires when mouse enters during a drag
                btn.enter_while_pressed.connect(self._on_drag_enter)
                self._grid_layout.addWidget(btn, row + 1, col + 1)
                self._buttons[(row, col)] = btn

        self._update_count()

    # ------------------------------------------------------------------
    # Drag-to-toggle logic
    # ------------------------------------------------------------------

    def _on_drag_start(self, row: int, col: int):
        """Called when the user first presses a well button."""
        btn = self._buttons[(row, col)]
        # The target state is the OPPOSITE of the first-touched well's current state
        self._drag_target_state = not btn.is_selected
        btn.set_selected(self._drag_target_state)
        self._update_count()

    def _on_drag_enter(self, row: int, col: int):
        """Called when the mouse enters a well while the button is held."""
        if self._drag_target_state is None:
            return
        self._buttons[(row, col)].set_selected(self._drag_target_state)
        self._update_count()

    def mouseReleaseEvent(self, event: QMouseEvent):
        """End the drag stroke when the mouse button is released."""
        self._drag_target_state = None
        super().mouseReleaseEvent(event)

    def _update_count(self):
        total = len(self._buttons)
        selected = sum(1 for b in self._buttons.values() if b.is_selected)
        self._count_label.setText(f"{selected}/{total} wells selected")


# ---------------------------------------------------------------------------
# Helper: labelled parameter row
# ---------------------------------------------------------------------------

def _field(label_text: str, default: str, tooltip: str,
           layout: QGridLayout, row: int) -> QLineEdit:
    lbl = QLabel(label_text)
    lbl.setToolTip(tooltip)
    layout.addWidget(lbl, row, 0)
    edit = QLineEdit(default)
    edit.setToolTip(tooltip)
    layout.addWidget(edit, row, 1)
    badge = QLabel("?")
    badge.setToolTip(tooltip)
    badge.setStyleSheet(
        "color: white; background: #555; border-radius: 8px; "
        "padding: 1px 5px; font-weight: bold;"
    )
    layout.addWidget(badge, row, 2)
    return edit


# ---------------------------------------------------------------------------
# Main panel
# ---------------------------------------------------------------------------

class ExperimentPanel(QWidget):
    """Three-column experiment panel: live preview | settings | well selection."""

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
        col2_layout.addWidget(self._build_params_group())
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

        sync_btn = QPushButton("Sync Grid from Calibration")
        sync_btn.setToolTip(
            "Load the well-plate dimensions from the Calibration tab\n"
            "and rebuild this selection grid to match."
        )
        sync_btn.clicked.connect(self._sync_from_calibration)
        col3_layout.addWidget(sync_btn)

        self.well_selection = WellSelectionWidget()
        col3_layout.addWidget(self.well_selection, stretch=1)
        splitter.addWidget(col3)

        # Proportions: camera ~40%, settings ~30%, wells ~30%
        splitter.setSizes([480, 360, 360])
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 1)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(splitter)

        self._load_from_session()

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

    def _build_params_group(self) -> QGroupBox:
        grp = QGroupBox("Experiment Parameters")
        layout = QGridLayout(grp)
        layout.setColumnStretch(1, 1)

        layout.addWidget(QLabel("Experiment Name:"), 0, 0)
        self.exp_name_input = QLineEdit("my_experiment")
        self.exp_name_input.setToolTip(
            "A short label for this run.\n"
            "Used to name the output folder: YYYYMMDD_HHMMSS_<name>/"
        )
        layout.addWidget(self.exp_name_input, 0, 1)
        badge = QLabel("?")
        badge.setToolTip(self.exp_name_input.toolTip())
        badge.setStyleSheet(
            "color: white; background: #555; border-radius: 8px; "
            "padding: 1px 5px; font-weight: bold;"
        )
        layout.addWidget(badge, 0, 2)

        self.param_inputs: dict[str, QLineEdit] = {}
        timing_params = [
            ("pre_laser_delay", "0.5",
             "Pre-Laser Delay (s):",
             "Seconds to wait after arriving at a well before turning the laser on.\n"
             "Allows vibration from movement to settle before imaging.\n"
             "Typical: 0.3–1.0 s"),
            ("laser_on_duration", "1.0",
             "Laser On Duration (s):",
             "How long the laser stays on per well (in seconds).\n"
             "This is the stimulation or illumination window.\n"
             "Typical: 0.5–5.0 s"),
            ("recording_duration", "5.0",
             "Recording Duration (s):",
             "How long the camera records video at each well (in seconds).\n"
             "Recording starts when the laser turns on.\n"
             "Typical: 2.0–30.0 s"),
            ("post_well_delay", "0.5",
             "Post-Well Delay (s):",
             "Seconds to wait after finishing a well before moving to the next.\n"
             "Useful for letting the sample recover or settle.\n"
             "Typical: 0.0–2.0 s"),
        ]
        for i, (key, default, label_text, tip) in enumerate(timing_params):
            edit = _field(label_text, default, tip, layout, i + 1)
            self.param_inputs[key] = edit
            edit.textChanged.connect(self._autosave)

        self.exp_name_input.textChanged.connect(self._autosave)
        return grp

    def _build_presets_group(self) -> QGroupBox:
        grp = QGroupBox("Presets")
        grp.setToolTip(
            "Save the current parameters as a named preset.\n"
            "Presets are stored in Documents/RoboCam/experiment_presets/"
        )
        layout = QHBoxLayout(grp)

        self.preset_combo = QComboBox()
        self.preset_combo.setToolTip("Select a saved preset to load.")
        self.preset_combo.setMinimumWidth(160)
        layout.addWidget(self.preset_combo)

        load_btn = QPushButton("Load")
        load_btn.setToolTip("Load the selected preset.")
        load_btn.clicked.connect(self._load_preset)
        layout.addWidget(load_btn)

        save_btn = QPushButton("Save As…")
        save_btn.setToolTip("Save the current parameters as a new named preset.")
        save_btn.clicked.connect(self._save_preset)
        layout.addWidget(save_btn)

        delete_btn = QPushButton("Delete")
        delete_btn.setToolTip("Delete the selected preset permanently.")
        delete_btn.clicked.connect(self._delete_preset)
        layout.addWidget(delete_btn)

        self._refresh_presets()
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
        layout.addWidget(self.status_label)

        self.start_btn.clicked.connect(self._start_experiment)
        self.stop_btn.clicked.connect(self._stop_experiment)
        return grp

    # ------------------------------------------------------------------
    # Calibration sync
    # ------------------------------------------------------------------

    def _sync_from_calibration(self):
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
            params = {k: float(v.text()) for k, v in self.param_inputs.items()}
            params["name"] = self.exp_name_input.text()
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
        d = {k: v.text() for k, v in self.param_inputs.items()}
        d["name"] = self.exp_name_input.text()
        return d

    def _apply_values(self, d: dict):
        self.exp_name_input.setText(d.get("name", "my_experiment"))
        for k, edit in self.param_inputs.items():
            if k in d:
                edit.setText(str(d[k]))

    def _refresh_presets(self):
        self.preset_combo.clear()
        for f in sorted(_default_preset_dir().glob("*.json")):
            self.preset_combo.addItem(f.stem)

    def _save_preset(self):
        name, ok = QInputDialog.getText(self, "Save Preset", "Preset name:")
        if not ok or not name.strip():
            return
        name = name.strip()
        path = _default_preset_dir() / f"{name}.json"
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._current_values(), f, indent=2)
        except OSError as e:
            QMessageBox.critical(self, "Save Error", str(e))
            return
        self._refresh_presets()
        idx = self.preset_combo.findText(name)
        if idx >= 0:
            self.preset_combo.setCurrentIndex(idx)

    def _load_preset(self):
        name = self.preset_combo.currentText()
        if not name:
            return
        path = _default_preset_dir() / f"{name}.json"
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._apply_values(data)
        except (OSError, json.JSONDecodeError) as e:
            QMessageBox.critical(self, "Load Error", str(e))

    def _delete_preset(self):
        name = self.preset_combo.currentText()
        if not name:
            return
        reply = QMessageBox.question(
            self, "Delete Preset", f"Delete preset '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            (_default_preset_dir() / f"{name}.json").unlink(missing_ok=True)
            self._refresh_presets()

    # ------------------------------------------------------------------
    # Session persistence
    # ------------------------------------------------------------------

    def _autosave(self):
        self._session.update_session("experiment", self._current_values())

    def _load_from_session(self):
        s = self._session.get_session("experiment")
        self._apply_values(s)
