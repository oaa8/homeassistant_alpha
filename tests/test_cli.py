"""
Tests for CLI argument parsing and configuration precedence.

Author: GitHub Copilot
Created: 2025-10-29
Purpose: Validate CLI implementation per T087

Test Coverage:
    - Argument parsing for all CLI options
    - Configuration precedence chain (CLI > env > config > defaults)
    - --require-mdns flag behavior
    - Invalid argument rejection with helpful messages
    - --help output includes usage examples
    - Environment variable overrides
    - Config file loading vs defaults

Related Tasks: T084-T087 (CLI Implementation)
Related Requirements: FR-067 (Configuration precedence chain)
"""

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deako_simulator.cli import parse_args, _load_config_with_precedence, main
from deako_simulator.config import get_default_config


class TestArgumentParsing:
    """Test CLI argument parsing per T086."""
    
    def test_no_arguments_uses_defaults(self):
        """
        Test: CLI with no arguments uses default configuration.
        
        End-User Scenario: Developer runs `deako-simulator` with no arguments
        and simulator starts with sensible defaults (3 sample devices, localhost).
        
        Validates FR-067: Default configuration when no config file specified.
        """
        with patch('sys.argv', ['deako-simulator']):
            args = parse_args()
        
        assert args.config is None, "Should use defaults when no config file specified"
        assert args.port is None, "Should use default port when not specified"
        assert args.http_port is None, "Should use default HTTP port when not specified"
        assert args.bind_ip is None, "Should use default bind IP when not specified"
        assert args.log_level is None, "Should use default log level when not specified"
        assert args.require_mdns is False, "Should not require mDNS by default"
    
    def test_config_file_argument(self, tmp_path):
        """
        Test: CLI accepts config file path argument.
        
        End-User Scenario: Developer runs `deako-simulator my-config.json`
        and simulator loads devices from custom configuration file.
        """
        config_file = tmp_path / "test-config.json"
        config_file.touch()
        
        with patch('sys.argv', ['deako-simulator', str(config_file)]):
            args = parse_args()
        
        assert args.config == config_file, "Should accept config file path"
    
    def test_port_override(self):
        """
        Test: --port argument overrides default port.
        
        End-User Scenario: Developer runs `deako-simulator --port 2323`
        to avoid port conflicts when port 23 requires sudo.
        
        Validates FR-067: CLI arguments override config file values.
        """
        with patch('sys.argv', ['deako-simulator', '--port', '2323']):
            args = parse_args()
        
        assert args.port == 2323, "Should accept --port argument"
    
    def test_http_port_override(self):
        """
        Test: --http-port argument overrides default HTTP port.
        
        End-User Scenario: Developer runs `deako-simulator --http-port 8888`
        to use different HTTP API port for parallel simulators.
        """
        with patch('sys.argv', ['deako-simulator', '--http-port', '8888']):
            args = parse_args()
        
        assert args.http_port == 8888, "Should accept --http-port argument"
    
    def test_bind_ip_override(self):
        """
        Test: --bind-ip argument overrides default bind address.
        
        End-User Scenario: Developer runs `deako-simulator --bind-ip 127.0.0.1`
        to bind only to localhost for security.
        """
        with patch('sys.argv', ['deako-simulator', '--bind-ip', '127.0.0.1']):
            args = parse_args()
        
        assert args.bind_ip == '127.0.0.1', "Should accept --bind-ip argument"
    
    def test_log_level_debug(self):
        """
        Test: --log-level DEBUG enables verbose logging.
        
        End-User Scenario: Developer debugging integration issues runs
        `deako-simulator --log-level DEBUG` to see all protocol messages.
        """
        with patch('sys.argv', ['deako-simulator', '--log-level', 'DEBUG']):
            args = parse_args()
        
        assert args.log_level == 'DEBUG', "Should accept DEBUG log level"
    
    def test_log_level_info(self):
        """Test: --log-level INFO shows normal operational messages."""
        with patch('sys.argv', ['deako-simulator', '--log-level', 'INFO']):
            args = parse_args()
        
        assert args.log_level == 'INFO', "Should accept INFO log level"
    
    def test_log_level_warning(self):
        """Test: --log-level WARNING shows only warnings and errors."""
        with patch('sys.argv', ['deako-simulator', '--log-level', 'WARNING']):
            args = parse_args()
        
        assert args.log_level == 'WARNING', "Should accept WARNING log level"
    
    def test_log_level_error(self):
        """Test: --log-level ERROR shows only errors."""
        with patch('sys.argv', ['deako-simulator', '--log-level', 'ERROR']):
            args = parse_args()
        
        assert args.log_level == 'ERROR', "Should accept ERROR log level"
    
    def test_require_mdns_flag(self):
        """
        Test: --require-mdns flag causes failure if mDNS unavailable.
        
        End-User Scenario: CI/CD pipeline runs `deako-simulator --require-mdns`
        and test fails early if mDNS service registration fails.
        """
        with patch('sys.argv', ['deako-simulator', '--require-mdns']):
            args = parse_args()
        
        assert args.require_mdns is True, "Should set require_mdns flag"
    
    def test_multiple_arguments_combined(self, tmp_path):
        """
        Test: Multiple CLI arguments work together.
        
        End-User Scenario: Developer runs complex command with multiple overrides:
        `deako-simulator config.json --port 2323 --http-port 8888 --log-level DEBUG --require-mdns`
        """
        config_file = tmp_path / "test.json"
        config_file.touch()
        
        with patch('sys.argv', [
            'deako-simulator', str(config_file),
            '--port', '2323',
            '--http-port', '8888',
            '--bind-ip', '127.0.0.1',
            '--log-level', 'DEBUG',
            '--require-mdns'
        ]):
            args = parse_args()
        
        assert args.config == config_file
        assert args.port == 2323
        assert args.http_port == 8888
        assert args.bind_ip == '127.0.0.1'
        assert args.log_level == 'DEBUG'
        assert args.require_mdns is True
    
    def test_invalid_port_rejected(self):
        """
        Test: Invalid port value causes helpful error message.
        
        End-User Scenario: Developer typos port number `--port abc`
        and gets clear error message about expected integer.
        """
        with patch('sys.argv', ['deako-simulator', '--port', 'invalid']):
            with pytest.raises(SystemExit):
                parse_args()
    
    def test_port_zero_rejected(self):
        """
        Test: Port 0 is rejected with helpful error message.
        
        End-User Scenario: Developer accidentally specifies `--port 0`
        and gets error "port must be between 1 and 65535".
        
        Validates T086: Port range validation (1-65535).
        """
        with patch('sys.argv', ['deako-simulator', '--port', '0']):
            with pytest.raises(SystemExit) as exc_info:
                parse_args()
            assert exc_info.value.code == 2, "Should exit with code 2 on argument error"
    
    def test_port_negative_rejected(self):
        """
        Test: Negative port number is rejected.
        
        End-User Scenario: Developer makes typo `--port -1`
        and gets validation error instead of cryptic network error.
        
        Validates T086: Port range validation (1-65535).
        """
        with patch('sys.argv', ['deako-simulator', '--port', '-1']):
            with pytest.raises(SystemExit) as exc_info:
                parse_args()
            assert exc_info.value.code == 2, "Should exit with code 2 on argument error"
    
    def test_port_too_large_rejected(self):
        """
        Test: Port number > 65535 is rejected.
        
        End-User Scenario: Developer specifies `--port 70000`
        and gets error "port must be between 1 and 65535".
        
        Validates T086: Port range validation (1-65535).
        """
        with patch('sys.argv', ['deako-simulator', '--port', '70000']):
            with pytest.raises(SystemExit) as exc_info:
                parse_args()
            assert exc_info.value.code == 2, "Should exit with code 2 on argument error"
    
    def test_port_boundary_1_accepted(self):
        """
        Test: Port 1 (minimum valid) is accepted.
        
        End-User Scenario: Developer wants to use very low port number
        and port 1 is the minimum valid TCP port.
        
        Validates T086: Port range validation boundary (1 is valid).
        """
        with patch('sys.argv', ['deako-simulator', '--port', '1']):
            args = parse_args()
        
        assert args.port == 1, "Port 1 should be accepted (minimum valid)"
    
    def test_port_boundary_65535_accepted(self):
        """
        Test: Port 65535 (maximum valid) is accepted.
        
        End-User Scenario: Developer uses high port number to avoid
        privileged port restrictions.
        
        Validates T086: Port range validation boundary (65535 is valid).
        """
        with patch('sys.argv', ['deako-simulator', '--port', '65535']):
            args = parse_args()
        
        assert args.port == 65535, "Port 65535 should be accepted (maximum valid)"
    
    def test_http_port_zero_rejected(self):
        """
        Test: HTTP port 0 is rejected with helpful error message.
        
        End-User Scenario: Developer accidentally specifies `--http-port 0`
        and gets error "port must be between 1 and 65535".
        
        Validates T086: HTTP port range validation (1-65535).
        """
        with patch('sys.argv', ['deako-simulator', '--http-port', '0']):
            with pytest.raises(SystemExit) as exc_info:
                parse_args()
            assert exc_info.value.code == 2, "Should exit with code 2 on argument error"
    
    def test_http_port_negative_rejected(self):
        """
        Test: Negative HTTP port number is rejected.
        
        Validates T086: HTTP port range validation (1-65535).
        """
        with patch('sys.argv', ['deako-simulator', '--http-port', '-1']):
            with pytest.raises(SystemExit) as exc_info:
                parse_args()
            assert exc_info.value.code == 2, "Should exit with code 2 on argument error"
    
    def test_http_port_too_large_rejected(self):
        """
        Test: HTTP port number > 65535 is rejected.
        
        Validates T086: HTTP port range validation (1-65535).
        """
        with patch('sys.argv', ['deako-simulator', '--http-port', '70000']):
            with pytest.raises(SystemExit) as exc_info:
                parse_args()
            assert exc_info.value.code == 2, "Should exit with code 2 on argument error"
    
    def test_http_port_boundary_1_accepted(self):
        """
        Test: HTTP port 1 (minimum valid) is accepted.
        
        Validates T086: HTTP port range validation boundary (1 is valid).
        """
        with patch('sys.argv', ['deako-simulator', '--http-port', '1']):
            args = parse_args()
        
        assert args.http_port == 1, "HTTP port 1 should be accepted (minimum valid)"
    
    def test_http_port_boundary_65535_accepted(self):
        """
        Test: HTTP port 65535 (maximum valid) is accepted.
        
        Validates T086: HTTP port range validation boundary (65535 is valid).
        """
        with patch('sys.argv', ['deako-simulator', '--http-port', '65535']):
            args = parse_args()
        
        assert args.http_port == 65535, "HTTP port 65535 should be accepted (maximum valid)"
    
    def test_invalid_log_level_rejected(self):
        """
        Test: Invalid log level causes helpful error message.
        
        End-User Scenario: Developer typos log level `--log-level TRACE`
        and gets error showing valid choices: DEBUG, INFO, WARNING, ERROR.
        """
        with patch('sys.argv', ['deako-simulator', '--log-level', 'INVALID']):
            with pytest.raises(SystemExit):
                parse_args()
    
    def test_help_shows_examples(self, capsys):
        """
        Test: --help output includes usage examples.
        
        End-User Scenario: Developer runs `deako-simulator --help`
        and sees practical examples of common usage patterns.
        
        Validates T086: --help output requirement.
        """
        with patch('sys.argv', ['deako-simulator', '--help']):
            with pytest.raises(SystemExit) as exc_info:
                parse_args()
        
        # Help should exit with code 0
        assert exc_info.value.code == 0, "--help should exit with success code"
        
        # Capture help output
        captured = capsys.readouterr()
        help_text = captured.out
        
        # Verify examples present
        assert "Examples:" in help_text, "Help should include examples section"
        assert "deako-simulator" in help_text, "Help should show command name"
        assert "--port" in help_text, "Help should document --port option"
        assert "--log-level" in help_text, "Help should document --log-level option"


