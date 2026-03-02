from robocam.stentorcam import StentorCam, WellPlatePathGenerator
from robocam.pihqcamera import PiHQCamera
from robocam.robocam import RoboCam
import time

from picamera2 import Picamera2
from picamera2.encoders import JpegEncoder

size = (1280, 1024)
picam2 = Picamera2()
video_config = picam2.create_video_configuration(main={'size': size})
picam2.configure(video_config)

robocam = RoboCam(baudrate=115200)

recording_time = 45*3

robocam.home()

X, Y, Z = 98, 138, 169.5
loc = (X, Y, Z)
robocam.move_absolute(X=X, Y=Y, Z=Z)
# reduce shaking
time.sleep(5)

video_path = f"loc-{loc}_timestamp-{time.strftime('%Y%m%d_%H%M%S')}.mjpeg"

picam2.start_preview()
encoder = JpegEncoder(q=100)

picam2.start_recording(encoder, video_path)

print("RECORDING BEGAN")

time.sleep(recording_time)

picam2.stop_recording()
print("RECORDING ENDED")
