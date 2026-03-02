from robocam.stentorcam import StentorCam, WellPlatePathGenerator
from robocam.pihqcamera import PiHQCamera
from robocam.robocam import RoboCam
from robocam.laser import Laser
import time
# Author: Addy Brien
# Date Created: March 19, 2025
# Function: command line program to input the X,Y, Z coordinates of finite number of wells to image
# Intended Use: run from the command line
# $python scan_select_wells.py
# input how many wells to be photographed
# TODO input which wells are being photographed (A8, C2, etc.)
#
# Derived from: scan_all_wells.py

robocam = RoboCam(baudrate=115200)
# TODO: 115200 is the baudrate for monoprice printer, change this value if using alternative
camera = PiHQCamera(resolution=(1280, 1024))

l = Laser(laser_pin=21)

robocam.home() #G28

well_count = 1
well_count = int(input("Number of wells: "))

#print("Would you like to name the wells? [Y/N]")
#TODO: conditional statement that takes in Y/N value and
#TODO: branch for when user types 'Y', will >> input for loop length of well_count
#example use case: name is 'A8' for the well labeled as such OR name is something useful to user

print("Well Coordinates")
#create a list of tuples of size well_count where they are X,Y,Z in order
well_coordinates = list()
for _ in range(well_count): #for loop of length of number of wells
	#take input and split at ' ', map each to an int, save as tuple
	well_coords_temps = tuple(map(float, input("Enter X Y Z separated by a single space: ").split()))
	#append this tuple to the list well_coordinates
	well_coordinates.append(well_coords_temps)

#TODO: take photo after wait
for i in range(len(well_coordinates)):
        time.sleep(1)
        #
        print(well_coordinates[i][0],well_coordinates[i][1],well_coordinates[i][2])
        robocam.move_absolute(X=well_coordinates[i][0],Y=well_coordinates[i][1],Z=well_coordinates[i][2])
	# wait 3 seconds before taking photo
        time.sleep(1)
        l.switch(Laser.ON)
        time.sleep(3)
        photo_path = f"timestamp-{time.strftime('%Y%m%d_%H%M%S')}-img{i:03d}.png"
        camera.take_photo_and_save(photo_path)
        l.switch(Laser.OFF)
        time.sleep(2)
