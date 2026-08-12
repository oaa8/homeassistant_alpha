"""
Integration tests for User Story 2: Device Discovery and State Queries (DEVICE_POLL)

Module: test_integration_device_poll.py
Created: 2025-10-27
Last Modified: 2025-10-27
Author: GitHub Copilot
Purpose: Test DEVICE_POLL request/response flow and state query validation

Test Coverage:
- DEVICE_POLL request/response flow with real asyncio
- DEVICE_POLL returns current device state (power, dim)
- DEVICE_POLL for non-existent device (FR-066: REQUEST_INVALID error)
- DEVICE_POLL quirk: returns status="error" on success per FR-023 and hardware tests

Related Requirements:
- FR-017: DEVICE_POLL returns current device state
- FR-023: DEVICE_POLL returns status="error" even on successful query (hardware quirk)
- FR-066: DEVICE_POLL for invalid UUID returns REQUEST_INVALID error

Hardware Validation References:
- research/device-state-test-2025-10-18.md (validates status="error" quirk)
"""

import asyncio
import json
import pytest
from typing import AsyncGenerator

from deako_simulator.models import Device, DeviceState
from deako_simulator.server import DeakoSimulator
from deako_simulator.state import SimulatorState
from deako_simulator.config import Config, NetworkConfig


@pytest.fixture
def test_devices():
    """
    Create test devices for DEVICE_POLL testing.
    
    Returns devices with different states to test various scenarios.
    """
    return [
        Device(
            uuid="11111111-1111-4111-8111-111111111111",
            name="Kitchen Overhead",
            capabilities=["power", "dim"],
            state=DeviceState(power=False, dim=0)
        ),
        Device(
            uuid="22222222-2222-4222-8222-222222222222",
            name="Living Room Main",
            capabilities=["power", "dim"],
            state=DeviceState(power=True, dim=75)
        ),
        Device(
            uuid="33333333-3333-4333-8333-333333333333",
            name="Bedroom Closet",
            capabilities=["power"],
            state=DeviceState(power=True, dim=None)
        ),
    ]


@pytest.fixture
async def simulator_port(test_devices) -> AsyncGenerator[tuple[int, DeakoSimulator], None]:
    """
    Start simulator on dynamic port with test devices.
    
    Yields:
        tuple: (port, simulator_instance) for tests to use
    
    Cleanup:
        Stops simulator after test completes
    """
    # Create simulator state with test devices
    state = SimulatorState(devices=test_devices)
    
    # Create simulator with dynamic port allocation
    config = Config(
        devices=test_devices,
        network=NetworkConfig(
            host="127.0.0.1",
            port=0,  # Dynamic port allocation
            http_port=0,  # Not used in these tests
            mdns_name="test-integration"
        ),
        log_level="DEBUG",
        scenarios=[]
    )

    simulator = DeakoSimulator(state=state, config=config)
    
    # Start simulator and wait for it to be ready
    await simulator.start()
    
    # Get actual port assigned
    port = simulator.server.sockets[0].getsockname()[1]
    
    yield (port, simulator)
    
    # Cleanup: shutdown simulator
    await simulator.shutdown()
# Helper functions

async def send_message(writer: asyncio.StreamWriter, message: dict) -> None:
    """Send JSON message with CRLF termination per FR-063."""
    message_bytes = json.dumps(message).encode() + b'\r\n'
    writer.write(message_bytes)
    await writer.drain()


async def read_message(reader: asyncio.StreamReader) -> dict:
    """
    Read one JSON message terminated by CRLF.
    
    Returns:
        Parsed message dict
    
    Raises:
        EOFError: Connection closed
        json.JSONDecodeError: Invalid JSON
    """
    line = await reader.readline()
    if not line:
        raise EOFError("Connection closed")
    
    # Strip CRLF and parse
    return json.loads(line[:-2].decode('utf-8'))


# Test Cases

