#!/usr/bin/env python3
"""Ask whether our own reconnect storm can make a healthy Deako node go silent.

After the house cutover the connection dropped in *bursts* -- five flaps in 84 s,
then four in 90 s -- rather than singly. Two readings fit that shape:

* the node stalls for about ninety seconds at a time, and our client simply
  reconnects into a session that is not being served; or
* the first drop is node-side, but our reaction to it -- an immediate reconnect
  followed by a full 37-device resync (the O7 deviation) -- is what keeps the
  node from recovering, making the burst self-sustaining.

The second is the one we would be responsible for, so it is the one worth
trying to falsify. This drives the *vendored* client through repeated
drop-and-resync cycles against a node known to be healthy, at the cadence the
house actually produced, and reports whether the node ever stopped answering.

Strictly read-only: it enumerates, which is what a resync does, and never sends
a CONTROL, so no real light moves.

Usage
-----
    python3 tools/deako_reconnect_storm.py --host <node-address> --cycles 10
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "custom_components" / "deako"))

import pydeako  # noqa: E402
from pydeako.deako import Deako  # noqa: E402
from pydeako.models import ResponseType  # noqa: E402

VENDORED_ROOT = REPO_ROOT / "custom_components" / "deako" / "pydeako"
if Path(pydeako.__file__).resolve().parent != VENDORED_ROOT.resolve():
    raise SystemExit(f"refusing to run: imported {pydeako.__file__}")

PONG_TYPE = str(ResponseType.PONG.value)


def wall() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


async def one_cycle(host: str, port: int, index: int) -> dict:
    """Connect, resync, tear down hard -- and time every part of it."""
    address = f"{host}:{port}"
    seen: list[tuple[float, str]] = []

    async def get_address():
        return address, host

    deako = Deako(get_address)
    manager = deako.connection_manager
    real_incoming = manager.incoming_json

    def incoming_json(payload: dict) -> None:
        seen.append((time.monotonic(), str(payload.get("type"))))
        real_incoming(payload)

    manager.incoming_json = incoming_json  # type: ignore[method-assign]

    t0 = time.monotonic()
    await deako.connect()
    connected_at = None
    for _ in range(30):
        if deako.is_connected():
            connected_at = time.monotonic()
            break
        await asyncio.sleep(0.25)

    result = {
        "cycle": index,
        "connect_s": None if connected_at is None else connected_at - t0,
        "devices": 0,
        "enumerate_s": None,
        "messages": 0,
        "silent": connected_at is None,
    }
    if connected_at is None:
        await deako.disconnect()
        return result

    # A resync is a full device list. This is what every reconnect costs the
    # node, and it is the part of our reaction that could plausibly hurt.
    t1 = time.monotonic()
    try:
        await asyncio.wait_for(deako.find_devices(), timeout=20)
        result["enumerate_s"] = time.monotonic() - t1
    except Exception as exc:  # pylint: disable=broad-exception-caught
        result["enumerate_s"] = None
        result["error"] = repr(exc)
    result["devices"] = len(deako.get_devices())
    result["messages"] = len(seen)

    # Hard teardown, the way a watchdog drop leaves it: close the socket and
    # immediately go round again, with no pause for the node to tidy up.
    await deako.disconnect()
    return result


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=23)
    parser.add_argument("--cycles", type=int, default=10)
    parser.add_argument(
        "--gap", type=float, default=1.0,
        help="seconds between teardown and the next connect",
    )
    args = parser.parse_args()

    print(f"{wall()}  storming {args.host}:{args.port} "
          f"for {args.cycles} reconnect+resync cycles")
    results = []
    for i in range(1, args.cycles + 1):
        res = await one_cycle(args.host, args.port, i)
        results.append(res)
        conn = res["connect_s"]
        enum = res["enumerate_s"]
        print(
            f"{wall()}  cycle {i:2d}  "
            f"connect={'FAILED' if conn is None else f'{conn:.2f}s'}  "
            f"enumerate={'FAILED' if enum is None else f'{enum:.2f}s'}  "
            f"devices={res['devices']}  messages={res['messages']}",
            flush=True,
        )
        await asyncio.sleep(args.gap)

    failed = [r for r in results if r["silent"] or r["devices"] == 0]
    print()
    print("=" * 60)
    print(f"cycles:            {len(results)}")
    print(f"cycles that failed to connect or enumerate: {len(failed)}")
    oks = [r for r in results if r["connect_s"] is not None]
    if oks:
        conns = [r["connect_s"] for r in oks]
        print(f"connect time  min {min(conns):.2f}s  max {max(conns):.2f}s")
        enums = [r["enumerate_s"] for r in oks if r["enumerate_s"] is not None]
        if enums:
            print(f"enumerate time min {min(enums):.2f}s max {max(enums):.2f}s")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
