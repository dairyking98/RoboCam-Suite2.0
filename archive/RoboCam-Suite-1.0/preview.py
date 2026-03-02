"""
Preview Application - Sequential Well Alignment Preview

Provides a GUI for sequentially previewing well positions for alignment
verification before running experiments. Loads wells from calibration files
or experiment save files and allows sequential navigation through positions.

Author: RoboCam-Suite
"""

import tkinter as tk
from tkinter import messagebox
from tkinter import ttk
import os
import json
import re
from datetime import datetime
from typing import Optional, List, Tuple, Dict, Any
from robocam.camera_backend import detect_camera
from robocam.robocam_ccc import RoboCam
from robocam.camera_preview import FPSTracker
from robocam.config import get_config
from robocam.capture_interface import CaptureManager
from robocam.preview_window import PreviewWindow
from robocam.playerone_camera import PlayerOneCamera

# Preview resolution for camera display (will be loaded from config)
default_preview_resolution: tuple[int, int] = (800, 600)


class PreviewApp:
    """
    Preview application GUI for sequential well alignment checking.
    
    Provides:
    - Native hardware-accelerated camera preview (separate window)
    - Sequential navigation through well positions
    - Load wells from calibration files or experiment save files
    - Real-time position display
    - FPS monitoring
    - Home functionality
    
    Attributes:
        root (tk.Tk): Main tkinter window (controls)
        picam2 (Picamera2): Camera instance
        robocam (RoboCam): Printer control instance
        running (bool): Application running state
        position_label (tk.Label): Current position display
        fps_label (tk.Label): FPS display
        fps_tracker (FPSTracker): FPS tracking instance
        wells (List[Tuple]): List of (position, label) tuples
        current_index (int): Current well index
        homed (bool): Whether printer has been homed
    """
    
    def __init__(self, root: tk.Tk, simulate_3d: bool = False, simulate_cam: bool = False) -> None:
        """
        Initialize preview application.
        
        Args:
            root: Tkinter root window
            simulate_3d: If True, run in 3D printer simulation mode (no printer connection)
            simulate_cam: If True, run in camera simulation mode (no camera connection)
        """
        self.root: tk.Tk = root
        title = "RoboCam Preview - Alignment Check"
        sim_text = []
        if simulate_3d:
            sim_text.append("3D PRINTER SIM")
        if simulate_cam:
            sim_text.append("CAMERA SIM")
        if sim_text:
            title += f" [{' + '.join(sim_text)}]"
        self.root.title(title)
        self._simulate_3d: bool = simulate_3d
        self._simulate_cam: bool = simulate_cam

        # Load config for camera settings
        config = get_config()
        camera_config = config.get_camera_config()
        default_fps = camera_config.get("default_fps", 30.0)
        
        # Get preview resolution from config, or use default
        preview_res = camera_config.get("preview_resolution", list(default_preview_resolution))
        if isinstance(preview_res, list) and len(preview_res) == 2:
            preview_resolution = tuple(preview_res)
        else:
            preview_resolution = default_preview_resolution

        # Camera setup: use first camera found (Pi HQ or Player One; only one in system at a time)
        self.preview_window: Optional[PreviewWindow] = None
        self.picam2 = None
        self.usb_camera = None
        self.fps_tracker: Optional[FPSTracker] = None

        if self._simulate_cam:
            print("Camera simulation mode: Skipping camera initialization")
        else:
            backend = detect_camera()
            if backend == "pihq":
                from picamera2 import Picamera2
                self.picam2 = Picamera2()
                self.picam2_config = self.picam2.create_preview_configuration(
                    main={"size": preview_resolution},
                    controls={"FrameRate": default_fps},
                    buffer_count=2
                )
                self.picam2.configure(self.picam2_config)
                self.fps_tracker = FPSTracker()
                def frame_callback(request):
                    if self.fps_tracker:
                        self.fps_tracker.update()
                self.picam2.post_callback = frame_callback
                try:
                    self.picam2.start()
                    print("Camera started (Pi HQ)")
                except Exception as exc:
                    msg = f"Camera start failed: {exc}"
                    raise RuntimeError(msg) from exc
            elif isinstance(backend, tuple) and backend[0] == "playerone":
                self.usb_camera = PlayerOneCamera(
                    resolution=preview_resolution,
                    fps=default_fps,
                    camera_index=backend[1]
                )
                self.fps_tracker = FPSTracker()
                print("Camera started (Player One)")
            else:
                raise RuntimeError(
                    "No camera found. Connect a Raspberry Pi HQ camera or Player One (Mars 662M). "
                    "Use --simulate_cam to run without a camera. "
                    "On Linux for Player One: run 'bash scripts/populate_playerone_lib.sh' to download and extract the SDK."
                )

        # UI Elements
        self.create_widgets()

        # Initialize capture manager (only if not in camera simulation mode)
        self.capture_manager: Optional[CaptureManager] = None
        if not self._simulate_cam and (self.picam2 is not None or self.usb_camera is not None):
            try:
                if self.usb_camera is not None:
                    is_playerone = type(self.usb_camera).__name__ == "PlayerOneCamera"
                    self.capture_manager = CaptureManager(
                        capture_type="Player One (Grayscale)" if is_playerone else "Player One (Grayscale)",
                        resolution=preview_resolution,
                        fps=default_fps,
                        playerone_camera=self.usb_camera
                    )
                else:
                    self.capture_manager = CaptureManager(
                        capture_type="Picamera2 (Color)",
                        resolution=preview_resolution,
                        fps=default_fps,
                        picam2=self.picam2
                    )
            except Exception as e:
                print(f"Warning: Failed to initialize capture manager: {e}")

        # Create separate preview window (after widgets and capture manager)
        if not self._simulate_cam and (self.picam2 is not None or self.usb_camera is not None):
            try:
                self.preview_window = PreviewWindow(
                    parent=self.root,
                    picam2=self.picam2,
                    capture_manager=self.capture_manager,
                    initial_resolution=preview_resolution,
                    initial_fps=default_fps,
                    simulate_cam=self._simulate_cam,
                    usb_camera=self.usb_camera
                )
                print("Preview window created")
            except Exception as e:
                print(f"Warning: Failed to create preview window: {e}")

        self.running: bool = True
        self.homed: bool = False  # Track homing status, but not required for movement
        self.wells: List[Tuple[Tuple[float, float, float], str]] = []  # (position, label)
        self.current_index: int = -1
        self.source_loaded_from: Optional[str] = None  # "calibration" or "experiment"
        self.selected_wells_set: set = set()  # Set of well labels that are selected (for experiment mode)
        self.all_wells_set: set = set()  # Set of all well labels in the grid (for experiment mode, from calibration)
        self.x_quantity: Optional[int] = None  # Grid width from calibration
        self.y_quantity: Optional[int] = None  # Grid height from calibration
        self.preferred_window_size: Optional[Tuple[int, int]] = None  # Store preferred window size
        
        # Load config for baudrate
        baudrate = config.get("hardware.printer.baudrate", 115200)
        
        # Initialize RoboCam with error handling
        try:
            self.robocam: RoboCam = RoboCam(baudrate=baudrate, config=config, simulate_3d=self._simulate_3d)
            
            # Check if position is available - if not, prompt to home
            if not self._simulate_3d and self.robocam is not None:
                # Try to get current position
                position_available = (
                    self.robocam.X is not None and
                    self.robocam.Y is not None and
                    self.robocam.Z is not None
                )
                
                if not position_available:
                    # Try to update position once more
                    try:
                        self.robocam.update_current_position()
                        position_available = (
                            self.robocam.X is not None and
                            self.robocam.Y is not None and
                            self.robocam.Z is not None
                        )
                    except Exception as e:
                        print(f"Failed to get initial position: {e}")
                        position_available = False
                
                # Check if position is suspiciously at 0,0,0 (might be uninitialized)
                # Even if position_available is True, 0,0,0 before homing is suspicious
                position_is_zero = (
                    position_available and
                    abs(self.robocam.X) < 0.01 and
                    abs(self.robocam.Y) < 0.01 and
                    abs(self.robocam.Z) < 0.01
                )
                
                # If position not available OR position is exactly 0,0,0 (uninitialized), prompt to home
                if not position_available or position_is_zero:
                    response = messagebox.askyesno(
                        "Home Printer",
                        "Current printer position is unavailable.\n\n"
                        "Please home the printer first to establish a known position.\n\n"
                        "Would you like to home the printer now?\n\n"
                        "(Click 'No' to continue without homing, but coordinates may be inaccurate.)"
                    )
                    if response:
                        # User wants to home - do it
                        try:
                            self.robocam.home()
                            # Update position after homing
                            self.robocam.update_current_position()
                            messagebox.showinfo(
                                "Homing Complete",
                                f"Printer homed successfully.\n\n"
                                f"Current position: X={self.robocam.X:.2f}, "
                                f"Y={self.robocam.Y:.2f}, Z={self.robocam.Z:.2f}"
                            )
                            self.homed = True
                        except Exception as e:
                            messagebox.showerror(
                                "Homing Failed",
                                f"Failed to home printer: {e}\n\n"
                                f"Please try homing manually using the Home button."
                            )
        except Exception as e:
            error_msg = str(e).lower()
            if self._simulate_3d:
                # In 3D printer simulation mode, don't show error - just continue
                print(f"3D printer simulation mode: Ignoring printer initialization error: {e}")
                user_msg = "You are simulating a 3D printer! No printer connection needed in simulation mode."
                # Don't show error dialog in simulation mode, just print
                print(user_msg)
            elif "not connected" in error_msg or "serial port" in error_msg or "failed to initialize" in error_msg or "connection" in error_msg:
                user_msg = "Printer connection failed. Check USB cable and try again."
                messagebox.showerror("Connection Error", user_msg)
            else:
                user_msg = f"Initialization error: {error_msg}"
                messagebox.showerror("Connection Error", user_msg)
            
            print(f"RoboCam initialization error: {e}")
            self.robocam = None


        # Start updating position and FPS display
        self.update_status()

    def create_widgets(self) -> None:
        """Create and layout GUI widgets."""
        # Info label about preview window
        if self._simulate_cam:
            info_text = "Camera simulation mode: No camera preview available"
        else:
            info_text = "Camera preview and capture settings are in a separate window"
        tk.Label(self.root, text=info_text, font=("Arial", 9), fg="gray").grid(
            row=0, column=0, columnspan=4, padx=10, pady=5
        )

        # Source selection section
        tk.Label(self.root, text="Load Wells From:", font=("Arial", 10, "bold")).grid(
            row=1, column=0, columnspan=4, sticky="w", padx=5, pady=5
        )
        
        source_frame = tk.Frame(self.root)
        source_frame.grid(row=2, column=0, columnspan=4, padx=5, pady=5, sticky="w")
        
        self.source_type = tk.StringVar(value="calibration")
        tk.Radiobutton(source_frame, text="Calibration File", variable=self.source_type, 
                      value="calibration", command=self.on_source_type_change).pack(side=tk.LEFT, padx=5)
        tk.Radiobutton(source_frame, text="Experiment Save File", variable=self.source_type,
                      value="experiment", command=self.on_source_type_change).pack(side=tk.LEFT, padx=5)
        
        # File selection dropdown
        tk.Label(source_frame, text="File:").pack(side=tk.LEFT, padx=(10, 5))
        self.selected_file = tk.StringVar(value="")
        self.file_dropdown = ttk.Combobox(source_frame, textvariable=self.selected_file, 
                                          state="readonly", width=30)
        self.file_dropdown.pack(side=tk.LEFT, padx=5)
        
        tk.Button(source_frame, text="Load", command=self.load_wells,
                 bg="#2196F3", fg="white", width=10).pack(side=tk.LEFT, padx=10)
        
        # Initialize dropdown with calibration files
        self.update_file_dropdown()
        
        self.source_status_label = tk.Label(self.root, text="No wells loaded", fg="gray", font=("Arial", 9))
        self.source_status_label.grid(row=3, column=0, columnspan=4, sticky="w", padx=5, pady=2)

        # Separator
        tk.Label(self.root, text="─" * 50, fg="gray").grid(
            row=4, column=0, columnspan=4, padx=5, pady=10
        )

        # Well list section with view selector
        well_section_frame = tk.Frame(self.root)
        well_section_frame.grid(row=5, column=0, columnspan=4, sticky="w", padx=5, pady=5)
        
        tk.Label(well_section_frame, text="Well List:", font=("Arial", 10, "bold")).pack(side=tk.LEFT, padx=5)
        
        # View type dropdown
        tk.Label(well_section_frame, text="View:").pack(side=tk.LEFT, padx=(20, 5))
        self.view_type = tk.StringVar(value="list")
        view_menu = tk.OptionMenu(well_section_frame, self.view_type, "list", "graphical", command=self.on_view_change)
        view_menu.pack(side=tk.LEFT, padx=5)
        
        # Container for well display (listbox or graphical)
        self.well_display_frame = tk.Frame(self.root)
        self.well_display_frame.grid(row=6, column=0, columnspan=4, padx=5, pady=5, sticky="nsew")
        
        # Scrollable listbox
        listbox_frame = tk.Frame(self.well_display_frame)
        listbox_frame.pack(fill=tk.BOTH, expand=True)
        
        scrollbar = tk.Scrollbar(listbox_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.well_listbox = tk.Listbox(listbox_frame, height=10, yscrollcommand=scrollbar.set)
        self.well_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.well_listbox.yview)
        
        self.well_listbox.bind("<<ListboxSelect>>", self.on_well_select)
        
        # Graphical view frame (initially hidden)
        self.graphical_frame = tk.Frame(self.well_display_frame)
        self.graphical_canvas = None
        self.graphical_scrollbar = None
        self.well_buttons: Dict[str, tk.Button] = {}  # Map label to button
        
        # Navigation buttons
        nav_frame = tk.Frame(self.root)
        nav_frame.grid(row=7, column=0, columnspan=4, padx=5, pady=5)
        
        tk.Button(nav_frame, text="Home Printer", command=self.home_printer,
                 width=15, height=2, bg="#4CAF50", fg="white").pack(side=tk.LEFT, padx=5)
        # Note: Homing is optional - movement works from current position
        tk.Button(nav_frame, text="Previous", command=self.previous_well,
                 width=12, bg="#FF9800", fg="white").pack(side=tk.LEFT, padx=5)
        tk.Button(nav_frame, text="Next", command=self.next_well,
                 width=12, bg="#FF9800", fg="white").pack(side=tk.LEFT, padx=5)
        tk.Button(nav_frame, text="Go to Selected", command=self.go_to_selected_well,
                 width=15, bg="#2196F3", fg="white").pack(side=tk.LEFT, padx=5)

        # Position and status display
        tk.Label(self.root, text="Position (X, Y, Z):").grid(row=8, column=0, sticky="e", padx=5, pady=5)
        self.position_label = tk.Label(self.root, text="0.00, 0.00, 0.00", font=("Courier", 10))
        self.position_label.grid(row=8, column=1, columnspan=2, sticky="w", padx=5)

        tk.Label(self.root, text="Current Well:").grid(row=9, column=0, sticky="e", padx=5, pady=5)
        self.current_well_label = tk.Label(self.root, text="None", font=("Courier", 10))
        self.current_well_label.grid(row=9, column=1, sticky="w", padx=5)


        tk.Label(self.root, text="Status:").grid(row=11, column=0, sticky="e", padx=5, pady=5)
        self.status_label = tk.Label(self.root, text="Ready", fg="green", font=("Arial", 9))
        self.status_label.grid(row=11, column=1, columnspan=2, sticky="w", padx=5)
        
        
        # Configure grid weights for resizing
        self.root.grid_rowconfigure(6, weight=1)
        self.root.grid_columnconfigure(0, weight=1)
    
    def on_source_type_change(self) -> None:
        """Handle radio button change - update file dropdown options."""
        self.update_file_dropdown()
    
    def update_file_dropdown(self) -> None:
        """Update file dropdown based on selected source type."""
        source_type = self.source_type.get()
        
        if source_type == "calibration":
            # Load calibration files
            calib_dir = "calibrations"
            if os.path.exists(calib_dir):
                files = sorted([f for f in os.listdir(calib_dir) if f.endswith(".json")])
                self.file_dropdown['values'] = files
                if files:
                    self.selected_file.set(files[0])
                else:
                    self.selected_file.set("")
            else:
                self.file_dropdown['values'] = []
                self.selected_file.set("")
        else:
            # Load experiment files
            exp_dir = "experiments"
            if os.path.exists(exp_dir):
                files = sorted([f for f in os.listdir(exp_dir) if f.endswith(".json")])
                self.file_dropdown['values'] = files
                if files:
                    self.selected_file.set(files[0])
                else:
                    self.selected_file.set("")
            else:
                self.file_dropdown['values'] = []
                self.selected_file.set("")
    
    def adjust_window_size_for_graphical(self, grid_width: int, grid_height: int) -> None:
        """Adjust window size to fit graphical well grid - only resize if necessary."""
        # Calculate button size (width=6 chars, height=2 lines, plus padding)
        button_width_px = 60  # Approximate width for 6-char button
        button_height_px = 40  # Approximate height for 2-line button
        padding = 5
        scrollbar_width = 20
        
        # Calculate required canvas size for full grid
        required_width = grid_width * (button_width_px + 2 * padding) + scrollbar_width + 40  # Extra for margins
        required_height = grid_height * (button_height_px + 2 * padding) + scrollbar_width + 40
        
        # Get current window size
        try:
            current_width = self.root.winfo_width()
            current_height = self.root.winfo_height()
            # If window is too small (less than 10x10, it's not yet displayed properly)
            if current_width < 10 or current_height < 10:
                current_width = self.root.winfo_reqwidth()
                current_height = self.root.winfo_reqheight()
        except:
            try:
                current_width = self.root.winfo_reqwidth()
                current_height = self.root.winfo_reqheight()
            except:
                current_width = 600
                current_height = 500
        
        # Get minimum required size (account for other UI elements)
        # Estimate: ~300px for other UI elements (labels, buttons, etc.)
        ui_overhead_width = 50  # Padding and margins
        ui_overhead_height = 350  # Space for source selection, navigation buttons, status labels
        
        min_width = max(required_width + ui_overhead_width, 600)  # At least 600px wide
        min_height = max(required_height + ui_overhead_height, 500)  # At least 500px tall
        
        # Set minimum window size
        self.root.minsize(min_width, min_height)
        
        # Only resize if current window is smaller than required
        if current_width < min_width or current_height < min_height:
            new_width = max(current_width if current_width > 1 else min_width, min_width)
            new_height = max(current_height if current_height > 1 else min_height, min_height)
            self.root.geometry(f"{new_width}x{new_height}")
            # Store the new size as preferred
            self.preferred_window_size = (new_width, new_height)
        else:
            # Window is already large enough, preserve current size
            if self.preferred_window_size is None:
                self.preferred_window_size = (current_width, current_height)
    
    def on_view_change(self, view_type: str) -> None:
        """Handle view type change between list and graphical - maintain window size if possible."""
        # Store current window size before changing view
        try:
            current_width = self.root.winfo_width()
            current_height = self.root.winfo_height()
            if current_width > 10 and current_height > 10:
                self.preferred_window_size = (current_width, current_height)
        except:
            pass
        
        # Clear current display
        for widget in self.well_display_frame.winfo_children():
            widget.destroy()
        
        if view_type == "list":
            # Set minimum window size for list view
            self.root.minsize(400, 400)
            
            # Show listbox
            listbox_frame = tk.Frame(self.well_display_frame)
            listbox_frame.pack(fill=tk.BOTH, expand=True)
            
            scrollbar = tk.Scrollbar(listbox_frame)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            
            self.well_listbox = tk.Listbox(listbox_frame, height=10, yscrollcommand=scrollbar.set)
            self.well_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            scrollbar.config(command=self.well_listbox.yview)
            
            self.well_listbox.bind("<<ListboxSelect>>", self.on_well_select)
            
            # Repopulate listbox if wells are loaded
            if self.wells:
                self.well_listbox.delete(0, tk.END)
                for _, label in self.wells:
                    self.well_listbox.insert(tk.END, label)
            
            # Restore preferred window size if it was set and is larger than minimum
            if self.preferred_window_size:
                pref_width, pref_height = self.preferred_window_size
                if pref_width >= 400 and pref_height >= 400:
                    # Only restore if it's larger than minimum - don't force resize
                    try:
                        current_w = self.root.winfo_width()
                        current_h = self.root.winfo_height()
                        # Only restore if current size is at minimum (user hasn't manually resized)
                        if current_w <= 450 and current_h <= 450:
                            self.root.geometry(f"{pref_width}x{pref_height}")
                    except:
                        pass
        else:
            # Show graphical view
            self.create_graphical_view()
    
    def parse_label_to_grid_pos(self, label: str) -> Optional[Tuple[int, int]]:
        """
        Parse well label (e.g., 'A1', 'B2') to grid position (row, col).
        Returns (row, col) where row is 0-based and col is 0-based.
        """
        match = re.match(r'^([A-Z]+)(\d+)$', label)
        if not match:
            return None
        
        row_str = match.group(1)
        col_str = match.group(2)
        
        # Convert row letter(s) to row index
        row = 0
        for i, char in enumerate(reversed(row_str)):
            row += (ord(char) - ord('A') + 1) * (26 ** i)
        row -= 1  # Make 0-based
        
        # Convert column number to 0-based index
        col = int(col_str) - 1
        
        return (row, col)
    
    def determine_grid_dimensions(self) -> Tuple[int, int]:
        """
        Determine grid dimensions from well labels.
        Returns (width, height) as (x_quantity, y_quantity).
        """
        if self.x_quantity is not None and self.y_quantity is not None:
            return (self.x_quantity, self.y_quantity)
        
        # Parse from labels - use all_wells_set if available (for experiment mode)
        # otherwise use self.wells (for calibration mode)
        labels_to_parse = list(self.all_wells_set) if self.all_wells_set else [label for _, label in self.wells]
        
        max_row = -1
        max_col = -1
        
        for label in labels_to_parse:
            pos = self.parse_label_to_grid_pos(label)
            if pos:
                row, col = pos
                max_row = max(max_row, row)
                max_col = max(max_col, col)
        
        # Dimensions are max + 1 (0-based to 1-based)
        width = max_col + 1 if max_col >= 0 else 1
        height = max_row + 1 if max_row >= 0 else 1
        
        return (width, height)
    
    def create_graphical_view(self) -> None:
        """Create graphical grid view of wells."""
        if not self.wells:
            tk.Label(self.well_display_frame, text="No wells loaded", fg="gray").pack(pady=20)
            return
        
        # Determine grid dimensions
        width, height = self.determine_grid_dimensions()
        
        # Create scrollable canvas with both horizontal and vertical scrolling
        canvas_frame = tk.Frame(self.well_display_frame)
        canvas_frame.pack(fill=tk.BOTH, expand=True)
        
        self.graphical_canvas = tk.Canvas(canvas_frame, bg="white")
        self.graphical_v_scrollbar = tk.Scrollbar(canvas_frame, orient="vertical", command=self.graphical_canvas.yview)
        self.graphical_h_scrollbar = tk.Scrollbar(canvas_frame, orient="horizontal", command=self.graphical_canvas.xview)
        scrollable_frame = tk.Frame(self.graphical_canvas)
        
        self.graphical_canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        self.graphical_canvas.configure(yscrollcommand=self.graphical_v_scrollbar.set, xscrollcommand=self.graphical_h_scrollbar.set)
        
        # Bind mouse wheel for scrolling
        def on_mousewheel(event):
            self.graphical_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        
        self.graphical_canvas.bind_all("<MouseWheel>", on_mousewheel)
        
        # Grid layout for canvas and scrollbars
        self.graphical_canvas.grid(row=0, column=0, sticky="nsew")
        self.graphical_v_scrollbar.grid(row=0, column=1, sticky="ns")
        self.graphical_h_scrollbar.grid(row=1, column=0, sticky="ew")
        canvas_frame.grid_rowconfigure(0, weight=1)
        canvas_frame.grid_columnconfigure(0, weight=1)
        
        # Update canvas scroll region when frame size changes
        def configure_scroll_region(event):
            # Update scroll region to include all content
            bbox = self.graphical_canvas.bbox("all")
            if bbox:
                self.graphical_canvas.configure(scrollregion=bbox)
        
        scrollable_frame.bind("<Configure>", configure_scroll_region)
        
        # Create mapping of label to (row, col) for all possible wells in grid
        all_wells_map: Dict[str, Tuple[int, int]] = {}
        for row in range(height):
            row_letter = chr(ord('A') + row) if row < 26 else f"A{chr(ord('A') + row - 26)}"
            for col in range(width):
                label = f"{row_letter}{col + 1}"
                all_wells_map[label] = (row, col)
        
        # Create buttons for all wells in grid
        self.well_buttons = {}
        button_size = 50
        padding = 5
        
        for label, (row, col) in all_wells_map.items():
            # Check if this well is in the full grid
            well_in_grid = label in self.all_wells_set if self.all_wells_set else True
            
            # Determine if well should be enabled and grayed out
            # For experiment: enable only if in selected_wells_set, gray out if not
            # For calibration: enable all wells in grid
            if self.source_loaded_from == "experiment":
                is_enabled = label in self.selected_wells_set
                is_grayed = not is_enabled
            else:
                # Calibration: all wells are enabled
                is_enabled = well_in_grid
                is_grayed = False
            
            # Create button
            btn = tk.Button(
                scrollable_frame,
                text=label,
                width=6,
                height=2,
                font=("Arial", 8),
                state=tk.NORMAL if is_enabled else tk.DISABLED,
                bg="#E3F2FD" if not is_grayed else "#E0E0E0",
                fg="#000000" if not is_grayed else "#808080",
                relief=tk.RAISED if is_enabled else tk.FLAT,
                command=lambda l=label: self.go_to_well_by_label(l) if is_enabled else None
            )
            
            btn.grid(row=row, column=col, padx=padding, pady=padding, sticky="nsew")
            self.well_buttons[label] = btn
        
        # Configure grid weights for equal spacing
        for row in range(height):
            scrollable_frame.grid_rowconfigure(row, weight=1)
        for col in range(width):
            scrollable_frame.grid_columnconfigure(col, weight=1)
        
        # Update scroll region after all buttons are created
        self.root.update_idletasks()
        self.graphical_canvas.configure(scrollregion=self.graphical_canvas.bbox("all"))
        
        # Calculate required size and adjust window
        self.adjust_window_size_for_graphical(width, height)
    
    def go_to_well_by_label(self, label: str) -> None:
        """Navigate to well by label."""
        # Find index of well with this label
        for idx, (_, well_label) in enumerate(self.wells):
            if well_label == label:
                self.go_to_well(idx)
                return
        
        self.status_label.config(text=f"Well {label} not found", fg="orange")

    def load_wells(self) -> None:
        """Load wells from calibration file or experiment save file."""
        source_type = self.source_type.get()
        
        if source_type == "calibration":
            self.load_from_calibration()
        else:
            self.load_from_experiment()

    def load_from_calibration(self) -> None:
        """Load all wells from a calibration file."""
        # Get selected file from dropdown
        selected = self.selected_file.get()
        if not selected:
            messagebox.showerror("Error", "Please select a calibration file from the dropdown.")
            return
        
        # List available calibrations
        calib_dir = "calibrations"
        if not os.path.exists(calib_dir):
            messagebox.showerror("Error", "Calibrations directory not found: calibrations/")
            return
        
        calibrations = [f for f in os.listdir(calib_dir) if f.endswith(".json")]
        if not calibrations:
            messagebox.showerror("Error", "No calibration files found in calibrations/")
            return
        
        # Build full path
        filename = os.path.join(calib_dir, selected)
        
        if not os.path.exists(filename):
            messagebox.showerror("Error", f"Selected file not found: {selected}")
            return
        
        try:
            with open(filename, 'r') as f:
                calib_data = json.load(f)
            
            # Validate structure
            required_fields = ["interpolated_positions", "labels"]
            if not all(field in calib_data for field in required_fields):
                raise ValueError("Invalid calibration file format")
            
            positions = calib_data.get("interpolated_positions", [])
            labels = calib_data.get("labels", [])
            
            if len(positions) != len(labels):
                raise ValueError("Mismatch between positions and labels count")
            
            # Store wells
            self.wells = [(tuple(pos), label) for pos, label in zip(positions, labels)]
            self.current_index = -1
            
            # Store source type and grid dimensions
            self.source_loaded_from = "calibration"
            self.x_quantity = calib_data.get("x_quantity")
            self.y_quantity = calib_data.get("y_quantity")
            self.selected_wells_set = set(labels)  # All wells are selected for calibration
            self.all_wells_set = set(labels)  # All wells in the grid
            
            # Update display based on current view
            if self.view_type.get() == "list":
                self.well_listbox.delete(0, tk.END)
                for label in labels:
                    self.well_listbox.insert(tk.END, label)
            else:
                self.create_graphical_view()
            
            self.source_status_label.config(
                text=f"Loaded {len(self.wells)} wells from {os.path.basename(filename)}",
                fg="green"
            )
            self.status_label.config(text=f"Loaded {len(self.wells)} wells", fg="green")
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load calibration file: {e}")
            self.source_status_label.config(text="Error loading file", fg="red")

    def load_from_experiment(self) -> None:
        """Load checked wells from an experiment save file."""
        # Get selected file from dropdown
        selected = self.selected_file.get()
        if not selected:
            messagebox.showerror("Error", "Please select an experiment file from the dropdown.")
            return
        
        # List available experiment files
        exp_dir = "experiments"
        if not os.path.exists(exp_dir):
            messagebox.showerror("Error", "Experiments directory not found: experiments/")
            return
        
        experiment_files = [f for f in os.listdir(exp_dir) if f.endswith(".json")]
        if not experiment_files:
            messagebox.showerror("Error", "No experiment files found in experiments/")
            return
        
        # Build full path
        filename = os.path.join(exp_dir, selected)
        
        if not os.path.exists(filename):
            messagebox.showerror("Error", f"Selected file not found: {selected}")
            return
        
        try:
            with open(filename, 'r') as f:
                exp_data = json.load(f)
            
            # Extract calibration file and selected wells
            calib_file = exp_data.get("calibration_file")
            selected_wells = exp_data.get("selected_wells", [])
            
            if not calib_file:
                raise ValueError("No calibration_file field in experiment settings")
            
            if not selected_wells:
                raise ValueError("No selected_wells field in experiment settings")
            
            # Load the referenced calibration file
            calib_path = os.path.join("calibrations", calib_file)
            if not os.path.exists(calib_path):
                raise FileNotFoundError(f"Referenced calibration file not found: {calib_file}")
            
            with open(calib_path, 'r') as f:
                calib_data = json.load(f)
            
            # Validate calibration structure
            required_fields = ["interpolated_positions", "labels"]
            if not all(field in calib_data for field in required_fields):
                raise ValueError("Invalid calibration file format")
            
            positions = calib_data.get("interpolated_positions", [])
            labels = calib_data.get("labels", [])
            
            # Create mapping from label to position
            label_to_pos = {}
            for i, label in enumerate(labels):
                if i < len(positions):
                    label_to_pos[label] = tuple(positions[i])
            
            # Filter to only selected wells
            self.wells = []
            for label in selected_wells:
                if label in label_to_pos:
                    self.wells.append((label_to_pos[label], label))
                else:
                    print(f"Warning: Selected well {label} not found in calibration")
            
            if not self.wells:
                raise ValueError("No valid wells found after filtering")
            
            self.current_index = -1
            
            # Store source type and grid dimensions
            self.source_loaded_from = "experiment"
            self.x_quantity = calib_data.get("x_quantity")
            self.y_quantity = calib_data.get("y_quantity")
            self.selected_wells_set = set(selected_wells)  # Only selected wells
            self.all_wells_set = set(labels)  # All wells in the grid (from calibration)
            
            # Update display based on current view
            if self.view_type.get() == "list":
                self.well_listbox.delete(0, tk.END)
                for _, label in self.wells:
                    self.well_listbox.insert(tk.END, label)
            else:
                self.create_graphical_view()
            
            self.source_status_label.config(
                text=f"Loaded {len(self.wells)} selected wells from {os.path.basename(filename)}",
                fg="green"
            )
            self.status_label.config(text=f"Loaded {len(self.wells)} wells", fg="green")
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load experiment file: {e}")
            self.source_status_label.config(text="Error loading file", fg="red")

    def on_well_select(self, event=None) -> None:
        """Handle well selection in listbox."""
        selection = self.well_listbox.curselection()
        if selection:
            index = selection[0]
            self.current_index = index

    def go_to_selected_well(self) -> None:
        """Move to the currently selected well in the listbox."""
        selection = self.well_listbox.curselection()
        if not selection:
            self.status_label.config(text="No well selected", fg="orange")
            return
        
        index = selection[0]
        self.go_to_well(index)

    def go_to_well(self, index: int) -> None:
        """Move to the well at the specified index."""
        if not self.wells or index < 0 or index >= len(self.wells):
            self.status_label.config(text="Invalid well index", fg="red")
            return
        
        if self.robocam is None:
            self.status_label.config(text="Printer not initialized", fg="red")
            return
        
        # Homing is not required - movement works from current position
        position, label = self.wells[index]
        x, y, z = position
        
        try:
            self.status_label.config(text=f"Moving to {label}...", fg="orange")
            self.root.update()
            self.robocam.move_absolute(X=x, Y=y, Z=z)
            self.current_index = index
            self.update_position()
            self.current_well_label.config(text=label)
            self.status_label.config(text=f"At {label}", fg="green")
            
            # Update listbox selection (if in list view)
            if self.view_type.get() == "list":
                self.well_listbox.selection_clear(0, tk.END)
                self.well_listbox.selection_set(index)
                self.well_listbox.see(index)
            
            # Update graphical view highlighting (if in graphical view)
            if self.view_type.get() == "graphical":
                # Reset all button styles to default
                for label, btn in self.well_buttons.items():
                    if btn.cget("state") == tk.NORMAL:
                        # Determine if this well should be grayed
                        is_grayed = (self.source_loaded_from == "experiment" and 
                                    label not in self.selected_wells_set)
                        btn.config(
                            relief=tk.RAISED,
                            bg="#E3F2FD" if not is_grayed else "#E0E0E0",
                            fg="#000000" if not is_grayed else "#808080"
                        )
                    else:
                        btn.config(relief=tk.FLAT)
                
                # Highlight current well
                _, current_label = self.wells[index]
                if current_label in self.well_buttons:
                    self.well_buttons[current_label].config(relief=tk.SUNKEN, bg="#2196F3", fg="white")
            
        except Exception as e:
            error_msg = str(e)
            if self._simulate_3d:
                user_msg = "You are simulating a 3D printer! No printer connection needed in simulation mode."
            elif "not connected" in error_msg.lower():
                user_msg = "Printer not connected. Check USB cable."
            elif "timeout" in error_msg.lower():
                user_msg = "Movement timed out. Check printer connection."
            else:
                user_msg = f"Movement failed: {error_msg}"
            
            self.status_label.config(text=user_msg, fg="red")
            print(f"Go to well error: {e}")

    def next_well(self) -> None:
        """Move to the next well in sequence."""
        if not self.wells:
            self.status_label.config(text="No wells loaded", fg="orange")
            return
        
        if self.current_index < 0:
            next_index = 0
        elif self.current_index >= len(self.wells) - 1:
            next_index = 0  # Wrap around
        else:
            next_index = self.current_index + 1
        
        self.go_to_well(next_index)

    def previous_well(self) -> None:
        """Move to the previous well in sequence."""
        if not self.wells:
            self.status_label.config(text="No wells loaded", fg="orange")
            return
        
        if self.current_index <= 0:
            prev_index = len(self.wells) - 1  # Wrap around
        else:
            prev_index = self.current_index - 1
        
        self.go_to_well(prev_index)

    def home_printer(self) -> None:
        """Home the printer and update position display."""
        if self.robocam is None:
            self.status_label.config(text="Printer not initialized", fg="red")
            return
        
        try:
            self.status_label.config(text="Homing...", fg="orange")
            self.root.update()
            self.robocam.home()
            self.homed = True
            self.update_position()
            self.status_label.config(text="Homed successfully", fg="green")
        except Exception as e:
            error_msg = str(e)
            if self._simulate_3d:
                user_msg = "You are simulating a 3D printer! No printer connection needed in simulation mode."
            elif "not connected" in error_msg.lower():
                user_msg = "Printer not connected. Check USB cable."
            elif "timeout" in error_msg.lower():
                user_msg = "Homing timed out. Check printer connection."
            else:
                user_msg = f"Homing failed: {error_msg}"
            self.status_label.config(text=user_msg, fg="red")
            self.homed = False
            print(f"Homing error: {e}")

    def update_status(self) -> None:
        """Update position display."""
        if self.running:
            self.update_position()
            # FPS is displayed in the preview window
            self.root.after(200, self.update_status)
    
    def update_position(self) -> None:
        """Update position display with current printer coordinates."""
        if self.robocam is None:
            self.position_label.config(text="N/A, N/A, N/A")
            return
        
        x = self.robocam.X if self.robocam.X is not None else 0.0
        y = self.robocam.Y if self.robocam.Y is not None else 0.0
        z = self.robocam.Z if self.robocam.Z is not None else 0.0
        position = f"{x:.2f}, {y:.2f}, {z:.2f}"
        self.position_label.config(text=position)

    def on_close(self) -> None:
        """Handle window close event."""
        self.running = False
        
        # Close preview window
        if self.preview_window is not None:
            try:
                self.preview_window.destroy()
            except Exception as e:
                print(f"Error closing preview window: {e}")
        
        # Cleanup capture manager
        if self.capture_manager is not None:
            try:
                self.capture_manager.cleanup()
            except Exception as e:
                print(f"Error cleaning up capture manager: {e}")
        
        # Stop camera (Pi HQ only; USB is cleaned up by capture_manager)
        try:
            if self.picam2 is not None:
                self.picam2.stop()
        except Exception:
            pass
        
        self.root.destroy()


# Main application
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="RoboCam Preview - Sequential well alignment check")
    parser.add_argument(
        "--simulate_3d",
        action="store_true",
        help="Run in 3D printer simulation mode (no printer connection, movements are simulated)"
    )
    parser.add_argument(
        "--simulate_cam",
        action="store_true",
        help="Run in camera simulation mode (no camera connection, no preview window)"
    )
    args = parser.parse_args()
    
    root = tk.Tk()
    app = PreviewApp(root, simulate_3d=args.simulate_3d, simulate_cam=args.simulate_cam)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()

