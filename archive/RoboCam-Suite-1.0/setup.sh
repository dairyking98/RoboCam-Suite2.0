#!/bin/bash
# RoboCam-Suite Setup Script
# Creates virtual environment and installs dependencies

set -e  # Exit on error

# Run from repo root; on Linux ensure Player One SDK is present (download + full extract if missing)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
if [ "$(uname -s)" = "Linux" ]; then
  echo "Checking Player One SDK..."
  if [ -f "$SCRIPT_DIR/scripts/populate_playerone_lib.sh" ]; then
    bash "$SCRIPT_DIR/scripts/populate_playerone_lib.sh" || true
  fi
fi

echo "RoboCam-Suite Setup Script"
echo "=========================="
echo ""

# Check for Python 3
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is not installed or not in PATH"
    exit 1
fi

PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
echo "Found Python: $PYTHON_VERSION"

# Check Python version (3.7+)
PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d'.' -f1)
PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d'.' -f2)

if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 7 ]); then
    echo "Error: Python 3.7 or higher is required. Found: $PYTHON_VERSION"
    exit 1
fi

echo "Python version check passed."
echo ""

# Check for and install system dependencies
echo "Checking for system dependencies..."
MISSING_DEPS=()
OPTIONAL_DEPS=()

# Check for python3-libcamera (required for picamera2)
if ! dpkg -l | grep -q "^ii.*python3-libcamera"; then
    MISSING_DEPS+=("python3-libcamera")
fi

# Check for libcap-dev (required for python-prctl)
if ! dpkg -l | grep -q "^ii.*libcap-dev"; then
    MISSING_DEPS+=("libcap-dev")
fi

# Check for other common build dependencies
if ! dpkg -l | grep -q "^ii.*python3-dev"; then
    MISSING_DEPS+=("python3-dev")
fi

if ! dpkg -l | grep -q "^ii.*build-essential"; then
    MISSING_DEPS+=("build-essential")
fi

# Check for python3-rpi.gpio (required for GPIO control)
if ! dpkg -l | grep -q "^ii.*python3-rpi.gpio"; then
    MISSING_DEPS+=("python3-rpi.gpio")
fi

# Check for libcamera-apps (contains rpicam-vid command-line tool)
# rpicam-vid is optional for high-FPS grayscale capture mode (alternative to Picamera2)
# Note: This is checked separately because it's a command-line tool, not a Python package
RPICAM_VID_AVAILABLE=false
RPICAM_VID_PACKAGE_AVAILABLE=false
RPICAM_VID_ATTEMPT_INSTALL=false

if command -v rpicam-vid &> /dev/null; then
    RPICAM_VID_AVAILABLE=true
    echo "rpicam-vid command found."
else
    echo "rpicam-vid command not found. Checking for installation package..."
    # Check if package is available in repositories
    if apt-cache show libcamera-apps &>/dev/null 2>&1; then
        RPICAM_VID_PACKAGE_AVAILABLE=true
        # Note: libcamera-apps is optional - don't add to MISSING_DEPS automatically
        # User can install it if they want to use rpicam-vid mode
        echo "libcamera-apps package is available in repositories (optional)."
    else
        RPICAM_VID_ATTEMPT_INSTALL=false
        echo ""
        echo "Note: libcamera-apps package is not available in repositories."
        echo "The 'rpicam-vid (Grayscale - High FPS)' capture mode will not be available."
        echo "Alternative: Use 'Picamera2 (Grayscale - High FPS)' capture mode (recommended)."
        echo ""
    fi
fi

# Check for ffmpeg (required for Picamera2 high-FPS capture with hardware encoding)
# ffmpeg is used by picamera2_highfps_capture.py for hardware-accelerated video encoding
# Note: ffmpeg is often already installed on Raspberry Pi OS
FFMPEG_AVAILABLE=false
if command -v ffmpeg &> /dev/null; then
    FFMPEG_AVAILABLE=true
    echo "ffmpeg command found (already installed)."
else
    echo "ffmpeg command not found. Checking for installation package..."
    # Check if package is available in repositories
    if apt-cache show ffmpeg &>/dev/null 2>&1; then
        # ffmpeg is required for high-FPS capture mode, so add to MISSING_DEPS
        MISSING_DEPS+=("ffmpeg")
        echo "ffmpeg package is available in repositories (required for high-FPS capture)."
    else
        echo ""
        echo "WARNING: ffmpeg package is not available in repositories."
        echo "The 'Picamera2 (Grayscale - High FPS)' capture mode with hardware encoding will not work."
        echo "You may need to install ffmpeg manually or use alternative capture modes."
        echo ""
    fi
fi

# Check for python3-pil.imagetk (required for tkinter preview ImageTk support)
# Note: This is optional - Pillow in venv should work, but system package ensures compatibility
if ! dpkg -l | grep -q "^ii.*python3-pil.imagetk"; then
    # Don't add to MISSING_DEPS - it's optional, we'll try to install it but won't fail if unavailable
    OPTIONAL_DEPS+=("python3-pil.imagetk")
fi

