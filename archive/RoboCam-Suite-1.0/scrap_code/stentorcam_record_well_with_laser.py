from robocam.stentorcam import StentorCam, WellPlatePathGenerator
from robocam.pihqcamera import PiHQCamera
from robocam.robocam import RoboCam
from robocam.laser import Laser
import time

from picamera2 import Picamera2
from picamera2.encoders import JpegEncoder

size = (640, 512)
picam2 = Picamera2()
video_config = picam2.create_video_configuration(main={'size': size})
picam2.configure(video_config)

robocam = RoboCam(baudrate=115200)
laser = Laser(21)

picam2.start_preview()
encoder = JpegEncoder(q=100)

recording_time = 30

video_path = f"videos/loc-none_timestamp-{time.strftime('%Y%m%d_%H%M%S')}.mjpeg"
picam2.start_recording(encoder, video_path)

print("RECORDING BEGAN")

time.sleep(recording_time)

laser.switch(1)

time.sleep(recording_time)

laser.switch(0)

picam2.stop_recording()
print("RECORDING ENDED")
