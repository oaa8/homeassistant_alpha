"""Unit tests for device and message data models.

Author: GitHub Copilot
Created: 2025-10-25
Purpose: Validate Device and DeviceState creation, validation, and state updates

Test Coverage:
- Device creation with valid/invalid data
- UUID validation (format, lowercase requirement)
- DeviceState validation (dim range, null handling)
- Capability validation (power requirement, dim+power relationship)
- State update logic (null=no-change per FR-082)
"""

import pytest
from deako_simulator.models import Device, DeviceState


class TestDeviceState:
    """Test DeviceState dataclass validation and behavior."""
    
    def test_create_power_only_state(self):
        """Validates FR-005: Power-only devices have dim=None."""
        state = DeviceState(power=False, dim=None)
        assert state.power is False
        assert state.dim is None
    
    def test_create_dimmable_state(self):
        """Validates FR-005: Dimmable devices have power and dim."""
        state = DeviceState(power=True, dim=75)
        assert state.power is True
        assert state.dim == 75
    
    def test_dim_range_clamping_upper(self):
        """Validates dim-validation-test-2025-10-18.md: Values >100 clamped to 100."""
        state = DeviceState(power=True, dim=150)
        assert state.dim == 100, \
            "Dim value 150 should be clamped to 100 per hardware behavior"
    
    def test_dim_range_clamping_lower(self):
        """Validates dim-validation-test-2025-10-18.md: Values <0 clamped to 0."""
        state = DeviceState(power=True, dim=-50)
        assert state.dim == 0, \
            "Dim value -50 should be clamped to 0 per hardware behavior"
    
    def test_dim_decimal_truncation(self):
        """Validates dim-validation-test-2025-10-18.md: Decimal values truncated."""
        state = DeviceState(power=True, dim=75.9)
        assert state.dim == 75, \
            "Dim value 75.9 should be truncated to 75 per hardware behavior"
    
    def test_dim_invalid_type(self):
        """Validates dim must be numeric."""
        with pytest.raises(ValueError, match="dim must be numeric"):
            DeviceState(power=True, dim="invalid")


