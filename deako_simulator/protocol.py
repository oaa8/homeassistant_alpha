"""Protocol message parsing and formatting for Deako Hub Simulator.

Author: GitHub Copilot
Created: 2025-10-26
Last Modified: 2025-10-26
Purpose: Parse incoming JSON messages, format responses, create protocol messages

Key Assumptions:
- All messages are line-delimited JSON with CRLF termination (\\r\\n)
- Message types are uppercase strings ("PING", "DEVICE_LIST", "CONTROL", etc.)
- Malformed JSON is silently ignored per FR-077
- Extra fields in messages are ignored per FR-078
- Uppercase message type required per FR-079

Hardware Quirks (validated via research):
- DEVICE_POLL returns status="error" even on success (FR-023)
- Whitespace-only messages silently ignored (research/whitespace-behavior-test)
- CRLF required, LF-only rejected (research/message-format-edge-cases-test)

Related Research:
- specs/001-deako-hub-simulator/research/message-format-edge-cases-test-2025-10-18.md
- specs/001-deako-hub-simulator/research/device-state-test-2025-10-18.md
- specs/001-deako-hub-simulator/contracts/messages.schema.json
"""

from __future__ import annotations

import json
import time
from typing import Any

from deako_simulator.models import Device


def parse_message(line: str) -> dict[str, Any] | None:
    """Parse JSON message from line.
    
    Validates:
    - CRLF termination (\\r\\n)
    - Valid JSON structure
    - Required fields present
    
    Args:
        line: Raw line from telnet connection (should include \\r\\n)
        
    Returns:
        Parsed message dict, or None if invalid
        
    Behavior (per hardware validation):
    - Malformed JSON: silently ignored (FR-077), returns None
    - Missing CRLF: silently ignored, returns None
    - Whitespace-only: silently ignored, returns None
    - Extra fields: ignored (FR-078)
    
    Research references:
    - FR-077: Malformed messages silently ignored
    - research/message-format-edge-cases-test-2025-10-18.md
    """
    # Validate CRLF termination
    if not line.endswith('\r\n'):
        return None
    
    # Strip CRLF for parsing
    json_str = line[:-2]
    
    # Ignore whitespace-only messages
    if not json_str.strip():
        return None
    
    # Parse JSON
    try:
        message = json.loads(json_str)
    except (json.JSONDecodeError, ValueError):
        # Silently ignore malformed JSON per FR-077
        return None
    
    # Validate basic structure
    if not isinstance(message, dict):
        return None
    
    # Accept either 'type' or 'name' field for message type
    # Real Deako hub uses 'type' in requests and responses
    if 'type' not in message and 'name' not in message:
        return None
    
    return message


def format_response(message: dict[str, Any]) -> str:
    """Format message dict to JSON string with CRLF.
    
    Args:
        message: Message dictionary
        
    Returns:
        JSON string with CRLF terminator
        
    Format:
    - Compact JSON (no extra whitespace)
    - CRLF terminator (\\r\\n)
    - Timestamp added if not present (Unix milliseconds)
    
    Research reference:
    - FR-063: All messages must end with CRLF
    """
    # Add timestamp if not present
    if 'timestamp' not in message:
        message['timestamp'] = int(time.time() * 1000)
    
    # Format as compact JSON with CRLF
    json_str = json.dumps(message, separators=(',', ':'))
    return json_str + '\r\n'


def create_device_list_response(count: int, transaction_id: str, client_name: str = "unknown") -> dict[str, Any]:
    """Create DEVICE_LIST response message.
    
    Args:
        count: Total number of devices
        transaction_id: Client-provided correlation ID
        client_name: Client identifier from request 'src' field
        
    Returns:
        DEVICE_LIST response dict
        
    Message format (per research/protocol-testing-2025-01-15.md):
    {
        "type": "DEVICE_LIST",
        "transactionId": "...",
        "dst": "<client_name>",
        "src": "deako",
        "status": "ok",
        "data": {"number_of_devices": N},
        "timestamp": <unix_ms>
    }
    """
    return {
        "type": "DEVICE_LIST",
        "transactionId": transaction_id,
        "dst": client_name,
        "src": "deako",
        "status": "ok",
        "data": {
            "number_of_devices": count
        }
    }


