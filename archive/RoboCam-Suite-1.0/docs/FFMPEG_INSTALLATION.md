# FFmpeg Installation Guide

## Overview

FFmpeg is required for **Picamera2 (Grayscale - High FPS)** capture mode, which uses hardware-accelerated video encoding for optimal performance on Raspberry Pi 4.

**Note**: FFmpeg is often **already installed** on Raspberry Pi OS (especially newer versions). The setup script will detect if it's present and skip installation if it's already available.

## Why FFmpeg is Needed

The high-FPS capture mode (`picamera2_highfps_capture.py`) uses FFmpeg to:
- Encode grayscale video using Raspberry Pi's hardware video encoder (v4l2-m2m)
- Achieve real-time recording with minimal CPU usage (GPU handles encoding)
- Support high resolutions (up to sensor maximum)
- Produce reasonable file sizes with hardware H.264/HEVC encoding

**Without FFmpeg**: The `record_with_ffmpeg()` method will fail with "FFmpeg executable not found" error.

## Installation Methods

### Method 1: Automatic Installation (Recommended)

The setup script automatically detects and installs FFmpeg:

```bash
./setup.sh
```

The script will:
1. Check if `ffmpeg` command is available
2. If missing, add it to required dependencies
3. Automatically install it via `apt-get` (requires sudo)

### Method 2: Manual Installation

If you prefer to install FFmpeg manually, or if automatic installation fails:

```bash
# Update package list
sudo apt-get update

# Install ffmpeg
sudo apt-get install -y ffmpeg
```

### Method 3: Verify Existing Installation (Most Common)

FFmpeg is often **already installed** on Raspberry Pi OS. To check:

```bash
# Check if ffmpeg is available
ffmpeg -version
```

If the command works and shows version information, FFmpeg is already installed and ready to use. The setup script will detect this automatically and skip installation.

**Common on Raspberry Pi OS**: Many Raspberry Pi OS images come with FFmpeg pre-installed, especially:
- Raspberry Pi OS Bullseye (Debian 11)
- Raspberry Pi OS Bookworm (Debian 12)
- Raspberry Pi OS with desktop environment

## Verification

After installation, verify FFmpeg is working correctly:

```bash
# Check version and build information
ffmpeg -version

# Test hardware encoder availability (should show h264_v4l2m2m)
ffmpeg -encoders | grep v4l2m2m
```

Expected output should include:
- `h264_v4l2m2m` - Hardware H.264 encoder
- `hevc_v4l2m2m` - Hardware HEVC encoder (Pi 4+)

## Troubleshooting

### Problem: "FFmpeg executable not found"

**Symptoms:**
- Error message: `FFmpeg executable not found: ffmpeg`
- High-FPS capture mode fails to start

**Solutions:**

1. **Install FFmpeg:**
   ```bash
   sudo apt-get update
   sudo apt-get install -y ffmpeg
   ```

2. **Verify installation:**
   ```bash
   which ffmpeg
   ffmpeg -version
   ```

3. **If FFmpeg is installed but not in PATH:**
   - Check if it's in a non-standard location: `find /usr -name ffmpeg 2>/dev/null`
   - Create symlink if needed: `sudo ln -s /path/to/ffmpeg /usr/local/bin/ffmpeg`

### Problem: Hardware encoder not available

**Symptoms:**
- FFmpeg works but hardware encoding fails
- Error: `Unknown encoder 'h264_v4l2m2m'`

**Solutions:**

1. **Check encoder availability:**
   ```bash
   ffmpeg -encoders | grep v4l2m2m
   ```

2. **If hardware encoders are missing:**
   - Update Raspberry Pi OS: `sudo apt-get update && sudo apt-get upgrade`
   - Reinstall FFmpeg: `sudo apt-get install --reinstall ffmpeg`
   - Hardware encoders require Raspberry Pi 4 or newer

3. **Alternative: Use software encoder (slower, higher CPU):**
   - Modify code to use `libx264` instead of `h264_v4l2m2m`
   - Not recommended for high-FPS capture

### Problem: Package not found in repositories

**Symptoms:**
- `apt-get install ffmpeg` fails with "Package not found"

**Solutions:**

1. **Update package lists:**
   ```bash
   sudo apt-get update
   ```

2. **Check if package exists:**
   ```bash
   apt-cache search ffmpeg
   ```

3. **If still not found:**
   - Ensure you're using Raspberry Pi OS (not generic Linux)
   - Check `/etc/apt/sources.list` for correct repositories
   - Try: `sudo apt-get install ffmpeg -y --fix-missing`

## System Requirements

- **Raspberry Pi OS** (Bullseye or Bookworm recommended)
- **Raspberry Pi 4 or newer** (for hardware encoder support)
- **Root/sudo access** (for installation)

## Hardware Encoder Support

The following hardware encoders are available on Raspberry Pi:

| Encoder | Pi Model | Codec | Usage |
|---------|----------|-------|-------|
| `h264_v4l2m2m` | Pi 4+ | H.264 | Default, recommended |
| `hevc_v4l2m2m` | Pi 4+ | HEVC/H.265 | Better compression, newer |

**Note:** Older Raspberry Pi models (Pi 3 and earlier) may not have hardware encoder support. Software encoding will work but is much slower.

## Testing FFmpeg with High-FPS Capture

After installation, test the high-FPS capture mode:

```python
from robocam.picamera2_highfps_capture import Picamera2HighFpsCapture

# Create capture instance
capture = Picamera2HighFpsCapture(width=1920, height=1080, fps=30)

# Record with FFmpeg hardware encoding
frames = capture.record_with_ffmpeg(
    output_path="test_output.mp4",
    codec="h264_v4l2m2m",
    bitrate="12M",
    duration_seconds=10
)

capture.stop_capture()
```

If this works without errors, FFmpeg is correctly installed and configured.

## Additional Resources

- **FFmpeg Documentation**: https://ffmpeg.org/documentation.html
- **Raspberry Pi Hardware Encoding**: https://www.raspberrypi.com/documentation/computers/camera_software.html
- **v4l2-m2m Encoder**: Hardware video encoder used by Raspberry Pi for efficient encoding

## Summary

**Quick Installation:**
```bash
sudo apt-get update
sudo apt-get install -y ffmpeg
ffmpeg -version  # Verify
```

**Automatic Installation:**
```bash
./setup.sh  # Installs ffmpeg automatically if missing
```

FFmpeg is essential for high-performance video encoding in high-FPS capture mode. The setup script handles installation automatically, but manual installation is straightforward if needed.

