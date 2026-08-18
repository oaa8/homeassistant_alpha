#!/usr/bin/env python3
"""Unattended watch measuring whether a Deako node goes *silent* under the
vendored 0.6.0 client, and what the ping watchdog does when it does.

Why this exists
---------------
After the house cutover the hub connection dropped and recovered ten times in
under two hours, then held. The recorder showed the age of the last inbound hub
message climbing past the 10 s ping sawtooth immediately before each drop --
16.9 s before one, 39.1 s across another -- so the hub had stopped saying
anything at all, and the watchdog was doing its job rather than inventing a
fault. That reading comes from a sensor sampled every 30 s, which is too coarse
to say *why* the node went quiet or whether our own reconnect made it worse.

This tool takes the same measurement at full resolution against a node we are
allowed to hold: it drives the *vendored* library -- the thing that runs in the
house -- and records every inbound message, every ping, every pong correlation
decision and every connection transition, then reports the gaps.

Strictly read-only
------------------
The spare node carries the full house device profile, so a ``CONTROL`` moves a
real light. This tool never sends one: it enumerates once, exactly as the
integration does at setup, and then does nothing but let the ping watchdog run.

Run it under Linux/WSL, not Windows: the vendored ``_SocketConnection`` passes
the port to ``sock_connect`` as a str, which getaddrinfo tolerates only on
POSIX. Same constraint as ``deako_watchdog_battery.py``.

Usage
-----
    python3 tools/deako_silence_watch.py --host <node-address> --minutes 25 \
        --log /tmp/silence.log
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Import the vendored copy, never an installed pydeako. Putting the integration
# directory on the path rather than the repo root avoids dragging in
# custom_components.deako, which imports Home Assistant.
sys.path.insert(0, str(REPO_ROOT / "custom_components" / "deako"))

import pydeako  # noqa: E402
from pydeako.deako import Deako  # noqa: E402
from pydeako.deako._manager import PING_WORKER_WAIT_S  # noqa: E402
from pydeako.models import ResponseType  # noqa: E402

VENDORED_ROOT = REPO_ROOT / "custom_components" / "deako" / "pydeako"
if Path(pydeako.__file__).resolve().parent != VENDORED_ROOT.resolve():
    raise SystemExit(
        f"refusing to run: imported {pydeako.__file__}, expected the vendored "
        f"copy under {VENDORED_ROOT}"
    )

# The reply to a PING is itself typed "PING" on the wire -- ResponseType.PONG
# is the string "PING". There is no distinct PONG type.
PONG_TYPE = str(ResponseType.PONG.value)

# The age at which an inbound gap has outrun the ping sawtooth and means the
# node genuinely stopped answering, rather than simply not having been asked.
SILENCE_THRESHOLD_S = PING_WORKER_WAIT_S + 1

DEVICE_LIST_TIMEOUT_S = 20


def wall(ts: float | None = None) -> str:
    """Format a wall-clock stamp to milliseconds."""
    return datetime.fromtimestamp(ts or time.time()).strftime("%H:%M:%S.%f")[:-3]


class Watch:
    """Records what the connection did, so the run can be read back."""

    def __init__(self, out) -> None:
        self.out = out
        self.messages: list[tuple[float, str, str]] = []
        self.pings: list[tuple[float, str]] = []
        self.ignored_pongs: list[tuple[float, str, str]] = []
        self.transitions: list[tuple[float, bool]] = []
        self.silences: list[tuple[float, float]] = []
        self.started = time.monotonic()

    def say(self, line: str) -> None:
        stamped = f"{wall()}  {line}"
        print(stamped, flush=True)
        self.out.write(stamped + "\n")
        self.out.flush()

    def on_message(self, kind: str, txn: str) -> None:
        self.messages.append((time.monotonic(), kind, txn))

    def on_transition(self, connected: bool) -> None:
        self.transitions.append((time.monotonic(), connected))
        self.say(f"CONNECTION {'up' if connected else 'DOWN'}")


def instrument(deako: Deako, watch: Watch) -> None:
    """Wrap the manager so every inbound message and ping is recorded.

    Wrapping rather than reading the debug log: the correlation decision is the
    thing under test, and it is only visible as a branch inside incoming_json.
    """
    manager = deako.connection_manager
    real_incoming = manager.incoming_json
    real_send = manager.send_request

    def incoming_json(payload: dict) -> None:
        kind = str(payload.get("type"))
        txn = str(payload.get("transactionId"))
        pending = manager.pending_ping_id
        watch.on_message(kind, txn)
        if kind == PONG_TYPE and (pending is None or txn != pending):
            watch.ignored_pongs.append((time.monotonic(), txn, str(pending)))
            watch.say(f"IGNORED PONG txn={txn} waiting-on={pending}")
        real_incoming(payload)

    async def send_request(req):
        try:
            body = json.loads(req.get_body_str())
        except Exception:  # pylint: disable=broad-exception-caught
            body = {}
        if body.get("type") == "PING":
            watch.pings.append((time.monotonic(), str(body.get("transactionId"))))
            watch.say(f"PING sent txn={body.get('transactionId')}")
        sent = await real_send(req)
        if not sent:
            watch.say("SEND FAILED (socket is dead)")
        return sent

    manager.incoming_json = incoming_json  # type: ignore[method-assign]
    manager.send_request = send_request  # type: ignore[method-assign]
    # _Connection is built with the *manager's* callback captured at connect
    # time, so the wrapper has to be in place before the first connection.


async def connect_with_retry(deako: Deako, watch: Watch, budget_s: int) -> bool:
    """Connect, retrying: a freshly woken node resets the first connection."""
    deadline = time.monotonic() + budget_s
    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        watch.say(f"connect attempt {attempt}")
        await deako.connect()
        for _ in range(20):
            if deako.is_connected():
                watch.say(f"connected on attempt {attempt}")
                return True
            await asyncio.sleep(0.5)
        await deako.disconnect()
        await asyncio.sleep(2)
    return False


async def run(args: argparse.Namespace) -> int:
    log_path = Path(args.log)
    with log_path.open("w", encoding="utf-8") as out:
        watch = Watch(out)
        address = f"{args.host}:{args.port}"

        async def get_address():
            return address, args.host

        deako = Deako(get_address, client_name=args.client_name)
        instrument(deako, watch)
        deako.add_connection_listener(watch.on_transition)

        watch.say(f"watching {address} for {args.minutes} min "
                  f"(ping window {PING_WORKER_WAIT_S}s)")

        if not await connect_with_retry(deako, watch, args.wait_for_node):
            watch.say("never connected -- node is asleep or held by someone else")
            return 2

        # One enumeration, exactly as the integration does at setup. Read-only.
        try:
            await asyncio.wait_for(
                deako.find_devices(), timeout=DEVICE_LIST_TIMEOUT_S,
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            watch.say(f"find_devices did not complete: {exc!r}")
        watch.say(f"enumerated {len(deako.get_devices())} devices")

        deadline = time.monotonic() + args.minutes * 60
        last_seen_count = len(watch.messages)
        silent_since: float | None = None
        while time.monotonic() < deadline:
            await asyncio.sleep(0.25)
            age = deako.seconds_since_last_message()
            if len(watch.messages) != last_seen_count:
                last_seen_count = len(watch.messages)
                if silent_since is not None:
                    watch.silences.append(
                        (silent_since, time.monotonic() - silent_since),
                    )
                    silent_since = None
            if age is not None and age >= SILENCE_THRESHOLD_S:
                if silent_since is None:
                    silent_since = time.monotonic() - age
                    watch.say(f"SILENCE begins -- {age:.1f}s with no hub message")

        await deako.disconnect()

        # ---- summary -------------------------------------------------------
        elapsed = time.monotonic() - watch.started
        drops = [t for t in watch.transitions if not t[1]]
        watch.say("")
        watch.say("=" * 60)
        watch.say(f"ran {elapsed / 60:.1f} min against {address}")
        watch.say(f"inbound messages: {len(watch.messages)}")
        watch.say(f"pings sent:       {len(watch.pings)}")
        watch.say(f"pongs ignored (uncorrelatable): {len(watch.ignored_pongs)}")
        watch.say(f"connection drops: {len(drops)}")
        watch.say(f"reconnects (library counter): {deako.get_reconnect_count()}")

        gaps = []
        for i in range(1, len(watch.messages)):
            gaps.append((watch.messages[i][0] - watch.messages[i - 1][0],
                         watch.messages[i - 1][0]))
        if gaps:
            gaps.sort(reverse=True)
            watch.say("longest inbound gaps (s):  "
                      + ", ".join(f"{g:.1f}" for g, _ in gaps[:8]))
            over = [g for g, _ in gaps if g >= SILENCE_THRESHOLD_S]
            watch.say(f"gaps over {SILENCE_THRESHOLD_S}s: {len(over)}")
        kinds: dict[str, int] = {}
        for _, kind, _txn in watch.messages:
            kinds[kind] = kinds.get(kind, 0) + 1
        watch.say(f"message types: {kinds}")
        watch.say("=" * 60)
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=23)
    parser.add_argument("--minutes", type=float, default=25)
    parser.add_argument("--log", default="silence_watch.log")
    parser.add_argument("--client-name", default=None)
    parser.add_argument(
        "--wait-for-node", type=int, default=120,
        help="seconds to keep retrying the first connection",
    )
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
