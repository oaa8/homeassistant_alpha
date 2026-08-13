# Zero-Dim Regression Test: pydeako 0.3.1 vs 0.6.0

**Date**: 2026-08-12
**Wayfinder ticket**: [oaa8/deako-house-wayfinder#12](https://github.com/oaa8/deako-house-wayfinder/issues/12)
**Question**: Does pydeako 0.6.0 break setting zero brightness, and does that matter in the house?
**Method**: Live experiment against the Deako hub simulator. No real hub or real
Home Assistant instance was contacted; the simulator bound 127.0.0.1 with its
mDNS advertisement suppressed.

## Verdict

**YES, the defect is real. It is a DISPLAY bug, not a functional one.**

pydeako 0.6.0 puts the correct `"dim": 0` on the wire and the hub applies it. Only
the library's in-memory cache — the thing `DeakoLightEntity.brightness` reads — is
wrong. It reports the *previous* brightness instead of zero, for up to ~2 minutes.

Additional findings, both of which change the shape of the fix:

1. **The inbound EVENT path is poisoned too — and in 0.6.0 it is the only path
   that exists.** A hub-originated `dim: 0` that the client never requested
   (physical button, Deako app, another controller) is also discarded. Worse,
   0.6.0 silently dropped the optimistic local echo entirely: `_Request`'s
   `complete_callback()` has no call site anywhere in the 0.6.0 package, so
   `control_device()`'s callback into `update_state()` never runs. Every cache
   update now depends on the EVENT path, which is the poisoned one.
2. **A device-list refresh repairs the cache.** `record_device()` assigns dim
   unconditionally, so the next `find_devices()` heals it. The integration
   refreshes on every property read but self-throttles to one refresh per ~120 s
   (`custom_components/deako/light.py:223-248`), so the wrong brightness is
   visible for up to about two minutes, not indefinitely.
3. **This is a genuine regression, but 0.3.1 is not clean either.** 0.3.1 handles
   zero correctly and instead corrupts the cache on a plain on/off command.
4. **It is live, not latent** — but not by the route the ticket assumed. Home
   Assistant never delivers `brightness: 0` to the integration. It does deliver
   `brightness: 1`, and the integration's own conversion turns that into a falsy
   `0.0`.

## Root cause (confirmed at runtime, not just by reading)

`pydeako/deako/_deako.py`, `Deako.update_state()`:

```python
# 0.3.1
self.devices[uuid]["state"]["dim"] = dim

# 0.6.0
# dimmables don't always send dim
self.devices[uuid]["state"]["dim"] = (
    dim or self.devices[uuid]["state"]["dim"]
)
```

`0 or 80 == 80`. `0.0 or 80 == 80`. The guard was clearly added to stop a
`dim=None` command from wiping the cached brightness (which 0.3.1 does — see case
4), but `or` tests falsiness rather than `None`, so it swallows legitimate zeros.

`update_state()` has two potential callers, and the experiment shows they do not
behave the same way in the two versions:

- `control_device()`'s `completed_callback` — the optimistic local echo of our own
  command. **In 0.6.0 this never fires.** `_Request.complete_callback()` is defined
  (`pydeako/deako/_request.py:31-34`) but has no call site anywhere in the 0.6.0
  package; 0.3.1 invokes it from `_manager.py:189` inside `process_queue_item()`,
  which 0.6.0 deleted along with the send queue. Runtime confirmation: on 0.6.0 the
  cache is unchanged 1.2 s after a `dim=50` command and only moves when the hub's
  EVENT lands (case 5); on 0.3.1 it moves immediately.
- `incoming_json()` on a `ResponseType.EVENT` — the hub's own truthful report. This
  is poisoned by the `or` in both the requested-change and the out-of-band case
  (cases 1, 2, 3, 3b, and critically 6).

So on 0.6.0 the EVENT path is the *only* writer of cached state after startup, and
that single path discards zero. The answer to "is the inbound EVENT path poisoned
too" is therefore **yes, and it is the only path that matters**.

The outbound path is unaffected in both versions: `state_change_request()` in
`pydeako/models/_request.py` uses `if dim is not None: state["dim"] = dim`, which
is byte-identical in 0.3.1 and 0.6.0.

## Evidence

Device under test: dimmable, starting at `power=true, dim=80`. "wire" is the exact
JSON captured by a TCP tap between the client and the simulator. "sim" is the
simulator's state over its HTTP API. "cache" is `Deako.get_state(uuid)`. The
`+1.2s` column is sampled after the local echo would fire but before the hub's
EVENT (~2 s after the acknowledgment); `after EVENT` is sampled after it. Bold
marks a cache that disagrees with the hub.

### pydeako 0.6.0

| # | Input | Wire (client→hub) | Sim after | Cache +1.2s | Cache after hub EVENT | Cache after refresh | HA would report |
|---|-------|-------------------|-----------|-------------|-----------------------|---------------------|-----------------|
| 1 | `control_device(u, True, 0)` | `{"power": true, "dim": 0}` | `power=true, dim=0` | dim=80 | **dim=80** | dim=0 | **204** |
| 2 | `control_device(u, False, 0)` | `{"power": false, "dim": 0}` | `power=false, dim=0` | dim=80 | `power=false`, **dim=80** | dim=0 | **204** |
| 3 | `control_device(u, True, 0.0)` | `{"power": true, "dim": 0.0}` | `power=true, dim=0` | dim=80 | **dim=80** | dim=0 | **204** |
| 3b | HA brightness 1 → `dim=0.0` | `{"power": true, "dim": 0.0}` | `power=true, dim=0` | dim=80 | **dim=80** | dim=0 | **204** |
| 3c | HA brightness 3 → `dim=1.0` | `{"power": true, "dim": 1.0}` | `power=true, dim=1` | dim=80 (no echo) | dim=1 | dim=1 | 3 |
| 4 | `control_device(u, True, None)` | `{"power": true}` (no dim) | `power=true, dim=80` | dim=80 | dim=80 | dim=80 | 204 |
| 5 | `control_device(u, True, 50)` | `{"power": true, "dim": 50}` | `power=true, dim=50` | dim=80 (no echo) | dim=50 | dim=50 | 127 |
| 6 | Hub-originated EVENT `dim: 0` | *(no client command)* | `power=true, dim=0` | dim=80 | **dim=80** | dim=0 | **204** |
| 6b | Hub-originated EVENT `dim: 25` | *(no client command)* | `power=true, dim=25` | dim=25 | dim=25 | dim=25 | 64 |

Cases 3c and 5 are the controls that expose the dead echo: a perfectly ordinary
non-zero command also leaves the cache stale at +1.2 s, and is corrected only by
the hub's EVENT. Cases 1/3/3b/6 differ in that the EVENT never corrects it.

### pydeako 0.3.1

| # | Input | Wire (client→hub) | Sim after | Cache +1.2s | Cache after hub EVENT | Cache after refresh | HA would report |
|---|-------|-------------------|-----------|-------------|-----------------------|---------------------|-----------------|
| 1 | `control_device(u, True, 0)` | `{"power": true, "dim": 0}` | `power=true, dim=0` | dim=0 | dim=0 | dim=0 | 0 |
| 2 | `control_device(u, False, 0)` | `{"power": false, "dim": 0}` | `power=false, dim=0` | dim=0 | dim=0 | dim=0 | 0 |
| 3 | `control_device(u, True, 0.0)` | `{"power": true, "dim": 0.0}` | `power=true, dim=0` | dim=0.0 | dim=0 | dim=0 | 0 |
| 3b | HA brightness 1 → `dim=0.0` | `{"power": true, "dim": 0.0}` | `power=true, dim=0` | dim=0.0 | dim=0 | dim=0 | 0 |
| 3c | HA brightness 3 → `dim=1.0` | `{"power": true, "dim": 1.0}` | `power=true, dim=1` | dim=1.0 | dim=1 | dim=1 | 3 |
| 4 | `control_device(u, True, None)` | `{"power": true}` (no dim) | `power=true, dim=80` | **dim=None** | dim=80 | dim=80 | **TypeError** |
| 5 | `control_device(u, True, 50)` | `{"power": true, "dim": 50}` | `power=true, dim=50` | dim=50 | dim=50 | dim=50 | 127 |
| 6 | Hub-originated EVENT `dim: 0` | *(no client command)* | `power=true, dim=0` | dim=0 | dim=0 | dim=0 | 0 |
| 6b | Hub-originated EVENT `dim: 25` | *(no client command)* | `power=true, dim=25` | dim=25 | dim=25 | dim=25 | 64 |

Raw captures, including every wire message: `research/data/zero-dim-pydeako-0.6.0.json`,
`research/data/zero-dim-pydeako-0.3.1.json`.

All six requested cases ran; nothing was blocked or skipped. Three extra cases
(3b, 3c, 6b) were added as controls.

### The 0.3.1 tradeoff, characterised precisely

0.3.1 is not simply "correct". On case 4 (`control_device(u, True, None)`, which
is what the integration sends for a plain on/off) it assigns `dim = None`
unconditionally, so the cache reads `{"power": true, "dim": None}` until the hub's
EVENT arrives ~2 s later and restores the real value. During that window:

- `DeakoLightEntity.brightness` computes `int(round(None * 2.55))` →
  **`TypeError: unsupported operand type(s) for *: 'NoneType' and 'float'`**
  (`custom_components/deako/light.py:109`, verified by direct evaluation).
- `supported_color_modes` sees `dim is None` and reports `ColorMode.ONOFF`
  instead of `ColorMode.BRIGHTNESS` (`light.py:111-122`), i.e. the entity briefly
  stops being a dimmer.

So the choice is not "0.3.1 good / 0.6.0 bad". It is: 0.3.1 breaks the cache on
every plain on/off for ~2 s; 0.6.0 fixed that and broke explicit zero for up to
~120 s. Both are the same class of bug — an unconditional write versus a falsy
guard — and both are fixed by the same one-line change.

## Does Home Assistant ever send brightness 0?

Checked against a real installed Home Assistant **2025.11.0** in the WSL e2e
environment (`~/ha_venv/lib/python3.13/site-packages/homeassistant/`), not from
memory. Schema behaviour was executed, not inferred.

- **`light.turn_on` with `brightness: 0` never reaches the integration's
  `async_turn_on`.** `components/light/__init__.py:648-651`:
  ```python
  if params.get(ATTR_BRIGHTNESS) == 0 or params.get(ATTR_WHITE) == 0:
      await async_handle_light_off_service(light, call)
  else:
      await light.async_turn_on(**filter_turn_on_params(light, params))
  ```
- **`brightness_pct: 0` behaves identically.** `preprocess_turn_on_alternatives`
  (`__init__.py:345-347`) rewrites it to `brightness = round(255 * 0 / 100) = 0`
  before that check. Executed: `{'brightness_pct': 0}` → `{'brightness': 0}`.
- **`light.turn_off` does NOT accept `brightness`.** `LIGHT_TURN_OFF_SCHEMA`
  (`__init__.py:284-287`) contains only `ATTR_TRANSITION` and `ATTR_FLASH`, and
  `filter_turn_off_params` (`__init__.py:350-364`) returns
  `{k: v for k, v in params.items() if k in (ATTR_TRANSITION, ATTR_FLASH)}`.
  Executed against the real schema:
  `turn_off {'brightness': 0}` → `Invalid: extra keys not allowed @ data['brightness']`.

  **Therefore the `ATTR_BRIGHTNESS` branch in `DeakoLightEntity.async_turn_off`
  (`custom_components/deako/light.py:135-137`) is dead code.** Case 2 above can
  never be reached from Home Assistant. It only matters if something calls
  `control_device` directly.

- **But brightness 1 is live.** `VALID_BRIGHTNESS` is
  `vol.All(vol.Coerce(int), vol.Clamp(min=0, max=255))`, so `brightness: 1` is
  valid, is not `== 0`, and reaches `async_turn_on`. The integration then computes
  `round(1 / 2.55, 0) == 0.0`, which is falsy. Executed:
  `{'brightness_pct': 0.4}` also normalises to `brightness: 1`.

**Conclusion: live, not latent, via a narrow door.** The reachable trigger is not
"HA sends 0" — HA never does. It is "HA sends 1 (or `brightness_pct` ≤ 0.4) and
the *integration's own* `round(x / 2.55, 0)` produces `0.0`". Any UI brightness
slider dragged to its minimum, or a scene/script specifying `brightness: 1`, does
this. The other reachable trigger is case 6: an out-of-band change to 0% from a
physical Deako button or the Deako app, which needs no Home Assistant action at
all and is arguably the more likely one in a real house.

## Recommended workaround

**Recommendation: fix it integration-side by never manufacturing a falsy dim —
clamp the turn-on conversion to `max(1, round(brightness / 2.55))` and delete the
dead `ATTR_BRIGHTNESS` branch in `async_turn_off` — and accept the residual
out-of-band case as cosmetic.** That closes every client-initiated route into the
bug: Home Assistant already reroutes `brightness: 0` to `turn_off` (which cannot
carry brightness at all), and the clamp stops `brightness: 1` from becoming a
falsy `0.0`. The library-side one-liner (`dim if dim is not None else old`) is the
unambiguously *correct* fix and is the only thing that can repair case 6, the
hub-originated zero, since 0.6.0 has no local echo left to compensate with — but
pydeako has had no release since 2024-12-05, so shipping it means vendoring or
monkey-patching the library, which is precisely the burden this effort exists to
reduce, and that is a bad trade for a display-only defect that self-heals within
~120 s. Option (ii), "stop trusting `client.get_state()` for brightness", is not
actually available: with the echo dead, `get_state()` is the only brightness
source the integration has. **For the 0.6.0 upgrade decision this is not a
blocker** — it is a cosmetic, self-healing misreport at the very bottom of the
dimming range, strictly less damaging than the `TypeError`-on-every-plain-on/off
that 0.3.1 exhibits in the house today. It should be recorded as a known deviation
with the clamp applied, not treated as a gate.

## Reproducing

```bash
# Inside WSL, from the repo root:
bash specs/001-deako-hub-simulator/e2e/wsl_run_zero_dim_experiment.sh
```

Harness:

- `e2e/zero_dim_sim_runner.py` — starts the simulator on loopback with mDNS
  suppressed, one dimmable device at `dim=80`.
- `e2e/zero_dim_experiment.py` — the version-agnostic driver: TCP tap, the nine
  cases, and the three-way wire/sim/cache capture.
- `e2e/wsl_run_zero_dim_experiment.sh` — builds the two pinned virtualenvs and
  runs both passes against one simulator.

### Two environment facts worth recording

1. **The experiment cannot run on Windows.** `pydeako`'s
   `_SocketConnection.connect_socket` does `address, port = self.address.split(":")`
   and passes the *string* port to `loop.sock_connect`. POSIX `getaddrinfo`
   accepts it; Windows raises `'str' object cannot be interpreted as an integer`
   and no connection is ever established. True of both 0.3.1 and 0.6.0.
2. **pydeako frames requests with no terminator.** `_Request.get_body_str()`
   returns bare `json.dumps(body)` — no newline, no CRLF (the hub terminates its
   own responses with CRLF). Any proxy, tap, or test double that reads client
   traffic with `readline()` will stall. The tap in this harness forwards raw
   bytes immediately and frames for logging with `JSONDecoder.raw_decode`.
3. **The address provider changed shape.** 0.3.1's `_Manager.init_connection` does
   `address = await self.get_address()`; 0.6.0 does
   `address, name = await self.get_address()`. The driver detects which by
   inspecting the installed source. This is an unrelated but real breaking change
   the 0.6.0 upgrade ticket will have to handle — the integration currently
   supplies a plain-string provider (`custom_components/deako/__init__.py:131-134`).
