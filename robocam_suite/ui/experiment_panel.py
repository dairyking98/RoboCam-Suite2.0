"""
Experiment Panel — configure, select wells, and run well-plate imaging experiments.

Features:
  - Inline help text explaining every parameter.
  - Interactive well-selection grid (click to toggle, Shift-click for range,
    Check All / Uncheck All buttons).
  - All values are auto-saved on change and restored on next launch.
  - Named presets can be saved and recalled for different experimental setups.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QGridLayout, QLabel, QLineEdit, QGroupBox, QSpinBox,
    QComboBox, QInputDialog, QMessageBox, QScrollArea,
    QSizePolicy,
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor

from robocam_suite.hw_manager import hw_manager
from robocam_suite.experiments.experiment import Experiment
from robocam_suite.experiments.well_plate import WellPlate
from robocam_suite.session_manager import session_manager
from robocam_suite.logger import setup_logger

logger = setup_logger()

# Corner order expected by WellPlate
CORNER_NAMES = ["Upper-Left", "Lower-Left", "Upper-Right", "Lower-Right"]


# ---------------------------------------------------------------------------
# Background experiment runner
# ---------------------------------------------------------------------------

class ExperimentRunner(QThread):
    """Runs an Experiment in a background thread so the GUI stays responsive."""
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
# Well toggle button
# ---------------------------------------------------------------------------

class _WellButton(QPushButton):
    """A small toggle button representing a single well in the selection grid."""

    SELECTED_STYLE = (
        "background-color: #2a7ae2; color: white; border: 1px solid #1a5ab2; "
        "border-radius: 3px; font-size: 9px; padding: 1px;"
    )
    DESELECTED_STYLE = (
        "background-color: #555; color: #aaa; border: 1px solid #333; "
        "border-radius: 3px; font-size: 9px; padding: 1px;"
    )

    def __init__(self, label: str, parent=None):
        super().__init__(label, parent)
        self._selected = True
        self.setFixedSize(36, 24)
        self.setCheckable(True)
        self.setChecked(True)
        self._apply_style()
        self.toggled.connect(self._on_toggled)

    def _on_toggled(self, checked: bool):
        self._selected = checked
        self._apply_style()

    def _apply_style(self):
        self.setStyleSheet(
            self.SELECTED_STYLE if self._selected else self.DESELECTED_STYLE
        )

    @property
    def is_selected(self) -> bool:
        return self._selected

    def set_selected(self, value: bool):
        self.setChecked(value)


# ---------------------------------------------------------------------------
# Well selection widget
# ---------------------------------------------------------------------------

class WellSelectionWidget(QGroupBox):
    """
    An interactive grid of toggle buttons, one per well.

    Supports:
    - Click to toggle individual wells.
    - Shift-click to select a rectangular range.
    - Check All / Uncheck All buttons.
    - Rebuilds automatically when rows/cols change.
    """

    def __init__(self, parent=None):
        super().__init__("Well Selection", parent)
        self.setToolTip(
            "Click a well to toggle it on/off.\n"
            "Shift-click to select a rectangular range.\n"
            "Only selected wells (blue) will be visited during the experiment."
        )
        self._rows = 8
        self._cols = 12
        self._buttons: dict[tuple[int, int], _WellButton] = {}
        self._last_clicked: tuple[int, int] | None = None

        outer = QVBoxLayout(self)
        outer.setSpacing(4)

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

        # Scrollable grid
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(220)
        self._grid_widget = QWidget()
        self._grid_layout = QGridLayout(self._grid_widget)
        self._grid_layout.setSpacing(2)
        scroll.setWidget(self._grid_widget)
        outer.addWidget(scroll)

        self._rebuild_grid()

    def rebuild(self, rows: int, cols: int):
        """Rebuild the grid for a new well-plate size, preserving selection where possible."""
        old_selection: dict[tuple[int, int], bool] = {
            pos: btn.is_selected for pos, btn in self._buttons.items()
        }
        self._rows = rows
        self._cols = cols
        self._rebuild_grid(old_selection)

    def _rebuild_grid(self, old_selection: dict | None = None):
        # Clear existing buttons
        for btn in self._buttons.values():
            btn.deleteLater()
        self._buttons.clear()
        self._last_clicked = None

        # Remove all items from layout
        while self._grid_layout.count():
            item = self._grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Column headers (A, B, C …)
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
                btn = _WellButton(label)
                # Restore previous selection if available
                if old_selection is not None:
                    btn.set_selected(old_selection.get((row, col), True))
                btn.clicked.connect(
                    lambda checked, r=row, c=col: self._on_well_clicked(r, c)
                )
                self._grid_layout.addWidget(btn, row + 1, col + 1)
                self._buttons[(row, col)] = btn

        self._update_count()

    def _on_well_clicked(self, row: int, col: int):
        modifiers = Qt.KeyboardModifier
        app_mods = __import__("PySide6.QtWidgets", fromlist=["QApplication"]).QApplication.keyboardModifiers()
        btn = self._buttons[(row, col)]

        if app_mods & Qt.KeyboardModifier.ShiftModifier and self._last_clicked is not None:
            # Range select: toggle all wells in the bounding rectangle
            r0, c0 = self._last_clicked
            r1, c1 = row, col
            target_state = btn.is_selected
            for r in range(min(r0, r1), max(r0, r1) + 1):
                for c in range(min(c0, c1), max(c0, c1) + 1):
                    self._buttons[(r, c)].set_selected(target_state)
        else:
            self._last_clicked = (row, col)

        self._update_count()

    def _update_count(self):
        total = len(self._buttons)
        selected = sum(1 for b in self._buttons.values() if b.is_selected)
        self._count_label.setText(f"{selected}/{total} wells selected")

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
        """
        Return a flat list of well indices (0-based, row-major order)
        that are currently selected.
        """
        indices = []
        idx = 0
        for row in range(self._rows):
            for col in range(self._cols):
                if self._buttons[(row, col)].is_selected:
                    indices.append(idx)
                idx += 1
        return indices

    def get_selected_labels(self) -> list[str]:
        """Return the labels of all selected wells (e.g. ['A1', 'A2', 'B3'])."""
        labels = []
        for row in range(self._rows):
            for col in range(self._cols):
                btn = self._buttons[(row, col)]
                if btn.is_selected:
                    labels.append(btn.text())
        return labels


# ---------------------------------------------------------------------------
# Helper: labelled field with tooltip
# ---------------------------------------------------------------------------

def _field(label_text: str, default: str, tooltip: str,
           layout: QGridLayout, row: int) -> QLineEdit:
    lbl = QLabel(label_text)
    lbl.setToolTip(tooltip)
    layout.addWidget(lbl, row, 0)
    edit = QLineEdit(default)
    edit.setToolTip(tooltip)
    layout.addWidget(edit, row, 1)
    help_lbl = QLabel("?")
    help_lbl.setToolTip(tooltip)
    help_lbl.setStyleSheet(
        "color: white; background: #555; border-radius: 8px; "
        "padding: 1px 5px; font-weight: bold;"
    )
    layout.addWidget(help_lbl, row, 2)
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
        root.setSpacing(8)

        root.addWidget(self._build_params_group())
        root.addWidget(self._build_well_selection_group())
        root.addWidget(self._build_presets_group())
        root.addWidget(self._build_controls_group())
        root.addStretch()

        self._load_from_session()

    # ------------------------------------------------------------------
    # Group builders
    # ------------------------------------------------------------------

    def _build_params_group(self) -> QGroupBox:
        grp = QGroupBox("Experiment Parameters")
        layout = QGridLayout(grp)
        layout.setColumnStretch(1, 1)

        # Experiment name
        layout.addWidget(QLabel("Experiment Name:"), 0, 0)
        self.exp_name_input = QLineEdit("my_experiment")
        self.exp_name_input.setToolTip(
            "A short label for this run.\n"
            "Used to name the output folder: YYYYMMDD_HHMMSS_<name>/"
        )
        layout.addWidget(self.exp_name_input, 0, 1)
        name_help = QLabel("?")
        name_help.setToolTip(self.exp_name_input.toolTip())
        name_help.setStyleSheet(
            "color: white; background: #555; border-radius: 8px; padding: 1px 5px; font-weight: bold;"
        )
        layout.addWidget(name_help, 0, 2)

        # Well plate dimensions
        layout.addWidget(QLabel("Well Plate Columns:"), 1, 0)
        self.width_spinbox = QSpinBox()
        self.width_spinbox.setRange(1, 48)
        self.width_spinbox.setValue(12)
        self.width_spinbox.setToolTip(
            "Number of columns (horizontal wells) in the well plate.\n"
            "Standard plates: 6-well=3 cols, 12-well=4 cols, 24-well=6 cols,\n"
            "48-well=8 cols, 96-well=12 cols."
        )
        layout.addWidget(self.width_spinbox, 1, 1)
        w_help = QLabel("?")
        w_help.setToolTip(self.width_spinbox.toolTip())
        w_help.setStyleSheet("color: white; background: #555; border-radius: 8px; padding: 1px 5px; font-weight: bold;")
        layout.addWidget(w_help, 1, 2)

        layout.addWidget(QLabel("Well Plate Rows:"), 2, 0)
        self.depth_spinbox = QSpinBox()
        self.depth_spinbox.setRange(1, 48)
        self.depth_spinbox.setValue(8)
        self.depth_spinbox.setToolTip(
            "Number of rows (vertical wells) in the well plate.\n"
            "Standard plates: 6-well=2 rows, 12-well=3 rows, 24-well=4 rows,\n"
            "48-well=6 rows, 96-well=8 rows."
        )
        layout.addWidget(self.depth_spinbox, 2, 1)
        d_help = QLabel("?")
        d_help.setToolTip(self.depth_spinbox.toolTip())
        d_help.setStyleSheet("color: white; background: #555; border-radius: 8px; padding: 1px 5px; font-weight: bold;")
        layout.addWidget(d_help, 2, 2)

        # Timing parameters
        self.param_inputs: dict[str, QLineEdit] = {}
        timing_params = [
            ("pre_laser_delay", "0.5",
             "Pre-Laser Delay (s):",
             "Seconds to wait after arriving at a well before turning the laser on.\n"
             "Allows any vibration from movement to settle before imaging."),
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
            edit = _field(label_text, default, tip, layout, i + 3)
            self.param_inputs[key] = edit
            edit.textChanged.connect(self._autosave)

        # Autosave connections
        self.exp_name_input.textChanged.connect(self._autosave)
        self.width_spinbox.valueChanged.connect(self._on_dimensions_changed)
        self.depth_spinbox.valueChanged.connect(self._on_dimensions_changed)

        return grp

    def _build_well_selection_group(self) -> QWidget:
        """Build the well-selection widget and wire it to the dimension spinboxes."""
        self.well_selection = WellSelectionWidget()
        return self.well_selection

    def _build_presets_group(self) -> QGroupBox:
        grp = QGroupBox("Presets")
        grp.setToolTip(
            "Save the current parameters as a named preset so you can quickly\n"
            "recall them for a particular experimental setup."
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
    # Dimension change handler
    # ------------------------------------------------------------------

    def _on_dimensions_changed(self):
        rows = self.depth_spinbox.value()
        cols = self.width_spinbox.value()
        self.well_selection.rebuild(rows, cols)
        self._autosave()

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
            well_plate = WellPlate(
                width=self.width_spinbox.value(),
                depth=self.depth_spinbox.value(),
                corners=corners,
            )
            experiment = Experiment(hw_manager, well_plate, params)
        except Exception as e:
            self.status_label.setText(f"Status: Error — {e}")
            return

        self.experiment_runner = ExperimentRunner(experiment)
        self.experiment_runner.finished.connect(self._on_experiment_finished)
        self.experiment_runner.start()
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        n = len(selected_indices)
        self.status_label.setText(f"Status: Running… ({n} wells)")

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
        d["well_plate_width"] = self.width_spinbox.value()
        d["well_plate_depth"] = self.depth_spinbox.value()
        return d

    def _apply_values(self, d: dict):
        self.exp_name_input.setText(d.get("name", "my_experiment"))
        self.width_spinbox.setValue(int(d.get("well_plate_width", 12)))
        self.depth_spinbox.setValue(int(d.get("well_plate_depth", 8)))
        for k, edit in self.param_inputs.items():
            if k in d:
                edit.setText(str(d[k]))

    def _refresh_presets(self):
        self.preset_combo.clear()
        for name in session_manager.list_presets():
            self.preset_combo.addItem(name)

    def _save_preset(self):
        name, ok = QInputDialog.getText(self, "Save Preset", "Preset name:")
        if ok and name.strip():
            session_manager.save_preset(name.strip(), self._current_values())
            self._refresh_presets()
            idx = self.preset_combo.findText(name.strip())
            if idx >= 0:
                self.preset_combo.setCurrentIndex(idx)

    def _load_preset(self):
        name = self.preset_combo.currentText()
        if not name:
            return
        data = session_manager.load_preset(name)
        if data:
            self._apply_values(data)

    def _delete_preset(self):
        name = self.preset_combo.currentText()
        if not name:
            return
        reply = QMessageBox.question(
            self, "Delete Preset",
            f"Delete preset '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            session_manager.delete_preset(name)
            self._refresh_presets()

    # ------------------------------------------------------------------
    # Session persistence
    # ------------------------------------------------------------------

    def _autosave(self):
        self._session.update_session("experiment", self._current_values())

    def _load_from_session(self):
        s = self._session.get_session("experiment")
        self._apply_values(s)
        # Rebuild the well grid to match restored dimensions
        self.well_selection.rebuild(
            self.depth_spinbox.value(),
            self.width_spinbox.value(),
        )
