from robocam.stentorcam import StentorCam, WellPlatePathGenerator
from robocam.pihqcamera import PiHQCamera
from robocam.robocam import RoboCam
import time

robocam = RoboCam(baudrate=115200)

robocam.home()

path = WellPlatePathGenerator.generate_path(width=8, depth=6, upper_left_loc=(8, 150, 157), lower_left_loc=(6.1, 77.7, 157), upper_right_loc=(98.1, 143.4, 157), lower_right_loc=(97.1, 78.7, 157))

for index, loc in enumerate(path):
	X, Y, Z = loc
	robocam.move_absolute(X=X, Y=Y, Z=Z)
	time.sleep(1) # to compensate for shakes
    
	time.sleep(2)
    