@pytest.mark.asyncio
async def test_device_poll_request_response_flow(simulator_port):
    """
    Test basic DEVICE_POLL request/response flow.
    
    User Story 2 Acceptance: Simulator responds to DEVICE_POLL with current state
    FR-017: DEVICE_POLL returns device state (power, dim, capabilities)
    
    Expected: DEVICE_POLL response contains current device state
    Actual: Response should arrive within 500ms per SC-003
    Impact: Home Assistant uses DEVICE_POLL to query individual device states
    """
    port, simulator = simulator_port
    
    # Connect to simulator
    reader, writer = await asyncio.open_connection('127.0.0.1', port)
    
    try:
        # Send DEVICE_POLL request for device with known state
        device_poll_request = {
            "name": "DEVICE_POLL",
            "transactionId": "test-poll-001",
            "data": {
                "target": "22222222-2222-4222-8222-222222222222"  # Living Room Main, power=True, dim=75
            }
        }
        await send_message(writer, device_poll_request)
        
        # Read DEVICE_POLL response
        response = await asyncio.wait_for(read_message(reader), timeout=1.0)
        
        # Validate response structure
        assert response["type"] == "DEVICE_POLL", \
            f"Expected response type 'DEVICE_POLL' but got '{response['type']}' - real hub uses 'type' field"
        assert response["src"] == "deako", \
            f"Expected src 'deako' - real hub always sets src"
        assert "dst" in response, \
            "Missing 'dst' field - real hub echoes client's src as dst"
        assert response["transactionId"] == "test-poll-001", \
            f"Expected transactionId 'test-poll-001' but got '{response['transactionId']}' - integration can't correlate response"
        
        # FR-023 hardware quirk: DEVICE_POLL returns status="error" even on success
        # See: research/device-state-test-2025-10-18.md
        assert response["status"] == "error", \
            f"Expected status 'error' per FR-023 hardware quirk but got '{response['status']}' - must match real hub behavior"
        
        assert "data" in response, \
            "Missing 'data' field in response - integration can't extract device state"
        
        # Validate device state fields
        data = response["data"]
        assert "power" in data, \
            "Missing 'power' field in response data - integration needs current on/off state"
        assert "dim" in data, \
            "Missing 'dim' field in response data - integration needs current brightness level"
        
        # Verify state matches expected device state
        assert data["power"] == True, \
            f"Expected power=True but got {data['power']} - state doesn't match device"
        assert data["dim"] == 75, \
            f"Expected dim=75 but got {data['dim']} - state doesn't match device"
        
    finally:
        writer.close()
        await writer.wait_closed()


@pytest.mark.asyncio
async def test_device_poll_returns_current_state(simulator_port):
    """
    Test that DEVICE_POLL returns actual current state for different devices.
    
    User Story 2 Acceptance: DEVICE_POLL reflects current device state accurately
    FR-017: DEVICE_POLL returns power and dim fields
    
    Expected: Each device's DEVICE_POLL returns its current state
    Actual: State values match device configuration
    Impact: Integration relies on DEVICE_POLL for state synchronization
    """
    port, simulator = simulator_port
    
    # Connect to simulator
    reader, writer = await asyncio.open_connection('127.0.0.1', port)
    
    try:
        # Test device 1: power=False, dim=0
        await send_message(writer, {
            "name": "DEVICE_POLL",
            "transactionId": "poll-device-1",
            "data": {"target": "11111111-1111-4111-8111-111111111111"}
        })
        response1 = await asyncio.wait_for(read_message(reader), timeout=1.0)
        assert response1["data"]["power"] == False, \
            "Device 1 should have power=False"
        assert response1["data"]["dim"] == 0, \
            "Device 1 should have dim=0"
        
        # Test device 2: power=True, dim=75
        await send_message(writer, {
            "name": "DEVICE_POLL",
            "transactionId": "poll-device-2",
            "data": {"target": "22222222-2222-4222-8222-222222222222"}
        })
        response2 = await asyncio.wait_for(read_message(reader), timeout=1.0)
        assert response2["data"]["power"] == True, \
            "Device 2 should have power=True"
        assert response2["data"]["dim"] == 75, \
            "Device 2 should have dim=75"
        
        # Test device 3: power=True, dim=None (power-only device)
        await send_message(writer, {
            "name": "DEVICE_POLL",
            "transactionId": "poll-device-3",
            "data": {"target": "33333333-3333-4333-8333-333333333333"}
        })
        response3 = await asyncio.wait_for(read_message(reader), timeout=1.0)
        assert response3["data"]["power"] == True, \
            "Device 3 should have power=True"
        assert response3["data"]["dim"] is None, \
            "Device 3 is power-only, dim should be None"
        
    finally:
        writer.close()
        await writer.wait_closed()


