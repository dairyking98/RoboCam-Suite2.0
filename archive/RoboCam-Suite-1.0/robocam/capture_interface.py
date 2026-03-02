"""
Unified Capture Interface - Multi-Capture Type Manager

Provides a unified interface for different capture types:
- Picamera2 (Color)
- Picamera2 (Grayscale)
- Picamera2 (Grayscale - High FPS) - using Picamera2 directly
- rpicam-vid (Grayscale - High FPS) - using rpicam-vid subprocess
- Player One (Grayscale) - Mars 662M etc. via Player One SDK

Author: RoboCam-Suite
"""

import os
import time
import cv2
import numpy as np
from typing import Optional, Tuple, List
from picamera2 import Picamera2
from picamera2.encoders import H264Encoder
from picamera2.outputs import FileOutput
from robocam.pihqcamera import PiHQCamera
from robocam.picamera2_highfps_capture import Picamera2HighFpsCapture
from robocam.rpicam_vid_capture import RpicamVidCapture
from robocam.playerone_camera import PlayerOneCamera
from robocam.logging_config import get_logger

logger = get_logger(__name__)


class CaptureManager:
    """
    Unified interface for multiple capture types.
    
    Supports four capture modes:
    - "Picamera2 (Color)": Standard color capture using Picamera2
    - "Picamera2 (Grayscale)": Grayscale capture using Picamera2 with YUV420
    - "Picamera2 (Grayscale - High FPS)": High-FPS grayscale using Picamera2 directly (recommended)
    - "rpicam-vid (Grayscale - High FPS)": High-FPS grayscale using rpicam-vid subprocess
    
    Attributes:
        capture_type (str): Current capture type
        resolution (Tuple[int, int]): Capture resolution (width, height)
        fps (float): Target frames per second
        picam2 (Optional[Picamera2]): Picamera2 instance (for Picamera2 modes)
        pihq_camera (Optional[PiHQCamera]): PiHQCamera wrapper (for Picamera2 modes)
        picamera2_highfps (Optional[Picamera2HighFpsCapture]): Picamera2 high-FPS instance
        rpicam_vid (Optional[RpicamVidCapture]): Rpicam-vid instance (for subprocess high-FPS mode)
        _recording (bool): Whether currently recording video
        _recorded_frames (List): Buffer for recorded frames (high-FPS modes)
    """
    
    CAPTURE_TYPES = [
        "Picamera2 (Color)",
        "Picamera2 (Grayscale)",
        "Picamera2 (Grayscale - High FPS)",
        "rpicam-vid (Grayscale - High FPS)",
        "Player One (Grayscale)",  # Mars 662M etc. via SDK
    ]
    # Types available when Player One (SDK) camera backend is detected
    CAPTURE_TYPES_PLAYERONE = ["Player One (Grayscale)"]

    def __init__(self, capture_type: str = "Picamera2 (Color)",
                 resolution: Tuple[int, int] = (1920, 1080),
                 fps: float = 30.0,
                 picam2: Optional[Picamera2] = None,
                 playerone_camera: Optional[PlayerOneCamera] = None) -> None:
        """
        Initialize capture manager.

        Args:
            capture_type: Capture type from CAPTURE_TYPES
            resolution: Capture resolution (width, height)
            fps: Target frames per second
            picam2: Optional existing Picamera2 instance (for Pi HQ modes)
            playerone_camera: Optional PlayerOneCamera instance (for Player One modes)
        """
        if capture_type not in self.CAPTURE_TYPES:
            raise ValueError(f"Invalid capture type: {capture_type}. Must be one of {self.CAPTURE_TYPES}")

        self.capture_type: str = capture_type
        self.resolution: Tuple[int, int] = resolution
        self.fps: float = fps
        self.width, self.height = resolution

        # Initialize capture instances based on type
        self.picam2: Optional[Picamera2] = picam2
        self.pihq_camera: Optional[PiHQCamera] = None
        self.picamera2_highfps: Optional[Picamera2HighFpsCapture] = None
        self.rpicam_vid: Optional[RpicamVidCapture] = None
        self.playerone_camera: Optional[PlayerOneCamera] = playerone_camera
        self._playerone_camera_owned: bool = False

        self._recording: bool = False
        self._recorded_frames: List[np.ndarray] = []
        self._video_output_path: Optional[str] = None

        # Initialize based on capture type
        self._initialize_capture()
    
    def _initialize_capture(self) -> None:
        """Initialize the appropriate capture instance based on capture_type."""
        if "Picamera2 (Grayscale - High FPS)" in self.capture_type:
            # High-FPS grayscale mode using Picamera2 directly
            # Use existing picam2 instance if provided (will stop and reconfigure it)
            # Otherwise create new instance
            self.picamera2_highfps = Picamera2HighFpsCapture(
                width=self.width,
                height=self.height,
                fps=int(self.fps),
                picam2=self.picam2  # Pass existing instance if available
            )
            if not self.picamera2_highfps.start_capture():
                logger.error("Failed to start Picamera2 high-FPS capture")
                raise RuntimeError("Picamera2 high-FPS capture failed to start")
            # Store reference to picam2 instance
            self.picam2 = self.picamera2_highfps.picam2
        elif "rpicam-vid (Grayscale - High FPS)" in self.capture_type:
            # High-FPS grayscale mode using rpicam-vid subprocess
            self.rpicam_vid = RpicamVidCapture(
                width=self.width,
                height=self.height,
                fps=int(self.fps)
            )
            if not self.rpicam_vid.start_capture():
                logger.error("Failed to start rpicam-vid capture")
                raise RuntimeError("rpicam-vid capture failed to start")
        elif "Player One" in self.capture_type:
            # Player One (Mars 662M etc.) via SDK - grayscale only
            if self.playerone_camera is None:
                self.playerone_camera = PlayerOneCamera(
                    resolution=self.resolution,
                    fps=self.fps
                )
                self._playerone_camera_owned = True
            else:
                self.playerone_camera.preset_resolution = self.resolution
                self.playerone_camera.fps = self.fps
                self._playerone_camera_owned = False
            logger.info("Initialized Player One (Grayscale) capture")
        else:
            # Picamera2 modes (Color or Grayscale)
            grayscale = "Grayscale" in self.capture_type
            
            # Use existing picam2 if provided, otherwise create new one
            if self.picam2 is None:
                self.picam2 = Picamera2()
                create_new_picam2 = True
            else:
                create_new_picam2 = False
                logger.info(f"Using existing Picamera2 instance for {self.capture_type} capture")
            
            # Create PiHQCamera wrapper
            # Note: If using existing picam2, we need to configure it for capture
            if create_new_picam2:
                self.pihq_camera = PiHQCamera(
                    resolution=self.resolution,
                    grayscale=grayscale
                )
                self.pihq_camera.start()
            else:
                # Use existing picam2 - create a minimal wrapper or use directly
                # For now, we'll create PiHQCamera but it will use the existing picam2
                # Actually, PiHQCamera creates its own picam2, so we need a different approach
                # Let's just store the picam2 and use it directly for capture operations
                self.pihq_camera = None  # We'll use picam2 directly
                logger.info(f"Using existing Picamera2 instance for {self.capture_type} capture (no PiHQCamera wrapper)")
            
            logger.info(f"Initialized {self.capture_type} capture")
    
    def capture_image(self, output_path: Optional[str] = None) -> bool:
        """
        Capture a single image and save to file.
        
        Args:
            output_path: Path to save image. If None, generates timestamped filename.
            
        Returns:
            True if successful, False otherwise
        """
        if output_path is None:
            timestamp = time.strftime('%Y%m%d_%H%M%S')
            ext = ".png"
            output_path = f"capture_{timestamp}{ext}"
        
        try:
            # Determine format from file extension
            ext = os.path.splitext(output_path)[1].lower()
            is_jpeg = ext in ['.jpg', '.jpeg']
            
            if self.picamera2_highfps is not None:
                # Capture single frame from Picamera2 high-FPS
                frame = self.picamera2_highfps.read_frame()
                if frame is None:
                    logger.error("Failed to read frame from Picamera2 high-FPS")
                    return False
                # Save with appropriate format
                if is_jpeg:
                    # JPEG with quality 95
                    cv2.imwrite(output_path, frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
                else:
                    # PNG (default)
                    cv2.imwrite(output_path, frame)
                logger.info(f"Saved image: {output_path}")
                return True
            elif self.playerone_camera is not None:
                # Capture single frame from Player One camera
                frame = self.playerone_camera.read_frame()
                if frame is None:
                    logger.error("Failed to read frame from Player One camera")
                    return False
                if is_jpeg:
                    cv2.imwrite(output_path, frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
                else:
                    cv2.imwrite(output_path, frame)
                logger.info(f"Saved image: {output_path}")
                return True
            elif self.rpicam_vid is not None:
                # Capture single frame from rpicam-vid
                frame = self.rpicam_vid.read_frame()
                if frame is None:
                    logger.error("Failed to read frame from rpicam-vid")
                    return False
                # Save with appropriate format
                if is_jpeg:
                    # JPEG with quality 95
                    cv2.imwrite(output_path, frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
                else:
                    # PNG (default)
                    cv2.imwrite(output_path, frame)
                logger.info(f"Saved image: {output_path}")
                return True
            else:
                # Use Picamera2
                if self.pihq_camera is not None:
                    # PiHQCamera uses capture_file which supports formats based on extension
                    self.pihq_camera.take_photo_and_save(output_path)
                elif self.picam2 is not None:
                    # Use picam2 directly - capture_file supports formats based on extension
                    self.picam2.capture_file(output_path)
                else:
                    logger.error("Picamera2 not initialized")
                    return False
                logger.info(f"Saved image: {output_path}")
                return True
        except Exception as e:
            logger.error(f"Error capturing image: {e}")
            return False
    
    def start_video_recording(self, output_path: Optional[str] = None,
                            codec: str = "FFV1") -> bool:
        """
        Start recording video.
        
        Args:
            output_path: Path to save video. If None, generates timestamped filename.
            codec: Video codec ("FFV1" for lossless, "PNG" for PNG codec)
            
        Returns:
            True if successful, False otherwise
        """
        if self._recording:
            logger.warning("Already recording")
            return False
        
        if output_path is None:
            timestamp = time.strftime('%Y%m%d_%H%M%S')
            if codec == "FFV1" or codec == "PNG":
                ext = ".avi"
            else:
                ext = ".h264"
            output_path = f"video_{timestamp}{ext}"
        
        self._video_output_path = output_path
        self._recording = True
        
        try:
            if self.picamera2_highfps is not None:
                # Start frame buffering for Picamera2 high-FPS
                self._recorded_frames = []
                self.picamera2_highfps.start_recording()
                logger.info(f"Started Picamera2 high-FPS recording: {output_path}")
                return True
            elif self.rpicam_vid is not None:
                # Start frame buffering for rpicam-vid
                self._recorded_frames = []
                self.rpicam_vid.start_recording()
                logger.info(f"Started rpicam-vid recording: {output_path}")
                return True
            elif self.playerone_camera is not None:
                self._recorded_frames = []
                logger.info(f"Started Player One recording: {output_path}")
                return True
            else:
                # Use Picamera2
                if self.pihq_camera is not None:
                    # Use PiHQCamera wrapper
                    self.pihq_camera.start_recording_video(output_path, fps=self.fps)
                elif self.picam2 is not None:
                    # Use picam2 directly with H264Encoder
                    from picamera2.encoders import H264Encoder
                    from picamera2.outputs import FileOutput
                    encoder = H264Encoder(bitrate=50_000_000, fps=self.fps)
                    output = FileOutput(output_path)
                    self.picam2.start_recording(encoder, output)
                else:
                    logger.error("Picamera2 not initialized")
                    return False
                logger.info(f"Started Picamera2 recording: {output_path}")
                return True
        except Exception as e:
            logger.error(f"Error starting video recording: {e}")
            self._recording = False
            return False
    
    def capture_frame_for_video(self) -> bool:
        """
        Capture a frame during video recording (for raspividyuv mode).
        
        Returns:
            True if frame captured successfully, False otherwise
        """
        if not self._recording:
            return False
        
        if self.picamera2_highfps is not None:
            frame = self.picamera2_highfps.read_frame()
            if frame is not None:
                self._recorded_frames.append(frame.copy())
                return True
            return False
        elif self.rpicam_vid is not None:
            frame = self.rpicam_vid.read_frame()
            if frame is not None:
                self._recorded_frames.append(frame.copy())
                return True
            return False
        elif self.playerone_camera is not None:
            frame = self.playerone_camera.read_frame()
            if frame is not None:
                self._recorded_frames.append(frame.copy())
                return True
            return False
        # For Picamera2, frames are automatically recorded
        return True
    
    def stop_video_recording(self, codec: str = "FFV1") -> Optional[str]:
        """
        Stop video recording and save file.
        
        Args:
            codec: Video codec for encoding (for raspividyuv mode)
            
        Returns:
            Path to saved video file, or None if error
        """
        if not self._recording:
            logger.warning("Not recording")
            return None
        
        self._recording = False
        
        try:
            if self.picamera2_highfps is not None:
                # Stop recording and encode frames to video (Picamera2 high-FPS)
                self.picamera2_highfps.stop_recording()
                
                if not self._recorded_frames:
                    logger.warning("No frames recorded")
                    return None
                
                # Use frames from buffer
                self.picamera2_highfps.frames = self._recorded_frames.copy()
                
                # Save frames to video
                success = self.picamera2_highfps.save_frames_to_video(
                    self._video_output_path,
                    fps=self.fps,
                    codec=codec
                )
                
                if success:
                    logger.info(f"Saved video: {self._video_output_path}")
                    return self._video_output_path
                else:
                    logger.error("Failed to save video")
                    return None
            elif self.rpicam_vid is not None:
                # Stop recording and encode frames to video (rpicam-vid)
                self.rpicam_vid.stop_recording()

                if not self._recorded_frames:
                    logger.warning("No frames recorded")
                    return None

                # Use frames from buffer
                self.rpicam_vid.frames = self._recorded_frames.copy()

                # Save frames to video
                success = self.rpicam_vid.save_frames_to_video(
                    self._video_output_path,
                    fps=self.fps,
                    codec=codec
                )

                if success:
                    logger.info(f"Saved video: {self._video_output_path}")
                    return self._video_output_path
                else:
                    logger.error("Failed to save video")
                    return None
            elif self.playerone_camera is not None:
                # Encode buffered frames to video (Player One)
                if not self._recorded_frames:
                    logger.warning("No frames recorded")
                    return None
                w, h = self.width, self.height
                is_color = self._recorded_frames[0].ndim == 3
                fourcc = cv2.VideoWriter_fourcc(*("FFV1" if codec == "FFV1" else "MJPG"))
                writer = cv2.VideoWriter(self._video_output_path, fourcc, self.fps, (w, h), is_color)
                if not writer.isOpened():
                    logger.error("Failed to open VideoWriter for recording")
                    return None
                for frame in self._recorded_frames:
                    writer.write(frame)
                writer.release()
                logger.info(f"Saved video: {self._video_output_path}")
                return self._video_output_path
            else:
                # Stop Picamera2 recording
                if self.pihq_camera is not None:
                    self.pihq_camera.stop_recording_video()
                elif self.picam2 is not None:
                    self.picam2.stop_recording()
                else:
                    logger.error("Picamera2 not initialized")
                    return None
                logger.info(f"Stopped recording: {self._video_output_path}")
                return self._video_output_path
        except Exception as e:
            logger.error(f"Error stopping video recording: {e}")
            return None
    
    def is_recording(self) -> bool:
        """Check if currently recording video."""
        return self._recording
    
    def get_capture_type(self) -> str:
        """Get current capture type."""
        return self.capture_type
    
    def set_capture_type(self, capture_type: str) -> bool:
        """
        Change capture type (requires reinitialization).
        
        Args:
            capture_type: New capture type from CAPTURE_TYPES
            
        Returns:
            True if successful, False otherwise
        """
        if capture_type not in self.CAPTURE_TYPES:
            logger.error(f"Invalid capture type: {capture_type}")
            return False
        
        if capture_type == self.capture_type:
            return True  # Already set
        
        # Stop current capture
        self.cleanup()
        
        # Set new type
        self.capture_type = capture_type
        
        # Reinitialize
        try:
            self._initialize_capture()
            return True
        except Exception as e:
            logger.error(f"Failed to switch capture type: {e}")
            return False
    
    def set_resolution(self, width: int, height: int) -> bool:
        """
        Set capture resolution (requires reinitialization).
        
        Args:
            width: Frame width
            height: Frame height
            
        Returns:
            True if successful, False otherwise
        """
        if self._recording:
            logger.error("Cannot change resolution while recording")
            return False
        
        self.resolution = (width, height)
        self.width = width
        self.height = height
        
        # Reinitialize
        self.cleanup()
        try:
            self._initialize_capture()
            return True
        except Exception as e:
            logger.error(f"Failed to set resolution: {e}")
            return False
    
    def set_fps(self, fps: float) -> None:
        """
        Set target frames per second.
        
        Args:
            fps: Target FPS
        """
        self.fps = fps
        # Note: For high-FPS modes, FPS is set at initialization
        # For Picamera2 standard modes, FPS can be set in video configuration
    
    def cleanup(self) -> None:
        """Clean up capture resources."""
        if self._recording:
            self.stop_video_recording()
        
        if self.picamera2_highfps is not None:
            self.picamera2_highfps.stop_capture()
            self.picamera2_highfps = None
        
        if self.rpicam_vid is not None:
            self.rpicam_vid.stop_capture()
            self.rpicam_vid = None
        
        if self.pihq_camera is not None:
            try:
                self.pihq_camera.picam2.stop()
            except:
                pass
            self.pihq_camera = None
        
        if self.picam2 is not None:
            try:
                self.picam2.stop()
            except Exception:
                pass
            self.picam2 = None

        if self.playerone_camera is not None and getattr(self, "_playerone_camera_owned", True):
            try:
                self.playerone_camera.release()
            except Exception:
                pass
            self.playerone_camera = None

        self._recorded_frames = []

