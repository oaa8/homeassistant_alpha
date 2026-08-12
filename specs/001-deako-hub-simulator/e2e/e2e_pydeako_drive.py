"""End-to-end drive of the simulator using the real pydeako library.

This is deliberately NOT a unit test. It exercises the actual client code the
Home Assistant integration runs -- pydeako's DeakoDiscoverer and Deako client --
against a live simulator over real sockets, the same way the integration does in
custom_components/deako/__init__.py.
"""

import asyncio
import os
import sys

from pydeako.deako import Deako
from pydeako.discover import DeakoDiscoverer

IN_WSL = "microsoft" in os.uname().release.lower() if hasattr(os, "uname") else False

results = []


def record(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if detail else ""))


async def main():
    # 1. Discovery, exactly as the integration does when no IP is configured.
    #    NOTE: under WSL this cannot work -- WSL sits behind NAT in its own
    #    network namespace, so mDNS multicast never reaches the Windows LAN.
    #    Discovery is validated separately from the LAN itself.
    discoverer = DeakoDiscoverer()
    try:
        address = await discoverer.get_address()
        record("mDNS discovery via pydeako DeakoDiscoverer", bool(address), f"address={address}")
    except Exception as e:
        if IN_WSL:
            print(f"SKIP  mDNS discovery (WSL NAT cannot see LAN multicast): {type(e).__name__}")
        else:
            record("mDNS discovery via pydeako DeakoDiscoverer", False, f"{type(e).__name__}: {e}")

    # The integration talks to whatever address it was given; force the
    # simulator so a real hub on the LAN cannot silently satisfy the test.
    sim_address = "127.0.0.1:8023"

    # pydeako expects an AWAITABLE address provider.
    async def get_address() -> str:
        return sim_address

    deako = Deako(get_address)

    # 2. Connect
    try:
        await asyncio.wait_for(deako.connect(), timeout=10)
        record("Deako.connect()", True, f"connected to {sim_address}")
    except Exception as e:
        record("Deako.connect()", False, f"{type(e).__name__}: {e}")
        return summarize()

    # 3. find_devices() -- this is where the integration previously saw
    #    "Unexpectedly received a count of zero devices from the hub".
    try:
        await asyncio.wait_for(deako.find_devices(), timeout=15)
        record("Deako.find_devices()", True)
    except Exception as e:
        record("Deako.find_devices()", False, f"{type(e).__name__}: {e}")

    # 4. Device count and state, as the integration reads them
    try:
        devices = deako.get_devices()
        ok = len(devices) == 3
        names = sorted(d.get("name") for d in devices.values())
        record("Device list populated (expected 3)", ok, f"count={len(devices)} names={names}")
    except Exception as e:
        record("Device list populated (expected 3)", False, f"{type(e).__name__}: {e}")
        devices = deako.get_devices()

    # 5. Control a device, the way the light entity does on turn_on
    try:
        uuid = next(iter(devices))
        before = devices[uuid]["state"].copy()
        await deako.control_device(uuid, True, 60)
        await asyncio.sleep(1.0)
        after = deako.get_devices()[uuid]["state"]
        ok = after.get("power") is True
        record("control_device power on", ok, f"before={before} after={after}")
    except Exception as e:
        record("control_device power on", False, f"{type(e).__name__}: {e}")

    # 6. Turn back off
    try:
        await deako.control_device(uuid, False)
        await asyncio.sleep(1.0)
        after = deako.get_devices()[uuid]["state"]
        record("control_device power off", after.get("power") is False, f"state={after}")
    except Exception as e:
        record("control_device power off", False, f"{type(e).__name__}: {e}")

    try:
        await deako.disconnect()
        record("Deako.disconnect()", True)
    except Exception as e:
        record("Deako.disconnect()", False, f"{type(e).__name__}: {e}")

    return summarize()


def summarize():
    print("\n" + "=" * 60)
    failed = [n for n, ok, _ in results if not ok]
    print(f"{len(results) - len(failed)}/{len(results)} passed")
    if failed:
        print("FAILED: " + ", ".join(failed))
    print("=" * 60)
    return 1 if failed else 0


sys.exit(asyncio.run(main()))
