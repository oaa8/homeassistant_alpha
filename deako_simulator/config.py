"""Configuration management for Deako Hub Simulator.

Author: GitHub Copilot
Created: 2025-10-26
Last Modified: 2025-10-26
Purpose: Load, validate, and manage simulator configuration from JSON files

Key Assumptions:
- Configuration files are JSON format only (no YAML/TOML per constitution)
- Validation is fail-fast (exit on errors, no warnings)
- Error messages include exact field paths per FR-043
- Default configuration available for zero-config startup

Related Research:
- specs/001-deako-hub-simulator/research.md - Decision 5 (Config Validation Approach)
- specs/001-deako-hub-simulator/contracts/config.schema.json
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import json
import sys
import jsonschema
from jsonschema import ValidationError

from deako_simulator.models import Device, DeviceState


@dataclass
class NetworkConfig:
    """Network configuration for telnet and HTTP servers.
    
    Attributes:
        host: Bind address (default: "0.0.0.0" for all interfaces)
        port: Telnet server port (default: 23)
        http_port: HTTP API server port (default: 8080)
        mdns_name: mDNS service name (default: "local-integration")
    """
    host: str = "0.0.0.0"
    port: int = 23
    http_port: int = 8080
    mdns_name: str = "local-integration"
    
    def __post_init__(self) -> None:
        """Validate network configuration.
        
        Note: port 0 is allowed for dynamic port allocation (used in tests).
        """
        if not 0 <= self.port <= 65535:
            raise ValueError(f"network.port must be 0-65535, got {self.port}")
        
        if not 0 <= self.http_port <= 65535:
            raise ValueError(f"network.http_port must be 0-65535, got {self.http_port}")
        
        # Allow both ports to be 0 (dynamic allocation in tests)
        # Otherwise, require them to be different
        if self.port == self.http_port and self.port != 0:
            raise ValueError(
                f"network.port and network.http_port must be different "
                f"(both are {self.port})"
            )
        
        if not self.mdns_name or not self.mdns_name.strip():
            raise ValueError("network.mdns_name must be non-empty")


@dataclass
class Scenario:
    """Named test scenario with predefined device states.
    
    Attributes:
        name: Scenario identifier (must be unique)
        description: Human-readable description
        device_states: Mapping of device UUID to desired state
    """
    name: str
    description: str
    device_states: dict[str, DeviceState]
    
    def __post_init__(self) -> None:
        """Validate scenario configuration."""
        if not self.name or not self.name.strip():
            raise ValueError("scenario.name must be non-empty")
        
        if not self.device_states:
            raise ValueError(f"scenario '{self.name}' has no device_states")


@dataclass
class Config:
    """Complete simulator configuration.
    
    Attributes:
        devices: List of devices to simulate
        network: Network configuration for servers
        scenarios: Named test scenarios for runtime activation
        log_level: Logging verbosity (DEBUG/INFO/WARNING/ERROR)
    """
    devices: list[Device]
    network: NetworkConfig = field(default_factory=NetworkConfig)
    scenarios: list[Scenario] = field(default_factory=list)
    log_level: str = "INFO"
    
    def __post_init__(self) -> None:
        """Validate configuration."""
        if not self.devices:
            raise ValueError("Configuration must have at least one device")
        
        valid_log_levels = {"DEBUG", "INFO", "WARNING", "ERROR"}
        if self.log_level not in valid_log_levels:
            raise ValueError(
                f"log_level must be one of {valid_log_levels}, got '{self.log_level}'"
            )


def get_default_config() -> Config:
    """Get default configuration with sample devices.
    
    Returns zero-config default suitable for initial testing:
    - 3 sample devices (mix of power-only and dimmable)
    - Default network settings (host=0.0.0.0, port=23, http_port=8080)
    - No scenarios (can be added via config file)
    - INFO log level
    
    Returns:
        Config: Default configuration
    """
    devices = [
        Device(
            uuid="11111111-1111-4111-8111-111111111111",
            name="Living Room Main",
            capabilities=["power", "dim"],
            state=DeviceState(power=False, dim=0)
        ),
        Device(
            uuid="22222222-2222-4222-8222-222222222222",
            name="Kitchen Overhead",
            capabilities=["power", "dim"],
            state=DeviceState(power=False, dim=0)
        ),
        Device(
            uuid="33333333-3333-4333-8333-333333333333",
            name="Hallway",
            capabilities=["power"],
            state=DeviceState(power=False, dim=None)
        ),
    ]
    
    return Config(
        devices=devices,
        network=NetworkConfig(),
        scenarios=[],
        log_level="INFO"
    )


def load_config(config_path: Path) -> Config:
    """Load and validate configuration from JSON file.
    
    Performs three stages of validation:
    1. JSON parsing (syntax)
    2. JSON Schema validation (structure)
    3. Semantic validation (business rules)
    
    Args:
        config_path: Path to JSON configuration file
        
    Returns:
        Config: Validated configuration object
        
    Exits:
        With status code 1 on any validation error, printing:
        - Exact field path where error occurred (FR-043)
        - Clear description of what's wrong
        - How to fix it
        
    Example error format:
        ERROR: Config validation failed at 'devices[2].state.dim': 
        150 is greater than the maximum of 100
    """
    # Stage 1: Load JSON
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            raw_config = json.load(f)
    except FileNotFoundError:
        print(f"ERROR: Configuration file not found: {config_path}", file=sys.stderr)
        print(f"  Create a config file or omit --config to use defaults", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON in {config_path}:", file=sys.stderr)
        print(f"  Line {e.lineno}, column {e.colno}: {e.msg}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: Failed to read {config_path}: {e}", file=sys.stderr)
        sys.exit(1)
    
    # Stage 2: JSON Schema validation
    schema_path = Path(__file__).parent.parent / "specs" / "001-deako-hub-simulator" / "contracts" / "config.schema.json"
    try:
        with open(schema_path, 'r', encoding='utf-8') as f:
            schema = json.load(f)
    except Exception as e:
        print(f"ERROR: Failed to load config schema: {e}", file=sys.stderr)
        print(f"  Schema file: {schema_path}", file=sys.stderr)
        sys.exit(1)
    
    try:
        jsonschema.validate(raw_config, schema)
    except ValidationError as e:
        # Format JSON path for user-friendly error message
        field_path = _format_json_path(e.absolute_path)
        print(f"ERROR: Config validation failed at '{field_path}':", file=sys.stderr)
        print(f"  {e.message}", file=sys.stderr)
        if e.context:
            print(f"  Additional errors:", file=sys.stderr)
            for ctx_error in e.context:
                ctx_path = _format_json_path(ctx_error.absolute_path)
                print(f"    - {ctx_path}: {ctx_error.message}", file=sys.stderr)
        sys.exit(1)
    
    # Stage 3: Semantic validation
    errors = _validate_semantic_rules(raw_config)
    if errors:
        print("ERROR: Config validation failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        sys.exit(1)
    
    # Convert to Config object
    try:
        return _config_from_dict(raw_config)
    except Exception as e:
        print(f"ERROR: Failed to create configuration: {e}", file=sys.stderr)
        sys.exit(1)


def _format_json_path(path: list) -> str:
    """Format JSON path for error messages.
    
    Examples:
        [] -> "$"
        ["devices", 0, "uuid"] -> "$.devices[0].uuid"
        ["network", "port"] -> "$.network.port"
    """
    if not path:
        return "$"
    
    result = "$"
    for element in path:
        if isinstance(element, int):
            result += f"[{element}]"
        else:
            result += f".{element}"
    return result


def _validate_semantic_rules(config: dict) -> list[str]:
    """Validate business rules not covered by JSON Schema.
    
    Rules:
    - Device UUIDs must be unique
    - Dim capability requires power capability (checked by Device model)
    - Scenario device UUIDs must reference existing devices
    - Scenario names must be unique
    - Network ports must not conflict
    
    Args:
        config: Raw configuration dictionary
        
    Returns:
        List of error messages (empty if valid)
    """
    errors = []
    
    # Check device UUID uniqueness
    device_uuids = [d['uuid'] for d in config.get('devices', [])]
    duplicate_uuids = {uuid for uuid in device_uuids if device_uuids.count(uuid) > 1}
    if duplicate_uuids:
        errors.append(
            f"Duplicate device UUIDs: {', '.join(sorted(duplicate_uuids))}"
        )
    
    # Check scenario name uniqueness
    if 'scenarios' in config:
        scenario_names = [s['name'] for s in config['scenarios']]
        duplicate_names = {name for name in scenario_names if scenario_names.count(name) > 1}
        if duplicate_names:
            errors.append(
                f"Duplicate scenario names: {', '.join(sorted(duplicate_names))}"
            )
        
        # Check scenario device references
        for scenario in config['scenarios']:
            scenario_name = scenario['name']
            for uuid in scenario.get('device_states', {}).keys():
                if uuid not in device_uuids:
                    errors.append(
                        f"Scenario '{scenario_name}' references unknown device UUID: {uuid}"
                    )
    
    return errors


def _config_from_dict(config_dict: dict) -> Config:
    """Convert validated dictionary to Config object.
    
    Args:
        config_dict: Validated configuration dictionary
        
    Returns:
        Config: Configuration object with all models instantiated
    """
    # Parse devices
    devices = []
    for device_dict in config_dict['devices']:
        state_dict = device_dict['state']
        state = DeviceState(
            power=state_dict['power'],
            dim=state_dict.get('dim')
        )
        device = Device(
            uuid=device_dict['uuid'],
            name=device_dict['name'],
            capabilities=device_dict['capabilities'],
            state=state
        )
        devices.append(device)
    
    # Parse network config
    network_dict = config_dict.get('network', {})
    network = NetworkConfig(
        host=network_dict.get('host', '0.0.0.0'),
        port=network_dict.get('port', 23),
        http_port=network_dict.get('http_port', 8080),
        mdns_name=network_dict.get('mdns_name', 'local-integration')
    )
    
    # Parse scenarios
    scenarios = []
    for scenario_dict in config_dict.get('scenarios', []):
        device_states = {}
        for uuid, state_dict in scenario_dict.get('device_states', {}).items():
            device_states[uuid] = DeviceState(
                power=state_dict['power'],
                dim=state_dict.get('dim')
            )
        scenario = Scenario(
            name=scenario_dict['name'],
            description=scenario_dict.get('description', ''),
            device_states=device_states
        )
        scenarios.append(scenario)
    
    return Config(
        devices=devices,
        network=network,
        scenarios=scenarios,
        log_level=config_dict.get('log_level', 'INFO')
    )

