#!/usr/bin/env python3
"""Measure what a *failed* connection attempt costs the vendored 0.6.0 manager.

The house's post-cutover drops recovered in 7-11 s, with one outlier at 1 s.
A reconnect that succeeds immediately takes about 1 s, so the 7-11 s cluster is
the cost of an attempt that did not succeed -- and the question is whether that
cost is the node taking its time or a floor we impose on ourselves.

``_Manager.init_connection`` polls ``connection.is_connected()`` once a second
up to ``CONNECTION_TIMEOUT_S``, and never looks at whether the socket has
already given up. So a connection refused in a millisecond should still burn
the full timeout before anything is retried. This measures that against a
closed port, where every attempt is guaranteed to fail instantly.

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
    CONNECTION_TIMEOUT_S,
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
    print(f"CONNECTION_TIMEOUT_S: {CONNECTION_TIMEOUT_S}")
    print(f"ran:                  {elapsed:.1f}s")
    print(f"connection attempts:  {len(attempts)}")
    print(f"attempts per minute:  {len(attempts) / elapsed * 60:.1f}")
    if gaps:
        print("seconds between attempts: "
              + ", ".join(f"{g:.2f}" for g in gaps))
        print(f"min gap {min(gaps):.2f}s  max gap {max(gaps):.2f}s")
        print()
        print("A refused connect returns in well under a millisecond, so any "
              "gap near CONNECTION_TIMEOUT_S is a delay we impose, not the "
              "network's.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
