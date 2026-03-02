import logging
import sys

def setup_logger(level=logging.INFO):
    """Sets up the root logger for the application."""
    logger = logging.getLogger("robocam_suite")
    logger.setLevel(level)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger
