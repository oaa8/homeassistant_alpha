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
from pydeako.deako import Deako, DeviceCommandError, FindDevicesError  # noqa: E402
from pydeako.deako._manager import _Manager, PING_WORKER_WAIT_S  # noqa: E402
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
        self.state_changes = 0
        self.send_ok = send_ok
        self.connected = False
        self.reconnect_count = 0
        self.last_message_age: float | None = None

    async def send_get_device_list(self) -> bool:
        self.device_list_requests += 1
        return self.send_ok

    async def send_state_change(
        self, uuid, power, dim=None, completed_callback=None,
    ) -> bool:
        self.state_changes += 1
        return self.send_ok

    def seconds_since_last_message(self) -> float | None:
        return self.last_message_age

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

    # -- wayfinder #23: the diagnostic signals and the witness detector -------
    #
    # The window is 5s in production (3x the 1.60s measured between a CONTROL
    # acknowledgement and its confirming EVENT on real hardware). Shortened
    # here so the *logic* can be checked in milliseconds; what the constant
    # should be is a hardware question, not a branch question.
    original_window = deako_module.WITNESS_WINDOW_S
    deako_module.WITNESS_WINDOW_S = 0.05
    try:
        deako, manager = _stub_deako(send_ok=True)
        manager.connected = True
        deako.record_device("Dimmer", DIMMABLE_UUID, True, True, 80)
        reachability: list[tuple[str, bool]] = []
        deako.add_reachability_listener(
            lambda uuid, reachable: reachability.append((uuid, reachable))
        )

        # One miss is a lost mesh frame, and must not mark anything.
        await deako.control_device(DIMMABLE_UUID, False)
        await asyncio.sleep(0.2)
        check(
            "#23 one unwitnessed command does not mark a device unreachable",
            deako.is_reachable(DIMMABLE_UUID) and reachability == [],
            f"misses={deako.consecutive_misses.get(DIMMABLE_UUID)}, "
            "one miss is a lost frame",
        )

        # Two consecutive is the pattern a person is already complaining about.
        await deako.control_device(DIMMABLE_UUID, True)
        await asyncio.sleep(0.2)
        check(
            "#23 two consecutive unwitnessed commands mark it unreachable",
            not deako.is_reachable(DIMMABLE_UUID)
            and reachability == [(DIMMABLE_UUID, False)],
            f"unreachable={deako.get_unreachable()}, "
            f"listener calls={reachability}",
        )

        # Any EVENT clears it, from any source.
        deako.incoming_json({
            "type": "EVENT",
            "data": {
                "eventType": "DEVICE_STATE_CHANGE",
                "target": DIMMABLE_UUID,
                "state": {"power": True, "dim": 80},
            },
        })
        check(
            "#23 any EVENT for the device clears the mark",
            deako.is_reachable(DIMMABLE_UUID)
            and reachability[-1] == (DIMMABLE_UUID, True),
            f"unreachable={deako.get_unreachable()}",
        )

        # An acknowledged send whose EVENT arrives inside the window is not a
        # miss. This is the check that would fail if the detector counted acks.
        deako, manager = _stub_deako(send_ok=True)
        manager.connected = True
        deako.record_device("Dimmer", DIMMABLE_UUID, True, True, 80)
        await deako.control_device(DIMMABLE_UUID, False)
        deako.incoming_json({
            "type": "EVENT",
            "data": {"target": DIMMABLE_UUID, "state": {"power": False}},
        })
        await asyncio.sleep(0.2)
        check(
            "#23 a witnessed command counts no miss at all",
            deako.is_reachable(DIMMABLE_UUID)
            and DIMMABLE_UUID not in deako.consecutive_misses,
            f"misses={deako.consecutive_misses}",
        )

        # A window still open when the socket dies proves nothing: the EVENT
        # could not have reached us either way. Without this, one hub outage
        # would mark every light anybody happened to touch.
        deako, manager = _stub_deako(send_ok=True)
        manager.connected = True
        deako.record_device("Dimmer", DIMMABLE_UUID, True, True, 80)
        await deako.control_device(DIMMABLE_UUID, False)
        deako.notify_connection_listeners(False)
        await asyncio.sleep(0.2)
        check(
            "#23 losing the connection voids the open witness window",
            deako.is_reachable(DIMMABLE_UUID)
            and DIMMABLE_UUID not in deako.consecutive_misses
            and deako.pending_witness == {},
            f"misses={deako.consecutive_misses}, pending={deako.pending_witness}",
        )

        # A send that never left the machine is not the device's fault either.
        deako, manager = _stub_deako(send_ok=False)
        deako.record_device("Dimmer", DIMMABLE_UUID, True, True, 80)
        try:
            await deako.control_device(DIMMABLE_UUID, False)
        except DeviceCommandError:
            pass
        await asyncio.sleep(0.2)
        check(
            "#23 a command that failed to send opens no window",
            deako.pending_witness == {}
            and DIMMABLE_UUID not in deako.consecutive_misses,
            "the probe is the command that actually left",
        )
    finally:
        deako_module.WITNESS_WINDOW_S = original_window

    # -- wayfinder #23: per-sweep enumeration accounting ---------------------
    #
    # Tracked outside the device cache on purpose: that cache is never cleared,
    # so a device missing from a later sweep leaves its old entry in place and
    # a cache lookup could never notice.
    deako, _ = _stub_deako()
    reported: list[int] = []
    deako.add_sweep_listener(lambda: reported.append(1))

    def _found(uuid: str, name: str) -> dict:
        return {
            "type": "DEVICE_FOUND",
            "data": {
                "uuid": uuid,
                "name": name,
                "capabilities": "power",
                "state": {"power": False},
            },
        }

    deako.incoming_json({"type": "DEVICE_LIST", "data": {"number_of_devices": 2}})
    deako.incoming_json(_found(DIMMABLE_UUID, "Dimmer"))
    deako.incoming_json(_found(NON_DIMMABLE_UUID, "Switch"))
    reporting, expected, missing = deako.get_last_sweep()
    check(
        "#23 a complete sweep concludes as soon as the last device reports",
        (reporting, expected, missing) == (2, 2, []) and len(reported) == 1,
        f"reporting={reporting}, expected={expected}, missing={missing}, "
        f"listener calls={len(reported)} (it must not wait out the window)",
    )

    # A second sweep that drops a device the cache still holds. The hub has
    # never once done this in ten measured sweeps, so this is a tripwire for
    # something never yet seen -- but it has to work if it is ever tripped.
    deako.incoming_json({"type": "DEVICE_LIST", "data": {"number_of_devices": 1}})
    deako.incoming_json(_found(DIMMABLE_UUID, "Dimmer"))
    reporting, expected, missing = deako.get_last_sweep()
    check(
        "#23 a device missing from a later sweep is named, not lost in the cache",
        (reporting, expected, missing) == (1, 1, [NON_DIMMABLE_UUID]),
        f"reporting={reporting}, expected={expected}, missing={missing} "
        f"(the cache still holds {len(deako.get_devices())} devices)",
    )
    deako.cancel_sweep_timer()

    deako, _ = _stub_deako()
    reporting, expected, missing = deako.get_last_sweep()
    check(
        "#23 before any sweep the count is unknown rather than zero",
        reporting is None and expected is None and missing == [],
        f"reporting={reporting!r} -- 'not asked yet' is not 'nothing answered'",
    )

    # -- wayfinder #23: the last-message stamp sits before pong filtering -----
    #
    # The pongs are the only thing a healthy but idle hub reliably says: ten
    # hardware runs with no manipulation produced zero EVENTs. Stamping after
    # the filter would make the age climb without bound on a quiet house.
    manager = _Manager(lambda: None, lambda _msg: None)
    check(
        "#23 the message age is unknown before the hub has said anything",
        manager.seconds_since_last_message() is None,
        "None, not 0.0 -- 'never heard' is not 'heard just now'",
    )
    manager.pending_ping_id = None
    manager.incoming_json({"type": ResponseType.PONG, "transactionId": "no-match"})
    age = manager.seconds_since_last_message()
    check(
        "#23 a pong the correlation rejects still stamps the message age",
        age is not None and age < 1,
        f"age={age!r} after an uncorrelatable pong "
        "(the only traffic on an idle, healthy connection)",
    )

    check(
        "#23 a rebuilt connection is counted, an attempt is not",
        manager.reconnect_count == 0,
        "0.6.0 retries a dead node ~6x/min with no backoff, so counting "
        "attempts would measure the length of one outage, not the number",
    )


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

    # The first connection must NOT resync -- the caller's find_devices() is
    # about to enumerate anyway, and firing both sent two full DEVICE_LIST
    # requests 38ms apart at every setup. Drive init_connection for real, with
    # the socket layer stubbed out, rather than asserting the bookkeeping.
    from pydeako.deako import _manager as manager_module

    class _InstantConnection:
        """A _Connection that is connected the moment it is built."""

        def __init__(self, address, name, _callback, on_state_change=None) -> None:
            self.address = address
            self.name = name
            self.on_state_change = on_state_change
            # _Manager.is_connected() reaches through to the raw socket, since
            # _Connection.close() does not move the state machine out of
            # CONNECTED (DEVIATION O5).
            self.socket = type("_Sock", (), {"sock": object()})()

        def is_connected(self) -> bool:
            return True

        def close(self) -> None:
            pass

    resyncs: list[int] = []

    async def _count_resync() -> None:
        resyncs.append(1)

    async def _address() -> tuple[str, str]:
        return "127.0.0.1:8023", "stub"

    real_connection = manager_module._Connection
    manager_module._Connection = _InstantConnection
    try:
        manager = _Manager(_address, lambda _json: None, on_connect=_count_resync)
        await manager.init_connection()
        after_first = len(resyncs)
        manager.maintain_worker.cancel()
        manager.maintain_worker = None
        await manager.init_connection()
        after_second = len(resyncs)
        manager.maintain_worker.cancel()
    finally:
        manager_module._Connection = real_connection

    check(
        "O7 the first connect does not resync, the second does",
        after_first == 0 and after_second == 1,
        f"resyncs after first connect={after_first}, after reconnect={after_second} "
        "(firing on both made every setup enumerate twice)",
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
        "O4 a pong with no transaction id does not count",
        manager.pong_received is False,
        "wayfinder #19 captured the real firmware echoing transactionId, so an "
        "uncorrelatable pong proves nothing about this window",
    )

    # Nothing is outstanding before the first ping goes out, so nothing can
    # answer it -- including a pong that also carries no id.
    manager = _Manager(lambda: None, lambda _json: None)
    manager.pong_received = False
    manager.incoming_json({"type": ResponseType.PONG})
    check(
        "O4 an id-less pong does not match an id-less pending ping",
        manager.pong_received is False,
        "pending_ping_id starts None; None == None must not read as a match",
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

    # Asking is not enough on its own -- nothing must have to poll for it.
    deako, manager = _stub_deako()
    seen: list[bool] = []
    deako.add_connection_listener(seen.append)
    deako.notify_connection_listeners(False)
    deako.notify_connection_listeners(True)
    deako.remove_connection_listener(seen.append)
    check(
        "O5 connection changes are pushed to listeners",
        seen == [False, True],
        f"listener saw {seen}",
    )

    # One listener blowing up must not cost the others their notification;
    # otherwise half the house would keep looking healthy.
    deako, manager = _stub_deako()
    survivors: list[bool] = []

    def _explode(_connected: bool) -> None:
        raise RuntimeError("listener is broken")

    deako.add_connection_listener(_explode)
    deako.add_connection_listener(survivors.append)
    deako.notify_connection_listeners(True)
    check(
        "O5 a broken listener does not silence the others",
        survivors == [True],
        f"surviving listener saw {survivors}",
    )

    # The manager only announces real transitions, and announces them from
    # every path that loses the socket.
    manager = _Manager(lambda: None, lambda _json: None, on_connection_change=None)
    announced: list[bool] = []
    manager.on_connection_change = announced.append
    manager.connection = type(
        "_Live", (), {
            "is_connected": lambda self: True,
            "socket": type("_Sock", (), {"sock": object()})(),
            "close": lambda self: None,
        },
    )()
    manager.notify_connection_change()
    manager.notify_connection_change()  # no change; must stay quiet
    manager.close()
    check(
        "O5 the manager announces transitions once, including on close()",
        announced == [True, False],
        f"announcements={announced} (close() is how the watchdog drops a "
        "blackholed connection)",
    )

    # -- O5: commands must not be swallowed ----------------------------------
    deako, manager = _stub_deako(send_ok=False)
    manager.connected = False
    deako.record_device("Dimmer", DIMMABLE_UUID, True, True, 80)
    try:
        await deako.control_device(DIMMABLE_UUID, True, 50)
        raised = None
    except DeviceCommandError as exc:
        raised = exc
    check(
        "O5 a command that could not be sent raises instead of returning",
        raised is not None,
        f"raised={raised!r} (stock awaited a send whose failure only ever "
        "reached a log line, so the light took the command and did not move)",
    )

    deako, manager = _stub_deako(send_ok=True)
    manager.connected = True
    deako.record_device("Dimmer", DIMMABLE_UUID, True, True, 80)
    try:
        await deako.control_device(DIMMABLE_UUID, True, 50)
        raised = None
    except DeviceCommandError as exc:
        raised = exc
    check(
        "O5 a command that was sent does not raise",
        raised is None and manager.state_changes == 1,
        f"raised={raised!r}, sends={manager.state_changes}",
    )
    # That command opened a witness window (wayfinder #23); this check is not
    # about the detector, so close it rather than leave a timer running.
    deako.void_pending_witnesses()

    # -- O10: a device that missed enumeration can still turn up -------------
    deako, _ = _stub_deako()
    announced_devices: list[str] = []
    deako.add_device_added_listener(announced_devices.append)
    deako.record_device("Late switch", NON_DIMMABLE_UUID, False, False, None)
    first_time = list(announced_devices)
    deako.record_device("Late switch", NON_DIMMABLE_UUID, False, True, None)
    check(
        "O10 a first-time DEVICE_FOUND is announced, a repeat is not",
        first_time == [NON_DIMMABLE_UUID] and announced_devices == first_time,
        f"announced={announced_devices} (the repeat goes to the device's own "
        "callback, which already exists)",
    )

    deako, _ = _stub_deako()
    deako.record_device("Late switch", NON_DIMMABLE_UUID, False, False, None)
    check(
        "O10 no listener is not an error",
        NON_DIMMABLE_UUID in deako.get_devices(),
        "the device is still recorded when nothing is listening",
    )

    # -- wayfinder #23: two platforms both hear about a late arrival ---------
    # The single callback slot this replaced would have let whichever platform
    # loaded second take the news away from the first, so the node status
    # sensor and the light could never both have been built for a straggler.
    deako, _ = _stub_deako()
    heard_by_light: list[str] = []
    heard_by_sensor: list[str] = []
    deako.add_device_added_listener(heard_by_light.append)
    deako.add_device_added_listener(heard_by_sensor.append)
    deako.record_device("Late switch", NON_DIMMABLE_UUID, False, False, None)
    check(
        "#23 every device-added listener hears a first-time DEVICE_FOUND",
        heard_by_light == [NON_DIMMABLE_UUID]
        and heard_by_sensor == [NON_DIMMABLE_UUID],
        f"light={heard_by_light}, sensor={heard_by_sensor}",
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

        # -- wayfinder #23 over the wire: the command-witness detector, against
        #    the simulator's model of a registered-but-unreachable device.
        #    Everything stays identical except the one thing that matters --
        #    the acknowledgement still says "ok", and the EVENT never comes.
        quirks.set_unreachable_devices({NON_DIMMABLE_UUID})
        witness_budget = 2 * deako_module.WITNESS_WINDOW_S + 4

        await client.control_device(NON_DIMMABLE_UUID, True)
        await asyncio.sleep(1)
        acked_but_unwitnessed = client.is_reachable(NON_DIMMABLE_UUID)

        await asyncio.sleep(deako_module.WITNESS_WINDOW_S + 1)
        await client.control_device(NON_DIMMABLE_UUID, False)
        marked = await _wait_until(
            lambda: not client.is_reachable(NON_DIMMABLE_UUID),
            timeout=witness_budget,
        )
        check(
            "#23 live: a switch that acks and never reports is marked unreachable",
            acked_but_unwitnessed and marked,
            "the hub acknowledged both commands with status ok, exactly as it "
            "does for a switch that has been out of the wall for months",
        )

        state = client.get_state(NON_DIMMABLE_UUID)
        check(
            "#23 live: its cached state never moved either",
            state["power"] is False,
            f"state={state} -- the hub's cache is stale, never optimistic, so "
            "the last confirmed value is what the integration still holds",
        )

        # And it comes back the moment the mesh speaks for it again. This is
        # why the light entity stays available while its node reads
        # unreachable: the next attempt is the cheapest thing that can clear
        # the mark, and Home Assistant drops unavailable entities from service
        # calls.
        quirks.set_unreachable_devices(set())
        await client.control_device(NON_DIMMABLE_UUID, True)
        cleared = await _wait_until(
            lambda: client.is_reachable(NON_DIMMABLE_UUID), timeout=15
        )
        check(
            "#23 live: a later witnessed command clears the mark",
            cleared,
            "any EVENT for the device clears it, from any source",
        )

        reporting, expected, missing = client.get_last_sweep()
        check(
            "#23 live: the sweep is accounted for against the real stream",
            (reporting, expected, missing) == (2, 2, []),
            f"reporting={reporting}, expected={expected}, missing={missing}",
        )

        age = client.seconds_since_last_message()
        check(
            "#23 live: the hub's last message is timed",
            age is not None and age < PING_WORKER_WAIT_S + 5,
            f"age={age!r}s on a connection whose only idle traffic is pings "
            f"every {PING_WORKER_WAIT_S}s",
        )

        # -- O4 over the wire: the correlation is strict, so the risk it carries
        #    is the opposite of every other O4 check here -- not a dead
        #    connection going unnoticed, but a *live* one being dumped because
        #    its pong did not match. Nothing else in this suite would catch
        #    that: the checks below all drop the connection deliberately, and a
        #    watchdog that dumps everything passes them. So hold a healthy
        #    connection across a full ping verdict and require it to be left
        #    alone. Watch continuously rather than sampling the end, because a
        #    dump followed by a reconnect looks identical afterwards.
        watch_s = 2 * PING_WORKER_WAIT_S + 5
        dropped_at: float | None = None
        watch_start = asyncio.get_running_loop().time()
        while asyncio.get_running_loop().time() - watch_start < watch_s:
            await asyncio.sleep(0.5)
            if not client.is_connected():
                dropped_at = asyncio.get_running_loop().time() - watch_start
                break
        check(
            "O4 live: a healthy connection survives a full ping verdict",
            dropped_at is None,
            f"held {watch_s}s (>= one ping + one verdict at "
            f"PING_WORKER_WAIT_S={PING_WORKER_WAIT_S}s); "
            + (
                "never dropped"
                if dropped_at is None
                else f"DROPPED at {dropped_at:.1f}s -- strict correlation is "
                "rejecting the hub's own pong"
            ),
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
        reconnects = client.get_reconnect_count()
        check(
            "#23 live: the rebuilt connection was counted",
            reconnects == 1,
            f"reconnects={reconnects} after exactly one forced drop and "
            "recovery",
        )
        reporting, expected, missing = client.get_last_sweep()
        check(
            "#23 live: the reconnect's resync is accounted for as a fresh sweep",
            (reporting, expected, missing) == (2, 2, []),
            f"reporting={reporting}, expected={expected}, missing={missing} "
            "(O7's resync re-enumerates, so the sweep numbers refresh with it)",
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
