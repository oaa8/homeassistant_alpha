# Deako local integration protocol — observed behaviour

**Status**: verified against real firmware (`3.21.9-prod-2025.232`) on a 37-device
profile, 2026-08-15. Every claim below is either measured on the wire or marked
as coming from the vendor documentation.

Sources, in order of authority:

1. **This document's measurements** — captured traffic, reproducible.
2. [`DeakoLights/local-integrations/API.md`](https://github.com/DeakoLights/local-integrations/blob/master/API.md)
   — the vendor's own documentation, v1.5, last revised **2020**. Several of its
   claims are wrong; each is flagged below.
3. The vendor's [open issues](https://github.com/DeakoLights/local-integrations/issues)
   — useful corroboration, since other integrators hit the same walls.

The transport is telnet on port 23, single-line JSON, CRLF terminated. There is
no handshake or banner; a client may send immediately. The vendor asks that
messages be sent no faster than **800 ms apart**.

## Requests a client can send

| Type | Where the target goes | Reply | Verified |
|---|---|---|---|
| `DEVICE_LIST` | n/a | `DEVICE_LIST` with a count, then one `DEVICE_FOUND` per device | yes |
| `CONTROL` | `data.target` | `CONTROL` acknowledgement, then an `EVENT` if the device actually moved | yes |
| `PING` | n/a — **any target is ignored** | `PING` acknowledgement, echoing `transactionId` | yes |
| `DEVICE_POLL` | **`target` at the message root** | `DEVICE_POLL` carrying the device | yes |

### `DEVICE_POLL` — the verb the documentation buried

Doc §3.5.1 gives the poll request as `type: "PING"` with a root `target`. That is
a copy-paste error, and an expensive one: a `PING` shaped exactly that way is a
plain hub ping, so anyone following the documentation concludes the feature does
not work. `pydeako` never implemented the verb, and the vendor's issue #5 —
asking for exactly this capability — has been open since before it shipped.

The real request, and a real reply:

```json
--> {"type":"DEVICE_POLL","target":"<uuid>","transactionId":"<uuid4>",
     "src":"<client>","dst":"deako"}

<-- {"type":"DEVICE_POLL","transactionId":"<uuid4>","dst":"deako","src":"deako",
     "status":"error","timestamp":1786846239,
     "data":{"name":"<name>","uuid":"<uuid>","capabilities":"power+dim",
             "state":{"power":true,"dim":60}}}
```

Three things about that reply are wrong or surprising, and a client must handle
all of them:

- **`status` is `"error"` on success.** Measured across **534 replies: 534
  `error`, zero `ok`** — every device, every condition, including against a
  profile where all 37 devices were confirmed reachable. It is a constant, not a
  signal. Branch on whether `data` carries a device, never on `status`.
- **`dst` is `"deako"`** — the hub addresses itself rather than the requesting
  client. Every other reply type addresses the client correctly.
- **The doc says the reply is a `DEVICE_FOUND`.** It is typed `DEVICE_POLL`.

The `data.target` form of the request, which the doc's structure implies, is
answered with **silence**, as is a bare `DEVICE_POLL` with no target at all.

### `PING` is hub-level

Tested with a root `target`, a `data.target`, and no target, against both a
reachable and an unreachable device: **all four produce the identical bare
acknowledgement**. The target is ignored. `PING` answers "is the hub alive",
never anything about a device.

The reply is typed `PING`, not `PONG` — there is no `PONG` on the wire. It does
echo the request's `transactionId`, so strict correlation is possible.

## Messages the hub sends

| Type | Solicited | Carries | Notes |
|---|---|---|---|
| `DEVICE_LIST` | yes | `status:"ok"`, `data.number_of_devices` | a count only, no identities |
| `DEVICE_FOUND` | no | `name`, `uuid`, `capabilities`, `state` | no `transactionId`, no `status` |
| `EVENT` | no | `eventType`, `target`, `state` | the only device-sourced message |
| `CONTROL` | yes | `status:"ok"` and nothing else | acknowledgement only, **no `data`** |
| `DEVICE_POLL` | yes | the device, under `status:"error"` | see above |

`DEVICE_FOUND` was inventoried across 185 records: the field set never varies —
`type`, `src`, `timestamp`, and `data{name, uuid, capabilities, state}`. There is
**no reachability, last-seen, staleness or health field of any kind**, and
nothing optional that ever appears or disappears. `state` carries `power`
always, and `dim` only for devices whose `capabilities` is `power+dim`.

Enumeration of 37 devices completes in **330–700 ms**, most records under a
millisecond apart, in a **byte-identical order every time** — including on a
node that had been off the network for twelve hours. It is a list being walked,
not devices being asked.

## Events

There is exactly one `eventType`: **`DEVICE_STATE_CHANGE`**. Confirmed by the
documentation and by all 113 events captured.

Events fire **only on real state change**, from any source — the vendor's app, a
physical press, or another hub entirely. There is no heartbeat, no join or leave
notification, and no periodic report. Ten runs with no device manipulation
produced zero events, so **silence is the healthy case** and time-since-last-event
says nothing about health.

Timing, measured: a `CONTROL` is acknowledged in **50–290 ms** (the
acknowledgement is local and says nothing about the device), and the confirming
`EVENT` follows **1.6–2.4 s** after that.

## Errors

The reply echoes the original message type; the code is in `data.code`.

| Code | Vendor doc | Reality |
|---|---|---|
| `REQUEST_UNKNOWN` | unsupported request type | ✅ as documented |
| `REQUEST_INVALID` | invalid values | ✅ — **also** returned for an unknown uuid, with `"device could not be found"` |
| `REQUEST_MALFORMED` | malformed JSON | ⚠️ misnamed: it fires on **valid JSON missing required fields**. Genuinely broken JSON is **silently ignored** |
| `DEVICE_UNKNOWN` | unknown device | ❌ **does not exist** — `REQUEST_INVALID` is used instead |
| `DEVICE_BUSY` | hub busy | ❌ **does not exist** — the hub **silently drops** commands sent too quickly, with no error at all |

`DEVICE_BUSY`'s absence is the dangerous one: exceeding the documented 800 ms
spacing loses commands with no indication whatsoever.

## How the protocol presents a device it cannot reach

This is the part with no vendor documentation at all, and it governs how an
integration must be written. Measured against a switch physically removed from
the wall, and separately against a powered, in-use switch that had dropped off
the mesh — both behave identically:

| Verb | Unreachable device | Distinguishes it? |
|---|---|---|
| `DEVICE_LIST` | counts it, always | no |
| `DEVICE_FOUND` | streams it every sweep, in its usual position, at the usual speed | no |
| `DEVICE_POLL` | answers normally, with state | no |
| `CONTROL` | **acknowledged `status:"ok"`** in ~110 ms | no |
| `EVENT` | **never arrives** | **yes — the only signal** |

The state served for such a device is the **last state a real device confirmed**.
It is stale, never invented: the hub's cache is written only by a genuine
`EVENT`, and a command that is acknowledged but never carried out does **not**
move it. There is no decay and no marker, so a device that dropped a minute ago
is indistinguishable by reading from one that dropped in June.

**Therefore: a command whose `EVENT` never arrives is the only available
evidence that a device is unreachable.** An idempotent `CONTROL` — asking for the
state the hub already holds — is a usable active probe, since it produces the
confirming `EVENT` without changing anything, but it is only safe while the
cached state is correct.

## Known vendor issues worth reading

- [#1](https://github.com/DeakoLights/local-integrations/issues/1) — `dim` was
  required even for `power`-only devices. Fix was "in testing" in 2020.
- [#4](https://github.com/DeakoLights/local-integrations/issues/4) — `DEVICE_LIST`
  once reported `power: true` for every device. Fixed in firmware.
- [#6](https://github.com/DeakoLights/local-integrations/issues/6) — Gen 1 and
  Gen 2 switches disagreed on reported power state.
- [#7](https://github.com/DeakoLights/local-integrations/issues/7) — asks for
  model, firmware and serial in `DEVICE_FOUND`. Still open, which is why a
  device's serial number cannot be matched to its uuid over this protocol.

## Discovery

mDNS service type `_telnet`, service name `local-integration` — **not**
`_deako._tcp.local.`, which is what the shape of the integration code suggests
and which is wrong. The broadcast also advertises firmware version and the
node's serial number.
