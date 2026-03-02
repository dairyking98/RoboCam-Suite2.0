"""
RoboCam-Suite 2.0 — main entry point.

Usage
-----
Normal mode (requires hardware):
    python main.py

Simulation mode (no hardware needed — all devices are emulated):
    python main.py --simulate

Simulation mode enables individual device simulation flags in the
config at runtime without modifying the config file on disk.
"""
import sys
import argparse

from PySide6.QtWidgets import QApplication
from robocam_suite.logger import setup_logger


def parse_args():
    parser = argparse.ArgumentParser(
        prog="robocam",
        description="RoboCam-Suite 2.0 — robotic camera control suite.",
    )
    parser.add_argument(
        "--simulate",
        action="store_true",
        default=False,
        help=(
            "Run in simulation mode. All hardware (motion controller, camera, GPIO) "
            "is emulated in software. No physical devices are required. "
            "Useful for development and testing on a computer without peripherals."
        ),
    )
    return parser.parse_args()


def main():
    args = parse_args()
    logger = setup_logger()

    if args.simulate:
        logger.info(
            "=== SIMULATION MODE ENABLED ===  "
            "All hardware is emulated. No physical devices are required."
        )
        # Patch the in-memory config BEFORE any driver is instantiated.
        # This does NOT write to default_config.json on disk.
        from robocam_suite.config.config_manager import config_manager
        config_manager._config["simulation"] = {
            "motion_controller": True,
            "camera": True,
            "gpio_controller": True,
        }
        # Force GPIO enabled so the simulate branch runs instead of NullGPIO
        config_manager._config.setdefault("gpio_controller", {})["enabled"] = True

    app = QApplication(sys.argv)
    app.setApplicationName("RoboCam-Suite")
    app.setApplicationVersion("2.0.0")

    # Import MainWindow AFTER config patches so drivers pick up simulate flags
    from robocam_suite.ui.main_window import MainWindow
    window = MainWindow()

    if args.simulate:
        window.setWindowTitle("RoboCam-Suite 2.0  [SIMULATION MODE]")

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
