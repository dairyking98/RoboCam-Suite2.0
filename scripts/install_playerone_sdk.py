"""
install_playerone_sdk.py
========================
Downloads the Player One Camera SDK for the current platform and extracts
the Python wrapper (pyPOACamera.py) and the native library into
``<project_root>/vendor/playerone/``.

Run once after cloning, or re-run to update to the latest SDK version.

Usage
-----
    python scripts/install_playerone_sdk.py

The script is called automatically by ``setup.bat`` (Windows) and
``setup.sh`` (Linux / macOS).
"""
from __future__ import annotations

import io
import os
import platform
import shutil
import sys
import tarfile
import zipfile
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# SDK download URLs (update when Player One releases a new version)
# ---------------------------------------------------------------------------
SDK_URLS = {
    "Windows": "https://player-one-astronomy.com/download/softwares/PlayerOne_Camera_SDK_Windows_V3.10.0.zip",
    "Linux":   "https://player-one-astronomy.com/download/softwares/PlayerOne_Camera_SDK_Linux_V3.10.0.tar.gz",
    "Darwin":  "https://player-one-astronomy.com/download/softwares/PlayerOne_Camera_SDK_MacOS_V3.10.0.tar.gz",
}

# Files to extract from the archive (source path inside zip → destination filename)
EXTRACT_MAP: dict[str, dict[str, str]] = {
    "Windows": {
        "python/pyPOACamera.py":        "pyPOACamera.py",
        "lib/x64/PlayerOneCamera.dll":  "PlayerOneCamera.dll",
    },
    "Linux": {
        "python/pyPOACamera.py":                     "pyPOACamera.py",
        "lib/x64/libPlayerOneCamera.so.3.10.0":      "libPlayerOneCamera.so.3.10.0",
        "lib/x64/libPlayerOneCamera.so.3":           "libPlayerOneCamera.so.3",
        "lib/x64/libPlayerOneCamera.so":             "libPlayerOneCamera.so",
        # Support for Raspberry Pi (ARM)
        "lib/armv7/libPlayerOneCamera.so.3.10.0":    "libPlayerOneCamera.so.3.10.0",
        "lib/armv7/libPlayerOneCamera.so.3":         "libPlayerOneCamera.so.3",
        "lib/armv7/libPlayerOneCamera.so":           "libPlayerOneCamera.so",
        "lib/armv8/libPlayerOneCamera.so.3.10.0":    "libPlayerOneCamera.so.3.10.0",
        "lib/armv8/libPlayerOneCamera.so.3":         "libPlayerOneCamera.so.3",
        "lib/armv8/libPlayerOneCamera.so":           "libPlayerOneCamera.so",
    },
    "Darwin": {
        "python/pyPOACamera.py":                          "pyPOACamera.py",
        "lib/x64/libPlayerOneCamera.dylib.3.10.0":        "libPlayerOneCamera.dylib.3.10.0",
        "lib/x64/libPlayerOneCamera.dylib.3":             "libPlayerOneCamera.dylib.3",
        "lib/x64/libPlayerOneCamera.dylib":               "libPlayerOneCamera.dylib",
    },
}


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _vendor_dir() -> Path:
    return _project_root() / "vendor" / "playerone"


def _already_installed() -> bool:
    vd = _vendor_dir()
    # If the folder exists, we check if the .so is for the right architecture
    if not (vd / "pyPOACamera.py").exists():
        return False
    
    # Simple check: if we are on Linux and have an x86 .so on an ARM machine, we need to reinstall
    if platform.system() == "Linux":
        lib_path = vd / "libPlayerOneCamera.so"
        if lib_path.exists():
            # Run 'file' to check architecture
            import subprocess
            try:
                out = subprocess.check_output(["file", str(lib_path)], stderr=subprocess.STDOUT).decode()
                arch = platform.machine().lower()
                is_arm = "aarch64" in arch or "arm" in arch
                is_x86 = "x86-64" in out or "x86_64" in out
                if is_arm and is_x86:
                    print("  Detected x86 library on ARM system. Reinstalling correct architecture...")
                    return False
            except Exception:
                pass
    return True


