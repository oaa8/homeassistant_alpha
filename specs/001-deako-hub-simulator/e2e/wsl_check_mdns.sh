#!/bin/bash
# Confirm mDNS multicast reaches the LAN from inside WSL under mirrored
# networking. Under the default NAT mode this finds nothing.
set -e
cd ~
if [ ! -d mdns-check ]; then
  python3 -m venv mdns-check
  ./mdns-check/bin/pip install -q zeroconf
fi

./mdns-check/bin/python - <<'PY'
import socket, time
from zeroconf import Zeroconf, ServiceBrowser, ServiceListener

found = []

class L(ServiceListener):
    def add_service(self, zc, t, name):
        info = zc.get_service_info(t, name)
        if info and info.addresses:
            found.append((name, f"{socket.inet_ntoa(info.addresses[0])}:{info.port}"))
    def update_service(self, *a): pass
    def remove_service(self, *a): pass

zc = Zeroconf()
ServiceBrowser(zc, "_deako._tcp.local.", L())
time.sleep(10)
zc.close()

print("Services visible from inside WSL on _deako._tcp.local.:")
for name, addr in sorted(found):
    tag = "   <-- SIMULATOR" if "simulator" in name else ""
    print(f"   {addr:<26} {name}{tag}")

sim = [a for n, a in found if "simulator" in n]
print()
print("RESULT:", "PASS - WSL sees the simulator via mDNS" if sim else "FAIL - no simulator visible")
PY
