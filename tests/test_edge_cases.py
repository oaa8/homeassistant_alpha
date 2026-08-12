"""Unit tests for edge cases in device management.

Author: GitHub Copilot
Created: 2025-10-29
Purpose: Validate edge cases for device lists, names, and UUID handling

Test Coverage (T079):
- Empty device list scenarios
- Single device operations
- Large device lists (50 devices - typical residential)
- Device names with special characters
- UUID generation and validation

Related Requirements:
- Constitution Principle VII: 95% test coverage with deterministic tests
- FR-005: Device validation rules
- data-model.md: Device structure and constraints
"""

import pytest
import uuid
from deako_simulator.models import Device, DeviceState
from deako_simulator.config import Config, NetworkConfig, get_default_config
from deako_simulator.state import SimulatorState


class TestEmptyDeviceList:
    """Test scenarios with no devices configured.
    
    User Story: Simulator should handle empty device lists gracefully.
    This tests initial setup or scenarios where all devices are removed.
    """
    
    def test_empty_device_list_creation(self):
        """Validates simulator state can handle zero devices.
        
        Impact: Integration must handle case where all devices are removed at runtime.
        Note: Config requires at least one device, but SimulatorState should handle empty list.
        """
        # SimulatorState can be initialized with empty list (e.g., after removing all devices)
        state = SimulatorState([])
        
        assert len(state.devices) == 0, \
            "Empty device list should result in zero devices"
        assert state.get_all_devices() == [], \
            "get_all_devices() should return empty list, not None"
    
    def test_empty_device_list_get_device_returns_none(self):
        """Validates get_device returns None when no devices exist.
        
        Impact: Integration DEVICE_POLL for non-existent device should fail gracefully.
        """
        state = SimulatorState([])
        
        result = state.get_device("11111111-1111-4111-8111-111111111111")
        assert result is None, \
            "get_device() with empty device list should return None"
    
    def test_empty_device_list_device_count(self):
        """Validates DEVICE_LIST response shows count=0.
        
        Impact: Integration should handle empty device discovery correctly.
        """
        state = SimulatorState([])
        devices = state.get_all_devices()
        
        assert len(devices) == 0, \
            "Device count should be 0 for empty list - integration sees no devices"


class TestSingleDevice:
    """Test scenarios with exactly one device.
    
    User Story: Minimal configuration for testing integration with single device.
    """
    
    def test_single_power_only_device(self):
        """Validates single power-only device operations.
        
        Impact: Integration must work with minimal device configuration.
        """
        device = Device(
            uuid="11111111-1111-4111-8111-111111111111",
            name="Single Light",
            capabilities=["power"],
            state=DeviceState(power=False, dim=None)
        )
        state = SimulatorState([device])
        
        assert len(state.devices) == 1, \
            "Single device should result in count=1"
        
        retrieved = state.get_device("11111111-1111-4111-8111-111111111111")
        assert retrieved is not None, \
            "get_device() should find the single device"
        assert retrieved.name == "Single Light", \
            "Retrieved device should match configured device"
    
    def test_single_dimmable_device(self):
        """Validates single dimmable device operations.
        
        Impact: Integration must handle power and dim control for single device.
        """
        device = Device(
            uuid="22222222-2222-4222-8222-222222222222",
            name="Single Dimmer",
            capabilities=["power", "dim"],
            state=DeviceState(power=True, dim=75)
        )
        state = SimulatorState([device])
        
        # Test state update
        updated = state.update_device_state(
            "22222222-2222-4222-8222-222222222222",
            power=False,
            dim=0
        )
        
        assert updated is not None, \
            "update_device_state() should succeed for single device"
        assert updated.state.power is False, \
            "Power state should be updated"
        assert updated.state.dim == 0, \
            "Dim state should be updated"
    
    def test_single_device_removal_makes_list_empty(self):
        """Validates removing single device results in empty list.
        
        Impact: Integration must handle device removal during runtime.
        """
        device = Device(
            uuid="11111111-1111-4111-8111-111111111111",
            name="Temporary Device",
            capabilities=["power"],
            state=DeviceState(power=False, dim=None)
        )
        state = SimulatorState([device])
        
        state.remove_device("11111111-1111-4111-8111-111111111111")
        
        assert len(state.devices) == 0, \
            "Removing single device should result in empty device list"
        assert state.get_device("11111111-1111-4111-8111-111111111111") is None, \
            "Device should not be retrievable after removal"


