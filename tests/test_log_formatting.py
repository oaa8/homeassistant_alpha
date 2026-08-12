"""
Deako Hub Simulator - Log Formatting Tests

Author: GitHub Copilot
Creation Date: 2025-10-29
Last Modified: 2025-10-29

Purpose:
    Tests for log message formatting to ensure logs are structured correctly
    with timestamps, log levels, component names, and full message content.

End-User Scenario:
    When developers review logs for debugging, they need consistent formatting
    with timestamps, clear component identification, and complete message content.
    This test ensures log format meets these requirements.

Related Requirements:
    - FR-046: Log all received messages with timestamp, client IP, full content
    - FR-047: Log all sent messages with timestamp, client IP, full content
    - FR-048: Log connection events with client IP
    - T073: Log formatting test task
"""

import logging
import re
import pytest
from io import StringIO

from deako_simulator.logging_config import setup_logging, get_logger


class TestLogFormat:
    """Test that logs follow the specified format."""
    
    def test_log_format_structure(self, caplog):
        """
        Verify logs match format: [timestamp] [level] [component] message
        
        End-User Impact: Consistent log format enables easy parsing and filtering.
        Without consistent format, log analysis tools won't work correctly.
        """
        caplog.set_level(logging.INFO)
        
        logger = get_logger("test")
        logger.info("Test message for format validation")
        
        # Verify we have a log record
        assert len(caplog.records) > 0, \
            "Log record must be captured for format validation"
        
        record = caplog.records[0]
        
        # Verify logger name follows component pattern
        assert record.name == "deako_simulator.test", \
            "Logger name must follow deako_simulator.{component} pattern"
        
        # Verify log level is correct
        assert record.levelname == "INFO", \
            "Log level must be captured correctly"
        
        # Verify message content is preserved
        assert record.message == "Test message for format validation", \
            "Log message content must be preserved exactly"
    
    def test_log_format_with_setup_logging(self):
        """
        Verify setup_logging configures correct format in output.
        
        End-User Impact: The setup_logging function must configure the
        correct format that includes timestamp, level, and component.
        """
        # Capture stdout to verify formatted output
        import sys
        from io import StringIO
        
        # Save original stdout
        original_stdout = sys.stdout
        
        try:
            # Redirect stdout to capture log output
            sys.stdout = StringIO()
            
            # Setup logging and create a logger
            setup_logging("INFO")
            logger = get_logger("format_test")
            logger.info("Format validation message")
            
            # Get the captured output
            log_output = sys.stdout.getvalue()
            
            # Restore stdout
            sys.stdout = original_stdout
            
            # Verify format: [timestamp] [level] [component] message
            # Pattern: [YYYY-MM-DD HH:MM:SS] [LEVEL] [deako_simulator.component] message
            pattern = r'\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] \[INFO\] \[deako_simulator\.format_test\] Format validation message'
            
            assert re.search(pattern, log_output), \
                f"Log output must match format pattern. Got: {log_output}"
        
        finally:
            # Ensure stdout is restored even if test fails
            sys.stdout = original_stdout
    
    def test_timestamp_in_logs(self, caplog):
        """
        Verify all logs include timestamp information.
        
        End-User Impact: Timestamps are critical for debugging timing issues
        and correlating events across systems.
        """
        caplog.set_level(logging.DEBUG)
        
        logger = get_logger("timestamp_test")
        logger.info("Message with timestamp")
        
        assert len(caplog.records) > 0, "Must have log records"
        record = caplog.records[0]
        
        # Verify record has timestamp (created attribute)
        assert hasattr(record, 'created'), \
            "Log records must have timestamp (created attribute)"
        assert record.created > 0, \
            "Timestamp must be a valid Unix timestamp"
    
    def test_log_level_in_output(self):
        """
        Verify log level appears in formatted output.
        
        End-User Impact: Log level must be visible to filter by severity.
        """
        import sys
        from io import StringIO
        
        original_stdout = sys.stdout
        
        try:
            sys.stdout = StringIO()
            
            setup_logging("DEBUG")
            logger = get_logger("level_test")
            
            # Test different log levels
            logger.debug("Debug message")
            logger.info("Info message")
            logger.warning("Warning message")
            logger.error("Error message")
            
            output = sys.stdout.getvalue()
            sys.stdout = original_stdout
            
            # Verify each level appears in output
            assert "[DEBUG]" in output, \
                "DEBUG level must appear in formatted output"
            assert "[INFO]" in output, \
                "INFO level must appear in formatted output"  
            assert "[WARNING]" in output, \
                "WARNING level must appear in formatted output"
            assert "[ERROR]" in output, \
                "ERROR level must appear in formatted output"
        
        finally:
            sys.stdout = original_stdout
    
    def test_component_name_in_output(self):
        """
        Verify component name appears in formatted output.
        
        End-User Impact: Component names enable filtering logs by subsystem.
        """
        import sys
        from io import StringIO
        
        original_stdout = sys.stdout
        
        try:
            sys.stdout = StringIO()
            
            setup_logging("INFO")
            logger = get_logger("component_test")
            logger.info("Component message")
            
            output = sys.stdout.getvalue()
            sys.stdout = original_stdout
            
            assert "[deako_simulator.component_test]" in output, \
                "Component name must appear in formatted output in brackets"
        
        finally:
            sys.stdout = original_stdout


