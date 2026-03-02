@echo off
REM =============================================================================
REM RoboCam-Suite 2.0 — Setup Script (Windows)
REM =============================================================================
REM Creates a virtual environment named .venv and installs all dependencies.
REM Run once after cloning:
REM   setup.bat
REM
REM To activate the environment afterwards:
REM   .venv\Scripts\activate
REM =============================================================================

echo =^> Checking Python version...
python --version
IF ERRORLEVEL 1 (
    echo ERROR: Python not found. Please install Python 3.10+ and add it to PATH.
    exit /b 1
)

echo =^> Creating virtual environment in '.venv'...
python -m venv .venv

echo =^> Activating virtual environment...
call .venv\Scripts\activate

echo =^> Upgrading pip...
pip install --upgrade pip

echo =^> Installing RoboCam-Suite and its dependencies (including Windows camera extras)...
echo    cv2-enumerate-cameras : shows real device names (e.g. "Iriun Webcam" instead of "USB Camera (index 0)")
echo    wmi                   : detects WIA Imaging Devices (scanners, scientific cameras)
pip install -e ".[windows]"
IF ERRORLEVEL 1 (
    echo WARNING: Could not install Windows camera extras.
    echo          Camera devices will show as "USB Camera (index N)" instead of their real names.
    echo          To install manually:  pip install cv2-enumerate-cameras wmi
)

echo.
echo ============================================================
echo  Setup complete!
echo.
echo  To activate the environment, run:
echo    .venv\Scripts\activate
echo.
echo  To launch the application:
echo    python main.py
echo    -- or --
echo    python -m robocam_suite
echo ============================================================
