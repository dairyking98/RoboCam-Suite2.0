from robocam.stentorcam import StentorCam, WellPlatePathGenerator
from robocam.pihqcamera import PiHQCamera
from robocam.robocam import RoboCam
import time

from picamera2 import Picamera2
from picamera2.encoders import JpegEncoder

resolution = (1280, 1024)
picam2 = Picamera2()
cam_config = picam2.create_still_configuration(main={"size": resolution})

picam2.configure(cam_config)

robocam = RoboCam(baudrate=115200)

recording_time = 45*3

photo_path = f"still_timestamp-{time.strftime('%Y%m%d_%H%M%S')}.png"

picam2.start()
picam2.capture_file(photo_path)
picam2.stop()
