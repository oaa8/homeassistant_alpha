"""
Deako Hub Simulator - Logging Configuration

Author: GitHub Copilot
Created: 2025-10-26
Last Modified: 2026-08-11

Purpose:
    Configures Python logging module with structured logging format and
    component-based logger names for filtering.

Key Assumptions:
    - Console output is always wanted; the simulator is run interactively or
      under a supervisor that captures stdout, so no file handler is imposed.
    - Component names are hierarchical (deako_simulator.telnet, .http, .state)
      so operators can raise or lower verbosity per subsystem without code changes.

Key Features:
    - Consistent log format with timestamp, level, component, and message
    - Component tags via logger names (telnet, http, simulator, connection)
    - Console handler always enabled
    - Configurable log levels (DEBUG, INFO, WARNING, ERROR)

Related Requirements:
    - FR-045 to FR-053: Logging requirements for different components
    - FR-068: Log effective configuration at startup
"""

from __future__ import annotations

import logging
import sys
from typing import Literal

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]


def setup_logging(log_level: str = "INFO") -> None:
    """
    Configure Python logging module with structured format.
    
    Log format: [timestamp] [level] [component] message
    Example: [2025-10-26 15:30:45] [INFO] [deako_simulator.telnet] Connection from 127.0.0.1
    
    Component tags available for filtering:
    - deako_simulator.telnet: Telnet server messages
    - deako_simulator.http: HTTP API messages
    - deako_simulator.simulator: General simulator messages
    - deako_simulator.connection: Connection lifecycle events
    - deako_simulator.state: State management messages
    - deako_simulator.protocol: Protocol message parsing
    - deako_simulator.config: Configuration loading
    
    Example filter commands (PowerShell on Windows):
    - Filter telnet messages: python -m deako_simulator | Select-String "deako_simulator.telnet"
    - Filter HTTP messages: python -m deako_simulator | Select-String "deako_simulator.http"
    - Filter ERROR level: python -m deako_simulator | Select-String "ERROR"
    On Linux/Mac use grep: python -m deako_simulator | grep "[deako_simulator.telnet]"
    
    Args:
        log_level: Logging verbosity level (DEBUG, INFO, WARNING, ERROR)
        
    Raises:
        ValueError: If log_level is not a valid level
    """
    # Validate log level
    valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR"]
    if log_level.upper() not in valid_levels:
        raise ValueError(
            f"Invalid log level: {log_level}. "
            f"Must be one of: {', '.join(valid_levels)}"
        )
    
    # Convert string to logging level constant
    numeric_level = getattr(logging, log_level.upper())
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)
    
    # Remove existing handlers to avoid duplicates
    root_logger.handlers.clear()
    
    # Create console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(numeric_level)
    
    # Create formatter with structured format
    # Format: [timestamp] [level] [component] message
    formatter = logging.Formatter(
        fmt="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    console_handler.setFormatter(formatter)
    
    # Add handler to root logger
    root_logger.addHandler(console_handler)
    
    # Log configuration completion
    logger = logging.getLogger("deako_simulator.logging")
    logger.info(f"Logging configured with level: {log_level}")


def get_logger(component: str) -> logging.Logger:
    """
    Get logger for a specific component.
    
    Args:
        component: Component name (e.g., "telnet", "http", "simulator")
        
    Returns:
        Logger instance with component-specific name
        
    Example:
        >>> logger = get_logger("telnet")
        >>> logger.info("Connection established")
        [2025-10-26 15:30:45] [INFO] [deako_simulator.telnet] Connection established
    """
    return logging.getLogger(f"deako_simulator.{component}")

