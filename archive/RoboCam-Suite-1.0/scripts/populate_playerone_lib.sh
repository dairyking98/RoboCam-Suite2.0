#!/bin/bash
# Ensure Player One SDK is present on Linux: download + full extract if missing or incomplete.
# Keeps a copy of the tarball in the repo root (RoboCam-Suite/PlayerOne_Camera_SDK_Linux_V3.10.0.tar.gz).
# Run from repo root. Invoked by start_preview.sh, start_experiment.sh, etc. on Linux.

if [ "$(uname -s)" != "Linux" ]; then
  exit 0
fi

# Resolve repo root from this script's path (works when run as bash path/to/this/script or from repo root)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT" || exit 1

SDK_DIR="PlayerOne_Camera_SDK_Linux_V3.10.0"
TARBALL_NAME="PlayerOne_Camera_SDK_Linux_V3.10.0.tar.gz"
URL="https://player-one-astronomy.com/download/softwares/PlayerOne_Camera_SDK_Linux_V3.10.0.tar.gz"
# Keep tarball in repo root
TARBALL="$REPO_ROOT/$TARBALL_NAME"

echo "Player One SDK: checking..."

# If SDK dir exists but is incomplete (missing python or lib), remove it so we full-extract again
if [ -d "$SDK_DIR" ]; then
  if [ ! -f "$SDK_DIR/python/pyPOACamera.py" ]; then
    echo "Player One SDK: existing folder incomplete (missing python), re-extracting..."
    rm -rf "$SDK_DIR"
  elif [ ! -d "$SDK_DIR/lib/arm64" ] && [ ! -d "$SDK_DIR/lib/aarch64" ]; then
    echo "Player One SDK: existing folder incomplete (missing lib/), re-extracting..."
    rm -rf "$SDK_DIR"
  fi
fi

# Download tarball to repo root if missing
if [ ! -f "$TARBALL" ]; then
  echo "Player One SDK: downloading to $TARBALL_NAME ..."
  if ! wget -O "$TARBALL" "$URL"; then
    echo "Player One SDK: download failed (check network). Continuing without SDK."
    exit 0
  fi
  echo "Player One SDK: saved to $TARBALL_NAME"
fi

# Full extract if SDK dir is missing
if [ ! -d "$SDK_DIR" ]; then
  echo "Player One SDK: fully extracting to $REPO_ROOT ..."
  if ! tar -xzf "$TARBALL" -C "$REPO_ROOT"; then
    echo "Player One SDK: extract failed. Continuing without SDK."
    exit 0
  fi
  if [ -f "$SDK_DIR/python/pyPOACamera.py" ]; then
    echo "Player One SDK: extracted to $SDK_DIR (full SDK, tarball kept at $TARBALL_NAME)"
  else
    echo "Player One SDK: extracted to $SDK_DIR (python/ not in archive; set PLAYERONE_SDK_PYTHON if needed)"
  fi
  exit 0
fi

echo "Player One SDK: already present."
exit 0
