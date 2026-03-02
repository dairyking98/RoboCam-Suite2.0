from robocam.stentorcam import StentorCam, WellPlatePathGenerator
# from robocam.pihqcamera import PiHQCamera
from picamera2 import Picamera2
from picamera2.encoders import JpegEncoder
from robocam.laser import Laser
import time

stentorcam = StentorCam(baudrate=115200, laser_pin=17)
# camera = PiHQCamera(resolution=(1280, 1024))

size = (1280, 1024)
picam2 = Picamera2()
video_config = picam2.create_video_configuration(main={'size': size})
picam2.configure(video_config)

laser = Laser(laser_pin=17)

stentorcam.home()

path = WellPlatePathGenerator.generate_path(width=8, depth=6, upper_left_loc=(72, 149.4, 153), lower_left_loc=(72, 92.5, 153), upper_right_loc=(150, 147.9, 153), lower_right_loc=(150, 90.9, 153))

for index, loc in enumerate(path):
    if index != 0:
        continue
    X, Y, Z = loc
    stentorcam.move_absolute(X=X, Y=Y, Z=Z)
    time.sleep(5) # to compensate for shakes
    
    video_path = f"loc-{loc}_timestamp-{time.strftime('%Y%m%d_%H%M%S')}.mjpeg"

    picam2.start_preview()
    encoder = JpegEncoder(q=100)
    
    picam2.start_recording(encoder, video_path)
    
    time.sleep(45)
    laser.switch(Laser.ON)
    time.sleep(45)
    laser.switch(Laser.OFF)
    time.sleep(45)
    
    #camera.stop_recording_video()
    picam2.stop_recording()
