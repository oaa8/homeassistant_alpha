#!/usr/bin/env python3
"""Poke a live rig by hand. A pair of eyes, not a test.

Companion to `wsl_rig_up.sh`. Every command here is one thing a person would
do while watching the integration: read the diagnostics, ask for a census,
take a switch off the mesh, put it back, make a device report.

Nothing here asserts anything. That is deliberate -- this map's bar is that
somebody drives the thing and reports what they saw, and an assertion is the
question you already thought of. Wayfinder #45 shipped two false docstring
claims past 30 green assertions; both fell out of reading a dump like the one
below and noticing a number that could not be right.

Usage (with a rig up, from the repo root):

    python3 specs/001-deako-hub-simulator/e2e/rig_poke.py dump
    python3 specs/001-deako-hub-simulator/e2e/rig_poke.py get <entity_id>
    python3 specs/001-deako-hub-simulator/e2e/rig_poke.py call button press <entity_id>
    python3 specs/001-deako-hub-simulator/e2e/rig_poke.py census
    python3 specs/001-deako-hub-simulator/e2e/rig_poke.py deaf [uuid]
    python3 specs/001-deako-hub-simulator/e2e/rig_poke.py hear
    python3 specs/001-deako-hub-simulator/e2e/rig_poke.py event true [uuid]
    python3 specs/001-deako-hub-simulator/e2e/rig_poke.py dim 20
    python3 specs/001-deako-hub-simulator/e2e/rig_poke.py press
    python3 specs/001-deako-hub-simulator/e2e/rig_poke.py wire
    python3 specs/001-deako-hub-simulator/e2e/rig_poke.py history <entity_id>
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

WORK_DIR = os.environ.get("RIG_WORK_DIR", os.path.expanduser("~/rig"))
BASE = "http://127.0.0.1:8123"
SIM = "http://127.0.0.1:8080"

# The two devices zero_dim_sim_runner.py serves.
DIMMER = "11111111-1111-4111-8111-111111111111"
SWITCH = "33333333-3333-4333-8333-333333333333"

WATCH = ("probe", "asymmetry", "unreachable", "node_status", "deako_hub")
INTERESTING = ("dim", "witnessed", "unwitnessed", "unreachable_uuids",
               "brightness", "last_device", "last_value", "last_witnessed")


def token() -> str:
    with open(os.path.join(WORK_DIR, "token.txt")) as fh:
        return fh.read().strip()


def auth() -> str:
    return f"Authorization: Bearer {token()}"


def _json(out: str, what: str):
    try:
        return json.loads(out)
    except Exception:
        sys.exit(f"could not read {what}: {out[:300]}\n"
                 f"(is the rig up? has the token expired -- try {WORK_DIR}/refresh)")


def get(path: str):
    out = subprocess.run(["curl", "-s", f"{BASE}{path}", "-H", auth()],
                         capture_output=True, text=True).stdout
    return _json(out, path)


def post(path: str, body=None):
    cmd = ["curl", "-s", "-X", "POST", f"{BASE}{path}", "-H", auth()]
    if body is not None:
        cmd += ["-H", "Content-Type: application/json", "-d", json.dumps(body)]
    return subprocess.run(cmd, capture_output=True, text=True).stdout


def sim(path: str, body=None):
    cmd = ["curl", "-s", "-X", "POST", f"{SIM}{path}"]
    if body is not None:
        cmd += ["-H", "Content-Type: application/json", "-d", json.dumps(body)]
    return subprocess.run(cmd, capture_output=True, text=True).stdout


def dump(heading: str = "") -> None:
    """Everything worth watching, as a person would read it off a dashboard."""
    if heading:
        print(f"--- {heading} ---")
    for e in sorted(get("/api/states"), key=lambda r: r["entity_id"]):
        eid = e["entity_id"]
        if not (any(k in eid for k in WATCH) or eid.startswith("light.")):
            continue
        extra = {k: v for k, v in e["attributes"].items() if k in INTERESTING}
        print(f"  {eid:58} {str(e['state']):28} {extra if extra else ''}")


def history(entity: str) -> None:
    """History for one entity, including the attribute-only changes.

    `significant_changes_only=0` matters: an attribute-only update -- such as
    the asymmetry measurement's verdict landing 5s after its write -- is
    collapsed out of the default view, and every row then reads as though
    nothing ever resolved.
    """
    rows = get(f"/api/history/period?filter_entity_id={entity}"
               "&significant_changes_only=0")
    flat = [p for run in rows for p in run]
    print(f"{len(flat)} row(s) for {entity}")
    for p in flat:
        extra = {k: v for k, v in p.get("attributes", {}).items()
                 if k in INTERESTING}
        print(f"  {p.get('last_updated', '')[11:19]}  {str(p['state']):>10}  {extra}")


def wire() -> None:
    """The last few CONTROLs the simulator actually received.

    The only honest account of what left the building: Home Assistant's own
    API cannot tell a command that reached the integration from one the hub
    never took.
    """
    log = os.path.join(WORK_DIR, "sim.log")
    try:
        with open(log, errors="replace") as fh:
            lines = [ln.rstrip() for ln in fh
                     if "[RECV]" in ln and '"type": "CONTROL"' in ln]
    except FileNotFoundError:
        sys.exit(f"no simulator log at {log}")
    for ln in lines[-8:]:
        print(" ", ln)
    print(f"({len(lines)} CONTROL(s) received in total)")


def main() -> None:
    args = sys.argv[1:] or ["dump"]
    cmd, rest = args[0], args[1:]

    if cmd == "dump":
        dump(" ".join(rest))
    elif cmd == "get":
        d = get(f"/api/states/{rest[0]}")
        print(d.get("state"), json.dumps(d.get("attributes", {})))
    elif cmd == "call":
        print(post(f"/api/services/{rest[0]}/{rest[1]}",
                   {"entity_id": rest[2]}) or "ok")
    elif cmd == "census":
        print(post("/api/services/button/press",
                   {"entity_id": "button.deako_hub_run_census_now"}) or "ok")
    elif cmd == "deaf":
        uuid = rest[0] if rest else SWITCH
        print(sim("/api/control/unreachable", {"uuids": [uuid]}))
    elif cmd == "hear":
        print(sim("/api/control/unreachable", {"uuids": []}))
    elif cmd == "event":
        power = rest[0].lower() in ("1", "true", "on", "yes")
        uuid = rest[1] if len(rest) > 1 else SWITCH
        print(sim(f"/api/devices/{uuid}/state", {"power": power}))
    elif cmd == "dim":
        print(sim(f"/api/devices/{DIMMER}/state",
                  {"power": True, "dim": int(rest[0])}))
    elif cmd == "press":
        uuid = rest[0] if rest else SWITCH
        print(sim(f"/api/devices/{uuid}/button"))
    elif cmd == "wire":
        wire()
    elif cmd == "history":
        history(rest[0])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
