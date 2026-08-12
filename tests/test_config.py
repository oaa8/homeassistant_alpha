"""Unit tests for configuration management.

Author: GitHub Copilot
Created: 2025-10-26
Purpose: Validate configuration loading, validation, and error handling

Test Coverage:
- Config file loading (valid/invalid JSON)
- JSON Schema validation (structure)
- Semantic validation (business rules)
- Default configuration
- Error message formatting (FR-043)
"""

import pytest
import json
import tempfile
from pathlib import Path

from deako_simulator.config import (
    Config, NetworkConfig, Scenario, DeviceState,
    load_config, get_default_config,
    _validate_semantic_rules, _format_json_path, _config_from_dict
)
from deako_simulator.models import Device


class TestDefaultConfig:
    """Test get_default_config() function."""
    
    def test_default_config_structure(self):
        """Validates default config has expected structure."""
        config = get_default_config()
        
        assert isinstance(config, Config)
        assert len(config.devices) == 3, \
            "Default config should have 3 sample devices for testing"
        assert config.network.host == "0.0.0.0"
        assert config.network.port == 23
        assert config.network.http_port == 8080
        assert config.network.mdns_name == "local-integration"
        assert config.log_level == "INFO"
        assert config.scenarios == []
    
    def test_default_devices_valid(self):
        """Validates default devices are properly configured."""
        config = get_default_config()
        
        # Check mix of power-only and dimmable
        dimmable_count = sum(1 for d in config.devices if "dim" in d.capabilities)
        power_only_count = len(config.devices) - dimmable_count
        
        assert dimmable_count >= 1, "Default config should have at least one dimmable device"
        assert power_only_count >= 1, "Default config should have at least one power-only device"
        
        # Check all devices valid
        for device in config.devices:
            assert device.uuid
            assert device.name
            assert "power" in device.capabilities


class TestNetworkConfig:
    """Test NetworkConfig validation."""
    
    def test_create_valid_network_config(self):
        """Validates valid network configuration."""
        config = NetworkConfig(
            host="127.0.0.1",
            port=2323,
            http_port=8888,
            mdns_name="test-simulator"
        )
        assert config.host == "127.0.0.1"
        assert config.port == 2323
        assert config.http_port == 8888
    
    def test_port_validation_too_low(self):
        """Validates port must be >= 0 (0 allowed for dynamic allocation)."""
        with pytest.raises(ValueError, match="network.port must be 0-65535"):
            NetworkConfig(port=-1)
    
    def test_port_validation_too_high(self):
        """Validates port must be <= 65535."""
        with pytest.raises(ValueError, match="network.port must be 0-65535"):
            NetworkConfig(port=65536)
    
    def test_http_port_validation(self):
        """Validates http_port must be valid range."""
        with pytest.raises(ValueError, match="network.http_port must be 0-65535"):
            NetworkConfig(http_port=70000)
    
    def test_ports_must_differ(self):
        """Validates telnet and HTTP ports cannot be the same."""
        with pytest.raises(ValueError, match="must be different"):
            NetworkConfig(port=8080, http_port=8080)
    
    def test_mdns_name_empty(self):
        """Validates mDNS name cannot be empty."""
        with pytest.raises(ValueError, match="mdns_name must be non-empty"):
            NetworkConfig(mdns_name="")


class TestScenario:
    """Test Scenario validation."""
    
    def test_create_valid_scenario(self):
        """Validates valid scenario creation."""
        device_states = {
            "11111111-1111-4111-8111-111111111111": DeviceState(power=True, dim=100)
        }
        scenario = Scenario(
            name="test-scenario",
            description="Test scenario",
            device_states=device_states
        )
        assert scenario.name == "test-scenario"
        assert scenario.description == "Test scenario"
        assert len(scenario.device_states) == 1
    
    def test_scenario_name_empty(self):
        """Validates scenario name cannot be empty."""
        with pytest.raises(ValueError, match="scenario.name must be non-empty"):
            Scenario(
                name="",
                description="Test",
                device_states={"uuid": DeviceState(power=True, dim=None)}
            )
    
    def test_scenario_no_device_states(self):
        """Validates scenario must have at least one device state."""
        with pytest.raises(ValueError, match="has no device_states"):
            Scenario(
                name="test",
                description="Test",
                device_states={}
            )


