import sys
from PySide6.QtWidgets import QApplication
from robocam_suite.ui.main_window import MainWindow
from robocam_suite.logger import setup_logger

def main():
    """Main entry point for the application."""
    setup_logger()
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
