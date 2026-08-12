# Deako Hub mDNS Service Type Test

**Date**: August 11, 2026
**Hubs**: 192.168.86.31, 192.168.86.46 (live production hubs)
**Purpose**: Determine which mDNS service type(s) a real Deako hub advertises, and which type consumers actually browse
**Spec Reference**: [spec.md](../spec.md) - FR-001

## Executive Summary

**Key Finding**: A real Deako hub advertises **two** mDNS service types simultaneously. The simulator advertised only one of them — and it was the wrong one for discovery purposes.

The simulator published only `_telnet._tcp.local.`, but both consumers of discovery browse `_deako._tcp.local.`:

- `pydeako` hardcodes `DEAKO_TYPE = "_deako._tcp.local."`
- The Home Assistant integration manifest declares `"zeroconf": ["_deako._tcp.local."]`

**Impact**: Home Assistant and pydeako could never auto-discover the simulator. This defeated the simulator's primary purpose, since the originating requirement was that "anything discovering deako devices actually sees the simulator."

**Spec Impact**: FR-001 corrected. Its prior claim that the service type was `_telnet` "verified against real hub and official API documentation" was not supported by the hardware.

## Test Methodology

Browsed both candidate service types concurrently on the LAN with `zeroconf.ServiceBrowser`, resolving each discovered service to its address and port.

## Test Results

### `_deako._tcp.local.`

| Service name | Resolved address |
|---|---|
| `HUB-SERIAL-A._deako._tcp.local.` | 192.168.86.31:23 |
| `HUB-SERIAL-B._deako._tcp.local.` | 192.168.86.46:23 |

Instance names are hub serial numbers.

### `_telnet._tcp.local.`

| Service name | Resolved address |
|---|---|
| `local-integration-3._telnet._tcp.local.` | 192.168.86.31:23 |
| `local-integration-2._telnet._tcp.local.` | 192.168.86.46:23 |

Instance names follow a `local-integration-N` pattern.

### Interpretation

Both types resolve to the **same two hosts on the same telnet port (23)**. A hub therefore publishes the pair; the types are not alternatives, and observing one does not disprove the other.

This explains the earlier confusion. The January 2025 note in
[protocol-testing-2025-01-15.md](./protocol-testing-2025-01-15.md) recorded an
initial assumption of `_deako._tcp.local.` and then "corrected" it to `_telnet`.
The `_telnet` observation was real, but concluding it *replaced* `_deako` was
wrong — both were present all along.

## Consumer Evidence

`pydeako/discover/_discover.py` (DeakoLights/pydeako):

```python
DEAKO_TYPE = "_deako._tcp.local."

class DeakoDiscoverer(ServiceBrowser):
    def __init__(self, zeroconf: Zeroconf | None = None) -> None:
        super().__init__(self.zeroconf, DEAKO_TYPE, DeakoListener(...))
```

`custom_components/deako/manifest.json`:

```json
"zeroconf": ["_deako._tcp.local."]
```

Additionally, `DeakoListener.__get_addresses()` builds its connection string from
`info.addresses`. A `ServiceInfo` registered without addresses yields an empty
list and the discovered hub is silently dropped, so the simulator must register
with an explicit address rather than relying on auto-detection.

## Implications for Simulator

### What the simulator MUST do

- Advertise `_deako._tcp.local.` — required for Home Assistant and pydeako discovery
- Advertise `_telnet._tcp.local.` — for fidelity with real hardware
- Register with an explicit resolvable address so `info.addresses` is non-empty
- Continue to degrade gracefully when mDNS is unavailable (FR-069)

### What the simulator should NOT do

- Advertise only one type and assume discovery works
- Register a `ServiceInfo` without addresses

## Verification After Fix

With the simulator running on port 8023, a browser using pydeako's exact
algorithm collected:

```
192.168.86.65:8023    deako-test-simulator._deako._tcp.local.   <-- simulator
192.168.86.46:23      HUB-SERIAL-B._deako._tcp.local.
192.168.86.31:23      HUB-SERIAL-A._deako._tcp.local.
```

The simulator is discovered alongside the real hubs, confirming the fix.

## Spec Updates Required

### FR-001 Correction

**Old FR-001** (unsupported by hardware):

```markdown
Simulator MUST advertise itself via mDNS/Zeroconf using service type "_telnet"
with service name "local-integration" on the local network (verified against
real hub and official API documentation)
```

**New FR-001** (corrected):

```markdown
Simulator MUST advertise itself via mDNS/Zeroconf using BOTH service types
published by a real hub: "_deako._tcp.local." and "_telnet._tcp.local."
(validated August 2026 against two production hubs). The "_deako._tcp.local."
advertisement is mandatory for discovery because pydeako's DeakoDiscoverer
hardcodes it and the Home Assistant integration manifest declares it under
"zeroconf". Advertisements MUST include a resolvable address, because pydeako
derives the connection address from ServiceInfo.addresses and discards services
that expose none.
```

## Confidence Level

**Very High** — the service types were observed directly on two production hubs,
and the consumer requirement is confirmed by pydeako's published source and the
integration manifest rather than by inference.

## Conclusion

The simulator's discovery advertisement was incompatible with every real
consumer of that advertisement. Publishing both service types with explicit
addresses restores the simulator's core promise: that software looking for a
Deako hub finds the simulator without any manual configuration.
