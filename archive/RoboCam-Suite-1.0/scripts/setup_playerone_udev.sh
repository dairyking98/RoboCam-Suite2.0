#!/bin/bash
# One-time setup: install udev rule so the Player One camera (e.g. Mars 662M) is
# accessible without root. Run on the Pi once: bash scripts/setup_playerone_udev.sh
# (will use sudo to write to /etc/udev/rules.d/).
#
# Usage:
#   bash scripts/setup_playerone_udev.sh              # Mars 662M (default: a0a0:6621)
#   bash scripts/setup_playerone_udev.sh a0a0 6621    # custom vendor product (hex)
#   sudo bash scripts/setup_playerone_udev.sh         # run with sudo directly

set -e

VENDOR="${1:-a0a0}"
PRODUCT="${2:-6621}"
RULES_FILE="/etc/udev/rules.d/99-playerone-mars662m.rules"
RULE="SUBSYSTEM==\"usb\", ATTRS{idVendor}==\"${VENDOR}\", ATTRS{idProduct}==\"${PRODUCT}\", MODE=\"0666\""

echo "Player One udev rule: ${VENDOR}:${PRODUCT} -> ${RULES_FILE}"

if [ ! -w /etc/udev/rules.d 2>/dev/null ]; then
  TMP="$(mktemp)"
  echo "$RULE" > "$TMP"
  sudo cp "$TMP" "$RULES_FILE"
  rm -f "$TMP"
  sudo udevadm control --reload-rules
  sudo udevadm trigger
else
  echo "$RULE" > "$RULES_FILE"
  udevadm control --reload-rules
  udevadm trigger
fi

echo "Done. Unplug and replug the Player One camera, then run ./start_preview.sh"
