"""
Configuration Management Module

Centralized configuration system for RoboCam-Suite. Handles loading,
validating, and managing configuration values from JSON files with
support for environment variable overrides.

Author: RoboCam-Suite
"""

import json
import os
from typing import Any, Dict, Optional
from pathlib import Path


class Config:
    """
    Configuration management class for RoboCam-Suite.
    
    Loads configuration from JSON files with support for:
    - Default configuration values
    - User configuration file overrides
    - Environment variable overrides
    - Configuration validation
    
    Attributes:
        config (Dict[str, Any]): Current configuration dictionary
        config_file (Optional[Path]): Path to loaded configuration file
    """
    
    # Default configuration values
    DEFAULT_CONFIG = {
        "hardware": {
            "printer": {
                "baudrate": 115200,
                "timeout": 10.0,
                "home_timeout": 90.0,
                "movement_wait_timeout": 30.0,
                "command_delay": 0.1,
                "position_update_delay": 0.1,
                "connection_retry_delay": 2.0,
                "max_retries": 5
            },
            "laser": {
                "gpio_pin": 21,
                "default_state": "OFF"
            },
            "camera": {
                "preview_resolution": [800, 600],
                "default_fps": 30.0,
                "preview_backend": "auto"
            }
        },
        "paths": {
            "config_dir": "config",
            "motion_config_file": "config/motion_config.json",
            "calibration_dir": "config/calibrations",
            "experiment_config": "experiment_config.json"
        }
    }
    
    def __init__(self, config_file: Optional[str] = None) -> None:
        """
        Initialize configuration manager.
        
        Args:
            config_file: Path to configuration file. If None, uses default location.
                        If file doesn't exist, creates it with default values.
        """
        self.config: Dict[str, Any] = {}
        self.config_file: Optional[Path] = None
        
        # Load default config first
        self.config = self._deep_copy(self.DEFAULT_CONFIG)
        
        # Load from file if provided
        if config_file:
            self.config_file = Path(config_file)
            if self.config_file.exists():
                self.load_config(str(self.config_file))
            else:
                # Create default config file
                self.save_config(str(self.config_file))
        else:
            # Try to load from default location
            default_path = Path("config/default_config.json")
            if default_path.exists():
                self.config_file = default_path
                self.load_config(str(default_path))
            else:
                # Create default config file
                default_path.parent.mkdir(parents=True, exist_ok=True)
                self.config_file = default_path
                self.save_config(str(default_path))
        
        # Apply environment variable overrides
        self._apply_env_overrides()
        
        # Validate configuration
        self.validate()
    
    def _deep_copy(self, d: Dict[str, Any]) -> Dict[str, Any]:
        """Deep copy dictionary."""
        return json.loads(json.dumps(d))
    
    def load_config(self, file_path: str) -> None:
        """
        Load configuration from JSON file.
        
        Args:
            file_path: Path to configuration file
            
        Raises:
            FileNotFoundError: If file doesn't exist
            json.JSONDecodeError: If file is not valid JSON
        """
        config_path = Path(file_path)
        if not config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {file_path}")
        
        with open(config_path, 'r') as f:
            loaded_config = json.load(f)
        
        # Merge with existing config (loaded config takes precedence)
        self._merge_config(self.config, loaded_config)
        self.config_file = config_path
    
    def save_config(self, file_path: Optional[str] = None) -> None:
        """
        Save current configuration to JSON file.
        
        Args:
            file_path: Path to save configuration. If None, uses current config_file.
        """
        save_path = Path(file_path) if file_path else self.config_file
        if save_path is None:
            raise ValueError("No file path specified and no config_file set")
        
        save_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(save_path, 'w') as f:
            json.dump(self.config, f, indent=2)
        
        self.config_file = save_path
    
    def _merge_config(self, base: Dict[str, Any], override: Dict[str, Any]) -> None:
        """Recursively merge override config into base config."""
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._merge_config(base[key], value)
            else:
                base[key] = value
    
    def _apply_env_overrides(self) -> None:
        """Apply environment variable overrides to configuration."""
        # Printer baudrate
        if os.environ.get("ROBOCAM_BAUDRATE"):
            try:
                self.config["hardware"]["printer"]["baudrate"] = int(os.environ["ROBOCAM_BAUDRATE"])
            except ValueError:
                pass
        
        # Laser GPIO pin
        if os.environ.get("ROBOCAM_LASER_PIN"):
            try:
                self.config["hardware"]["laser"]["gpio_pin"] = int(os.environ["ROBOCAM_LASER_PIN"])
            except ValueError:
                pass
        
        # Printer timeout
        if os.environ.get("ROBOCAM_TIMEOUT"):
            try:
                self.config["hardware"]["printer"]["timeout"] = float(os.environ["ROBOCAM_TIMEOUT"])
            except ValueError:
                pass
        
        # Printer home timeout
        if os.environ.get("ROBOCAM_HOME_TIMEOUT"):
            try:
                self.config["hardware"]["printer"]["home_timeout"] = float(os.environ["ROBOCAM_HOME_TIMEOUT"])
            except ValueError:
                pass
        
        # Printer movement wait timeout
        if os.environ.get("ROBOCAM_MOVEMENT_WAIT_TIMEOUT"):
            try:
                self.config["hardware"]["printer"]["movement_wait_timeout"] = float(os.environ["ROBOCAM_MOVEMENT_WAIT_TIMEOUT"])
            except ValueError:
                pass
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        Get configuration value using dot notation.
        
        Args:
            key: Configuration key in dot notation (e.g., "hardware.printer.baudrate")
            default: Default value if key not found
            
        Returns:
            Configuration value or default
            
        Examples:
            config.get("hardware.printer.baudrate")  # Returns 115200
            config.get("hardware.laser.gpio_pin")     # Returns 21
            config.get("nonexistent.key", "default") # Returns "default"
        """
        keys = key.split('.')
        value = self.config
        
        try:
            for k in keys:
                value = value[k]
            return value
        except (KeyError, TypeError):
            return default
    
    def set(self, key: str, value: Any) -> None:
        """
        Set configuration value using dot notation.
        
        Args:
            key: Configuration key in dot notation
            value: Value to set
            
        Examples:
            config.set("hardware.printer.baudrate", 9600)
            config.set("hardware.laser.gpio_pin", 18)
        """
        keys = key.split('.')
        config = self.config
        
        # Navigate to the parent dict
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
        
        # Set the value
        config[keys[-1]] = value
    
    def validate(self) -> None:
        """
        Validate configuration values.
        
        Raises:
            ValueError: If configuration values are invalid
        """
        # Validate printer baudrate
        baudrate = self.get("hardware.printer.baudrate")
        if not isinstance(baudrate, int) or baudrate <= 0:
            raise ValueError(f"Invalid baudrate: {baudrate}")
        
        # Validate timeout
        timeout = self.get("hardware.printer.timeout")
        if not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ValueError(f"Invalid timeout: {timeout}")
        
        # Validate home_timeout
        home_timeout = self.get("hardware.printer.home_timeout")
        if not isinstance(home_timeout, (int, float)) or home_timeout <= 0:
            raise ValueError(f"Invalid home_timeout: {home_timeout}")
        
        # Validate movement_wait_timeout
        movement_wait_timeout = self.get("hardware.printer.movement_wait_timeout")
        if not isinstance(movement_wait_timeout, (int, float)) or movement_wait_timeout <= 0:
            raise ValueError(f"Invalid movement_wait_timeout: {movement_wait_timeout}")
        
        # Validate GPIO pin
        gpio_pin = self.get("hardware.laser.gpio_pin")
        if not isinstance(gpio_pin, int) or gpio_pin < 0 or gpio_pin > 27:
            raise ValueError(f"Invalid GPIO pin: {gpio_pin} (must be 0-27)")
        
        # Validate preview resolution
        preview_res = self.get("hardware.camera.preview_resolution")
        if not isinstance(preview_res, list) or len(preview_res) != 2:
            raise ValueError(f"Invalid preview_resolution: {preview_res}")
        if not all(isinstance(x, int) and x > 0 for x in preview_res):
            raise ValueError(f"Invalid preview_resolution values: {preview_res}")
        
        # Validate FPS
        fps = self.get("hardware.camera.default_fps")
        if not isinstance(fps, (int, float)) or fps <= 0:
            raise ValueError(f"Invalid default_fps: {fps}")
    
    def get_printer_config(self) -> Dict[str, Any]:
        """Get printer configuration dictionary."""
        return self.get("hardware.printer", {})
    
    def get_laser_config(self) -> Dict[str, Any]:
        """Get laser configuration dictionary."""
        return self.get("hardware.laser", {})
    
    def get_camera_config(self) -> Dict[str, Any]:
        """Get camera configuration dictionary."""
        return self.get("hardware.camera", {})
    
    def get_paths_config(self) -> Dict[str, Any]:
        """Get paths configuration dictionary."""
        return self.get("paths", {})


# Global configuration instance
_global_config: Optional[Config] = None


def get_config(config_file: Optional[str] = None) -> Config:
    """
    Get or create global configuration instance.
    
    Args:
        config_file: Path to configuration file (only used on first call)
        
    Returns:
        Global Config instance
    """
    global _global_config
    if _global_config is None:
        _global_config = Config(config_file)
    return _global_config


def reset_config() -> None:
    """Reset global configuration (useful for testing)."""
    global _global_config
    _global_config = None

