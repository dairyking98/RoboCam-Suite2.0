import logging
import sys

def setup_logger(level=logging.DEBUG):
    """Sets up the root logger for the application."""
    logger = logging.getLogger("robocam_suite")
    logger.setLevel(level)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        # Match 1.0 format: 15:42:55 - name - LEVEL - message
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s', datefmt='%H:%M:%S')
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger
