"""
Unit tests for state management module.

Tests cover:
- Device lookup and storage
- State updates with null handling (FR-082)
- Device addition/removal
- Rate limiting logic (FR-023)
- Connection management (passive rejection per FR-072)
- EVENT broadcasting
"""

import asyncio
import pytest
import time
from unittest.mock import AsyncMock, Mock, patch

from deako_simulator.models import Device, DeviceState
from deako_simulator.state import SimulatorState


@pytest.fixture
def sample_devices():
    """Create sample devices for testing."""
    return [
        Device(
            uuid="11111111-1111-4111-8111-111111111111",
            name="Test Light 1",
            capabilities=["power", "dim"],
            state=DeviceState(power=False, dim=0)
        ),
        Device(
            uuid="22222222-2222-4222-8222-222222222222",
            name="Test Light 2",
            capabilities=["power"],
            state=DeviceState(power=False, dim=None)
        ),
    ]


@pytest.fixture
def state(sample_devices):
    """Create SimulatorState with sample devices."""
    return SimulatorState(sample_devices)


class TestSimulatorStateInitialization:
    """Test SimulatorState initialization."""
    
    def test_initialization_with_devices(self, sample_devices):
        """Test state initializes with correct device mapping."""
        state = SimulatorState(sample_devices)
        
        assert len(state.devices) == 2
        assert "11111111-1111-4111-8111-111111111111" in state.devices
        assert "22222222-2222-4222-8222-222222222222" in state.devices
        assert len(state.connections) == 0
        assert state.active_connection is None
        assert len(state.command_queues) == 2
    
    def test_initialization_creates_command_queues(self, sample_devices):
        """Test command queues created for each device."""
        state = SimulatorState(sample_devices)
        
        for device in sample_devices:
            assert device.uuid in state.command_queues
            assert isinstance(state.command_queues[device.uuid], asyncio.Queue)


class TestDeviceLookup:
    """Test device retrieval methods."""
    
    def test_get_device_found(self, state):
        """Test get_device returns device when UUID exists."""
        device = state.get_device("11111111-1111-4111-8111-111111111111")
        
        assert device is not None
        assert device.name == "Test Light 1"
    
    def test_get_device_not_found(self, state):
        """Test get_device returns None when UUID doesn't exist."""
        device = state.get_device("99999999-9999-9999-9999-999999999999")
        
        assert device is None
    
    def test_get_all_devices(self, state):
        """Test get_all_devices returns all devices."""
        devices = state.get_all_devices()
        
        assert len(devices) == 2
        assert all(isinstance(d, Device) for d in devices)


class TestDeviceStateUpdates:
    """Test device state update logic."""
    
    def test_update_power_only(self, state):
        """Test updating only power state."""
        uuid = "11111111-1111-4111-8111-111111111111"
        
        device = state.update_device_state(uuid, power=True)
        
        assert device.state.power is True
        assert device.state.dim == 0  # Unchanged
    
    def test_update_dim_only(self, state):
        """Test updating only dim state."""
        uuid = "11111111-1111-4111-8111-111111111111"
        
        device = state.update_device_state(uuid, dim=75)
        
        assert device.state.power is False  # Unchanged
        assert device.state.dim == 75
    
    def test_update_both_power_and_dim(self, state):
        """Test updating both power and dim."""
        uuid = "11111111-1111-4111-8111-111111111111"
        
        device = state.update_device_state(uuid, power=True, dim=50)
        
        assert device.state.power is True
        assert device.state.dim == 50
    
    def test_update_null_power_no_change(self, state):
        """Test null power value means no change (FR-082)."""
        uuid = "11111111-1111-4111-8111-111111111111"
        
        # Set initial state
        state.update_device_state(uuid, power=True, dim=50)
        
        # Update with null power
        device = state.update_device_state(uuid, power=None, dim=75)
        
        assert device.state.power is True  # Unchanged
        assert device.state.dim == 75  # Changed
    
    def test_update_null_dim_no_change(self, state):
        """Test null dim value means no change (FR-082)."""
        uuid = "11111111-1111-4111-8111-111111111111"
        
        # Set initial state
        state.update_device_state(uuid, power=True, dim=50)
        
        # Update with null dim
        device = state.update_device_state(uuid, power=False, dim=None)
        
        assert device.state.power is False  # Changed
        assert device.state.dim == 50  # Unchanged
    
    def test_update_nonexistent_device_raises_error(self, state):
        """Test updating nonexistent device raises KeyError."""
        with pytest.raises(KeyError):
            state.update_device_state("99999999-9999-9999-9999-999999999999", power=True)
    
    def test_dim_value_clamped_to_zero(self, state):
        """Test dim values below 0 are clamped to 0 (FR-071)."""
        uuid = "11111111-1111-4111-8111-111111111111"
        
        device = state.update_device_state(uuid, dim=-10)
        
        assert device.state.dim == 0
    
    def test_dim_value_clamped_to_100(self, state):
        """Test dim values above 100 are clamped to 100 (FR-071)."""
        uuid = "11111111-1111-4111-8111-111111111111"
        
        device = state.update_device_state(uuid, dim=150)
        
        assert device.state.dim == 100
    
    def test_dim_value_truncated_to_int(self, state):
        """Test dim decimal values are truncated to int (FR-071)."""
        uuid = "11111111-1111-4111-8111-111111111111"
        
        device = state.update_device_state(uuid, dim=50.7)
        
        assert device.state.dim == 50
        assert isinstance(device.state.dim, int)


