# Validation: End-to-End Home Assistant Integration Against Simulator

**Date**: August 11, 2026
**Task**: T097 (re-validation), T107 (mDNS fix verification)
**Result**: **PASSED**
**Harness**: [`../e2e/`](../e2e/)

## Why this was re-run

T097 had been marked complete on the strength of an earlier agent's report. That
report could not be trusted: the accompanying `tests/test_ha_integration.py` was
incapable of passing (it imported `telnetlib`, removed in Python 3.13, and
asserted a `PING`/`PONG` protocol the hub has never spoken), and a root-level
`T097-BLOCKER.md` contradicted it. This run validates the simulator against a
real Home Assistant instance from scratch and records exactly what was observed.

## Environment

| Component | Detail |
|---|---|
| Simulator | Windows host `192.168.86.65`, telnet `8023`, HTTP API `8080`, 3 devices |
| Home Assistant | 2025.1.4, throwaway instance in WSL Ubuntu (Python 3.12.3) |
| Integration | `custom_components/deako` copied into the test instance |
| pydeako | 0.3.1 (the version pinned in `manifest.json`) |

The Home Assistant instance was created solely for this validation and destroyed
afterwards. It is not the author's production system.

## Part 1 - Real pydeako library against the simulator

Driving the simulator with the actual library the integration depends on,
run on Linux (`e2e/e2e_pydeako_drive.py`):

```
PASS  Deako.connect()                    connected to 192.168.86.65:8023
PASS  Deako.find_devices()
PASS  Device list populated (expected 3) names=['Bedroom Dimmer','Kitchen Light','Living Room Light']
PASS  control_device power on            before={'power': False, 'dim': None} after={'power': True, 'dim': 60}
PASS  control_device power off           state={'power': False, 'dim': None}
PASS  Deako.disconnect()
6/6 passed
```

## Part 2 - Home Assistant discovery and setup

Config flow submitted with the simulator's address:

```
config entry ->  deako: state=loaded  title=Deako
```

Entities created, with initial states matching the simulator's configuration
exactly (Kitchen configured `power: true`, the other two `false`):

```
light.living_room_light   state=off   name=Living Room Light
light.bedroom_dimmer      state=off   name=Bedroom Dimmer
light.kitchen_light       state=on    name=Kitchen Light
TOTAL_LIGHTS=3
```

## Part 3 - Bidirectional control

Full round trip: HA service call -> integration -> pydeako -> telnet ->
simulator, and simulator EVENT -> pydeako -> HA entity state.

| Action | Home Assistant | Simulator |
|---|---|---|
| initial | `state=off brightness=None` | `{'power': False, 'dim': 0}` |
| `light.turn_on` brightness 128 | `state=on brightness=127` | `{'power': True, 'dim': 50}` |
| `light.turn_off` | `state=off brightness=None` | `{'power': False, 'dim': 50}` |
| simulator button press | `state=on brightness=127` | `{'power': True, 'dim': 50}` |

Brightness 128/255 maps to dim 50%, as expected.

The final row is the important one: an **external** state change originating in
the simulator propagated back into Home Assistant. This exercises the
asynchronous EVENT broadcast path (FR-065, FR-075) rather than just
request/response, and confirms unsolicited messages reach the integration.

## Findings

### 1. mDNS fix confirmed (T107)

Before the fix the simulator advertised only `_telnet._tcp.local.`, while
pydeako's `DeakoDiscoverer` browses `_deako._tcp.local.` exclusively. Discovery
was therefore impossible. After the fix, a browser replicating pydeako's exact
algorithm collected:

```
192.168.86.65:8023    deako-test-simulator._deako._tcp.local.   <-- simulator
192.168.86.46:23      HUB-SERIAL-B._deako._tcp.local.
192.168.86.31:23      HUB-SERIAL-A._deako._tcp.local.
```

The simulator is discovered alongside both physical hubs.

### 2. pydeako 0.3.1 cannot connect on Windows (upstream limitation, not a simulator defect)

`pydeako/deako/utils/_socket.py`:

```python
address, port = self.address.split(":")
await self.loop.sock_connect(self.sock, (address, port))   # port is a str
```

Verified behaviour of the resulting call:

| Platform | Result |
|---|---|
| Windows (ProactorEventLoop) | `TypeError: 'str' object cannot be interpreted as an integer` |
| Linux | works - `getaddrinfo` accepts a numeric string port |

This is why the integration runs fine in production (Home Assistant on Linux)
while direct Windows-hosted pydeako tests fail. It is an upstream pydeako issue
and is unrelated to simulator behaviour; it is recorded here so the failure mode
is not misdiagnosed as a simulator bug again. Any future Windows-side pydeako
testing must account for it.

### 3. Unrelated dependency noise

The test instance logged `TypeError: Channel.getaddrinfo() takes 3 positional
arguments` from `aiodns`/`aiohttp`. This affects Home Assistant's outbound DNS
in that throwaway environment only; it did not affect the Deako integration,
which loaded and operated normally.

## Conclusion

The simulator behaves as a Deako hub from the perspective of the software that
actually consumes one. Home Assistant discovers it, sets up the integration
against it, creates correct entities, controls them, and receives asynchronous
state changes from it.

The simulator is fit for its stated purpose: validating integration changes and
pydeako upgrades without physical hardware.

## Reproducing

From `specs/001-deako-hub-simulator/e2e/`, with the simulator running:

```bash
bash wsl_setup_ha.sh      # install Home Assistant in WSL
bash wsl_start_ha.sh      # deploy custom_components/deako and start HA
bash wsl_wait_ha.sh       # wait for the API
bash wsl_onboard_ha.sh    # onboard and add the integration
bash wsl_control_ha.sh    # drive lights and compare HA vs simulator state
bash wsl_teardown_ha.sh   # destroy the throwaway instance
```

Update `SIM_IP` in the scripts if the host address differs.
