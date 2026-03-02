"""
Tkinter Preview Widget - Embedded Camera Preview in Tkinter Window

Provides a tkinter Canvas widget that displays live camera preview frames
captured from Picamera2. Optimized for fast refresh rates.

Author: RoboCam-Suite
"""

import threading
import time
from typing import Optional, Tuple
import numpy as np
from picamera2 import Picamera2
from robocam.logging_config import get_logger

logger = get_logger(__name__)

# Try to import PIL Image and ImageTk
try:
    from PIL import Image, ImageTk
except ImportError as e:
    logger.error(f"Failed to import PIL ImageTk: {e}")
    logger.error("Pillow with tkinter support is required. Please install:")
    logger.error("  pip install Pillow")
    logger.error("Or on Debian/Ubuntu: sudo apt-get install python3-pil.imagetk")
    raise ImportError(
        "PIL.ImageTk is not available. Please install Pillow with tkinter support:\n"
        "  pip install Pillow\n"
        "Or on Debian/Ubuntu: sudo apt-get install python3-pil.imagetk"
    ) from e


class TkinterPreviewWidget:
    """
    Tkinter widget for displaying live camera preview.
    
    Captures frames from Picamera2 and displays them in a tkinter Canvas widget.
    Optimized for fast refresh rates using threading and efficient frame conversion.
    
    Attributes:
        canvas (tk.Canvas): Tkinter canvas widget for displaying preview
        picam2 (Picamera2): Picamera2 camera instance
        width (int): Preview width
        height (int): Preview height
        running (bool): Whether preview is running
        photo_image (Optional[ImageTk.PhotoImage]): Current PhotoImage for display
        update_interval (float): Time between frame updates (seconds)
        _thread (Optional[threading.Thread]): Thread for frame capture loop
        _lock (threading.Lock): Lock for thread-safe frame updates
    """
    
    def __init__(
        self,
        canvas: 'tk.Canvas',
        picam2: Picamera2,
        width: int = 800,
        height: int = 600,
        fps: float = 30.0,
        update_interval: Optional[float] = None,
        grayscale: bool = False
    ):
        """
        Initialize Tkinter preview widget.
        
        Args:
            canvas: Tkinter Canvas widget to display preview in
            picam2: Picamera2 camera instance (must be configured and started)
            width: Preview display width
            height: Preview display height
            fps: Target frames per second (used to calculate update interval if not provided)
            update_interval: Time between frame updates in seconds (defaults to 1/fps)
            grayscale: If True, convert frames to grayscale for display
        """
        self.canvas: 'tk.Canvas' = canvas
        self.picam2: Picamera2 = picam2
        self.width: int = width
        self.height: int = height
        self.grayscale: bool = grayscale
        self.running: bool = False
        self.photo_image: Optional[ImageTk.PhotoImage] = None
        self._thread: Optional[threading.Thread] = None
        self._lock: threading.Lock = threading.Lock()
        
        # Calculate update interval (target ~30 FPS for smooth preview)
        if update_interval is None:
            # Cap at 30 FPS for preview to avoid overwhelming tkinter
            target_fps = min(fps, 30.0)
            self.update_interval: float = 1.0 / target_fps
        else:
            self.update_interval = update_interval
        
        # Store image ID for canvas update
        self._image_id: Optional[int] = None
        
    def start(self) -> None:
        """Start the preview update loop."""
        if self.running:
            logger.warning("Preview already running")
            return
        
        self.running = True
        self._thread = threading.Thread(target=self._update_loop, daemon=True)
        self._thread.start()
        logger.info(f"Tkinter preview started (update interval: {self.update_interval:.3f}s)")
    
    def stop(self) -> None:
        """Stop the preview update loop."""
        if not self.running:
            return
        
        self.running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        logger.info("Tkinter preview stopped")
    
    def set_grayscale(self, grayscale: bool) -> None:
        """Update grayscale mode without recreating the widget."""
        self.grayscale = grayscale
        logger.info(f"Preview grayscale mode set to: {grayscale}")
    
    def _update_loop(self) -> None:
        """Main update loop running in separate thread."""
        while self.running:
            try:
                start_time = time.time()
                
                # Capture frame from camera
                frame = self._capture_frame()
                if frame is not None:
                    # Update display in main thread
                    self.canvas.after(0, self._update_display, frame)
                
                # Sleep to maintain target FPS
                elapsed = time.time() - start_time
                sleep_time = max(0, self.update_interval - elapsed)
                if sleep_time > 0:
                    time.sleep(sleep_time)
                    
            except Exception as e:
                logger.error(f"Error in preview update loop: {e}")
                # Continue loop even on error
                time.sleep(0.1)
    
    def _capture_frame(self) -> Optional[np.ndarray]:
        """
        Capture a frame from Picamera2.
        
        Returns:
            Frame as numpy array (RGB, uint8), or None if capture failed
        """
        try:
            # Capture array from main stream
            array = self.picam2.capture_array("main")
            
            # Convert to RGB if needed (Picamera2 may return different formats)
            if array.ndim == 2:
                # Grayscale (2D) - convert to RGB by stacking
                array = np.stack([array, array, array], axis=-1)
            elif array.ndim == 3:
                if array.shape[2] == 4:
                    # RGBA - convert to RGB
                    array = array[:, :, :3]
                elif array.shape[2] == 1:
                    # Single channel (3D with 1 channel) - convert to RGB
                    array = np.stack([array[:, :, 0], array[:, :, 0], array[:, :, 0]], axis=-1)
                elif array.shape[2] == 3:
                    # RGB format - check if we need to convert to grayscale
                    if self.grayscale:
                        # Convert RGB to grayscale using standard weights
                        # Formula: gray = 0.2989*R + 0.5870*G + 0.1140*B
                        gray = np.dot(array[...,:3], [0.2989, 0.5870, 0.1140]).astype(np.uint8)
                        # Convert back to RGB for display (3 channels, same values)
                        array = np.stack([gray, gray, gray], axis=-1)
                    # Otherwise, keep as RGB
                else:
                    # Unknown format - try to extract first channel
                    logger.warning(f"Unexpected array shape: {array.shape}")
                    if array.shape[2] > 0:
                        array = np.stack([array[:, :, 0], array[:, :, 0], array[:, :, 0]], axis=-1)
            else:
                logger.error(f"Unexpected array dimensions: {array.ndim}")
                return None
            
            # Ensure uint8
            if array.dtype != np.uint8:
                if array.max() <= 1.0:
                    array = (array * 255).astype(np.uint8)
                else:
                    array = array.astype(np.uint8)
            
            return array
            
        except Exception as e:
            logger.error(f"Error capturing frame: {e}")
            return None
    
    def _update_display(self, frame: np.ndarray) -> None:
        """
        Update the canvas display with a new frame.
        
        This method runs in the main thread (called via canvas.after).
        
        Args:
            frame: Frame as numpy array (RGB, uint8)
        """
        try:
            # Resize frame to fit canvas if needed
            canvas_width = self.canvas.winfo_width()
            canvas_height = self.canvas.winfo_height()
            
            # Use actual canvas size if available, otherwise use configured size
            if canvas_width > 1 and canvas_height > 1:
                display_width = canvas_width
                display_height = canvas_height
            else:
                display_width = self.width
                display_height = self.height
            
            # Resize frame to fit display size
            if frame.shape[1] != display_width or frame.shape[0] != display_height:
                pil_image = Image.fromarray(frame)
                pil_image = pil_image.resize((display_width, display_height), Image.Resampling.LANCZOS)
            else:
                pil_image = Image.fromarray(frame)
            
            # Convert to PhotoImage
            photo = ImageTk.PhotoImage(image=pil_image)
            
            # Store reference to prevent garbage collection
            with self._lock:
                self.photo_image = photo
            
            # Update canvas
            if self._image_id is None:
                # Create image item if it doesn't exist
                self._image_id = self.canvas.create_image(
                    display_width // 2,
                    display_height // 2,
                    image=photo,
                    anchor='center'
                )
            else:
                # Update existing image item
                self.canvas.itemconfig(self._image_id, image=photo)
                # Update canvas position if size changed
                self.canvas.coords(
                    self._image_id,
                    display_width // 2,
                    display_height // 2
                )
            
        except Exception as e:
            logger.error(f"Error updating display: {e}")

