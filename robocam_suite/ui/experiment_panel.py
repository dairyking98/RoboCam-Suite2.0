from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QGridLayout, QLabel, QLineEdit, QGroupBox, QSpinBox
from PySide6.QtCore import Qt, QThread, Signal
from robocam_suite.hw_manager import hw_manager
from robocam_suite.experiments.experiment import Experiment
from robocam_suite.experiments.well_plate import WellPlate
import time

class ExperimentRunner(QThread):
    """A QThread to run the experiment in the background."""
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

class ExperimentPanel(QWidget):
    """A widget for configuring and running experiments."""

    def __init__(self, parent=None, calibration_panel=None):
        super().__init__(parent)
        self.calibration_panel = calibration_panel
        self.experiment_runner = None

        self.layout = QVBoxLayout(self)

        # Experiment Parameters
        params_group = QGroupBox("Experiment Parameters")
        params_layout = QGridLayout()
        params_group.setLayout(params_layout)
        self.layout.addWidget(params_group)

        # Well Plate Dimensions
        params_layout.addWidget(QLabel("Well Plate Width:"), 0, 0)
        self.width_spinbox = QSpinBox()
        self.width_spinbox.setValue(12)
        params_layout.addWidget(self.width_spinbox, 0, 1)

        params_layout.addWidget(QLabel("Well Plate Depth:"), 1, 0)
        self.depth_spinbox = QSpinBox()
        self.depth_spinbox.setValue(8)
        params_layout.addWidget(self.depth_spinbox, 1, 1)

        # Timings
        self.param_inputs = {}
        for i, (name, default_val) in enumerate([
            ("pre_laser_delay", "0.5"),
            ("laser_on_duration", "1.0"),
            ("recording_duration", "5.0"),
            ("post_well_delay", "0.5"),
        ]):
            label = QLabel(f"{name.replace('_', ' ').title()} (s):")
            params_layout.addWidget(label, i + 2, 0)
            line_edit = QLineEdit(default_val)
            params_layout.addWidget(line_edit, i + 2, 1)
            self.param_inputs[name] = line_edit

        # Experiment Name
        params_layout.addWidget(QLabel("Experiment Name:"), 6, 0)
        self.exp_name_input = QLineEdit("my_experiment")
        params_layout.addWidget(self.exp_name_input, 6, 1)

        # Controls
        control_layout = QHBoxLayout()
        self.start_btn = QPushButton("Start Experiment")
        self.stop_btn = QPushButton("Stop Experiment")
        self.stop_btn.setEnabled(False)
        control_layout.addWidget(self.start_btn)
        control_layout.addWidget(self.stop_btn)
        self.layout.addLayout(control_layout)

        # Status
        self.status_label = QLabel("Status: Idle")
        self.layout.addWidget(self.status_label)

        self.layout.addStretch()

        # Connect signals
        self.start_btn.clicked.connect(self.start_experiment)
        self.stop_btn.clicked.connect(self.stop_experiment)

    def start_experiment(self):
        if self.calibration_panel is None:
            self.status_label.setText("Status: Error - Calibration panel not found.")
            return

        # Get corners from calibration panel
        corners = []
        corner_names = ["Upper-Left", "Lower-Left", "Upper-Right", "Lower-Right"]
        for name in corner_names:
            corner_data = self.calibration_panel.corners.get(name)
            if corner_data is None or corner_data.get("position") is None:
                self.status_label.setText(f"Status: Error - Corner '{name}' not set.")
                return
            corners.append(corner_data["position"])

        # Get parameters
        params = {name: float(widget.text()) for name, widget in self.param_inputs.items()}
        params["name"] = self.exp_name_input.text()

        # Create WellPlate and Experiment objects
        try:
            well_plate = WellPlate(
                width=self.width_spinbox.value(),
                depth=self.depth_spinbox.value(),
                corners=corners
            )
            experiment = Experiment(hw_manager, well_plate, params)
        except Exception as e:
            self.status_label.setText(f"Status: Error - {e}")
            return

        # Run experiment in a separate thread
        self.experiment_runner = ExperimentRunner(experiment)
        self.experiment_runner.finished.connect(self.on_experiment_finished)
        self.experiment_runner.start()

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.status_label.setText("Status: Running...")

    def stop_experiment(self):
        if self.experiment_runner and self.experiment_runner.isRunning():
            self.experiment_runner.stop()
            self.status_label.setText("Status: Stopping...")

    def on_experiment_finished(self):
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_label.setText("Status: Finished.")
        self.experiment_runner = None
