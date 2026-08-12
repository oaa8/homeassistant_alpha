"""
Integration tests for scenario management (User Story 5).

Tests scenario functionality:
- Scenario loading from config file
- Scenario activation atomically replaces devices per FR-042
- Clients must re-query DEVICE_LIST after scenario activation
- Telnet connections remain active during scenario changes

Author: GitHub Copilot
Created: 2025-10-28
Purpose: Validate scenario management for dynamic test configuration

Research References:
- FR-042: Scenario activation atomically replaces devices
- spec.md clarifications session 2025-10-25: replace all devices, keep connections active
"""

import asyncio
import json
from typing import AsyncGenerator

import pytest

from deako_simulator.config import Config, NetworkConfig, Scenario
from deako_simulator.models import Device, DeviceState
from deako_simulator.server import DeakoSimulator
from deako_simulator.state import SimulatorState


@pytest.fixture
def scenario_devices() -> list[Device]:
    """Devices for scenario testing."""
    return [
        Device(
            uuid="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            name="Scenario Light 1",
            capabilities=["power", "dim"],
            state=DeviceState(power=False, dim=0)
        ),
        Device(
            uuid="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            name="Scenario Light 2",
            capabilities=["power"],
            state=DeviceState(power=False, dim=None)
        ),
    ]


@pytest.fixture
def test_scenarios() -> list[Scenario]:
    """Test scenarios with different device configurations."""
    return [
        Scenario(
            name="evening_mode",
            description="Evening lighting: dim lights to 30%",
            device_states={
                "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa": DeviceState(power=True, dim=30),
                "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb": DeviceState(power=True, dim=None),
            }
        ),
        Scenario(
            name="movie_mode",
            description="Movie watching: very dim lights",
            device_states={
                "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa": DeviceState(power=True, dim=10),
                "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb": DeviceState(power=False, dim=None),
            }
        ),
        Scenario(
            name="party_mode",
            description="Party: all lights at 100%",
            device_states={
                "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa": DeviceState(power=True, dim=100),
                "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb": DeviceState(power=True, dim=None),
            }
        ),
    ]


@pytest.fixture
async def simulator_with_scenarios(
    scenario_devices,
    test_scenarios
) -> AsyncGenerator[tuple[int, int, DeakoSimulator, SimulatorState], None]:
    """
    Start simulator with scenarios configured.
    
    TDD NOTE: This fixture will fail until T055-T060 are implemented.
    Tests using this fixture are marked with @pytest.mark.skip.

    Yields:
        tuple: (telnet_port, http_port, simulator, state) for tests to use

    Cleanup:
        Stops simulator after test completes
        
    Blocks: T055-T060 (HTTP API + scenario activation)
    """
    # Create simulator state with test devices
    state = SimulatorState(devices=scenario_devices)

    # Create simulator with scenarios
    config = Config(
        devices=scenario_devices,
        network=NetworkConfig(
            host="127.0.0.1",
            port=0,  # Dynamic port
            http_port=0,  # Dynamic HTTP port
            mdns_name="test-scenarios"
        ),
        log_level="DEBUG",
        scenarios=test_scenarios
    )

    simulator = DeakoSimulator(state=state, config=config)

    # Start simulator
    server_task = asyncio.create_task(simulator.start())

    # Wait for startup
    await asyncio.sleep(0.2)

    # Get ports
    telnet_port = simulator.server.sockets[0].getsockname()[1]
    http_port = simulator.http_runner.addresses[0][1] if simulator.http_runner else 0

    yield (telnet_port, http_port, simulator, state)

    # Cleanup
    await simulator.shutdown()
    server_task.cancel()
    try:
        await server_task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
