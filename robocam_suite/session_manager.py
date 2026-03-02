"""
SessionManager — persists UI state and named experiment presets.

Two separate files are maintained:
  - session.json   : last-used values for every UI field (auto-saved on close)
  - presets.json   : named presets the user explicitly saves and recalls

Both files live in a platform-appropriate user-data directory so they are
never accidentally committed to git.
"""

import json
import os
import sys
from copy import deepcopy
from typing import Any, Dict, List, Optional


def _user_data_dir() -> str:
    """Return a writable, platform-appropriate directory for app data."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
    path = os.path.join(base, "RoboCam-Suite")
    os.makedirs(path, exist_ok=True)
    return path


# Default values for every UI field that should be persisted.
# These are used when no session file exists yet (first run).
DEFAULT_SESSION: Dict[str, Any] = {
    "experiment": {
        "name": "my_experiment",
        "well_plate_width": 12,
        "well_plate_depth": 8,
        "pre_laser_delay": 0.5,
        "laser_on_duration": 1.0,
        "recording_duration": 5.0,
        "post_well_delay": 0.5,
    },
    "calibration": {
        "step_size": "1.0",
        "corners": {
            "Upper-Left": None,
            "Lower-Left": None,
            "Upper-Right": None,
            "Lower-Right": None,
        },
    },
    "setup": {
        "camera_driver": "opencv",
        "camera_index": 0,
        "motion_port": "auto",
        "motion_baudrate": 115200,
        "gpio_enabled": False,
        "gpio_port": "auto",
        "gpio_baudrate": 9600,
        "gpio_laser_pin": 21,
    },
}


class SessionManager:
    """Manages last-session state and named presets."""

    def __init__(self):
        data_dir = _user_data_dir()
        self._session_path = os.path.join(data_dir, "session.json")
        self._presets_path = os.path.join(data_dir, "presets.json")
        self._session: Dict[str, Any] = self._load_json(self._session_path, DEFAULT_SESSION)
        self._presets: Dict[str, Dict[str, Any]] = self._load_json(self._presets_path, {})

    # ------------------------------------------------------------------
    # Session (auto-save / auto-restore)
    # ------------------------------------------------------------------

    def get_session(self, section: str) -> Dict[str, Any]:
        """Return a copy of a session section (e.g. 'experiment')."""
        return deepcopy(self._session.get(section, DEFAULT_SESSION.get(section, {})))

    def update_session(self, section: str, values: Dict[str, Any]):
        """Merge *values* into the given session section and persist immediately."""
        if section not in self._session:
            self._session[section] = {}
        self._session[section].update(values)
        self._save_json(self._session_path, self._session)

    def save_session(self):
        """Explicitly flush the current session to disk."""
        self._save_json(self._session_path, self._session)

    # ------------------------------------------------------------------
    # Presets (named, user-managed)
    # ------------------------------------------------------------------

    def list_presets(self) -> List[str]:
        """Return the names of all saved presets, sorted alphabetically."""
        return sorted(self._presets.keys())

    def save_preset(self, name: str, data: Dict[str, Any]):
        """Save *data* under the given preset name and persist."""
        self._presets[name] = deepcopy(data)
        self._save_json(self._presets_path, self._presets)

    def load_preset(self, name: str) -> Optional[Dict[str, Any]]:
        """Return a copy of the named preset, or None if it does not exist."""
        preset = self._presets.get(name)
        return deepcopy(preset) if preset is not None else None

    def delete_preset(self, name: str):
        """Delete a preset by name."""
        if name in self._presets:
            del self._presets[name]
            self._save_json(self._presets_path, self._presets)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _load_json(path: str, default: Any) -> Any:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        return deepcopy(default)

    @staticmethod
    def _save_json(path: str, data: Any):
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except OSError as e:
            print(f"[SessionManager] Could not save {path}: {e}")


# Global singleton
session_manager = SessionManager()