def create_device_found(device: Device, timestamp: int | None = None) -> dict[str, Any]:
    """Create DEVICE_FOUND message (server push).
    
    Args:
        device: Device to announce
        timestamp: Unix timestamp in milliseconds (generated if None)
        
    Returns:
        DEVICE_FOUND message dict
        
    Message format per research/protocol-testing-2025-01-15.md:
    {
        "type": "DEVICE_FOUND",
        "src": "deako",
        "data": {
            "uuid": "...",
            "name": "...",
            "capabilities": "power" or "power+dim",
            "state": {
                "power": true/false,
                "dim": 0-100 or null (only for dimmable)
            }
        },
        "timestamp": <unix_ms>
    }
    
    Note: Real hub uses "power+dim" string format for capabilities, not array.
    """
    if timestamp is None:
        timestamp = int(time.time() * 1000)
    
    # Convert capabilities array to real hub format: "power" or "power+dim"
    if "dim" in device.capabilities:
        capabilities_str = "power+dim"
    else:
        capabilities_str = "power"
    
    # Build state dict - only include dim if device is dimmable
    # Per research: power-only devices have state with ONLY power field
    state = {"power": device.state.power}
    if "dim" in device.capabilities:
        state["dim"] = device.state.dim
    
    return {
        "type": "DEVICE_FOUND",
        "src": "deako",
        "data": {
            "uuid": device.uuid,
            "name": device.name,
            "capabilities": capabilities_str,  # Real hub uses string, not array
            "state": state
        },
        "timestamp": timestamp
    }


def create_event(device_uuid: str, state: dict[str, Any], timestamp: int | None = None) -> dict[str, Any]:
    """Create EVENT message (state change broadcast).
    
    Args:
        device_uuid: UUID of device that changed
        state: New device state with power and dim fields
        timestamp: Unix timestamp in milliseconds (generated if None)
        
    Returns:
        EVENT message dict
        
    Message format per research/protocol-testing-2025-01-15.md:
    {
        "type": "EVENT",
        "src": "deako",
        "data": {
            "eventType": "DEVICE_STATE_CHANGE",
            "target": "...",
            "state": {
                "power": true/false,
                "dim": 0-100 or null
            }
        },
        "timestamp": <unix_ms>
    }
    
    Research reference:
    - FR-075: EVENT contains full device state (power + dim), not just changed fields
    - research/physical-button-behavior-test-2025-10-18.md
    """
    if timestamp is None:
        timestamp = int(time.time() * 1000)
    
    return {
        "type": "EVENT",
        "src": "deako",
        "data": {
            "eventType": "DEVICE_STATE_CHANGE",
            "target": device_uuid,
            "state": {
                "power": state["power"],
                "dim": state.get("dim")
            }
        },
        "timestamp": timestamp
    }


def create_control_response(transaction_id: str, status: str, client_name: str = "unknown", error: str | None = None) -> dict[str, Any]:
    """Create CONTROL response message.
    
    Args:
        transaction_id: Client-provided correlation ID
        status: Response status ("ok" or "error")
        client_name: Client identifier from request 'src' field
        error: Error message (required if status="error")
        
    Returns:
        CONTROL response dict
        
    Message format:
    {
        "type": "CONTROL",
        "transactionId": "...",
        "dst": "<client_name>",
        "src": "deako",
        "status": "ok" | "error",
        "error": "..." (only if status="error"),
        "timestamp": <unix_ms>
    }
    """
    response = {
        "type": "CONTROL",
        "transactionId": transaction_id,
        "dst": client_name,
        "src": "deako",
        "status": status
    }
    
    if error:
        response["error"] = error
    
    return response


