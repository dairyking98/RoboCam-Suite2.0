#!/bin/bash
# Quick fix script for missing system dependencies
# Run this if setup.sh failed due to missing libcap-dev or other build dependencies

echo "RoboCam-Suite Dependency Fix Script"
echo "==================================="
echo ""

# Run from repo root; on Linux ensure Player One SDK is present (download + full extract if missing)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
if [ "$(uname -s)" = "Linux" ]; then
  echo "Checking Player One SDK..."
  if [ -f "$SCRIPT_DIR/scripts/populate_playerone_lib.sh" ]; then
    bash "$SCRIPT_DIR/scripts/populate_playerone_lib.sh" || true
  fi
fi

# Install required system dependencies
echo "Installing system dependencies..."
sudo apt-get update
sudo apt-get install -y python3-libcamera libcap-dev python3-dev build-essential

# ImageTk for preview (USB camera and tkinter) - system PIL needs python3-pil.imagetk
echo "Installing python3-pil.imagetk and python3-tk (for PIL.ImageTk in preview)..."
sudo apt-get install -y python3-pil.imagetk python3-tk 2>/dev/null || echo "  (optional; if preview still fails, install manually: sudo apt-get install python3-pil.imagetk python3-tk)"

echo ""
echo "System dependencies installed."
echo ""

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "Creating virtual environment with system site packages..."
    python3 -m venv --system-site-packages venv
else
    echo "Checking if venv has system site packages enabled..."
    # Check if pyvenv.cfg has system-site-packages = true
    if ! grep -q "include-system-site-packages = true" venv/pyvenv.cfg 2>/dev/null; then
        echo "Virtual environment was created without system site packages."
        echo "Recreating venv with system site packages to access python3-libcamera..."
        rm -rf venv
        python3 -m venv --system-site-packages venv
        echo "Virtual environment recreated with system site packages."
    else
        echo "Virtual environment already has system site packages enabled."
    fi
fi

# Activate virtual environment and reinstall Python packages
echo "Activating virtual environment and reinstalling Python packages..."
source venv/bin/activate

echo "Upgrading pip..."
pip install --upgrade pip

echo ""
echo "Reinstalling requirements..."
pip install -r requirements.txt

echo ""
echo "Ensuring Pillow (with ImageTk) in venv for preview..."
pip install --force-reinstall Pillow 2>/dev/null || true

echo ""
echo "Verifying installation..."
if pip show picamera2 &>/dev/null && pip show pyserial &>/dev/null; then
    echo "✓ picamera2 and pyserial are installed successfully!"
else
    echo "✗ Some packages are still missing. Please check the error messages above."
    exit 1
fi

# Check if libcamera can be imported
echo ""
echo "Checking if libcamera is accessible..."
if python3 -c "import libcamera" 2>/dev/null; then
    echo "✓ libcamera is accessible!"
else
    echo "✗ libcamera cannot be imported."
    echo "  This may mean python3-libcamera is not installed, or venv can't access it."
    echo "  Try: sudo apt-get install -y python3-libcamera"
    echo "  Then recreate venv: rm -rf venv && python3 -m venv --system-site-packages venv"
    exit 1
fi

echo ""
echo "✓ All dependencies verified!"
echo ""
echo "You can now run:"
echo "  ./start_calibrate.sh"

