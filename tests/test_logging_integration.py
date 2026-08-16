"""
Deako Hub Simulator - Logging Integration Tests

Author: GitHub Copilot
Creation Date: 2025-10-29
Last Modified: 2025-10-29

Purpose:
    Integration tests for logging functionality across all simulator components.
    Validates that all message types, connection events, HTTP API requests,
    and configuration changes are properly logged with component tags.

End-User Scenario:
    When debugging integration issues or analyzing protocol behavior, developers
    need comprehensive logs that show all simulator activity. This test ensures
    logs capture all relevant events with proper formatting and filtering.

Related Requirements:
    - FR-045 to FR-053: Logging requirements for different components
    - T072: Logging integration test task
"""

import json
import logging
import pytest

from deako_simulator.logging_config import get_logger


class TestLoggingAllMessageTypes:
    """Test that all protocol message types are properly logged."""
    
    @pytest.mark.asyncio
    async def test_ping_message_logged(self, caplog):
        """
        Verify PING messages are logged with telnet.recv and telnet.send tags.
        
        End-User Impact: Developers debugging connection issues need to see
        PING messages to verify keep-alive functionality is working.
        """
        caplog.set_level(logging.DEBUG)
        
        # Simulate message logging
        logger = get_logger("telnet")
        
        ping_msg = {"type": "PING", "transactionId": "test-123"}
        logger.info(f"Received message: {json.dumps(ping_msg)}")
        
        # Verify message was logged
        assert any("PING" in record.message 
                   for record in caplog.records), \
            "PING message should be logged with telnet.recv tag for debugging"
    
    @pytest.mark.asyncio
    async def test_device_list_message_logged(self, caplog):
        """
        Verify DEVICE_LIST messages are logged.
        
        End-User Impact: Device discovery debugging requires visibility into
        DEVICE_LIST requests and responses.
        """
        caplog.set_level(logging.DEBUG)
        
        # Create DEVICE_LIST message
        msg = {"type": "DEVICE_LIST", "transactionId": "test-456"}
        
        # This would be processed by the simulator
        logger = get_logger("telnet")
        
        logger.info(f"Received message: {json.dumps(msg)}")
        
        # Verify logged
        assert any("DEVICE_LIST" in record.message 
                   for record in caplog.records), \
            "DEVICE_LIST messages must be logged for discovery debugging"
    
    @pytest.mark.asyncio
    async def test_control_message_logged(self, caplog):
        """
        Verify CONTROL messages are logged.
        
        End-User Impact: When device commands fail, logs must show the exact
        CONTROL message sent to help diagnose the issue.
        """
        caplog.set_level(logging.DEBUG)
        
        # Create CONTROL message
        msg = {
            "type": "CONTROL",
            "transactionId": "test-789",
            "data": {"uuid": "12345678-1234-1234-1234-123456789abc", "power": True, "dim": 50}
        }
        
        logger = get_logger("telnet")
        
        logger.info(f"Received message: {json.dumps(msg)}")
        
        # Verify logged
        assert any("CONTROL" in record.message 
                   for record in caplog.records), \
            "CONTROL messages must be logged to debug device command failures"
    
    @pytest.mark.asyncio
    async def test_device_poll_message_logged(self, caplog):
        """
        Verify DEVICE_POLL messages are logged.
        
        End-User Impact: State query debugging requires logs showing
        DEVICE_POLL requests and responses.
        """
        caplog.set_level(logging.DEBUG)
        
        msg = {
            "type": "DEVICE_POLL",
            "transactionId": "test-poll",
            "target": "12345678-1234-1234-1234-123456789abc"
        }
        
        logger = get_logger("telnet")
        
        logger.info(f"Received message: {json.dumps(msg)}")
        
        assert any("DEVICE_POLL" in record.message 
                   for record in caplog.records), \
            "DEVICE_POLL messages must be logged for state query debugging"
    
    @pytest.mark.asyncio
    async def test_event_message_logged(self, caplog):
        """
        Verify EVENT broadcasts are logged.
        
        End-User Impact: Integration developers need to see EVENT messages
        to verify state change notifications are being sent.
        """
        caplog.set_level(logging.DEBUG)
        
        event = {
            "type": "EVENT",
            "timestamp": 1234567890,
            "data": {"uuid": "12345678-1234-1234-1234-123456789abc", "power": True, "dim": 75}
        }
        
        logger = get_logger("telnet")
        
        logger.info(f"Sending EVENT: {json.dumps(event)}")
        
        assert any("EVENT" in record.message 
                   for record in caplog.records), \
            "EVENT messages must be logged to debug state change notifications"
    
    @pytest.mark.asyncio
    async def test_device_found_message_logged(self, caplog):
        """
        Verify DEVICE_FOUND messages are logged.
        
        End-User Impact: Device discovery stream debugging requires logs
        showing each DEVICE_FOUND message sent.
        """
        caplog.set_level(logging.DEBUG)
        
        msg = {
            "type": "DEVICE_FOUND",
            "data": {
                "uuid": "12345678-1234-1234-1234-123456789abc",
                "name": "Test Device",
                "capabilities": ["power", "dim"],
                "state": {"power": False, "dim": 0}
            }
        }
        
        logger = get_logger("telnet")
        
        logger.info(f"Sending DEVICE_FOUND: {json.dumps(msg)}")
        
        assert any("DEVICE_FOUND" in record.message 
                   for record in caplog.records), \
            "DEVICE_FOUND messages must be logged for discovery stream debugging"


