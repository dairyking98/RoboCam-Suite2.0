import RPi.GPIO as GPIO
import time

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)
GPIO.setup(18, GPIO.OUT)

try:
    while True:
        GPIO.output(18, GPIO.HIGH)
        time.sleep(1)

        GPIO.output(18, GPIO.LOW)
        time.sleep(1)

        GPIO.output(18, GPIO.HIGH)
        time.sleep(10)

        GPIO.output(18, GPIO.LOW)
        time.sleep(10)

except KeyboardInterrupt:
    GPIO.cleanup()

GPIO.cleanup()

