from robocam.stentorcam import StentorCam, WellPlatePathGenerator
from robocam.pihqcamera import PiHQCamera
from robocam.robocam_ccc import RoboCam
from robocam.laser import Laser
import time

from picamera2 import Picamera2
from picamera2.encoders import JpegEncoder

wells = [
    (70.5, 98.5, 111.4),
    (70.5, 80.5, 111.4),
    (70.5, 62.5, 111.4),
    (97.5, 98.5, 111.4),
    (97.5, 80.5, 111.4),
    (97.5, 62.5, 111.4),
    (124.5, 98.5, 111.4),
    (124.5, 80.5, 111.4),
    (124.5, 62.5, 111.4),
    (151.5, 98.5, 111.4),
    (151.5, 80.5, 111.4),
    (151.5, 62.5, 111.4),
]

size = (640, 512)
picam2 = Picamera2()
video_config = picam2.create_video_configuration(main={'size': size})
picam2.configure(video_config)

robocam = RoboCam(baudrate=115200)
laser = Laser(21)

picam2.start_preview()
encoder = JpegEncoder(q=100)

recording_time = 30

robocam.home()

for x,y,z in wells:
    robocam.move_absolute(x,y,z)

    video_path = f"videos/GREEN_LSR-CONTROL-x{x}_y{y}_z{z}_timestamp-{time.strftime('%Y%m%d_%H%M%S')}.mjpeg"
    picam2.start_recording(encoder, video_path)

    print("RECORDING BEGAN")

    time.sleep(recording_time)

    laser.switch(1)

    time.sleep(recording_time)

    laser.switch(0)
    
    time.sleep(recording_time)

    picam2.stop_recording()
    print("RECORDING ENDED")