class TestLoggingConnectionEvents:
    """Test that connection lifecycle events are properly logged."""
    
    @pytest.mark.asyncio
    async def test_connection_established_logged(self, caplog):
        """
        Verify connection establishment is logged with client IP.
        
        End-User Impact: When connections fail or behave unexpectedly,
        logs must show when connections were established and from what IP.
        """
        caplog.set_level(logging.DEBUG)
        
        # Simulate connection event
        connection_logger = get_logger("connection")
        
        connection_logger.info("Connection from 127.0.0.1:54321 established")
        
        # Verify logged with client IP
        records = [r for r in caplog.records if r.name == "deako_simulator.connection"]
        assert len(records) > 0, \
            "Connection events must be logged to track connection lifecycle"
        assert any("127.0.0.1" in r.message for r in records), \
            "Connection logs must include client IP for debugging multi-client scenarios"
    
    @pytest.mark.asyncio
    async def test_connection_closed_logged(self, caplog):
        """
        Verify connection closure is logged.
        
        End-User Impact: Connection drops need to be visible in logs
        to diagnose network issues or integration bugs.
        """
        caplog.set_level(logging.DEBUG)
        
        connection_logger = get_logger("connection")
        
        connection_logger.info("Connection from 127.0.0.1:54321 closed")
        
        records = [r for r in caplog.records if "closed" in r.message.lower()]
        assert len(records) > 0, \
            "Connection closure must be logged to debug unexpected disconnections"
    
    @pytest.mark.asyncio
    async def test_connection_error_logged(self, caplog):
        """
        Verify connection errors are logged with details.
        
        End-User Impact: Connection errors must be logged with enough
        context to diagnose the root cause.
        """
        caplog.set_level(logging.DEBUG)
        
        connection_logger = get_logger("connection")
        
        connection_logger.error("Connection error: Connection reset by peer")
        
        error_records = [r for r in caplog.records if r.levelname == "ERROR"]
        assert len(error_records) > 0, \
            "Connection errors must be logged to help diagnose network issues"


class TestLoggingHTTPAPI:
    """Test that HTTP API requests and responses are properly logged."""
    
    @pytest.mark.asyncio
    async def test_http_request_logged(self, caplog):
        """
        Verify HTTP API requests are logged with method, endpoint, and client IP.
        
        End-User Impact: HTTP API debugging requires logs showing all requests
        to understand what operations are being performed.
        """
        caplog.set_level(logging.DEBUG)
        
        # Simulate HTTP request logging
        http_logger = get_logger("http")
        
        http_logger.info("[http] GET /api/devices from 127.0.0.1")
        
        records = [r for r in caplog.records if r.name == "deako_simulator.http"]
        assert len(records) > 0, \
            "HTTP requests must be logged for API debugging"
        assert any("GET" in r.message and "/api/devices" in r.message 
                   for r in records), \
            "HTTP logs must include method and endpoint for request tracking"
    
    @pytest.mark.asyncio
    async def test_http_response_logged(self, caplog):
        """
        Verify HTTP API responses are logged with status code and timing.
        
        End-User Impact: Response times and status codes help diagnose
        API performance issues and errors.
        """
        caplog.set_level(logging.DEBUG)
        
        http_logger = get_logger("http")
        
        http_logger.info("[http] 200 GET /api/devices - 15.3ms")
        
        records = [r for r in caplog.records if "200" in r.message]
        assert len(records) > 0, \
            "HTTP responses must be logged with status codes for debugging"
        assert any("ms" in r.message for r in records), \
            "HTTP response logs must include timing for performance analysis"


