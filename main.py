"""
RoboCam-Suite 2.0 — main entry point.

Usage
-----
Normal mode (requires hardware):
    python main.py

Simulation mode (no hardware needed — all devices are emulated):
    python main.py --simulate

Debug mode (verbose G-code and driver logging to console):
    python main.py --debug

Both flags can be combined:
    python main.py --simulate --debug

Simulation mode enables individual device simulation flags in the
config at runtime without modifying the config file on disk.
"""
import sys
import argparse
import logging

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
    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help=(
            "Enable DEBUG-level logging. Prints every G-code command sent to the "
            "printer and every response received, plus verbose SDK and driver output. "
            "Useful for diagnosing motion, serial, and camera issues."
        ),
    )
    return parser.parse_args()


def main():
    args = parse_args()
    log_level = logging.DEBUG if args.debug else logging.INFO
    logger = setup_logger(level=log_level)

    if args.debug:
        logger.debug(
            "=== DEBUG MODE ENABLED ===  "
            "All G-code TX/RX, SDK calls, and driver events will be logged."
        )

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

    title_parts = ["RoboCam-Suite 2.0"]
    if args.simulate:
        title_parts.append("[SIMULATION MODE]")
    if args.debug:
        title_parts.append("[DEBUG]")
    if len(title_parts) > 1:
        window.setWindowTitle("  ".join(title_parts))

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
