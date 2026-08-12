"""
Command-line interface for Deako Hub Simulator.

Author: GitHub Copilot
Created: 2025-10-26
Last Modified: 2026-08-11
Purpose: Entry point for deako-simulator command with argument parsing and lifecycle management
Assumptions:
    - Configuration can come from file, CLI args, or defaults
    - Signal handling required for graceful shutdown (SIGINT/SIGTERM)
    - Precedence: CLI > env vars > config file > defaults
Related Research: research.md (decision 1: asyncio architecture, decision 3: mDNS lifecycle)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from argparse import Namespace

    from deako_simulator.config import Config
    from deako_simulator.server import DeakoSimulator

logger = logging.getLogger(__name__)


def validate_port(value: str) -> int:
    """Validate port number is in valid range (1-65535).
    
    Args:
        value: Port number as string from command line
        
    Returns:
        int: Validated port number
        
    Raises:
        argparse.ArgumentTypeError: If port is not in valid range
    """
    try:
        port = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"port must be an integer, got: {value}")
    
    if port < 1 or port > 65535:
        raise argparse.ArgumentTypeError(f"port must be between 1 and 65535, got: {port}")
    
    return port


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Deako Hub Simulator - Test facility for Home Assistant integration development",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Start with default configuration (3 sample devices, localhost)
  deako-simulator

  # Start with custom configuration file
  deako-simulator my-config.json

  # Override network settings
  deako-simulator --port 2323 --bind-ip 0.0.0.0 --http-port 8888

  # Enable debug logging
  deako-simulator --log-level DEBUG

  # Require mDNS registration (fail if mDNS unavailable)
  deako-simulator --require-mdns

For detailed usage, see: specs/001-deako-hub-simulator/quickstart.md
        """
    )
    
    parser.add_argument(
        "config",
        nargs="?",
        type=Path,
        default=None,
        help="Path to configuration JSON file (default: use built-in defaults)"
    )
    
    parser.add_argument(
        "--port",
        type=validate_port,
        default=None,
        help="Telnet server port (default: 23, overrides config file)"
    )
    
    parser.add_argument(
        "--bind-ip",
        type=str,
        default=None,
        dest="bind_ip",
        help="Bind address (default: 0.0.0.0, overrides config file)"
    )
    
    parser.add_argument(
        "--http-port",
        type=validate_port,
        default=None,
        dest="http_port",
        help="HTTP API port (default: 8080, overrides config file)"
    )
    
    parser.add_argument(
        "--log-level",
        type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default=None,
        dest="log_level",
        help="Log level (default: INFO, overrides config file)"
    )
    
    parser.add_argument(
        "--require-mdns",
        action="store_true",
        dest="require_mdns",
        help="Fail if mDNS registration fails (default: warn and continue)"
    )
    
    return parser.parse_args()


def main() -> int:
    """Main entry point for CLI.
    
    Loads configuration with precedence chain (CLI > env > config > defaults per FR-067),
    sets up logging, creates simulator state, starts servers, and handles graceful shutdown.
    
    Returns:
        int: Exit code (0 for success, non-zero for errors)
    """
    args = parse_args()
    
    # Step 1: Load configuration with precedence chain (CLI > env > config > defaults)
    try:
        config = _load_config_with_precedence(args)
    except Exception as e:
        print(f"ERROR: Failed to load configuration: {e}", file=sys.stderr)
        return 1
    
    # Step 2: Setup logging
    from deako_simulator.logging_config import setup_logging
    setup_logging(config.log_level)
    logger.info("Deako Hub Simulator v0.1.0")
    
    # Step 3: Create simulator state from config devices
    from deako_simulator.state import SimulatorState
    from deako_simulator.quirks import QuirkManager
    
    state = SimulatorState(config.devices)
    quirk_manager = QuirkManager()
    
    # Step 4: Create DeakoSimulator and start servers
    from deako_simulator.server import DeakoSimulator
    
    simulator = DeakoSimulator(state, config, quirk_manager)
    
    # Step 5: Run asyncio event loop with graceful shutdown
    try:
        asyncio.run(_run_simulator(simulator, args.require_mdns))
        return 0
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, shutting down...")
        return 0
    except Exception as e:
        logger.error(f"Simulator failed: {e}", exc_info=True)
        return 1


async def _run_simulator(simulator: "DeakoSimulator", require_mdns: bool) -> None:
    """Run simulator with graceful shutdown handling.
    
    Args:
        simulator: DeakoSimulator instance
        require_mdns: If True, fail if mDNS registration fails
    """
    try:
        # Start simulator (telnet + HTTP servers)
        await simulator.start()
        
        # Check mDNS registration if required
        if require_mdns and simulator.zeroconf is None:
            logger.error("mDNS registration failed and --require-mdns specified")
            await simulator.shutdown()
            raise RuntimeError("mDNS registration required but failed")
        
        # Wait for shutdown signal
        await simulator._shutdown_event.wait()
        
    finally:
        # Graceful shutdown
        await simulator.shutdown()


def _load_config_with_precedence(args: "Namespace") -> "Config":
    """Load configuration with precedence chain: CLI > env > config > defaults.
    
    Per FR-067: Command-line arguments override config file values.
    
    Args:
        args: Parsed command-line arguments
        
    Returns:
        Config: Loaded and merged configuration
        
    Raises:
        ValueError: If configuration is invalid
        FileNotFoundError: If config file specified but not found
    """
    from deako_simulator.config import load_config, get_default_config
    import os
    
    # Step 1: Start with config file or defaults
    if args.config:
        if not args.config.exists():
            raise FileNotFoundError(f"Configuration file not found: {args.config}")
        config = load_config(args.config)
        logger.info(f"Loaded configuration from {args.config}")
    else:
        config = get_default_config()
        logger.info("Using default configuration (no config file specified)")
    
    # Step 2: Apply environment variable overrides
    if "DEAKO_PORT" in os.environ:
        config.network.port = int(os.environ["DEAKO_PORT"])
        logger.info(f"Overriding port from DEAKO_PORT env: {config.network.port}")
    
    if "DEAKO_HTTP_PORT" in os.environ:
        config.network.http_port = int(os.environ["DEAKO_HTTP_PORT"])
        logger.info(f"Overriding http_port from DEAKO_HTTP_PORT env: {config.network.http_port}")
    
    if "DEAKO_BIND_IP" in os.environ:
        config.network.host = os.environ["DEAKO_BIND_IP"]
        logger.info(f"Overriding bind IP from DEAKO_BIND_IP env: {config.network.host}")
    
    if "DEAKO_LOG_LEVEL" in os.environ:
        config.log_level = os.environ["DEAKO_LOG_LEVEL"].upper()
        logger.info(f"Overriding log level from DEAKO_LOG_LEVEL env: {config.log_level}")
    
    # Step 3: Apply CLI argument overrides (highest precedence)
    if args.port is not None:
        config.network.port = args.port
        logger.info(f"Overriding port from CLI: {config.network.port}")
    
    if args.http_port is not None:
        config.network.http_port = args.http_port
        logger.info(f"Overriding http_port from CLI: {config.network.http_port}")
    
    if args.bind_ip is not None:
        config.network.host = args.bind_ip
        logger.info(f"Overriding bind IP from CLI: {config.network.host}")
    
    if args.log_level is not None:
        config.log_level = args.log_level
        logger.info(f"Overriding log level from CLI: {config.log_level}")
    
    return config


if __name__ == "__main__":
    sys.exit(main())