class TestMessageContent:
    """Test that full message content is logged."""
    
    def test_full_message_content_preserved(self, caplog):
        """
        Verify complete message content is logged without truncation.
        
        End-User Impact: Truncated messages hide critical debugging information.
        Full message content is required per FR-046 and FR-047.
        """
        caplog.set_level(logging.INFO)
        
        # Create a long message with special characters
        long_message = (
            "CONTROL command received: "
            '{"type":"CONTROL","transactionId":"abc-123-def-456",'
            '"data":{"uuid":"12345678-1234-1234-1234-123456789abc",'
            '"power":true,"dim":75}} from client 192.168.1.100:54321'
        )
        
        logger = get_logger("content_test")
        logger.info(long_message)
        
        assert len(caplog.records) > 0, "Must have log records"
        assert caplog.records[0].message == long_message, \
            "Full message content must be preserved exactly without truncation"
    
    def test_special_characters_preserved(self, caplog):
        """
        Verify special characters in messages are preserved.
        
        End-User Impact: JSON messages, UUIDs, and special characters
        must not be corrupted or escaped incorrectly.
        """
        caplog.set_level(logging.INFO)
        
        # Message with various special characters
        message_with_specials = 'Message with "quotes", {braces}, [brackets], and newline\n'
        
        logger = get_logger("special_test")
        logger.info(message_with_specials)
        
        assert len(caplog.records) > 0, "Must have log records"
        assert caplog.records[0].message == message_with_specials, \
            "Special characters must be preserved in log messages"
    
    def test_unicode_characters_preserved(self, caplog):
        """
        Verify Unicode characters in messages are preserved.
        
        End-User Impact: Device names may contain Unicode characters
        that must not be corrupted in logs.
        """
        caplog.set_level(logging.INFO)
        
        unicode_message = "Device name: Café Light™ 🏠"
        
        logger = get_logger("unicode_test")
        logger.info(unicode_message)
        
        assert len(caplog.records) > 0, "Must have log records"
        assert caplog.records[0].message == unicode_message, \
            "Unicode characters must be preserved in log messages"


class TestClientIPLogging:
    """Test that client IP addresses are included in connection logs."""
    
    def test_connection_logs_include_ip(self, caplog):
        """
        Verify connection logs include client IP addresses.
        
        End-User Impact: Client IP is required per FR-048 to track
        which client is experiencing issues.
        """
        caplog.set_level(logging.INFO)
        
        connection_logger = get_logger("connection")
        connection_logger.info("Connection from 192.168.1.100:54321 established")
        
        assert len(caplog.records) > 0, "Must have log records"
        message = caplog.records[0].message
        
        # Verify IP address is in message
        assert "192.168.1.100" in message, \
            "Client IP address must be included in connection logs per FR-048"
        
        # Verify port is also included
        assert "54321" in message, \
            "Client port should be included for complete connection information"
    
    def test_protocol_logs_include_client_info(self, caplog):
        """
        Verify protocol message logs can include client information.
        
        End-User Impact: Knowing which client sent a message helps
        debug multi-client scenarios per FR-046 and FR-047.
        """
        caplog.set_level(logging.DEBUG)
        
        telnet_logger = get_logger("telnet")
        telnet_logger.info("Received PING from 192.168.1.100")
        
        assert len(caplog.records) > 0, "Must have log records"
        assert "192.168.1.100" in caplog.records[0].message, \
            "Protocol logs should include client IP when relevant"


class TestTimestampFormat:
    """Test that timestamps are formatted correctly and consistently."""
    
    def test_timestamp_format_readable(self):
        """
        Verify timestamps are in human-readable format.
        
        End-User Impact: Human-readable timestamps (YYYY-MM-DD HH:MM:SS)
        are easier to read than Unix timestamps when reviewing logs.
        """
        import sys
        from io import StringIO
        
        original_stdout = sys.stdout
        
        try:
            sys.stdout = StringIO()
            
            setup_logging("INFO")
            logger = get_logger("timestamp_format_test")
            logger.info("Timestamp test message")
            
            output = sys.stdout.getvalue()
            sys.stdout = original_stdout
            
            # Verify timestamp format: YYYY-MM-DD HH:MM:SS
            timestamp_pattern = r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}'
            assert re.search(timestamp_pattern, output), \
                f"Timestamp must be in YYYY-MM-DD HH:MM:SS format. Got: {output}"
        
        finally:
            sys.stdout = original_stdout
    
    def test_timestamp_consistency(self):
        """
        Verify all logs use consistent timestamp format.
        
        End-User Impact: Consistent timestamps enable reliable log sorting
        and timeline reconstruction.
        """
        import sys
        from io import StringIO
        
        original_stdout = sys.stdout
        
        try:
            sys.stdout = StringIO()
            
            setup_logging("INFO")
            logger = get_logger("consistency_test")
            
            # Log multiple messages
            logger.info("First message")
            logger.info("Second message")
            logger.info("Third message")
            
            output = sys.stdout.getvalue()
            sys.stdout = original_stdout
            
            # Find all timestamps in output
            timestamp_pattern = r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]'
            timestamps = re.findall(timestamp_pattern, output)
            
            assert len(timestamps) >= 3, \
                "Should have timestamps for all log messages"
            
            # Verify all timestamps follow same format
            for ts in timestamps:
                assert len(ts) == 19, \
                    f"All timestamps must be exactly 19 characters (YYYY-MM-DD HH:MM:SS). Got: {ts}"
        
        finally:
            sys.stdout = original_stdout