if [ ${#MISSING_DEPS[@]} -gt 0 ]; then
    echo "Missing system dependencies detected: ${MISSING_DEPS[*]}"
    echo "These are required for:"
    echo "  - python3-libcamera: Required for picamera2 (Raspberry Pi camera support)"
    echo "  - python3-rpi.gpio: Required for GPIO control (laser control)"
    echo "  - ffmpeg: Required for Picamera2 high-FPS capture with hardware encoding"
    echo "  - libcap-dev, python3-dev, build-essential: Required to build Python packages"
    echo ""
    echo "Please install them before continuing:"
    echo "  sudo apt-get update"
    echo "  sudo apt-get install -y ${MISSING_DEPS[*]}"
    echo ""
    echo "Attempting to install automatically (requires sudo)..."
    if sudo apt-get update && sudo apt-get install -y "${MISSING_DEPS[@]}" 2>/dev/null; then
        echo "System dependencies installed successfully."
    else
        echo ""
        echo "ERROR: Could not install system dependencies automatically."
        echo "Please run the following commands manually:"
        echo "  sudo apt-get update"
        echo "  sudo apt-get install -y ${MISSING_DEPS[*]}"
        echo ""
        echo "Then re-run this setup script."
        exit 1
    fi
    else
        echo "System dependencies check passed."
fi

# Note about optional rpicam-vid installation
if [ "$RPICAM_VID_AVAILABLE" = false ] && [ "$RPICAM_VID_PACKAGE_AVAILABLE" = true ]; then
    echo ""
    echo "Note: rpicam-vid command is not available, but libcamera-apps package is available."
    echo "To enable 'rpicam-vid (Grayscale - High FPS)' capture mode, install:"
    echo "  sudo apt-get install -y libcamera-apps"
    echo ""
    echo "Alternative: Use 'Picamera2 (Grayscale - High FPS)' capture mode (recommended, requires ffmpeg)."
    echo ""
fi

# Note about ffmpeg installation
if [ "$FFMPEG_AVAILABLE" = false ]; then
    echo ""
    echo "WARNING: ffmpeg is not installed."
    echo "The 'Picamera2 (Grayscale - High FPS)' capture mode with hardware encoding requires ffmpeg."
    echo ""
    echo "Installation:"
    echo "  sudo apt-get update"
    echo "  sudo apt-get install -y ffmpeg"
    echo ""
    echo "Verify installation:"
    echo "  ffmpeg -version"
    echo "  ffmpeg -encoders | grep v4l2m2m  # Check hardware encoder support"
    echo ""
    echo "For detailed installation guide, see: docs/FFMPEG_INSTALLATION.md"
    echo ""
fi

# Install optional dependencies (won't fail if unavailable)
if [ ${#OPTIONAL_DEPS[@]} -gt 0 ]; then
    echo ""
    echo "Installing optional system dependencies..."
    echo "These improve compatibility but are not strictly required:"
    echo "  ${OPTIONAL_DEPS[*]}"
    echo ""
    echo "Attempting to install (requires sudo)..."
    if sudo apt-get update && sudo apt-get install -y "${OPTIONAL_DEPS[@]}" 2>/dev/null; then
        echo "Optional dependencies installed successfully."
    else
        echo "Warning: Could not install optional dependencies. This is usually fine."
        echo "Pillow in venv should work, but if you see ImageTk import errors, try:"
        echo "  sudo apt-get install python3-pil.imagetk"
    fi
fi

echo ""

# Create virtual environment with system site packages
# This allows access to system-installed packages like python3-libcamera
if [ ! -d "venv" ]; then
    echo "Creating virtual environment (with system site packages)..."
    python3 -m venv --system-site-packages venv
    echo "Virtual environment created."
else
    echo "Virtual environment already exists."
    echo "Note: If you're having issues with libcamera, you may need to recreate the venv with:"
    echo "  rm -rf venv && python3 -m venv --system-site-packages venv"
fi

echo ""

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

echo ""

# Upgrade pip
echo "Upgrading pip..."
# Suppress send2trash dependency parsing warning (harmless metadata issue)
pip install --upgrade pip 2>&1 | grep -v "WARNING: Error parsing dependencies of send2trash" || true

echo ""

# Install dependencies
if [ -f "requirements.txt" ]; then
    echo "Installing dependencies from requirements.txt..."
    # Try to install dependencies, but don't exit on error
    # This allows partial installation if some packages fail
    set +e  # Temporarily disable exit on error
    # Suppress send2trash dependency parsing warning (harmless metadata issue)
    # Filter warning while preserving pip's exit code
    pip install -r requirements.txt 2>&1 | grep -v "WARNING: Error parsing dependencies of send2trash"
    PIP_EXIT_CODE=${PIPESTATUS[0]}
    set -e  # Re-enable exit on error
    
    if [ $PIP_EXIT_CODE -eq 0 ]; then
        echo "Dependencies installed successfully."
    else
        echo ""
        echo "Warning: Some dependencies failed to install."
        echo "This may be due to missing system packages."
        echo ""
        echo "Common solutions:"
        echo "  1. Install missing system dependencies (see above)"
        echo "  2. Try installing dependencies manually:"
        echo "     source venv/bin/activate"
        echo "     pip install -r requirements.txt"
        echo ""
        echo "Checking which packages were installed..."
        pip list | grep -E "(picamera2|pyserial)" || echo "Critical packages may be missing."
    fi
else
    echo "Warning: requirements.txt not found. Skipping dependency installation."
fi

echo ""

# Fix opencv-python: uninstall GUI version and install headless version
# opencv-python includes Qt/GUI dependencies that cause issues on headless systems
# opencv-python-headless has all the same functionality (VideoWriter, imwrite, etc.) without GUI
echo "Fixing opencv-python installation..."
echo "Uninstalling opencv-python (if installed) and installing opencv-python-headless..."
# Uninstall any existing opencv-python (system or venv)
pip uninstall -y opencv-python 2>/dev/null || true
# Install opencv-python-headless in venv
pip install opencv-python-headless 2>&1 | grep -v "WARNING: Error parsing dependencies of send2trash" || true
echo "opencv-python-headless installed (no Qt/GUI dependencies)"

echo ""

# Ensure Pillow is installed in venv (required for tkinter preview)
# System PIL may not have ImageTk support, so we need Pillow in venv
echo "Ensuring Pillow is installed in venv (required for tkinter preview)..."
# Uninstall any existing Pillow/PIL (system or venv) to avoid conflicts
pip uninstall -y Pillow PIL 2>/dev/null || true
# Install Pillow in venv (will compile with tkinter support if available)
pip install Pillow 2>&1 | grep -v "WARNING: Error parsing dependencies of send2trash" || true
echo "Pillow installed in venv"

echo ""

# Create configuration directories
echo "Creating configuration directories..."
mkdir -p calibrations
mkdir -p experiments
mkdir -p outputs
mkdir -p config/templates
mkdir -p docs
echo "Configuration directories created."

echo ""

# Create motion configuration file with all profiles if it doesn't exist
if [ ! -f "config/motion_config.json" ]; then
    echo "Creating motion configuration file with profiles..."
    cat > config/motion_config.json << 'EOF'
{
  "default": {
    "name": "Default Profile",
    "description": "Balanced speed and precision for general use",
    "preliminary": {
      "feedrate": 3000,
      "acceleration": 500
    },
    "between_wells": {
      "feedrate": 1200,
      "acceleration": 300
    }
  },
  "precise": {
    "name": "Precise Profile",
    "description": "Lower speed and acceleration for maximum precision",
    "preliminary": {
      "feedrate": 2000,
      "acceleration": 300
    },
    "between_wells": {
      "feedrate": 3000,
      "acceleration": 500
    }
  },
  "fast": {
    "name": "Fast Profile",
    "description": "Maximum speed for rapid well-to-well movements",
    "preliminary": {
      "feedrate": 5000,
      "acceleration": 1000
    },
    "between_wells": {
      "feedrate": 8000,
      "acceleration": 1500
    }
  }
}
EOF
    echo "Motion configuration file created with default, precise, and fast profiles."
fi

echo ""

# Verify critical packages are installed
echo "Verifying installation..."
CRITICAL_PACKAGES=("picamera2" "pyserial")
MISSING_PACKAGES=()

for package in "${CRITICAL_PACKAGES[@]}"; do
    if ! pip show "$package" &>/dev/null; then
        MISSING_PACKAGES+=("$package")
    fi
done

if [ ${#MISSING_PACKAGES[@]} -gt 0 ]; then
    echo ""
    echo "WARNING: The following critical packages are missing: ${MISSING_PACKAGES[*]}"
    echo "Installation may have failed. Please check the error messages above."
    echo ""
    echo "To fix this, try:"
    echo "  1. Ensure system dependencies are installed (libcap-dev, python3-dev, build-essential)"
    echo "  2. Activate the virtual environment: source venv/bin/activate"
    echo "  3. Reinstall: pip install -r requirements.txt"
    echo ""
else
    echo "Critical packages verified: ${CRITICAL_PACKAGES[*]}"
fi

echo ""

# Check for hardware (optional, inform user)
echo "Hardware Setup Checklist:"
echo "  - Raspberry Pi Camera: Check connection and enable in raspi-config"
echo "  - 3D Printer: Check USB serial connection"
echo "  - GPIO Laser: Check connection to GPIO pin (default: GPIO 21)"
echo "  - Serial Port Permissions: Add user to dialout group if needed"
echo "    sudo usermod -a -G dialout \$USER"
echo "  - GPIO Permissions: Add user to gpio group if needed"
echo "    sudo usermod -a -G gpio \$USER"
echo ""

if [ ${#MISSING_PACKAGES[@]} -eq 0 ]; then
    echo "Setup complete!"
else
    echo "Setup completed with warnings. Please address missing packages before use."
fi
echo ""
echo "To activate the virtual environment, run:"
echo "  source venv/bin/activate"
echo ""
echo "To start the calibration application:"
echo "  ./start_calibrate.sh"
echo ""
echo "To start the preview application:"
echo "  ./start_preview.sh"
echo ""
echo "To start the experiment application:"
echo "  ./start_experiment.sh"
echo ""

