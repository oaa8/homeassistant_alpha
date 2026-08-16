#!/usr/bin/env python3
"""Name every device the hub can no longer reach.

Sweeps for current state, then echoes each device's **own** state back to it and
records which ones answer with a confirming ``EVENT``. The command is a no-op by
construction -- it asks for the state the hub already believes -- so nothing in
the house moves unless the hub's belief was already wrong.

Silence is the finding: an acknowledged command that produces no event means the
hub could not reach that device. See the notes on the wayfinder ticket for why
this is the only signal that works -- enumeration, polling and the command
acknowledgement all answer identically for a device that is not there.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from deako_probe import Capture, wait_for_node  # noqa: E402
from deako_reachability_probe import Journal, Session, sweep  # noqa: E402


async def scan(session: Session, devices: dict, gap: float, watch: float) -> dict:
    """Command every device with its own state, then wait for the events."""
    order = list(devices)
    sent_at: dict[str, float] = {}

    for uuid in order:
        state = dict(devices[uuid]["state"] or {})
        if "power" not in state:
            session.journal.note(f"skipping {uuid}: no power state reported")
            continue
        outcome = await session.request(
            {"type": "CONTROL", "data": {"target": uuid, "state": state}},
            timeout=watch,
        )
        sent_at[uuid] = session.journal.offset_ms()
        if not outcome["answered"]:
            session.journal.note(f"{uuid}: command not even acknowledged")
        await asyncio.sleep(gap)

    # The confirming event trails the ack by ~1.6-2.4 s, so give the last
    # command time to land before judging it.
    session.journal.note(f"waiting {watch}s for trailing events")
    deadline = time.monotonic() + watch
    while time.monotonic() < deadline:
        await asyncio.sleep(0.2)

    witnessed: dict[str, float] = {}
    for offset, msg in session.messages:
        if msg.get("type") != "EVENT":
            continue
        target = (msg.get("data") or {}).get("target")
        if target in sent_at and offset >= sent_at[target] - 500:
            witnessed.setdefault(target, round(offset - sent_at[target], 1))

    unreachable = [u for u in sent_at if u not in witnessed]
    result = {
        "commanded": len(sent_at),
        "witnessed": len(witnessed),
        "unreachable_count": len(unreachable),
        "unreachable": [
            {"uuid": u, "name": devices[u]["name"], "hub_state": devices[u]["state"]}
            for u in unreachable
        ],
    }
    session.journal.record("reachability_scan", **result)
    return result


async def run(args: argparse.Namespace, journal: Journal) -> int:
    if args.wait_for_node and not await wait_for_node(
        args.host, args.port, args.wait_for_node, journal
    ):
        return 2

    session = Session(args.host, args.port, journal)
    await session.open()
    try:
        first = await sweep(session, "scan_baseline")
        if not first["received"]:
            journal.note("empty enumeration; reconnecting once")
            await session.close()
            session = Session(args.host, args.port, journal)
            await session.open()
            first = await sweep(session, "scan_baseline_retry")
        devices = first["devices"]
        if not devices:
            journal.record("aborted", reason="no devices enumerated")
            return 1

        journal.note(f"scanning {len(devices)} devices, {args.gap}s apart")
        result = await scan(session, devices, args.gap, args.watch)
    finally:
        await session.close()

    print("\n" + "=" * 60)
    print(f"commanded {result['commanded']}, witnessed {result['witnessed']}")
    if result["unreachable"]:
        print(f"\nUNREACHABLE ({result['unreachable_count']}):")
        for d in result["unreachable"]:
            print(f"   {d['name']:<34} {d['uuid']}  hub says {d['hub_state']}")
    else:
        print("\nevery device answered: nothing unreachable")
    print("=" * 60)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=23)
    parser.add_argument("--log", type=Path)
    parser.add_argument("--wait-for-node", type=float, metavar="SECONDS")
    parser.add_argument(
        "--gap",
        type=float,
        default=0.9,
        help="seconds between commands; the hub documents 800 ms as its floor",
    )
    parser.add_argument(
        "--watch",
        type=float,
        default=8.0,
        help="seconds to keep listening after the last command",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    journal = Journal(args.log)
    try:
        return asyncio.run(run(args, journal))
    except KeyboardInterrupt:
        return 130
    finally:
        journal.close()


if __name__ == "__main__":
    sys.exit(main())
