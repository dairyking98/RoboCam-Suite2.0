#!/bin/bash
# RoboCam-Suite Calibration Application Launcher

set -e  # Exit on error

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"
# On Linux: ensure Player One SDK is present (download + full extract if missing)
if [ "$(uname -s)" = "Linux" ]; then
  echo "Checking Player One SDK..."
  if [ -f "$SCRIPT_DIR/scripts/populate_playerone_lib.sh" ]; then
    bash "$SCRIPT_DIR/scripts/populate_playerone_lib.sh" || true
  else
    echo "Warning: scripts/populate_playerone_lib.sh not found."
  fi
fi

# Player One SDK: full SDK in project root (lib/arm64 or lib/aarch64), then /usr/local/lib
for sdk_dir in "PlayerOne_Camera_SDK_Linux_V3.10.0" "PlayerOne_Camera_SDK_Linux_"*; do
  if [ -d "$SCRIPT_DIR/$sdk_dir" ]; then
    for arch in arm64 aarch64 armhf; do
      if [ -d "$SCRIPT_DIR/$sdk_dir/lib/$arch" ]; then
        export LD_LIBRARY_PATH="$SCRIPT_DIR/$sdk_dir/lib/$arch${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
      fi
    done
    break
  fi
done 2>/dev/null || true
export LD_LIBRARY_PATH="/usr/local/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "Error: Virtual environment not found. Please run ./setup.sh first."
    exit 1
fi

# Activate virtual environment
source venv/bin/activate

# Check if calibrate.py exists
if [ ! -f "calibrate.py" ]; then
    echo "Error: calibrate.py not found in current directory."
    exit 1
fi

# Create log directory if it doesn't exist
mkdir -p logs

# Run the calibration application
echo "Starting RoboCam-Suite Calibration Application..."
echo "Log file: logs/calibrate_$(date +%Y%m%d_%H%M%S).log"
echo ""

# Pass through all command-line arguments (e.g., --simulate_3d, --simulate_cam, --backend)
# Examples:
#   ./start_calibrate.sh --simulate_3d
#   ./start_calibrate.sh --simulate_cam
#   ./start_calibrate.sh --simulate_3d --simulate_cam
#   ./start_calibrate.sh --backend qtgl
python calibrate.py "$@" 2>&1 | tee "logs/calibrate_$(date +%Y%m%d_%H%M%S).log"

# Deactivate virtual environment on exit
deactivate

