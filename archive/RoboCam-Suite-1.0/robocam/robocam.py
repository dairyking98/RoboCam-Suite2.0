"""
DEPRECATED: This module is deprecated. Use robocam.robocam_ccc instead.

This implementation lacks M400 wait commands and is less reliable.
It will be removed in a future version.

Author: RoboCam-Suite
"""

import warnings
import serial
import serial.tools.list_ports
import time
import sys
import re
from picamera2 import Picamera2

warnings.warn(
    "robocam.robocam is deprecated. Use robocam.robocam_ccc instead. "
    "This module lacks M400 wait commands and will be removed in a future version.",
    DeprecationWarning,
    stacklevel=2
)

class RoboCam:
    def __init__(self, baudrate):
        # Printer startup and settings
        self.baud_rate = baudrate
        serial_port = self.find_serial_port()
        if serial_port:
            self.printer_on_serial = self.wait_for_connection(serial_port)

        self.send_gcode("M105") # creality ender 5 s1, to announce control via serial
        self.X, self.Y, self.Z = self.update_current_position()

    def send_gcode(self, command):
        print(f'[log] sending "{command}"')
        self.printer_on_serial.write((command + '\n').encode('utf-8'))  # Use '\r\n' if needed
        time.sleep(0.1)  # Initial delay for command processing
        while True:
            if self.printer_on_serial.in_waiting > 0:  # Check if there's data waiting to be read
                response = self.printer_on_serial.readline().decode('utf-8').strip()
                print(f'[log] printer response: {response}')
                if "ok" in response:  # Assuming 'ok' is the acknowledgment from the printer
                    break
                elif "error" in response:  # Handle potential error messages
                    print(f"Error from printer: {response}")
                    break

    def find_serial_port(self):
        ports = serial.tools.list_ports.comports()
        usb_ports = [port for port in ports if 'USB' in port.description]
        if not usb_ports:
            print("No USB serial ports found.")
            return None

        for usb_port in usb_ports:
            try:
                ser = serial.Serial(usb_port.device, self.baud_rate, timeout=1)
                ser.close()  # Close the port now that we know it works
                print(f"Selected port: {usb_port.device} - {usb_port.description}")
                return usb_port.device
            except serial.SerialException:
                print(f"Failed to connect on {usb_port.device}")

        print("No available ports responded.")
        return None

    def wait_for_connection(self, serial_port):
        """Attempt to open a serial connection and wait until it is established."""
        while True:
            try:
                self.printer_on_serial = serial.Serial(serial_port, self.baud_rate, timeout=1)
                print(f"Connected to {serial_port} at {self.baud_rate} baud. Allow 10 seconds for printer to load.")
                time.sleep(10)
                # Dump printer output on startup
                self.dump_printer_output()
                return self.printer_on_serial
            except serial.SerialException:
                print(f"Waiting for connection on {serial_port}...")
                time.sleep(2)  # Wait a bit before trying to connect again
                
    def dump_printer_output(self):
        while self.printer_on_serial.in_waiting > 0:  # Check if there's data waiting to be read
            response = self.printer_on_serial.readline().decode('utf-8').strip()
            print(f'[log] printer output, dumping: {response}')
                
    def home(self):
        print('Homing Printer, please wait for the countdown to complete')
        self.send_gcode('G28')  # Homing command
        print(f"Printer homed. Reset positions to X: {self.X}, Y: {self.Y}, Z: {self.Z}")

    def update_current_position(self):
        print(f'[log] updating current position')
        # Manually sending command because send_gcode dumps all output before "ok" response
        command = "M114"
        self.printer_on_serial.write((command + '\n').encode('utf-8'))  # Use '\r\n' if needed
        time.sleep(0.1)  # Initial delay for command processing
        # Parse printer's response
        while True:
            response = self.printer_on_serial.readline().decode('utf-8').strip()
            print(f'[log] printer response: {response}')
            if response.startswith('X:'):
                break
            time.sleep(0.1)
            
        position = {}
        matches = re.findall(r'(X|Y|Z):([0-9.-]+)', response)
        collected_axes = set()
        for axis, value in matches:
            try:
                if axis not in collected_axes:
                    position[axis] = float(value)
                    collected_axes.add(axis)
            except ValueError:
                continue
                    
        # Save XYZ values on the Pi
        self.X = position.get('X', None)
        self.Y = position.get('Y', None)
        self.Z = position.get('Z', None)
        # Return XYZ values if they have to be used somewhere else
        self.dump_printer_output()
        return position.get('X', None), position.get('Y', None), position.get('Z', None)
        
    # This method is for moving the print head (camera) by a certain amount of millimeters in the 3 directions
    def move_relative(self, X=None, Y=None, Z=None, speed=None):
        print(f'[log] relative move to X:{X}, Y:{Y}, Z:{Z}')
        self.send_gcode('G91')
        command = "G0"

        if speed is not None:
            command += f" F{speed}"
        if X is not None:
            command += f" X{X}"
        if Y is not None:
            command += f" Y{Y}"
        if Z is not None:
            command += f" Z{Z}"

        self.send_gcode(command)
        self.update_current_position()
            
    # This method is for moving the print head (camera) to a specific point in space
    def move_absolute(self, X=None, Y=None, Z=None, speed=None):
        print(f'[log] absolute move to X:{X}, Y:{Y}, Z:{Z}')
        self.send_gcode('G90')
        command = "G0"

        if speed is not None:
            command += f" F{speed}"
        if X is not None:
            command += f" X{X}"
        if Y is not None:
            command += f" Y{Y}"
        if Z is not None:
            command += f" Z{Z}"

        self.send_gcode(command)
        self.update_current_position()
        
    
