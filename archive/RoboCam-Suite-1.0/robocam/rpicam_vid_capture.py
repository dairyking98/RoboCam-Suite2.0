"""
Rpicam-Vid Capture Module - High-FPS Grayscale Capture

Fast grayscale capture using rpicam-vid command-line tool with YUV420 format.
Allows grayscale video capture at very high frame rates (100+ FPS) using modern libcamera stack.

This is an alternative subprocess-based approach using rpicam-vid.
Replaces the legacy raspividyuv command-line tool.

Based on: https://gist.github.com/CarlosGS/b8462a8a1cb69f55d8356cbb0f3a4d63

Author: RoboCam-Suite
"""

import subprocess as sp
import numpy as np
import cv2
import atexit
import time
import os
from typing import Optional, List
from robocam.logging_config import get_logger

logger = get_logger(__name__)


class RpicamVidCapture:
    """
    High-FPS grayscale capture using rpicam-vid command-line tool.
    
    Provides direct access to raw YUV420 frames via subprocess, extracting Y (luminance) channel.
    Supports saving frames as individual PNG files or encoding to video.
    
    Attributes:
        width (int): Frame width in pixels
        height (int): Frame height in pixels
        fps (int): Target frames per second
        bytes_per_frame (int): Number of bytes per YUV420 frame (width * height * 3 / 2)
        y_bytes_per_frame (int): Number of bytes for Y channel (width * height)
        process (Optional[sp.Popen]): Subprocess running rpicam-vid
        frames (List[np.ndarray]): Buffer for captured frames
        _recording (bool): Whether currently recording frames
    """
    
    def __init__(self, width: int = 640, height: int = 480, fps: int = 250) -> None:
        """
        Initialize rpicam-vid capture.
        
        Args:
            width: Frame width in pixels (should be multiple of 32 for optimal performance)
            height: Frame height in pixels (should be multiple of 16 for optimal performance)
            fps: Target frames per second
        """
        self.width: int = width
        self.height: int = height
        self.fps: int = fps
        # YUV420: Y plane = w*h, U plane = w*h/4, V plane = w*h/4
        # Total = w*h + w*h/4 + w*h/4 = w*h*3/2
        self.bytes_per_frame: int = width * height * 3 // 2
        self.y_bytes_per_frame: int = width * height
        self.process: Optional[sp.Popen] = None
        self.frames: List[np.ndarray] = []
        self._recording: bool = False
        self.last_error: Optional[str] = None
        
    def start_capture(self) -> bool:
        """
        Start capturing frames from camera.
        
        Returns:
            True if capture started successfully, False otherwise
        """
        self.last_error = None
        if self.process is not None:
            logger.warning("Capture already started")
            return False
        
        # Check if rpicam-vid is available
        try:
            result = sp.run(["rpicam-vid", "--help"], 
                           stdout=sp.DEVNULL, stderr=sp.DEVNULL, timeout=2)
            if result.returncode != 0:
                logger.error("rpicam-vid command failed. Please install libcamera-apps: sudo apt-get install -y libcamera-apps")
                self.last_error = "rpicam-vid command failed"
                return False
        except FileNotFoundError:
            logger.error("rpicam-vid command not found. Please install libcamera-apps: sudo apt-get install -y libcamera-apps")
            self.last_error = "rpicam-vid not found"
            return False
        except sp.TimeoutExpired:
            logger.error("rpicam-vid command timed out. Camera may be in use by another process.")
            self.last_error = "rpicam-vid timed out (camera busy?)"
            return False
        except Exception as e:
            logger.error(f"Error checking rpicam-vid availability: {e}")
            self.last_error = str(e)
            return False
        
        # Build rpicam-vid command
        # -t 0: continuous video (no timeout)
        # --codec yuv420: output raw YUV420 format
        # --output -: send output to stdout
        # -n: no preview window
        video_cmd = [
            "rpicam-vid",
            "-t", "0",
            "--codec", "yuv420",
            "--width", str(self.width),
            "--height", str(self.height),
            "--framerate", str(self.fps),
            "-o", "-",
            "-n"
        ]
        
        try:
            # Start subprocess with unbuffered output
            # Use stderr=sp.PIPE to capture error messages
            self.process = sp.Popen(
                video_cmd,
                stdout=sp.PIPE,
                stderr=sp.PIPE,
                bufsize=0  # Unbuffered
            )
            
            # Give process a moment to start and check if it's still running
            time.sleep(0.2)
            if self.process.poll() is not None:
                # Process exited immediately - likely an error
                stderr_output = ""
                if self.process.stderr:
                    try:
                        stderr_output = self.process.stderr.read().decode('utf-8', errors='ignore')
                    except Exception as e:
                        stderr_output = f"<stderr decode failed: {e}>"
                error_msg = (
                    "rpicam-vid process exited immediately.\n"
                    f"Command: {' '.join(video_cmd)}\n"
                    f"Stderr:\n{stderr_output[:2000]}"
                )
                logger.error(error_msg)
                self.last_error = error_msg
                self.stop_capture()
                return False
            
            # Register cleanup on exit
            atexit.register(self.stop_capture)
            
            # Wait for first frame and discard it (warmup)
            try:
                raw_stream = self.process.stdout.read(self.bytes_per_frame)
                if len(raw_stream) != self.bytes_per_frame:
                    stderr_output = ""
                    if self.process.stderr:
                        try:
                            stderr_output = self.process.stderr.read().decode('utf-8', errors='ignore')[:200]
                        except:
                            pass
                    logger.error(f"Failed to read initial frame. Expected {self.bytes_per_frame} bytes, got {len(raw_stream)}. Error: {stderr_output}")
                    self.last_error = f"init frame short read ({len(raw_stream)}/{self.bytes_per_frame}) {stderr_output}"
                    self.stop_capture()
                    return False
            except Exception as e:
                logger.error(f"Error reading initial frame: {e}")
                self.last_error = str(e)
                self.stop_capture()
                return False
            
            logger.info(f"Rpicam-vid capture started: {self.width}x{self.height} @ {self.fps} FPS")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start rpicam-vid: {e}")
            self.last_error = str(e)
            if self.process is not None:
                self.stop_capture()
            return False
    
    def read_frame(self) -> Optional[np.ndarray]:
        """
        Read a single frame from the camera stream.
        
        Returns:
            Grayscale frame as numpy array (height, width), or None if error
        """
        if self.process is None:
            logger.error("Capture not started")
            return None
        
        # Check if subprocess is still alive
        if self.process.poll() is not None:
            # Process has terminated
            stderr_output = ""
            if self.process.stderr:
                try:
                    stderr_output = self.process.stderr.read().decode('utf-8', errors='ignore')
                except:
                    pass
            logger.error(f"rpicam-vid process has terminated (returncode: {self.process.returncode}). Stderr: {stderr_output[:500]}")
            return None
        
        try:
            # Read raw YUV420 frame (w*h*3/2 bytes total) with a short timeout to avoid blocking forever
            import select, os
            # Use shorter timeout (0.1s) to allow more frequent checks and faster failure detection
            timeout_seconds = 0.1
            rlist, _, _ = select.select([self.process.stdout], [], [], timeout_seconds)
            if not rlist:
                # Check again if process is still alive after timeout
                if self.process.poll() is not None:
                    logger.error("rpicam-vid process terminated during read timeout")
                    return None
                logger.debug("rpicam-vid read timeout (no data available)")
                return None
            
            # Check process status one more time before reading
            if self.process.poll() is not None:
                logger.error("rpicam-vid process terminated before read")
                return None
            
            # Read with a limit to prevent blocking too long
            # Use os.read with the exact number of bytes needed
            frame_bytes = os.read(self.process.stdout.fileno(), self.bytes_per_frame)
            
            if len(frame_bytes) != self.bytes_per_frame:
                logger.warning(f"Read incomplete frame: {len(frame_bytes)}/{self.bytes_per_frame} bytes")
                return None
            
            # Extract Y (luminance) channel - first w*h bytes
            y_bytes = frame_bytes[:self.y_bytes_per_frame]
            
            # Convert Y channel to numpy array
            frame = np.frombuffer(y_bytes, dtype=np.uint8)
            frame = frame.reshape((self.height, self.width))
            
            return frame
            
        except Exception as e:
            logger.error(f"Error reading frame: {e}")
            return None
    
    def capture_frame_sequence(self, num_frames: int, 
                               save_individual: bool = False,
                               output_dir: Optional[str] = None) -> List[np.ndarray]:
        """
        Capture a sequence of frames.
        
        Args:
            num_frames: Number of frames to capture
            save_individual: If True, save each frame as PNG file
            output_dir: Directory to save individual frames (if save_individual is True)
            
        Returns:
            List of captured frames as numpy arrays
        """
        frames = []
        start_time = time.time()
        
        for i in range(num_frames):
            frame = self.read_frame()
            if frame is None:
                logger.warning(f"Failed to capture frame {i+1}/{num_frames}")
                continue
            
            frames.append(frame.copy())
            
            # Save individual frame if requested
            if save_individual and output_dir:
                timestamp = time.strftime('%Y%m%d_%H%M%S')
                frame_path = os.path.join(output_dir, f"frame_{i:06d}_{timestamp}.png")
                cv2.imwrite(frame_path, frame)
        
        elapsed = time.time() - start_time
        if elapsed > 0:
            actual_fps = len(frames) / elapsed
            logger.info(f"Captured {len(frames)} frames in {elapsed:.2f}s ({actual_fps:.1f} FPS)")
        
        return frames
    
    def start_recording(self) -> None:
        """Start recording frames to buffer."""
        self.frames = []
        self._recording = True
        logger.info("Started recording frames")
    
    def stop_recording(self) -> None:
        """Stop recording frames."""
        self._recording = False
        logger.info(f"Stopped recording. Captured {len(self.frames)} frames")
    
    def is_recording(self) -> bool:
        """Check if currently recording."""
        return self._recording
    
    def save_frames_to_video(self, output_path: str, 
                            fps: Optional[float] = None,
                            codec: str = "FFV1") -> bool:
        """
        Save captured frames to video file with minimal compression.
        
        Args:
            output_path: Path to save video file
            fps: Frames per second for video (uses capture FPS if None)
            codec: Video codec to use ("FFV1" for lossless, "PNG" for PNG codec)
            
        Returns:
            True if successful, False otherwise
        """
        if not self.frames:
            logger.error("No frames to save")
            return False
        
        if fps is None:
            fps = float(self.fps)
        
        # Determine codec
        if codec == "FFV1":
            # FFV1 lossless codec (requires OpenCV with FFV1 support)
            fourcc = cv2.VideoWriter_fourcc(*'FFV1')
            ext = ".avi"
        elif codec == "PNG":
            # PNG codec (lossless, but very large files)
            fourcc = cv2.VideoWriter_fourcc(*'PNG ')
            ext = ".avi"
        else:
            logger.warning(f"Unknown codec {codec}, using FFV1")
            fourcc = cv2.VideoWriter_fourcc(*'FFV1')
            ext = ".avi"
        
        # Ensure output path has correct extension
        if not output_path.endswith(ext):
            base_path = os.path.splitext(output_path)[0]
            output_path = base_path + ext
        
        # Convert grayscale frames to BGR for video codec
        # Most codecs require 3-channel images
        height, width = self.frames[0].shape
        out = cv2.VideoWriter(output_path, fourcc, fps, (width, height), isColor=True)
        
        if not out.isOpened():
            logger.error(f"Failed to open video writer for {output_path}")
            return False
        
        logger.info(f"Saving {len(self.frames)} frames to {output_path} using {codec} codec @ {fps} FPS")
        
        for i, frame in enumerate(self.frames):
            # Convert grayscale to BGR (3-channel)
            frame_bgr = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
            out.write(frame_bgr)
            
            if (i + 1) % 100 == 0:
                logger.debug(f"Saved {i+1}/{len(self.frames)} frames")
        
        out.release()
        logger.info(f"Successfully saved video: {output_path}")
        return True
    
    def save_frames_to_png_sequence(self, output_dir: str, prefix: str = "frame") -> bool:
        """
        Save captured frames as individual PNG files.
        
        Args:
            output_dir: Directory to save PNG files
            prefix: Filename prefix for frames
            
        Returns:
            True if successful, False otherwise
        """
        if not self.frames:
            logger.error("No frames to save")
            return False
        
        os.makedirs(output_dir, exist_ok=True)
        
        logger.info(f"Saving {len(self.frames)} frames as PNG sequence to {output_dir}")
        
        for i, frame in enumerate(self.frames):
            frame_path = os.path.join(output_dir, f"{prefix}_{i:06d}.png")
            cv2.imwrite(frame_path, frame)
            
            if (i + 1) % 100 == 0:
                logger.debug(f"Saved {i+1}/{len(self.frames)} frames")
        
        logger.info(f"Successfully saved {len(self.frames)} PNG frames to {output_dir}")
        return True
    
    def stop_capture(self) -> None:
        """Stop capturing and clean up subprocess."""
        if self.process is not None:
            try:
                self.process.terminate()
                self.process.wait(timeout=2)
            except sp.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            except Exception as e:
                logger.warning(f"Error stopping process: {e}")
            finally:
                self.process = None
                self._recording = False
                logger.info("Rpicam-vid capture stopped")

