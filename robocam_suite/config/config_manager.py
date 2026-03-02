import json
from copy import deepcopy
from typing import Any, Dict
import os


class ConfigManager:
    """
    Manages loading and accessing configuration.

    The config is loaded once from ``default_config.json`` at startup.
    The Setup tab can call ``update_section`` to push live changes into
    the in-memory config; these are also written back to the JSON file
    so they persist across restarts.
    """

    def __init__(self, config_path: str = "robocam_suite/config/default_config.json"):
        self._config_path = config_path
        self._config = self._load_config()

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, default)

    def get_section(self, section: str) -> Dict[str, Any]:
        return deepcopy(self._config.get(section, {}))

    # ------------------------------------------------------------------
    # Writing (used by Setup tab)
    # ------------------------------------------------------------------

    def update_section(self, section: str, values: Dict[str, Any]):
        """Merge *values* into *section* and persist to disk."""
        if section not in self._config:
            self._config[section] = {}
        self._config[section].update(values)
        self._save_config()

    def set_section(self, section: str, data: Dict[str, Any]):
        """Replace an entire section and persist to disk."""
        self._config[section] = deepcopy(data)
        self._save_config()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load_config(self) -> Dict[str, Any]:
        if not os.path.exists(self._config_path):
            raise FileNotFoundError(
                f"Configuration file not found at {self._config_path!r}"
            )
        with open(self._config_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save_config(self):
        try:
            with open(self._config_path, "w", encoding="utf-8") as f:
                json.dump(self._config, f, indent=4)
        except OSError as e:
            print(f"[ConfigManager] Could not save config: {e}")


# Global config instance
config_manager = ConfigManager()
