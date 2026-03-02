import sys
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QPushButton, QTabWidget
from PySide6.QtCore import QTimer

from robocam_suite.ui.camera_widget import CameraWidget
from robocam_suite.hw_manager import hw_manager

class MainWindow(QMainWindow):
    """The main application window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("RoboCam-Suite 2.0")
        self.setGeometry(100, 100, 1200, 800)

        # Create main layout
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)

        # Create camera widget
        self.camera_widget = CameraWidget()
        self.layout.addWidget(self.camera_widget, stretch=3) # Give more space to camera

        # Create tab widget for controls
        self.tabs = QTabWidget()
        self.layout.addWidget(self.tabs, stretch=1)

        # Add placeholder tabs
        from robocam_suite.ui.calibration_panel import CalibrationPanel
        self.calibration_panel = CalibrationPanel()
        self.tabs.addTab(self.calibration_panel, "Calibration")
        self.tabs.addTab(QWidget(), "Experiment")
        self.tabs.addTab(QWidget(), "Manual Control")

        # Set up camera update timer
        self.camera_timer = QTimer(self)
        self.camera_timer.timeout.connect(self.update_camera_feed)
        self.camera_timer.start(33) # Aim for ~30 FPS

        # Connect to hardware
        try:
            hw_manager.connect_all()
        except Exception as e:
            print(f"Could not connect to hardware: {e}")

    def update_camera_feed(self):
        """Fetches a frame from the camera and displays it."""
        camera = hw_manager.get_camera()
        if camera.is_connected:
            frame = camera.read_frame()
            self.camera_widget.set_frame(frame)

    def closeEvent(self, event):
        """Handles the window closing event."""
        hw_manager.disconnect_all()
        event.accept()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
