import json
from typing import Any, Dict
import os

class ConfigManager:
    """Manages loading and accessing configuration files."""

    def __init__(self, config_path: str = "robocam_suite/config/default_config.json"):
        self._config_path = config_path
        self._config = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        """Loads the configuration from the specified JSON file."""
        if not os.path.exists(self._config_path):
            raise FileNotFoundError(f"Configuration file not found at {self._config_path}")
        with open(self._config_path, "r") as f:
            return json.load(f)

    def get(self, key: str, default: Any = None) -> Any:
        """Gets a configuration value for a given key."""
        return self._config.get(key, default)

    def get_section(self, section: str) -> Dict[str, Any]:
        """Gets a whole section of the configuration."""
        return self._config.get(section, {})

# Global config instance
config_manager = ConfigManager()
