import time
from robocam.laser import Laser

# Program to test functionality of laser controls on Raspberry Pi 4 Model B
# Laser needs to be connected to one GPIO pin and GND
# Last edited by: Addy Brien, 02-11-2025

#Change value to GPIO pin you are using
l = Laser(laser_pin=16)

for _ in range(3):
    l.switch(Laser.ON)
    time.sleep(3)
    l.switch(Laser.OFF)
    time.sleep(1)