class TestConfig:
    """Test Config validation."""
    
    def test_create_valid_config(self):
        """Validates valid configuration creation."""
        devices = [
            Device(
                uuid="11111111-1111-4111-8111-111111111111",
                name="Test Device",
                capabilities=["power"],
                state=DeviceState(power=False, dim=None)
            )
        ]
        config = Config(devices=devices)
        
        assert len(config.devices) == 1
        assert config.log_level == "INFO"
        assert isinstance(config.network, NetworkConfig)
    
    def test_config_empty_devices(self):
        """Validates configuration must have at least one device."""
        with pytest.raises(ValueError, match="at least one device"):
            Config(devices=[])
    
    def test_config_invalid_log_level(self):
        """Validates log_level must be valid value."""
        devices = [
            Device(
                uuid="11111111-1111-4111-8111-111111111111",
                name="Test",
                capabilities=["power"],
                state=DeviceState(power=False, dim=None)
            )
        ]
        with pytest.raises(ValueError, match="log_level must be one of"):
            Config(devices=devices, log_level="TRACE")


class TestLoadConfig:
    """Test load_config() function with actual files."""
    
    def test_load_valid_config(self, tmp_path):
        """Validates loading valid configuration file."""
        config_data = {
            "devices": [
                {
                    "uuid": "11111111-1111-4111-8111-111111111111",
                    "name": "Test Device",
                    "capabilities": ["power", "dim"],
                    "state": {"power": False, "dim": 0}
                }
            ]
        }
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))
        
        config = load_config(config_file)
        
        assert len(config.devices) == 1
        assert config.devices[0].name == "Test Device"
    
    def test_load_config_file_not_found(self, tmp_path):
        """Validates appropriate error when config file doesn't exist."""
        nonexistent_file = tmp_path / "nonexistent.json"
        
        with pytest.raises(SystemExit) as exc_info:
            load_config(nonexistent_file)
        
        assert exc_info.value.code == 1
    
    def test_load_config_invalid_json(self, tmp_path, capsys):
        """Validates error handling for malformed JSON."""
        config_file = tmp_path / "invalid.json"
        config_file.write_text("{invalid json")
        
        with pytest.raises(SystemExit) as exc_info:
            load_config(config_file)
        
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Invalid JSON" in captured.err
        assert "Line" in captured.err
    
    def test_load_config_schema_violation(self, tmp_path, capsys):
        """Validates JSON Schema validation catches structure errors."""
        config_data = {
            "devices": [
                {
                    "uuid": "11111111-1111-4111-8111-111111111111",
                    "name": "Test",
                    "capabilities": ["power"],
                    "state": {"power": False, "dim": 150}  # dim > 100
                }
            ]
        }
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))
        
        with pytest.raises(SystemExit) as exc_info:
            load_config(config_file)
        
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Config validation failed" in captured.err
        assert "devices[0].state.dim" in captured.err or "$.devices[0].state.dim" in captured.err
    
    def test_load_config_with_network_settings(self, tmp_path):
        """Validates loading config with custom network settings."""
        config_data = {
            "devices": [
                {
                    "uuid": "11111111-1111-4111-8111-111111111111",
                    "name": "Test",
                    "capabilities": ["power"],
                    "state": {"power": False, "dim": None}
                }
            ],
            "network": {
                "host": "127.0.0.1",
                "port": 2323,
                "http_port": 8888,
                "mdns_name": "custom-name"
            }
        }
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))
        
        config = load_config(config_file)
        
        assert config.network.host == "127.0.0.1"
        assert config.network.port == 2323
        assert config.network.http_port == 8888
        assert config.network.mdns_name == "custom-name"
    
    def test_load_config_with_scenarios(self, tmp_path):
        """Validates loading config with scenarios."""
        config_data = {
            "devices": [
                {
                    "uuid": "11111111-1111-4111-8111-111111111111",
                    "name": "Test Device",
                    "capabilities": ["power", "dim"],
                    "state": {"power": False, "dim": 0}
                }
            ],
            "scenarios": [
                {
                    "name": "all-on",
                    "description": "All lights on",
                    "device_states": {
                        "11111111-1111-4111-8111-111111111111": {
                            "power": True,
                            "dim": 100
                        }
                    }
                }
            ]
        }
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data))
        
        config = load_config(config_file)
        
        assert len(config.scenarios) == 1
        assert config.scenarios[0].name == "all-on"


