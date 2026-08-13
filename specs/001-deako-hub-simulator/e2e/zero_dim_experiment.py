"""Zero-dim regression experiment: pydeako 0.3.1 vs 0.6.0 against the simulator.

Research issue: oaa8/deako-house-wayfinder#12 -- "Does 0.6.0 break setting zero
brightness (dim or old_dim)?"

The claim under test is that 0.6.0's `Deako.update_state()` writes
`dim or self.devices[uuid]["state"]["dim"]`, so an explicit falsy dim (0 or 0.0)
is discarded and the previously cached brightness survives. This script proves or
disproves that at runtime by capturing three views of every operation:

    1. WIRE  - the exact JSON bytes pydeako put on the socket, captured by an
               in-process TCP tap sitting between the client and the simulator.
    2. SIM   - the simulator's own device state, read back over its HTTP API,
               i.e. what the "hub" actually did.
    3. CACHE - `Deako.get_state(uuid)`, i.e. what the Home Assistant integration
               would report as `brightness`.

Divergence between WIRE/SIM and CACHE is a display bug. Divergence between the
requested value and WIRE/SIM is a functional bug.

Run the SAME file under both pinned virtualenvs; nothing here is version
specific. Only the standard library and pydeako are imported, so the venvs need
no extra dependencies.

Usage:
    python zero_dim_experiment.py --label 0.6.0 --out results-060.json
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import sys
import urllib.request
from importlib.metadata import version as pkg_version
from typing import Any

from pydeako.deako import Deako

DIMMABLE_UUID = "11111111-1111-4111-8111-111111111111"

PYDEAKO_VERSION = pkg_version("pydeako")

# API change between the two versions under test: 0.3.1's _Manager does
# `address = await self.get_address()`, 0.6.0's does
# `address, name = await self.get_address()` (pydeako/deako/_manager.py:71).
# The address provider has to match, so detect it from the installed source
# rather than hard-coding a version comparison.
def _address_provider_returns_tuple() -> bool:
    from pydeako.deako._manager import _Manager

    source = inspect.getsource(_Manager.init_connection)
    return "await self.get_address()" in source and "address, name" in source


ADDRESS_PROVIDER_RETURNS_TUPLE = _address_provider_returns_tuple()

# The integration's own conversion, custom_components/deako/light.py:
#   dim = round(kwargs[ATTR_BRIGHTNESS] / 2.55, 0)
def ha_brightness_to_dim(brightness: int) -> float:
    return round(brightness / 2.55, 0)


class WireTap:
    """TCP proxy that records every line in both directions.

    pydeako connects here instead of to the simulator, so the recorded bytes are
    literally what the library emitted -- no reliance on the simulator's logging
    or on reconstructing the request from library internals.
    """

    def __init__(self, listen_port: int, target_host: str, target_port: int) -> None:
        self.listen_port = listen_port
        self.target_host = target_host
        self.target_port = target_port
        self.lines: list[dict[str, Any]] = []
        self._buffers: dict[str, str] = {"client->hub": "", "hub->client": ""}
        self._server: asyncio.AbstractServer | None = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._handle, host="127.0.0.1", port=self.listen_port
        )

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    def mark(self) -> int:
        return len(self.lines)

    def since(self, mark: int) -> list[dict[str, Any]]:
        return self.lines[mark:]

    def _record(self, direction: str, chunk: bytes) -> None:
        """Split a byte stream into JSON messages for the record.

        pydeako writes `json.dumps(body)` with no terminator at all
        (pydeako/deako/_request.py get_body_str), while the hub terminates with
        CRLF. Framing therefore has to be done on JSON object boundaries, not on
        newlines -- forwarding must never wait for a delimiter that may never
        arrive.
        """
        buffer = self._buffers[direction] + chunk.decode("utf-8", errors="replace")
        decoder = json.JSONDecoder()
        while True:
            buffer = buffer.lstrip("\r\n ")
            if not buffer:
                break
            try:
                parsed, end = decoder.raw_decode(buffer)
            except json.JSONDecodeError:
                break
            self.lines.append(
                {"dir": direction, "raw": buffer[:end], "json": parsed}
            )
            buffer = buffer[end:]
        self._buffers[direction] = buffer

    async def _handle(
        self, client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter
    ) -> None:
        try:
            server_reader, server_writer = await asyncio.open_connection(
                self.target_host, self.target_port
            )
        except OSError:
            client_writer.close()
            return

        async def pump(reader, writer, direction) -> None:
            try:
                while True:
                    chunk = await reader.read(65536)
                    if not chunk:
                        break
                    # Forward first, record second: the tap must add no latency
                    # and must never hold bytes waiting for a frame boundary.
                    writer.write(chunk)
                    await writer.drain()
                    self._record(direction, chunk)
            except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
                pass
            finally:
                try:
                    writer.close()
                except Exception:  # noqa: BLE001, S110 - teardown only
                    pass

        await asyncio.gather(
            pump(client_reader, server_writer, "client->hub"),
            pump(server_reader, client_writer, "hub->client"),
        )


class SimApi:
    """Thin stdlib client for the simulator's HTTP control API."""

    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")

    def get_device(self, uuid: str) -> dict[str, Any]:
        with urllib.request.urlopen(f"{self.base}/api/devices/{uuid}", timeout=5) as resp:
            return json.loads(resp.read().decode())

    def set_state(self, uuid: str, **payload: Any) -> dict[str, Any]:
        body = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{self.base}/api/devices/{uuid}/state",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode())


