"""Prove the vendored pydeako deviations, against stubs and against the simulator.

Every check below maps to an outcome in the register recorded on wayfinder #8,
and exists so that "do I still have everything I fought for?" is answerable by
running something rather than by reading the diff.

Two halves, because they buy different things:

* ``--offline`` drives the vendored library against stubs. It exercises the
  changed branches directly -- including a short enumeration, which no
  simulator API can produce, because the hub cannot be told to promise N
  devices and deliver fewer.
* the live half drives the vendored library over real sockets against the
  in-process simulator, including a forcibly dropped connection, which is the
  only way to show that state is resynced after the watchdog rebuilds.

Run the live half under WSL/Linux, not Windows: pydeako's
``_SocketConnection.connect_socket`` passes the port to ``sock_connect`` as a
*str*. getaddrinfo tolerates that on POSIX; on Windows it raises and no
connection is ever made. That is true of stock 0.3.1 and 0.6.0 alike, and is
left alone here because the house runs Home Assistant on Linux.

Usage:
    python vendored_deviation_checks.py --offline
    python vendored_deviation_checks.py
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

# Import the vendored copy, never an installed pydeako. Putting the integration
# directory on the path rather than the repo root avoids dragging in
# custom_components.deako, which imports Home Assistant.
sys.path.insert(0, str(REPO_ROOT / "custom_components" / "deako"))
sys.path.insert(0, str(REPO_ROOT))

import pydeako  # noqa: E402
from pydeako.deako import _deako as deako_module  # noqa: E402
from pydeako.deako import Deako, FindDevicesError  # noqa: E402
from pydeako.deako._manager import _Manager  # noqa: E402
from pydeako.models import ResponseType, device_ping_request  # noqa: E402

VENDORED_ROOT = REPO_ROOT / "custom_components" / "deako" / "pydeako"
if Path(pydeako.__file__).resolve().parent != VENDORED_ROOT.resolve():
    raise SystemExit(
        f"refusing to run: imported {pydeako.__file__}, expected the vendored "
        f"copy under {VENDORED_ROOT}"
    )

DIMMABLE_UUID = "11111111-1111-4111-8111-111111111111"
NON_DIMMABLE_UUID = "33333333-3333-4333-8333-333333333333"

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if detail else ""))
    return ok


def summarize() -> int:
    print("\n" + "=" * 68)
    failed = [n for n, ok, _ in results if not ok]
    print(f"{len(results) - len(failed)}/{len(results)} passed")
    if failed:
        print("FAILED: " + "; ".join(failed))
    print("=" * 68)
    return 1 if failed else 0


# --------------------------------------------------------------------------
# Offline checks: the changed branches, driven directly.
# --------------------------------------------------------------------------


class _StubManager:
    """Stands in for _Manager so Deako can be driven without a socket."""

    def __init__(self, send_ok: bool = True) -> None:
        self.device_list_requests = 0
        self.send_ok = send_ok
        self.connected = False

    async def send_get_device_list(self) -> bool:
        self.device_list_requests += 1
        return self.send_ok

    def is_connected(self) -> bool:
        return self.connected


def _stub_deako(send_ok: bool = True) -> tuple[Deako, _StubManager]:
    deako = Deako(lambda: None)
    manager = _StubManager(send_ok=send_ok)
    deako.connection_manager = manager  # type: ignore[assignment]
    return deako, manager


async def offline_checks() -> None:
    # -- O9: zero brightness -------------------------------------------------
    deako, _ = _stub_deako()
    deako.record_device("Dimmer", DIMMABLE_UUID, True, True, 80)
    deako.update_state(DIMMABLE_UUID, True, 0)
    dim = deako.get_state(DIMMABLE_UUID)["dim"]
    check(
        "O9 explicit dim=0 is recorded as 0, not silently preserved",
        dim == 0,
        f"dim={dim!r} (stock `dim or old_dim` would leave 80)",
    )

    deako.record_device("Dimmer", DIMMABLE_UUID, True, True, 80)
    deako.update_state(DIMMABLE_UUID, False)
    dim = deako.get_state(DIMMABLE_UUID)["dim"]
    check(
        "O9 an omitted dim still preserves the previous brightness",
        dim == 80,
        f"dim={dim!r} (dimmables do not send dim on plain on/off)",
    )

    # -- O7a: record_device notifies ----------------------------------------
    deako, _ = _stub_deako()
    deako.record_device("Dimmer", DIMMABLE_UUID, True, True, 80)
    fired = []
    deako.set_state_callback(DIMMABLE_UUID, lambda: fired.append(1))
    deako.record_device("Dimmer", DIMMABLE_UUID, True, False, 10)
    check(
        "O7 record_device() notifies listeners",
        len(fired) == 1,
        f"callback fired {len(fired)}x (stock updates the cache silently)",
    )

    # -- O7b: resync re-requests the device list ----------------------------
    deako, manager = _stub_deako()
    deako.record_device("Dimmer", DIMMABLE_UUID, True, True, 80)
    deako.expected_devices = 1
    await deako.resync_devices()
    check(
        "O7 resync_devices() re-requests the list even when the cache is full",
        manager.device_list_requests == 1,
        f"device list requests={manager.device_list_requests} "
        "(find_devices() would have fallen through both wait loops)",
    )

    deako, manager = _stub_deako()
    check(
        "O7 Deako wires resync_devices() into the manager's on_connect",
        Deako(lambda: None).connection_manager.on_connect is not None,
        "so it fires on reconnects, not just the first connect",
    )

    # -- O1: enumeration window ---------------------------------------------
    check(
        "O1 the enumeration window is a named constant, not 2s per device",
        hasattr(deako_module, "DEVICE_FOUND_WINDOW_S")
        and not hasattr(deako_module, "DEVICE_FOUND_TIME_FACTOR_S"),
        f"DEVICE_FOUND_WINDOW_S={getattr(deako_module, 'DEVICE_FOUND_WINDOW_S', None)}s",
    )

    original_window = deako_module.DEVICE_FOUND_WINDOW_S
    deako_module.DEVICE_FOUND_WINDOW_S = 2
    try:
        deako, manager = _stub_deako()
        deako.expected_devices = 3
        deako.record_device("Only one", DIMMABLE_UUID, True, True, 80)
        try:
            await deako.find_devices()
            raised = None
        except FindDevicesError as exc:
            raised = exc
        check(
            "O1 a short enumeration proceeds instead of failing setup",
            raised is None and len(deako.get_devices()) == 1,
            f"raised={raised!r}, devices={len(deako.get_devices())} of 3 "
            "(stock raises FindDevicesError, leaving the house with no lights)",
        )
    finally:
        deako_module.DEVICE_FOUND_WINDOW_S = original_window

    # A hub that never answers the device list at all is still an error.
    deako, manager = _stub_deako()
    try:
        await deako.find_devices(timeout=1)
        raised = None
    except FindDevicesError as exc:
        raised = exc
    check(
        "O1 a hub that never answers at all still raises",
        raised is not None,
        f"raised={raised!r} (silence is not a shortfall)",
    )

    # -- O4: pong matching ---------------------------------------------------
    manager = _Manager(lambda: None, lambda _json: None)
    ping = device_ping_request(source="test")
    manager.pending_ping_id = ping["transactionId"]
    manager.pong_received = False
    manager.incoming_json({"type": ResponseType.PONG, "transactionId": "a-stale-ping"})
    stale_rejected = manager.pong_received is False
    manager.incoming_json(
        {"type": ResponseType.PONG, "transactionId": ping["transactionId"]}
    )
    matching_accepted = manager.pong_received is True
    check(
        "O4 a pong answering a previous ping does not satisfy this window",
        stale_rejected and matching_accepted,
        f"stale rejected={stale_rejected}, matching accepted={matching_accepted}",
    )

    manager = _Manager(lambda: None, lambda _json: None)
    manager.pending_ping_id = "some-ping"
    manager.pong_received = False
    manager.incoming_json({"type": ResponseType.PONG})
    check(
        "O4 a pong with no transaction id still counts (stock behaviour)",
        manager.pong_received is True,
        "no capture proves the real firmware echoes transactionId, so the "
        "fallback must never be worse than stock",
    )

    # -- O5: connection health ----------------------------------------------
    deako, manager = _stub_deako()
    manager.connected = False
    down = deako.is_connected()
    manager.connected = True
    up = deako.is_connected()
    check(
        "O5 Deako exposes an honest connection-state accessor",
        down is False and up is True,
        f"reported {down} when down and {up} when up",
    )


# --------------------------------------------------------------------------
# Live checks: real sockets against the in-process simulator.
# --------------------------------------------------------------------------


async def _wait_until(predicate, timeout: float = 20.0, interval: float = 0.5) -> bool:
    """Poll until predicate holds. Hub EVENTs land ~2s after the acknowledgment."""
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return predicate()


async def live_checks(port: int, http_port: int) -> None:
    from deako_simulator import server as server_module
    from deako_simulator.config import Config, NetworkConfig
    from deako_simulator.models import Device, DeviceState
    from deako_simulator.protocol import create_event
    from deako_simulator.quirks import QuirkManager
    from deako_simulator.server import DeakoSimulator
    from deako_simulator.state import SimulatorState

    async def _no_mdns(*_args, **_kwargs):
        """The real house is on this LAN. Advertise nothing."""
        return None, []

    server_module.register_mdns = _no_mdns

    devices = [
        Device(
            uuid=DIMMABLE_UUID,
            name="Deviation Test Dimmer",
            capabilities=["power", "dim"],
            state=DeviceState(power=True, dim=80),
        ),
        Device(
            uuid=NON_DIMMABLE_UUID,
            name="Deviation Test Switch",
            capabilities=["power"],
            state=DeviceState(power=False, dim=None),
        ),
    ]
    config = Config(
        devices=devices,
        network=NetworkConfig(host="127.0.0.1", port=port, http_port=http_port),
        scenarios=[],
        log_level="WARNING",
    )
    quirks = QuirkManager()
    simulator = DeakoSimulator(SimulatorState(config.devices), config, quirks)
    await simulator.start()

    async def hub_originated_change(uuid: str, **new_state) -> None:
        """Change state the way a wall press does: mutate, then push an EVENT.

        Mirrors the simulator's own POST /api/devices/{uuid}/state handler.
        Updating the state without broadcasting would change nothing the client
        can see, since it is never asked.
        """
        device = simulator.state.update_device_state(uuid, **new_state)
        await simulator.state.broadcast_event(
            create_event(
                device_uuid=device.uuid,
                state={"power": device.state.power, "dim": device.state.dim},
                timestamp=int(time.time() * 1000),
            )
        )

    async def get_address() -> tuple[str, str]:
        return f"127.0.0.1:{port}", "simulator"

    client = Deako(get_address)
    try:
        await asyncio.wait_for(client.connect(), timeout=15)
        check("live connect() against the simulator", client.is_connected() is True)

        await asyncio.wait_for(client.find_devices(), timeout=30)
        found = client.get_devices()
        check(
            "live find_devices() enumerates every device",
            len(found) == 2,
            f"count={len(found)} names={sorted(d['name'] for d in found.values())}",
        )

        updates: list[str] = []
        for uuid in found:
            client.set_state_callback(uuid, lambda u=uuid: updates.append(u))

        # -- O9 over the wire: drive brightness to zero and read it back.
        #    0.6.0 has no optimistic local echo (_Request.complete_callback has
        #    no call site), so the cache only moves when the hub's EVENT lands.
        await client.control_device(DIMMABLE_UUID, True, 0)
        await _wait_until(lambda: client.get_state(DIMMABLE_UUID)["dim"] == 0)
        dim = client.get_state(DIMMABLE_UUID)["dim"]
        check(
            "O9 live: a requested dim=0 reports 0, not the previous brightness",
            dim == 0,
            f"dim={dim!r} (0.6.0 stock reports 80 here, i.e. 204 in Home Assistant)",
        )

        # -- O9 case 6: the one that actually bites in the house. A wall press
        #    or the Deako app takes the light to 0% with no client command at
        #    all, and the EVENT path is the only writer of cached state.
        await client.control_device(DIMMABLE_UUID, True, 60)
        await _wait_until(lambda: client.get_state(DIMMABLE_UUID)["dim"] == 60)
        await hub_originated_change(DIMMABLE_UUID, power=True, dim=0)
        await _wait_until(lambda: client.get_state(DIMMABLE_UUID)["dim"] == 0)
        dim = client.get_state(DIMMABLE_UUID)["dim"]
        check(
            "O9 live: a hub-originated dim=0 is not discarded",
            dim == 0,
            f"dim={dim!r} after an out-of-band change to 0%",
        )

        # -- O5 + O7 over the wire: drop the connection underneath the client,
        #    change state while it is down, and require that reconnecting
        #    corrects the cache with nobody calling find_devices().
        await client.control_device(DIMMABLE_UUID, True, 40)
        await _wait_until(lambda: client.get_state(DIMMABLE_UUID)["dim"] == 40)

        closed = await quirks.simulate_connection_failure()
        check("live: simulator forcibly dropped the connection", closed is True)

        # O4/O5: the close must be noticed at all. Stock spins on the EOF and
        # starves the event loop, so nothing downstream ever gets to run.
        noticed = await _wait_until(lambda: not client.is_connected(), timeout=15)
        check(
            "O4 live: a hub-side close is detected instead of spinning on EOF",
            noticed,
            "stock keeps reading b'' without yielding, hanging the event loop",
        )

        simulator.state.update_device_state(DIMMABLE_UUID, power=False)

        updates.clear()
        _LOGGER_NOTE = (
            "the watchdog pings every 10s and only drops the connection after a "
            "missed pong, so a full recovery takes ~20-30s"
        )
        deadline = asyncio.get_running_loop().time() + 75
        recovered = False
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(1)
            if client.is_connected() and client.get_state(DIMMABLE_UUID)["power"] is False:
                recovered = True
                break

        state = client.get_state(DIMMABLE_UUID)
        check(
            "O7 live: state changed during an outage is corrected on reconnect",
            recovered,
            f"cached state={state}, reconnected={client.is_connected()}; {_LOGGER_NOTE}",
        )
        check(
            "O7 live: the resync notified listeners rather than updating silently",
            len(updates) > 0,
            f"{len(updates)} callback(s) fired after reconnect",
        )

        await client.disconnect()
        await asyncio.sleep(1)
        check(
            "O5 live: is_connected() reports false after disconnect",
            client.is_connected() is False,
            "stock has no accessor at all, and find_devices() would still "
            "report success here",
        )
    finally:
        try:
            await client.disconnect()
        except Exception:  # pylint: disable=broad-exception-caught
            pass
        await simulator.shutdown()


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="skip the simulator half")
    parser.add_argument("--port", type=int, default=8023)
    parser.add_argument("--http-port", type=int, dest="http_port", default=8080)
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")

    print(f"vendored library: {Path(pydeako.__file__).resolve().parent}\n")
    print("-- offline checks --")
    await offline_checks()

    if not args.offline:
        print("\n-- live checks against the simulator --")
        await live_checks(args.port, args.http_port)

    return summarize()


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(0)