class TestSemanticValidation:
    """Test _validate_semantic_rules() function."""
    
    def test_valid_config_no_errors(self):
        """Validates semantic validation passes for valid config."""
        config_dict = {
            "devices": [
                {
                    "uuid": "11111111-1111-4111-8111-111111111111",
                    "name": "Device 1",
                    "capabilities": ["power"],
                    "state": {"power": False, "dim": None}
                },
                {
                    "uuid": "22222222-2222-4222-8222-222222222222",
                    "name": "Device 2",
                    "capabilities": ["power", "dim"],
                    "state": {"power": False, "dim": 0}
                }
            ]
        }
        
        errors = _validate_semantic_rules(config_dict)
        
        assert errors == [], \
            f"Valid config should have no errors, got: {errors}"
    
    def test_duplicate_device_uuids(self):
        """Validates detection of duplicate device UUIDs."""
        config_dict = {
            "devices": [
                {
                    "uuid": "11111111-1111-4111-8111-111111111111",
                    "name": "Device 1",
                    "capabilities": ["power"],
                    "state": {"power": False, "dim": None}
                },
                {
                    "uuid": "11111111-1111-4111-8111-111111111111",  # Duplicate
                    "name": "Device 2",
                    "capabilities": ["power"],
                    "state": {"power": False, "dim": None}
                }
            ]
        }
        
        errors = _validate_semantic_rules(config_dict)
        
        assert len(errors) == 1
        assert "Duplicate device UUIDs" in errors[0]
        assert "11111111-1111-4111-8111-111111111111" in errors[0]
    
    def test_duplicate_scenario_names(self):
        """Validates detection of duplicate scenario names."""
        config_dict = {
            "devices": [
                {
                    "uuid": "11111111-1111-4111-8111-111111111111",
                    "name": "Device",
                    "capabilities": ["power"],
                    "state": {"power": False, "dim": None}
                }
            ],
            "scenarios": [
                {
                    "name": "test-scenario",
                    "device_states": {
                        "11111111-1111-4111-8111-111111111111": {"power": True, "dim": None}
                    }
                },
                {
                    "name": "test-scenario",  # Duplicate
                    "device_states": {
                        "11111111-1111-4111-8111-111111111111": {"power": False, "dim": None}
                    }
                }
            ]
        }
        
        errors = _validate_semantic_rules(config_dict)
        
        assert len(errors) == 1
        assert "Duplicate scenario names" in errors[0]
        assert "test-scenario" in errors[0]
    
    def test_scenario_references_unknown_device(self):
        """Validates detection of scenario referencing non-existent device."""
        config_dict = {
            "devices": [
                {
                    "uuid": "11111111-1111-4111-8111-111111111111",
                    "name": "Device",
                    "capabilities": ["power"],
                    "state": {"power": False, "dim": None}
                }
            ],
            "scenarios": [
                {
                    "name": "test-scenario",
                    "device_states": {
                        "99999999-9999-4999-8999-999999999999": {"power": True, "dim": None}
                    }
                }
            ]
        }
        
        errors = _validate_semantic_rules(config_dict)
        
        assert len(errors) == 1
        assert "unknown device UUID" in errors[0]
        assert "99999999-9999-4999-8999-999999999999" in errors[0]


class TestFormatJsonPath:
    """Test _format_json_path() helper function."""
    
    def test_empty_path(self):
        """Validates empty path formats as root '$'."""
        assert _format_json_path([]) == "$"
    
    def test_simple_property(self):
        """Validates simple property path formatting."""
        assert _format_json_path(["devices"]) == "$.devices"
    
    def test_nested_property(self):
        """Validates nested property path formatting."""
        assert _format_json_path(["network", "port"]) == "$.network.port"
    
    def test_array_index(self):
        """Validates array index path formatting."""
        assert _format_json_path(["devices", 0]) == "$.devices[0]"
    
    def test_complex_path(self):
        """Validates complex path with mixed elements."""
        assert _format_json_path(["devices", 2, "state", "dim"]) == "$.devices[2].state.dim"


class TestConfigFromDict:
    """Test _config_from_dict() conversion function."""
    
    def test_minimal_config(self):
        """Validates conversion of minimal valid config."""
        config_dict = {
            "devices": [
                {
                    "uuid": "11111111-1111-4111-8111-111111111111",
                    "name": "Test Device",
                    "capabilities": ["power"],
                    "state": {"power": False, "dim": None}
                }
            ]
        }
        
        config = _config_from_dict(config_dict)
        
        assert isinstance(config, Config)
        assert len(config.devices) == 1
        assert config.devices[0].name == "Test Device"
        assert config.log_level == "INFO"  # Default
    
    def test_config_with_all_fields(self):
        """Validates conversion of fully-populated config."""
        config_dict = {
            "devices": [
                {
                    "uuid": "11111111-1111-4111-8111-111111111111",
                    "name": "Test Device",
                    "capabilities": ["power", "dim"],
                    "state": {"power": True, "dim": 75}
                }
            ],
            "network": {
                "host": "127.0.0.1",
                "port": 2323,
                "http_port": 8888,
                "mdns_name": "test"
            },
            "scenarios": [
                {
                    "name": "test-scenario",
                    "description": "Test",
                    "device_states": {
                        "11111111-1111-4111-8111-111111111111": {"power": False, "dim": 0}
                    }
                }
            ],
            "log_level": "DEBUG"
        }
        
        config = _config_from_dict(config_dict)
        
        assert config.network.host == "127.0.0.1"
        assert config.network.port == 2323
        assert len(config.scenarios) == 1
        assert config.scenarios[0].name == "test-scenario"
        assert config.log_level == "DEBUG"
