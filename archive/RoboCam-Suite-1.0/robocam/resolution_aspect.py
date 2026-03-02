"""
Resolution Aspect Ratio Validation - Camera-Specific Correct Resolution

Ensures resolution maintains the correct aspect ratio per camera sensor to avoid
libcamera cropping (Pi HQ) or incorrect scaling (USB/Mars 662M).

Camera aspect ratios:
- Raspberry Pi HQ (IMX477): 4:3 (4056×3040)
- Mars 662M (IMX662): ~16:9 (1936×1100)

When a user specifies a resolution with the wrong aspect ratio (e.g. 1920×1080
on Pi HQ), the resolution is corrected to the nearest valid size and a
notification can be shown.

Author: RoboCam-Suite
"""

from typing import Tuple

from robocam.logging_config import get_logger

logger = get_logger(__name__)

# Pi HQ Camera (IMX477): 4:3 native
PI_HQ_ASPECT_RATIO: Tuple[int, int] = (4, 3)
PI_HQ_MAX_RESOLUTION: Tuple[int, int] = (4056, 3040)

# Mars 662M (IMX662): ~16:9
USB_MARS_ASPECT_RATIO: Tuple[int, int] = (16, 9)
USB_MARS_MAX_RESOLUTION: Tuple[int, int] = (1936, 1100)


def _clamp_to_max(
    width: int, height: int, max_w: int, max_h: int
) -> Tuple[int, int]:
    """Clamp resolution to maximum while preserving aspect ratio."""
    if width <= max_w and height <= max_h:
        return (width, height)
    scale = min(max_w / width, max_h / height)
    w = int(round(width * scale))
    h = int(round(height * scale))
    return (max(1, w), max(1, h))


def correct_resolution_for_camera(
    width: int, height: int, is_pihq: bool
) -> Tuple[int, int, bool]:
    """
    Correct resolution to match camera's native aspect ratio.

    Args:
        width: Requested width in pixels
        height: Requested height in pixels
        is_pihq: True if Raspberry Pi HQ (4:3), False if USB/Mars 662M (16:9)

    Returns:
        Tuple of (corrected_width, corrected_height, was_corrected)
    """
    if width < 1 or height < 1:
        return (max(1, width), max(1, height), False)

    if is_pihq:
        target_ratio = PI_HQ_ASPECT_RATIO[0] / PI_HQ_ASPECT_RATIO[1]
        max_w, max_h = PI_HQ_MAX_RESOLUTION
    else:
        target_ratio = USB_MARS_ASPECT_RATIO[0] / USB_MARS_ASPECT_RATIO[1]
        max_w, max_h = USB_MARS_MAX_RESOLUTION

    current_ratio = width / height

    # Check if already correct within small tolerance (0.5% to allow rounding)
    if abs(current_ratio - target_ratio) / target_ratio < 0.005:
        return (width, height, False)

    if current_ratio > target_ratio:
        # Too wide: keep width, adjust height
        new_height = int(round(width / target_ratio))
        new_width = width
    else:
        # Too tall: keep height, adjust width
        new_width = int(round(height * target_ratio))
        new_height = height

    new_width = max(1, new_width)
    new_height = max(1, new_height)

    # Clamp to sensor maximum
    new_width, new_height = _clamp_to_max(new_width, new_height, max_w, max_h)

    return (new_width, new_height, True)


def get_default_resolution_for_camera(is_pihq: bool) -> Tuple[int, int]:
    """
    Get a sensible default resolution for the camera that matches its aspect ratio.

    Args:
        is_pihq: True for Pi HQ (4:3), False for USB/Mars 662M (16:9)

    Returns:
        (width, height) tuple
    """
    if is_pihq:
        # 4:3 - 1920×1440 is a common high-res choice
        return (1920, 1440)
    else:
        # 16:9 - 1920×1080
        return (1920, 1080)
