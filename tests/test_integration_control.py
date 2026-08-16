"""
Integration tests for CONTROL command (User Story 3).

Tests device control functionality:
- Power on/off control
- Dim level changes
- State updates reflected in queries
- EVENT broadcast with full state (FR-075)
- Rate limiting (100ms minimum, FR-023)
- Acknowledgment timing (<500ms, SC-003)

Author: GitHub Copilot
Created: 2025-10-27
Purpose: Validate CONTROL command behavior matches real Deako hub

Research References:
- FR-018: CONTROL command structure
- FR-023: 100ms minimum spacing, silent dropping
- FR-075: EVENT includes full state (not deltas)
- SC-003: Acknowledgment within 500ms
- research/rate-limiting-systematic-test-2025-10-18.md
"""

import asyncio
import json
import time
from typing import AsyncGenerator

import pytest

from deako_simulator.config import Config, NetworkConfig
from deako_simulator.models import Device, DeviceState
from deako_simulator.server import DeakoSimulator
from deako_simulator.state import SimulatorState


@pytest.fixture
def test_devices() -> list[Device]:
    """Test devices with mix of power-only and dimmable."""
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
            state=DeviceState(power=True, dim=100)
        ),
        Device(
            uuid="33333333-3333-4333-8333-333333333333",
            name="Bedroom Closet",
            capabilities=["power"],
            state=DeviceState(power=False, dim=None)
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


async def send_message(writer: asyncio.StreamWriter, message: dict):
    """
    Send JSON message with CRLF termination.

    Args:
        writer: StreamWriter to send to
        message: Message dict to serialize
    """
    line = json.dumps(message) + '\r\n'
    writer.write(line.encode())
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

    line_str = line.decode('utf-8').strip()
    return json.loads(line_str)


@pytest.mark.asyncio
async def test_control_power_on(simulator_port):
    """
    Test CONTROL command turns device power on.

    User Story 3 Acceptance: Control commands update device state
    FR-018: CONTROL command structure (transactionId, data.uuid, data.power)

    Expected: Power on command updates device state to power=true
    Actual: Subsequent DEVICE_POLL should show power=true
    Impact: Integration needs reliable power control for user commands
    """
    port, simulator = simulator_port

    # Connect to simulator
    reader, writer = await asyncio.open_connection('127.0.0.1', port)

    try:
        # Send CONTROL command to turn power on
        control_request = {
            "name": "CONTROL",
            "transactionId": "test-power-on-001",
            "data": {
                "uuid": "11111111-1111-4111-8111-111111111111",
                "power": True
            }
        }
        await send_message(writer, control_request)

        # Read acknowledgment
        response = await asyncio.wait_for(read_message(reader), timeout=1.0)

        # Validate acknowledgment
        assert response["type"] == "CONTROL", \
            f"Expected response type 'CONTROL' but got '{response['type']}' - real hub uses 'type' field"
        assert response["src"] == "deako", \
            f"Expected src 'deako' but got '{response.get('src')}' - real hub always sets src"
        assert "dst" in response, \
            "Missing 'dst' field - real hub echoes client's src as dst"
        assert response["transactionId"] == "test-power-on-001", \
            f"Expected transactionId match"
        assert response["status"] == "ok", \
            f"Expected status 'ok' for successful control but got '{response['status']}'"

        # Wait for state update to complete
        await asyncio.sleep(0.2)

        # Query device state to verify update
        poll_request = {
            "name": "DEVICE_POLL",
            "transactionId": "test-poll-001",
            "target": "11111111-1111-4111-8111-111111111111"
        }
        await send_message(writer, poll_request)

        poll_response = await asyncio.wait_for(read_message(reader), timeout=1.0)

        # Validate state updated
        assert poll_response["data"]["state"]["power"] is True, \
            f"Expected power=True after control command but got {poll_response['data']['state']['power']} - state not updated"

    finally:
        writer.close()
        await writer.wait_closed()


@pytest.mark.asyncio
async def test_control_dim_level(simulator_port):
    """
    Test CONTROL command changes dim level.

    User Story 3 Acceptance: Dim level changes work correctly
    FR-018: CONTROL command with data.dim field

    Expected: Dim command updates device brightness level
    Actual: Subsequent DEVICE_POLL should show new dim value
    Impact: Integration needs accurate dim control for user brightness adjustments
    """
    port, simulator = simulator_port

    # Connect to simulator
    reader, writer = await asyncio.open_connection('127.0.0.1', port)

    try:
        # Send CONTROL command to set dim level to 50
        control_request = {
            "name": "CONTROL",
            "transactionId": "test-dim-001",
            "data": {
                "uuid": "22222222-2222-4222-8222-222222222222",
                "dim": 50
            }
        }
        await send_message(writer, control_request)

        # Read acknowledgment
        response = await asyncio.wait_for(read_message(reader), timeout=1.0)

        assert response["status"] == "ok", \
            f"Expected status 'ok' for successful dim control"

        # Wait for state update
        await asyncio.sleep(0.2)

        # Query device state
        poll_request = {
            "name": "DEVICE_POLL",
            "transactionId": "test-poll-002",
            "target": "22222222-2222-4222-8222-222222222222"
        }
        await send_message(writer, poll_request)

        poll_response = await asyncio.wait_for(read_message(reader), timeout=1.0)

        # Validate dim level updated
        assert poll_response["data"]["state"]["dim"] == 50, \
            f"Expected dim=50 after control command but got {poll_response['data']['state']['dim']} - brightness not updated"

    finally:
        writer.close()
        await writer.wait_closed()


@pytest.mark.asyncio
async def test_event_broadcast_on_state_change(simulator_port):
    """
    Test EVENT broadcast when device state changes.

    User Story 3 Acceptance: State changes trigger EVENT broadcasts
    FR-075: EVENT includes full state (power + dim), not just changed fields

    Expected: CONTROL command triggers EVENT with full device state
    Actual: EVENT message should include power AND dim, not just changed field
    Impact: Integration must receive complete state updates to stay in sync
    
    Research: research/physical-button-behavior-test-2025-10-18.md
    """
    port, simulator = simulator_port

    # Connect to simulator
    reader, writer = await asyncio.open_connection('127.0.0.1', port)

    try:
        # Send CONTROL command
        control_request = {
            "name": "CONTROL",
            "transactionId": "test-event-001",
            "data": {
                "uuid": "11111111-1111-4111-8111-111111111111",
                "power": True
            }
        }
        await send_message(writer, control_request)

        # Read acknowledgment
        ack = await asyncio.wait_for(read_message(reader), timeout=1.0)
        assert ack["type"] == "CONTROL"

        # Read EVENT broadcast (should arrive after ~2s delay per research)
        # Allow up to 3s for EVENT to arrive
        event = await asyncio.wait_for(read_message(reader), timeout=3.0)

        # Validate EVENT structure
        assert event["type"] == "EVENT", \
            f"Expected EVENT message but got '{event['type']}' - real hub uses 'type' field"
        
        assert "data" in event, \
            "Missing 'data' field in EVENT"
        
        data = event["data"]
        
        # Validate EVENT structure per real hub format
        assert "eventType" in data, \
            "Missing 'eventType' in EVENT data - real hub includes this field"
        assert data["eventType"] == "DEVICE_STATE_CHANGE", \
            f"Expected eventType 'DEVICE_STATE_CHANGE' but got '{data['eventType']}'"
        assert "target" in data, \
            "Missing 'target' field in EVENT data - real hub uses 'target' for device UUID"
        assert "state" in data, \
            "Missing 'state' field in EVENT data - real hub nests state info"
        
        # FR-075: EVENT must include FULL state (power + dim), not just changed field
        state = data["state"]
        assert "power" in state, \
            "Missing 'power' in EVENT state - integration needs full state"
        assert "dim" in state, \
            "Missing 'dim' in EVENT state - integration needs full state (FR-075)"
        
        assert data["target"] == "11111111-1111-4111-8111-111111111111", \
            f"EVENT should be for controlled device"
        assert state["power"] is True, \
            f"EVENT should show updated power state"

    finally:
        writer.close()
        await writer.wait_closed()


@pytest.mark.asyncio
async def test_rate_limiting_silent_drop(simulator_port):
    """
    Test rapid CONTROL commands are rate-limited (100ms minimum spacing).

    User Story 3 Acceptance: Rapid commands handled correctly
    FR-023: 100ms minimum spacing between commands, second command silently dropped

    Expected: Second command within 100ms is silently dropped (no acknowledgment, no state change)
    Actual: Only first command should be acknowledged and processed
    Impact: Integration must handle rate limiting gracefully (first-in-wins)
    
    Research: research/rate-limiting-systematic-test-2025-10-18.md
    """
    port, simulator = simulator_port

    # Connect to simulator
    reader, writer = await asyncio.open_connection('127.0.0.1', port)

    try:
        # Send first CONTROL command
        control_1 = {
            "name": "CONTROL",
            "transactionId": "test-rate-001",
            "data": {
                "uuid": "11111111-1111-4111-8111-111111111111",
                "power": True,
                "dim": 75
            }
        }
        await send_message(writer, control_1)

        # Send second CONTROL command immediately (within 100ms)
        await asyncio.sleep(0.01)  # 10ms gap - well within rate limit
        control_2 = {
            "name": "CONTROL",
            "transactionId": "test-rate-002",
            "data": {
                "uuid": "11111111-1111-4111-8111-111111111111",
                "power": False,
                "dim": 25
            }
        }
        await send_message(writer, control_2)

        # Read first acknowledgment
        ack1 = await asyncio.wait_for(read_message(reader), timeout=1.0)
        assert ack1["transactionId"] == "test-rate-001", \
            "First command should be acknowledged"

        # Second command should be silently dropped - no acknowledgment
        # Try to read with short timeout - should timeout because no response
        try:
            ack2 = await asyncio.wait_for(read_message(reader), timeout=0.5)
            # If we get here, there was a message - it should be EVENT, not second ack
            assert ack2["type"] == "EVENT", \
                f"Second command was not silently dropped - got response: {ack2}"
        except asyncio.TimeoutError:
            # This is expected - second command silently dropped
            pass

        # Wait for state update and EVENT
        await asyncio.sleep(2.5)
        
        # Consume any pending EVENT messages from the CONTROL command
        # (EVENT may arrive between the ack and our DEVICE_POLL request)
        pending_messages = []
        while True:
            try:
                msg = await asyncio.wait_for(read_message(reader), timeout=0.1)
                pending_messages.append(msg)
            except asyncio.TimeoutError:
                break

        # Verify state shows FIRST command (power=True, dim=75), not second
        poll_request = {
            "name": "DEVICE_POLL",
            "transactionId": "test-poll-rate",
            "target": "11111111-1111-4111-8111-111111111111"
        }
        await send_message(writer, poll_request)

        poll_response = await asyncio.wait_for(read_message(reader), timeout=1.0)
        
        # Validate we got DEVICE_POLL response, not EVENT
        assert poll_response["type"] == "DEVICE_POLL", \
            f"Expected DEVICE_POLL response but got {poll_response['type']}"
        
        assert poll_response["data"]["state"]["power"] is True, \
            f"Power should be True (first command) not False (second command was dropped) - first-in-wins behavior"
        assert poll_response["data"]["state"]["dim"] == 75, \
            f"Dim should be 75 (first command) not 25 (second command was dropped)"

    finally:
        writer.close()
        await writer.wait_closed()


@pytest.mark.asyncio
async def test_acknowledgment_timing(simulator_port):
    """
    Test CONTROL acknowledgment arrives within 500ms.

    User Story 3 Acceptance: Commands acknowledged quickly
    SC-003: Acknowledgment within 500ms

    Expected: Acknowledgment arrives in < 500ms after command sent
    Actual: Response time should be measured and verified
    Impact: Integration relies on timely acknowledgments for user feedback
    """
    port, simulator = simulator_port

    # Connect to simulator
    reader, writer = await asyncio.open_connection('127.0.0.1', port)

    try:
        # Send CONTROL command and measure response time
        control_request = {
            "name": "CONTROL",
            "transactionId": "test-timing-001",
            "data": {
                "uuid": "22222222-2222-4222-8222-222222222222",
                "power": False
            }
        }
        
        start_time = time.time()
        await send_message(writer, control_request)

        # Read acknowledgment
        response = await asyncio.wait_for(read_message(reader), timeout=1.0)
        end_time = time.time()

        response_time_ms = (end_time - start_time) * 1000

        # Validate acknowledgment timing (SC-003: <500ms)
        assert response_time_ms < 500, \
            f"Acknowledgment took {response_time_ms:.1f}ms but must be < 500ms (SC-003) - user experience degraded"
        
        assert response["status"] == "ok", \
            "Acknowledgment should indicate success"

    finally:
        writer.close()
        await writer.wait_closed()


@pytest.mark.asyncio
async def test_control_nonexistent_device(simulator_port):
    """
    Test CONTROL for non-existent device returns error.

    User Story 3 Acceptance: Invalid device UUIDs handled gracefully
    FR-066: CONTROL with invalid UUID returns REQUEST_INVALID error

    Expected: Error response with code "REQUEST_INVALID"
    Actual: Error message should indicate device not found
    Impact: Integration needs clear error when controlling non-existent devices
    """
    port, simulator = simulator_port

    # Connect to simulator
    reader, writer = await asyncio.open_connection('127.0.0.1', port)

    try:
        # Send CONTROL for non-existent device
        control_request = {
            "name": "CONTROL",
            "transactionId": "test-invalid-001",
            "data": {
                "uuid": "99999999-9999-4999-8999-999999999999",
                "power": True
            }
        }
        await send_message(writer, control_request)

        # Read error response
        response = await asyncio.wait_for(read_message(reader), timeout=1.0)

        # Validate error response
        assert response["type"] == "CONTROL", \
            f"Expected response type 'CONTROL' for errors - real hub uses 'type' field"
        assert response["src"] == "deako", \
            f"Expected src 'deako' - real hub always sets src"
        assert "dst" in response, \
            "Missing 'dst' field - real hub echoes client's src as dst"
        assert response["status"] == "error", \
            f"Expected status 'error' for non-existent device"
        assert response["data"]["code"] == "REQUEST_INVALID", \
            f"Expected error code 'REQUEST_INVALID'"

    finally:
        writer.close()
        await writer.wait_closed()
