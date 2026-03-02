import sys
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QTabWidget
from PySide6.QtCore import QTimer

from robocam_suite.ui.camera_widget import CameraWidget
from robocam_suite.hw_manager import hw_manager
from robocam_suite.session_manager import session_manager


class MainWindow(QMainWindow):
    """The main application window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("RoboCam-Suite 2.0")
        self.setGeometry(100, 100, 1280, 900)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # Camera preview (top, larger)
        self.camera_widget = CameraWidget()
        root.addWidget(self.camera_widget, stretch=3)

        # Control tabs (bottom)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs, stretch=2)

        # --- Tab order: Setup first so hardware is configured before use ---
        from robocam_suite.ui.setup_panel import SetupPanel
        self.setup_panel = SetupPanel()
        self.tabs.addTab(self.setup_panel, "Setup")

        from robocam_suite.ui.calibration_panel import CalibrationPanel
        self.calibration_panel = CalibrationPanel()
        self.tabs.addTab(self.calibration_panel, "Calibration")

        from robocam_suite.ui.experiment_panel import ExperimentPanel
        self.experiment_panel = ExperimentPanel(calibration_panel=self.calibration_panel)
        self.tabs.addTab(self.experiment_panel, "Experiment")

        from robocam_suite.ui.manual_control_panel import ManualControlPanel
        self.manual_control_panel = ManualControlPanel()
        self.tabs.addTab(self.manual_control_panel, "Manual Control")

        # Camera feed timer (~30 FPS)
        self.camera_timer = QTimer(self)
        self.camera_timer.timeout.connect(self._update_camera_feed)
        self.camera_timer.start(33)

        # Attempt initial hardware connection (non-fatal)
        try:
            hw_manager.connect_all()
        except Exception as e:
            print(f"[MainWindow] Hardware connect on startup: {e}")

    def _update_camera_feed(self):
        try:
            camera = hw_manager.get_camera()
            if camera.is_connected:
                frame = camera.read_frame()
                self.camera_widget.set_frame(frame)
        except Exception:
            pass

    def closeEvent(self, event):
        """Save session and disconnect hardware on close."""
        session_manager.save_session()
        hw_manager.disconnect_all()
        event.accept()
