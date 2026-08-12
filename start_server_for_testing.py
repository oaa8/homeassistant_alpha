"""Temporary script to start server for T052 validation."""
import asyncio
import logging
from deako_simulator.config import get_default_config
from deako_simulator.state import SimulatorState
from deako_simulator.server import DeakoSimulator
from deako_simulator.logging_config import setup_logging

async def main():
    # Setup logging
    setup_logging("INFO")
    
    # Get default config
    config = get_default_config()
    
    # Create state with default devices
    state = SimulatorState(config.devices)
    
    # Create and start simulator
    simulator = DeakoSimulator(state, config)
    
    print("Starting Deako Simulator for T052 validation...")
    print(f"Telnet server will start on {config.network.host}:{config.network.port}")
    print(f"HTTP API server will start on {config.network.host}:{config.network.http_port}")
    print()
    print("Press Ctrl+C to stop")
    print()
    
    await simulator.start()
    await simulator.run_until_shutdown()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutdown complete")
