#!/usr/bin/env python3
"""Unattended battery measuring whether vendored pydeako 0.6.0 rebuilds its own
connection against a real Deako node, and what has to be re-requested when it does.

This is the O4/O7 measurement. It drives the *vendored* library -- the thing that
will run in the house -- rather than the raw protocol, because the question is
about 0.6.0's own reconnection logic, not about what the hub can be made to say.

Why a proxy
-----------
"The network dropped" cannot be produced on demand by asking a Deako node for
it, and waiting for the node to drop by itself is what makes this rig hostile.
So the library is pointed at a local fault-injecting proxy that forwards to the
hub and can be made to fail in the three ways that matter:

* ``blackhole`` -- the client's socket stays open and nothing ever arrives
  again. This is the case the ping watchdog exists for, and the only one that
  looks like a live connection while being dead.
* ``fin`` -- a clean close. This is the case that starves the asyncio event
  loop in stock 0.6.0 (see the O4 deviation in ``utils/_connection.py``); the
  proxy can reproduce it against real firmware without needing the hub to
  cooperate.
* ``refuse`` -- the node is simply gone, which is how reconnect churn gets
  measured without a node that has to be physically flipped.

Crucially the proxy *closes its upstream connection to the hub* when a fault is
injected, so the hub's single telnet slot is released. That is what makes an
out-of-band state change possible while the library is blind, which is the only
honest way to prove the resync corrects something.

Run it under Linux/WSL, not Windows: the vendored ``_SocketConnection`` passes
the port to ``sock_connect`` as a str, which getaddrinfo tolerates only on
POSIX. That is true of stock 0.3.1 and 0.6.0 alike and is left alone, because
the house runs Home Assistant on Linux.

Every phase prints its result the moment it has one, so a run cut short by the
node vanishing still yields everything measured up to that point.

Usage
-----
    # prove the harness against the in-process simulator first
    python3 tools/deako_watchdog_battery.py --simulator

    # then the real thing, unattended, waiting for a physically flipped node
    python3 tools/deako_watchdog_battery.py --host <addr> \
        --wait-for-node 1200 --log run.log
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import socket
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]

# Import the vendored copy, never an installed pydeako. Putting the integration
# directory on the path rather than the repo root avoids dragging in
# custom_components.deako, which imports Home Assistant.
sys.path.insert(0, str(REPO_ROOT / "custom_components" / "deako"))
sys.path.insert(0, str(REPO_ROOT))

import pydeako  # noqa: E402
from pydeako.deako import Deako  # noqa: E402

VENDORED_ROOT = REPO_ROOT / "custom_components" / "deako" / "pydeako"
if Path(pydeako.__file__).resolve().parent != VENDORED_ROOT.resolve():
    raise SystemExit(
        f"refusing to run: imported {pydeako.__file__}, expected the vendored "
        f"copy under {VENDORED_ROOT}"
    )

DEFAULT_PORT = 23
CLIENT_NAME = "deako_watchdog_battery"

# The watchdog pings every PING_WORKER_WAIT_S and only gives up after a whole
# further window with no pong, so detection alone is a ~10-20s affair.
WATCHDOG_BUDGET_S = 90.0


# --------------------------------------------------------------------------
# Recording
# --------------------------------------------------------------------------


class Journal:
    """Timestamped log plus a machine-readable record of every finding."""

    def __init__(self, path: Path | None) -> None:
        self._fh = path.open("a", encoding="utf-8") if path else None
        self.findings: list[dict[str, Any]] = []
        self.t0 = time.monotonic()

    def note(self, text: str) -> None:
        line = (
            f"{datetime.now().isoformat(timespec='milliseconds')}"
            f"\t+{time.monotonic() - self.t0:7.1f}s\t{text}"
        )
        print(line, flush=True)
        if self._fh:
            self._fh.write(line + "\n")
            self._fh.flush()

    def record(self, phase: str, **fields: Any) -> None:
        entry = {"phase": phase, **fields}
        self.findings.append(entry)
        self.note(f"RESULT {json.dumps(entry, default=str)}")

    def close(self) -> None:
        if self._fh:
            self._fh.close()


class LoopLagSampler:
    """Watch for event-loop starvation while everything else runs.

    #14 found that stock 0.6.0 spins on EOF without ever suspending, which
    stops the whole loop rather than merely the integration. A run that claims
    recovery while the loop was wedged would be claiming the wrong thing, so
    the claim is measured rather than assumed.
    """

    def __init__(self, interval: float = 0.1) -> None:
        self.interval = interval
        self.max_lag_ms = 0.0
        self._task: asyncio.Task | None = None

    async def _run(self) -> None:
        while True:
            before = time.monotonic()
            await asyncio.sleep(self.interval)
            lag = (time.monotonic() - before - self.interval) * 1000.0
            self.max_lag_ms = max(self.max_lag_ms, lag)

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    def reset(self) -> None:
        self.max_lag_ms = 0.0

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task


# --------------------------------------------------------------------------
# The fault-injecting proxy
# --------------------------------------------------------------------------


class FaultProxy:
    """A TCP proxy in front of the hub that can fail on command.

    One upstream connection at a time, matching the hub's exclusive telnet
    server. Injecting a fault always closes upstream, so the hub's slot is
    freed and the harness can talk to it directly while the library is blind.
    """

    def __init__(self, hub_host: str, hub_port: int, journal: Journal) -> None:
        self.hub_host = hub_host
        self.hub_port = hub_port
        self.journal = journal
        self.port = 0
        self.accepting = True
        self.client_connections = 0
        self.upstream_connections = 0
        self.upstream_eof_seen = False
        self.upstream_reset_seen = False
        self._server: asyncio.AbstractServer | None = None
        self._client_writer: asyncio.StreamWriter | None = None
        self._upstream_writer: asyncio.StreamWriter | None = None
        self._pumps: set[asyncio.Task] = set()

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._handle_client, "127.0.0.1", 0
        )
        self.port = self._server.sockets[0].getsockname()[1]
        self.journal.note(
            f"proxy listening on 127.0.0.1:{self.port} -> "
            f"{self.hub_host}:{self.hub_port}"
        )

    @property
    def address(self) -> str:
        return f"127.0.0.1:{self.port}"

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self.client_connections += 1
        index = self.client_connections
        if not self.accepting:
            self.journal.note(f"proxy: client #{index} rejected (fault armed)")
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()
            return

        try:
            up_reader, up_writer = await asyncio.wait_for(
                asyncio.open_connection(self.hub_host, self.hub_port), timeout=10.0
            )
        except (OSError, asyncio.TimeoutError) as exc:
            self.journal.note(f"proxy: upstream connect failed ({exc})")
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()
            return

        self.upstream_connections += 1
        self.journal.note(
            f"proxy: client #{index} bridged to upstream "
            f"#{self.upstream_connections}"
        )
        self._client_writer = writer
        self._upstream_writer = up_writer

        for src, dst, label in (
            (reader, up_writer, "c->h"),
            (up_reader, writer, "h->c"),
        ):
            task = asyncio.create_task(self._pump(src, dst, label))
            self._pumps.add(task)
            task.add_done_callback(self._pumps.discard)

    async def _pump(
        self, src: asyncio.StreamReader, dst: asyncio.StreamWriter, label: str
    ) -> None:
        """Forward one direction, propagating only closes the hub really made.

        A deliberate fault cancels this task, and cancellation must not close
        the client socket: leaving it open with nothing arriving is precisely
        what a blackhole is, and it is the only fault the ping watchdog can be
        the thing that catches.
        """
        try:
            while True:
                data = await src.read(4096)
                if not data:
                    if label == "h->c":
                        # The hub closed cleanly. Worth knowing: a FIN takes
                        # the path that used to hang stock 0.6.0, an RST
                        # raises and takes the ordinary error path.
                        self.upstream_eof_seen = True
                        self.journal.note("proxy: HUB CLOSED CLEANLY (FIN)")
                    break
                dst.write(data)
                await dst.drain()
        except asyncio.CancelledError:
            return
        except (ConnectionResetError, BrokenPipeError):
            if label == "h->c":
                self.upstream_reset_seen = True
                self.journal.note("proxy: HUB CONNECTION RESET (RST)")
        except OSError:
            pass
        # Only a close the hub actually made is propagated onward.
        with contextlib.suppress(OSError):
            dst.close()

    async def _drop_bridge(self) -> None:
        for task in list(self._pumps):
            task.cancel()
        self._pumps.clear()
        if self._upstream_writer is not None:
            self._upstream_writer.close()
            with contextlib.suppress(OSError, asyncio.TimeoutError):
                await asyncio.wait_for(self._upstream_writer.wait_closed(), 2.0)
            self._upstream_writer = None

    async def blackhole(self) -> None:
        """Client socket stays open; nothing ever arrives again."""
        self.journal.note("FAULT: blackhole -- upstream closed, client left hanging")
        self.accepting = False
        await self._drop_bridge()

    async def fin(self) -> None:
        """Close the client socket cleanly, the way a polite peer would."""
        self.journal.note("FAULT: clean close (FIN) toward the client")
        self.accepting = False
        await self._drop_bridge()
        if self._client_writer is not None:
            self._client_writer.close()
            with contextlib.suppress(OSError, asyncio.TimeoutError):
                await asyncio.wait_for(self._client_writer.wait_closed(), 2.0)
            self._client_writer = None

    async def reset(self) -> None:
        """Abort the client socket, so the library sees ECONNRESET."""
        self.journal.note("FAULT: abortive close (RST) toward the client")
        self.accepting = False
        await self._drop_bridge()
        if self._client_writer is not None:
            sock = self._client_writer.get_extra_info("socket")
            if sock is not None:
                with contextlib.suppress(OSError):
                    sock.setsockopt(
                        socket.SOL_SOCKET,
                        socket.SO_LINGER,
                        # linger on, timeout 0 -> RST rather than FIN
                        b"\x01\x00\x00\x00\x00\x00\x00\x00",
                    )
            self._client_writer.close()
            with contextlib.suppress(OSError, asyncio.TimeoutError):
                await asyncio.wait_for(self._client_writer.wait_closed(), 2.0)
            self._client_writer = None

    def heal(self) -> None:
        self.journal.note("HEAL: proxy accepting again")
        self.accepting = True

    async def stop(self) -> None:
        await self._drop_bridge()
        if self._server is not None:
            self._server.close()
            with contextlib.suppress(OSError):
                await self._server.wait_closed()


# --------------------------------------------------------------------------
# Raw protocol helpers -- used where the library is deliberately not the tool
# --------------------------------------------------------------------------


async def raw_exchange(
    host: str,
    port: int,
    messages: list[dict[str, Any]],
    listen_s: float,
    journal: Journal,
) -> list[dict[str, Any]]:
    """Open a direct connection, send messages, collect whatever comes back."""
    import uuid as uuid_mod

    received: list[dict[str, Any]] = []
    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(host, port), timeout=10.0
    )
    try:
        for message in messages:
            message.setdefault("transactionId", str(uuid_mod.uuid4()))
            message.setdefault("src", CLIENT_NAME)
            message.setdefault("dst", "deako")
            writer.write(json.dumps(message, separators=(",", ":")).encode() + b"\r\n")
            await writer.drain()
            journal.note(f"raw --> {json.dumps(message)}")

        deadline = time.monotonic() + listen_s
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            try:
                line = await asyncio.wait_for(reader.readline(), timeout=remaining)
            except asyncio.TimeoutError:
                break
            if not line:
                break
            text = line.decode(errors="replace").strip()
            if not text:
                continue
            try:
                received.append(json.loads(text))
            except (json.JSONDecodeError, ValueError):
                journal.note(f"raw <-- (unparsed) {text!r}")
    finally:
        writer.close()
        with contextlib.suppress(OSError):
            await writer.wait_closed()
    return received


async def wait_for_node(host: str, port: int, timeout: float, journal: Journal) -> bool:
    """Block until the node accepts a connection, so a wake can be caught."""
    journal.note(f"waiting up to {timeout:.0f}s for {host}:{port} to accept")
    start = time.monotonic()
    reported = 0.0
    while time.monotonic() - start < timeout:
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=2.0
            )
        except (OSError, asyncio.TimeoutError):
            waited = time.monotonic() - start
            if waited - reported >= 30:
                reported = waited
                journal.note(f"  still waiting ({waited:.0f}s)")
            await asyncio.sleep(1.0)
            continue
        writer.close()
        with contextlib.suppress(OSError):
            await writer.wait_closed()
        waited = time.monotonic() - start
        journal.note(f"node accepted a connection after {waited:.1f}s")
        return True
    journal.note("node never came back within the timeout")
    return False


async def wait_until(
    predicate: Callable[[], bool], timeout: float, interval: float = 0.5
) -> float | None:
    """Return seconds waited once predicate holds, or None on timeout."""
    start = time.monotonic()
    deadline = start + timeout
    while time.monotonic() < deadline:
        if predicate():
            return time.monotonic() - start
        await asyncio.sleep(interval)
    return time.monotonic() - start if predicate() else None


# --------------------------------------------------------------------------
# Phases
# --------------------------------------------------------------------------


async def phase_pong_echo(host: str, port: int, journal: Journal) -> None:
    """Does the real firmware echo transactionId on a PONG?

    #14's pong-matching fix correlates the reply against the id sent, but
    accepts an id-less pong because nothing proved the echo. Settling this is
    seconds of hardware time and either deletes the fallback or leaves the
    correlation knowingly inert.

    Retried, because a node that has just woken accepts TCP before it is
    serving and resets the first connection -- observed on the first hardware
    run, which cost the measurement an entire window.
    """
    last_error: str | None = None
    for attempt in range(1, 6):
        sent_id = f"wf19-ping-{attempt:04d}"
        try:
            replies = await raw_exchange(
                host, port, [{"type": "PING", "transactionId": sent_id}], 8.0, journal
            )
        except (OSError, asyncio.TimeoutError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            journal.note(f"pong probe attempt {attempt} failed ({last_error}); retrying")
            await asyncio.sleep(3.0)
            continue

        # The reply to a PING is itself typed "PING" -- pydeako's
        # ResponseType.PONG is the string "PING". There is no distinct PONG
        # type on the wire.
        pongs = [m for m in replies if str(m.get("type", "")).upper() == "PING"]
        if not pongs and attempt < 5:
            last_error = "no pong in the reply window"
            journal.note(f"pong probe attempt {attempt}: no pong; retrying")
            await asyncio.sleep(3.0)
            continue

        echoed = any(p.get("transactionId") == sent_id for p in pongs)
        journal.record(
            "pong_echo",
            attempts=attempt,
            sent_transaction_id=sent_id,
            pong_count=len(pongs),
            first_pong=pongs[0] if pongs else None,
            echoes_transaction_id=echoed,
            other_traffic=len(replies) - len(pongs),
        )
        return

    journal.record("pong_echo", attempts=5, error=last_error or "unknown")


async def phase_scene_verbs(
    host: str, port: int, probe_name: str, journal: Journal, gap: float = 0.6
) -> None:
    """Enumerate the hub's verb space, using error codes as the oracle.

    Out of scope for this map, but the expensive part of the experiment is
    getting the node awake, so it rides along with a window that already
    exists. Hardware testing in October 2025 established that this firmware
    answers an unknown message type with ``REQUEST_UNKNOWN``, a known type with
    missing fields with ``REQUEST_MALFORMED``, and a known type with bad values
    with ``REQUEST_INVALID``. So **any candidate answering something other than
    REQUEST_UNKNOWN names a verb the firmware actually knows.**

    Two design constraints, both learned the hard way:

    * #17's probe run was **confounded** -- the node died partway through and
      its silence was read as "ignored". Silence is not a valid answer to
      anything, so every candidate is **bracketed** by a known-good command.
      A negative is only trustworthy if a positive answers after it.
    * The window may be **20 seconds**. Rather than waiting on each candidate
      in turn, the whole set is sent as one burst with distinct transaction
      ids and correlated on the way back, which collapses minutes into
      seconds. The closing bracket proves the burst was processed to the end.
    """
    import uuid as uuid_mod

    reader = writer = None
    for attempt in range(1, 6):
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=10.0
            )
            break
        except (OSError, asyncio.TimeoutError) as exc:
            journal.note(f"scene: connect attempt {attempt} failed ({exc}); retrying")
            await asyncio.sleep(2.0)
    if writer is None or reader is None:
        journal.record("scene_verbs", error="could not connect")
        return

    sent: dict[str, str] = {}

    async def send(label: str, message: dict[str, Any]) -> None:
        tid = str(uuid_mod.uuid4())
        message["transactionId"] = tid
        message.setdefault("src", CLIENT_NAME)
        message.setdefault("dst", "deako")
        sent[tid] = label
        writer.write(json.dumps(message, separators=(",", ":")).encode() + b"\r\n")
        await writer.drain()

    try:
        # Find the one load that is safe to move. Names are deliberately not
        # journalled: this is the whole house inventory.
        await send("device_list", {"type": "DEVICE_LIST"})
        probe_uuid: str | None = None
        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline:
            try:
                line = await asyncio.wait_for(
                    reader.readline(), timeout=deadline - time.monotonic()
                )
            except asyncio.TimeoutError:
                break
            if not line:
                break
            try:
                msg = json.loads(line.decode(errors="replace").strip())
            except (json.JSONDecodeError, ValueError):
                continue
            data = msg.get("data") or {}
            if msg.get("type") == "DEVICE_FOUND" and str(
                data.get("name", "")
            ).strip().lower() == probe_name.strip().lower():
                probe_uuid = data.get("uuid")
                break

        if probe_uuid is None:
            journal.record("scene_verbs", error=f"probe device {probe_name!r} not found")
            return
        journal.note(f"scene: bracketing with {probe_name} (uuid withheld)")

        def bracket(dim: int) -> dict[str, Any]:
            # power stays true throughout; this only ever changes brightness.
            return {
                "type": "CONTROL",
                "data": {"target": probe_uuid, "state": {"power": True, "dim": dim}},
            }

        # A multi-target CONTROL is probed with the SAME uuid twice, so the
        # question "is a list accepted at all" is answered without moving a
        # second real light. Escalate only if a list is accepted.
        pair = [probe_uuid, probe_uuid]
        candidates: list[tuple[str, dict[str, Any]]] = [
            ("SCENE", {"type": "SCENE"}),
            ("SCENE_LIST", {"type": "SCENE_LIST"}),
            ("GROUP", {"type": "GROUP"}),
            ("GROUP_LIST", {"type": "GROUP_LIST"}),
            ("GROUP_CONTROL", {"type": "GROUP_CONTROL"}),
            ("ACTIVATE", {"type": "ACTIVATE"}),
            ("TRIGGER", {"type": "TRIGGER"}),
            ("PRESET", {"type": "PRESET"}),
            ("MACRO", {"type": "MACRO"}),
            ("BUTTON_PRESS", {"type": "BUTTON_PRESS"}),
            ("DEVICE_POLL", {"type": "DEVICE_POLL"}),
            (
                "CONTROL:target=[uuid,uuid]",
                {"type": "CONTROL", "data": {"target": pair, "state": {"power": True, "dim": 55}}},
            ),
            (
                "CONTROL:targets=[uuid,uuid]",
                {"type": "CONTROL", "data": {"targets": pair, "state": {"power": True, "dim": 55}}},
            ),
            (
                "CONTROL:target=csv",
                {
                    "type": "CONTROL",
                    "data": {
                        "target": ",".join(pair),
                        "state": {"power": True, "dim": 55},
                    },
                },
            ),
        ]

        async def drain(seconds: float) -> None:
            """Read whatever is available for a bounded time."""
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                try:
                    line = await asyncio.wait_for(
                        reader.readline(), timeout=deadline - time.monotonic()
                    )
                except asyncio.TimeoutError:
                    return
                if not line:
                    journal.note("scene: hub closed the connection")
                    raise ConnectionResetError("hub closed mid-probe")
                try:
                    msg = json.loads(line.decode(errors="replace").strip())
                except (json.JSONDecodeError, ValueError):
                    continue
                tid = msg.get("transactionId")
                label = sent.get(tid) if tid else None
                if label is None:
                    # EVENTs for the whole house land here; keep only the shape.
                    unmatched.append({"type": msg.get("type")})
                else:
                    replies.setdefault(label, []).append(msg)

        replies: dict[str, list[dict[str, Any]]] = {}
        unmatched: list[dict[str, Any]] = []

        def answered(label: str) -> bool:
            return bool(replies.get(label))

        # One message at a time, with a gap. The previous run sent the whole
        # set back to back and only the FIRST was ever answered, while the hub
        # went on streaming events -- consistent with several messages landing
        # in one TCP segment and the firmware reading only one. Both known
        # clients send one message at a time, so match that.
        dim_cycle = iter([45, 50, 40, 55, 35, 60, 42])
        bracket_index = 0
        confounded_at: str | None = None

        async def send_bracket(tag: str) -> bool:
            nonlocal bracket_index
            bracket_index += 1
            label = f"bracket_{bracket_index}_{tag}"
            await send(label, bracket(next(dim_cycle, 45)))
            await drain(gap * 3)
            return answered(label)

        if not await send_bracket("open"):
            journal.record(
                "scene_verbs",
                error="the opening bracket went unanswered; the node was not "
                "serving and nothing after it would mean anything",
            )
            return

        results: dict[str, str] = {}
        for index, (label, message) in enumerate(candidates, 1):
            await send(label, message)
            await drain(gap)
            # Re-establish liveness every few candidates, so a death is
            # localised rather than poisoning the whole set.
            if index % 3 == 0 or index == len(candidates):
                if not await send_bracket(f"after_{label}"):
                    confounded_at = label
                    journal.note(
                        f"scene: bracket after {label} went unanswered -- "
                        "everything from here is confounded"
                    )
                    break
            results[label] = "answered" if answered(label) else "SILENCE"

        classified = {}
        for label, _ in candidates:
            if label not in results:
                classified[label] = {"answer": "NOT REACHED"}
                continue
            got = replies.get(label, [])
            if not got:
                classified[label] = {"answer": "SILENCE"}
            else:
                first = got[0]
                classified[label] = {
                    "answer": first.get("type"),
                    "status": first.get("status"),
                    "body": first,
                }

        journal.record(
            "scene_verbs",
            method="one message at a time, bracketed every 3 candidates",
            gap_s=gap,
            confounded_at=confounded_at,
            negatives_trustworthy=confounded_at is None,
            candidates=classified,
            unmatched_traffic=len(unmatched),
            note="a verb the firmware knows answers something other than "
            "REQUEST_UNKNOWN; SILENCE counts only where a later bracket answered",
        )
    finally:
        writer.close()
        with contextlib.suppress(OSError):
            await writer.wait_closed()


async def phase_payload_variants(
    host: str, port: int, probe_name: str, journal: Journal, gap: float = 0.6
) -> None:
    """Probe multi-target CONTROL forms, each on its own fresh connection.

    Both this session's first sweep and #17's original run stopped getting
    answers at exactly the same place: the first ``CONTROL`` carrying a
    non-string ``target``. If that message kills the connection, then every
    variant after it in a shared sequence is untestable, and #17's "silently
    ignored" readings were never readings at all.

    So each variant gets a fresh connection, bracketed by a known-good
    single-target command **before and after**. The closing bracket is the
    whole experiment: if it answers, the variant was genuinely ignored; if it
    does not, the variant **killed the connection**, which is a finding in its
    own right rather than a failed probe.
    """
    import uuid as uuid_mod

    probe_uuid: str | None = None
    outcomes: dict[str, Any] = {}

    async def one_connection(label: str, variant: dict[str, Any] | None) -> dict[str, Any]:
        nonlocal probe_uuid
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=10.0
        )
        sent: dict[str, str] = {}
        replies: dict[str, list[dict[str, Any]]] = {}
        events: list[Any] = []

        async def send(tag: str, message: dict[str, Any]) -> None:
            tid = str(uuid_mod.uuid4())
            message["transactionId"] = tid
            message.setdefault("src", CLIENT_NAME)
            message.setdefault("dst", "deako")
            sent[tid] = tag
            writer.write(json.dumps(message, separators=(",", ":")).encode() + b"\r\n")
            await writer.drain()

        async def drain(seconds: float) -> bool:
            """Read for a bounded time. False if the hub closed on us."""
            nonlocal probe_uuid
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                try:
                    line = await asyncio.wait_for(
                        reader.readline(), timeout=deadline - time.monotonic()
                    )
                except asyncio.TimeoutError:
                    return True
                if not line:
                    return False
                try:
                    msg = json.loads(line.decode(errors="replace").strip())
                except (json.JSONDecodeError, ValueError):
                    continue
                tag = sent.get(msg.get("transactionId"))
                if tag:
                    replies.setdefault(tag, []).append(msg)
                elif msg.get("type") == "EVENT":
                    # An EVENT for the probe device is the only proof that a
                    # command actually moved something. `status: ok` alone
                    # does not mean the hub routed the message anywhere.
                    data = msg.get("data") or {}
                    if probe_uuid and data.get("target") == probe_uuid:
                        events.append(data.get("state"))
                elif probe_uuid is None:
                    data = msg.get("data") or {}
                    if msg.get("type") == "DEVICE_FOUND" and str(
                        data.get("name", "")
                    ).strip().lower() == probe_name.strip().lower():
                        probe_uuid = data.get("uuid")
            return True

        try:
            if probe_uuid is None:
                await send("device_list", {"type": "DEVICE_LIST"})
                await drain(6.0)
                if probe_uuid is None:
                    return {"error": f"probe device {probe_name!r} not found"}

            def bracket(dim: int) -> dict[str, Any]:
                return {
                    "type": "CONTROL",
                    "data": {"target": probe_uuid, "state": {"power": True, "dim": dim}},
                }

            await send("open", bracket(45))
            alive = await drain(gap * 3)
            if not replies.get("open"):
                return {"error": "opening bracket unanswered; node not serving"}

            if variant is not None:
                await send("variant", variant)
                # The confirming EVENT lands ~2.4 s after the acknowledgment
                # (#17), so a short drain reads as "nothing moved" when the
                # truth is "not yet". Wait long enough to see it.
                alive = await drain(max(gap * 2, 5.0))

            await send("close", bracket(38))
            alive = await drain(gap * 4) and alive
            answered_close = bool(replies.get("close"))
            variant_reply = (replies.get("variant") or [None])[0]
            return {
                "variant_answered": variant_reply,
                "probe_device_events": events,
                "connection_survived": answered_close,
                "verdict": (
                    "ignored, connection intact"
                    if answered_close and variant_reply is None
                    else "answered"
                    if variant_reply is not None
                    else "KILLED THE CONNECTION"
                ),
            }
        finally:
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()

    async def attempt(label: str, variant: dict[str, Any] | None) -> dict[str, Any]:
        """Run one probe, retrying transport failures.

        A freshly woken node resets the first connection -- measured twice in
        #19, and it cost this probe an entire window when it was not handled
        here. A reset before the variant is sent says nothing about the
        variant, so it must be retried rather than recorded.
        """
        last: dict[str, Any] = {}
        for tries in range(1, 5):
            try:
                result = await one_connection(label, variant)
            except (OSError, asyncio.TimeoutError) as exc:
                # Only a reset *after* the variant was sent is evidence about
                # the variant. Before that, it is just a cold node.
                if variant is not None and probe_uuid is not None:
                    return {
                        "verdict": "KILLED THE CONNECTION",
                        "error": f"{type(exc).__name__}: {exc}",
                        "attempts": tries,
                    }
                last = {"error": f"{type(exc).__name__}: {exc}"}
                await asyncio.sleep(2.0)
                continue
            if result.get("error") and probe_uuid is None:
                last = result
                await asyncio.sleep(2.0)
                continue
            result["attempts"] = tries
            return result
        return last or {"error": "exhausted retries"}

    # A control run with no variant at all, proving the rig itself does not
    # kill connections -- otherwise a kill proves nothing.
    outcomes["control_no_variant"] = await attempt("control", None)

    variants = [
        (
            "target=[uuid,uuid]",
            lambda u: {"type": "CONTROL", "data": {"target": [u, u], "state": {"power": True, "dim": 55}}},
        ),
        (
            "targets=[uuid,uuid]",
            lambda u: {"type": "CONTROL", "data": {"targets": [u, u], "state": {"power": True, "dim": 55}}},
        ),
        (
            "target=csv",
            lambda u: {"type": "CONTROL", "data": {"target": f"{u},{u}", "state": {"power": True, "dim": 55}}},
        ),
        (
            "target=missing",
            lambda _u: {"type": "CONTROL", "data": {"state": {"power": True, "dim": 55}}},
        ),
        # Disambiguates the "csv was accepted" result. If a deliberately
        # corrupted target ALSO returns ok, then ok means "message parsed",
        # not "message routed", and the csv result carries no information.
        (
            "target=uuid+garbage",
            lambda u: {
                "type": "CONTROL",
                "data": {"target": f"{u}ZZZZ", "state": {"power": True, "dim": 52}},
            },
        ),
        # Same csv form again, this time watching for an EVENT naming the
        # probe device -- the only proof the command actually moved anything.
        (
            "target=csv (event-watched)",
            lambda u: {
                "type": "CONTROL",
                "data": {"target": f"{u},{u}", "state": {"power": True, "dim": 58}},
            },
        ),
        # The decisive experiment. Both csv and a corrupted id returned ok AND
        # moved the device, which is consistent with the hub matching the
        # *leading* uuid and ignoring the rest. If that is what it does, a csv
        # target is a single-target command wearing a disguise, and no second
        # light is ever addressed.
        #
        # Real-first should move the probe device; bogus-first should not.
        # Neither form can touch a second real light, so this settles
        # multi-target semantics without actuating anything else.
        (
            "target=real,bogus",
            lambda u: {
                "type": "CONTROL",
                "data": {
                    "target": f"{u},00000000-0000-4000-8000-000000000000",
                    "state": {"power": True, "dim": 63},
                },
            },
        ),
        (
            "target=bogus,real",
            lambda u: {
                "type": "CONTROL",
                "data": {
                    "target": f"00000000-0000-4000-8000-000000000000,{u}",
                    "state": {"power": True, "dim": 67},
                },
            },
        ),
    ]
    for label, build in variants:
        if probe_uuid is None:
            outcomes[label] = {"error": "no probe uuid"}
            continue
        outcomes[label] = await attempt(label, build(probe_uuid))
        await asyncio.sleep(0.5)

    journal.record(
        "payload_variants",
        method="one fresh connection per variant, bracketed before and after",
        outcomes=outcomes,
        note="a variant that leaves the closing bracket unanswered killed the "
        "connection; that is why a shared-connection sweep cannot test these",
    )


async def phase_enumerate(client: Deako, journal: Journal) -> dict[str, Any]:
    """Time a full enumeration through the library, not the raw socket."""
    start = time.monotonic()
    await client.find_devices()
    elapsed = time.monotonic() - start
    devices = client.get_devices()
    journal.record(
        "enumerate",
        expected=client.expected_devices,
        received=len(devices),
        seconds=round(elapsed, 3),
        complete=len(devices) == client.expected_devices,
    )
    return devices


def pick_probe_device(
    devices: dict[str, Any], preferred_name: str | None, journal: Journal
) -> dict[str, Any] | None:
    """Choose a dimmable device to use for the out-of-band change.

    Actuation on this rig moves real lights, so the caller names the one load
    that is safe to touch and nothing is picked at random.
    """
    if preferred_name:
        for uuid, device in devices.items():
            if device.get("name", "").strip().lower() == preferred_name.strip().lower():
                if not device.get("dimmable"):
                    journal.note(
                        f"probe device {preferred_name!r} is not dimmable; "
                        "the out-of-band change needs dim, refusing to use power"
                    )
                    return None
                return {"uuid": uuid, **device}
        journal.note(f"probe device {preferred_name!r} not found in enumeration")
    return None


async def phase_fault_recovery(
    *,
    name: str,
    inject: Callable[[], Awaitable[None]],
    client: Deako,
    proxy: FaultProxy,
    lag: LoopLagSampler,
    journal: Journal,
    probe: dict[str, Any] | None,
    hub_host: str,
    hub_port: int,
    outage_s: float,
) -> None:
    """Inject one fault, then measure detection, recovery and resync."""
    journal.note(f"--- phase {name} ---")
    lag.reset()
    if not client.is_connected():
        journal.record(name, skipped="not connected before the fault")
        return

    before_upstreams = proxy.upstream_connections
    fault_at = time.monotonic()
    await inject()

    detected = await wait_until(
        lambda: not client.is_connected(), WATCHDOG_BUDGET_S
    )
    journal.record(
        f"{name}.detect",
        detected=detected is not None,
        seconds=round(detected, 1) if detected is not None else None,
        max_loop_lag_ms=round(lag.max_lag_ms, 1),
    )
    if detected is None:
        journal.note(
            f"{name}: the library never noticed; skipping the rest of this phase"
        )
        proxy.heal()
        return

    # The hub's slot is free while the library is blind, so change something
    # out of band. Without this the resync would only ever confirm state that
    # never moved, which proves nothing.
    changed_to: int | None = None
    if probe is not None:
        current = probe.get("state", {}).get("dim")
        changed_to = 30 if current != 30 else 60
        try:
            await raw_exchange(
                hub_host,
                hub_port,
                [
                    {
                        "type": "CONTROL",
                        "data": {
                            "target": probe["uuid"],
                            # power stays true: powering this load off is what
                            # is suspected of taking the node off the network.
                            "state": {"power": True, "dim": changed_to},
                        },
                    }
                ],
                6.0,
                journal,
            )
            journal.note(
                f"{name}: out-of-band change while blind -- "
                f"{probe['name']} dim -> {changed_to}"
            )
        except (OSError, asyncio.TimeoutError) as exc:
            journal.note(f"{name}: out-of-band change failed ({exc})")
            changed_to = None

    remaining = outage_s - (time.monotonic() - fault_at)
    if remaining > 0:
        await asyncio.sleep(remaining)
    proxy.heal()
    heal_at = time.monotonic()

    reconnected = await wait_until(client.is_connected, WATCHDOG_BUDGET_S)
    journal.record(
        f"{name}.reconnect",
        reconnected=reconnected is not None,
        seconds_after_heal=round(reconnected, 1) if reconnected is not None else None,
        seconds_since_fault=round(heal_at - fault_at + (reconnected or 0), 1),
        connection_attempts=proxy.client_connections,
        upstreams_opened=proxy.upstream_connections - before_upstreams,
        max_loop_lag_ms=round(lag.max_lag_ms, 1),
    )
    if reconnected is None:
        return

    if changed_to is not None:
        corrected = await wait_until(
            lambda: client.get_state(probe["uuid"]) is not None
            and client.get_state(probe["uuid"]).get("dim") == changed_to,
            45.0,
        )
        state = client.get_state(probe["uuid"])
        journal.record(
            f"{name}.resync",
            device=probe["name"],
            expected_dim=changed_to,
            observed_state=state,
            corrected=corrected is not None,
            seconds=round(corrected, 1) if corrected is not None else None,
            callbacks_fired=probe["callbacks"][0],
        )
        probe["state"] = dict(state or {})
    else:
        journal.record(f"{name}.resync", skipped="no safe out-of-band change available")


async def phase_churn(hub_host: str, hub_port: int, journal: Journal) -> None:
    """How hard does 0.6.0 retry against a node that is simply gone?

    0.6.0 has no reconnect backoff. Against a node that disappears for minutes
    at a time that is worth watching rather than assuming, so this points the
    library at a closed port and counts.
    """
    journal.note("--- phase churn ---")
    attempts = 0
    server_free_port = 0
    # Bind and immediately close, so the port is one nothing is listening on.
    probe_sock = socket.socket()
    probe_sock.bind(("127.0.0.1", 0))
    server_free_port = probe_sock.getsockname()[1]
    probe_sock.close()

    async def counting_address() -> tuple[str, str]:
        nonlocal attempts
        attempts += 1
        return f"127.0.0.1:{server_free_port}", "dead-node"

    lag = LoopLagSampler()
    lag.start()
    client = Deako(counting_address, client_name=CLIENT_NAME)
    window = 60.0
    start = time.monotonic()
    try:
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(client.connect(), timeout=window)
        while time.monotonic() - start < window:
            await asyncio.sleep(1.0)
    finally:
        await client.disconnect()
        await lag.stop()

    elapsed = time.monotonic() - start
    journal.record(
        "churn",
        window_s=round(elapsed, 1),
        connect_attempts=attempts,
        attempts_per_minute=round(attempts / elapsed * 60, 1),
        max_loop_lag_ms=round(lag.max_lag_ms, 1),
        note="0.6.0 has no backoff; the 10s connect timeout is the only gate",
    )


async def phase_node_restart(
    client: Deako,
    proxy: FaultProxy,
    journal: Journal,
    hold_s: float,
) -> None:
    """Watch an unassisted recovery across whatever the node does by itself.

    Nothing is injected here. The library is simply left running while the node
    is power-cycled or drops off on its own, which is the failure the house
    actually sees.
    """
    journal.note(f"--- phase node_restart: holding for {hold_s:.0f}s ---")
    transitions: list[tuple[float, bool]] = []
    last = client.is_connected()
    start = time.monotonic()
    transitions.append((0.0, last))
    while time.monotonic() - start < hold_s:
        await asyncio.sleep(1.0)
        now = client.is_connected()
        if now != last:
            offset = round(time.monotonic() - start, 1)
            transitions.append((offset, now))
            journal.note(f"node_restart: connected={now} at +{offset}s")
            last = now
    journal.record(
        "node_restart",
        held_s=round(time.monotonic() - start, 1),
        transitions=transitions,
        ended_connected=client.is_connected(),
        client_connections=proxy.client_connections,
        upstreams_opened=proxy.upstream_connections,
        hub_closed_cleanly=proxy.upstream_eof_seen,
        hub_reset=proxy.upstream_reset_seen,
    )


# --------------------------------------------------------------------------
# Simulator harness, so the battery is debugged before hardware sees it
# --------------------------------------------------------------------------


async def start_simulator(port: int, http_port: int, probe_name: str):
    from deako_simulator import server as server_module
    from deako_simulator.config import Config, NetworkConfig
    from deako_simulator.models import Device, DeviceState
    from deako_simulator.quirks import QuirkManager
    from deako_simulator.server import DeakoSimulator
    from deako_simulator.state import SimulatorState

    async def _no_mdns(*_args, **_kwargs):
        """The real house is on this LAN. Advertise nothing."""
        return None, []

    server_module.register_mdns = _no_mdns

    devices = [
        Device(
            uuid="11111111-1111-4111-8111-111111111111",
            name=probe_name,
            capabilities=["power", "dim"],
            state=DeviceState(power=True, dim=100),
        ),
        Device(
            uuid="33333333-3333-4333-8333-333333333333",
            name="Plain Switch",
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
    simulator = DeakoSimulator(
        SimulatorState(config.devices), config, QuirkManager()
    )
    await simulator.start()
    return simulator


# --------------------------------------------------------------------------


async def run(args: argparse.Namespace) -> int:
    journal = Journal(args.log)
    journal.note(f"vendored library: {Path(pydeako.__file__).resolve().parent}")

    simulator = None
    hub_host, hub_port = args.host, args.port
    if args.simulator:
        simulator = await start_simulator(
            args.sim_port, args.sim_http_port, args.probe_device
        )
        hub_host, hub_port = "127.0.0.1", args.sim_port
        journal.note(f"simulator listening on {hub_host}:{hub_port}")

    phases = set(args.phases)
    lag = LoopLagSampler()
    lag.start()
    proxy = FaultProxy(hub_host, hub_port, journal)
    client: Deako | None = None
    try:
        if args.wait_for_node and not await wait_for_node(
            hub_host, hub_port, args.wait_for_node, journal
        ):
            journal.record("wait_for_node", reached=False)
            return 2

        if "pong" in phases:
            journal.note("--- phase pong_echo ---")
            try:
                await phase_pong_echo(hub_host, hub_port, journal)
            except (OSError, asyncio.TimeoutError) as exc:
                journal.record("pong_echo", error=str(exc))

        if "scene" in phases:
            journal.note("--- phase scene_verbs ---")
            try:
                await phase_scene_verbs(
                    hub_host, hub_port, args.probe_device, journal
                )
            except (OSError, asyncio.TimeoutError) as exc:
                journal.record("scene_verbs", error=str(exc))

        if "payload" in phases:
            journal.note("--- phase payload_variants ---")
            try:
                await phase_payload_variants(
                    hub_host, hub_port, args.probe_device, journal
                )
            except (OSError, asyncio.TimeoutError) as exc:
                journal.record("payload_variants", error=str(exc))

        needs_hub = phases & {"enumerate", "blackhole", "fin", "reset", "restart"}
        if needs_hub:
            await proxy.start()

            async def get_address() -> tuple[str, str]:
                return proxy.address, "spare"

            client = Deako(get_address, client_name=CLIENT_NAME)
            journal.note("--- phase connect ---")
            connect_start = time.monotonic()
            await asyncio.wait_for(client.connect(), timeout=30)
            journal.record(
                "connect",
                connected=client.is_connected(),
                seconds=round(time.monotonic() - connect_start, 3),
            )

            devices = await phase_enumerate(client, journal)
            probe = pick_probe_device(devices, args.probe_device, journal)
            if probe is not None:
                counter = [0]
                probe["callbacks"] = counter
                client.set_state_callback(
                    probe["uuid"], lambda: counter.__setitem__(0, counter[0] + 1)
                )
                journal.note(
                    f"out-of-band probe device: {probe['name']} "
                    f"(dim={probe.get('state', {}).get('dim')})"
                )
            else:
                journal.note(
                    "no probe device: the resync check will be skipped, since "
                    "confirming unchanged state proves nothing"
                )

            for fault_name, inject in (
                ("blackhole", proxy.blackhole),
                ("fin", proxy.fin),
                ("reset", proxy.reset),
            ):
                if fault_name in phases:
                    await phase_fault_recovery(
                        name=fault_name,
                        inject=inject,
                        client=client,
                        proxy=proxy,
                        lag=lag,
                        journal=journal,
                        probe=probe,
                        hub_host=hub_host,
                        hub_port=hub_port,
                        outage_s=args.outage,
                    )

            if "restart" in phases:
                await phase_node_restart(client, proxy, journal, args.hold)

        if "churn" in phases:
            await phase_churn(hub_host, hub_port, journal)

    except Exception as exc:  # pylint: disable=broad-exception-caught
        journal.record("aborted", error=f"{type(exc).__name__}: {exc}")
    finally:
        if client is not None:
            with contextlib.suppress(Exception):
                await client.disconnect()
        await proxy.stop()
        await lag.stop()
        if simulator is not None:
            await simulator.shutdown()

        journal.note("=" * 68)
        journal.note("SUMMARY")
        for entry in journal.findings:
            journal.note("  " + json.dumps(entry, default=str))
        journal.note("=" * 68)
        journal.close()
    return 0


ALL_PHASES = [
    "pong",
    "scene",
    "payload",
    "enumerate",
    "blackhole",
    "fin",
    "reset",
    "churn",
    "restart",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="", help="node address")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--log", type=Path, help="append the journal to this file")
    parser.add_argument(
        "--wait-for-node",
        type=float,
        metavar="SECONDS",
        help="poll until the node accepts connections before starting, so a "
        "physically flipped node is caught the moment it wakes",
    )
    parser.add_argument(
        "--phases",
        nargs="+",
        default=["pong", "enumerate", "blackhole", "fin", "churn"],
        choices=ALL_PHASES,
        help="ordered by cost: the cheap, high-value ones run first so a short "
        "window still yields findings",
    )
    parser.add_argument(
        "--probe-device",
        default="",
        help="name of the one load that is safe to actuate, used for the "
        "out-of-band change that proves the resync corrected something",
    )
    parser.add_argument(
        "--outage",
        type=float,
        default=25.0,
        help="how long each injected fault is held before healing",
    )
    parser.add_argument(
        "--hold",
        type=float,
        default=900.0,
        help="how long the restart phase watches for unassisted recovery",
    )
    parser.add_argument("--simulator", action="store_true", help="run against the "
                        "in-process simulator instead of hardware")
    parser.add_argument("--sim-port", type=int, default=8123)
    parser.add_argument("--sim-http-port", type=int, default=8180)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not args.simulator and not args.host:
        raise SystemExit("--host is required unless --simulator is given")
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s %(message)s"
    )
    logging.getLogger("deako_simulator").setLevel(logging.WARNING)
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
