# Player One Mars 662M (and Mars cameras) on Raspberry Pi

## Why this is needed

The **Player One Mars 662M** (and similar Mars cameras) are **not standard UVC webcams**. They use a proprietary USB protocol and the **Player One Camera SDK**. They do **not** show up as `/dev/video*` and are not supported by the generic `uvcvideo` driver.

- **RoboCam-Suite** supports the Mars 662M (and similar Player One cameras) via a **Player One SDK backend** when the SDK is installed and the SDK Python folder is available (see step 5 below). It also supports **V4L2/USB** cameras and **Raspberry Pi HQ (Picamera2)**.
- You can also use the camera with INDI or other compatible software (e.g. AstroDMx).

---

## On the Pi – quick setup (what to do and what’s automated)

| Step | What to do | Automated? |
|------|------------|------------|
| **1. SDK** | Nothing. On first run of `./start_preview.sh` (or any launcher), the script downloads and extracts the Player One SDK into the project and keeps the tarball in the repo root. | Yes – `scripts/populate_playerone_lib.sh` runs from the launchers on Linux. |
| **2. pyPOACamera.py** | Nothing. The app patches the SDK’s `pyPOACamera.py` to load `libPlayerOneCamera.so` on Linux (by name, so `LD_LIBRARY_PATH` from the launcher is used). | Yes – `_ensure_pypoa_patched_for_linux()` in `robocam/playerone_camera.py` runs when the app uses the SDK. |
| **3. USB permissions** | Run **once**: `bash scripts/setup_playerone_udev.sh` (prompts for sudo). Then unplug and replug the camera. | One-time – run `scripts/setup_playerone_udev.sh` yourself; it installs the udev rule for Mars 662M (vendor a0a0, product 6621). For other cameras, use: `bash scripts/setup_playerone_udev.sh <vendor_hex> <product_hex>` (e.g. from `lsusb`). |

**Order on a fresh Pi:** run `./setup.sh`, then `bash scripts/setup_playerone_udev.sh`, unplug/replug the camera, then `./start_preview.sh`.

---

## Option 1: Install the Player One Linux SDK (for development)

Use this if you want to write or build software that talks to the camera via the official API.

### 1. Download the SDK

