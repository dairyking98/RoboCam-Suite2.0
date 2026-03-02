"""
StentorCam Module - Extended RoboCam with Well Plate Support

Specialized RoboCam implementation with movement limits and well plate path generation.
Designed for Monoprice printer with specific coordinate limits.

Author: RoboCam-Suite
"""

from .robocam_ccc import RoboCam
import time
import RPi.GPIO as GPIO
from typing import Optional, List, Tuple
ON = GPIO.HIGH
OFF = GPIO.LOW


class StentorCam(RoboCam):
    """
    Extended RoboCam with movement limits and well plate support.
    
    Inherits from RoboCam and adds:
    - Movement limit checking (prevents out-of-bounds moves)
    - Well plate path generation support
    - Laser control integration
    
    Attributes:
        X_LOWER_LIMIT, X_UPPER_LIMIT (float): X-axis movement limits (mm)
        Y_LOWER_LIMIT, Y_UPPER_LIMIT (float): Y-axis movement limits (mm)
        Z_LOWER_LIMIT, Z_UPPER_LIMIT (float): Z-axis movement limits (mm)
        wells (Optional[List]): Well plate path data
    """
    
    def __init__(self, baudrate: int, laser_pin: int) -> None:
        """
        Initialize StentorCam with movement limits.
        
        Args:
            baudrate: Serial communication baud rate (typically 115200)
            laser_pin: GPIO pin number for laser control
            
        Note:
            These limits are specific to the Monoprice printer setup.
            Adjust limits based on your hardware configuration.
        """
        # Printer startup and settings
        super().__init__(baudrate)
        
        # These settings are specific to the monoprice printer
        self.X_LOWER_LIMIT: float = 0
        self.X_UPPER_LIMIT: float = 200
        self.Y_LOWER_LIMIT: float = 80
        self.Y_UPPER_LIMIT: float = 150
        self.Z_LOWER_LIMIT: float = 95
        self.Z_UPPER_LIMIT: float = 170
        
        # Laser settings
        self.laser_pin: int = laser_pin
        # GPIO.setmode(GPIO.BCM)  # Already set in Laser class if used
        # GPIO.setup(self.laser_pin, GPIO.OUT)
        
        # Path settings
        self.wells: Optional[List] = None
        
        # Camera startup and settings

    def laser_control(self, state: Optional[int] = None) -> None:
        """
        Control laser ON/OFF state.
        
        Args:
            state: Laser.ON or Laser.OFF, or GPIO.HIGH/GPIO.LOW
            
        Note:
            Blue wire is ground, green wire is live.
            Purple wire is ground, orange wire is live (alternative wiring).
        """
        GPIO.output(self.laser_pin, state)
        print(f'[log] laser is {state}')
        
    def move_relative(self, X: Optional[float] = None, Y: Optional[float] = None,
                     Z: Optional[float] = None, speed: Optional[float] = None) -> None:
        """
        Move relative with limit checking.
        
        Args:
            X: Relative movement in X direction (mm). None to skip.
            Y: Relative movement in Y direction (mm). None to skip.
            Z: Relative movement in Z direction (mm). None to skip.
            speed: Movement speed in mm/min. None to use default.
            
        Note:
            Checks that resulting position is within limits before moving.
            Prints error message if limits would be exceeded (should raise exception).
        """
        if (X is None or self.X_LOWER_LIMIT <= self.X + X <= self.X_UPPER_LIMIT) and \
           (Y is None or self.Y_LOWER_LIMIT <= self.Y + Y <= self.Y_UPPER_LIMIT) and \
           (Z is None or self.Z_LOWER_LIMIT <= self.Z + Z <= self.Z_UPPER_LIMIT):
            super().move_relative(X, Y, Z, speed)
        else:
            print(f"[error] {self.X, self.Y, self.Z} + {X, Y, Z} is outside of limits, check LOWER_LIMIT and UPPER_LIMIT variables (needs to be thrown as an exception)")
            
    def move_absolute(self, X: Optional[float] = None, Y: Optional[float] = None,
                      Z: Optional[float] = None, speed: Optional[float] = None) -> None:
        """
        Move absolute with limit checking.
        
        Args:
            X: Absolute X position (mm). None to skip.
            Y: Absolute Y position (mm). None to skip.
            Z: Absolute Z position (mm). None to skip.
            speed: Movement speed in mm/min. None to use default.
            
        Note:
            Checks that target position is within limits before moving.
            Prints error message if limits would be exceeded (should raise exception).
        """
        if (X is None or self.X_LOWER_LIMIT <= X <= self.X_UPPER_LIMIT) and \
           (Y is None or self.Y_LOWER_LIMIT <= Y <= self.Y_UPPER_LIMIT) and \
           (Z is None or self.Z_LOWER_LIMIT <= Z <= self.Z_UPPER_LIMIT):
            super().move_absolute(X, Y, Z, speed)
        else:
            print(f"[error] {X, Y, Z} is outside of limits X: {self.X_LOWER_LIMIT <= X <= self.X_UPPER_LIMIT}, Y: {self.Y_LOWER_LIMIT <= Y <= self.Y_UPPER_LIMIT}, Z: {self.Z_LOWER_LIMIT <= Z <= self.Z_UPPER_LIMIT}, check LOWER_LIMIT and UPPER_LIMIT variables (needs to be thrown as an exception)")
        
    def move_across_path(self, path: List[Tuple[float, float, float]]) -> None:
        """
        Move across a path of well locations with laser control.
        
        Args:
            path: List of (X, Y, Z) tuples representing well positions
            
        Note:
            For each position in path:
            - Moves to position
            - Turns laser ON for 3 seconds
            - Turns laser OFF
        """
        for loc in path:
            X, Y, Z = loc
            self.move_absolute(X=X, Y=Y, Z=Z)
            self.laser_control(ON)
            time.sleep(3)
            self.laser_control(OFF)
    