def sim_state(api: SimApi, uuid: str) -> dict[str, Any]:
    return api.get_device(uuid)["state"]


def cache_state(deako: Deako, uuid: str) -> dict[str, Any]:
    state = deako.get_state(uuid)
    return dict(state) if state else {}


def brightness_from_cache(state: dict[str, Any]) -> Any:
    """Reproduce custom_components/deako/light.py DeakoLightEntity.brightness."""
    dim = state.get("dim", 0)
    if dim is None:
        return None
    return round(dim * 2.55)


async def wait_for_event(seconds: float) -> None:
    """The simulator broadcasts its post-CONTROL EVENT ~2s later (FR-075)."""
    await asyncio.sleep(seconds)


async def run_case(
    *,
    name: str,
    description: str,
    api: SimApi,
    tap: WireTap,
    proxy_port: int,
    action,
    initial_dim: int = 80,
    initial_power: bool = True,
) -> dict[str, Any]:
    """Run one case on a freshly connected client against a freshly reset device.

    A new client per case guarantees no cache carry-over between cases, and the
    reset happens while nothing is connected so the reset's own EVENT cannot
    perturb the measurement.
    """
    api.set_state(DIMMABLE_UUID, power=initial_power, dim=initial_dim)
    await asyncio.sleep(0.3)

    async def get_address():
        address = f"127.0.0.1:{proxy_port}"
        if ADDRESS_PROVIDER_RETURNS_TUPLE:
            return address, "zero-dim-experiment"
        return address

    deako = Deako(get_address)
    result: dict[str, Any] = {"case": name, "description": description}
    try:
        await asyncio.wait_for(deako.connect(), timeout=10)
        await asyncio.wait_for(deako.find_devices(), timeout=20)
        mark = tap.mark()

        result["sim_before"] = sim_state(api, DIMMABLE_UUID)
        result["cache_before"] = cache_state(deako, DIMMABLE_UUID)

        await action(deako, api)

        # Snapshot between the local echo and the hub's EVENT. pydeako's send
        # worker ticks every WORKER_WAIT_S=0.5s, so control_device's
        # completed_callback can lag the call by up to ~0.6s; the simulator
        # broadcasts its EVENT ~2.0s after the acknowledgment (FR-075). 1.2s
        # sits cleanly between the two.
        await asyncio.sleep(1.2)
        result["cache_after_action"] = cache_state(deako, DIMMABLE_UUID)

        # After the hub's own EVENT, which reports the truthful state.
        await wait_for_event(1.8)
        result["cache_after_hub_event"] = cache_state(deako, DIMMABLE_UUID)
        result["sim_after"] = sim_state(api, DIMMABLE_UUID)

        result["wire"] = tap.since(mark)

        # Does a device-list refresh repair a corrupted cache? record_device()
        # assigns dim unconditionally in both versions, so it should -- but
        # find_devices() returns as soon as the device count already matches, so
        # the DEVICE_FOUND stream must be given time to land before reading.
        try:
            await asyncio.wait_for(deako.find_devices(), timeout=20)
            await asyncio.sleep(1.5)
            result["cache_after_refresh"] = cache_state(deako, DIMMABLE_UUID)
        except Exception as exc:  # noqa: BLE001 - report, don't abort the suite
            result["cache_after_refresh"] = f"ERROR {type(exc).__name__}: {exc}"

        result["ha_brightness_reported"] = brightness_from_cache(
            result["cache_after_hub_event"]
        )
    except Exception as exc:  # noqa: BLE001 - a failed case must not kill the run
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            await deako.disconnect()
        except Exception:  # noqa: BLE001, S110 - teardown only
            pass
        await asyncio.sleep(0.6)
    return result


