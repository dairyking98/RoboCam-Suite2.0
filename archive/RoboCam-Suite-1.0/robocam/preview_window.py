"""
Preview Window - Hardware-Optimized Native Preview with Capture Settings

Provides a separate window with hardware-accelerated native preview (DRM/QTGL)
and capture settings. Uses native Picamera2 preview for maximum performance.

Author: RoboCam-Suite
"""

import tkinter as tk
from tkinter import ttk
from typing import Optional, Tuple
from datetime import datetime
import os
import time
import threading
import subprocess as sp
import numpy as np
import atexit

# PIL.ImageTk required for Player One / external camera preview (convert frames to tkinter PhotoImage)
try:
    from PIL import Image, ImageTk
except ImportError as e:
    raise ImportError(
        "PIL.ImageTk is not available (needed for Player One camera preview).\n"
        "Install Pillow and ensure tkinter is available:\n"
        "  1. pip install --upgrade Pillow\n"
        "  2. Test tkinter: python -c \"import tkinter\"\n"
        "  3. If it still fails, reinstall Python with 'tcl/tk and IDLE' checked."
    ) from e

from robocam.capture_interface import CaptureManager
from robocam.camera_preview import FPSTracker, start_best_preview
from robocam.logging_config import get_logger
from robocam.resolution_presets import (
    get_capture_resolution_presets,
    format_resolution_option,
    parse_resolution_option,
    resolution_to_preset_option,
)

logger = get_logger(__name__)