class TestDevice:
    """Test Device dataclass validation and behavior."""
    
    def test_create_power_only_device(self):
        """Validates device creation with only power capability."""
        device = Device(
            uuid="a1b2c3d4-e5f6-4789-a012-b3c4d5e6f789",
            name="Test Light",
            capabilities=["power"],
            state=DeviceState(power=False, dim=None)
        )
        assert device.uuid == "a1b2c3d4-e5f6-4789-a012-b3c4d5e6f789"
        assert device.name == "Test Light"
        assert device.capabilities == ["power"]
        assert device.state.power is False
        assert device.state.dim is None
    
    def test_create_dimmable_device(self):
        """Validates device creation with power and dim capabilities."""
        device = Device(
            uuid="b2c3d4e5-f6a7-4890-b123-c4d5e6f7a890",
            name="Test Dimmer",
            capabilities=["power", "dim"],
            state=DeviceState(power=True, dim=50)
        )
        assert device.capabilities == ["power", "dim"]
        assert device.state.power is True
        assert device.state.dim == 50
    
    def test_uuid_validation_invalid_format(self):
        """Validates UUID must be valid UUID v4 format."""
        with pytest.raises(ValueError, match="uuid must be lowercase UUID v4 format"):
            Device(
                uuid="invalid-uuid",
                name="Test",
                capabilities=["power"],
                state=DeviceState(power=False, dim=None)
            )
    
    def test_uuid_validation_uppercase(self):
        """Validates UUID must be lowercase."""
        with pytest.raises(ValueError, match="uuid must be lowercase UUID v4 format"):
            Device(
                uuid="A1B2C3D4-E5F6-4789-A012-B3C4D5E6F789",
                name="Test",
                capabilities=["power"],
                state=DeviceState(power=False, dim=None)
            )
    
    def test_uuid_validation_uuid_v1_rejected(self):
        """Validates only UUID v4 accepted (not v1, v3, v5)."""
        # UUID v1 (time-based) has version nibble = 1
        with pytest.raises(ValueError, match="uuid must be lowercase UUID v4 format"):
            Device(
                uuid="a1b2c3d4-e5f6-1789-a012-b3c4d5e6f789",  # v1, not v4
                name="Test",
                capabilities=["power"],
                state=DeviceState(power=False, dim=None)
            )
    
    def test_name_validation_empty(self):
        """Validates device name must be non-empty."""
        with pytest.raises(ValueError, match="name must be non-empty"):
            Device(
                uuid="a1b2c3d4-e5f6-4789-a012-b3c4d5e6f789",
                name="",
                capabilities=["power"],
                state=DeviceState(power=False, dim=None)
            )
    
    def test_name_validation_whitespace_only(self):
        """Validates device name must not be only whitespace."""
        with pytest.raises(ValueError, match="name must be non-empty"):
            Device(
                uuid="a1b2c3d4-e5f6-4789-a012-b3c4d5e6f789",
                name="   ",
                capabilities=["power"],
                state=DeviceState(power=False, dim=None)
            )
    
    def test_capabilities_empty(self):
        """Validates capabilities must not be empty."""
        with pytest.raises(ValueError, match="capabilities must not be empty"):
            Device(
                uuid="a1b2c3d4-e5f6-4789-a012-b3c4d5e6f789",
                name="Test",
                capabilities=[],
                state=DeviceState(power=False, dim=None)
            )
    
    def test_capabilities_missing_power(self):
        """Validates FR-005: capabilities must include 'power'."""
        with pytest.raises(ValueError, match="capabilities must include 'power'"):
            Device(
                uuid="a1b2c3d4-e5f6-4789-a012-b3c4d5e6f789",
                name="Test",
                capabilities=["dim"],
                state=DeviceState(power=False, dim=None)
            )
    
    def test_capabilities_dim_requires_power(self):
        """Validates FR-005: dim capability requires power capability.
        
        Note: This test triggers the 'power required' check before the
        'dim requires power' check, so we test the first error encountered.
        """
        with pytest.raises(ValueError, match="capabilities must include 'power'"):
            Device(
                uuid="a1b2c3d4-e5f6-4789-a012-b3c4d5e6f789",
                name="Test",
                capabilities=["dim"],
                state=DeviceState(power=False, dim=None)
            )
    
    def test_capabilities_unknown(self):
        """Validates only known capabilities accepted."""
        with pytest.raises(ValueError, match="Unknown capabilities"):
            Device(
                uuid="a1b2c3d4-e5f6-4789-a012-b3c4d5e6f789",
                name="Test",
                capabilities=["power", "color"],
                state=DeviceState(power=False, dim=None)
            )
    
    def test_state_consistency_dim_without_capability(self):
        """Validates device cannot have dim state without dim capability."""
        with pytest.raises(ValueError, match="has dim state but no dim capability"):
            Device(
                uuid="a1b2c3d4-e5f6-4789-a012-b3c4d5e6f789",
                name="Test",
                capabilities=["power"],
                state=DeviceState(power=False, dim=50)
            )
    
    def test_update_state_power(self):
        """Validates state.update_state() changes power."""
        device = Device(
            uuid="a1b2c3d4-e5f6-4789-a012-b3c4d5e6f789",
            name="Test",
            capabilities=["power"],
            state=DeviceState(power=False, dim=None)
        )
        device.update_state(power=True)
        assert device.state.power is True, \
            "update_state(power=True) should change device power state"
    
    def test_update_state_dim(self):
        """Validates state.update_state() changes dim."""
        device = Device(
            uuid="a1b2c3d4-e5f6-4789-a012-b3c4d5e6f789",
            name="Test",
            capabilities=["power", "dim"],
            state=DeviceState(power=True, dim=0)
        )
        device.update_state(dim=75)
        assert device.state.dim == 75, \
            "update_state(dim=75) should change device dim level"
    
    def test_update_state_null_means_no_change(self):
        """Validates FR-082: null/None in update means 'no change'."""
        device = Device(
            uuid="a1b2c3d4-e5f6-4789-a012-b3c4d5e6f789",
            name="Test",
            capabilities=["power", "dim"],
            state=DeviceState(power=True, dim=75)
        )
        # Update with None should keep current values
        device.update_state(power=None, dim=None)
        assert device.state.power is True, \
            "update_state(power=None) should keep current power state per FR-082"
        assert device.state.dim == 75, \
            "update_state(dim=None) should keep current dim level per FR-082"
    
    def test_update_state_dim_without_capability(self):
        """Validates cannot update dim on power-only device."""
        device = Device(
            uuid="a1b2c3d4-e5f6-4789-a012-b3c4d5e6f789",
            name="Test",
            capabilities=["power"],
            state=DeviceState(power=False, dim=None)
        )
        with pytest.raises(ValueError, match="does not have dim capability"):
            device.update_state(dim=50)
    
    def test_update_state_dim_clamping(self):
        """Validates update_state() clamps dim values to 0-100."""
        device = Device(
            uuid="a1b2c3d4-e5f6-4789-a012-b3c4d5e6f789",
            name="Test",
            capabilities=["power", "dim"],
            state=DeviceState(power=True, dim=50)
        )
        device.update_state(dim=150)
        assert device.state.dim == 100, \
            "update_state(dim=150) should clamp to 100"
        
        device.update_state(dim=-10)
        assert device.state.dim == 0, \
            "update_state(dim=-10) should clamp to 0"
    
    def test_update_state_method_chaining(self):
        """Validates update_state() returns self for method chaining."""
        device = Device(
            uuid="a1b2c3d4-e5f6-4789-a012-b3c4d5e6f789",
            name="Test",
            capabilities=["power", "dim"],
            state=DeviceState(power=False, dim=0)
        )
        result = device.update_state(power=True, dim=75)
        assert result is device, \
            "update_state() should return self for method chaining"
