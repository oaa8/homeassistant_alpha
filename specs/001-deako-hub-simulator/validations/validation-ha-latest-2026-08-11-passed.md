# Validation: Simulator Against Home Assistant 2026.8.1 (Latest)

**Date**: August 11, 2026
**Result**: **Simulator PASSED.** Three defects found in `custom_components/deako`, none in the simulator.
**Harness**: [`../e2e/`](../e2e/)

## Why this run

An earlier run in this session validated against Home Assistant 2025.1.4, which
was 19 months old at the time and therefore a weak test of the upgrade path this
simulator exists to support. This run targets the current release.

## Environment

| Component | Detail |
|---|---|
| Home Assistant | **2026.8.1** (current) on **Python 3.14.7**, installed via `uv` |
| Integration | `custom_components/deako` (pydeako 0.3.1, atomics 1.0.2) |
| Simulator | Windows host `192.168.86.65`, telnet `8023`, HTTP `8080`, 3 devices |
| WSL networking | **mirrored** (`networkingMode=mirrored`), enabling LAN multicast |

Home Assistant requires Python 3.14.2+, which the distro does not ship; `uv`
supplies it without touching system packages.

## Simulator behaviour: correct throughout

Captured from Home Assistant's own debug log while it drove the simulator:

```
Turning on 550e8400-...-446655440002 with dim 78.0
Sending data: {"type": "CONTROL", "data": {"target": "...440002",
               "state": {"power": true, "dim": 78.0}}}
Raw message received: {"type":"CONTROL", ..., "status":"ok"}
Raw message received: {"type": "EVENT", "data": {"eventType": "DEVICE_STATE_CHANGE",
               "target": "...440002", "state": {"power": true, "dim": 78}}}
Sending data: {"type": "PING"}
Raw message received: {"type":"PING", ..., "status":"ok"}
```

The simulator accepted the command, acknowledged it, applied the state, and
broadcast the asynchronous `DEVICE_STATE_CHANGE` event. Its own API confirmed
the change (`{'power': True, 'dim': 78}`). Keepalive PING/PONG held steady.

**mDNS discovery** now verified from inside Home Assistant's own network
namespace. With mirrored WSL networking, a browse of `_deako._tcp.local.`
returned:

```
192.168.86.65:8023   deako-test-simulator._deako._tcp.local.   <-- simulator
192.168.86.46:23     HUB-SERIAL-B._deako._tcp.local.
```

This closes the gap noted in the previous validation, where WSL's default NAT
prevented multicast from reaching the LAN.

## Findings in the integration

### 1. Lights do not report a color mode - entity dropped and state frozen (HIGH)

```
ERROR [homeassistant.components.light] Error adding entity light.kitchen_light
      for domain light with platform deako
HomeAssistantError: light.kitchen_light (<class 'DeakoLightSwitch'>)
      does not report a color mode
```

Home Assistant now requires a light entity to declare `color_mode` /
`supported_color_modes`. `DeakoLightSwitch` does not, which produced both
anomalies observed:

- Only **2 of 3** lights registered; `light.kitchen_light` was rejected outright.
- Entity state **never updated**. Polled at 2s, 5s, 10s, 20s and 30s after a
  successful command, Home Assistant still reported `off` while the simulator
  reported `{'power': True, 'dim': 78}`, because every state write raised.

Commands still travelled outward correctly, so the failure is confined to the
entity layer. On 2025.1.4 the same integration tracked state correctly, so this
is a genuine forward-compatibility break rather than a pre-existing defect.

### 2. Blocking call inside the event loop (MEDIUM)

```
WARNING [homeassistant.util.loop] Detected blocking call to scandir with args
('.../atomics/_clib/',) inside the event loop by custom integration 'deako'
at custom_components/deako/__init__.py, line 185:
connection.is_refreshing = atomics.atomic(width=1, atype=atomics.INT)
```

`atomics.atomic()` performs a filesystem scan on first use. Called on the event
loop it stalls Home Assistant. It needs to move to executor context or be
replaced; a plain `bool` guard or `asyncio.Lock` would remove the `atomics`
dependency altogether, which would also resolve finding 4.

### 3. Auto-discovery cannot complete - no zeroconf step (MEDIUM)

`manifest.json` advertises discovery:

```json
"zeroconf": ["_deako._tcp.local."]
```

but `config_flow.py` implements only `async_step_user` (plus `async_step_init`
for options). There is no `async_step_zeroconf`, and the
`config_entry_flow.register_discovery_flow` call is commented out. No Deako
discovery flow was offered even though the simulator was demonstrably visible on
the correct service type.

Auto-discovery therefore cannot work regardless of what the hub or simulator
advertises. Upstream Home Assistant's Deako integration implements this step;
this fork does not.

### 4. Packaging friction on Python 3.14 (LOW, environment-only)

`atomics` depends on `cffi`. Home Assistant reinstalls manifest requirements at
every startup, which pulled `cffi` 2.0.0 while the compiled `_cffi_backend` was
2.1.1, and `atomics` then failed to import:

```
Exception: Version mismatch: this is the 'cffi' package version 2.0.0 ...
we get version 2.1.1 ... The two versions should be equal
```

Worked around by pinning the dependencies and starting with `--skip-pip`. This
is an artifact of the test environment rather than proof of a production
problem, but it is a second reason to reconsider the `atomics` dependency.

## Not a simulator defect: pydeako on Windows

Recorded again for continuity from the earlier validation.
`pydeako/deako/utils/_socket.py` splits `"host:port"` and passes the port as a
string to `sock_connect`. Windows' ProactorEventLoop raises
`TypeError: 'str' object cannot be interpreted as an integer`; Linux accepts it
because `getaddrinfo` tolerates a numeric string. Windows-hosted pydeako tests
will fail for this reason alone.

## Conclusion

The simulator behaved correctly against the current Home Assistant release:
discoverable over mDNS, correct protocol responses, correct state transitions,
and correct asynchronous event broadcast.

Every failure observed originated in the integration, and each was surfaced
without touching physical hardware. That is precisely the outcome the simulator
was built to enable, and these three findings form a concrete starting backlog
for the integration upgrade work.

## Suggested order for the upgrade work

1. Add `_attr_color_mode` / `_attr_supported_color_modes` to `DeakoLightSwitch`
   (unblocks entity registration and state updates).
2. Remove the `atomics` event-loop call (fixes the blocking warning and the
   `cffi` fragility together).
3. Implement `async_step_zeroconf` so advertised discovery actually works.
4. Re-run this harness, then move pydeako off 0.3.1.

## Reproducing

From `specs/001-deako-hub-simulator/e2e/`, with the simulator running:

```bash
bash wsl_check_mdns.sh          # confirm multicast reaches WSL
bash wsl_setup_ha_latest.sh     # uv + Python 3.14 + latest Home Assistant
bash wsl_fresh_latest.sh        # deploy integration, start minimal instance
bash wsl_onboard_latest.sh      # onboard, check for discovery flows
bash wsl_validate_latest.sh     # entities + control round trip
bash wsl_diag_state_sync.sh     # detailed state-sync diagnosis
bash wsl_teardown_latest.sh     # destroy the instance
```

Requires `networkingMode=mirrored` in `%USERPROFILE%\.wslconfig` for the mDNS
step. Update `SIM_IP` if the host address differs.