class TestConfigurationPrecedence:
    """Test configuration precedence chain: CLI > env > config > defaults per FR-067."""
    
    def test_defaults_when_no_config(self):
        """
        Test: Default configuration used when no config file specified.
        
        End-User Scenario: Developer runs `deako-simulator` and gets
        3 sample devices (mix of power-only and dimmable) without any config file.
        
        Validates FR-067: Default fallback behavior.
        """
        with patch('sys.argv', ['deako-simulator']):
            args = parse_args()
        
        config = _load_config_with_precedence(args)
        
        default_config = get_default_config()
        assert config.network.port == default_config.network.port
        assert config.network.http_port == default_config.network.http_port
        assert config.network.host == default_config.network.host
        assert len(config.devices) == len(default_config.devices)
    
    def test_config_file_overrides_defaults(self, tmp_path):
        """
        Test: Config file values override defaults.
        
        End-User Scenario: Developer creates custom-config.json with port: 2323
        and simulator uses port 2323 instead of default 23.
        """
        config_file = tmp_path / "test-config.json"
        config_data = {
            "network": {
                "host": "127.0.0.1",
                "port": 2323,
                "http_port": 8888,
                "mdns_name": "test-simulator"
            },
            "devices": [
                {
                    "uuid": "a1b2c3d4-e5f6-4789-a012-b3c4d5e6f789",
                    "name": "Test Device",
                    "capabilities": ["power"],
                    "state": {"power": False, "dim": None}
                }
            ],
            "log_level": "DEBUG"
        }
        config_file.write_text(__import__('json').dumps(config_data))
        
        with patch('sys.argv', ['deako-simulator', str(config_file)]):
            args = parse_args()
        
        config = _load_config_with_precedence(args)
        
        assert config.network.port == 2323, "Config file should override default port"
        assert config.network.http_port == 8888, "Config file should override default HTTP port"
        assert config.network.host == "127.0.0.1", "Config file should override default host"
        assert len(config.devices) == 1, "Config file should specify devices"
    
    def test_env_vars_override_config_file(self, tmp_path, monkeypatch):
        """
        Test: Environment variables override config file values.
        
        End-User Scenario: Docker container sets DEAKO_PORT=2323 env var,
        overriding port in mounted config file.
        
        Validates FR-067: ENV > config in precedence chain.
        """
        config_file = tmp_path / "test-config.json"
        config_data = {
            "network": {"host": "0.0.0.0", "port": 23, "http_port": 8080},
            "devices": [
                {
                    "uuid": "a1b2c3d4-e5f6-4789-a012-b3c4d5e6f789",
                    "name": "Test Device",
                    "capabilities": ["power"],
                    "state": {"power": False, "dim": None}
                }
            ],
            "log_level": "INFO"
        }
        config_file.write_text(__import__('json').dumps(config_data))
        
        # Set environment variables
        monkeypatch.setenv("DEAKO_PORT", "2323")
        monkeypatch.setenv("DEAKO_HTTP_PORT", "8888")
        monkeypatch.setenv("DEAKO_BIND_IP", "127.0.0.1")
        monkeypatch.setenv("DEAKO_LOG_LEVEL", "DEBUG")
        
        with patch('sys.argv', ['deako-simulator', str(config_file)]):
            args = parse_args()
        
        config = _load_config_with_precedence(args)
        
        assert config.network.port == 2323, "DEAKO_PORT should override config file"
        assert config.network.http_port == 8888, "DEAKO_HTTP_PORT should override config file"
        assert config.network.host == "127.0.0.1", "DEAKO_BIND_IP should override config file"
        assert config.log_level == "DEBUG", "DEAKO_LOG_LEVEL should override config file"
    
    def test_cli_args_override_everything(self, tmp_path, monkeypatch):
        """
        Test: CLI arguments override both config file and environment variables.
        
        End-User Scenario: Developer needs to quickly test different port
        without editing config or env vars: `deako-simulator --port 9999`
        
        Validates FR-067: CLI > ENV > config precedence chain (highest priority).
        """
        config_file = tmp_path / "test-config.json"
        config_data = {
            "network": {"host": "0.0.0.0", "port": 23, "http_port": 8080},
            "devices": [
                {
                    "uuid": "b2c3d4e5-f6a7-4890-b123-c4d5e6f7a890",
                    "name": "Test Device",
                    "capabilities": ["power"],
                    "state": {"power": False, "dim": None}
                }
            ],
            "log_level": "INFO"
        }
        config_file.write_text(__import__('json').dumps(config_data))
        
        # Set environment variables (should be overridden by CLI)
        monkeypatch.setenv("DEAKO_PORT", "2323")
        monkeypatch.setenv("DEAKO_LOG_LEVEL", "WARNING")
        
        with patch('sys.argv', [
            'deako-simulator', str(config_file),
            '--port', '9999',
            '--http-port', '7777',
            '--bind-ip', '192.168.1.100',
            '--log-level', 'DEBUG'
        ]):
            args = parse_args()
        
        config = _load_config_with_precedence(args)
        
        assert config.network.port == 9999, "CLI --port should have highest precedence"
        assert config.network.http_port == 7777, "CLI --http-port should override env and config"
        assert config.network.host == "192.168.1.100", "CLI --bind-ip should override env and config"
        assert config.log_level == "DEBUG", "CLI --log-level should override env and config"
    
    def test_nonexistent_config_file_error(self):
        """
        Test: Missing config file causes clear error message.
        
        End-User Scenario: Developer typos config filename
        `deako-simulator mising-config.json` and gets helpful error.
        """
        with patch('sys.argv', ['deako-simulator', 'nonexistent.json']):
            args = parse_args()
        
        with pytest.raises(FileNotFoundError, match="Configuration file not found"):
            _load_config_with_precedence(args)
    
    def test_invalid_config_file_error(self, tmp_path):
        """
        Test: Invalid JSON in config file causes descriptive error.
        
        End-User Scenario: Developer has syntax error in config.json
        and gets error pointing to exact problem location.
        """
        config_file = tmp_path / "invalid.json"
        config_file.write_text("{ invalid json }")
        
        with patch('sys.argv', ['deako-simulator', str(config_file)]):
            args = parse_args()
        
        # The load_config function calls sys.exit(1) on JSON errors
        # We need to catch SystemExit
        with pytest.raises(SystemExit) as exc_info:
            _load_config_with_precedence(args)
        
        assert exc_info.value.code == 1, "Should exit with code 1 on JSON error"


