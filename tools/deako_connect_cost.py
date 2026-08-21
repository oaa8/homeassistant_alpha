#!/usr/bin/env python3
"""Measure what a *failed* connection attempt costs the vendored 0.6.0 manager.

The house's post-cutover drops recovered in 7-11 s, with one outlier at 1 s.
A reconnect that succeeds immediately takes about 1 s, so the 7-11 s cluster is
the cost of an attempt that did not succeed -- and the question is whether that
cost is the node taking its time or a floor we impose on ourselves.

**Before wayfinder #41**, ``_Manager.init_connection`` polled
``connection.is_connected()`` once a second up to a 10 s budget and never looked
at whether the socket had already given up, so a connection refused in a
millisecond still burned the full timeout. Measured here against a closed port:
a flat ``10.02`` s between every attempt.

**After #41** the wait is event-driven, so a refusal ends it immediately and the
gaps are the deliberate backoff instead: 1, 2, 4, 8, then capped at 10. That cap
is #19's measured-safe cadence, so steady state against a dead node is no more
aggressive than the code that was already in the house. This script is the
instrument for both halves -- run it and read the ladder.

Nothing is sent to any Deako node: the target is a port on localhost that is
closed, so the rig cannot touch the spare's exclusive telnet slot.

Usage
-----
    python3 tools/deako_connect_cost.py --seconds 60
"""

from __future__ import annotations

import argparse
import asyncio
import socket
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "custom_components" / "deako"))

import pydeako  # noqa: E402
from pydeako.deako._manager import (  # noqa: E402
    CONNECT_TIMEOUT_S,
    RETRY_BACKOFF_MAX_S,
    RETRY_BACKOFF_START_S,
    _Manager,
)
from pydeako.deako.utils import _connection as connection_module  # noqa: E402

VENDORED_ROOT = REPO_ROOT / "custom_components" / "deako" / "pydeako"
if Path(pydeako.__file__).resolve().parent != VENDORED_ROOT.resolve():
    raise SystemExit(f"refusing to run: imported {pydeako.__file__}")


def closed_port() -> int:
    """Return a port that is guaranteed to refuse, by binding and releasing."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=60)
    args = parser.parse_args()

    port = closed_port()
    address = f"127.0.0.1:{port}"
    attempts: list[float] = []

    real_init = connection_module._Connection.__init__

    def traced_init(self, *a, **kw):
        attempts.append(time.monotonic())
        return real_init(self, *a, **kw)

    connection_module._Connection.__init__ = traced_init  # type: ignore[method-assign]

    async def get_address():
        return address, "closed-port"

    manager = _Manager(get_address, lambda _payload: None)
    started = time.monotonic()
    manager.create_connection_task()
    await asyncio.sleep(args.seconds)

    manager.close()
    elapsed = time.monotonic() - started

    gaps = [attempts[i] - attempts[i - 1] for i in range(1, len(attempts))]
    print(f"target:               {address} (guaranteed refused)")
    print(f"CONNECT_TIMEOUT_S:    {CONNECT_TIMEOUT_S} (TCP connect only)")
    print(f"backoff:              {RETRY_BACKOFF_START_S}s doubling, "
          f"capped at {RETRY_BACKOFF_MAX_S}s")
    print(f"ran:                  {elapsed:.1f}s")
    print(f"connection attempts:  {len(attempts)}")
    print(f"attempts per minute:  {len(attempts) / elapsed * 60:.1f}")
    print(f"failed attempts:      {manager.failed_connection_attempts}")
    print(f"  of those, unanswered (socket up, hub silent): "
          f"{manager.unanswered_connection_attempts}")
    if gaps:
        print("seconds between attempts: "
              + ", ".join(f"{g:.2f}" for g in gaps))
        print(f"min gap {min(gaps):.2f}s  max gap {max(gaps):.2f}s")
        print()
        print("A refused connect returns in well under a millisecond, so the "
              "gaps are entirely ours. Before #41 they were a flat 10.02s "
              "nobody chose; they should now climb 1, 2, 4, 8 and hold at "
              f"{RETRY_BACKOFF_MAX_S}s. A gap of 0 would be a bug -- an "
              "unbounded retry loop is what the old 10.02s was accidentally "
              "preventing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
