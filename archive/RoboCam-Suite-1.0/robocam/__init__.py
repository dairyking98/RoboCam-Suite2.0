"""
RoboCam Package - Robotic Camera Control for Well-Plate Experiments

This package provides modules for controlling a 3D printer as a positioning stage,
Raspberry Pi camera for imaging, and GPIO laser for experiment stimulation.

Main Components:
    - RoboCam: 3D printer control via G-code (robocam_ccc.py is preferred)
    - Laser: GPIO-controlled laser module
    - PiHQCamera: Raspberry Pi camera wrapper
    - StentorCam: Extended RoboCam with movement limits and well plate support
    - WellPlatePathGenerator: Generate well positions from corner coordinates

Author: RoboCam-Suite
"""

# Export preferred RoboCam implementation
from .robocam_ccc import RoboCam
from .laser import Laser
from .pihqcamera import PiHQCamera
from .stentorcam import StentorCam, WellPlatePathGenerator
from .camera_preview import start_best_preview, FPSTracker, has_desktop_session
from .config import Config, get_config, reset_config
from .logging_config import setup_logging, get_logger

__all__ = [
    'RoboCam',
    'Laser',
    'PiHQCamera',
    'StentorCam',
    'WellPlatePathGenerator',
    'start_best_preview',
    'FPSTracker',
    'has_desktop_session',
    'Config',
    'get_config',
    'reset_config',
    'setup_logging',
    'get_logger',
]

