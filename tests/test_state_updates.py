"""
Unit tests for device state update scenarios.

Created: 2025-10-27
Author: GitHub Copilot

Purpose:
    Tests device state update operations for User Story 3 (Device Control).
    Focuses on power toggle, dim level changes, null handling, and validation.

Coverage:
- Power toggle operations
- Dim level changes (0-100 range)
- Null handling (FR-082: null=no-change)
- Invalid dim values (FR-071: clamp to 0-100, truncate decimals)
- Non-existent device UUID (FR-066: REQUEST_INVALID error)

Related Requirements:
- FR-071: Accept all numeric dim values, clamp internally
- FR-082: Null fields mean no change
- FR-066: REQUEST_INVALID error for invalid device UUID

Related Research:
- research/dim-validation-test-2025-10-18.md - Dim value handling
"""

import pytest

from deako_simulator.models import Device, DeviceState
from deako_simulator.state import SimulatorState


@pytest.fixture
def sample_devices():
    """Create sample devices for testing."""
    return [
        Device(
            uuid="11111111-1111-4111-8111-111111111111",
            name="Dimmable Light",
            capabilities=["power", "dim"],
            state=DeviceState(power=False, dim=0)
        ),
        Device(
            uuid="22222222-2222-4222-8222-222222222222",
            name="Switch Only",
            capabilities=["power"],
            state=DeviceState(power=False, dim=None)
        ),
    ]


@pytest.fixture
def state(sample_devices):
    """Create SimulatorState with sample devices."""
    return SimulatorState(sample_devices)


class TestPowerToggle:
    """Test power toggle operations."""
    
    def test_power_toggle_off_to_on(self, state):
        """
        Test power toggle from off to on.
        
        End-User Scenario: User turns on a light via Home Assistant.
        Expected: Device power state changes to True.
        Impact: If this fails, user cannot turn on lights.
        """
        uuid = "11111111-1111-4111-8111-111111111111"
        
        # Initially off
        assert state.get_device(uuid).state.power is False
        
        # Toggle on
        device = state.update_device_state(uuid, power=True)
        
        assert device.state.power is True, \
            "Power should be True after turning on, but integration won't see device turn on"
    
    def test_power_toggle_on_to_off(self, state):
        """
        Test power toggle from on to off.
        
        End-User Scenario: User turns off a light via Home Assistant.
        Expected: Device power state changes to False.
        Impact: If this fails, user cannot turn off lights.
        """
        uuid = "11111111-1111-4111-8111-111111111111"
        
        # Turn on first
        state.update_device_state(uuid, power=True)
        assert state.get_device(uuid).state.power is True
        
        # Toggle off
        device = state.update_device_state(uuid, power=False)
        
        assert device.state.power is False, \
            "Power should be False after turning off, but integration won't see device turn off"
    
    def test_power_toggle_preserves_dim(self, state):
        """
        Test power toggle preserves dim level.
        
        End-User Scenario: User turns light off at 75%, then back on.
        Expected: Dim level remains 75% after power toggle.
        Impact: If this fails, user loses brightness setting when toggling power.
        
        Validates FR-082: null=no-change
        """
        uuid = "11111111-1111-4111-8111-111111111111"
        
        # Set to 75% brightness
        state.update_device_state(uuid, power=True, dim=75)
        assert state.get_device(uuid).state.dim == 75
        
        # Toggle power off (dim should remain)
        device = state.update_device_state(uuid, power=False)
        assert device.state.dim == 75, \
            "Dim level should remain 75 after power toggle, but user will lose brightness setting"


class TestDimLevelChanges:
    """Test dim level change operations."""
    
    def test_dim_level_change_0_to_100(self, state):
        """
        Test dim level change from minimum to maximum.
        
        End-User Scenario: User adjusts light from 0% to 100%.
        Expected: Dim level changes to 100.
        Impact: If this fails, user cannot set full brightness.
        """
        uuid = "11111111-1111-4111-8111-111111111111"
        
        # Set to 0%
        state.update_device_state(uuid, dim=0)
        assert state.get_device(uuid).state.dim == 0
        
        # Change to 100%
        device = state.update_device_state(uuid, dim=100)
        
        assert device.state.dim == 100, \
            "Dim level should be 100 after setting to maximum, but integration won't see full brightness"
    
    def test_dim_level_change_50_percent(self, state):
        """
        Test dim level change to 50%.
        
        End-User Scenario: User sets light to 50% brightness.
        Expected: Dim level changes to 50.
        Impact: If this fails, user cannot set mid-range brightness.
        """
        uuid = "11111111-1111-4111-8111-111111111111"
        
        device = state.update_device_state(uuid, dim=50)
        
        assert device.state.dim == 50, \
            "Dim level should be 50, but integration won't see correct brightness"
    
    def test_dim_level_change_preserves_power(self, state):
        """
        Test dim level change preserves power state.
        
        End-User Scenario: User adjusts brightness while light is on.
        Expected: Power state remains True after dim change.
        Impact: If this fails, adjusting brightness might turn off light.
        
        Validates FR-082: null=no-change
        """
        uuid = "11111111-1111-4111-8111-111111111111"
        
        # Turn on
        state.update_device_state(uuid, power=True)
        assert state.get_device(uuid).state.power is True
        
        # Change dim (power should remain)
        device = state.update_device_state(uuid, dim=50)
        
        assert device.state.power is True, \
            "Power should remain True after dim change, but user will see light turn off unexpectedly"


