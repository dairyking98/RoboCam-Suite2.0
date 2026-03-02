"""
Experiment Panel — configure, save, and run well-plate imaging experiments.

Features:
  - Inline help text explaining every parameter.
  - All values are auto-saved on change and restored on next launch.
  - Named presets can be saved and recalled for different experimental setups.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QGridLayout, QLabel, QLineEdit, QGroupBox, QSpinBox,
    QComboBox, QInputDialog, QMessageBox, QDoubleSpinBox,
)
from PySide6.QtCore import Qt, QThread, Signal

from robocam_suite.hw_manager import hw_manager
from robocam_suite.experiments.experiment import Experiment
from robocam_suite.experiments.well_plate import WellPlate
from robocam_suite.session_manager import session_manager


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
    # Help icon label
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
    """Configure and run a well-plate imaging experiment."""

    def __init__(self, parent=None, calibration_panel=None):
        super().__init__(parent)
        self.calibration_panel = calibration_panel
        self.experiment_runner: ExperimentRunner | None = None
        self._session = session_manager

        root = QVBoxLayout(self)
        root.setSpacing(8)

        root.addWidget(self._build_params_group())
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
        self.width_spinbox.valueChanged.connect(self._autosave)
        self.depth_spinbox.valueChanged.connect(self._autosave)

        return grp

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
            "Requires all four well-plate corners to be set in the Calibration tab."
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
    # Experiment control
    # ------------------------------------------------------------------

    def _start_experiment(self):
        if self.calibration_panel is None:
            self.status_label.setText("Status: Error — Calibration panel not found.")
            return

        corners = []
        for name in ["Upper-Left", "Lower-Left", "Upper-Right", "Lower-Right"]:
            pos = self.calibration_panel.get_corners().get(name)
            if pos is None:
                self.status_label.setText(f"Status: Error — Corner '{name}' not set.")
                return
            corners.append(pos)

        try:
            params = {k: float(v.text()) for k, v in self.param_inputs.items()}
            params["name"] = self.exp_name_input.text()
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
        self.status_label.setText("Status: Running…")

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
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
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
