"""
Picamera2 High-FPS Capture Module - High-FPS Grayscale Capture

Fast grayscale capture using Picamera2 with YUV420 format.
Allows grayscale video capture at very high frame rates (100+ FPS) using modern libcamera stack.

This is the recommended approach for Raspberry Pi OS (Bullseye/Bookworm) using libcamera.
Replaces the legacy raspividyuv command-line tool.

Option A (hardware encoder) quick start:
    capture = Picamera2HighFpsCapture(width=1920, height=1080, fps=30)
    frames = capture.record_with_ffmpeg(
        output_path="output.mp4",
        codec="h264_v4l2m2m",
        bitrate="12M",
        duration_seconds=10
    )
    capture.stop_capture()

Based on: https://gist.github.com/CarlosGS/b8462a8a1cb69f55d8356cbb0f3a4d63

Author: RoboCam-Suite
"""

import numpy as np
import cv2
import atexit
import time
import os
import subprocess
from typing import Optional, List
from picamera2 import Picamera2
from robocam.logging_config import get_logger

logger = get_logger(__name__)


class Picamera2HighFpsCapture:
    """
    High-FPS grayscale capture using Picamera2 with YUV420 format.
    
    Provides direct access to raw YUV420 frames, extracting Y (luminance) channel for grayscale.
    Supports saving frames as individual PNG files or encoding to video.
    
    Attributes:
        width (int): Frame width in pixels
        height (int): Frame height in pixels
        fps (int): Target frames per second
        picam2 (Optional[Picamera2]): Picamera2 instance
        frames (List[np.ndarray]): Buffer for captured frames
        _recording (bool): Whether currently recording frames
    """
    
    def __init__(self, width: int = 640, height: int = 480, fps: int = 250, picam2: Optional[Picamera2] = None) -> None:
        """
        Initialize Picamera2 high-FPS capture.
        
        Args:
            width: Frame width in pixels (should be multiple of 32 for optimal performance)
            height: Frame height in pixels (should be multiple of 16 for optimal performance)
            fps: Target frames per second
            picam2: Optional existing Picamera2 instance to reuse (will be stopped and reconfigured)
        """
        self.width: int = width
        self.height: int = height
        self.fps: int = fps
        self.picam2: Optional[Picamera2] = picam2  # Use provided instance or create new one
        self._picam2_provided: bool = picam2 is not None  # Track if we need to clean up on stop
        self.frames: List[np.ndarray] = []
        self._recording: bool = False
        self.last_error: Optional[str] = None
        self._ffmpeg_process: Optional[subprocess.Popen] = None
        self._ffmpeg_cmd: Optional[List[str]] = None
        # Precompute frame duration limit (microseconds) to nudge libcamera toward target FPS
        self._frame_duration_us: int = max(1, int(1_000_000 / max(1, fps)))
        
    def start_capture(self) -> bool:
        """
        Start capturing frames from camera.
        
        Returns:
            True if capture started successfully, False otherwise
        """
        self.last_error = None
        try:
            # Always stop existing camera if it's running (critical for proper transitions)
            if self.picam2 is not None:
                try:
                    # Clear any callbacks that might interfere with new configuration
                    if hasattr(self.picam2, 'post_callback'):
                        self.picam2.post_callback = None
                    if hasattr(self.picam2, 'pre_callback'):
                        self.picam2.pre_callback = None
                    
                    # Always stop the camera instance - this is required before reconfiguring
                    if hasattr(self.picam2, 'started') and self.picam2.started:
                        self.picam2.stop()
                        logger.info("Stopped existing Picamera2 instance before reconfiguring")
                    
                    # If allocator is missing (older picamera2 builds), recreate instance
                    if not hasattr(self.picam2, "allocator"):
                        self.picam2 = Picamera2()
                        self._picam2_provided = False
                        logger.info("Recreated Picamera2 instance because allocator was missing")
                    
                    # Wait for camera to fully stop and release hardware
                    time.sleep(0.5)
                except Exception as e:
                    logger.warning(f"Error stopping existing Picamera2 instance: {e}")
            else:
                # Create new Picamera2 instance if none was provided
                self.picam2 = Picamera2()
                self._picam2_provided = False
                logger.info("Created new Picamera2 instance for high-FPS capture")
            
            # Create video configuration with single-plane Y format for fastest readout.
            # Fallback to YUV420 if Y is unsupported on this platform.
            try:
                config = self.picam2.create_video_configuration(
                    main={"format": "Y", "size": (self.width, self.height)},
                    controls={
                        "FrameRate": self.fps,
                        "FrameDurationLimits": (self._frame_duration_us, self._frame_duration_us)
                    },
                    buffer_count=2  # Optimize buffer for high FPS
                )
                selected_format = "Y"
            except Exception as e:
                logger.warning(f"Y format not available, falling back to YUV420: {e}")
                config = self.picam2.create_video_configuration(
                    main={"format": "YUV420", "size": (self.width, self.height)},
                    controls={
                        "FrameRate": self.fps,
                        "FrameDurationLimits": (self._frame_duration_us, self._frame_duration_us)
                    },
                    buffer_count=2
                )
                selected_format = "YUV420"
            self._selected_format = selected_format
            
            # Always configure before starting - this initializes the allocator properly
            try:
                self.picam2.configure(config)
            except Exception as e:
                # If Y failed at configure time, retry once with YUV420
                if selected_format == "Y":
                    logger.warning(f"Configure failed for Y format, retrying with YUV420: {e}")
                    self.last_error = f"Y format configure failed: {e}"
                    config = self.picam2.create_video_configuration(
                        main={"format": "YUV420", "size": (self.width, self.height)},
                        controls={"FrameRate": self.fps},
                        buffer_count=2
                    )
                    selected_format = "YUV420"
                    self._selected_format = selected_format
                    self.picam2.configure(config)
                else:
                    raise
            logger.info(f"Configured Picamera2: {self.width}x{self.height} @ {self.fps} FPS ({selected_format})")
            
            # Brief pause after configure to ensure allocator is ready
            time.sleep(0.2)
            
            # Start the camera - this activates the allocator
            self.picam2.start()
            logger.info("Started Picamera2 for high-FPS capture")
            
            # Wait for camera to be ready
            time.sleep(0.2)
            
            # Register cleanup on exit
            atexit.register(self.stop_capture)
            
            # Wait for first frame and discard it (warmup)
            try:
                # Capture a frame to warm up using capture_array (more efficient for high-FPS)
                _ = self.picam2.capture_array("main")
            except Exception as e:
                logger.error(f"Error during warmup: {e}")
                self.last_error = str(e)
                self.stop_capture()
                return False
            
            logger.info(f"Picamera2 high-FPS capture started: {self.width}x{self.height} @ {self.fps} FPS")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start Picamera2 capture: {e}")
            self.last_error = str(e)
            self.stop_capture()
            return False
    
    def read_frame(self) -> Optional[np.ndarray]:
        """
        Read a single frame from the camera stream.
        
        Returns:
            Grayscale frame as numpy array (height, width), or None if error
        """
        if self.picam2 is None:
            logger.error("Capture not started")
            return None
        
        try:
            # Use capture_array for high-FPS - more efficient than capture_request
            # For Y format, this directly returns the Y plane as a 2D array
            # For YUV420, we'll extract the Y channel
            frame = self.picam2.capture_array("main")
            
            if frame is None:
                logger.warning("Received empty frame")
                return None
            
            # Expect a 2D array shaped (h, w) for Y format
            if frame.ndim == 2 and frame.shape[0] == self.height and frame.shape[1] == self.width:
                return frame
            
            # Fallback: handle YUV layouts if a different format slips through
            if frame.ndim == 2 and frame.shape[0] == self.height * 3 // 2:
                return frame[:self.height, :self.width].copy()
            if frame.ndim == 3:
                return frame[:, :, 0].copy()
            
            logger.warning(f"Unexpected frame shape: {frame.shape}")
            return None
                
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
        """Stop capturing and clean up Picamera2 instance."""
        if self.picam2 is not None:
            try:
                if hasattr(self.picam2, 'started') and self.picam2.started:
                    self.picam2.stop()
            except Exception as e:
                logger.warning(f"Error stopping Picamera2: {e}")
            finally:
                self.stop_ffmpeg_encoder()
                # Only set to None if we created it (not if it was provided)
                if not self._picam2_provided:
                    self.picam2 = None
                self._recording = False
                logger.info("Picamera2 high-FPS capture stopped")

    def start_ffmpeg_encoder(self,
                             output_path: str,
                             codec: str = "h264_v4l2m2m",
                             ffmpeg_path: str = "ffmpeg",
                             bitrate: Optional[str] = None,
                             extra_args: Optional[List[str]] = None,
                             overwrite: bool = True) -> bool:
        """
        Start an FFmpeg hardware-accelerated encoder that accepts raw grayscale frames via stdin.

        Args:
            output_path: Output file path (e.g., .mp4, .mkv)
            codec: FFmpeg video codec (h264_v4l2m2m or hevc_v4l2m2m)
            ffmpeg_path: Path to FFmpeg executable
            bitrate: Optional target bitrate string (e.g., "10M")
            extra_args: Additional FFmpeg arguments to append before output_path
            overwrite: Whether to overwrite an existing file

        Returns:
            True if the encoder started successfully, False otherwise
        """
        if self._ffmpeg_process is not None:
            logger.info("Stopping existing FFmpeg encoder before starting new one")
            self.stop_ffmpeg_encoder()

        cmd: List[str] = [ffmpeg_path]
        if overwrite:
            cmd.append("-y")
        cmd += [
            "-f", "rawvideo",
            "-pix_fmt", "gray",
            "-s", f"{self.width}x{self.height}",
            "-r", str(self.fps),
            "-i", "-",
            "-c:v", codec
        ]
        if bitrate:
            cmd += ["-b:v", bitrate]
        cmd += ["-pix_fmt", "gray"]
        if extra_args:
            cmd.extend(extra_args)
        cmd.append(output_path)

        try:
            self._ffmpeg_process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            self._ffmpeg_cmd = cmd
            logger.info(f"Started FFmpeg encoder: {' '.join(cmd)}")
            return True
        except FileNotFoundError:
            logger.error(f"FFmpeg executable not found: {ffmpeg_path}")
        except Exception as e:
            logger.error(f"Failed to start FFmpeg encoder: {e}")

        self._ffmpeg_process = None
        self._ffmpeg_cmd = None
        return False

    def stop_ffmpeg_encoder(self) -> None:
        """Stop FFmpeg encoder if running."""
        if self._ffmpeg_process is None:
            return

        try:
            if self._ffmpeg_process.stdin:
                self._ffmpeg_process.stdin.flush()
                self._ffmpeg_process.stdin.close()
            self._ffmpeg_process.wait(timeout=5)
        except Exception as e:
            logger.warning(f"Error stopping FFmpeg encoder: {e}")
        finally:
            self._ffmpeg_process = None
            self._ffmpeg_cmd = None
            logger.info("Stopped FFmpeg encoder")

    def record_with_ffmpeg(self,
                           output_path: str,
                           codec: str = "h264_v4l2m2m",
                           ffmpeg_path: str = "ffmpeg",
                           bitrate: Optional[str] = None,
                           duration_seconds: Optional[float] = None,
                           frame_limit: Optional[int] = None,
                           extra_args: Optional[List[str]] = None) -> int:
        """
        Record high-FPS grayscale video by piping raw Y-plane frames to FFmpeg hardware encoder.

        Args:
            output_path: Destination video file
            codec: FFmpeg codec (h264_v4l2m2m or hevc_v4l2m2m recommended)
            ffmpeg_path: Path to FFmpeg executable
            bitrate: Optional target bitrate (e.g., "20M")
            duration_seconds: Optional max duration in seconds
            frame_limit: Optional max number of frames to record
            extra_args: Extra FFmpeg CLI args (e.g., ["-g", "30"])

        Returns:
            Number of frames successfully written
        """
        if self.picam2 is None:
            started = self.start_capture()
            if not started:
                logger.error("Failed to start Picamera2 before recording")
                return 0

        if not self.start_ffmpeg_encoder(output_path=output_path,
                                         codec=codec,
                                         ffmpeg_path=ffmpeg_path,
                                         bitrate=bitrate,
                                         extra_args=extra_args):
            return 0

        if self._ffmpeg_process is None or self._ffmpeg_process.stdin is None:
            logger.error("FFmpeg process failed to initialize")
            return 0

        frames_written = 0
        start_time = time.perf_counter()

        try:
            while True:
                if duration_seconds is not None and (time.perf_counter() - start_time) >= duration_seconds:
                    break
                if frame_limit is not None and frames_written >= frame_limit:
                    break

                frame = self.read_frame()
                if frame is None:
                    logger.warning("Skipping empty frame during FFmpeg recording")
                    continue

                # Ensure contiguous buffer before writing to pipe
                gray_plane = np.ascontiguousarray(frame)
                try:
                    self._ffmpeg_process.stdin.write(gray_plane.tobytes())
                except BrokenPipeError:
                    logger.error("FFmpeg pipe closed unexpectedly")
                    break
                frames_written += 1
        finally:
            self.stop_ffmpeg_encoder()

        elapsed = time.perf_counter() - start_time
        if elapsed > 0:
            actual_fps = frames_written / elapsed
            logger.info(f"Wrote {frames_written} frames to FFmpeg in {elapsed:.2f}s ({actual_fps:.1f} FPS)")
        else:
            logger.info(f"Wrote {frames_written} frames to FFmpeg")

        return frames_written