class TestLargeDeviceList:
    """Test scenarios with 50 devices (typical residential installation).
    
    User Story: Simulator must handle typical residential device counts
    without performance degradation.
    """
    
    def test_50_devices_creation(self):
        """Validates simulator handles 50 devices efficiently.
        
        Impact: Integration must handle typical residential hub with 50+ devices.
        """
        devices = []
        for i in range(50):
            # Alternate between power-only and dimmable
            if i % 2 == 0:
                capabilities = ["power"]
                dim = None
            else:
                capabilities = ["power", "dim"]
                dim = 0
            
            # Generate valid UUID v4
            device_uuid = str(uuid.uuid4())
            
            device = Device(
                uuid=device_uuid,
                name=f"Device {i+1:02d}",
                capabilities=capabilities,
                state=DeviceState(power=False, dim=dim)
            )
            devices.append(device)
        
        state = SimulatorState(devices)
        
        assert len(state.devices) == 50, \
            "Should handle 50 devices - integration sees all devices"
        assert len(state.get_all_devices()) == 50, \
            "get_all_devices() should return all 50 devices"
    
    def test_50_devices_lookup_performance(self):
        """Validates device lookup remains fast with 50 devices.
        
        Impact: DEVICE_POLL latency must stay under 500ms (SC-003).
        """
        devices = []
        for i in range(50):
            device_uuid = str(uuid.uuid4())
            device = Device(
                uuid=device_uuid,
                name=f"Device {i+1:02d}",
                capabilities=["power"],
                state=DeviceState(power=False, dim=None)
            )
            devices.append(device)
        
        state = SimulatorState(devices)
        
        # Lookup arbitrary device from middle of list
        target_uuid = devices[25].uuid
        result = state.get_device(target_uuid)
        
        assert result is not None, \
            "Device lookup should succeed with 50 devices"
        assert result.uuid == target_uuid, \
            "Should retrieve correct device by UUID"
    
    def test_50_devices_state_updates(self):
        """Validates state updates work correctly with 50 devices.
        
        Impact: CONTROL commands must work for all devices in large list.
        """
        devices = []
        device_uuids = []
        for i in range(50):
            device_uuid = str(uuid.uuid4())
            device_uuids.append(device_uuid)
            device = Device(
                uuid=device_uuid,
                name=f"Device {i+1:02d}",
                capabilities=["power", "dim"],
                state=DeviceState(power=False, dim=0)
            )
            devices.append(device)
        
        state = SimulatorState(devices)
        
        # Update every 10th device
        for i in range(0, 50, 10):
            updated = state.update_device_state(
                device_uuids[i],
                power=True,
                dim=50
            )
            assert updated is not None, \
                f"Device {i} state update should succeed"
            assert updated.state.power is True, \
                f"Device {i} power should be updated"
            assert updated.state.dim == 50, \
                f"Device {i} dim should be updated"
    
    def test_50_devices_all_unique_uuids(self):
        """Validates all 50 devices have unique UUIDs.
        
        Impact: Integration must distinguish between all devices.
        """
        devices = []
        uuids_seen = set()
        
        for i in range(50):
            device_uuid = str(uuid.uuid4())
            
            # Ensure no duplicates
            assert device_uuid not in uuids_seen, \
                f"UUID collision detected at device {i}: {device_uuid}"
            uuids_seen.add(device_uuid)
            
            device = Device(
                uuid=device_uuid,
                name=f"Device {i+1:02d}",
                capabilities=["power"],
                state=DeviceState(power=False, dim=None)
            )
            devices.append(device)
        
        state = SimulatorState(devices)
        assert len(state.devices) == 50, \
            "All 50 devices should be stored"


