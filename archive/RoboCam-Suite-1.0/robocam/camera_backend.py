"""
Camera Backend Detection - Pi HQ vs Player One

Detects which camera is available: Raspberry Pi HQ (libcamera/Picamera2) or
Player One (e.g. Mars 662M via SDK). Uses the first one found: tries Pi HQ first, then Player One.

Author: RoboCam-Suite
"""

from typing import Optional, Literal, Tuple, Union
from robocam.logging_config import get_logger

logger = get_logger(__name__)

CameraBackend = Literal["pihq", "playerone"]

# Result: "pihq", ("playerone", index), or None
DetectResult = Union[
    Literal["pihq"],
    Tuple[Literal["playerone"], int],
    None,
]


def detect_camera() -> DetectResult:
    """
    Detect which camera is available. Tries Pi HQ first, then Player One (SDK).

    Returns:
        "pihq" if Raspberry Pi HQ camera is available,
        ("playerone", 0) if a Player One camera (e.g. Mars 662M) is available via SDK,
        None if no camera could be opened.
    """
    # Try Pi HQ (libcamera / Picamera2) first
    try:
        from picamera2 import Picamera2
        cam = Picamera2()
        config = cam.create_preview_configuration(main={"size": (640, 480)})
        cam.configure(config)
        cam.start()
        cam.stop()
        logger.info("Camera detected: Raspberry Pi HQ (Picamera2)")
        return "pihq"
    except Exception as e:
        logger.debug(f"Pi HQ camera not available: {e}")

    # Try Player One (Mars 662M etc.) via SDK
    try:
        from robocam.playerone_camera import get_playerone_camera_count
        count = get_playerone_camera_count()
        if count and count > 0:
            logger.info("Camera detected: Player One (SDK), count=%d", count)
            return ("playerone", 0)
    except Exception as e:
        logger.debug(f"Player One camera not available: {e}")

    logger.warning("No camera detected (neither Pi HQ nor Player One)")
    return None
