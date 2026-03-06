import numpy as np
from typing import Optional, Tuple
import logging
import threading
import queue
import time
import importlib.util

from robocam_suite.core.camera import Camera
from robocam_suite.logger import setup_logger

logger = setup_logger()

# Global variable to store the Picamera2 class if successfully imported
_Picamera2Class = None

def _get_picamera2_class():
    """Attempt to import Picamera2 class in a robust way."""
    global _Picamera2Class
    if _Picamera2Class is not None:
        return _Picamera2Class
    
    try:
        from picamera2 import Picamera2
        _Picamera2Class = Picamera2
        return _Picamera2Class
    except ImportError:
        # Try finding it if it's not in the standard path
        if importlib.util.find_spec("picamera2") is not None:
            try:
                import picamera2
                _Picamera2Class = picamera2.Picamera2
                return _Picamera2Class
            except:
                pass
    return None

class Picamera2Camera(Camera):
    """
    A camera implementation using Raspberry Pi's Picamera2 library.
    Uses a background thread and Queue for smooth frame acquisition, 
    matching the RoboCam 1.0 implementation style.
    """

    @staticmethod
    def force_reset() -> bool:
        """
        Forcefully release camera resources by killing other libcamera processes.
        This is a 'last resort' for 'Device Busy' errors.
        """
        import subprocess
        import os
        
        logger.warning("[Picamera2] Attempting FORCE RESET of camera resources...")
        
        try:
            # 1. Kill common libcamera-apps and v4l2 utilities
            apps = ["libcamera-hello", "libcamera-vid", "libcamera-still", "libcamera-raw", "v4l2-ctl"]
            for app in apps:
                subprocess.run(["pkill", "-9", app], stderr=subprocess.DEVNULL)
            
            # 2. Kill any other python process that might be using the camera (except us)
            # We use pgrep to find other python processes and check if they are us
            try:
                current_pid = str(os.getpid())
                result = subprocess.run(["pgrep", "python"], capture_output=True, text=True)
                pids = result.stdout.strip().split("\n")
                for pid in pids:
                    if pid and pid != current_pid:
                        # Check if this process is holding a camera device
                        # We use lsof if available, otherwise fuser is fine
                        subprocess.run(["fuser", "-k", "-9", "/dev/video0"], stderr=subprocess.DEVNULL)
                        subprocess.run(["fuser", "-k", "-9", "/dev/media0"], stderr=subprocess.DEVNULL)
            except:
                pass
            
            # 3. Last resort: restart the unicam driver (requires sudo, might not work without password)
            # subprocess.run(["sudo", "modprobe", "-r", "bcm2835_unicam"], stderr=subprocess.DEVNULL)
            # subprocess.run(["sudo", "modprobe", "bcm2835_unicam"], stderr=subprocess.DEVNULL)

            logger.info("[Picamera2] Force reset commands sent.")
            return True
        except Exception as e:
            logger.error(f"[Picamera2] Force reset failed: {e}")
            return False

    def __init__(self, config: Optional[dict] = None, simulate: bool = False):
        self._config = config or {}
        self._simulate = simulate
        self._picamera2 = None
        self._resolution = self._config.get("resolution", (2028, 1520)) # HQ Camera default
        self._fps = self._config.get("fps", 30.0)
        
        # Threading and Queue setup
        self._frame_queue = queue.Queue(maxsize=2)
        self._stop_event = threading.Event()
        self._capture_thread: Optional[threading.Thread] = None
        self._is_running = False

        if self._simulate:
            logger.info("[Picamera2] Running in SIMULATION MODE")

    def connect(self) -> None:
        if self._simulate:
            self._is_running = True
            return

        if self.is_connected:
            return

        Picamera2 = _get_picamera2_class()
        if Picamera2 is None:
            raise ImportError("Picamera2 library not found. Ensure you are on a Raspberry Pi with libcamera-python installed.")

        try:
            cam_idx = self._config.get("camera_index", 0)
            logger.info(f"[Picamera2] Initializing camera {cam_idx}...")
            
            # Device Busy Prevention: retry loop
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    self._picamera2 = Picamera2(camera_num=cam_idx)
                    break
                except Exception as e:
                    if "Device or resource busy" in str(e) and attempt < 2:
                        logger.warning(f"[Picamera2] Device busy, attempting AUTOMATIC FORCE RESET... (attempt {attempt+1}/3)")
                        self.force_reset() # Attempt to kill zombie processes
                        time.sleep(1.5) # Give the OS a bit more time to recover
                    else:
                        raise e
            
            # Configure the camera
            # libcamera/Picamera2 requires specific formats and sizes.
            # YUV420 is the most native and efficient format for the ISP.
            # We use it for capture and convert to BGR in the capture loop.
            try:
                # Log camera info to help debugging
                info = self._picamera2.camera_info
                logger.info(f"[Picamera2] Camera Info: {info}")
                
                logger.info(f"[Picamera2] Configuring stream: {self._resolution} YUV420 @ {self._fps} FPS")
                config = self._picamera2.create_video_configuration(
                    main={"size": self._resolution, "format": "YUV420"}
                )
                
                # Log the config to see what Picamera2 suggested
                logger.debug(f"[Picamera2] Suggested config: {config}")
                
                # Set framerate in the config controls if possible
                try:
                    config.controls.update({"FrameRate": self._fps})
                except Exception as ce:
                    logger.debug(f"[Picamera2] Could not set FrameRate in config: {ce}")
                
                self._picamera2.configure(config)
                logger.info("[Picamera2] Configuration applied successfully.")
            except Exception as e:
                logger.warning(f"[Picamera2] Failed with preferred config, trying default: {e}")
                # Fallback to a very safe default (usually 640x480 or similar)
                try:
                    config = self._picamera2.create_video_configuration()
                    self._picamera2.configure(config)
                    logger.info("[Picamera2] Fallback configuration applied.")
                except Exception as fe:
                    logger.error(f"[Picamera2] Fallback configuration also failed: {fe}")
                    raise fe
            
            try:
                self._picamera2.start()
                logger.info("[Picamera2] Camera started successfully.")
            except Exception as se:
                logger.error(f"[Picamera2] Failed to start camera: {se}")
                # One last attempt: close and reopen if start fails
                self._cleanup_resources()
                raise se
            
            # Start background capture thread
            self._stop_event.clear()
            self._capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
            self._capture_thread.start()
            
            self._is_running = True
            logger.info(f"[Picamera2] Connected and started thread at {self._resolution} @ {self._fps} FPS")
        except Exception as e:
            self._cleanup_resources()
            logger.error(f"[Picamera2] Failed to initialize: {e}")
            raise ConnectionError(f"Could not initialize Picamera2: {e}") from e

    def _capture_loop(self):
        """Background thread to continuously pull frames into the queue."""
        logger.debug("[Picamera2] Capture loop started.")
        import cv2
        while not self._stop_event.is_set():
            try:
                if self._picamera2:
                    # Capture a frame into a numpy array.
                    # Since we configured for YUV420, capture_array() returns YUV data.
                    # We convert it to BGR (standard for OpenCV/RoboCam) here.
                    frame_yuv = self._picamera2.capture_array()
                    
                    if frame_yuv is not None:
                        # Picamera2 capture_array() for YUV420 returns a YUV420p array.
                        # We use cv2 to convert it to BGR.
                        frame = cv2.cvtColor(frame_yuv, cv2.COLOR_YUV420p2BGR)
                        
                        # Keep the queue fresh by removing old frames if full
                        if self._frame_queue.full():
                            try:
                                self._frame_queue.get_nowait()
                            except queue.Empty:
                                pass
                        self._frame_queue.put(frame)
                else:
                    time.sleep(0.1)
            except Exception as e:
                logger.error(f"[Picamera2] Error in capture loop: {e}")
                time.sleep(0.5)
        logger.debug("[Picamera2] Capture loop stopped.")

    def disconnect(self) -> None:
        self._is_running = False
        self._stop_event.set()
        
        if self._capture_thread and self._capture_thread.is_alive():
            self._capture_thread.join(timeout=2.0)
            
        self._cleanup_resources()
        logger.info("[Picamera2] Disconnected.")

    def _cleanup_resources(self) -> None:
        """Safely close the Picamera2 instance."""
        if self._picamera2:
            try:
                self._picamera2.stop()
                self._picamera2.close()
            except:
                pass
        self._picamera2 = None
        # Clear the queue
        while not self._frame_queue.empty():
            try:
                self._frame_queue.get_nowait()
            except queue.Empty:
                break

    def start_capture(self) -> None:
        pass

    def stop_capture(self) -> None:
        pass

    def read_frame(self) -> Optional[np.ndarray]:
        if self._simulate:
            return np.zeros((self._resolution[1], self._resolution[0], 3), dtype=np.uint8)

        if not self.is_connected:
            return None

        try:
            # Return the latest frame from the queue without blocking
            return self._frame_queue.get(timeout=0.1)
        except queue.Empty:
            return None

    def get_resolution(self) -> Tuple[int, int]:
        return self._resolution

    def set_resolution(self, resolution: Tuple[int, int]) -> None:
        if self._resolution == resolution:
            return
        self._resolution = resolution
        if self.is_connected and not self._simulate:
            logger.info(f"[Picamera2] Updating resolution to {resolution}. Restarting...")
            self.disconnect()
            self.connect()

    def get_fps(self) -> float:
        return self._fps

    def set_fps(self, fps: float) -> None:
        if self._fps == fps:
            return
        self._fps = fps
        if self.is_connected and not self._simulate:
            logger.info(f"[Picamera2] Updating FPS to {fps}. Restarting...")
            self.disconnect()
            self.connect()

    @property
    def is_connected(self) -> bool:
        if self._simulate:
            return self._is_running
        return self._is_running and self._picamera2 is not None
