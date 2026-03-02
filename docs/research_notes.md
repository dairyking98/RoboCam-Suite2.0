# RoboCam-Suite 2.0 Research Notes

## Player One Camera SDK - Cross-Platform Support
- SDK V3.10.0 (Released 2025/12/25) supports: **Windows, Linux, Mac OS, Raspberry Pi (merged into Linux)**
- Raspberry Pi SDK has been merged into the Linux version
- Windows requires native camera driver (V1.5.12.25)
- Mac OS SDK available (button visible on site)
- LabVIEW support also available
- The SDK is fully cross-platform - this is a MAJOR advantage for 2.0

## GPIO Cross-Platform Options

### Option 1: Arduino/Pico as USB GPIO Bridge (RECOMMENDED)
- Arduino Nano/Uno/Micro or Raspberry Pi Pico connected via USB
- Python sends serial commands to microcontroller
- Microcontroller toggles GPIO pins
- Works on Windows, macOS, Linux identically
- Very cheap (~$5-15), widely available
- Can use `pyserial` for communication (already a dependency)
- Firmware: simple sketch that reads "ON"/"OFF" commands over serial
- Latency: ~1-5ms (sufficient for laser control)

### Option 2: Adafruit FT232H USB-to-GPIO
- USB breakout board with GPIO, I2C, SPI, UART
- Works on Windows, Linux, macOS via `pyftdi` or `adafruit-blinka`
- ~$15 from Adafruit
- Direct Python control without separate firmware
- `adafruit-blinka` provides RPi.GPIO-compatible API

### Option 3: Numato USB GPIO Modules
- 8-128 channel USB GPIO modules
- Python library: `numato-gpio` on PyPI
- Works cross-platform via serial

### Option 4: Keep Raspberry Pi as GPIO Controller
- Pi remains connected to main computer via USB/network
- Pi handles GPIO, main computer handles camera/GUI
- `gpiozero` supports remote GPIO via pigpio daemon
- Most complex but preserves existing hardware

## Camera Library Cross-Platform Analysis

### OpenCV (cv2) - RECOMMENDED for 2.0
- Fully cross-platform: Windows, macOS, Linux
- Works with any UVC/V4L2 camera
- `cv2.VideoCapture()` works everywhere
- For Player One: use their SDK + numpy arrays → cv2
- Performance: adequate for most use cases
- Limitation: USB bandwidth can cap FPS

### Player One SDK (Direct)
- Cross-platform: Windows, Linux, macOS (confirmed from website)
- Python bindings included in SDK
- Supports high FPS capture (80-90+ FPS confirmed)
- Already partially implemented in RoboCam-Suite

### VidGear
- Cross-platform high-performance video framework
- Wraps OpenCV, GStreamer, FFmpeg
- Good for high-FPS capture

## Python Performance Analysis

### Python GIL Considerations
- GIL affects CPU-bound threading, NOT I/O-bound operations
- Camera capture is I/O-bound → GIL is NOT a bottleneck for camera reads
- Serial communication is I/O-bound → GIL is NOT a bottleneck
- Image processing (numpy/cv2) releases GIL → threading works fine
- Python 3.13+ has optional free-threaded mode (experimental)

### Python vs C++ for this use case
- Camera capture: Python overhead ~5-10% vs C++ (negligible)
- Serial comms: Python overhead ~1-2% (negligible)  
- Image encoding: OpenCV/FFmpeg do heavy lifting in C anyway
- GUI: tkinter/PyQt both call native C libraries
- CONCLUSION: Python is perfectly adequate; bottleneck is USB bandwidth and camera sensor, not Python

### Where Python IS slow
- Pure Python pixel manipulation loops (avoid - use numpy)
- Tkinter canvas updates at high FPS (use OpenGL or native window)
- Blocking serial reads in main thread (use threading - already done)

## GUI Framework Analysis

### Current: tkinter
- Pros: Built into Python, no extra deps, simple
- Cons: Looks dated, poor performance for live video, no hardware acceleration
- Camera preview: requires PIL.ImageTk, limited to ~30 FPS in canvas

### PyQt6 / PySide6 (RECOMMENDED for 2.0)
- Pros: Native look on all platforms, QOpenGLWidget for GPU preview, rich widgets
- Cons: Larger dependency, licensing (PyQt6=GPL/commercial, PySide6=LGPL)
- Camera preview: QOpenGLWidget or QLabel with QPixmap → 60+ FPS possible
- Best choice for scientific instrument GUI

### Dear PyGui
- Pros: GPU-accelerated, very fast live preview, modern look
- Cons: Less mature, different paradigm
- Good for camera preview specifically

### Recommendation: PyQt6/PySide6
- PySide6 preferred (LGPL license, official Qt binding)
- QOpenGLWidget for camera preview → hardware accelerated
- Excellent cross-platform consistency

## Architecture Recommendations

### Modular Plugin Architecture
- `core/` - hardware abstraction interfaces (ABCs)
- `drivers/` - hardware implementations (camera, motion, gpio)
  - `drivers/camera/` - opencv, playerone, picamera2 backends
  - `drivers/motion/` - gcode_serial, simulated
  - `drivers/gpio/` - rpi_gpio, arduino_serial, ft232h, simulated
- `ui/` - GUI components
- `experiments/` - experiment definitions
- `config/` - configuration management

### Key Design Patterns
1. Abstract Base Classes for all hardware → easy to swap implementations
2. Plugin discovery for camera/GPIO backends
3. Async/threading for non-blocking hardware ops
4. Event-driven experiment execution
5. Configuration via TOML or JSON (TOML more readable)