@pytest.mark.skip(reason="TDD: Waiting for T060 scenario activation implementation")
async def test_scenario_activation_replaces_all_devices(simulator_with_scenarios):
    """
    Test scenario activation atomically replaces all device states per FR-042.
    
    Validates per spec.md clarifications 2025-10-25:
    - All device states updated atomically
    - No partial state updates
    - Changes take effect immediately
    - Returns count of devices updated
    
    Blocks: T060 (scenario activation implementation)
    """
    telnet_port, http_port, simulator, state = await simulator_with_scenarios
    
    # Initial state: all devices off
    for device in state.get_all_devices():
        assert device.state.power is False
    
    # Activate "evening_mode" scenario via HTTP
    import aiohttp
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"http://127.0.0.1:{http_port}/api/scenarios/evening_mode/activate"
        ) as resp:
            assert resp.status == 200
            result = await resp.json()
            assert result["devices_updated"] == 2
    
    # Verify all devices updated atomically
    devices = state.get_all_devices()
    device1 = next(d for d in devices if d.uuid == "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    device2 = next(d for d in devices if d.uuid == "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
    
    assert device1.state.power is True
    assert device1.state.dim == 30
    assert device2.state.power is True


@pytest.mark.asyncio
@pytest.mark.skip(reason="TDD: Waiting for T060 scenario activation implementation")
async def test_scenario_activation_keeps_connections_active(simulator_with_scenarios):
    """
    Test telnet connections remain active during scenario activation per FR-042.
    
    Validates per spec.md clarifications 2025-10-25:
    - Telnet connections NOT disconnected
    - Connection remains functional after scenario change
    - Clients can query new state via existing connection
    
    Blocks: T060 (scenario activation implementation)
    """
    telnet_port, http_port, simulator, state = await simulator_with_scenarios
    
    # Establish telnet connection
    reader, writer = await asyncio.open_connection("127.0.0.1", telnet_port)
    
    try:
        # Send PING to verify connection works
        ping_msg = {
            "transactionId": "test-ping-1",
            "type": "PING",
            "dst": "deako",
            "src": "test"
        }
        writer.write((json.dumps(ping_msg) + "\r\n").encode())
        await writer.drain()
        
        response_line = await asyncio.wait_for(reader.readline(), timeout=2.0)
        response = json.loads(response_line.decode().strip())
        assert response["status"] == "ok"
        
        # Activate scenario via HTTP while telnet connection active
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"http://127.0.0.1:{http_port}/api/scenarios/movie_mode/activate"
            ) as resp:
                assert resp.status == 200
        
        # Verify connection still works after scenario activation
        ping_msg2 = {
            "transactionId": "test-ping-2",
            "type": "PING",
            "dst": "deako",
            "src": "test"
        }
        writer.write((json.dumps(ping_msg2) + "\r\n").encode())
        await writer.drain()
        
        response_line2 = await asyncio.wait_for(reader.readline(), timeout=2.0)
        response2 = json.loads(response_line2.decode().strip())
        assert response2["status"] == "ok"
        
        # Query device state via telnet to verify scenario applied
        poll_msg = {
            "transactionId": "test-poll",
            "type": "DEVICE_POLL",
            "dst": "deako",
            "src": "test",
            "data": {"target": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"}
        }
        writer.write((json.dumps(poll_msg) + "\r\n").encode())
        await writer.drain()
        
        poll_response_line = await asyncio.wait_for(reader.readline(), timeout=2.0)
        poll_response = json.loads(poll_response_line.decode().strip())
        
        # Verify movie_mode scenario applied (power=True, dim=10)
        assert poll_response["data"]["state"]["power"] is True
        assert poll_response["data"]["state"]["dim"] == 10
        
    finally:
        writer.close()
        await writer.wait_closed()


@pytest.mark.asyncio
@pytest.mark.skip(reason="TDD: Waiting for T060 scenario activation implementation")
async def test_clients_must_requery_device_list_after_scenario(simulator_with_scenarios):
    """
    Test clients must re-query DEVICE_LIST after scenario activation.
    
    Validates per spec.md clarifications 2025-10-25:
    - Scenario changes device topology
    - Clients not automatically notified of topology changes
    - Clients must explicitly request DEVICE_LIST to discover new devices
    - Device states can be queried via DEVICE_POLL after scenario activation
    
    Note: This tests the "clients must re-query" requirement by demonstrating
    that device list doesn't automatically update - client must request it.
    
    Blocks: T060 (scenario activation implementation)
    """
    telnet_port, http_port, simulator, state = await simulator_with_scenarios
    
    # Connect via telnet and get initial device list
    reader, writer = await asyncio.open_connection("127.0.0.1", telnet_port)
    
    try:
        # Request initial DEVICE_LIST
        device_list_msg = {
            "transactionId": "test-list-1",
            "type": "DEVICE_LIST",
            "dst": "deako",
            "src": "test"
        }
        writer.write((json.dumps(device_list_msg) + "\r\n").encode())
        await writer.drain()
        
        # Read DEVICE_LIST response
        list_response_line = await asyncio.wait_for(reader.readline(), timeout=2.0)
        list_response = json.loads(list_response_line.decode().strip())
        initial_count = list_response["data"]["number_of_devices"]
        assert initial_count == 2
        
        # Read DEVICE_FOUND messages
        for _ in range(initial_count):
            await asyncio.wait_for(reader.readline(), timeout=2.0)
        
        # Activate scenario via HTTP
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"http://127.0.0.1:{http_port}/api/scenarios/party_mode/activate"
            ) as resp:
                assert resp.status == 200
        
        # Client must explicitly re-query DEVICE_LIST to see scenario changes
        # The device list is not automatically pushed to clients
        device_list_msg2 = {
            "transactionId": "test-list-2",
            "type": "DEVICE_LIST",
            "dst": "deako",
            "src": "test"
        }
        writer.write((json.dumps(device_list_msg2) + "\r\n").encode())
        await writer.drain()
        
        # Read new DEVICE_LIST response
        list_response_line2 = await asyncio.wait_for(reader.readline(), timeout=2.0)
        list_response2 = json.loads(list_response_line2.decode().strip())
        new_count = list_response2["data"]["number_of_devices"]
        assert new_count == 2  # Same devices, different states
        
        # Read DEVICE_FOUND messages and verify new states from party_mode
        found_devices = []
        for _ in range(new_count):
            found_line = await asyncio.wait_for(reader.readline(), timeout=2.0)
            found_msg = json.loads(found_line.decode().strip())
            found_devices.append(found_msg["data"])
        
        # Verify party_mode scenario applied (all power=True, dim=100 where applicable)
        for device_data in found_devices:
            assert device_data["state"]["power"] is True
            if "dim" in device_data["capabilities"]:
                assert device_data["state"]["dim"] == 100
                
    finally:
        writer.close()
        await writer.wait_closed()