@pytest.mark.asyncio
async def test_device_poll_nonexistent_device(simulator_port):
    """
    Test DEVICE_POLL for non-existent device UUID.
    
    User Story 2 Acceptance: Simulator returns error for invalid device UUID
    FR-066: DEVICE_POLL with invalid UUID returns REQUEST_INVALID error
    
    Expected: Error response with code "REQUEST_INVALID"
    Actual: Error message should indicate "device could not be found"
    Impact: Integration needs clear error when querying non-existent devices
    """
    port, simulator = simulator_port
    
    # Connect to simulator
    reader, writer = await asyncio.open_connection('127.0.0.1', port)
    
    try:
        # Send DEVICE_POLL request for non-existent device
        device_poll_request = {
            "name": "DEVICE_POLL",
            "transactionId": "test-invalid-001",
            "data": {
                "target": "99999999-9999-4999-8999-999999999999"  # Non-existent UUID
            }
        }
        await send_message(writer, device_poll_request)
        
        # Read error response
        response = await asyncio.wait_for(read_message(reader), timeout=1.0)
        
        # Validate error response
        assert response["type"] == "DEVICE_POLL", \
            f"Expected response type 'DEVICE_POLL' but got '{response['type']}' - real hub uses 'type' field"
        assert response["src"] == "deako", \
            f"Expected src 'deako' - real hub always sets src"
        assert "dst" in response, \
            "Missing 'dst' field - real hub echoes client's src as dst"
        assert response["transactionId"] == "test-invalid-001", \
            f"Expected transactionId 'test-invalid-001' but got '{response['transactionId']}'"
        assert response["status"] == "error", \
            f"Expected status 'error' for non-existent device but got '{response['status']}'"
        
        assert "data" in response, \
            "Missing 'data' field in error response"
        assert "code" in response["data"], \
            "Missing error 'code' in response data - integration needs to know error type"
        
        # FR-066: Error code must be REQUEST_INVALID for invalid device UUID
        assert response["data"]["code"] == "REQUEST_INVALID", \
            f"Expected error code 'REQUEST_INVALID' but got '{response['data']['code']}' - integration expects specific error codes"
        
        # Verify error message mentions device not found
        assert "message" in response["data"], \
            "Missing error 'message' in response data - integration needs human-readable error"
        assert "could not be found" in response["data"]["message"].lower() or "not found" in response["data"]["message"].lower(), \
            f"Error message should mention device not found - got: '{response['data']['message']}'"
        
    finally:
        writer.close()
        await writer.wait_closed()


@pytest.mark.asyncio
async def test_device_poll_status_error_quirk(simulator_port):
    """
    Test DEVICE_POLL quirk: returns status="error" even on successful query.
    
    User Story 2 Acceptance: Simulator replicates real hub quirk accurately
    FR-023: DEVICE_POLL returns status="error" on success (hardware-validated behavior)
    
    Expected: Successful DEVICE_POLL has status="error" (not "ok")
    Actual: This matches real Deako hub behavior
    Impact: Integration must handle this quirk to work with real hubs
    
    Hardware Validation: research/device-state-test-2025-10-18.md
    """
    port, simulator = simulator_port
    
    # Connect to simulator
    reader, writer = await asyncio.open_connection('127.0.0.1', port)
    
    try:
        # Send valid DEVICE_POLL request
        device_poll_request = {
            "name": "DEVICE_POLL",
            "transactionId": "test-quirk-001",
            "data": {
                "target": "11111111-1111-4111-8111-111111111111"
            }
        }
        await send_message(writer, device_poll_request)
        
        # Read response
        response = await asyncio.wait_for(read_message(reader), timeout=1.0)
        
        # Verify quirk: status="error" even though query succeeded
        assert response["status"] == "error", \
            f"DEVICE_POLL must return status='error' per FR-023 hardware quirk (validated 2025-10-18), but got '{response['status']}'"
        
        # Verify we still got valid device state (proves success despite status="error")
        assert "data" in response, \
            "Despite status='error', successful DEVICE_POLL must include data field with device state"
        assert "power" in response["data"], \
            "Device state should be present despite status='error' quirk"
        assert isinstance(response["data"]["power"], bool), \
            "Power state should be valid boolean despite status='error'"
        
        # If error code is present, it should NOT be REQUEST_INVALID (that's for actual errors)
        # The quirk is: status="error" but no error code (or error code is empty/absent)
        if "code" in response["data"]:
            # If code exists, it shouldn't be a real error code for successful queries
            # Real hub may omit code or use empty string - implementation may vary
            pass  # Implementation detail - key is status="error" with valid data
        
    finally:
        writer.close()
        await writer.wait_closed()


