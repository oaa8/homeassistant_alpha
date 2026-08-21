#!/usr/bin/env python3
"""Prove the *stuck exclusive slot* against real firmware, and that we refuse it.

Wayfinder #41 rests on a claim the map had only ever applied to other people's
integrations: Deako's telnet server is exclusive, and a second connector to the
same node gets a socket that opens and is then served nothing. On an ESP32 the
network stack completes the handshake a layer below the telnet application, so
the connection looks healthy to anything that asks only whether the socket
opened -- which is what ``is_connected()`` did before #41. Home Assistant then
shows every light available, serving cached state, with commands vanishing.

#32 caught the house node doing this for 13 seconds and read it as a node
symptom. The map owner confirmed the mechanism first-hand. Nobody had measured
it, and "confirmed first-hand" is exactly the kind of one-source claim this
map's Notes warn about, so this rig measures it:

  A. hold the node's one telnet slot open with a plain socket, proving the
     holder is genuinely being served by exchanging a PING/PONG;
  B. with the slot held, point the vendored client at the same node and report
     what it decides.

The expected reading, and the whole point of #41: B's TCP connect *succeeds*,
no pong comes back, and the client refuses to call it a connection -- counting
it as an unanswered attempt instead. Run against the pre-#41 library, B reports
connected.

Strictly read-only. It sends PING and DEVICE_LIST only, never a CONTROL, so no
light moves. It does hold the target's exclusive slot for the duration, so it
must only ever be pointed at the spare -- never at the node Home Assistant or
SmartThings is using.

Usage
-----
    python3 tools/deako_exclusive_slot_probe.py --host <spare-address>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import socket
import sys
import time
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "custom_components" / "deako"))

import pydeako  # noqa: E402
from pydeako.deako import Deako  # noqa: E402

VENDORED_ROOT = REPO_ROOT / "custom_components" / "deako" / "pydeako"
if Path(pydeako.__file__).resolve().parent != VENDORED_ROOT.resolve():
    raise SystemExit(f"refusing to run: imported {pydeako.__file__}")


def hold_slot(host: str, port: int, timeout: float = 5.0) -> tuple[socket.socket, bool]:
    """Take the node's telnet slot, and prove the holder is being served."""
    sock = socket.create_connection((host, port), timeout=timeout)
    sock.settimeout(timeout)
    transaction_id = f"slotprobe-{uuid.uuid4().hex[:8]}"
    sock.sendall(json.dumps({
        "transactionId": transaction_id,
        "dst": "deako",
        "src": "deako_exclusive_slot_probe",
        "type": "PING",
    }).encode())
    served = False
    deadline = time.monotonic() + timeout
    buffer = ""
    while time.monotonic() < deadline:
        try:
            chunk = sock.recv(4096)
        except socket.timeout:
            break
        if not chunk:
            break
        buffer += chunk.decode("utf-8", "replace")
        if transaction_id in buffer:
            served = True
            break
    return sock, served


async def second_connector(host: str, port: int, budget: float) -> dict:
    """Point the vendored client at a node whose slot is already held."""
    async def get_address() -> tuple[str, str]:
        return f"{host}:{port}", "spare"

    client = Deako(get_address)
    manager = client.connection_manager

    started = time.monotonic()
    try:
        await asyncio.wait_for(client.connect(), timeout=budget)
    except asyncio.TimeoutError:
        pass
    verdict = {
        "reported_connected": client.is_connected(),
        "seconds": time.monotonic() - started,
        # Absent on the pre-#41 library, which had no idea an attempt could
        # fail this way.
        "unanswered_attempts": getattr(
            manager, "unanswered_connection_attempts", None,
        ),
        "failed_attempts": getattr(
            manager, "failed_connection_attempts", None,
        ),
    }
    await client.disconnect()
    return verdict


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=23)
    parser.add_argument(
        "--budget", type=float, default=12.0,
        help="seconds to let the second connector try before reading it",
    )
    args = parser.parse_args()

    print(f"holding the telnet slot on {args.host}:{args.port}")
    holder, served = hold_slot(args.host, args.port)
    print(f"  holder is being served: {served} "
          f"({'exchanged a correlated PING/PONG' if served else 'NO PONG -- the '
             'slot may already be held by something else, so the reading below '
             'is not what it claims to be'})")
    try:
        verdict = await second_connector(args.host, args.port, args.budget)
    finally:
        holder.close()
        print("released the slot")

    print()
    print("=" * 64)
    print("second connector, while the slot was held:")
    print(f"  reported connected:   {verdict['reported_connected']}")
    print(f"  took:                 {verdict['seconds']:.2f}s")
    print(f"  unanswered attempts:  {verdict['unanswered_attempts']}")
    print(f"  failed attempts:      {verdict['failed_attempts']}")
    print()
    if verdict["reported_connected"]:
        print("REPORTED CONNECTED. Either this is the pre-#41 library -- in "
              "which case this is the bug, measured -- or the gate has been "
              "removed.")
    else:
        print("Refused, as #41 requires. The socket opened and the hub said "
              "nothing, so it was never reported as a connection.")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
