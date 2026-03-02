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
    return (vd / "pyPOACamera.py").exists()


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
            # Allow partial match (e.g. "python/pyPOACamera.py" matches
            # "PlayerOne_Camera_SDK_Windows_V3.10.0/python/pyPOACamera.py")
            match = next((n for n in names if n.endswith(src_path)), None)
            if match is None:
                print(f"  WARNING: {src_path!r} not found in archive — skipping.")
                continue
            content = zf.read(match)
            out = dest / dst_name
            out.write_bytes(content)
            print(f"  Extracted: {dst_name}")


def _extract_tar(data: bytes, extract_map: dict[str, str], dest: Path):
    with tarfile.open(fileobj=io.BytesIO(data)) as tf:
        members = tf.getnames()
        for src_path, dst_name in extract_map.items():
            match = next((m for m in members if m.endswith(src_path)), None)
            if match is None:
                print(f"  WARNING: {src_path!r} not found in archive — skipping.")
                continue
            member = tf.getmember(match)
            f = tf.extractfile(member)
            if f is None:
                continue
            content = f.read()
            out = dest / dst_name
            out.write_bytes(content)
            print(f"  Extracted: {dst_name}")


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

    print(f"Installing Player One Camera SDK for {os_name} …")
    try:
        data = _download(url)
    except Exception as e:
        print(f"  ERROR: Download failed: {e}")
        print("  Please download the SDK manually from:")
        print(f"  {url}")
        print("  and extract pyPOACamera.py + the native library into vendor/playerone/")
        sys.exit(1)

    if url.endswith(".zip"):
        _extract_zip(data, extract_map, dest)
    else:
        _extract_tar(data, extract_map, dest)

    print(f"\nPlayer One SDK installed to: {dest}")
    print("You can now use 'playerone' as the camera driver in the Setup tab.")


if __name__ == "__main__":
    main()