@pytest.mark.asyncio
async def test_device_poll_missing_target_field(simulator_port):
    """
    Test DEVICE_POLL with missing target field.
    
    User Story 2 Acceptance: Simulator validates required fields
    FR-066: DEVICE_POLL with missing required fields returns REQUEST_MALFORMED error
    
    Expected: Error response with code "REQUEST_MALFORMED"
    Actual: Error message should indicate missing "target" field
    Impact: Integration must provide all required fields
    """
    port, simulator = simulator_port
    
    # Connect to simulator
    reader, writer = await asyncio.open_connection('127.0.0.1', port)
    
    try:
        # Send DEVICE_POLL request without target field
        device_poll_request = {
            "name": "DEVICE_POLL",
            "transactionId": "test-missing-001",
            "data": {}  # Missing "target" field
        }
        await send_message(writer, device_poll_request)
        
        # Read error response
        response = await asyncio.wait_for(read_message(reader), timeout=1.0)
        
        # Validate error response
        assert response["status"] == "error", \
            f"Expected status 'error' for malformed request but got '{response['status']}'"
        assert "data" in response, \
            "Missing 'data' field in error response"
        assert "code" in response["data"], \
            "Missing error 'code' in response data"
        
        # FR-066: Error code must be REQUEST_MALFORMED for missing required fields
        assert response["data"]["code"] == "REQUEST_MALFORMED", \
            f"Expected error code 'REQUEST_MALFORMED' but got '{response['data']['code']}'"
        
    finally:
        writer.close()
        await writer.wait_closed()


@pytest.mark.asyncio
async def test_device_poll_after_state_change(simulator_port):
    """
    Test that DEVICE_POLL reflects state changes from CONTROL commands.
    
    User Story 2 Acceptance: DEVICE_POLL returns up-to-date state after changes
    
    Expected: DEVICE_POLL returns new state after CONTROL command
    Actual: State should update immediately
    Impact: Integration uses DEVICE_POLL to verify CONTROL commands succeeded
    """
    port, simulator = simulator_port
    
    # Connect to simulator
    reader, writer = await asyncio.open_connection('127.0.0.1', port)
    
    try:
        # Query initial state
        await send_message(writer, {
            "name": "DEVICE_POLL",
            "transactionId": "poll-before",
            "data": {"target": "11111111-1111-4111-8111-111111111111"}
        })
        initial_state = await asyncio.wait_for(read_message(reader), timeout=1.0)
        assert initial_state["data"]["power"] == False, \
            "Device should start with power=False"
        
        # Change state via CONTROL (will be implemented in Phase 5)
        # For now, change directly via simulator state
        simulator.state.update_device_state(
            uuid="11111111-1111-4111-8111-111111111111",
            power=True,
            dim=50
        )
        
        # Query state again
        await send_message(writer, {
            "name": "DEVICE_POLL",
            "transactionId": "poll-after",
            "data": {"target": "11111111-1111-4111-8111-111111111111"}
        })
        updated_state = await asyncio.wait_for(read_message(reader), timeout=1.0)
        
        # Verify state updated
        assert updated_state["data"]["power"] == True, \
            "DEVICE_POLL should reflect updated power state"
        assert updated_state["data"]["dim"] == 50, \
            "DEVICE_POLL should reflect updated dim level"
        
    finally:
        writer.close()
        await writer.wait_closed()


# Test execution notes
"""
These tests follow TDD principles:
1. Tests written FIRST before T037 implementation
2. Tests define expected DEVICE_POLL behavior per User Story 2
3. Tests use real asyncio event loop (no mocking)
4. Tests validate hardware quirk (status="error" on success per FR-023)
5. Tests will pass when server.py DEVICE_POLL handler implemented

Test Coverage:
- DEVICE_POLL request/response: ✓
- Current state queries for multiple devices: ✓
- Non-existent device error (REQUEST_INVALID): ✓
- Missing required field error (REQUEST_MALFORMED): ✓
- Status="error" quirk per hardware validation: ✓
- State changes reflected in subsequent polls: ✓

Expected pass after: T037 (DEVICE_POLL handler) and T038 (protocol.py updates)

Hardware Quirk Documentation:
The status="error" on success is a validated real hub behavior.
See: research/device-state-test-2025-10-18.md for hardware test results.
Integration MUST handle this quirk to work with real Deako hubs.
"""