class TestMainEntryPoint:
    """Test main() entry point and simulator lifecycle."""
    
    def test_main_starts_simulator(self, monkeypatch):
        """
        Test: main() creates and starts simulator successfully.
        
        End-User Scenario: Developer runs `deako-simulator` and simulator
        starts with telnet server on port 23 and HTTP API on port 8080.
        """
        # Helper to close coroutine to avoid "was never awaited" warning
        def close_coroutine(coro):
            coro.close()
            return None
        
        # Mock DeakoSimulator
        with patch('deako_simulator.server.DeakoSimulator') as mock_simulator_class:
            mock_instance = MagicMock()
            mock_instance.zeroconf = MagicMock()  # Simulate successful mDNS
            mock_simulator_class.return_value = mock_instance
            
            # Mock asyncio.run to avoid event loop conflict
            with patch('asyncio.run', side_effect=close_coroutine):
                with patch('sys.argv', ['deako-simulator']):
                    exit_code = main()
        
        assert exit_code == 0, "main() should return 0 on success"
    
    def test_main_handles_keyboard_interrupt(self, monkeypatch):
        """
        Test: Ctrl+C during simulator run triggers graceful shutdown.
        
        End-User Scenario: Developer stops simulator with Ctrl+C and
        simulator shuts down cleanly within 5 seconds per FR-010.
        """
        # Helper to close coroutine before raising exception
        def raise_keyboard_interrupt(coro):
            coro.close()
            raise KeyboardInterrupt()
        
        # Mock asyncio.run to raise KeyboardInterrupt
        with patch('asyncio.run', side_effect=raise_keyboard_interrupt):
            with patch('sys.argv', ['deako-simulator']):
                exit_code = main()
        
        assert exit_code == 0, "Should exit cleanly on KeyboardInterrupt"
    
    def test_main_handles_config_error(self, tmp_path):
        """
        Test: Invalid configuration causes main() to exit with error code.
        
        End-User Scenario: Developer has malformed config.json and gets
        clear error message and non-zero exit code.
        """
        config_file = tmp_path / "invalid.json"
        config_file.write_text("{ invalid }")
        
        with patch('sys.argv', ['deako-simulator', str(config_file)]):
            with pytest.raises(SystemExit) as exc_info:
                main()
        
        assert exc_info.value.code == 1, "Should exit with code 1 on config error"
    
    def test_main_require_mdns_fails_if_no_mdns(self, monkeypatch):
        """
        Test: --require-mdns flag causes failure if mDNS registration fails.
        
        End-User Scenario: CI/CD pipeline runs `deako-simulator --require-mdns`
        and test fails if mDNS service is unavailable in container.
        """
        # Helper to close coroutine before raising exception
        def raise_mdns_error(coro):
            coro.close()
            raise RuntimeError("mDNS registration required but failed")
        
        with patch('deako_simulator.server.DeakoSimulator') as mock_simulator_class:
            mock_instance = MagicMock()
            mock_instance.zeroconf = None  # Simulate mDNS failure
            mock_simulator_class.return_value = mock_instance
            
            # Mock asyncio.run to raise mDNS error
            with patch('asyncio.run', side_effect=raise_mdns_error):
                with patch('sys.argv', ['deako-simulator', '--require-mdns']):
                    exit_code = main()
        
        assert exit_code == 1, "Should fail when --require-mdns set and mDNS fails"


