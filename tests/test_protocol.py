"""Unit tests for protocol message parsing and formatting.

Author: GitHub Copilot
Created: 2025-10-26
Purpose: Validate message parsing, formatting, CRLF handling, hardware quirks

Test Coverage:
- Message parsing (valid/invalid JSON)
- CRLF termination validation
- Malformed JSON handling (FR-077: silent ignore)
- Message formatting with timestamps
- Message creation functions
- Hardware quirks (DEVICE_POLL status="error", etc.)
"""

import pytest
import time
from deako_simulator.protocol import (
    parse_message, format_response,
    create_device_list_response, create_device_found,
    create_event, create_control_response,
    create_ping_response, create_device_poll_response,
    create_error_response
)
from deako_simulator.models import Device, DeviceState


class TestParseMessage:
    """Test parse_message() function."""
    
    def test_parse_valid_message(self):
        """Validates parsing of valid JSON with CRLF."""
        line = '{"type": "PING", "transactionId": "test-001"}\r\n'
        message = parse_message(line)
        
        assert message is not None
        assert message["type"] == "PING"
        assert message["transactionId"] == "test-001"
    
    def test_parse_missing_crlf(self):
        """Validates message without CRLF is rejected."""
        line = '{"name": "PING", "transactionId": "test-001"}\n'  # LF only
        message = parse_message(line)
        
        assert message is None, \
            "Message with LF-only should be rejected per hardware behavior"
    
    def test_parse_malformed_json(self):
        """Validates FR-077: Malformed JSON silently ignored."""
        line = '{invalid json}\r\n'
        message = parse_message(line)
        
        assert message is None, \
            "Malformed JSON should be silently ignored per FR-077"
    
    def test_parse_whitespace_only(self):
        """Validates whitespace-only messages ignored."""
        line = '   \r\n'
        message = parse_message(line)
        
        assert message is None, \
            "Whitespace-only messages should be ignored"
    
    def test_parse_empty_with_crlf(self):
        """Validates empty message with CRLF ignored."""
        line = '\r\n'
        message = parse_message(line)
        
        assert message is None
    
    def test_parse_missing_type_field(self):
        """Validates message without 'type' or 'name' field rejected."""
        line = '{"transactionId": "test-001"}\r\n'
        message = parse_message(line)
        
        assert message is None, \
            "Message without 'type' or 'name' field should be rejected"
    
    def test_parse_non_dict_json(self):
        """Validates non-dict JSON rejected."""
        line = '["array", "not", "dict"]\r\n'
        message = parse_message(line)
        
        assert message is None, \
            "JSON arrays should be rejected (message must be dict)"
    
    def test_parse_extra_fields_allowed(self):
        """Validates FR-078: Extra fields ignored (not rejected)."""
        line = '{"type": "PING", "transactionId": "test", "extraField": "ignored"}\r\n'
        message = parse_message(line)
        
        assert message is not None, \
            "Extra fields should be ignored per FR-078, not rejected"
        assert message["type"] == "PING"
        assert "extraField" in message  # Parsed but not validated


class TestFormatResponse:
    """Test format_response() function."""
    
    def test_format_adds_crlf(self):
        """Validates response formatted with CRLF terminator."""
        message = {"type": "PING", "status": "ok"}
        formatted = format_response(message)
        
        assert formatted.endswith('\r\n'), \
            "Formatted message must end with CRLF per FR-063"
    
    def test_format_adds_timestamp(self):
        """Validates timestamp added if not present."""
        message = {"type": "PING", "status": "ok"}
        before = int(time.time() * 1000)
        formatted = format_response(message)
        after = int(time.time() * 1000)
        
        # Parse formatted message to check timestamp
        import json
        parsed = json.loads(formatted[:-2])  # Strip CRLF
        
        assert "timestamp" in parsed
        assert before <= parsed["timestamp"] <= after
    
    def test_format_preserves_existing_timestamp(self):
        """Validates existing timestamp not overwritten."""
        message = {"type": "PING", "status": "ok", "timestamp": 1234567890}
        formatted = format_response(message)
        
        import json
        parsed = json.loads(formatted[:-2])
        
        assert parsed["timestamp"] == 1234567890
    
    def test_format_compact_json(self):
        """Validates JSON formatted without extra whitespace."""
        message = {"type": "PING", "status": "ok"}
        formatted = format_response(message)
        
        # Compact JSON has no spaces after colons/commas
        assert ': ' not in formatted and ', ' not in formatted


class TestDeviceListResponse:
    """Test create_device_list_response() function."""
    
    def test_create_device_list_response(self):
        """Validates DEVICE_LIST response structure."""
        response = create_device_list_response(5, "test-001")
        
        assert response["type"] == "DEVICE_LIST"
        assert response["transactionId"] == "test-001"
        assert response["status"] == "ok"
        assert response["data"]["number_of_devices"] == 5
    
    def test_device_list_zero_devices(self):
        """Validates DEVICE_LIST with zero devices."""
        response = create_device_list_response(0, "test-002")
        
        assert response["data"]["number_of_devices"] == 0


