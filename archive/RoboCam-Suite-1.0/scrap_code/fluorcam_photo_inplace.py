from robocam.stentorcam import StentorCam, WellPlatePathGenerator
from robocam.pihqcamera import PiHQCamera
from robocam.robocam import RoboCam
from robocam.laser import Laser

import time

from picamera2 import Picamera2
from picamera2.encoders import JpegEncoder

resolution = (1280, 1024)
picam2 = Picamera2()
cam_config = picam2.create_still_configuration(main={"size": resolution})

picam2.configure(cam_config)

robocam = RoboCam(baudrate=115200)

photo_path = f"stills/still_timestamp-{time.strftime('%Y%m%d_%H%M%S')}.png"

excitation_light = Laser(21)
excitation_light.switch(1)

picam2.start()
picam2.capture_file(photo_path)
picam2.stop()

excitation_light.switch(0)