class WellPlatePathGenerator:
    """
    Generate well plate paths from corner positions using bilinear interpolation.
    
    Creates a grid of well positions from four corner coordinates, accounting for
    slight angles and misalignment in well plate positioning.
    """
    
    @staticmethod
    def generate_path(width: int, depth: int, 
                     upper_left_loc: Tuple[float, float, float],
                     lower_left_loc: Tuple[float, float, float],
                     upper_right_loc: Tuple[float, float, float],
                     lower_right_loc: Tuple[float, float, float]) -> List[Tuple[float, float, float]]:
        """
        Generate a path of well positions from four corner coordinates.
        
        Args:
            width: Number of wells horizontally (long side in landscape mode)
            depth: Number of wells vertically (short side in landscape mode)
            upper_left_loc: (X, Y, Z) location of upper-left corner well
            lower_left_loc: (X, Y, Z) location of lower-left corner well
            upper_right_loc: (X, Y, Z) location of upper-right corner well
            lower_right_loc: (X, Y, Z) location of lower-right corner well
            
        Returns:
            List of (X, Y, Z) tuples representing all well positions in the grid.
            Wells are ordered left-to-right, top-to-bottom.
            
        Note:
            Uses bilinear interpolation to calculate positions, accounting for:
            - Linear spacing between wells
            - Slight rotation of well plate
            - Non-perpendicular alignment
            - Z-axis variations across the plate
            
            If well plate is in landscape mode:
            - width = number of wells on the long side
            - depth = number of wells on the short side
            - upper_left_loc = location of left-hand-side farthest from you well
        """
        path: List[Tuple[float, float, float]] = []
        
        # Extract coordinates
        x1, y1, z1 = upper_left_loc
        x2, y2, z2 = lower_left_loc
        x3, y3, z3 = upper_right_loc
        x4, y4, z4 = lower_right_loc
        
        # Generate grid of XYZ locations using bilinear interpolation
        # This properly accounts for rotation and skew by interpolating along both axes together
        for i in range(depth):
            for j in range(width):
                # Calculate normalized coordinates [0, 1]
                u = j / (width - 1) if width > 1 else 0.0  # Horizontal position (0 = left, 1 = right)
                v = i / (depth - 1) if depth > 1 else 0.0  # Vertical position (0 = top, 1 = bottom)
                
                # Bilinear interpolation:
                # 1. Interpolate along top edge (UL to UR) at horizontal position u
                top_x = x1 + u * (x3 - x1)
                top_y = y1 + u * (y3 - y1)
                top_z = z1 + u * (z3 - z1)
                
                # 2. Interpolate along bottom edge (LL to LR) at horizontal position u
                bottom_x = x2 + u * (x4 - x2)
                bottom_y = y2 + u * (y4 - y2)
                bottom_z = z2 + u * (z4 - z2)
                
                # 3. Interpolate between top and bottom at vertical position v
                x = top_x + v * (bottom_x - top_x)
                y = top_y + v * (bottom_y - top_y)
                z = top_z + v * (bottom_z - top_z)
                
                # Append the location as a tuple
                path.append((x, y, z))
        
        return path
