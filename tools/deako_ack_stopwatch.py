#!/usr/bin/env python3
"""Stopwatch the ack-driven UI update against a real Deako node.

Wayfinder #39's headline claim is a number: the hub's acknowledgement moves the
UI in tens of milliseconds, where waiting for the switch's own EVENT took
1549-3412ms in the house. The simulator says 20ms, but the simulator is on
loopback and answers instantly by construction, so it can only show the
mechanism works -- not what it costs on real firmware over real wifi.

This drives the *vendored library* (not Home Assistant) against a named node and
reports what it measured:

  1. TIMINGS   -- one real state change. Time from the command leaving to the
                 optimistic callback firing (the ack), and to the state
                 callback firing (the EVENT). Then it waits out the witness
                 window to show a healthy light is not reverted, and puts the
                 device back the way it was found.
  2. BURST     -- N commands fired with no spacing at all, which is what a scene
                 does now that 0.6.0 has deleted 0.3.1's send queue. Every
                 command is the device's *own current state*, so nothing moves;
                 the hub's rate limiter works on arrival time, not content. The
                 drop counter is read afterwards, which is the first time this
                 question has been asked of real firmware.

Safety
------
A Deako node's telnet server is exclusive, so only point this at a node nothing
else is holding -- `deako_probe.py probe` answers that. And on a node carrying a
real house profile, phase 1 *moves a real light*: pick the target deliberately.
`--no-toggle` skips it and runs the burst alone, which moves nothing.

Run it under WSL/Linux, not Windows: pydeako passes the port to sock_connect as
a str, which getaddrinfo tolerates only on POSIX.

Usage
-----
    python3 tools/deako_ack_stopwatch.py --host <addr> --target <uuid>
    python3 tools/deako_ack_stopwatch.py --host <addr> --no-toggle --burst 6
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "custom_components" / "deako"))

import pydeako  # noqa: E402
from pydeako.deako import Deako  # noqa: E402
from pydeako.deako._deako import ACK_WINDOW_S, WITNESS_WINDOW_S  # noqa: E402

VENDORED_ROOT = REPO_ROOT / "custom_components" / "deako" / "pydeako"
if Path(pydeako.__file__).resolve().parent != VENDORED_ROOT.resolve():
    raise SystemExit(f"refusing to run: imported {pydeako.__file__}")


def ms(start: float, end: float | None) -> str:
    return "never" if end is None else f"{(end - start) * 1000:.1f}ms"


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", required=True, help="node address")
    parser.add_argument("--port", type=int, default=23)
    parser.add_argument("--client", default="wf39_stopwatch")
    parser.add_argument(
        "--target", help="device uuid to command; defaults to the first found"
    )
    parser.add_argument(
        "--no-toggle", action="store_true",
        help="skip the phase that moves a real light",
    )
    parser.add_argument(
        "--burst", type=int, default=6,
        help="how many unspaced commands to fire at one device",
    )
    args = parser.parse_args()

    address = f"{args.host}:{args.port}"

    async def get_address():
        return address, "stopwatch"

    client = Deako(get_address, client_name=args.client)
    print(f"connecting to {address}")
    await client.connect()
    await client.find_devices()
    devices = client.get_devices()
    print(f"enumerated {len(devices)} devices")
    if not devices:
        print("nothing to command")
        return 2

    target = args.target or next(iter(devices))
    if target not in devices:
        print(f"{target} is not a device this hub announced")
        return 2
    name = client.get_name(target)
    state = dict(client.get_state(target) or {})
    print(f"target: {name} ({target}) currently {state}")

    acked_at: list[float] = []
    reverted_at: list[float] = []
    evented_at: list[float] = []

    def on_optimistic(shown: dict | None) -> None:
        (reverted_at if shown is None else acked_at).append(time.monotonic())

    client.set_optimistic_callback(target, on_optimistic)
    client.set_state_callback(target, lambda: evented_at.append(time.monotonic()))

    if not args.no_toggle:
        print("\n=== phase 1: one real state change ===")
        was_on = bool(state.get("power"))
        started = time.monotonic()
        await client.control_device(target, not was_on)
        # Long enough for the EVENT (1.6-2.4s measured) and then the witness
        # window, so "a healthy light is not reverted" is observed rather than
        # assumed.
        await asyncio.sleep(WITNESS_WINDOW_S + 4)

        ack = acked_at[0] if acked_at else None
        event = evented_at[0] if evented_at else None
        print(f"  ack, and the UI update it drives:  {ms(started, ack)}")
        print(f"  the switch's own confirming EVENT: {ms(started, event)}")
        print(f"  reverted:                          "
              f"{'no' if not reverted_at else ms(started, reverted_at[0])}")
        if ack is not None and event is not None:
            print(f"  the UI is answering {(event - ack) * 1000:.0f}ms sooner "
                  "than it did before this change")

        print("  putting it back the way it was found")
        await client.control_device(target, was_on)
        await asyncio.sleep(4)

    print(f"\n=== phase 2: {args.burst} commands, no spacing ===")
    # Idempotent: every command is the state the device was *found* in, so
    # nothing in the room moves whatever the hub decides to do with them. Read
    # from what was captured before phase 1 rather than from the cache now:
    # after a toggle the cache can still be mid-flight, and echoing that back
    # would command the device somewhere nobody asked for.
    power = bool(state.get("power"))
    dim = state.get("dim") if power else None
    dropped_before = client.get_dropped_command_count()
    print(f"  sending {args.burst} x {{power: {power}, dim: {dim}}} back to back")
    for _ in range(args.burst):
        await client.send_command(target, power, dim)
    await asyncio.sleep(ACK_WINDOW_S + 3)
    dropped = client.get_dropped_command_count() - dropped_before
    print(f"  the hub did not acknowledge {dropped} of {args.burst}")
    if dropped:
        print("  -- 0.3.1 spaced commands 500ms apart through a send queue; "
              "0.6.0 spaces nothing, and this is what that costs")
    else:
        print("  -- no drops at this burst size on this node today")

    # Never leave a real light somewhere nobody put it. The hub drops commands
    # sent this close together, so the restore is checked and re-asked rather
    # than fired once and hoped for: a rig that reports "put back" without
    # looking is how a house ends up dark at midnight.
    print("\n=== leaving it as it was found ===")
    restored = False
    for attempt in range(1, 4):
        current = dict(client.get_state(target) or {})
        if bool(current.get("power")) == power and (
            not power or current.get("dim") == dim
        ):
            print(f"  {name} reads {current}, as found")
            restored = True
            break
        print(f"  attempt {attempt}: it reads {current}, re-commanding {state}")
        await client.control_device(target, power, dim)
        await asyncio.sleep(6)
    if not restored:
        print(f"  COULD NOT RESTORE {name}: it reads "
              f"{client.get_state(target)}, was found as {state} -- go and look")

    await client.disconnect()
    return 0 if restored else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
