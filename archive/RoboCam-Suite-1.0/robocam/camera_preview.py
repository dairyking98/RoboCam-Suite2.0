"""
Camera Preview Utilities - Native Picamera2 Preview with FPS Tracking

Utilities for starting native Picamera2 preview with automatic backend selection
and FPS tracking. Based on raspi_preview.py optimization techniques.

Author: RoboCam-Suite
"""

import os
import time
from collections import deque
from typing import Optional
from picamera2 import Picamera2, Preview


def has_desktop_session() -> bool:
    """
    Return True if running under X11/Wayland (likely desktop session).
    
    Returns:
        True if DISPLAY or WAYLAND_DISPLAY environment variable is set
    """
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def start_best_preview(picam2: Picamera2, backend: str = "auto") -> str:
    """
    Start a preview using the requested backend, or pick a sensible default.
    
    - DRM works well on the console (no X/Wayland).
    - QTGL works under a desktop session with OpenGL.
    - NULL runs headless (no visible preview), useful for diagnostics.
    
    Args:
        picam2: Picamera2 instance
        backend: Backend to use ("auto", "drm", "qtgl", "null")
        
    Returns:
        Name of the backend that was successfully started
        
    Raises:
        ValueError: If backend name is invalid
        RuntimeError: If all backends fail to start
    """
    backends = {
        "drm": Preview.DRM,
        "qtgl": Preview.QTGL,
        "null": Preview.NULL,
    }
    
    if backend not in ("auto", *backends.keys()):
        raise ValueError(f"Unknown backend '{backend}'. Valid: auto, drm, qtgl, null")
    
    order: list[str]
    if backend == "auto":
        # Prefer QTGL when a desktop session exists, else DRM on console.
        order = ["qtgl", "drm"] if has_desktop_session() else ["drm", "qtgl"]
    else:
        order = [backend]
    
    last_exc: Optional[Exception] = None
    for name in order:
        try:
            picam2.start_preview(backends[name])
            return name
        except Exception as exc:
            last_exc = exc
    
    raise RuntimeError(f"Failed to start preview using {order}: {last_exc}")


class FPSTracker:
    """
    Track FPS by monitoring frame timestamps.
    
    Uses a sliding window of frame timestamps to calculate average FPS.
    
    Attributes:
        timestamps (deque): Queue of frame timestamps
        window_size (int): Maximum number of timestamps to keep
    """
    
    def __init__(self, window_size: int = 30) -> None:
        """
        Initialize FPS tracker.
        
        Args:
            window_size: Number of recent frames to use for FPS calculation
        """
        self.timestamps: deque[float] = deque(maxlen=window_size)
        self.window_size: int = window_size
    
    def update(self) -> None:
        """Record a new frame timestamp."""
        self.timestamps.append(time.time())
    
    def get_fps(self) -> float:
        """
        Calculate FPS based on recent frame timestamps.
        
        Returns:
            Average FPS over the window, or 0.0 if insufficient data
        """
        if len(self.timestamps) < 2:
            return 0.0
        time_span = self.timestamps[-1] - self.timestamps[0]
        if time_span <= 0:
            return 0.0
        return (len(self.timestamps) - 1) / time_span
    
    def reset(self) -> None:
        """Clear all timestamps."""
        self.timestamps.clear()