class PreviewWindow:
    """
    Separate window for hardware-optimized camera preview and capture settings.
    
    Uses native Picamera2 preview (DRM/QTGL) for maximum performance.
    For grayscale mode, shows a captured image preview instead of live preview.
    
    Attributes:
        window (tk.Toplevel): The preview window
        capture_manager (Optional[CaptureManager]): Capture manager instance
        picam2: Picamera2 instance
        _recording (bool): Whether currently recording video
        _native_preview_active (bool): Whether native preview is active
        _preview_backend (Optional[str]): Active preview backend name
    """
    
    def __init__(
        self,
        parent: tk.Tk,
        picam2=None,
        capture_manager: Optional[CaptureManager] = None,
        initial_resolution: Tuple[int, int] = (800, 600),
        initial_fps: float = 30.0,
        simulate_cam: bool = False,
        usb_camera=None,
    ):
        """
        Initialize preview window.

        Args:
            parent: Parent tkinter window
            picam2: Optional Picamera2 camera instance (Pi HQ). If None and usb_camera is None, created automatically.
            capture_manager: Optional CaptureManager instance. If None, created from picam2 or usb_camera.
            initial_resolution: Initial preview resolution (width, height)
            initial_fps: Initial preview FPS
            simulate_cam: If True, run in camera simulation mode
            usb_camera: Optional camera instance (Player One). Used when Pi HQ is not present.
        """
        self.parent = parent
        self._simulate_cam = simulate_cam
        self._native_preview_active = False
        self._preview_backend: Optional[str] = None
        self._measuring_fps = False
        self.usb_camera = usb_camera
        self._usb_preview_job: Optional[str] = None  # after() id for external camera preview loop

        # Use first camera found: Pi HQ or Player One (only one in system at a time)
        if usb_camera is not None:
            self.picam2 = None
            logger.info("PreviewWindow: Using Player One camera")
        elif picam2 is not None:
            self.picam2 = picam2
        elif not simulate_cam:
            # No camera passed: detect and create (used by calibrate.py)
            from robocam.camera_backend import detect_camera
            backend = detect_camera()
            if backend == "pihq":
                from picamera2 import Picamera2
                self.picam2 = Picamera2()
                self.picam2_config = self.picam2.create_preview_configuration(
                    main={"size": initial_resolution},
                    controls={"FrameRate": initial_fps},
                    buffer_count=2
                )
                self.picam2.configure(self.picam2_config)
                try:
                    self.picam2.start()
                    logger.info("PreviewWindow: Created and started Picamera2 instance")
                except Exception as e:
                    logger.error(f"PreviewWindow: Failed to start camera: {e}")
                    self.picam2 = None
            elif isinstance(backend, tuple) and backend[0] == "playerone":
                from robocam.playerone_camera import PlayerOneCamera
                po_index = backend[1]
                self.usb_camera = PlayerOneCamera(
                    resolution=initial_resolution,
                    fps=initial_fps,
                    camera_index=po_index
                )
                self.picam2 = None
                logger.info("PreviewWindow: Created and started Player One camera instance (index %d)", po_index)
            else:
                self.picam2 = None
                logger.warning("PreviewWindow: No camera found")
        else:
            self.picam2 = picam2

        # Create capture manager if not provided
        if capture_manager is None and not simulate_cam:
            if self.usb_camera is not None:
                try:
                    self.capture_manager = CaptureManager(
                        capture_type="Player One (Grayscale)",
                        resolution=initial_resolution,
                        fps=initial_fps,
                        playerone_camera=self.usb_camera
                    )
                    logger.info("PreviewWindow: Created CaptureManager (Player One)")
                except Exception as e:
                    logger.warning(f"PreviewWindow: Failed to create capture manager: {e}")
                    self.capture_manager = None
            elif self.picam2 is not None:
                try:
                    self.capture_manager = CaptureManager(
                        capture_type="Picamera2 (Color)",
                        resolution=initial_resolution,
                        fps=initial_fps,
                        picam2=self.picam2
                    )
                    logger.info("PreviewWindow: Created CaptureManager")
                except Exception as e:
                    logger.warning(f"PreviewWindow: Failed to create capture manager: {e}")
                    self.capture_manager = None
            else:
                self.capture_manager = None
        else:
            self.capture_manager = capture_manager
        
        self._recording: bool = False
        self.fps_tracker: Optional[FPSTracker] = None
        self._running: bool = True
        self._fps_checked = False  # Track if FPS has been checked
        self._measured_fps: Optional[float] = None  # Store measured FPS value
        
        # Create window
        self.window = tk.Toplevel(parent)
        self.window.title("Camera Preview & Capture Settings")
        self.window.protocol("WM_DELETE_WINDOW", self.on_close)
        
        # Create main frame - only settings, no preview embedded
        main_frame = tk.Frame(self.window)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Settings frame (no preview area in tkinter - preview is separate native window)
        settings_frame = tk.LabelFrame(main_frame, text="Capture Settings", padx=5, pady=5)
        settings_frame.pack(fill=tk.BOTH, expand=True, padx=5)
        
        # Preview status label (info only, not actual preview)
        preview_status_frame = tk.LabelFrame(main_frame, text="Preview Status", padx=5, pady=5)
        preview_status_frame.pack(fill=tk.X, padx=5, pady=5)
        
        self.preview_info_label = tk.Label(
            preview_status_frame,
            text="Native preview opens in separate window",
            font=("Arial", 9),
            fg="gray",
            justify=tk.LEFT
        )
        self.preview_info_label.pack(anchor="w", padx=5, pady=5)
        
        # Grayscale preview canvas (shown when in grayscale mode - for captured image only)
        self.grayscale_canvas = tk.Canvas(
            preview_status_frame,
            width=min(initial_resolution[0], 400),
            height=min(initial_resolution[1], 300),
            bg="black",
            highlightthickness=1,
            highlightbackground="gray"
        )
        self.grayscale_image_id = None
        # Canvas is hidden by default, only shown for grayscale captured images
        
        # Capture Type (Player One backend shows only Player One type)
        tk.Label(settings_frame, text="Capture Type:").grid(row=0, column=0, sticky="w", padx=2, pady=2)
        if self.usb_camera is not None:
            capture_types = CaptureManager.CAPTURE_TYPES_PLAYERONE
            default_type = "Player One (Grayscale)"
        else:
            capture_types = CaptureManager.CAPTURE_TYPES
            default_type = "Picamera2 (Color)"
        self.capture_type_var = tk.StringVar(value=default_type)
        if capture_manager:
            capture_type_menu = tk.OptionMenu(
                settings_frame,
                self.capture_type_var,
                *capture_types,
                command=self.on_capture_type_change
            )
        else:
            capture_type_menu = tk.OptionMenu(
                settings_frame,
                self.capture_type_var,
                *capture_types
            )
        capture_type_menu.grid(row=0, column=1, sticky="w", padx=2, pady=2)
        
        # Resolution (native presets only)
        is_pihq = self.usb_camera is None
        is_playerone = self.usb_camera is not None and type(self.usb_camera).__name__ == "PlayerOneCamera"
        self._resolution_presets = get_capture_resolution_presets(is_pihq, is_playerone)
        self._resolution_options = [format_resolution_option(w, h) for w, h in self._resolution_presets]
        initial_opt = resolution_to_preset_option(initial_resolution, self._resolution_presets)
        self.resolution_var = tk.StringVar(value=initial_opt)
        tk.Label(settings_frame, text="Resolution:").grid(row=1, column=0, sticky="w", padx=2, pady=2)
        resolution_menu = tk.OptionMenu(
            settings_frame,
            self.resolution_var,
            *self._resolution_options,
            command=lambda _: self.on_settings_change()
        )
        resolution_menu.grid(row=1, column=1, sticky="w", padx=2, pady=2)
        
        # FPS
        tk.Label(settings_frame, text="Target FPS:").grid(row=2, column=0, sticky="w", padx=2, pady=2)
        self.fps_var = tk.StringVar(value=str(initial_fps))
        fps_entry = tk.Entry(settings_frame, textvariable=self.fps_var, width=10)
        fps_entry.grid(row=2, column=1, sticky="w", padx=2, pady=2)
        fps_entry.bind("<KeyRelease>", self.on_settings_change)
        
        # Capture Mode
        tk.Label(settings_frame, text="Mode:").grid(row=3, column=0, sticky="w", padx=2, pady=2)
        self.capture_mode_var = tk.StringVar(value="Image")
        capture_mode_menu = tk.OptionMenu(settings_frame, self.capture_mode_var, "Image", "Video")
        capture_mode_menu.grid(row=3, column=1, sticky="w", padx=2, pady=2)
        
        # Image Format (only for Image mode)
        tk.Label(settings_frame, text="Format:").grid(row=4, column=0, sticky="w", padx=2, pady=2)
        self.image_format_var = tk.StringVar(value="PNG")
        format_menu = tk.OptionMenu(settings_frame, self.image_format_var, "PNG", "JPEG")
        format_menu.grid(row=4, column=1, sticky="w", padx=2, pady=2)
        
        # Quick Capture Button
        self.quick_capture_btn = tk.Button(
            settings_frame,
            text="Quick Capture",
            command=self.on_quick_capture,
            width=15,
            bg="#2196F3",
            fg="white"
        )
        self.quick_capture_btn.grid(row=5, column=0, columnspan=2, padx=2, pady=10, sticky="ew")
        
        # Measure FPS Button
        self.measure_fps_btn = tk.Button(
            settings_frame,
            text="Measure FPS",
            command=self.on_measure_fps,
            width=15,
            bg="#4CAF50",
            fg="white"
        )
        self.measure_fps_btn.grid(row=6, column=0, columnspan=2, padx=2, pady=5, sticky="ew")
        
        # Preview FPS label
        tk.Label(settings_frame, text="Preview FPS:").grid(row=7, column=0, sticky="w", padx=2, pady=2)
        self.fps_label = tk.Label(settings_frame, text="0.0", font=("Courier", 10))
        self.fps_label.grid(row=7, column=1, sticky="w", padx=2, pady=2)
        
        # Status label
        self.status_label = tk.Label(
            settings_frame,
            text="Ready",
            fg="gray",
            font=("Arial", 9),
            wraplength=200
        )
        self.status_label.grid(row=9, column=0, columnspan=2, padx=2, pady=5, sticky="w")
        
        # Initialize FPS tracking if camera is available (Pi HQ or Player One)
        if (self.picam2 is not None or self.usb_camera is not None) and not self._simulate_cam:
            self.fps_tracker = FPSTracker()
            if self.picam2 is not None:
                # Set up frame callback for FPS tracking (Pi HQ)
                def frame_callback(request):
                    if self.fps_tracker:
                        self.fps_tracker.update()
                self.picam2.post_callback = frame_callback
        
        # Defer preview start to allow window to fully initialize
        # This prevents issues with preview backends that need a fully rendered window
        # Preview will start after FPS check if user clicks "Measure FPS", otherwise starts normally
        def start_preview_after_init():
            """Start preview after window is fully initialized."""
            self.window.update_idletasks()  # Ensure window is rendered
            time.sleep(0.1)  # Brief additional wait
            # Only auto-start if FPS hasn't been checked yet
            # If FPS check happens, preview will start after measurement completes
            if not self._fps_checked:
                # Start native preview (if not grayscale)
                self.update_preview()
        
        # Schedule preview start after window initialization
        self.window.after(100, start_preview_after_init)
        
        # Start FPS update loop
        self.update_fps()
    
    def update_fps(self) -> None:
        """Update FPS display from fps_tracker."""
        if self.fps_tracker is not None:
            fps = self.fps_tracker.get_fps()
            self.fps_label.config(text=f"{fps:.1f}")
        else:
            self.fps_label.config(text="0.0")
        
        # Schedule next update (every 200ms = 5 Hz update rate)
        if self._running:
            self.window.after(200, self.update_fps)
    
    def on_capture_type_change(self, capture_type: str) -> None:
        """Handle capture type change."""
        if self.capture_manager:
            try:
                success = self.capture_manager.set_capture_type(capture_type)
                if success:
                    self.status_label.config(text=f"Switched to {capture_type}", fg="green")
                    # Update preview based on capture type
                    self.update_preview()
                else:
                    self.status_label.config(text="Failed to switch capture type", fg="red")
            except Exception as e:
                self.status_label.config(text=f"Error: {e}", fg="red")
                logger.error(f"Error changing capture type: {e}")
    
    def get_resolution(self) -> Tuple[int, int]:
        """Return current capture resolution (width, height) from preset dropdown."""
        parsed = parse_resolution_option(self.resolution_var.get())
        if parsed is not None:
            return parsed
        if self._resolution_presets:
            return self._resolution_presets[0]
        return (800, 600)

    def on_settings_change(self, event=None) -> None:
        """Handle settings change (resolution, FPS)."""
        # Update preview when settings change
        self.update_preview()
    
    def update_preview(self) -> None:
        """Update preview based on current settings and capture type."""
        if (self.picam2 is None and self.usb_camera is None) or self._simulate_cam:
            return

        try:
            if self.usb_camera is not None:
                # Player One / external camera: live preview in canvas
                self._stop_native_preview()
                self._stop_usb_preview()
                self._hide_grayscale_preview()
                self.grayscale_canvas.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
                self._start_usb_preview()
                return

            # Pi HQ camera
            current_capture_type = self.capture_type_var.get()
            is_grayscale = "Grayscale" in current_capture_type

            if is_grayscale:
                self._stop_native_preview()
                self._show_grayscale_preview()
            else:
                self._hide_grayscale_preview()
                self._start_native_preview()

        except Exception as e:
            logger.error(f"Error updating preview: {e}")
            self.status_label.config(text=f"Preview error: {e}", fg="red")
    
    def _start_native_preview(self) -> None:
        """Start native hardware-accelerated preview."""
        if self._native_preview_active or self.picam2 is None:
            return
        
        try:
            # Get current resolution and FPS
            try:
                res_x, res_y = self.get_resolution()
                fps = float(self.fps_var.get().strip())
            except ValueError:
                res_x, res_y = self.get_resolution()
                fps = 30.0
            
            # Check if camera is already started and configured
            camera_ready = False
            if hasattr(self.picam2, 'started') and self.picam2.started:
                # Camera is already started - check if we need to reconfigure
                try:
                    # Try to check current config - if it matches, don't reconfigure
                    current_config = getattr(self.picam2, 'camera_config', None)
                    if current_config:
                        # Camera already running - only reconfigure if settings changed
                        main_config = current_config.get('main', {})
                        current_size = main_config.get('size')
                        if current_size == (res_x, res_y):
                            # Same resolution, camera is ready
                            camera_ready = True
                            logger.info("Camera already configured correctly, skipping reconfiguration")
                except:
                    pass
            
            # Only reconfigure if needed
            if not camera_ready:
                # Stop camera if running
                try:
                    if hasattr(self.picam2, 'started') and self.picam2.started:
                        self.picam2.stop()
                        time.sleep(0.1)  # Brief pause after stopping
                except Exception as e:
                    logger.warning(f"Error stopping camera: {e}")
                
                # Configure and start camera
                try:
                    self.picam2_config = self.picam2.create_preview_configuration(
                        main={"size": (res_x, res_y)},
                        controls={"FrameRate": fps},
                        buffer_count=2
                    )
                    self.picam2.configure(self.picam2_config)
                    self.picam2.start()
                    logger.info(f"Camera configured: {res_x}x{res_y} @ {fps} FPS")
                except Exception as e:
                    logger.error(f"Failed to configure camera: {e}")
                    self.preview_info_label.config(
                        text=f"✗ Camera configuration error: {str(e)[:60]}...",
                        fg="red"
                    )
                    return
                
                # Give camera time to fully start before attempting preview
                time.sleep(0.2)  # Increased wait time for camera initialization
            
            # Stop any existing preview first (in case preview was already started)
            try:
                if hasattr(self.picam2, '_preview'):
                    # Check if preview is active
                    if self.picam2._preview is not None:
                        logger.info("Stopping existing preview before starting new one...")
                        self.picam2.stop_preview()
                        time.sleep(0.1)
            except Exception as e:
                logger.debug(f"Error checking for existing preview (likely none): {e}")
            
            # Ensure camera is in the right state for preview
            # Check if camera is actually started and ready
            if not hasattr(self.picam2, 'started') or not self.picam2.started:
                logger.warning("Camera not started, attempting to start...")
                try:
                    self.picam2.start()
                    time.sleep(0.2)  # Give it more time to initialize
                except Exception as e:
                    logger.error(f"Failed to start camera: {e}")
                    self.preview_info_label.config(
                        text=f"✗ Camera start failed: {str(e)[:60]}...",
                        fg="red"
                    )
                    return
            
            # Start native preview using the smart backend selection function
            # This function automatically detects desktop session and picks the best backend
            error_details = []
            try:
                self._preview_backend = start_best_preview(self.picam2, backend="auto")
                self._native_preview_active = True
                self.preview_info_label.config(
                    text=f"✓ Native preview active in separate window (Backend: {self._preview_backend.upper()})",
                    fg="green"
                )
                logger.info(f"Started native preview with backend: {self._preview_backend.upper()}")
            except RuntimeError as e:
                error_msg = str(e)
                error_details.append(f"Auto-selection: {error_msg}")
                logger.warning(f"start_best_preview failed: {error_msg}")
                
                # Try each backend individually with better error messages
                from picamera2 import Preview
                backends_to_try = [
                    ("DRM", Preview.DRM),
                    ("QTGL", Preview.QTGL),
                    ("NULL", Preview.NULL)
                ]
                
                preview_started = False
                for backend_name, backend_type in backends_to_try:
                    if preview_started:
                        break
                    try:
                        logger.info(f"Trying {backend_name} backend...")
                        self.picam2.start_preview(backend_type)
                        self._preview_backend = backend_name.lower()
                        self._native_preview_active = True
                        preview_started = True
                        logger.info(f"Successfully started {backend_name} preview")
                        
                        if backend_name == "NULL":
                            self.preview_info_label.config(
                                text=f"⚠ Preview unavailable (headless mode)\nCapture still works\n\nAll visual backends failed.\nErrors: {error_msg[:60]}",
                                fg="orange"
                            )
                        else:
                            self.preview_info_label.config(
                                text=f"✓ Native preview active (Backend: {backend_name})",
                                fg="green"
                            )
                    except Exception as be:
                        be_msg = str(be)
                        error_details.append(f"{backend_name}: {be_msg[:40]}")
                        logger.warning(f"{backend_name} backend failed: {be_msg}")
                
                if not preview_started:
                    # All preview backends failed - but we can still capture
                    error_summary = "\n".join(error_details[:3])  # Show first 3 errors
                    logger.error(f"All preview backends failed. Errors: {error_details}")
                    self.preview_info_label.config(
                        text=f"⚠ Preview unavailable\nCapture still works\n\nAll backends failed.\n{error_summary[:80]}...\n\nCheck display/camera connection.",
                        fg="orange"
                    )
                    self._native_preview_active = False
                    # Don't return - allow app to continue without preview
                    return
            except Exception as e:
                # Unexpected error
                error_msg = str(e)
                logger.error(f"Unexpected error starting preview: {error_msg}", exc_info=True)
                self.preview_info_label.config(
                    text=f"✗ Preview error: {error_msg[:80]}...\n\nCheck logs for details.",
                    fg="red"
                )
                self._native_preview_active = False
        except Exception as e:
            logger.error(f"Error starting native preview: {e}")
            self.preview_info_label.config(
                text=f"✗ Preview error: {str(e)[:60]}...",
                fg="red"
            )
    
    def _stop_native_preview(self) -> None:
        """Stop native preview."""
        if not self._native_preview_active:
            return

        try:
            if self.picam2 is not None:
                self.picam2.stop_preview()
            self._native_preview_active = False
            self._preview_backend = None
            logger.info("Stopped native preview")
        except Exception as e:
            logger.error(f"Error stopping native preview: {e}")

    def _stop_usb_preview(self) -> None:
        """Stop Player One / external camera preview loop."""
        if self._usb_preview_job is not None:
            try:
                self.window.after_cancel(self._usb_preview_job)
            except Exception:
                pass
            self._usb_preview_job = None
            logger.info("Stopped external camera preview")

    def _usb_preview_loop(self) -> None:
        """Read one frame from Player One / external camera and display in canvas; schedule next."""
        if not self._running or self.usb_camera is None or self.usb_camera.cap is None or not self.usb_camera.cap.isOpened():
            self._usb_preview_job = None
            return
        try:
            frame = self.usb_camera.read_frame()
            if frame is not None and self.grayscale_canvas.winfo_exists():
                if self.fps_tracker:
                    self.fps_tracker.update()
                if frame.ndim == 2:
                    pil_image = Image.fromarray(frame, mode="L")
                else:
                    import cv2
                    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    pil_image = Image.fromarray(frame_rgb)
                cw = self.grayscale_canvas.winfo_width()
                ch = self.grayscale_canvas.winfo_height()
                if cw > 1 and ch > 1:
                    pil_image = pil_image.resize((cw, ch), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(image=pil_image)
                if self.grayscale_image_id is None:
                    self.grayscale_image_id = self.grayscale_canvas.create_image(
                        cw // 2, ch // 2, image=photo, anchor="center"
                    )
                else:
                    self.grayscale_canvas.itemconfig(self.grayscale_image_id, image=photo)
                    self.grayscale_canvas.coords(self.grayscale_image_id, cw // 2, ch // 2)
                self.grayscale_canvas.photo = photo
        except Exception as e:
            logger.debug(f"External camera preview frame error: {e}")
        if self._running and self.usb_camera is not None:
            self._usb_preview_job = self.window.after(33, self._usb_preview_loop)

    def _start_usb_preview(self) -> None:
        """Start Player One / external camera live preview in canvas."""
        self._stop_usb_preview()
        if self.usb_camera is None:
            return
        self.preview_info_label.config(text="Player One camera live preview", fg="green")
        self._usb_preview_job = self.window.after(50, self._usb_preview_loop)

    def _show_grayscale_preview(self) -> None:
        """Show captured grayscale image preview."""
        if self.usb_camera is not None:
            try:
                frame = self.usb_camera.read_frame()
                if frame is not None:
                    if frame.ndim == 2:
                        pil_image = Image.fromarray(frame, mode="L")
                    else:
                        import cv2
                        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        pil_image = Image.fromarray(frame_rgb)
                    canvas_width = self.grayscale_canvas.winfo_width()
                    canvas_height = self.grayscale_canvas.winfo_height()
                    if canvas_width > 1 and canvas_height > 1:
                        pil_image = pil_image.resize((canvas_width, canvas_height), Image.Resampling.LANCZOS)
                    photo = ImageTk.PhotoImage(image=pil_image)
                    self.grayscale_canvas.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
                    if self.grayscale_image_id is None:
                        self.grayscale_image_id = self.grayscale_canvas.create_image(
                            canvas_width // 2, canvas_height // 2, image=photo, anchor="center"
                        )
                    else:
                        self.grayscale_canvas.itemconfig(self.grayscale_image_id, image=photo)
                        self.grayscale_canvas.coords(
                            self.grayscale_image_id, canvas_width // 2, canvas_height // 2
                        )
                    self.grayscale_canvas.photo = photo
                    self.preview_info_label.config(
                        text="✓ Grayscale preview (captured image shown below)", fg="blue"
                    )
            except Exception as e:
                logger.error(f"Error showing Player One grayscale preview: {e}")
            return
        if self.picam2 is None:
            return
        
        try:
            # Ensure camera is running
            try:
                if hasattr(self.picam2, 'started') and not self.picam2.started:
                    self.picam2.start()
            except:
                pass
            
            # Capture a frame from picam2
            import numpy as np
            array = self.picam2.capture_array("main")
            
            # Convert to grayscale
            if array.ndim == 3 and array.shape[2] == 3:
                # RGB - convert to grayscale
                gray = np.dot(array[...,:3], [0.2989, 0.5870, 0.1140]).astype(np.uint8)
                frame = gray
            elif array.ndim == 2:
                # Already grayscale
                frame = array
            elif array.ndim == 3 and array.shape[2] == 1:
                # Single channel
                frame = array[:, :, 0]
            else:
                # Extract first channel
                frame = array[:, :, 0] if array.ndim == 3 else array
            
            if frame is not None:
                # Convert to PIL Image
                if frame.ndim == 2:
                    pil_image = Image.fromarray(frame, mode='L')
                else:
                    pil_image = Image.fromarray(frame)
                
                # Resize to fit canvas
                canvas_width = self.grayscale_canvas.winfo_width()
                canvas_height = self.grayscale_canvas.winfo_height()
                if canvas_width > 1 and canvas_height > 1:
                    pil_image = pil_image.resize((canvas_width, canvas_height), Image.Resampling.LANCZOS)
                
                # Convert to PhotoImage and display
                photo = ImageTk.PhotoImage(image=pil_image)
                
                # Show canvas below info label
                self.grayscale_canvas.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
                
                # Update canvas
                if self.grayscale_image_id is None:
                    self.grayscale_image_id = self.grayscale_canvas.create_image(
                        canvas_width // 2,
                        canvas_height // 2,
                        image=photo,
                        anchor='center'
                    )
                else:
                    self.grayscale_canvas.itemconfig(self.grayscale_image_id, image=photo)
                    self.grayscale_canvas.coords(
                        self.grayscale_image_id,
                        canvas_width // 2,
                        canvas_height // 2
                    )
                
                # Keep reference to prevent garbage collection
                self.grayscale_canvas.photo = photo
                
                self.preview_info_label.config(
                    text="✓ Grayscale preview (captured image shown below)",
                    fg="blue"
                )
        except Exception as e:
            logger.error(f"Error showing grayscale preview: {e}")
            self.preview_info_label.config(
                text=f"Preview error: {e}",
                fg="red"
            )
    
    def _hide_grayscale_preview(self) -> None:
        """Hide grayscale preview canvas."""
        self.grayscale_canvas.pack_forget()
    
    def on_quick_capture(self) -> None:
        """Handle quick capture button click."""
        if self.capture_manager is None:
            self.status_label.config(text="Capture not available", fg="orange")
            return
        
        mode = self.capture_mode_var.get()
        
        try:
            if mode == "Image":
                # Capture single image
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                output_dir = "outputs"
                os.makedirs(output_dir, exist_ok=True)
                
                # Get selected format
                image_format = self.image_format_var.get().upper()
                if image_format == "JPEG":
                    ext = ".jpg"
                else:  # Default to PNG
                    ext = ".png"
                
                output_path = os.path.join(output_dir, f"capture_{timestamp}{ext}")
                
                success = self.capture_manager.capture_image(output_path)
                if success:
                    self.status_label.config(text=f"Saved: {os.path.basename(output_path)}", fg="green")
                    # Update grayscale preview if in grayscale mode
                    if "Grayscale" in self.capture_type_var.get():
                        self._show_grayscale_preview()
                else:
                    self.status_label.config(text="Capture failed", fg="red")
            else:
                # Video mode - toggle recording
                if self._recording:
                    # Stop recording
                    output_path = self.capture_manager.stop_video_recording(codec="FFV1")
                    if output_path:
                        self.status_label.config(text=f"Saved: {os.path.basename(output_path)}", fg="green")
                        self.quick_capture_btn.config(text="Quick Capture", bg="#2196F3")
                        self._recording = False
                    else:
                        self.status_label.config(text="Recording failed", fg="red")
                else:
                    # Start recording
                    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                    output_dir = "outputs"
                    os.makedirs(output_dir, exist_ok=True)
                    output_path = os.path.join(output_dir, f"video_{timestamp}.avi")
                    
                    success = self.capture_manager.start_video_recording(output_path, codec="FFV1")
                    if success:
                        self.status_label.config(text="Recording...", fg="red")
                        self.quick_capture_btn.config(text="Stop Recording", bg="red")
                        self._recording = True
                    else:
                        self.status_label.config(text="Failed to start recording", fg="red")
        except Exception as e:
            self.status_label.config(text=f"Error: {e}", fg="red")
            logger.error(f"Quick capture error: {e}")
    
    def on_measure_fps(self) -> None:
        """Measure maximum capture FPS using method matching current capture type."""
        if self._simulate_cam:
            self.status_label.config(text="Camera not available", fg="orange")
            return
        if self.usb_camera is not None:
            self.status_label.config(
                text="Player One camera: FPS is set in capture settings (Mars 662M: up to 110 FPS @ 1080p).",
                fg="gray"
            )
            return

        if self._measuring_fps:
            self.status_label.config(text="FPS measurement in progress...", fg="orange")
            return
        
        def measure_fps_thread():
            """Measure capture FPS using method matching capture type in a separate thread."""
            self._measuring_fps = True
            self.measure_fps_btn.config(state="disabled", text="Measuring...")
            
            # Store current preview state
            was_preview_active = self._native_preview_active
            previous_backend = self._preview_backend
            
            try:
                # Stop native preview if active
                self._stop_native_preview()
                
                # Get current settings
                try:
                    res_x, res_y = self.get_resolution()
                    target_fps = float(self.fps_var.get().strip())
                except ValueError:
                    res_x, res_y = self.get_resolution()
                    target_fps = 250.0  # Use 250 for maximum FPS like in gist
                
                # Get current capture type
                current_capture_type = self.capture_type_var.get()
                
                # Determine which method to use based on capture type
                use_high_fps = "High FPS" in current_capture_type
                
                if use_high_fps:
                    # Use high-FPS method for Picamera2 (Grayscale - High FPS) or rpicam-vid (Grayscale - High FPS)
                    self.status_label.config(text="Stopping preview and measuring FPS using high-FPS method...", fg="orange")
                    self._measure_fps_highfps(res_x, res_y, target_fps, was_preview_active, current_capture_type)
                else:
                    # Use Picamera2 method for Picamera2 (Color) or Picamera2 (Grayscale)
                    self.status_label.config(text="Stopping preview and measuring FPS using Picamera2...", fg="orange")
                    self._measure_fps_picamera2(res_x, res_y, target_fps, was_preview_active)
                
            except Exception as e:
                logger.error(f"Error measuring FPS: {e}", exc_info=True)
                self.status_label.config(text=f"FPS measurement error: {e}", fg="red")
                
                # Try to restore preview even on error
                try:
                    res_x, res_y = self.get_resolution()
                    fps = float(self.fps_var.get().strip())
                except ValueError:
                    res_x, res_y = self.get_resolution()
                    fps = 30.0
                
                self._restore_preview_config(res_x, res_y, fps, was_preview_active)
                
            finally:
                self._measuring_fps = False
                self.measure_fps_btn.config(state="normal", text="Measure FPS")
        
        # Start measurement in separate thread
        thread = threading.Thread(target=measure_fps_thread, daemon=True)
        thread.start()
    
    def _measure_fps_highfps(self, w: int, h: int, target_fps: float, was_preview_active: bool, capture_type: str) -> None:
        """Measure FPS using high-FPS capture methods (Picamera2 or rpicam-vid)."""
        # Store reference to preview window's picam2 for later restoration
        preview_picam2 = self.picam2
        
        # Always stop the preview window's picam2 instance completely before creating new one
        # This is critical to avoid camera hardware conflicts
        if self.picam2 is not None:
            try:
                # Stop preview first
                self._stop_native_preview()
                
                # Clear any callbacks that might interfere
                if hasattr(self.picam2, 'post_callback'):
                    self.picam2.post_callback = None
                if hasattr(self.picam2, 'pre_callback'):
                    self.picam2.pre_callback = None
                
                # Always stop the camera instance - this is critical for proper cleanup
                if hasattr(self.picam2, 'started') and self.picam2.started:
                    self.picam2.stop()
                    logger.info("Stopped preview window's picam2 instance before high-FPS measurement")
                
                # Wait for camera to fully stop and release hardware
                # Longer wait for rpicam-vid since it's a subprocess that needs hardware access
                wait_time = 1.0 if "rpicam-vid" in capture_type else 0.5
                time.sleep(wait_time)
                
                # For rpicam-vid, fully close the Picamera2 instance to release the pipeline handler
                if "rpicam-vid" in capture_type:
                    try:
                        if hasattr(self.picam2, "close"):
                            self.picam2.close()
                            logger.info("Closed preview picam2 to release camera for rpicam-vid")
                    except Exception as e:
                        logger.warning(f"Error closing picam2 before rpicam-vid: {e}")
                    # Ensure references are cleared so we recreate later
                    self.picam2 = None
                    preview_picam2 = None
                
            except Exception as e:
                logger.warning(f"Error stopping camera before high-FPS measurement: {e}")
        
        # Video capture parameters
        res_x, res_y = w, h
        fps = int(target_fps)  # Use target FPS
        
        # Determine which implementation to use
        use_picamera2 = "Picamera2 (Grayscale - High FPS)" in capture_type
        use_rpicam_vid = "rpicam-vid (Grayscale - High FPS)" in capture_type
        
        self.status_label.config(text="Starting high-FPS capture and measuring FPS (5 seconds)...", fg="orange")
        
        capture_instance = None
        try:
            if use_picamera2:
                # Use Picamera2 high-FPS implementation, reusing the preview instance to avoid allocator issues
                from robocam.picamera2_highfps_capture import Picamera2HighFpsCapture
                capture_instance = Picamera2HighFpsCapture(width=w, height=h, fps=fps, picam2=preview_picam2)
                if not capture_instance.start_capture():
                    detail = f" ({capture_instance.last_error})" if getattr(capture_instance, 'last_error', None) else ""
                    if detail:
                        logger.error(f"Picamera2 high-FPS start failed detail: {capture_instance.last_error}")
                    raise RuntimeError(f"Failed to start Picamera2 high-FPS capture{detail}")
                logger.info(f"Picamera2 high-FPS started: {w}x{h} @ {fps} FPS")
            elif use_rpicam_vid:
                # Use rpicam-vid subprocess implementation
                from robocam.rpicam_vid_capture import RpicamVidCapture
                capture_instance = RpicamVidCapture(width=w, height=h, fps=fps)
                if not capture_instance.start_capture():
                    detail = f" ({capture_instance.last_error})" if getattr(capture_instance, 'last_error', None) else ""
                    if detail:
                        logger.error(f"rpicam-vid start failed detail: {capture_instance.last_error}")
                    raise RuntimeError(f"Failed to start rpicam-vid capture{detail}")
                logger.info(f"Rpicam-vid started: {w}x{h} @ {fps} FPS")
            else:
                raise ValueError(f"Unknown high-FPS capture type: {capture_type}")
            
            # Measure FPS by reading frames as fast as possible
            self.status_label.config(text="Measuring FPS (5 seconds)...", fg="orange")
            
            start_time = time.time()
            frame_count = 0
            measurement_duration = 5.0
            consecutive_failures = 0
            max_consecutive_failures = 50  # Exit early if 50 consecutive failures (about 1.25 seconds)
            
            # Use a flag to force exit (set by timeout thread)
            measurement_timeout = threading.Event()
            
            def timeout_handler():
                """Set timeout flag after measurement duration."""
                time.sleep(measurement_duration)
                measurement_timeout.set()
                logger.info("FPS measurement timeout reached")
            
            # Start timeout thread
            timeout_thread = threading.Thread(target=timeout_handler, daemon=True)
            timeout_thread.start()
            
            # Maximum hard timeout (6 seconds - slightly longer than measurement duration)
            hard_timeout = start_time + 6.0
            max_iterations = 1000  # Absolute maximum iterations (safety net)
            iteration_count = 0
            
            while not measurement_timeout.is_set() and time.time() < hard_timeout and iteration_count < max_iterations:
                iteration_count += 1
                # Check elapsed time at start of each iteration to ensure we can exit
                current_time = time.time()
                elapsed = current_time - start_time
                if elapsed >= measurement_duration or current_time >= hard_timeout:
                    logger.info(f"FPS measurement time limit reached: {elapsed:.2f}s elapsed")
                    break
                
                # For rpicam-vid, check if subprocess is still alive
                if use_rpicam_vid and hasattr(capture_instance, 'process'):
                    if capture_instance.process is not None:
                        if capture_instance.process.poll() is not None:
                            logger.error(f"rpicam-vid process died during FPS measurement (returncode: {capture_instance.process.returncode})")
                            break
                    else:
                        logger.error("rpicam-vid process is None during FPS measurement")
                        break
                
                try:
                    # Read frame with timeout protection
                    frame = capture_instance.read_frame()
                    if frame is not None:
                        frame_count += 1
                        consecutive_failures = 0  # Reset failure counter on success
                    else:
                        consecutive_failures += 1
                        if consecutive_failures >= max_consecutive_failures:
                            logger.warning(f"Too many consecutive frame read failures ({consecutive_failures}), stopping FPS measurement early")
                            break
                        # Small delay to prevent busy loop, but shorter to allow more attempts
                        time.sleep(0.01)
                except Exception as e:
                    consecutive_failures += 1
                    logger.warning(f"Frame read error during FPS measurement: {e}")
                    if consecutive_failures >= max_consecutive_failures:
                        logger.warning(f"Too many consecutive errors ({consecutive_failures}), stopping FPS measurement early")
                        break
                    # Continue measuring even if some frames fail
                    time.sleep(0.01)  # Small delay to prevent busy loop
                
                # Additional safety check - if we've been running too long, force exit
                if time.time() >= hard_timeout:
                    logger.warning("FPS measurement exceeded hard timeout, forcing exit")
                    break
            
            # Force exit if we're still in the loop (safety net)
            end_time = time.time()
            elapsed_seconds = end_time - start_time
            
            # Log why we exited
            if iteration_count >= max_iterations:
                logger.warning(f"FPS measurement exited due to maximum iteration limit ({max_iterations} iterations)")
            elif measurement_timeout.is_set():
                logger.info("FPS measurement exited due to timeout event")
            elif elapsed_seconds >= measurement_duration:
                logger.info(f"FPS measurement exited due to duration limit ({elapsed_seconds:.2f}s >= {measurement_duration}s)")
            elif elapsed_seconds >= 6.0:
                logger.warning(f"FPS measurement exited due to hard timeout ({elapsed_seconds:.2f}s)")
            else:
                logger.info(f"FPS measurement exited early after {elapsed_seconds:.2f}s (consecutive failures or process died)")
            
            if elapsed_seconds > 0:
                measured_fps = frame_count / elapsed_seconds
            else:
                measured_fps = 0.0
            
            # Store measured FPS
            self._measured_fps = measured_fps
            self._fps_checked = True
            
            method_name = "Picamera2 high-FPS" if use_picamera2 else "rpicam-vid"
            logger.info(f"{method_name} FPS test: {frame_count} frames in {elapsed_seconds:.2f}s = {measured_fps:.1f} FPS")
            
            # Always stop the capture instance completely before restoring preview
            if capture_instance is not None:
                try:
                    capture_instance.stop_capture()
                    logger.info("Stopped high-FPS capture instance")
                except Exception as e:
                    logger.warning(f"Error stopping capture: {e}")
                capture_instance = None
            
            # Wait for capture instance to fully release hardware
            # Longer wait for rpicam-vid subprocess
            wait_time = 1.0 if use_rpicam_vid else 0.5
            time.sleep(wait_time)
            
            # Restore preview window's picam2 reference if we kept it; otherwise a new one will be created in restore
            if preview_picam2 is not None:
                self.picam2 = preview_picam2
            
            # Restore preview configuration - this will properly start the preview instance
            self._restore_preview_config(res_x, res_y, target_fps, was_preview_active)
            
            # Update status with measured FPS
            self.status_label.config(
                text=f"FPS: {measured_fps:.1f} at {res_x}x{res_y} ({frame_count} frames in {elapsed_seconds:.2f}s)",
                fg="green"
            )
            logger.info(f"Measured FPS using {method_name}: {measured_fps:.1f} at {res_x}x{res_y}")
            
        except Exception as e:
            logger.error(f"Error with high-FPS method: {e}", exc_info=True)
            # Determine method name for error message
            try:
                method_name = "Picamera2 high-FPS" if use_picamera2 else "rpicam-vid" if use_rpicam_vid else "high-FPS"
            except:
                method_name = "high-FPS"
            self.status_label.config(text=f"{method_name} error: {e}", fg="red")
            
            # Always stop capture instance on error
            if capture_instance is not None:
                try:
                    capture_instance.stop_capture()
                    logger.info("Stopped high-FPS capture instance (error cleanup)")
                except Exception as cleanup_error:
                    logger.warning(f"Error during cleanup: {cleanup_error}")
                capture_instance = None
            
            # Wait for hardware release - longer for rpicam-vid
            try:
                wait_time = 1.5 if use_rpicam_vid else 0.5
            except:
                wait_time = 0.5
            time.sleep(wait_time)
            
            # Restore preview window's picam2 reference
            if preview_picam2 is not None:
                self.picam2 = preview_picam2
            
            # Restore preview even on error
            self._restore_preview_config(res_x, res_y, target_fps, was_preview_active)
    
    def _measure_fps_picamera2(self, w: int, h: int, target_fps: float, was_preview_active: bool) -> None:
        """Measure FPS using Picamera2 method (for Picamera2 Color or Grayscale)."""
        if self.picam2 is None:
            self.status_label.config(text="Camera not available", fg="red")
            return
        
        res_x, res_y = w, h
        
        try:
            # Stop camera if running (required before configuring)
            if hasattr(self.picam2, 'started') and self.picam2.started:
                try:
                    self.picam2.stop()
                    time.sleep(0.2)  # Give camera time to fully stop
                except Exception as e:
                    logger.warning(f"Error stopping camera before FPS measurement: {e}")
            
            # Check if grayscale mode
            current_capture_type = self.capture_type_var.get()
            is_grayscale = "Grayscale" in current_capture_type
            
            # Configure for capture (YUV420 format for grayscale, default for color)
            # Use buffer_count=2 for optimal FPS performance
            if is_grayscale:
                config = self.picam2.create_video_configuration(
                    main={"size": (w, h), "format": "YUV420"},
                    controls={"FrameRate": target_fps},
                    buffer_count=2  # Optimize for high FPS
                )
            else:
                config = self.picam2.create_video_configuration(
                    main={"size": (w, h)},
                    controls={"FrameRate": target_fps},
                    buffer_count=2  # Optimize for high FPS
                )
            
            # Configure and start with proper delays
            self.picam2.configure(config)
            time.sleep(0.1)  # Brief pause after configure
            self.picam2.start()
            time.sleep(0.3)  # Wait for camera to be ready
            
            # Measure FPS
            self.status_label.config(text="Measuring FPS (5 seconds)...", fg="orange")
            fps_tracker = FPSTracker()
            start_time = time.time()
            frame_count = 0
            measurement_duration = 5.0
            
            while time.time() - start_time < measurement_duration:
                try:
                    array = self.picam2.capture_array("main")
                    
                    # Process frame based on format
                    if is_grayscale:
                        # Extract Y channel from YUV420 efficiently
                        # YUV420 format: first h rows are Y channel, rest is U/V
                        if array.ndim == 2:
                            # Full YUV420 frame - extract Y channel (first h rows)
                            if array.shape[0] >= h:
                                gray_frame = array[:h, :w]
                            else:
                                gray_frame = array
                        elif array.ndim == 3:
                            # 3D array - extract Y channel (first channel)
                            gray_frame = array[:, :, 0] if array.shape[2] >= 1 else array
                        else:
                            gray_frame = array
                    else:
                        # Color frame - no processing needed for FPS measurement
                        pass
                    
                    fps_tracker.update()
                    frame_count += 1
                except Exception as e:
                    logger.warning(f"Frame capture error: {e}")
                    time.sleep(0.01)
            
            measured_fps = fps_tracker.get_fps()
            actual_duration = time.time() - start_time
            
            # Store measured FPS
            self._measured_fps = measured_fps
            self._fps_checked = True
            
            logger.info(f"Picamera2 FPS test: {frame_count} frames in {actual_duration:.2f}s = {measured_fps:.1f} FPS")
            
            # Stop camera
            self.picam2.stop()
            
            # Restore preview configuration
            self._restore_preview_config(res_x, res_y, target_fps, was_preview_active)
            
            # Update status with measured FPS
            self.status_label.config(
                text=f"FPS: {measured_fps:.1f} at {res_x}x{res_y} ({frame_count} frames in {actual_duration:.2f}s)",
                fg="green"
            )
            logger.info(f"Measured FPS using Picamera2: {measured_fps:.1f} at {res_x}x{res_y}")
            
        except Exception as e:
            logger.error(f"Error in Picamera2 FPS measurement: {e}", exc_info=True)
            self.status_label.config(text=f"Picamera2 FPS measurement error: {e}", fg="red")
            # Restore preview even on error
            self._restore_preview_config(res_x, res_y, target_fps, was_preview_active)
    
    def _restore_preview_config(self, res_x: int, res_y: int, fps: float, was_preview_active: bool) -> None:
        """Restore preview configuration after FPS test."""
        if self.picam2 is None:
            try:
                from picamera2 import Picamera2
                self.picam2 = Picamera2()
                logger.info("Created new Picamera2 instance for preview restore")
            except Exception as e:
                logger.error(f"Cannot restore preview config: failed to create Picamera2 ({e})")
                return
        
        try:
            # Always ensure camera is stopped before reconfiguring
            try:
                if hasattr(self.picam2, 'started') and self.picam2.started:
                    self.picam2.stop()
                    logger.info("Stopped picam2 before restoring preview config")
                    time.sleep(0.3)  # Wait for stop to complete
            except Exception as e:
                logger.warning(f"Error stopping picam2 before restore: {e}")
            
            # Create new preview configuration
            self.picam2_config = self.picam2.create_preview_configuration(
                main={"size": (res_x, res_y)},
                controls={"FrameRate": fps},
                buffer_count=2
            )
            
            # Configure the camera
            self.picam2.configure(self.picam2_config)
            time.sleep(0.1)  # Brief pause after configure
            
            # Start the camera
            self.picam2.start()
            logger.info(f"Started picam2 for preview: {res_x}x{res_y} @ {fps} FPS")
            
            # Restore FPS tracking callback
            if self.fps_tracker:
                def restore_callback(request):
                    if self.fps_tracker:
                        self.fps_tracker.update()
                self.picam2.post_callback = restore_callback
            
            # Wait for camera to be ready
            time.sleep(0.3)
            
            # Restart preview (now that FPS check is complete)
            if "Grayscale" not in self.capture_type_var.get():
                self._start_native_preview()
            else:
                self._show_grayscale_preview()
                
        except Exception as e:
            logger.error(f"Error restoring preview config: {e}", exc_info=True)
    
    def on_close(self) -> None:
        """Handle window close."""
        # Stop FPS update loop
        self._running = False
        
        # Save measured FPS if available
        if self._measured_fps is not None and self._measured_fps > 0:
            try:
                from robocam.config import get_config
                config = get_config()
                # Save measured FPS
                config.set("hardware.camera.last_measured_fps", self._measured_fps)
                # Also save the target FPS from the entry
                try:
                    target_fps = float(self.fps_var.get().strip())
                    config.set("hardware.camera.last_target_fps", target_fps)
                except ValueError:
                    pass
                # Save resolution if available
                try:
                    res_x, res_y = self.get_resolution()
                    config.set("hardware.camera.last_measured_resolution", [res_x, res_y])
                except ValueError:
                    pass
                config.save_config()
                logger.info(f"Saved FPS: {self._measured_fps:.1f} FPS")
            except Exception as e:
                logger.warning(f"Could not save FPS to config: {e}")
        
        # Stop native preview and external camera preview
        self._stop_native_preview()
        self._stop_usb_preview()

        # Stop recording if active
        if self._recording and self.capture_manager:
            try:
                self.capture_manager.stop_video_recording()
            except Exception as e:
                logger.error(f"Error stopping recording: {e}")
        
        # Cleanup capture manager (if we created it)
        if self.capture_manager is not None:
            try:
                self.capture_manager.cleanup()
            except Exception as e:
                logger.error(f"Error cleaning up capture manager: {e}")
        
        # Stop camera (if we created Pi HQ; Player One is owned by capture_manager or caller)
        if self.picam2 is not None:
            try:
                self.picam2.stop()
            except Exception as e:
                logger.error(f"Error stopping camera: {e}")

        # Destroy window
        self.window.destroy()
    
    def destroy(self) -> None:
        """Destroy the preview window."""
        self.on_close()
