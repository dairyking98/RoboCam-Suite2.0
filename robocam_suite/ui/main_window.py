"""
Main application window.

The window is a full-screen QTabWidget — no shared camera preview at the
top. Each tab that needs a live feed (Calibration, Experiment, Manual
Control) manages its own camera thread internally.

Tab order
---------
Setup → Calibration → Experiment → Manual Control
"""
from PySide6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QTabWidget
from PySide6.QtCore import QTimer

from robocam_suite.hw_manager import hw_manager
from robocam_suite.session_manager import session_manager


class MainWindow(QMainWindow):
    """The main application window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("RoboCam-Suite 2.0")
        self.setGeometry(100, 100, 1440, 900)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Full-window tab widget — tabs at the top
        self.tabs = QTabWidget()
        self.tabs.setTabPosition(QTabWidget.TabPosition.North)
        self.tabs.setDocumentMode(True)   # cleaner look on all platforms
        root.addWidget(self.tabs)

        # --- Tabs (Setup first so hardware is configured before use) ---
        from robocam_suite.ui.setup_panel import SetupPanel
        self.setup_panel = SetupPanel()
        self.tabs.addTab(self.setup_panel, "Setup")

        from robocam_suite.ui.calibration_panel import CalibrationPanel
        self.calibration_panel = CalibrationPanel()
        self.tabs.addTab(self.calibration_panel, "Calibration")

        from robocam_suite.ui.experiment_panel import ExperimentPanel
        self.experiment_panel = ExperimentPanel(
            calibration_panel=self.calibration_panel
        )
        self.tabs.addTab(self.experiment_panel, "Experiment")

        from robocam_suite.ui.manual_control_panel import ManualControlPanel
        self.manual_control_panel = ManualControlPanel()
        self.tabs.addTab(self.manual_control_panel, "Manual Control")

        # Wire calibration → experiment auto-sync
        # Re-sync whenever the user changes rows, columns, or corner positions
        self.calibration_panel.cols_spin.valueChanged.connect(
            lambda _: self.experiment_panel.sync_from_calibration()
        )
        self.calibration_panel.rows_spin.valueChanged.connect(
            lambda _: self.experiment_panel.sync_from_calibration()
        )
        self.calibration_panel.corners_changed.connect(
            self.experiment_panel.sync_from_calibration
        )
        
        # Initial sync check in case calibration was auto-loaded during CalibrationPanel.__init__
        QTimer.singleShot(500, self.experiment_panel.sync_from_calibration)
        
        # Wire camera connection → calibration control refresh
        self.setup_panel.camera_connected.connect(
            self.calibration_panel._refresh_camera_controls
        )
        self.setup_panel.camera_connected.connect(
            self.experiment_panel._update_resolution_label
        )
        # Update QuickCapture resolution label
        self.setup_panel.camera_connected.connect(
            self.calibration_panel.quick_capture._update_resolution_label
        )

        # Attempt initial hardware connection (non-fatal)
        try:
            hw_manager.connect_all()
        except Exception as e:
            print(f"[MainWindow] Hardware connect on startup: {e}")

    def closeEvent(self, event):
        """Gracefully stop all background threads, save session, then quit."""
        # Stop experiment runner if running
        exp = self.experiment_panel
        if hasattr(exp, 'experiment_runner') and exp.experiment_runner and exp.experiment_runner.isRunning():
            exp.experiment_runner.stop()
            exp.experiment_runner.wait(5000)

        # Stop frame grabbers
        for panel in (self.calibration_panel, self.experiment_panel):
            grabber = getattr(panel, '_grabber', None)
            if grabber and grabber.isRunning():
                grabber.stop()
                grabber.wait(2000)

        session_manager.save_session()
        hw_manager.disconnect_all()
        event.accept()