def _download(url: str) -> bytes:
    print(f"  Downloading {url} …", flush=True)
    req = urllib.request.Request(url, headers={"User-Agent": "RoboCam-Suite/2.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        total = int(resp.headers.get("Content-Length", 0))
        data = bytearray()
        chunk = 65536
        while True:
            block = resp.read(chunk)
            if not block:
                break
            data.extend(block)
            if total:
                pct = len(data) * 100 // total
                print(f"\r  {pct:3d}%  {len(data)//1024} KB / {total//1024} KB", end="", flush=True)
        print()
    return bytes(data)


def _extract_zip(data: bytes, extract_map: dict[str, str], dest: Path):
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()
        for src_path, dst_name in extract_map.items():
            match = next((n for n in names if n.endswith(src_path)), None)
            if match is None:
                continue
            content = zf.read(match)
            out = dest / dst_name
            out.write_bytes(content)
            print(f"  Extracted: {dst_name}")


def _extract_tar(data: bytes, extract_map: dict[str, str], dest: Path):
    with tarfile.open(fileobj=io.BytesIO(data)) as tf:
        members = tf.getnames()
        arch = platform.machine().lower() # e.g. 'x86_64', 'aarch64', 'armv7l'
        
        # Priority order for architectures in the SDK
        # For aarch64/arm64, we prefer armv8, then armv7, then x64 (which will fail later)
        if arch in ["aarch64", "arm64"]:
            preferred_archs = ["armv8", "armv7", "x64"]
        elif arch.startswith("armv7"):
            preferred_archs = ["armv7", "x64"]
        else:
            preferred_archs = ["x64"]

        # 1. Extract the Python wrapper (it's the same for all archs)
        wrapper_src = "python/pyPOACamera.py"
        match = next((m for m in members if m.endswith(wrapper_src)), None)
        if match:
            content = tf.extractfile(tf.getmember(match)).read()
            (dest / "pyPOACamera.py").write_bytes(content)
            print(f"  Extracted: pyPOACamera.py")

        # 2. Extract the library for the best matching architecture
        lib_basenames = ["libPlayerOneCamera.so", "libPlayerOneCamera.so.3", "libPlayerOneCamera.so.3.10.0"]
        for base in lib_basenames:
            found_best = False
            for p_arch in preferred_archs:
                # We need to find the full path in the tar that ends with lib/{p_arch}/{base}
                # e.g. "PlayerOne_Camera_SDK_Linux_V3.10.0/lib/armv8/libPlayerOneCamera.so"
                src_pattern = f"lib/{p_arch}/{base}"
                match = next((m for m in members if m.endswith(src_pattern)), None)
                if match:
                    content = tf.extractfile(tf.getmember(match)).read()
                    (dest / base).write_bytes(content)
                    print(f"  Extracted: {base} (from {src_pattern})")
                    found_best = True
                    break
            if not found_best:
                print(f"  WARNING: Could not find {base} for any preferred architecture {preferred_archs}")


def main():
    os_name = platform.system()
    if os_name not in SDK_URLS:
        print(f"Unsupported platform: {os_name}")
        sys.exit(1)

    if _already_installed():
        print("Player One SDK already installed in vendor/playerone/ — skipping.")
        print("  (Delete vendor/playerone/ and re-run to force a fresh install.)")
        return

    url = SDK_URLS[os_name]
    extract_map = EXTRACT_MAP[os_name]
    dest = _vendor_dir()
    dest.mkdir(parents=True, exist_ok=True)

    print(f"Installing Player One Camera SDK for {os_name} ({platform.machine()}) …")
    try:
        data = _download(url)
    except Exception as e:
        print(f"  ERROR: Download failed: {e}")
        sys.exit(1)

    # DEBUG: List all files in the archive to see the exact structure
    print("\n--- SDK Archive Structure (Debug) ---")
    if url.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for name in zf.namelist()[:50]: # First 50 files
                print(f"  {name}")
    else:
        with tarfile.open(fileobj=io.BytesIO(data)) as tf:
            for name in tf.getnames()[:100]: # First 100 files
                print(f"  {name}")
    print("------------------------------------\n")

    if url.endswith(".zip"):
        _extract_zip(data, extract_map, dest)
    else:
        _extract_tar(data, extract_map, dest)

    print(f"\nPlayer One SDK installed to: {dest}")


if __name__ == "__main__":
    main()