class TestIntegrationScenarios:
    """Integration tests for complete CLI workflows."""
    
    def test_default_startup_workflow(self):
        """
        Test: Complete default startup workflow.
        
        End-User Scenario: New developer runs `deako-simulator` for first time:
        1. No config file needed
        2. Gets 3 sample devices
        3. Telnet server starts on port 23
        4. HTTP API starts on port 8080
        5. mDNS registration attempted
        6. Logs show effective configuration
        """
        with patch('sys.argv', ['deako-simulator']):
            args = parse_args()
            config = _load_config_with_precedence(args)
        
        # Verify defaults loaded
        assert len(config.devices) == 3, "Should have 3 default devices"
        assert config.network.port == 23, "Should use port 23"
        assert config.network.http_port == 8080, "Should use HTTP port 8080"
        assert config.network.host == "0.0.0.0", "Should bind to all interfaces"
        assert config.log_level == "INFO", "Should use INFO log level"
    
    def test_custom_config_workflow(self, tmp_path):
        """
        Test: Custom configuration file workflow.
        
        End-User Scenario: Developer creates custom config with 10 devices,
        runs `deako-simulator my-config.json`, and simulator loads all devices.
        """
        import uuid
        config_file = tmp_path / "custom.json"
        config_data = {
            "network": {"host": "0.0.0.0", "port": 2323, "http_port": 8888},
            "devices": [
                {
                    "uuid": str(uuid.uuid4()),
                    "name": f"Device {i}",
                    "capabilities": ["power", "dim"],
                    "state": {"power": False, "dim": 50}
                }
                for i in range(10)
            ],
            "log_level": "DEBUG"
        }
        config_file.write_text(__import__('json').dumps(config_data))
        
        with patch('sys.argv', ['deako-simulator', str(config_file)]):
            args = parse_args()
            config = _load_config_with_precedence(args)
        
        assert len(config.devices) == 10, "Should load 10 devices from config"
        assert config.network.port == 2323, "Should use custom port"
        assert config.log_level == "DEBUG", "Should use custom log level"
    
    def test_docker_deployment_workflow(self, tmp_path, monkeypatch):
        """
        Test: Docker container deployment workflow.
        
        End-User Scenario: Docker container with:
        - Config file mounted at /config/simulator.json
        - Environment variables for network settings
        - Simulator adapts to container environment
        """
        config_file = tmp_path / "simulator.json"
        config_data = {
            "network": {"host": "0.0.0.0", "port": 23, "http_port": 8080},
            "devices": [
                {"uuid": "a1b2c3d4-e5f6-4789-a012-b3c4d5e6f789", "name": "Device 1", "capabilities": ["power"], "state": {"power": False, "dim": None}}
            ],
            "log_level": "INFO"
        }
        config_file.write_text(__import__('json').dumps(config_data))
        
        # Simulate Docker environment variables
        monkeypatch.setenv("DEAKO_PORT", "23")
        monkeypatch.setenv("DEAKO_HTTP_PORT", "8080")
        monkeypatch.setenv("DEAKO_BIND_IP", "0.0.0.0")
        monkeypatch.setenv("DEAKO_LOG_LEVEL", "INFO")
        
        with patch('sys.argv', ['deako-simulator', str(config_file)]):
            args = parse_args()
            config = _load_config_with_precedence(args)
        
        assert config.network.host == "0.0.0.0", "Should bind to all interfaces in container"
        assert config.network.port == 23, "Should use standard telnet port"
        assert config.network.http_port == 8080, "Should use standard HTTP port"