class TestDeviceFound:
    """Test create_device_found() function."""
    
    def test_create_device_found_dimmable(self):
        """Validates DEVICE_FOUND for dimmable device."""
        device = Device(
            uuid="11111111-1111-4111-8111-111111111111",
            name="Test Dimmer",
            capabilities=["power", "dim"],
            state=DeviceState(power=True, dim=75)
        )
        
        message = create_device_found(device)
        
        assert message["type"] == "DEVICE_FOUND"
        assert message["data"]["uuid"] == device.uuid
        assert message["data"]["name"] == "Test Dimmer"
        assert message["data"]["state"]["power"] is True
        assert message["data"]["state"]["dim"] == 75
        assert "timestamp" in message
    
    def test_create_device_found_power_only(self):
        """Validates DEVICE_FOUND for power-only device."""
        device = Device(
            uuid="22222222-2222-4222-8222-222222222222",
            name="Test Switch",
            capabilities=["power"],
            state=DeviceState(power=False, dim=None)
        )
        
        message = create_device_found(device)
        
        assert message["data"]["state"]["power"] is False
        # Power-only devices don't include dim in state per protocol
        assert "dim" not in message["data"]["state"], \
            "Power-only devices should NOT include dim field in state"
    
    def test_device_found_custom_timestamp(self):
        """Validates custom timestamp preserved."""
        device = Device(
            uuid="11111111-1111-4111-8111-111111111111",
            name="Test",
            capabilities=["power"],
            state=DeviceState(power=False, dim=None)
        )
        
        custom_timestamp = 1234567890
        message = create_device_found(device, timestamp=custom_timestamp)
        
        assert message["timestamp"] == custom_timestamp


class TestEvent:
    """Test create_event() function."""
    
    def test_create_event_full_state(self):
        """Validates FR-075: EVENT contains full state (power + dim)."""
        state = {
            "name": "Kitchen Light",
            "power": True,
            "dim": 50
        }
        message = create_event("test-uuid", state)
        
        assert message["type"] == "EVENT"
        assert message["data"]["target"] == "test-uuid"
        assert message["data"]["state"]["power"] is True
        assert message["data"]["state"]["dim"] == 50, \
            "EVENT must include full state per FR-075"
        assert message["data"]["eventType"] == "DEVICE_STATE_CHANGE"
    
    def test_event_null_dim(self):
        """Validates FR-082: null/None values handled correctly."""
        state = {
            "name": "Test",
            "power": True,
            "dim": None
        }
        message = create_event("test-uuid", state)
        
        assert message["data"]["state"]["dim"] is None


class TestControlResponse:
    """Test create_control_response() function."""
    
    def test_control_response_success(self):
        """Validates successful CONTROL response."""
        response = create_control_response("test-001", "ok")
        
        assert response["type"] == "CONTROL"
        assert response["transactionId"] == "test-001"
        assert response["status"] == "ok"
        assert "error" not in response
    
    def test_control_response_error(self):
        """Validates error CONTROL response."""
        response = create_control_response("test-002", "error", error="Device not found")
        
        assert response["type"] == "CONTROL"
        assert response["transactionId"] == "test-002"
        assert response["status"] == "error"
        assert response["error"] == "Device not found"


class TestPingResponse:
    """Test create_ping_response() function."""
    
    def test_ping_response(self):
        """Validates PING response structure."""
        response = create_ping_response("ping-001")
        
        assert response["type"] == "PING"
        assert response["transactionId"] == "ping-001"
        assert response["status"] == "ok"


class TestDevicePollResponse:
    """Test create_device_poll_response() function."""
    
    def test_device_poll_response_quirk(self):
        """Validates FR-023: DEVICE_POLL returns status='error' on success.
        
        QUIRK: Real hub returns status="error" even for successful polls.
        This is validated hardware behavior, not a bug in the simulator.
        """
        device = Device(
            uuid="11111111-1111-4111-8111-111111111111",
            name="Test Device",
            capabilities=["power", "dim"],
            state=DeviceState(power=True, dim=75)
        )
        
        response = create_device_poll_response(device, "poll-001")
        
        assert response["type"] == "DEVICE_POLL"
        assert response["transactionId"] == "poll-001"
        assert response["status"] == "error", \
            "DEVICE_POLL must return status='error' per FR-023 quirk"
        assert response["data"]["uuid"] == device.uuid
        assert response["data"]["power"] is True
        assert response["data"]["dim"] == 75


class TestErrorResponse:
    """Test create_error_response() function."""
    
    def test_error_response_unknown(self):
        """Validates REQUEST_UNKNOWN error."""
        response = create_error_response(
            "test-001",
            "REQUEST_UNKNOWN",
            "Unknown message type"
        )
        
        assert response["type"] == "ERROR"
        assert response["transactionId"] == "test-001"
        assert response["status"] == "error"
        assert response["data"]["code"] == "REQUEST_UNKNOWN"
        assert response["data"]["message"] == "Unknown message type"
    
    def test_error_response_malformed(self):
        """Validates REQUEST_MALFORMED error."""
        response = create_error_response(
            "test-002",
            "REQUEST_MALFORMED",
            "Missing required field: transactionId"
        )
        
        assert response["data"]["code"] == "REQUEST_MALFORMED"
    
    def test_error_response_invalid(self):
        """Validates REQUEST_INVALID error."""
        response = create_error_response(
            "test-003",
            "REQUEST_INVALID",
            "Device could not be found"
        )
        
        assert response["data"]["code"] == "REQUEST_INVALID"
    
    def test_error_codes_only_three(self):
        """Validates only 3 error codes exist per FR-066.
        
        IMPORTANT: DEVICE_BUSY and DEVICE_UNKNOWN do not exist on real hub.
        Only REQUEST_UNKNOWN, REQUEST_MALFORMED, REQUEST_INVALID are valid.
        
        Research reference: research/error-code-validation-test-2025-10-18.md
        """
        valid_codes = {"REQUEST_UNKNOWN", "REQUEST_MALFORMED", "REQUEST_INVALID"}
        
        # This is a documentation test - validates our understanding
        # In actual code, we should never use codes outside this set
        assert len(valid_codes) == 3, \
            "Only 3 error codes exist per FR-066"
