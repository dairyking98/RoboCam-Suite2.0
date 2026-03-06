#!/usr/bin/env bash
# =============================================================================
# RoboCam-Suite 2.0 — Setup Script (Linux / macOS)
# =============================================================================
# Creates a virtual environment named .venv and installs all dependencies.
# Run once after cloning:
#   bash setup.sh
#
# To activate the environment afterwards:
#   source .venv/bin/activate
# =============================================================================

set -e  # Exit immediately on any error

VENV_DIR=".venv"
PYTHON="${PYTHON:-python3}"  # Override with: PYTHON=python3.11 bash setup.sh

echo "==> Checking Python version..."
$PYTHON --version

echo "==> Creating virtual environment in '$VENV_DIR'..."
$PYTHON -m venv "$VENV_DIR"

echo "==> Activating virtual environment..."
source "$VENV_DIR/bin/activate"

echo "==> Upgrading pip..."
pip install --upgrade pip

echo "==> Installing RoboCam-Suite and its dependencies..."
pip install -e .

# --- Raspberry Pi HQ Camera (picamera2) ---
if [[ "$OSTYPE" == "linux-gnueabihf"* ]] || [[ "$OSTYPE" == "linux-gnu"* ]]; then
    if [ -f /etc/rpi-issue ]; then
        echo "==> Raspberry Pi detected. Installing picamera2 dependencies..."
        # We try to install the system-level picamera2 if possible, or use the 
        # python-picamera2 package if it's available. 
        # Note: modern RPi OS (Bullseye/Bookworm) uses libcamera.
        echo "    Installing libcamera and picamera2 Python bindings..."
        # On modern RPi OS, we can use pip to install picamera2, but it requires 
        # libcamera-dev and other system dependencies.
        pip install picamera2 || echo "WARNING: picamera2 pip install failed. Ensure you have libcamera installed."
    fi
fi

# Windows-only extras (cv2-enumerate-cameras, wmi) are declared with
# sys_platform == "win32" markers in requirements.txt so pip skips them
# automatically on Linux and macOS.  No extra step needed here.

echo "==> Installing Player One Camera SDK (pyPOACamera + native library)..."
echo "    Downloads SDK from player-one-astronomy.com into vendor/playerone/"
echo "    Safe to skip if you don't have a Player One camera."
python scripts/install_playerone_sdk.py || {
    echo "WARNING: Player One SDK install failed or was skipped."
    echo "         To install manually later:  python scripts/install_playerone_sdk.py"
}

echo ""
echo "============================================================"
echo " Setup complete!"
echo ""
echo " To activate the environment, run:"
echo "   source .venv/bin/activate"
echo ""
echo " To launch the application:"
echo "   python main.py"
echo "   -- or --"
echo "   python -m robocam_suite"
echo "============================================================"
