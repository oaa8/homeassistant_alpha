#!/usr/bin/env python3
"""Hardware probe and traffic capture tool for a Deako local-integration node.

Speaks the Deako telnet protocol directly, with no dependency on pydeako or on
Home Assistant, so that hub behaviour can be measured independently of the
integration under test. Every byte sent and received is written to a capture
log with timestamps relative to connect, which is what makes the timings
reproducible rather than anecdotal.

The node address is always supplied on the command line. Nothing about any
particular installation is baked into this file.

Safety
------
A Deako node's telnet server is effectively exclusive: the first connection is
the functional one and later connections are accepted but silent. Connecting to
a node that an integration is *not* currently holding will make this tool the
functional connection, so only point it at a node you know is free. The
``probe`` command exists to establish exactly that before anything else runs.

Usage
-----
    python tools/deako_probe.py --host <addr> probe
    python tools/deako_probe.py --host <addr> enumerate --rounds 5
    python tools/deako_probe.py --host <addr> listen --seconds 300
    python tools/deako_probe.py --host <addr> newlines --count 60 --interval 10
    python tools/deako_probe.py --host <addr> control --target <uuid> --power on
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import sys
import time
import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

DEFAULT_PORT = 23
DEFAULT_CLIENT = "deako_probe"


class Capture:
    """Timestamped record of everything crossing the connection."""

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self._fh = path.open("a", encoding="utf-8") if path else None
        self.t0 = time.monotonic()

    def reset_clock(self) -> None:
        self.t0 = time.monotonic()

    def offset_ms(self) -> float:
        return (time.monotonic() - self.t0) * 1000.0

    def write(self, direction: str, payload: str) -> None:
        line = (
            f"{datetime.now().isoformat(timespec='milliseconds')}"
            f"\t+{self.offset_ms():9.1f}ms\t{direction}\t{payload}"
        )
        print(line, flush=True)
        if self._fh:
            self._fh.write(line + "\n")
            self._fh.flush()

    def note(self, text: str) -> None:
        self.write("##", text)

    def close(self) -> None:
        if self._fh:
            self._fh.close()


class DeakoConnection:
    """A single telnet session against one Deako node."""

    def __init__(self, host: str, port: int, client: str, capture: Capture) -> None:
        self.host = host
        self.port = port
        self.client = client
        self.capture = capture
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

    async def __aenter__(self) -> DeakoConnection:
        self.capture.note(f"connecting to {self.host}:{self.port} as {self.client}")
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port), timeout=10.0
        )
        self.capture.reset_clock()
        self.capture.note("connected")
        return self

    async def __aexit__(self, *_exc: object) -> None:
        if self._writer is not None:
            self._writer.close()
            with contextlib.suppress(OSError):
                await self._writer.wait_closed()
        self.capture.note("disconnected")

    async def send_raw(self, payload: str) -> None:
        assert self._writer is not None
        self.capture.write("-->", repr(payload))
        self._writer.write(payload.encode())
        await self._writer.drain()

    async def send(self, message: dict[str, Any]) -> str:
        """Send a protocol message, returning its transaction id."""
        message.setdefault("transactionId", str(uuid.uuid4()))
        message.setdefault("src", self.client)
        message.setdefault("dst", "deako")
        await self.send_raw(json.dumps(message, separators=(",", ":")) + "\r\n")
        return message["transactionId"]

    async def read_lines(
        self,
        seconds: float,
        on_message: Callable[[dict[str, Any] | None, str, float], bool | None]
        | None = None,
    ) -> list[tuple[float, str]]:
        """Read for a bounded period, returning (offset_ms, raw_line) pairs.

        ``on_message`` may return True to stop reading early.
        """
        assert self._reader is not None
        received: list[tuple[float, str]] = []
        deadline = time.monotonic() + seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                raw = await asyncio.wait_for(
                    self._reader.readline(), timeout=remaining
                )
            except asyncio.TimeoutError:
                break
            if not raw:
                self.capture.note("remote closed the connection")
                break
            offset = self.capture.offset_ms()
            text = raw.decode(errors="replace")
            self.capture.write("<--", repr(text))
            received.append((offset, text))
            if on_message is not None:
                parsed: dict[str, Any] | None
                try:
                    parsed = json.loads(text.strip())
                except (json.JSONDecodeError, ValueError):
                    parsed = None
                if on_message(parsed, text, offset):
                    break
        return received


async def cmd_probe(conn_factory: Callable[[], DeakoConnection], args) -> int:
    """Establish whether this node is free, without disturbing it if it isn't.

    A node already held by another integration accepts the socket but answers
    nothing. A PONG therefore means we are the functional connection, which
    means nothing else was using the node.
    """
    async with conn_factory() as conn:
        conn.capture.note(f"listening {args.settle}s before sending anything")
        unsolicited = await conn.read_lines(args.settle)

        answered = False

        def check(parsed, _raw, _offset) -> bool:
            nonlocal answered
            if parsed and parsed.get("type") == "PING":
                answered = True
                return True
            return False

        conn.capture.note("sending PING")
        await conn.send({"type": "PING"})
        await conn.read_lines(args.wait, on_message=check)

        conn.capture.note(
            f"result: {'RESPONSIVE - this node is free' if answered else 'SILENT - node is held by another client, or telnet is not serving'}"
        )
        conn.capture.note(f"unsolicited lines before PING: {len(unsolicited)}")
    return 0 if answered else 1


async def cmd_enumerate(conn_factory: Callable[[], DeakoConnection], args) -> int:
    """Measure how long a full device enumeration actually takes.

    This is the measurement that replaces the guessed enumeration window: time
    to the DEVICE_LIST response, time to the first and last DEVICE_FOUND, and
    the largest gap between consecutive DEVICE_FOUND messages.
    """
    summaries: list[dict[str, float | int]] = []
    for round_index in range(1, args.rounds + 1):
        async with conn_factory() as conn:
            conn.capture.note(f"--- enumeration round {round_index}/{args.rounds}")
            expected: int | None = None
            list_response_ms: float | None = None
            found_ms: list[float] = []

            def check(parsed, _raw, offset) -> bool:
                nonlocal expected, list_response_ms
                if not parsed:
                    return False
                if parsed.get("type") == "DEVICE_LIST" and "data" in parsed:
                    expected = parsed["data"].get("number_of_devices")
                    list_response_ms = offset
                elif parsed.get("type") == "DEVICE_FOUND":
                    found_ms.append(offset)
                return expected is not None and len(found_ms) >= expected

            await conn.send({"type": "DEVICE_LIST"})
            await conn.read_lines(args.timeout, on_message=check)

            gaps = [b - a for a, b in zip(found_ms, found_ms[1:])]
            summary = {
                "round": round_index,
                "expected": expected if expected is not None else -1,
                "received": len(found_ms),
                "list_response_ms": round(list_response_ms or -1, 1),
                "first_found_ms": round(found_ms[0], 1) if found_ms else -1,
                "last_found_ms": round(found_ms[-1], 1) if found_ms else -1,
                "max_gap_ms": round(max(gaps), 1) if gaps else 0,
            }
            summaries.append(summary)
            conn.capture.note(f"round summary: {json.dumps(summary)}")
        if round_index < args.rounds:
            await asyncio.sleep(args.gap)

    print("\n=== enumeration summary ===", flush=True)
    for s in summaries:
        print(json.dumps(s), flush=True)
    complete = [s for s in summaries if s["received"] == s["expected"]]
    if complete:
        worst = max(float(s["last_found_ms"]) for s in complete)
        worst_gap = max(float(s["max_gap_ms"]) for s in complete)
        print(
            f"\nslowest complete enumeration: {worst:.1f} ms; "
            f"largest inter-device gap: {worst_gap:.1f} ms",
            flush=True,
        )
    return 0


async def cmd_listen(conn_factory: Callable[[], DeakoConnection], args) -> int:
    """Capture unsolicited traffic without sending anything at all."""
    async with conn_factory() as conn:
        conn.capture.note(f"passive capture for {args.seconds}s")
        lines = await conn.read_lines(args.seconds)
        conn.capture.note(f"captured {len(lines)} lines")
    return 0


async def cmd_newlines(conn_factory: Callable[[], DeakoConnection], args) -> int:
    """Send bare newlines and record whatever comes back.

    Tests the hypothesis that the firmware echoes or reacts to blank lines,
    which would be a plausible source of the original whitespace flood.
    """
    async with conn_factory() as conn:
        conn.capture.note(
            f"sending {args.count} bare newlines at {args.interval}s intervals"
        )
        total = 0
        for index in range(1, args.count + 1):
            await conn.send_raw(args.newline)
            lines = await conn.read_lines(args.interval)
            total += len(lines)
            if index % 10 == 0:
                conn.capture.note(
                    f"after {index} newlines: {total} lines received so far"
                )
        conn.capture.note(f"total lines received during newline probe: {total}")
        conn.capture.note("draining for a final 30s")
        tail = await conn.read_lines(30)
        conn.capture.note(f"tail lines: {len(tail)}")
    return 0


async def cmd_control(conn_factory: Callable[[], DeakoConnection], args) -> int:
    """Actuate one device, and capture the response and any resulting EVENT."""
    state: dict[str, Any] = {"power": args.power == "on"}
    if args.dim is not None:
        state["dim"] = args.dim
    async with conn_factory() as conn:
        await conn.send(
            {"type": "CONTROL", "data": {"target": args.target, "state": state}}
        )
        await conn.read_lines(args.wait)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", required=True, help="node address")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--client", default=DEFAULT_CLIENT, help="client name sent as src")
    parser.add_argument("--log", type=Path, help="append the capture to this file")

    sub = parser.add_subparsers(dest="command", required=True)

    p_probe = sub.add_parser("probe", help="is this node free and answering?")
    p_probe.add_argument("--settle", type=float, default=5.0)
    p_probe.add_argument("--wait", type=float, default=10.0)
    p_probe.set_defaults(func=cmd_probe)

    p_enum = sub.add_parser("enumerate", help="measure device enumeration timing")
    p_enum.add_argument("--rounds", type=int, default=5)
    p_enum.add_argument("--timeout", type=float, default=120.0)
    p_enum.add_argument("--gap", type=float, default=5.0)
    p_enum.set_defaults(func=cmd_enumerate)

    p_listen = sub.add_parser("listen", help="passive capture")
    p_listen.add_argument("--seconds", type=float, default=300.0)
    p_listen.set_defaults(func=cmd_listen)

    p_nl = sub.add_parser("newlines", help="bare-newline / whitespace probe")
    p_nl.add_argument("--count", type=int, default=60)
    p_nl.add_argument("--interval", type=float, default=10.0)
    p_nl.add_argument("--newline", default="\n")
    p_nl.set_defaults(func=cmd_newlines)

    p_ctl = sub.add_parser("control", help="actuate one device")
    p_ctl.add_argument("--target", required=True, help="device uuid")
    p_ctl.add_argument("--power", choices=["on", "off"], required=True)
    p_ctl.add_argument("--dim", type=float)
    p_ctl.add_argument("--wait", type=float, default=10.0)
    p_ctl.set_defaults(func=cmd_control)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    capture = Capture(args.log)

    def factory() -> DeakoConnection:
        return DeakoConnection(args.host, args.port, args.client, capture)

    try:
        return asyncio.run(args.func(factory, args))
    except KeyboardInterrupt:
        return 130
    finally:
        capture.close()


if __name__ == "__main__":
    sys.exit(main())