class TestDeviceAddRemove:
    """Test device addition and removal."""
    
    def test_add_device(self, state):
        """Test adding a new device."""
        new_device = Device(
            uuid="33333333-3333-4333-8333-333333333333",
            name="New Light",
            capabilities=["power"],
            state=DeviceState(power=False, dim=None)
        )
        
        state.add_device(new_device)
        
        assert new_device.uuid in state.devices
        assert new_device.uuid in state.command_queues
        assert len(state.devices) == 3
    
    def test_remove_device(self, state):
        """Test removing a device."""
        uuid = "11111111-1111-4111-8111-111111111111"
        
        state.remove_device(uuid)
        
        assert uuid not in state.devices
        assert uuid not in state.command_queues
        assert len(state.devices) == 1
    
    def test_remove_nonexistent_device_raises_error(self, state):
        """Test removing nonexistent device raises KeyError."""
        with pytest.raises(KeyError):
            state.remove_device("99999999-9999-9999-9999-999999999999")


class TestRateLimiting:
    """Test rate limiting logic (FR-023)."""
    
    def test_not_rate_limited_initially(self, state):
        """Test device not rate-limited on first command."""
        uuid = "11111111-1111-4111-8111-111111111111"
        
        assert not state.is_rate_limited(uuid)
    
    def test_not_rate_limited_after_update(self, state):
        """Test device not rate-limited after updating timestamp."""
        uuid = "11111111-1111-4111-8111-111111111111"
        
        state.update_command_time(uuid)
        
        # Immediately check - should be rate-limited
        assert state.is_rate_limited(uuid)
    
    def test_rate_limited_within_100ms(self, state):
        """Test device rate-limited within 100ms (FR-023)."""
        uuid = "11111111-1111-4111-8111-111111111111"
        
        # First command
        state.update_command_time(uuid)
        
        # Second command immediately after (<100ms)
        assert state.is_rate_limited(uuid)
    
    def test_not_rate_limited_after_100ms(self, state):
        """Test device not rate-limited after 100ms."""
        uuid = "11111111-1111-4111-8111-111111111111"
        
        # First command
        state.update_command_time(uuid)
        
        # Wait 100ms
        time.sleep(0.11)
        
        # Should not be rate-limited now
        assert not state.is_rate_limited(uuid)
    
    def test_rate_limiting_per_device(self, state):
        """Test rate limiting is per-device (commands to different devices don't interfere)."""
        uuid1 = "11111111-1111-4111-8111-111111111111"
        uuid2 = "22222222-2222-4222-8222-222222222222"
        
        # Update device 1
        state.update_command_time(uuid1)
        
        # Device 1 should be rate-limited
        assert state.is_rate_limited(uuid1)
        
        # Device 2 should NOT be rate-limited
        assert not state.is_rate_limited(uuid2)