def create_ping_response(transaction_id: str, client_name: str = "unknown") -> dict[str, Any]:
    """Create PING response message.
    
    Args:
        transaction_id: Client-provided correlation ID
        client_name: Client identifier from request 'src' field
        
    Returns:
        PING response dict
        
    Message format:
    {
        "type": "PING",
        "transactionId": "...",
        "dst": "<client_name>",
        "src": "deako",
        "status": "ok",
        "timestamp": <unix_ms>
    }
    """
    return {
        "type": "PING",
        "transactionId": transaction_id,
        "dst": client_name,
        "src": "deako",
        "status": "ok"
    }


def create_device_poll_response(device: Device, transaction_id: str, client_name: str = "unknown") -> dict[str, Any]:
    """Create DEVICE_POLL response message.
    
    QUIRK: Real hub returns status="error" even on successful poll (FR-023).
    This matches hardware behavior validated 2025-10-18.
    
    Args:
        device: Device to return state for
        transaction_id: Client-provided correlation ID
        client_name: Client identifier from request 'src' field
        
    Returns:
        DEVICE_POLL response dict
        
    Message format (QUIRK: status always "error"):
    {
        "type": "DEVICE_POLL",
        "transactionId": "...",
        "dst": "<client_name>",
        "src": "deako",
        "status": "error",  // QUIRK: Always "error", even on success
        "data": {
            "uuid": "...",
            "name": "...",
            "power": true/false,
            "dim": 0-100 or null
        },
        "timestamp": <unix_ms>
    }
    
    Research reference:
    - FR-023: DEVICE_POLL quirk documented
    - research/device-state-test-2025-10-18.md: Validated status="error" on success
    """
    return {
        "type": "DEVICE_POLL",
        "transactionId": transaction_id,
        "dst": client_name,
        "src": "deako",
        "status": "error",  # QUIRK: Always "error", even on success (FR-023)
        "data": {
            "uuid": device.uuid,
            "name": device.name,
            "power": device.state.power,
            "dim": device.state.dim
        }
    }


def create_error_response(
    transaction_id: str, 
    error_code: str, 
    message: str,
    message_type: str = "ERROR",
    client_name: str = "unknown"
) -> dict[str, Any]:
    """Create error response message.
    
    Only 3 error codes exist per research validation (FR-066):
    - REQUEST_UNKNOWN: Invalid message type
    - REQUEST_MALFORMED: Valid JSON but missing required fields
    - REQUEST_INVALID: Invalid data values (e.g., device not found)
    
    IMPORTANT: DEVICE_BUSY and DEVICE_UNKNOWN do not exist on real hub.
    
    Args:
        transaction_id: Client-provided correlation ID (or generated if not available)
        error_code: Error code (REQUEST_UNKNOWN | REQUEST_MALFORMED | REQUEST_INVALID)
        message: Human-readable error description
        message_type: Original message type to echo back (default: "ERROR")
        client_name: Client identifier from request 'src' field
        
    Returns:
        Error response dict
        
    Message format:
    {
        "type": "<ORIGINAL_MESSAGE_TYPE>",  // Echo original message type if known, else "ERROR"
        "transactionId": "...",
        "dst": "<client_name>",
        "src": "deako",
        "status": "error",
        "data": {
            "code": "REQUEST_UNKNOWN" | "REQUEST_MALFORMED" | "REQUEST_INVALID",
            "message": "..."
        },
        "timestamp": <unix_ms>
    }
    
    Research reference:
    - FR-066: Only 3 error codes exist
    - research/error-code-validation-test-2025-10-18.md: DEVICE_BUSY and DEVICE_UNKNOWN do not exist
    """
    return {
        "type": message_type,  # Echo original message type or use "ERROR"
        "transactionId": transaction_id,
        "dst": client_name,
        "src": "deako",
        "status": "error",
        "data": {
            "code": error_code,
            "message": message
        }
    }