class TestNullHandling:
    """Test null handling per FR-082."""
    
    def test_null_power_no_change(self, state):
        """
        Test null power value means no change.
        
        End-User Scenario: CONTROL command with only dim value (power=null).
        Expected: Power state unchanged.
        Impact: If this fails, setting brightness might unexpectedly change power state.
        
        Validates FR-082: null fields mean no change
        """
        uuid = "11111111-1111-4111-8111-111111111111"
        
        # Turn on
        state.update_device_state(uuid, power=True)
        assert state.get_device(uuid).state.power is True
        
        # Update with null power (only dim)
        device = state.update_device_state(uuid, power=None, dim=50)
        
        assert device.state.power is True, \
            "Power should remain True when power=None, but integration will see unexpected power state"
    
    def test_null_dim_no_change(self, state):
        """
        Test null dim value means no change.
        
        End-User Scenario: CONTROL command with only power value (dim=null).
        Expected: Dim level unchanged.
        Impact: If this fails, toggling power might reset brightness.
        
        Validates FR-082: null fields mean no change
        """
        uuid = "11111111-1111-4111-8111-111111111111"
        
        # Set to 75%
        state.update_device_state(uuid, dim=75)
        assert state.get_device(uuid).state.dim == 75
        
        # Update with null dim (only power)
        device = state.update_device_state(uuid, power=True, dim=None)
        
        assert device.state.dim == 75, \
            "Dim should remain 75 when dim=None, but user will lose brightness setting"
    
    def test_both_null_no_change(self, state):
        """
        Test both null values means no change.
        
        End-User Scenario: CONTROL command with no state changes (edge case).
        Expected: Both power and dim remain unchanged.
        Impact: If this fails, empty updates might reset device state.
        
        Validates FR-082: null fields mean no change
        """
        uuid = "11111111-1111-4111-8111-111111111111"
        
        # Set initial state
        state.update_device_state(uuid, power=True, dim=50)
        initial_power = state.get_device(uuid).state.power
        initial_dim = state.get_device(uuid).state.dim
        
        # Update with both null
        device = state.update_device_state(uuid, power=None, dim=None)
        
        assert device.state.power == initial_power, \
            "Power should remain unchanged when both fields null"
        assert device.state.dim == initial_dim, \
            "Dim should remain unchanged when both fields null"


