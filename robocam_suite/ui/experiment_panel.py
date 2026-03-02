"""
Experiment Panel — configure, select wells, and run well-plate imaging experiments.

Layout order (top to bottom)
-----------------------------
1. Well Selection  — loaded from calibration; Shift/Ctrl-click supported.
2. Experiment Parameters — timing fields only (no rows/cols here).
3. Presets — saved to Documents/RoboCam/experiment_presets/.
4. Run controls.

Well Selection click behaviour
--------------------------------
- Plain click      : toggle well + set range anchor.
- Shift + click    : rectangular range select/deselect from anchor to here.
- Ctrl  + click    : additive individual toggle (anchor unchanged).

Note: modifier detection uses mousePressEvent on each button, NOT the
clicked() signal, because Qt clears modifier state before clicked fires.
"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QGridLayout, QLabel, QLineEdit, QGroupBox, QSpinBox,
    QComboBox, QInputDialog, QMessageBox, QScrollArea,
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QMouseEvent

from robocam_suite.hw_manager import hw_manager
from robocam_suite.experiments.experiment import Experiment
from robocam_suite.experiments.well_plate import WellPlate
from robocam_suite.session_manager import session_manager
from robocam_suite.logger import setup_logger

logger = setup_logger()

CORNER_NAMES = ["Upper-Left", "Lower-Left", "Upper-Right", "Lower-Right"]


def _default_preset_dir() -> Path:
    return Path.home() / "Documents" / "RoboCam" / "experiment_presets"


# ---------------------------------------------------------------------------
# Background experiment runner
# ---------------------------------------------------------------------------

class ExperimentRunner(QThread):
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
# Well toggle button — captures mouse modifiers in mousePressEvent
# ---------------------------------------------------------------------------

class _WellButton(QPushButton):
    # Emits (row, col, Qt.KeyboardModifiers)
    well_pressed = Signal(int, int, object)

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

    def mousePressEvent(self, event: QMouseEvent):
        # Capture modifiers HERE — before Qt clears them in the base handler
        if event.button() == Qt.MouseButton.LeftButton:
            self.well_pressed.emit(self._row, self._col, event.modifiers())
        super().mousePressEvent(event)


# ---------------------------------------------------------------------------
# Well selection widget
# ---------------------------------------------------------------------------

class WellSelectionWidget(QGroupBox):
    """
    Interactive grid of toggle buttons driven by calibration dimensions.
    Dimensions are set externally via rebuild(); the widget never owns rows/cols.
    """

    def __init__(self, parent=None):
        super().__init__("Well Selection", parent)
        self.setToolTip(
            "Click a well to toggle it.\n"
            "Shift-click to select a rectangular range.\n"
            "Ctrl-click to toggle individual wells additively.\n"
            "Only selected (blue) wells will be visited during the experiment."
        )
        self._rows = 8
        self._cols = 12
        self._buttons: dict[tuple[int, int], _WellButton] = {}
        self._anchor: tuple[int, int] | None = None

        outer = QVBoxLayout(self)
        outer.setSpacing(4)
        outer.setContentsMargins(4, 4, 4, 4)

        # Toolbar
        toolbar = QHBoxLayout()
        check_all_btn = QPushButton("Check All")
        check_all_btn.setToolTip("Select all wells.")
        check_all_btn.clicked.connect(self.check_all)
        toolbar.addWidget(check_all_btn)

        uncheck_all_btn = QPushButton("Uncheck All")
        uncheck_all_btn.setToolTip("Deselect all wells.")
        uncheck_all_btn.clicked.connect(self.uncheck_all)
        toolbar.addWidget(uncheck_all_btn)

        invert_btn = QPushButton("Invert")
        invert_btn.setToolTip("Invert the current selection.")
        invert_btn.clicked.connect(self.invert)
        toolbar.addWidget(invert_btn)

        self._count_label = QLabel("")
        self._count_label.setStyleSheet("font-size: 10px; color: gray;")
        toolbar.addWidget(self._count_label, stretch=1)
        outer.addLayout(toolbar)

        # Scrollable grid — no fixed height cap; expands to fill available space
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
        """Rebuild the grid for a new plate size, preserving selection where possible."""
        old: dict[tuple[int, int], bool] = {
            pos: btn.is_selected for pos, btn in self._buttons.items()
        }
        self._rows = rows
        self._cols = cols
        self._anchor = None
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
            btn.well_pressed.disconnect()
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
                # Connect via well_pressed — modifiers captured in mousePressEvent
                btn.well_pressed.connect(self._on_well_pressed)
                self._grid_layout.addWidget(btn, row + 1, col + 1)
                self._buttons[(row, col)] = btn

        self._update_count()

    # ------------------------------------------------------------------
    # Click handling — modifiers arrive reliably here
    # ------------------------------------------------------------------

    def _on_well_pressed(self, row: int, col: int, modifiers):
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        ctrl  = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        btn   = self._buttons[(row, col)]

        if shift and self._anchor is not None:
            # Rectangular range: target state = opposite of anchor's current state
            r0, c0 = self._anchor
            target = not self._buttons[self._anchor].is_selected
            for r in range(min(r0, row), max(r0, row) + 1):
                for c in range(min(c0, col), max(c0, col) + 1):
                    self._buttons[(r, c)].set_selected(target)
            # Anchor stays at original position

        elif ctrl:
            # Additive individual toggle — anchor unchanged
            btn.set_selected(not btn.is_selected)

        else:
            # Plain click — toggle and move anchor
            btn.set_selected(not btn.is_selected)
            self._anchor = (row, col)

        self._update_count()

    def _update_count(self):
        total = len(self._buttons)
        selected = sum(1 for b in self._buttons.values() if b.is_selected)
        self._count_label.setText(f"{selected}/{total} wells selected")


# ---------------------------------------------------------------------------
# Helper: labelled parameter field with tooltip badge
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
    """Configure, select wells, and run a well-plate imaging experiment."""

    def __init__(self, parent=None, calibration_panel=None):
        super().__init__(parent)
        self.calibration_panel = calibration_panel
        self.experiment_runner: ExperimentRunner | None = None
        self._session = session_manager

        root = QVBoxLayout(self)
        root.setSpacing(6)
        root.setContentsMargins(6, 6, 6, 6)

        # 1. Well selection — top, takes most vertical space
        self.well_selection = WellSelectionWidget()
        root.addWidget(self.well_selection, stretch=3)

        # Sync button just above the well grid
        sync_row = QHBoxLayout()
        sync_btn = QPushButton("Sync Well Grid from Calibration")
        sync_btn.setToolTip(
            "Load the well-plate dimensions from the Calibration tab\n"
            "and rebuild this selection grid to match."
        )
        sync_btn.clicked.connect(self._sync_from_calibration)
        sync_row.addWidget(sync_btn)
        sync_row.addStretch()
        # Insert above well_selection
        root.insertLayout(0, sync_row)

        # 2. Parameters
        root.addWidget(self._build_params_group(), stretch=0)

        # 3. Presets
        root.addWidget(self._build_presets_group(), stretch=0)

        # 4. Run controls
        root.addWidget(self._build_controls_group(), stretch=0)

        self._load_from_session()

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
        name_badge = QLabel("?")
        name_badge.setToolTip(self.exp_name_input.toolTip())
        name_badge.setStyleSheet(
            "color: white; background: #555; border-radius: 8px; "
            "padding: 1px 5px; font-weight: bold;"
        )
        layout.addWidget(name_badge, 0, 2)

        self.param_inputs: dict[str, QLineEdit] = {}
        timing_params = [
            ("pre_laser_delay", "0.5",
             "Pre-Laser Delay (s):",
             "Seconds to wait after arriving at a well before turning the laser on.\n"
             "Allows vibration from movement to settle before imaging."),
            ("laser_on_duration", "1.0",
             "Laser On Duration (s):",
             "How long the laser stays on per well (in seconds).\n"
             "This is the stimulation or illumination window."),
            ("recording_duration", "5.0",
             "Recording Duration (s):",
             "How long the camera records video at each well (in seconds).\n"
             "Recording starts when the laser turns on."),
            ("post_well_delay", "0.5",
             "Post-Well Delay (s):",
             "Seconds to wait after finishing a well before moving to the next.\n"
             "Useful for letting the sample recover or settle."),
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
            f"Presets are stored in Documents/RoboCam/experiment_presets/"
        )
        layout = QHBoxLayout(grp)

        self.preset_combo = QComboBox()
        self.preset_combo.setToolTip("Select a saved preset to load.")
        self.preset_combo.setMinimumWidth(160)
        layout.addWidget(self.preset_combo)

        load_btn = QPushButton("Load")
        load_btn.setToolTip("Load the selected preset into the fields above.")
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
        logger.info(f"[Experiment] Synced well grid from calibration: {rows}×{cols}")

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

        selected_labels = self.well_selection.get_selected_labels()
        logger.info(f"[Experiment] Running on {len(selected_indices)} wells: {selected_labels}")

        try:
            params = {k: float(v.text()) for k, v in self.param_inputs.items()}
            params["name"] = self.exp_name_input.text()
            params["selected_well_indices"] = selected_indices
            well_plate = WellPlate(width=cols, depth=rows, corners=corners)
            experiment = Experiment(hw_manager, well_plate, params)
        except Exception as e:
            self.status_label.setText(f"Status: Error — {e}")
            return

        self.experiment_runner = ExperimentRunner(experiment)
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
    # Presets — stored as JSON files in Documents/RoboCam/experiment_presets/
    # ------------------------------------------------------------------

    def _preset_dir(self) -> Path:
        d = _default_preset_dir()
        d.mkdir(parents=True, exist_ok=True)
        return d

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
        preset_dir = self._preset_dir()
        for f in sorted(preset_dir.glob("*.json")):
            self.preset_combo.addItem(f.stem)

    def _save_preset(self):
        name, ok = QInputDialog.getText(self, "Save Preset", "Preset name:")
        if not ok or not name.strip():
            return
        name = name.strip()
        path = self._preset_dir() / f"{name}.json"
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
        path = self._preset_dir() / f"{name}.json"
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
            path = self._preset_dir() / f"{name}.json"
            path.unlink(missing_ok=True)
            self._refresh_presets()

    # ------------------------------------------------------------------
    # Session persistence (timing params + name only — not well selection)
    # ------------------------------------------------------------------

    def _autosave(self):
        self._session.update_session("experiment", self._current_values())

    def _load_from_session(self):
        s = self._session.get_session("experiment")
        self._apply_values(s)