def control(power: bool, dim: Any):
    async def action(deako: Deako, _api: SimApi) -> None:
        await deako.control_device(DIMMABLE_UUID, power, dim)

    return action


def hub_originated(power: bool, dim: Any):
    """Change state through the simulator's API so the hub pushes an EVENT.

    This is the path the library did NOT initiate: a physical button press, a
    Deako app change, or any other out-of-band update.
    """

    async def action(_deako: Deako, api: SimApi) -> None:
        api.set_state(DIMMABLE_UUID, power=power, dim=dim)

    return action


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True, help="pydeako version label")
    parser.add_argument("--sim-host", default="127.0.0.1")
    parser.add_argument("--sim-port", type=int, default=8023)
    parser.add_argument("--http-port", type=int, default=8080)
    parser.add_argument("--proxy-port", type=int, default=8123)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    api = SimApi(f"http://127.0.0.1:{args.http_port}")
    tap = WireTap(args.proxy_port, args.sim_host, args.sim_port)
    await tap.start()

    cases = [
        (
            "1_control_on_dim_0",
            "control_device(uuid, True, 0) - explicit int zero, power on",
            control(True, 0),
        ),
        (
            "2_control_off_dim_0",
            (
                "control_device(uuid, False, 0) - explicit int zero, power off "
                "(the integration's async_turn_off path)"
            ),
            control(False, 0),
        ),
        (
            "3_control_on_dim_0_float",
            "control_device(uuid, True, 0.0) - float zero, what round(x/2.55, 0) returns",
            control(True, 0.0),
        ),
        (
            "3b_control_on_ha_brightness_1",
            "HA brightness=1 -> round(1/2.55, 0) == 0.0, integration's exact math",
            control(True, ha_brightness_to_dim(1)),
        ),
        (
            "3c_control_on_ha_brightness_3",
            "HA brightness=3 -> round(3/2.55, 0) == 1.0, first non-falsy dim",
            control(True, ha_brightness_to_dim(3)),
        ),
        (
            "4_control_on_dim_none",
            (
                "control_device(uuid, True, None) - plain on, no dim "
                "(0.3.1 is expected to wipe the cached dim here)"
            ),
            control(True, None),
        ),
        (
            "5_control_on_dim_50",
            "control_device(uuid, True, 50) - non-zero sanity baseline",
            control(True, 50),
        ),
        (
            "6_hub_event_dim_0",
            "Hub-originated EVENT carrying dim: 0, not initiated by the client",
            hub_originated(True, 0),
        ),
        (
            "6b_hub_event_dim_25",
            "Hub-originated EVENT carrying dim: 25, non-falsy control for case 6",
            hub_originated(True, 25),
        ),
    ]

    results = []
    for name, description, action in cases:
        print(f"--- {args.label}: {name}", flush=True)
        res = await run_case(
            name=name,
            description=description,
            api=api,
            tap=tap,
            proxy_port=args.proxy_port,
            action=action,
        )
        results.append(res)
        print(json.dumps(res, indent=2), flush=True)

    await tap.stop()

    payload = {
        "label": args.label,
        "pydeako_version": PYDEAKO_VERSION,
        "python": sys.version,
        "results": results,
    }
    with open(args.out, "w", encoding="utf-8") as handle:  # noqa: ASYNC230 - one write at shutdown
        json.dump(payload, handle, indent=2)
    print(f"wrote {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