@pytest.mark.asyncio
@pytest.mark.skip(reason="TDD: Waiting for T060 scenario activation implementation")
async def test_scenario_activation_multiple_times(simulator_with_scenarios):
    """
    Test activating multiple scenarios in sequence.
    
    Validates:
    - Can activate different scenarios sequentially
    - Each activation replaces previous scenario state
    - State changes are atomic and consistent
    - No residual state from previous scenarios
    
    Blocks: T060 (scenario activation implementation)
    """
    telnet_port, http_port, simulator, state = await simulator_with_scenarios
    
    import aiohttp
    async with aiohttp.ClientSession() as session:
        # Activate evening_mode
        async with session.post(
            f"http://127.0.0.1:{http_port}/api/scenarios/evening_mode/activate"
        ) as resp:
            assert resp.status == 200
        
        # Verify evening_mode state
        devices = state.get_all_devices()
        device1 = next(d for d in devices if d.uuid == "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
        assert device1.state.power is True
        assert device1.state.dim == 30
        
        # Activate movie_mode
        async with session.post(
            f"http://127.0.0.1:{http_port}/api/scenarios/movie_mode/activate"
        ) as resp:
            assert resp.status == 200
        
        # Verify movie_mode state replaced evening_mode
        devices = state.get_all_devices()
        device1 = next(d for d in devices if d.uuid == "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
        device2 = next(d for d in devices if d.uuid == "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
        assert device1.state.power is True
        assert device1.state.dim == 10  # Changed from 30
        assert device2.state.power is False  # Changed from True
        
        # Activate party_mode
        async with session.post(
            f"http://127.0.0.1:{http_port}/api/scenarios/party_mode/activate"
        ) as resp:
            assert resp.status == 200
        
        # Verify party_mode state replaced movie_mode
        devices = state.get_all_devices()
        device1 = next(d for d in devices if d.uuid == "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
        device2 = next(d for d in devices if d.uuid == "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
        assert device1.state.power is True
        assert device1.state.dim == 100  # Changed from 10
        assert device2.state.power is True  # Changed from False


@pytest.mark.asyncio
@pytest.mark.skip(reason="TDD: Waiting for T060 scenario activation implementation")
async def test_scenario_activation_broadcasts_events(simulator_with_scenarios):
    """
    Test scenario activation broadcasts EVENTs for state changes.
    
    Validates per FR-042:
    - DEVICE_STATE_CHANGE EVENTs broadcast for all changed devices
    - EVENTs contain full device state (power + dim)
    - Active telnet connection receives EVENTs
    - EVENTs sent after scenario activation completes
    
    Blocks: T060 (scenario activation implementation)
    """
    telnet_port, http_port, simulator, state = await simulator_with_scenarios
    
    # Connect via telnet
    reader, writer = await asyncio.open_connection("127.0.0.1", telnet_port)
    
    try:
        # Activate scenario via HTTP
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"http://127.0.0.1:{http_port}/api/scenarios/evening_mode/activate"
            ) as resp:
                assert resp.status == 200
        
        # Wait for EVENTs to arrive
        await asyncio.sleep(0.5)
        
        # Read EVENTs (should receive one per device that changed)
        events_received = []
        try:
            while True:
                event_line = await asyncio.wait_for(reader.readline(), timeout=1.0)
                if event_line:
                    event = json.loads(event_line.decode().strip())
                    if event.get("type") == "EVENT":
                        events_received.append(event)
                else:
                    break
        except asyncio.TimeoutError:
            pass  # No more events
        
        # Verify EVENTs received for device state changes
        assert len(events_received) >= 2, "Should receive EVENTs for both devices"
        
        # Verify EVENT structure
        for event in events_received:
            assert event["type"] == "EVENT"
            assert "data" in event
            assert event["data"]["eventType"] == "DEVICE_STATE_CHANGE"
            assert "target" in event["data"]
            assert "state" in event["data"]
            # Verify full state included (not just deltas)
            assert "power" in event["data"]["state"]
            
    finally:
        writer.close()
        await writer.wait_closed()