class TestInvalidDimValues:
    """Test invalid dim value handling per FR-071."""
    
    def test_negative_dim_clamped_to_zero(self, state):
        """
        Test negative dim values clamped to 0.
        
        End-User Scenario: Integration sends invalid dim=-1.
        Expected: Dim clamped to 0 (not rejected).
        Impact: If this fails, invalid commands will cause errors instead of graceful handling.
        
        Validates FR-071: Accept all numeric values, clamp to 0-100
        Research: research/dim-validation-test-2025-10-18.md - Real hub accepts -1 and clamps
        """
        uuid = "11111111-1111-4111-8111-111111111111"
        
        device = state.update_device_state(uuid, dim=-1)
        
        assert device.state.dim == 0, \
            f"Dim should be clamped to 0 for negative values, but got {device.state.dim} - integration will see wrong brightness"
    
    def test_negative_dim_large_value_clamped(self, state):
        """
        Test large negative dim values clamped to 0.
        
        End-User Scenario: Integration sends invalid dim=-1000.
        Expected: Dim clamped to 0.
        Impact: If this fails, invalid commands will cause errors.
        
        Validates FR-071: Accept all numeric values, clamp to 0-100
        Research: research/dim-validation-test-2025-10-18.md
        """
        uuid = "11111111-1111-4111-8111-111111111111"
        
        device = state.update_device_state(uuid, dim=-1000)
        
        assert device.state.dim == 0, \
            f"Dim should be clamped to 0 for large negative values, but got {device.state.dim}"
    
    def test_dim_over_100_clamped(self, state):
        """
        Test dim values over 100 clamped to 100.
        
        End-User Scenario: Integration sends invalid dim=101.
        Expected: Dim clamped to 100.
        Impact: If this fails, invalid commands will cause errors.
        
        Validates FR-071: Accept all numeric values, clamp to 0-100
        Research: research/dim-validation-test-2025-10-18.md - Real hub accepts 101 and clamps
        """
        uuid = "11111111-1111-4111-8111-111111111111"
        
        device = state.update_device_state(uuid, dim=101)
        
        assert device.state.dim == 100, \
            f"Dim should be clamped to 100 for values >100, but got {device.state.dim} - integration will see wrong brightness"
    
    def test_dim_large_value_clamped(self, state):
        """
        Test large dim values clamped to 100.
        
        End-User Scenario: Integration sends invalid dim=1000.
        Expected: Dim clamped to 100.
        Impact: If this fails, invalid commands will cause errors.
        
        Validates FR-071: Accept all numeric values, clamp to 0-100
        Research: research/dim-validation-test-2025-10-18.md
        """
        uuid = "11111111-1111-4111-8111-111111111111"
        
        device = state.update_device_state(uuid, dim=1000)
        
        assert device.state.dim == 100, \
            f"Dim should be clamped to 100 for large values, but got {device.state.dim}"
    
    def test_decimal_dim_truncated(self, state):
        """
        Test decimal dim values truncated to int.
        
        End-User Scenario: Integration sends dim=50.7.
        Expected: Dim truncated to 50.
        Impact: If this fails, decimal values might cause errors or wrong brightness.
        
        Validates FR-071: Truncate decimals to int
        Research: research/dim-validation-test-2025-10-18.md - Real hub accepts 50.7 and truncates to 50
        """
        uuid = "11111111-1111-4111-8111-111111111111"
        
        device = state.update_device_state(uuid, dim=50.7)
        
        assert device.state.dim == 50, \
            f"Dim should be truncated to 50 for decimal 50.7, but got {device.state.dim} - integration will see wrong brightness"
    
    def test_decimal_dim_truncated_rounds_down(self, state):
        """
        Test decimal dim values always round down (truncate).
        
        End-User Scenario: Integration sends dim=50.9.
        Expected: Dim truncated to 50 (not rounded to 51).
        Impact: If this fails, brightness might not match user expectations.
        
        Validates FR-071: Truncate decimals to int (not round)
        """
        uuid = "11111111-1111-4111-8111-111111111111"
        
        device = state.update_device_state(uuid, dim=50.9)
        
        assert device.state.dim == 50, \
            f"Dim should be truncated to 50 for decimal 50.9, but got {device.state.dim} - should truncate not round"


class TestNonExistentDevice:
    """Test error handling for non-existent device UUIDs."""
    
    def test_update_nonexistent_device_raises_keyerror(self, state):
        """
        Test updating non-existent device raises KeyError.
        
        End-User Scenario: Integration sends CONTROL for unknown device UUID.
        Expected: KeyError raised (should be caught and converted to REQUEST_INVALID).
        Impact: If this fails, invalid commands won't trigger proper error responses.
        
        Validates FR-066: REQUEST_INVALID error for invalid device UUID
        """
        uuid = "99999999-9999-9999-9999-999999999999"
        
        with pytest.raises(KeyError):
            state.update_device_state(uuid, power=True)
    
    def test_get_nonexistent_device_returns_none(self, state):
        """
        Test getting non-existent device returns None.
        
        End-User Scenario: Integration queries unknown device UUID.
        Expected: None returned (should be checked before update operations).
        Impact: If this fails, invalid queries might not be detected properly.
        
        Validates FR-066: REQUEST_INVALID error for invalid device UUID
        """
        uuid = "99999999-9999-9999-9999-999999999999"
        
        device = state.get_device(uuid)
        
        assert device is None, \
            "get_device should return None for non-existent UUID, but integration won't detect invalid devices"


class TestDimValidationRange:
    """Test dim validation covers full 0-100 range."""
    
    def test_dim_valid_range_0(self, state):
        """Test dim=0 is valid (minimum)."""
        uuid = "11111111-1111-4111-8111-111111111111"
        device = state.update_device_state(uuid, dim=0)
        assert device.state.dim == 0
    
    def test_dim_valid_range_100(self, state):
        """Test dim=100 is valid (maximum)."""
        uuid = "11111111-1111-4111-8111-111111111111"
        device = state.update_device_state(uuid, dim=100)
        assert device.state.dim == 100
    
    def test_dim_valid_range_50(self, state):
        """Test dim=50 is valid (mid-range)."""
        uuid = "11111111-1111-4111-8111-111111111111"
        device = state.update_device_state(uuid, dim=50)
        assert device.state.dim == 50
    
    def test_dim_valid_range_1(self, state):
        """Test dim=1 is valid (minimum non-zero)."""
        uuid = "11111111-1111-4111-8111-111111111111"
        device = state.update_device_state(uuid, dim=1)
        assert device.state.dim == 1
    
    def test_dim_valid_range_99(self, state):
        """Test dim=99 is valid (maximum minus 1)."""
        uuid = "11111111-1111-4111-8111-111111111111"
        device = state.update_device_state(uuid, dim=99)
        assert device.state.dim == 99