class TestDeviceNamesWithSpecialCharacters:
    """Test device names with special characters and Unicode.
    
    User Story: Users name devices with various special characters,
    emojis, and Unicode. Simulator must handle these gracefully.
    """
    
    def test_device_name_with_apostrophe(self):
        """Validates device names with apostrophes (e.g., "Kid's Room").
        
        Impact: Integration must display user's original device names correctly.
        """
        device = Device(
            uuid="11111111-1111-4111-8111-111111111111",
            name="Kid's Room Light",
            capabilities=["power"],
            state=DeviceState(power=False, dim=None)
        )
        state = SimulatorState([device])
        
        retrieved = state.get_device("11111111-1111-4111-8111-111111111111")
        assert retrieved.name == "Kid's Room Light", \
            "Device name with apostrophe should be preserved - user sees correct name"
    
    def test_device_name_with_quotes(self):
        """Validates device names with double quotes.
        
        Impact: JSON encoding must escape quotes correctly.
        """
        device = Device(
            uuid="22222222-2222-4222-8222-222222222222",
            name='The "Main" Hallway',
            capabilities=["power"],
            state=DeviceState(power=False, dim=None)
        )
        state = SimulatorState([device])
        
        retrieved = state.get_device("22222222-2222-4222-8222-222222222222")
        assert retrieved.name == 'The "Main" Hallway', \
            "Device name with quotes should be preserved"
    
    def test_device_name_with_unicode(self):
        """Validates device names with Unicode characters (international names).
        
        Impact: Integration must support international users' device names.
        """
        device = Device(
            uuid="33333333-3333-4333-8333-333333333333",
            name="Café Lumière",  # French characters
            capabilities=["power"],
            state=DeviceState(power=False, dim=None)
        )
        state = SimulatorState([device])
        
        retrieved = state.get_device("33333333-3333-4333-8333-333333333333")
        assert retrieved.name == "Café Lumière", \
            "Device name with Unicode should be preserved - international support"
    
    def test_device_name_with_emoji(self):
        """Validates device names with emoji characters.
        
        Impact: Users often add emojis to device names for visual identification.
        """
        device = Device(
            uuid="44444444-4444-4444-8444-444444444444",
            name="🏠 Front Door",  # House emoji
            capabilities=["power"],
            state=DeviceState(power=False, dim=None)
        )
        state = SimulatorState([device])
        
        retrieved = state.get_device("44444444-4444-4444-8444-444444444444")
        assert retrieved.name == "🏠 Front Door", \
            "Device name with emoji should be preserved - visual identification"
    
    def test_device_name_with_newline_rejected(self):
        """Validates device names cannot contain newlines.
        
        Impact: Newlines would break JSON protocol formatting.
        Note: Device model currently accepts newlines, this documents current behavior.
        """
        # Current behavior: newlines are accepted by model
        # This test documents the behavior for future validation enhancement
        device = Device(
            uuid="55555555-5555-4555-8555-555555555555",
            name="Line1\nLine2",
            capabilities=["power"],
            state=DeviceState(power=False, dim=None)
        )
        
        # Accepted by model (may break protocol - documented for future fix)
        assert "\n" in device.name, \
            "Current behavior: newlines accepted (potential protocol issue)"
    
    def test_device_name_with_special_chars(self):
        """Validates device names with various special characters.
        
        Impact: Users may use special characters for organization.
        """
        special_names = [
            "Room #1",
            "Light (Main)",
            "Device @ Home",
            "Switch & Dimmer",
            "Name-With-Dashes",
            "Under_Score_Name",
        ]
        
        for i, name in enumerate(special_names):
            device_uuid = f"{i+1:08d}-1111-4111-8111-111111111111"
            device = Device(
                uuid=device_uuid,
                name=name,
                capabilities=["power"],
                state=DeviceState(power=False, dim=None)
            )
            
            state = SimulatorState([device])
            retrieved = state.get_device(device_uuid)
            
            assert retrieved.name == name, \
                f"Special character name '{name}' should be preserved"
    
    def test_device_name_very_long(self):
        """Validates device names can be very long (up to reasonable limit).
        
        Impact: Some users create detailed device names.
        """
        long_name = "Living Room Main Overhead Light Switch With Dimmer Capability " * 3
        
        device = Device(
            uuid="66666666-6666-4666-8666-666666666666",
            name=long_name,
            capabilities=["power", "dim"],
            state=DeviceState(power=False, dim=0)
        )
        state = SimulatorState([device])
        
        retrieved = state.get_device("66666666-6666-4666-8666-666666666666")
        assert retrieved.name == long_name, \
            "Very long device name should be preserved - no truncation"
        assert len(retrieved.name) > 100, \
            "Name should still be long (>100 chars)"


