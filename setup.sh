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