- **Software page:** https://player-one-astronomy.com/service/software/
- Under **Camera SDK**, use the **Linux** link (same archive for Raspberry Pi).
- Current version as of this doc: **V3.10.0** (see [SDK History](https://player-one-astronomy.com/service/software/sdk-history/) for newer versions).
- Direct download: https://player-one-astronomy.com/download/softwares/PlayerOne_Camera_SDK_Linux_V3.10.0.tar.gz

On the Pi:

```bash
cd ~
wget https://player-one-astronomy.com/download/softwares/PlayerOne_Camera_SDK_Linux_V3.10.0.tar.gz
tar -xzf PlayerOne_Camera_SDK_Linux_V3.10.0.tar.gz
cd PlayerOne_Camera_SDK_Linux_V3.10.0
ls
```

### 2. Install libraries and headers

Typical layout inside the tarball:

- `lib/` – shared libraries, often in an arch subfolder (e.g. `lib/aarch64/`, `lib/arm64/`, or `lib/armhf/` for Pi)
- `include/` – C/C++ headers
- Sometimes `README` or `ReleaseNotes` with exact steps

RoboCam-Suite uses only **real `.so` files** in `lib/` (no symlinks). The repo tracks `PlayerOne_Camera_SDK_Linux_V3.10.0/lib/`, so once that folder is committed, **push from Windows works on the Pi**.

**If you extracted the tar on Windows:** ensure the real `.so` files are in the project SDK `lib/`. Run `scripts/populate_playerone_lib.sh` on the Pi once if `lib/` is missing, then commit and push so push-from-Windows works on the Pi.

**Generic steps (run these from inside the extracted SDK folder):**

```bash
cd ~/PlayerOne_Camera_SDK_Linux_V3.10.0

# See what arch subfolder the SDK uses (V3.10.0 often has arm64, not aarch64)
ls lib/
```

Then copy from the folder you see (use its name in place of `FOLDER` below). On 64-bit Raspberry Pi OS, it is often **`arm64`** even though `uname -m` is `aarch64`:

```bash
# If ls lib/ showed e.g. arm64, aarch64, or armhf:
sudo cp -P lib/FOLDER/*.so* /usr/local/lib/
sudo ldconfig
sudo cp -r include/* /usr/local/include/
```

Example for 64-bit Pi when the folder is `arm64`:

```bash
sudo cp -P lib/arm64/*.so* /usr/local/lib/
sudo ldconfig
sudo cp -r include/* /usr/local/include/
```

If the tarball has a different structure (e.g. no arch subfolder), open the extracted folder and copy:

- All `.so` / `.so.*` files → `/usr/local/lib/`, then run `sudo ldconfig`
- Any `.h` files or include folder → `/usr/local/include/`

### 3. USB permissions (so non-root can access the camera)

Create a udev rule so the Mars 662M is accessible without sudo. Vendor:Product for Mars 662M is **a0a0:6621**.

```bash
echo 'SUBSYSTEM=="usb", ATTRS{idVendor}=="a0a0", ATTRS{idProduct}=="6621", MODE="0666"' | sudo tee /etc/udev/rules.d/99-playerone-mars662m.rules
sudo udevadm control --reload-rules
sudo udevadm trigger
# Unplug and replug the camera
```

### 4. Test (if the SDK includes a sample app)

If the SDK contains a sample executable or build instructions, run or build it to confirm the camera is detected.

### 5. Python bindings on Linux

The SDK’s `python/` folder includes **pyPOACamera.py** and **POA_Camera_Test.py**, but they are written for **Windows** (they load `PlayerOneCamera.dll`). On Linux you must patch the wrapper to load the shared library (`.so`) you installed in step 2. Follow 5.1–5.3 in order.

#### 5.1 Find the installed library name

From the Pi:

```bash
ls /usr/local/lib/lib*PlayerOne* /usr/local/lib/lib*POA* 2>/dev/null
```

If that shows nothing:

```bash
ls /usr/local/lib/*.so* 2>/dev/null | xargs -I {} basename {}
```

Look for a name like **libPlayerOne_camera.so** or **libPOACamera.so**. Note the exact name (without the path) — you'll use it in 5.2 as `LIBNAME`.

#### 5.2 Patch pyPOACamera.py

1. Open the file:
   ```bash
   cd ~/PlayerOne_Camera_SDK_Linux_V3.10.0/python
   nano pyPOACamera.py
   ```

2. At the top, ensure `sys` is imported. If there is no `import sys`, add it with the other imports (e.g. after `from ctypes import *`).

3. Find the single line that loads the DLL, for example:
   ```python
   dll = cdll.LoadLibrary("./PlayerOneCamera.dll") # Windows, if your python is 64bit...
   ```

4. Replace that **entire line** with the following block (use the library name from 5.1 in place of `libPlayerOne_camera.so` if it differs):

   ```python
   import sys
   if sys.platform == "win32":
       dll = cdll.LoadLibrary("./PlayerOneCamera.dll")
   else:
       dll = cdll.LoadLibrary("libPlayerOne_camera.so")
   ```

   If you already added `import sys` in step 2, omit the `import sys` inside this block. Save and exit (in nano: Ctrl+O, Enter, Ctrl+X).

#### 5.3 Run the Python test

With the camera plugged in (and udev rules applied, step 3):

```bash
cd ~/PlayerOne_Camera_SDK_Linux_V3.10.0/python
python POA_Camera_Test.py
```

If you see `OSError: libPlayerOne_camera.so: cannot open shared object file`, the library name is wrong or not on the loader path. Confirm with `ldconfig -p | grep -i player` and use that exact name in 5.2. You can also try:

```bash
LD_LIBRARY_PATH=/usr/local/lib python POA_Camera_Test.py
```

#### 5.4 Where to put the SDK (RoboCam-Suite)

**Option 1: Full SDK folder in project root (simplest)**

Drop the **entire** extracted SDK folder inside RoboCam-Suite, e.g.:

```
RoboCam-Suite/
  PlayerOne_Camera_SDK_Linux_V3.10.0/   ← full SDK (lib/, python/, include/, ...)
  preview.py
  ...
```

RoboCam-Suite will use **`PlayerOne_Camera_SDK_Linux_V3.10.0/python`** for the Python bindings and add **`lib/arm64`** (or **`lib/aarch64`**, **`lib/armhf`**) to the library path. No copying of files needed. Just patch **`PlayerOne_Camera_SDK_Linux_V3.10.0/python/pyPOACamera.py`** for Linux (step 5.2) so it loads the library by name (e.g. `LoadLibrary("libPlayerOne_camera.so")`). Run `./start_preview.sh` from the project root.

**Alternative: system path**  
Install the .so in `/usr/local/lib/` (step 2), copy it with the name the SDK expects if different, patch pyPOACamera to load by name, and set `LD_LIBRARY_PATH=/usr/local/lib` when running (the launcher scripts already do this).

#### 5.4.1 Pushed from Windows – will it work on the Pi?

**Yes, once the repo has real `.so` files in `PlayerOne_Camera_SDK_Linux_V3.10.0/lib/`.** The repo tracks that folder (no symlinks). Push from Windows works on the Pi after that.

**If `lib/` is not in the repo yet:** run `scripts/populate_playerone_lib.sh` on the Pi once. It downloads the SDK tarball, extracts it, and copies `lib/` into the project SDK folder. Then run `git add PlayerOne_Camera_SDK_Linux_V3.10.0/lib/`, commit, and push. After that, push-from-Windows works on the Pi.

#### 5.5 OpenCV GUI error (cv2.namedWindow) on “Video Mode”

The test script opens a live preview window with OpenCV (`cv2.namedWindow`). If you see:

```text
cv2.error: ... The function is not implemented. Rebuild the library with Windows, GTK+ 2.x or Cocoa support.
```

then your OpenCV build has no GUI support (e.g. **opencv-python-headless**). The camera is already working: “Connected POA Camera Count: 1”, “Get Camera Properties”, and single-frame capture have all succeeded. The script fails only when it starts the continuous “Video Mode” preview.

**Options:**

- **Treat as success** – If you only needed to confirm the camera and SDK work, you can stop here. Detection, properties, and single-frame capture are fine.
- **Enable the live preview** – You need OpenCV built with GUI (GTK on Linux). On Raspberry Pi OS / Debian:
  ```bash
  sudo apt-get update
  sudo apt-get install -y libgtk2.0-dev pkg-config
  pip install opencv-python   # GUI build; use a separate venv if your project uses opencv-python-headless
  ```
  Then run `POA_Camera_Test.py` again (with a display connected, or over X11 forwarding if SSH). Note: RoboCam-Suite uses **opencv-python-headless** on purpose; install **opencv-python** only in a separate venv or environment used for this SDK test if you want to avoid conflicts.

#### 5.6 Alternative: C examples or INDI

If you prefer not to patch Python: the SDK may include C/C++ code under `examples/` — build and run one of those to test the camera. Otherwise use **INDI** (Option 2 below) for a ready-made Linux workflow without the Python wrapper.

---

## Option 2: Use INDI (ready-made driver on Pi)

**INDI** supports Player One cameras via the **indi-playone** driver. This lets you use the camera from INDI-based software (e.g. KStars, AstroDMx) without writing C code.

- **INDI:** https://www.indilib.org/
- **indi-playone** is in the **indi-3rdparty** package: https://github.com/indilib/indi-3rdparty/releases

On Raspberry Pi / Debian you can often install INDI from the Mutlaq PPA or from your distro’s packages. Example (adjust for your OS):

```bash
# Example for Raspberry Pi OS / Debian (check indilib.org for current instructions)
sudo add-apt-repository ppa:mutlaqja/ppa
sudo apt-get update
sudo apt-get install indi-full  # or indi-bin + indi-playone if available
```

After installation, start an INDI server (e.g. **KStars** or **INDI Web Manager**), add the **Player One** camera driver, and connect the Mars 662M.

**AstroDMx Capture** is also listed by Player One as supporting their cameras on Linux/Raspberry Pi: https://www.astrodmx-capture.org.uk/astrodmx-capture-downloads/

---

## Summary

| Goal | What to do |
|------|------------|
| Use the camera in existing astronomy apps | Install **INDI** + **indi-playone**, or use **AstroDMx Capture**. |
| Develop your own app that uses the camera | Install the **Player One Linux SDK** (Option 1), then link against the provided libraries and use the SDK API. |
| Use the camera inside RoboCam-Suite | Install the SDK (Option 1, steps 1–3), patch Python (step 5), set **PLAYERONE_SDK_PYTHON** to the SDK `python` folder. RoboCam-Suite then offers **Player One (Grayscale)** for preview and recording. |

**References**

- Player One software (SDK download): https://player-one-astronomy.com/service/software/
- SDK history (newer versions): https://player-one-astronomy.com/service/software/sdk-history/
- INDI: https://www.indilib.org/
- INDI 3rd party (indi-playone): https://github.com/indilib/indi-3rdparty/releases
