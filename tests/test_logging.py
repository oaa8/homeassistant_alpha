"""
Unit tests for logging configuration module.

Tests cover:
- Log level configuration
- Log message format
- Console handler enabled
- Component tag filtering
"""

import logging
import pytest
from io import StringIO

from deako_simulator.logging_config import setup_logging, get_logger


@pytest.fixture(autouse=True)
def reset_logging():
    """Reset logging configuration before each test."""
    # Clear all handlers and reset root logger
    root = logging.getLogger()
    for handler in root.handlers[:]:
        root.removeHandler(handler)
    root.setLevel(logging.WARNING)
    
    yield
    
    # Cleanup after test
    for handler in root.handlers[:]:
        root.removeHandler(handler)


class TestLoggingSetup:
    """Test logging configuration setup."""
    
    def test_setup_logging_default_level(self):
        """Test setup with default INFO level."""
        setup_logging()
        
        root = logging.getLogger()
        assert root.level == logging.INFO
        assert len(root.handlers) == 1
        assert isinstance(root.handlers[0], logging.StreamHandler)
    
    def test_setup_logging_debug_level(self):
        """Test setup with DEBUG level."""
        setup_logging("DEBUG")
        
        root = logging.getLogger()
        assert root.level == logging.DEBUG
    
    def test_setup_logging_warning_level(self):
        """Test setup with WARNING level."""
        setup_logging("WARNING")
        
        root = logging.getLogger()
        assert root.level == logging.WARNING
    
    def test_setup_logging_error_level(self):
        """Test setup with ERROR level."""
        setup_logging("ERROR")
        
        root = logging.getLogger()
        assert root.level == logging.ERROR
    
    def test_setup_logging_case_insensitive(self):
        """Test log level is case-insensitive."""
        setup_logging("info")
        
        root = logging.getLogger()
        assert root.level == logging.INFO
    
    def test_setup_logging_invalid_level(self):
        """Test invalid log level raises ValueError."""
        with pytest.raises(ValueError, match="Invalid log level"):
            setup_logging("INVALID")
    
    def test_setup_logging_console_handler_added(self):
        """Test console handler is added."""
        setup_logging()
        
        root = logging.getLogger()
        assert len(root.handlers) == 1
        assert isinstance(root.handlers[0], logging.StreamHandler)
    
    def test_setup_logging_removes_duplicate_handlers(self):
        """Test setup removes existing handlers to avoid duplicates."""
        setup_logging()
        setup_logging()  # Call twice
        
        root = logging.getLogger()
        assert len(root.handlers) == 1  # Should only have one handler


class TestLogMessageFormat:
    """Test log message formatting."""
    
    def test_log_format_includes_timestamp(self):
        """Test log messages include timestamp."""
        setup_logging("DEBUG")
        logger = get_logger("test")
        
        # Log messages go to stdout - we verify format via handler
        logger.info("Test message")
        
        # Verify formatter is configured correctly
        root = logging.getLogger()
        formatter = root.handlers[0].formatter
        assert formatter._fmt == "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
    
    def test_log_format_includes_level(self):
        """Test log messages include level name via formatter."""
        setup_logging("DEBUG")
        
        # Verify formatter includes level
        root = logging.getLogger()
        formatter = root.handlers[0].formatter
        assert "%(levelname)s" in formatter._fmt
    
    def test_log_format_includes_component_name(self):
        """Test log messages include component name via formatter."""
        setup_logging("INFO")
        
        # Verify formatter includes logger name
        root = logging.getLogger()
        formatter = root.handlers[0].formatter
        assert "%(name)s" in formatter._fmt


class TestComponentTags:
    """Test component-based logger naming."""
    
    def test_get_logger_telnet(self):
        """Test telnet component logger."""
        logger = get_logger("telnet")
        assert logger.name == "deako_simulator.telnet"
    
    def test_get_logger_http(self):
        """Test http component logger."""
        logger = get_logger("http")
        assert logger.name == "deako_simulator.http"
    
    def test_get_logger_simulator(self):
        """Test simulator component logger."""
        logger = get_logger("simulator")
        assert logger.name == "deako_simulator.simulator"
    
    def test_get_logger_connection(self):
        """Test connection component logger."""
        logger = get_logger("connection")
        assert logger.name == "deako_simulator.connection"
    
    def test_get_logger_state(self):
        """Test state component logger."""
        logger = get_logger("state")
        assert logger.name == "deako_simulator.state"
    
    def test_component_filtering(self):
        """Test messages can be filtered by component via logger names."""
        setup_logging("DEBUG")
        
        telnet_logger = get_logger("telnet")
        http_logger = get_logger("http")
        
        # Verify loggers have correct names for filtering
        assert telnet_logger.name == "deako_simulator.telnet"
        assert http_logger.name == "deako_simulator.http"
        
        # Log messages - in real usage, would grep logs for component
        telnet_logger.info("Telnet message 1")
        http_logger.info("HTTP message 1")
        telnet_logger.info("Telnet message 2")


class TestLogLevelFiltering:
    """Test log level filtering."""
    
    def test_info_level_filters_debug(self):
        """Test INFO level configuration."""
        setup_logging("INFO")
        
        root = logging.getLogger()
        assert root.level == logging.INFO
        
        # Verify handler level matches
        assert root.handlers[0].level == logging.INFO
    
    def test_warning_level_configuration(self):
        """Test WARNING level configuration."""
        setup_logging("WARNING")
        
        root = logging.getLogger()
        assert root.level == logging.WARNING
        assert root.handlers[0].level == logging.WARNING
    
    def test_error_level_configuration(self):
        """Test ERROR level configuration."""
        setup_logging("ERROR")
        
        root = logging.getLogger()
        assert root.level == logging.ERROR
        assert root.handlers[0].level == logging.ERROR
    
    def test_debug_level_configuration(self):
        """Test DEBUG level configuration."""
        setup_logging("DEBUG")
        
        root = logging.getLogger()
        assert root.level == logging.DEBUG
        assert root.handlers[0].level == logging.DEBUG
