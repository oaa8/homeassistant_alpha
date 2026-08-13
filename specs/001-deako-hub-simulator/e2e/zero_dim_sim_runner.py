"""Loopback-only simulator runner for the zero-dim regression experiment.

Purpose: start the Deako hub simulator for research issue
oaa8/deako-house-wayfinder#12 ("Does 0.6.0 break setting zero brightness?")
with two deliberate deviations from `deako-simulator` (the normal CLI):

1. mDNS registration is disabled. The real house is on this LAN and a real
   Home Assistant is running on it. Advertising `_deako._tcp` from a dev box
   would invite the live integration to discover the simulator. The experiment
   only needs a TCP endpoint, so the advertisement is suppressed outright.
2. Both servers bind 127.0.0.1 only, so nothing on the LAN can reach it.

Usage:
    python zero_dim_sim_runner.py --port 8023 --http-port 8080
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from deako_simulator import server as server_module
from deako_simulator.config import Config, NetworkConfig
from deako_simulator.models import Device, DeviceState
from deako_simulator.quirks import QuirkManager
from deako_simulator.server import DeakoSimulator
from deako_simulator.state import SimulatorState

# The device under test starts ON at 80% so that "dim was silently preserved"
# is visually distinguishable from "dim was correctly set to 0".
DIMMABLE_UUID = "11111111-1111-4111-8111-111111111111"
NON_DIMMABLE_UUID = "33333333-3333-4333-8333-333333333333"


async def _no_mdns(*_args, **_kwargs):
    """Stand-in for register_mdns that publishes nothing. See module docstring."""
    return None, []


def build_config(port: int, http_port: int) -> Config:
    devices = [
        Device(
            uuid=DIMMABLE_UUID,
            name="Zero Dim Test Dimmer",
            capabilities=["power", "dim"],
            state=DeviceState(power=True, dim=80),
        ),
        Device(
            uuid=NON_DIMMABLE_UUID,
            name="Zero Dim Test Switch",
            capabilities=["power"],
            state=DeviceState(power=False, dim=None),
        ),
    ]
    return Config(
        devices=devices,
        network=NetworkConfig(host="127.0.0.1", port=port, http_port=http_port),
        scenarios=[],
        log_level="INFO",
    )


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8023)
    parser.add_argument("--http-port", type=int, dest="http_port", default=8080)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    server_module.register_mdns = _no_mdns

    config = build_config(args.port, args.http_port)
    simulator = DeakoSimulator(SimulatorState(config.devices), config, QuirkManager())
    await simulator.start()
    print(f"READY telnet=127.0.0.1:{args.port} http=127.0.0.1:{args.http_port}", flush=True)
    try:
        await simulator._shutdown_event.wait()
    finally:
        await simulator.shutdown()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(0)
