import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import time
import cv2
from robocam_suite.hw_manager import hw_manager
from robocam_suite.logger import setup_logger

logger = setup_logger()

def test_camera():
    logger.info("Starting camera test...")
    try:
        hw_manager.connect_all()
        camera = hw_manager.get_camera()

        if camera and camera.is_connected:
            logger.info(f"Camera connected: {camera.get_name()}")
            logger.info("Attempting to read 5 frames...")
            for i in range(5):
                frame = camera.read_frame()
                if frame is not None:
                    logger.info(f"Successfully read frame {i+1} with shape: {frame.shape}")
                    # Optionally, save a frame to verify content
                    # cv2.imwrite(f"test_frame_{i+1}.png", frame)
                else:
                    logger.warning(f"Failed to read frame {i+1}.")
                time.sleep(0.1)
            logger.info("Camera test complete.")
        else:
            logger.error("Camera not connected or not found.")

    except Exception as e:
        logger.error(f"An error occurred during camera test: {e}")
    finally:
        hw_manager.disconnect_all()
        logger.info("Disconnected all hardware.")

if __name__ == "__main__":
    test_camera()