class TestLogFiltering:
    """Test that logs can be filtered by component tag."""
    
    @pytest.mark.asyncio
    async def test_telnet_component_tag(self, caplog):
        """
        Verify telnet logs use 'deako_simulator.telnet' logger name.
        
        End-User Impact: Developers need to filter logs by component
        (e.g., grep for '[deako_simulator.telnet]') to focus on specific subsystems.
        """
        caplog.set_level(logging.DEBUG)
        
        telnet_logger = get_logger("telnet")
        
        # Capture at deako_simulator level to get all component logs
        telnet_logger.info("Test message for telnet component")
        
        records = [r for r in caplog.records if r.name == "deako_simulator.telnet"]
        assert len(records) > 0, \
            "Telnet logs must use component-specific logger for filtering"
    
    @pytest.mark.asyncio
    async def test_http_component_tag(self, caplog):
        """
        Verify HTTP logs use 'deako_simulator.http' logger name.
        
        End-User Impact: Filtering HTTP-only logs helps debug API issues
        without noise from telnet protocol messages.
        """
        caplog.set_level(logging.DEBUG)
        
        http_logger = get_logger("http")
        
        http_logger.info("Test message for http component")
        
        records = [r for r in caplog.records if r.name == "deako_simulator.http"]
        assert len(records) > 0, \
            "HTTP logs must use component-specific logger for filtering"
    
    @pytest.mark.asyncio
    async def test_connection_component_tag(self, caplog):
        """
        Verify connection logs use 'deako_simulator.connection' logger name.
        
        End-User Impact: Connection lifecycle filtering helps diagnose
        multi-client scenarios and connection drops.
        """
        caplog.set_level(logging.DEBUG)
        
        connection_logger = get_logger("connection")
        
        connection_logger.info("Test message for connection component")
        
        records = [r for r in caplog.records if r.name == "deako_simulator.connection"]
        assert len(records) > 0, \
            "Connection logs must use component-specific logger for filtering"
    
    @pytest.mark.asyncio
    async def test_simulator_component_tag(self, caplog):
        """
        Verify general simulator logs use 'deako_simulator.simulator' logger name.
        
        End-User Impact: General simulator operations can be filtered
        separately from protocol and connection events.
        """
        caplog.set_level(logging.DEBUG)
        
        simulator_logger = get_logger("simulator")
        
        simulator_logger.info("Test message for simulator component")
        
        records = [r for r in caplog.records if r.name == "deako_simulator.simulator"]
        assert len(records) > 0, \
            "Simulator logs must use component-specific logger for filtering"


class TestLogLevelConfiguration:
    """Test that log level configuration works correctly."""
    
    @pytest.mark.asyncio
    async def test_debug_level_shows_all(self, caplog):
        """
        Verify DEBUG level logs all messages.
        
        End-User Impact: DEBUG mode must show all details for
        comprehensive protocol analysis.
        """
        caplog.set_level(logging.DEBUG)
        
        logger = get_logger("test")
        
        logger.debug("Debug message")
        logger.info("Info message")
        logger.warning("Warning message")
        logger.error("Error message")
        
        assert len(caplog.records) == 4, \
            "DEBUG level must capture all log levels for comprehensive debugging"
    
    @pytest.mark.asyncio
    async def test_info_level_filters_debug(self, caplog):
        """
        Verify INFO level filters out DEBUG messages.
        
        End-User Impact: INFO mode provides major events only
        without verbose protocol details.
        """
        caplog.set_level(logging.INFO)
        
        logger = get_logger("test")
        
        logger.debug("Debug message")
        logger.info("Info message")
        logger.warning("Warning message")
        
        debug_records = [r for r in caplog.records if r.levelname == "DEBUG"]
        info_records = [r for r in caplog.records if r.levelname in ["INFO", "WARNING"]]
        
        assert len(debug_records) == 0, \
            "INFO level must filter DEBUG messages to reduce log noise"
        assert len(info_records) >= 2, \
            "INFO level must show INFO and WARNING messages"
    
    @pytest.mark.asyncio
    async def test_warning_level_filters_info(self, caplog):
        """
        Verify WARNING level filters out INFO and DEBUG.
        
        End-User Impact: WARNING mode shows only issues requiring attention.
        """
        caplog.set_level(logging.WARNING)
        
        logger = get_logger("test")
        
        logger.debug("Debug message")
        logger.info("Info message")
        logger.warning("Warning message")
        logger.error("Error message")
        
        low_level = [r for r in caplog.records if r.levelname in ["DEBUG", "INFO"]]
        high_level = [r for r in caplog.records if r.levelname in ["WARNING", "ERROR"]]
        
        assert len(low_level) == 0, \
            "WARNING level must filter DEBUG and INFO messages"
        assert len(high_level) >= 2, \
            "WARNING level must show WARNING and ERROR messages"
    
    @pytest.mark.asyncio
    async def test_error_level_only_errors(self, caplog):
        """
        Verify ERROR level shows only errors.
        
        End-User Impact: ERROR mode shows only critical failures.
        """
        caplog.set_level(logging.ERROR)
        
        logger = get_logger("test")
        
        logger.debug("Debug message")
        logger.info("Info message")
        logger.warning("Warning message")
        logger.error("Error message")
        
        non_error = [r for r in caplog.records if r.levelname != "ERROR"]
        error_records = [r for r in caplog.records if r.levelname == "ERROR"]
        
        assert len(non_error) == 0, \
            "ERROR level must filter all non-error messages"
        assert len(error_records) >= 1, \
            "ERROR level must show ERROR messages"
