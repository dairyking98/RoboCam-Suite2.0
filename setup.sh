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

# Check if we should skip venv (only on Pi)
SKIP_VENV=false
if [[ "$OSTYPE" == "linux-gnueabihf"* ]] || [[ "$OSTYPE" == "linux-gnu"* ]]; then
    if [ -f /etc/rpi-issue ]; then
        echo "==> Raspberry Pi detected. Would you like to use a virtual environment? (y/n)"
        # Default to yes for safety
        read -r use_venv
        if [[ "$use_venv" == "n" ]]; then
            SKIP_VENV=true
        fi
    fi
fi

if [ "$SKIP_VENV" = false ]; then
    echo "==> Creating virtual environment in '$VENV_DIR'..."
    # On Raspberry Pi, we often need access to system packages for libcamera.
    # Using --system-site-packages allows the venv to use the system libcamera-python.
    if [[ "$OSTYPE" == "linux-gnueabihf"* ]] || [[ "$OSTYPE" == "linux-gnu"* ]]; then
        if [ -f /etc/rpi-issue ]; then
            echo "    Using --system-site-packages for Raspberry Pi compatibility."
            $PYTHON -m venv --system-site-packages "$VENV_DIR"
        else
            $PYTHON -m venv "$VENV_DIR"
        fi
    else
        $PYTHON -m venv "$VENV_DIR"
    fi
    
    echo "==> Activating virtual environment..."
    source "$VENV_DIR/bin/activate"
    
    echo "==> Upgrading pip..."
    pip install --upgrade pip
else
    echo "==> Skipping virtual environment. Installing dependencies globally..."
    echo "    (You may need to run this script with sudo if you hit permission errors)"
fi

echo "==> Installing RoboCam-Suite and its dependencies..."
if [ "$SKIP_VENV" = true ]; then
    pip3 install -e .
else
    pip install -e .
fi

# --- Raspberry Pi HQ Camera (picamera2 / libcamera) ---
if [[ "$OSTYPE" == "linux-gnueabihf"* ]] || [[ "$OSTYPE" == "linux-gnu"* ]]; then
    if [ -f /etc/rpi-issue ]; then
        echo "==> Raspberry Pi detected. Installing picamera2 and libcamera dependencies..."
        
        # On modern RPi OS (Bullseye/Bookworm), libcamera-python is the core.
        # Picamera2 is a high-level wrapper around it.
        
        # We can't easily install system packages (apt) without sudo, 
        # but we can check if they are missing and warn the user.
        if ! dpkg -l | grep -q "python3-libcamera"; then
            echo "WARNING: python3-libcamera not found. You may need to run:"
            echo "         sudo apt update && sudo apt install -y python3-libcamera python3-kms++ libcap-dev"
        fi

        echo "    Installing picamera2 Python wrapper..."
        if [ "$SKIP_VENV" = true ]; then
            pip3 install picamera2 || echo "WARNING: picamera2 pip install failed. Ensure libcamera-python is installed."
        else
            pip install picamera2 || echo "WARNING: picamera2 pip install failed. Ensure libcamera-python is installed."
        fi
    fi
fi

# Windows-only extras (cv2-enumerate-cameras, wmi) are declared with
# sys_platform == "win32" markers in requirements.txt so pip skips them
# automatically on Linux and macOS.  No extra step needed here.

echo "==> Installing Player One Camera SDK (pyPOACamera + native library)..."
echo "    Downloads SDK from player-one-astronomy.com into vendor/playerone/"
echo "    Safe to skip if you don't have a Player One camera."
if [ "$SKIP_VENV" = true ]; then
    python3 scripts/install_playerone_sdk.py || {
        echo "WARNING: Player One SDK install failed or was skipped."
    }
else
    python scripts/install_playerone_sdk.py || {
        echo "WARNING: Player One SDK install failed or was skipped."
    }
fi

echo ""
echo "============================================================"
echo " Setup complete!"
echo ""
if [ "$SKIP_VENV" = false ]; then
    echo " To launch the application using the virtual environment:"
    echo "   source .venv/bin/activate"
    echo "   python main.py"
else
    echo " To launch the application directly:"
    echo "   python3 main.py"
fi
echo ""
echo " NOTE FOR RASPBERRY PI USERS:"
echo " If you have installed system-level dependencies (e.g., python3-libcamera),"
echo " you can also run the app directly using the system Python:"
echo "   python3 main.py"
echo " (Ensure you've run: sudo apt install python3-pyside6 python3-opencv python3-serial)"
echo "============================================================"
