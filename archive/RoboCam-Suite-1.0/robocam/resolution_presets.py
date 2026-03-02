"""
Native capture resolution presets per camera backend.
Used by preview and experiment so users pick only supported resolutions (no custom).
"""

from typing import List, Optional, Tuple

from robocam.playerone_camera import PLAYERONE_SUPPORTED_RESOLUTIONS

# Pi HQ (IMX477) 4:3 native resolutions
PI_HQ_RESOLUTION_PRESETS: List[Tuple[int, int]] = [
    (4056, 3040),
    (2028, 1520),
    (1920, 1440),
    (1332, 990),
    (640, 480),
]


def get_capture_resolution_presets(
    is_pihq: bool,
    is_playerone: bool = False,
) -> List[Tuple[int, int]]:
    """
    Return list of (width, height) presets for the current camera backend.
    Only these resolutions are shown in the dropdown (no custom).
    """
    if is_playerone:
        return list(PLAYERONE_SUPPORTED_RESOLUTIONS)
    if is_pihq:
        return list(PI_HQ_RESOLUTION_PRESETS)
    return list(PLAYERONE_SUPPORTED_RESOLUTIONS)


def format_resolution_option(width: int, height: int) -> str:
    """Display string for dropdown, e.g. '1920×1080'."""
    return f"{width}×{height}"


def parse_resolution_option(s: str) -> Optional[Tuple[int, int]]:
    """Parse 'W×H' or 'WxH' to (width, height), or None."""
    s = (s or "").strip()
    for sep in ("×", "x", "*"):
        if sep in s:
            parts = s.split(sep, 1)
            if len(parts) == 2:
                try:
                    w = int(parts[0].strip())
                    h = int(parts[1].strip())
                    if w > 0 and h > 0:
                        return (w, h)
                except ValueError:
                    pass
            return None
    return None


def resolution_to_preset_option(resolution: Tuple[int, int], presets: List[Tuple[int, int]]) -> str:
    """If resolution is in presets, return its option string; else return first preset."""
    w, h = resolution
    for pw, ph in presets:
        if (pw, ph) == (w, h):
            return format_resolution_option(pw, ph)
    if presets:
        return format_resolution_option(presets[0][0], presets[0][1])
    return format_resolution_option(1920, 1080)