class TestConnectionManagement:
    """Test connection management (passive rejection per FR-072)."""
    
    def test_add_connection(self, state):
        """Test adding a connection."""
        mock_writer = Mock(spec=asyncio.StreamWriter)
        mock_writer.get_extra_info.return_value = ('127.0.0.1', 12345)
        
        state.add_connection(mock_writer)
        
        assert mock_writer in state.connections
        assert len(state.connections) == 1
    
    def test_remove_connection(self, state):
        """Test removing a connection."""
        mock_writer = Mock(spec=asyncio.StreamWriter)
        mock_writer.get_extra_info.return_value = ('127.0.0.1', 12345)
        
        state.add_connection(mock_writer)
        state.remove_connection(mock_writer)
        
        assert mock_writer not in state.connections
        assert len(state.connections) == 0
    
    def test_set_active_connection_first(self, state):
        """Test first connection becomes active."""
        mock_writer = Mock(spec=asyncio.StreamWriter)
        mock_writer.get_extra_info.return_value = ('127.0.0.1', 12345)
        
        state.set_active_connection(mock_writer)
        
        assert state.active_connection is mock_writer
        assert state.is_active_connection(mock_writer)
    
    def test_set_active_connection_second_ignored(self, state):
        """Test second connection doesn't become active (passive rejection)."""
        mock_writer1 = Mock(spec=asyncio.StreamWriter)
        mock_writer1.get_extra_info.return_value = ('127.0.0.1', 12345)
        mock_writer2 = Mock(spec=asyncio.StreamWriter)
        mock_writer2.get_extra_info.return_value = ('127.0.0.1', 12346)
        
        state.set_active_connection(mock_writer1)
        state.set_active_connection(mock_writer2)
        
        # First connection remains active
        assert state.active_connection is mock_writer1
        assert state.is_active_connection(mock_writer1)
        assert not state.is_active_connection(mock_writer2)
    
    def test_clear_active_connection(self, state):
        """Test clearing active connection."""
        mock_writer = Mock(spec=asyncio.StreamWriter)
        mock_writer.get_extra_info.return_value = ('127.0.0.1', 12345)
        
        state.set_active_connection(mock_writer)
        state.clear_active_connection(mock_writer)
        
        assert state.active_connection is None
    
    def test_clear_inactive_connection_no_effect(self, state):
        """Test clearing non-active connection has no effect."""
        mock_writer1 = Mock(spec=asyncio.StreamWriter)
        mock_writer1.get_extra_info.return_value = ('127.0.0.1', 12345)
        mock_writer2 = Mock(spec=asyncio.StreamWriter)
        mock_writer2.get_extra_info.return_value = ('127.0.0.1', 12346)
        
        state.set_active_connection(mock_writer1)
        state.clear_active_connection(mock_writer2)
        
        # First connection still active
        assert state.active_connection is mock_writer1


class TestEventBroadcasting:
    """Test EVENT broadcasting to connections."""
    
    @pytest.mark.asyncio
    async def test_broadcast_event_no_active_connection(self, state):
        """Test broadcast when no active connection (no error, just logs)."""
        event = {"name": "EVENT", "data": {"test": "data"}}
        
        # Should not raise error
        await state.broadcast_event(event)
    
    @pytest.mark.asyncio
    async def test_broadcast_event_to_active_connection(self, state):
        """Test EVENT sent to active connection only."""
        mock_writer = AsyncMock(spec=asyncio.StreamWriter)
        mock_writer.get_extra_info.return_value = ('127.0.0.1', 12345)
        
        state.set_active_connection(mock_writer)
        state.add_connection(mock_writer)
        
        event = {"name": "EVENT", "data": {"test": "data"}}
        await state.broadcast_event(event)
        
        # Give async task time to complete
        await asyncio.sleep(0.01)
        
        # Verify write called
        mock_writer.write.assert_called()
    
    @pytest.mark.asyncio
    async def test_broadcast_removes_dead_connection(self, state):
        """Test broadcast removes connection on write failure."""
        mock_writer = AsyncMock(spec=asyncio.StreamWriter)
        mock_writer.get_extra_info.return_value = ('127.0.0.1', 12345)
        mock_writer.drain.side_effect = ConnectionResetError("Connection lost")
        
        state.set_active_connection(mock_writer)
        state.add_connection(mock_writer)
        
        event = {"name": "EVENT", "data": {"test": "data"}}
        await state.broadcast_event(event)
        
        # Give async task time to complete
        await asyncio.sleep(0.01)
        
        # Connection should be removed
        assert mock_writer not in state.connections
        assert state.active_connection is None
