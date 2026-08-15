#!/usr/bin/env python3
"""Establish how a Deako node reports a device it cannot reach.

The protocol has no per-device reachability field, so unreachability can only
be inferred. This tool measures the three candidate inferences on one short
connection, because the node it must run against may only be on the network for
seconds at a time:

1. **Sweep omission** — does ``DEVICE_LIST`` advertise more devices than it
   delivers, and is the shortfall the *same* devices every time?
2. **``DEVICE_POLL``** — is it a real verb, and if so does it reach the device
   or answer from the node's own profile? A UUID that is not in the profile at
   all is sent as a contrast: a node that answers for a device it has never
   heard of is answering from nothing, and a node that answers a known UUID as
   fast as it rejects an unknown one never left the building.
3. **``CONTROL`` with no following ``EVENT``** — the acknowledgement is known to
   be local and fast, so only the trailing ``EVENT`` can witness the mesh.

Everything is recorded as timestamped JSON so the numbers are reproducible
rather than remembered. The node address is always an argument; nothing about
any particular installation is baked into this file.

Usage
-----
    python tools/deako_reachability_probe.py --host <addr> --log run.log \
        --wait-for-node 1200
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import random
import sys
import time
import uuid as uuidlib
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))

from deako_probe import Capture, wait_for_node  # noqa: E402

DEFAULT_PORT = 23
CLIENT = "deako_reachability"


class Journal(Capture):
    """A capture that also carries structured results."""

    def __init__(self, path: Path | None) -> None:
        super().__init__(path)
        self.results: dict[str, Any] = {}

    def record(self, phase: str, **fields: Any) -> None:
        self.results[phase] = fields
        self.write("##", f"RESULT {json.dumps({'phase': phase, **fields})}")


class Session:
    """One telnet session with a continuously-draining reader.

    Draining continuously is the point: replies and unsolicited ``EVENT``s are
    interleaved, and a reader that only runs between sends will attribute an
    event to whatever it happened to be waiting for.
    """

    def __init__(self, host: str, port: int, journal: Journal) -> None:
        self.host = host
        self.port = port
        self.journal = journal
        self.messages: list[tuple[float, dict[str, Any]]] = []
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._pump: asyncio.Task[None] | None = None
        self._waiters: dict[str, asyncio.Future[tuple[float, dict[str, Any]]]] = {}
        self.closed = asyncio.Event()

    async def open(self, attempts: int = 6) -> None:
        """Connect, retrying — a freshly woken node resets the first connection."""
        last: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                self._reader, self._writer = await asyncio.wait_for(
                    asyncio.open_connection(self.host, self.port), timeout=6.0
                )
            except (OSError, asyncio.TimeoutError) as exc:
                last = exc
                self.journal.note(f"connect attempt {attempt} failed ({exc}); retrying")
                await asyncio.sleep(1.0)
                continue
            self.journal.reset_clock()
            self.journal.note(f"connected on attempt {attempt}")
            self._pump = asyncio.create_task(self._drain())
            return
        raise ConnectionError(f"could not connect to {self.host}:{self.port}: {last}")

    async def _drain(self) -> None:
        assert self._reader is not None
        while True:
            try:
                raw = await self._reader.readline()
            except (OSError, asyncio.IncompleteReadError) as exc:
                self.journal.note(f"read failed: {exc}")
                break
            if not raw:
                self.journal.note("remote closed the connection")
                break
            offset = self.journal.offset_ms()
            text = raw.decode(errors="replace").strip()
            if not text:
                continue
            self.journal.write("<--", text)
            try:
                msg = json.loads(text)
            except (json.JSONDecodeError, ValueError):
                continue
            self.messages.append((offset, msg))
            tid = msg.get("transactionId")
            waiter = self._waiters.get(tid) if tid else None
            if waiter is not None and not waiter.done():
                waiter.set_result((offset, msg))
        self.closed.set()

    async def send(self, message: dict[str, Any], tid: str | None = None) -> tuple[str, float]:
        assert self._writer is not None
        message.setdefault("transactionId", tid or str(uuidlib.uuid4()))
        message.setdefault("src", CLIENT)
        message.setdefault("dst", "deako")
        payload = json.dumps(message, separators=(",", ":")) + "\r\n"
        sent_at = self.journal.offset_ms()
        self.journal.write("-->", payload.strip())
        self._writer.write(payload.encode())
        await self._writer.drain()
        return message["transactionId"], sent_at

    async def request(
        self, message: dict[str, Any], timeout: float
    ) -> dict[str, Any]:
        """Send one message and wait for the reply carrying its transaction id."""
        tid = message.get("transactionId") or str(uuidlib.uuid4())
        message["transactionId"] = tid
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[tuple[float, dict[str, Any]]] = loop.create_future()
        self._waiters[tid] = fut
        _, sent_at = await self.send(message)
        try:
            offset, reply = await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            return {"answered": False, "latency_ms": None, "reply": None}
        finally:
            self._waiters.pop(tid, None)
        return {
            "answered": True,
            "latency_ms": round(offset - sent_at, 1),
            "reply": reply,
        }

    async def close(self) -> None:
        if self._writer is not None:
            with contextlib.suppress(OSError):
                self._writer.close()
            with contextlib.suppress(OSError, asyncio.TimeoutError):
                await asyncio.wait_for(self._writer.wait_closed(), timeout=3.0)
        if self._pump is not None:
            self._pump.cancel()
            with contextlib.suppress(asyncio.CancelledError, OSError):
                await self._pump
        self.journal.note("disconnected")


async def sweep(session: Session, label: str, timeout: float = 8.0) -> dict[str, Any]:
    """One DEVICE_LIST, recording the advertised count *and* every identity."""
    start = len(session.messages)
    tid, sent_at = await session.send({"type": "DEVICE_LIST"})
    advertised: int | None = None
    devices: dict[str, dict[str, Any]] = {}
    list_reply_ms: float | None = None
    last_found_ms: float | None = None
    deadline = time.monotonic() + timeout
    index = start
    while time.monotonic() < deadline:
        while index < len(session.messages):
            offset, msg = session.messages[index]
            index += 1
            if msg.get("type") == "DEVICE_LIST" and "data" in msg:
                advertised = msg["data"].get("number_of_devices")
                list_reply_ms = round(offset - sent_at, 1)
            elif msg.get("type") == "DEVICE_FOUND":
                data = msg.get("data", {})
                devices[data.get("uuid")] = {
                    "name": data.get("name"),
                    "state": data.get("state"),
                    "capabilities": data.get("capabilities"),
                }
                last_found_ms = round(offset - sent_at, 1)
        if advertised is not None and len(devices) >= advertised:
            break
        await asyncio.sleep(0.05)
    result = {
        "label": label,
        "advertised": advertised,
        "received": len(devices),
        "list_reply_ms": list_reply_ms,
        "last_found_ms": last_found_ms,
        "complete": advertised is not None and len(devices) >= advertised,
    }
    session.journal.record(f"sweep.{label}", **result)
    return {**result, "devices": devices}


async def poll_variants(
    session: Session, known_uuid: str, timeout: float = 4.0
) -> dict[str, Any]:
    """Is DEVICE_POLL a verb, and does it answer from the device or the profile?

    #19 only ever sent a bare ``DEVICE_POLL`` with no target, on a connection
    whose silence was never validated, so nothing is known. The absent UUID is
    the control: it is well-formed and cannot be in any profile.
    """
    absent = str(uuidlib.UUID(int=random.getrandbits(128), version=4))
    shapes = {
        "root_target.known": {"type": "DEVICE_POLL", "target": known_uuid},
        "data_target.known": {"type": "DEVICE_POLL", "data": {"target": known_uuid}},
        "root_target.absent": {"type": "DEVICE_POLL", "target": absent},
        "bare": {"type": "DEVICE_POLL"},
    }
    outcomes: dict[str, Any] = {"absent_uuid": absent}
    for label, message in shapes.items():
        if session.closed.is_set():
            outcomes[label] = {"answered": False, "note": "connection already closed"}
            continue
        outcome = await session.request(dict(message), timeout=timeout)
        reply = outcome.get("reply") or {}
        data = reply.get("data") if isinstance(reply.get("data"), dict) else {}
        outcomes[label] = {
            "answered": outcome["answered"],
            "latency_ms": outcome["latency_ms"],
            "status": reply.get("status"),
            "code": data.get("code"),
            # The hub is documented to answer a *successful* poll with
            # status="error", so success is judged by whether the reply carries
            # the device rather than by the status field.
            "carries_device": bool(data) and any(
                key in data for key in ("state", "name", "uuid", "capabilities")
            ),
            "reply": reply or None,
        }
        await asyncio.sleep(0.4)
    session.journal.record("device_poll", **outcomes)
    return outcomes


async def control_and_event(
    session: Session, target: str, state: dict[str, Any], watch: float = 8.0
) -> dict[str, Any]:
    """Idempotent CONTROL, then wait for the EVENT that witnesses the mesh.

    The acknowledgement is known to arrive in tens of milliseconds and is local,
    so it says nothing about the device. Only the trailing DEVICE_STATE_CHANGE
    shows the command actually reached something.
    """
    desired = {k: v for k, v in state.items() if v is not None}
    if "power" not in desired:
        desired["power"] = True
    start = len(session.messages)
    outcome = await session.request(
        {"type": "CONTROL", "data": {"target": target, "state": desired}},
        timeout=watch,
    )
    ack_ms = outcome["latency_ms"]
    event_ms = None
    deadline = time.monotonic() + watch
    index = start
    while time.monotonic() < deadline and event_ms is None:
        while index < len(session.messages):
            offset, msg = session.messages[index]
            index += 1
            if msg.get("type") != "EVENT":
                continue
            data = msg.get("data", {})
            if data.get("target") == target:
                event_ms = round(offset, 1)
                break
        await asyncio.sleep(0.05)
    result = {
        "target": target,
        "requested_state": desired,
        "acknowledged": outcome["answered"],
        "ack_ms": ack_ms,
        "event_seen": event_ms is not None,
        "event_offset_ms": event_ms,
    }
    session.journal.record("control_event", **result)
    return result


async def poll_all(
    session: Session, uuids: list[str], shape: str, per_wait: float = 6.0
) -> dict[str, Any]:
    """Poll every device at once and see which ones fail to answer.

    Pipelined rather than sequential: the window this runs in may be under 90
    seconds, and 37 sequential round trips would not fit.
    """
    loop = asyncio.get_running_loop()
    pending: dict[str, tuple[str, asyncio.Future[tuple[float, dict[str, Any]]], float]] = {}
    for target in uuids:
        tid = str(uuidlib.uuid4())
        fut: asyncio.Future[tuple[float, dict[str, Any]]] = loop.create_future()
        session._waiters[tid] = fut
        message = (
            {"type": "DEVICE_POLL", "target": target, "transactionId": tid}
            if shape == "root_target"
            else {"type": "DEVICE_POLL", "data": {"target": target}, "transactionId": tid}
        )
        _, sent_at = await session.send(message)
        pending[target] = (tid, fut, sent_at)
        await asyncio.sleep(0.05)

    answered: dict[str, float] = {}
    silent: list[str] = []
    deadline = time.monotonic() + per_wait
    for target, (tid, fut, sent_at) in pending.items():
        remaining = max(0.1, deadline - time.monotonic())
        try:
            offset, _ = await asyncio.wait_for(asyncio.shield(fut), timeout=remaining)
        except asyncio.TimeoutError:
            silent.append(target)
        else:
            answered[target] = round(offset - sent_at, 1)
        finally:
            session._waiters.pop(tid, None)
    result = {
        "shape": shape,
        "polled": len(uuids),
        "answered": len(answered),
        "silent": silent,
        "latency_ms_min": min(answered.values()) if answered else None,
        "latency_ms_max": max(answered.values()) if answered else None,
    }
    session.journal.record("poll_all", **result)
    return result


async def poll_serial(
    session: Session, uuids: list[str], shape: str, timeout: float = 3.0, gap: float = 0.15
) -> dict[str, Any]:
    """Poll every device one at a time, waiting for each reply before the next.

    The pipelined sweep loses a different random subset on every run, which is
    the signature of the node shedding concurrent work rather than of devices
    being unreachable. Pacing the polls separates those two explanations.
    """
    answered: dict[str, float] = {}
    silent: list[str] = []
    for target in uuids:
        message = (
            {"type": "DEVICE_POLL", "target": target}
            if shape == "root_target"
            else {"type": "DEVICE_POLL", "data": {"target": target}}
        )
        outcome = await session.request(message, timeout=timeout)
        if outcome["answered"]:
            answered[target] = outcome["latency_ms"]
        else:
            silent.append(target)
        await asyncio.sleep(gap)
    result = {
        "shape": shape,
        "mode": "serial",
        "polled": len(uuids),
        "answered": len(answered),
        "silent": silent,
        "latency_ms_min": min(answered.values()) if answered else None,
        "latency_ms_max": max(answered.values()) if answered else None,
        "latency_ms_median": sorted(answered.values())[len(answered) // 2]
        if answered
        else None,
    }
    session.journal.record("poll_serial", **result)
    return result


async def duel(
    session: Session,
    suspect: str,
    control: str,
    repeats: int,
    shape: str = "root_target",
    timeout: float = 3.0,
    gap: float = 0.4,
) -> dict[str, Any]:
    """Poll a suspect and a known-good device alternately, and compare.

    Alternating matters: the node loses a random share of concurrent requests,
    so a suspect polled on its own cannot be told apart from a node having a bad
    moment. Interleaving a control device makes each pair its own experiment.
    """
    stats: dict[str, dict[str, Any]] = {
        "suspect": {"uuid": suspect, "answered": 0, "silent": 0, "latencies": [], "codes": []},
        "control": {"uuid": control, "answered": 0, "silent": 0, "latencies": [], "codes": []},
    }
    for _ in range(repeats):
        for role in ("suspect", "control"):
            target = stats[role]["uuid"]
            message = (
                {"type": "DEVICE_POLL", "target": target}
                if shape == "root_target"
                else {"type": "DEVICE_POLL", "data": {"target": target}}
            )
            outcome = await session.request(message, timeout=timeout)
            if outcome["answered"]:
                reply = outcome["reply"] or {}
                data = reply.get("data") if isinstance(reply.get("data"), dict) else {}
                stats[role]["answered"] += 1
                stats[role]["latencies"].append(outcome["latency_ms"])
                stats[role]["codes"].append(data.get("code") or "device")
            else:
                stats[role]["silent"] += 1
            await asyncio.sleep(gap)

    result: dict[str, Any] = {"repeats": repeats}
    for role, s in stats.items():
        lat = s["latencies"]
        result[role] = {
            "uuid": s["uuid"],
            "answered": s["answered"],
            "silent": s["silent"],
            "latency_ms_min": min(lat) if lat else None,
            "latency_ms_max": max(lat) if lat else None,
            "latency_ms_mean": round(sum(lat) / len(lat), 1) if lat else None,
            "reply_kinds": sorted(set(s["codes"])),
        }
    session.journal.record("duel", **result)
    return result


async def watch(
    session: Session, target: str, seconds: float, interval: float = 0.25
) -> dict[str, Any]:
    """Poll one device continuously and record when its answer changes.

    This is what separates a poll that reaches the device from one answered out
    of the node's own profile. The device is driven out of band, through a
    different hub, while this runs. A poll that reports the new state *before*
    the mesh EVENT announcing it must have asked the device; a poll that only
    changes once the EVENT lands was reading what the EVENT wrote.
    """
    samples: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    seen = len(session.messages)
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        outcome = await session.request(
            {"type": "DEVICE_POLL", "target": target}, timeout=2.0
        )
        reply = outcome.get("reply") or {}
        data = reply.get("data") if isinstance(reply.get("data"), dict) else {}
        state = data.get("state") if isinstance(data.get("state"), dict) else None
        samples.append(
            {
                "at_ms": round(session.journal.offset_ms(), 1),
                "answered": outcome["answered"],
                "latency_ms": outcome["latency_ms"],
                "state": state,
            }
        )
        while seen < len(session.messages):
            offset, msg = session.messages[seen]
            seen += 1
            if msg.get("type") == "EVENT" and (msg.get("data") or {}).get("target") == target:
                events.append({"at_ms": round(offset, 1), "state": msg["data"].get("state")})
        await asyncio.sleep(interval)

    transitions = []
    previous = None
    for sample in samples:
        current = sample["state"]
        if current is not None and current != previous:
            if previous is not None:
                transitions.append({"at_ms": sample["at_ms"], "from": previous, "to": current})
            previous = current
    result = {
        "target": target,
        "polls": len(samples),
        "answered": sum(1 for s in samples if s["answered"]),
        "poll_transitions": transitions,
        "events": events,
    }
    session.journal.record("watch", **result)
    return result


async def run(args: argparse.Namespace, journal: Journal) -> int:
    if args.wait_for_node and not await wait_for_node(
        args.host, args.port, args.wait_for_node, journal
    ):
        return 2

    # A freshly woken node accepts TCP before it is serving and resets the
    # first connection, so an enumeration that comes back empty is retried on a
    # new socket rather than believed.
    session: Session | None = None
    first: dict[str, Any] = {}
    for attempt in range(1, args.attempts + 1):
        session = Session(args.host, args.port, journal)
        await session.open()
        first = await sweep(session, f"first.attempt{attempt}")
        if first["received"]:
            break
        journal.note(f"attempt {attempt}: enumeration came back empty; reconnecting")
        await session.close()
        session = None
        await asyncio.sleep(1.0)
    if session is None or not first.get("received"):
        journal.record("aborted", reason="no enumeration after retries")
        return 1

    try:
        second = await sweep(session, "second")

        same = set(first["devices"]) == set(second["devices"])
        journal.record(
            "sweep.compare",
            first_received=first["received"],
            second_received=second["received"],
            advertised=first["advertised"],
            identical_uuid_sets=same,
            only_in_first=sorted(set(first["devices"]) - set(second["devices"])),
            only_in_second=sorted(set(second["devices"]) - set(first["devices"])),
            shortfall=(first["advertised"] or 0) - first["received"],
        )

        devices = first["devices"] or second["devices"]
        if not devices:
            journal.note("no devices enumerated; cannot probe further")
            return 1

        known = args.target if args.target in devices else next(iter(devices))
        journal.note(f"probing with known device {devices[known]['name']!r}")
        polls = await poll_variants(session, known)

        working_shape = None
        for shape, label in (("root_target", "root_target.known"), ("data_target", "data_target.known")):
            if polls.get(label, {}).get("carries_device"):
                working_shape = shape
                break
        if working_shape and args.poll_all:
            await poll_all(session, list(devices), working_shape)
        if working_shape and args.poll_serial:
            await poll_serial(session, list(devices), working_shape, gap=args.poll_gap)
        if not working_shape:
            journal.record("poll_all", skipped=True, reason="no DEVICE_POLL shape answered")

        if working_shape and args.suspect:
            control = args.control_uuid or known
            await duel(session, args.suspect, control, args.duel_repeats, shape=working_shape)

        if working_shape and args.watch_seconds:
            journal.note(
                f"watching {devices[known]['name']!r} for {args.watch_seconds}s "
                "-- drive it out of band now"
            )
            await watch(session, known, args.watch_seconds)

        if args.control:
            state = dict(devices[known]["state"] or {})
            await control_and_event(session, known, state)
        else:
            journal.record("control_event", skipped=True, reason="--control not given")
    finally:
        await session.close()

    journal.write("##", "=" * 68)
    journal.write("##", "SUMMARY")
    journal.write("##", json.dumps(journal.results, indent=1))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", required=True, help="node address")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--log", type=Path, help="append the capture to this file")
    parser.add_argument(
        "--wait-for-node",
        type=float,
        metavar="SECONDS",
        help="poll until the node accepts connections, so the battery can fire "
        "unattended on a node that is only briefly present",
    )
    parser.add_argument("--target", default="", help="uuid to probe with, if known")
    parser.add_argument(
        "--poll-all",
        action="store_true",
        help="poll every enumerated device at once, to find ones that do not answer",
    )
    parser.add_argument(
        "--poll-serial",
        action="store_true",
        help="poll every enumerated device one at a time, so a silent device is "
        "not confused with a node shedding concurrent requests",
    )
    parser.add_argument(
        "--poll-gap",
        type=float,
        default=0.15,
        help="seconds between serial polls",
    )
    parser.add_argument(
        "--control",
        action="store_true",
        help="send one idempotent CONTROL and watch for its EVENT (moves a real light)",
    )
    parser.add_argument(
        "--attempts",
        type=int,
        default=6,
        help="how many times to rebuild the connection if enumeration comes back empty",
    )
    parser.add_argument(
        "--suspect",
        default="",
        help="uuid suspected of being registered but unreachable; polled head to "
        "head against a known-good device",
    )
    parser.add_argument(
        "--control-uuid",
        default="",
        help="the known-good device to compare the suspect against (default: --target)",
    )
    parser.add_argument("--duel-repeats", type=int, default=10)
    parser.add_argument(
        "--watch-seconds",
        type=float,
        default=0,
        help="poll --target continuously for this long while it is driven out of "
        "band, to see whether the poll leads or follows the mesh EVENT",
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
