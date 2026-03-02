# Developer Guide

This guide provides a deep dive into the architecture of RoboCam-Suite 2.0 and explains how to extend it with new functionality.

## Architecture Overview

The suite is built around a few key architectural principles:

- **Abstraction:** Core hardware functionality is defined by abstract base classes (ABCs) in the `robocam_suite.core` module. This decouples the main application logic from the specific hardware being used.
- **Dependency Injection:** The `HardwareManager` is responsible for instantiating the correct hardware drivers based on the configuration file. This makes it easy to switch between different hardware implementations without changing the application code.
- **Modularity:** The project is organized into distinct modules for hardware drivers, experiment logic, and UI components. This makes the codebase easier to understand, maintain, and extend.

### Core Interfaces

The following abstract base classes define the core hardware interfaces:

- `Camera`: Defines the interface for a camera, including methods for connecting, disconnecting, starting/stopping capture, and reading frames.
- `MotionController`: Defines the interface for a motion controller, including methods for homing, moving to absolute/relative positions, and getting the current position.
- `GPIOController`: Defines the interface for a GPIO controller, including methods for setting pin modes and writing/reading pin values.

### Hardware Drivers

Concrete implementations of the core interfaces are located in the `robocam_suite.drivers` module. To add support for a new piece of hardware, you simply need to create a new class that inherits from the appropriate ABC and implements its methods.

For example, to add a new camera, you would create a new class in `robocam_suite.drivers.camera` that inherits from `Camera` and implements its methods for interacting with the new camera's SDK or API.

### Configuration

The application is configured through the `robocam_suite/config/default_config.json` file. This file allows you to specify which drivers to use for each hardware component, as well as any driver-specific settings.

The `ConfigManager` class provides a simple way to access configuration values from anywhere in the application.

### GUI

The GUI is built with PySide6 and is organized into a main window with several panels for different functions (calibration, experiment, manual control). The UI is designed to be responsive and user-friendly.

## How to Add a New Hardware Driver

1.  **Create the Driver Class:** Create a new Python file in the appropriate subdirectory of `robocam_suite/drivers`. In this file, define a new class that inherits from the corresponding abstract base class in `robocam_suite.core`.

2.  **Implement the Interface:** Implement all of the abstract methods defined in the base class. This will involve writing the code to communicate with your new hardware device.

3.  **Update the Hardware Manager:** In `robocam_suite/hw_manager.py`, add a new case to the `if/elif` block in the appropriate `get_*` method to instantiate your new driver class when it is specified in the configuration file.

4.  **Update the Configuration:** Add a new entry to the `default_config.json` file to allow users to select your new driver.