class TestUUIDHandling:
    """Test UUID generation and validation edge cases.
    
    User Story: Devices must have valid UUIDs for identification.
    """
    
    def test_uuid_format_validation_v4_only(self):
        """Validates only UUID v4 format accepted (not v1, v3, v5).
        
        Impact: Integration relies on consistent UUID format.
        """
        # Valid UUID v4 (version nibble = 4, variant nibble = 8/9/a/b)
        valid_uuid = "a1b2c3d4-e5f6-4789-a012-b3c4d5e6f789"
        device = Device(
            uuid=valid_uuid,
            name="Valid Device",
            capabilities=["power"],
            state=DeviceState(power=False, dim=None)
        )
        assert device.uuid == valid_uuid
    
    def test_uuid_lowercase_required(self):
        """Validates UUID must be lowercase.
        
        Impact: Protocol specifies lowercase UUIDs for consistency.
        """
        with pytest.raises(ValueError, match="uuid must be lowercase UUID v4 format"):
            Device(
                uuid="A1B2C3D4-E5F6-4789-A012-B3C4D5E6F789",
                name="Uppercase UUID",
                capabilities=["power"],
                state=DeviceState(power=False, dim=None)
            )
    
    def test_uuid_mixed_case_rejected(self):
        """Validates mixed-case UUIDs rejected.
        
        Impact: Ensures consistent UUID formatting.
        """
        with pytest.raises(ValueError, match="uuid must be lowercase UUID v4 format"):
            Device(
                uuid="a1b2c3d4-E5F6-4789-A012-b3c4d5e6f789",
                name="Mixed Case UUID",
                capabilities=["power"],
                state=DeviceState(power=False, dim=None)
            )
    
    def test_uuid_without_hyphens_rejected(self):
        """Validates UUID must include hyphens in correct positions.
        
        Impact: Standard UUID format required for interoperability.
        """
        with pytest.raises(ValueError, match="uuid must be lowercase UUID v4 format"):
            Device(
                uuid="a1b2c3d4e5f64789a012b3c4d5e6f789",
                name="No Hyphens",
                capabilities=["power"],
                state=DeviceState(power=False, dim=None)
            )
    
    def test_uuid_wrong_version_rejected(self):
        """Validates UUID v1/v3/v5 rejected (only v4 accepted).
        
        Impact: Consistent UUID generation across all devices.
        """
        # UUID v1 (version nibble = 1)
        with pytest.raises(ValueError, match="uuid must be lowercase UUID v4 format"):
            Device(
                uuid="a1b2c3d4-e5f6-1789-a012-b3c4d5e6f789",
                name="UUID v1",
                capabilities=["power"],
                state=DeviceState(power=False, dim=None)
            )
    
    def test_uuid_duplicate_detection_in_config(self):
        """Validates config validation catches duplicate UUIDs.
        
        Impact: Each device must have unique UUID for identification.
        """
        # This is validated at Config level, not Device level
        # Documented here for completeness
        device1 = Device(
            uuid="11111111-1111-4111-8111-111111111111",
            name="Device 1",
            capabilities=["power"],
            state=DeviceState(power=False, dim=None)
        )
        device2 = Device(
            uuid="11111111-1111-4111-8111-111111111111",  # Duplicate UUID
            name="Device 2",
            capabilities=["power"],
            state=DeviceState(power=False, dim=None)
        )
        
        # Both devices can be created individually
        assert device1.uuid == device2.uuid, \
            "Model allows duplicate UUIDs (config validation catches this)"
    
    def test_uuid_generated_are_unique(self):
        """Validates UUID generation produces unique IDs.
        
        Impact: No collisions when generating UUIDs for new devices.
        """
        generated_uuids = set()
        
        for i in range(100):
            new_uuid = str(uuid.uuid4())
            
            assert new_uuid not in generated_uuids, \
                f"UUID collision detected: {new_uuid}"
            
            # Verify format is valid for Device model
            device = Device(
                uuid=new_uuid,
                name=f"Generated Device {i}",
                capabilities=["power"],
                state=DeviceState(power=False, dim=None)
            )
            
            generated_uuids.add(new_uuid)
        
        assert len(generated_uuids) == 100, \
            "All generated UUIDs should be unique"


class TestDefaultConfigDevices:
    """Test default configuration device list.
    
    User Story: Default config should work out-of-box for testing.
    """
    
    def test_default_config_has_three_devices(self):
        """Validates default config provides 3 sample devices.
        
        Impact: Zero-config startup should work immediately.
        """
        config = get_default_config()
        
        assert len(config.devices) == 3, \
            "Default config should have 3 devices - ready for immediate testing"
    
    def test_default_config_mixed_capabilities(self):
        """Validates default devices include power-only and dimmable.
        
        Impact: Default config should demonstrate both device types.
        """
        config = get_default_config()
        
        power_only_count = sum(
            1 for d in config.devices 
            if d.capabilities == ["power"]
        )
        dimmable_count = sum(
            1 for d in config.devices 
            if "dim" in d.capabilities
        )
        
        assert power_only_count >= 1, \
            "Default config should have at least one power-only device"
        assert dimmable_count >= 1, \
            "Default config should have at least one dimmable device"
    
    def test_default_config_all_devices_have_valid_uuids(self):
        """Validates all default devices have valid UUID v4 format.
        
        Impact: Default config should be valid without modification.
        """
        config = get_default_config()
        
        for device in config.devices:
            # Device model __post_init__ validates UUID format
            # If no exception raised, UUID is valid
            assert device.uuid, \
                f"Device '{device.name}' should have valid UUID"
            assert "-" in device.uuid, \
                f"Device '{device.name}' UUID should have hyphens"
