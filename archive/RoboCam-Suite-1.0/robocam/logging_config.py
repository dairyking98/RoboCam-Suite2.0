"""
Logging Configuration Module

Centralized logging setup for RoboCam-Suite. Configures Python logging
with file and console handlers, log rotation, and configurable log levels.

Author: RoboCam-Suite
"""

import logging
import logging.handlers
import os
from pathlib import Path
from typing import Optional
from .config import get_config


def setup_logging(log_file: Optional[str] = None, log_level: Optional[str] = None) -> logging.Logger:
    """
    Set up logging configuration for RoboCam-Suite.
    
    Args:
        log_file: Path to log file. If None, uses config default or creates logs/robocam.log
        log_level: Log level (DEBUG, INFO, WARNING, ERROR). If None, uses config default or INFO
        
    Returns:
        Configured logger instance
        
    Note:
        Creates log directory if it doesn't exist.
        Sets up both file and console handlers.
        File handler uses rotation (max 10MB, 5 backups).
    """
    # Get config for logging settings
    config = get_config()
    
    # Determine log file path
    if log_file is None:
        log_file = config.get("logging.log_file", "logs/robocam.log")
    
    # Determine log level
    if log_level is None:
        log_level = config.get("logging.log_level", "INFO")
    
    # Convert string level to logging constant
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    
    # Create log directory if needed
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Create logger
    logger = logging.getLogger("robocam")
    logger.setLevel(numeric_level)
    
    # Remove existing handlers to avoid duplicates
    logger.handlers.clear()
    
    # File handler with rotation
    max_bytes = config.get("logging.max_bytes", 10 * 1024 * 1024)  # 10MB default
    backup_count = config.get("logging.backup_count", 5)
    
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding='utf-8'
    )
    file_handler.setLevel(numeric_level)
    
    # Console handler (optional, for development)
    console_enabled = config.get("logging.console_enabled", False)
    if console_enabled:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(numeric_level)
        console_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%H:%M:%S'
        )
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)
    
    # File formatter (more detailed)
    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)
    
    return logger


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """
    Get a logger instance for a module.
    
    Args:
        name: Logger name (typically __name__). If None, returns root robocam logger.
        
    Returns:
        Logger instance
        
    Note:
        Child loggers inherit configuration from root robocam logger.
        Use this in modules: logger = get_logger(__name__)
    """
    if name is None:
        return logging.getLogger("robocam")
    
    # Return child logger
    return logging.getLogger(f"robocam.{name}")


# Initialize logging on module import
_initialized = False

def initialize_logging() -> None:
    """Initialize logging system (called once on first import)."""
    global _initialized
    if not _initialized:
        setup_logging()
        _initialized = True

# Auto-initialize on import
initialize_logging()

