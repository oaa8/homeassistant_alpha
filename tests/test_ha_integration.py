"""
Home Assistant facing contract tests for the Deako simulator.

Module: test_ha_integration.py
Created: 2025-11-08
Last Modified: 2026-08-11
Author: GitHub Copilot
Purpose: Verify the surface Home Assistant and pydeako actually consume when
    they talk to a hub -- mDNS advertisement, the DEVICE_LIST/DEVICE_FOUND
    handshake, control, polling and the HTTP control API -- so that the
    simulator can be trusted as a stand-in for real hardware when upgrading
    the integration.

Key Assumptions:
    - Tests must be self-contained and deterministic. Every test starts its own
      simulator on an ephemeral port (port=0) rather than assuming an operator
      left one running, so results never depend on machine or LAN state.
    - Home Assistant itself is not installed in this environment. Tests that
      genuinely require it skip rather than fail, and are explicitly marked so
      a skip is never mistaken for a pass.
    - mDNS is exercised through the simulator's own registration path rather
      than a live network browse, because a LAN browse also returns physical
      hubs and would make the suite environment dependent.

Related Requirements:
    - FR-001: mDNS advertisement on both _deako and _telnet service types
    - FR-016: DEVICE_LIST returns a count followed by a DEVICE_FOUND stream
    - FR-017: DEVICE_POLL returns device state (status="error" quirk)

Related Research:
    - research/mdns-service-type-test-2026-08-11.md
    - research/device-list-event-ordering-test-2025-10-25.md

History:
    Replaced an earlier version of this module that could not pass and did not
    test the product: it imported telnetlib (removed in Python 3.13), asserted a
    plaintext PING/PONG protocol the hub has never spoken, requested HTTP routes
    (/status, /devices) that do not exist, and required an externally running
    simulator. It is reconstructed here against the real protocol.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, AsyncGenerator

import pytest

from deako_simulator.config import Config, NetworkConfig
from deako_simulator.mdns_service import (
    DEAKO_SERVICE_TYPE,
    TELNET_SERVICE_TYPE,
)
from deako_simulator.models import Device, DeviceState
from deako_simulator.server import DeakoSimulator
from deako_simulator.state import SimulatorState

REPO_ROOT = Path(__file__).resolve().parents[1]
INTEGRATION_DIR = REPO_ROOT / "custom_components" / "deako"
MANIFEST_PATH = INTEGRATION_DIR / "manifest.json"


@pytest.fixture
def ha_devices() -> list[Device]:
    """Device set covering both capability shapes Home Assistant renders.

    A power-only device and dimmable devices are both included because the
    integration maps them onto different Home Assistant light features.
    """
    return [
        Device(
            uuid="550e8400-e29b-41d4-a716-446655440001",
            name="Living Room Light",
            capabilities=["power"],
            state=DeviceState(power=False, dim=None),
        ),
        Device(
            uuid="550e8400-e29b-41d4-a716-446655440002",
            name="Bedroom Dimmer",
            capabilities=["power", "dim"],
            state=DeviceState(power=False, dim=0),
        ),
        Device(
            uuid="550e8400-e29b-41d4-a716-446655440003",
            name="Kitchen Light",
            capabilities=["power", "dim"],
            state=DeviceState(power=True, dim=75),
        ),
    ]


@pytest.fixture
async def simulator(
    ha_devices: list[Device],
) -> AsyncGenerator[tuple[DeakoSimulator, int, int], None]:
    """Start a simulator on ephemeral ports and yield (simulator, port, http_port).

    Port 0 lets the OS assign free ports so tests can run concurrently and never
    collide with a simulator an operator is running by hand.
    """
    config = Config(
        devices=ha_devices,
        network=NetworkConfig(
            host="127.0.0.1",
            port=0,
            http_port=0,
            mdns_name="test-ha-integration",
        ),
        log_level="INFO",
        scenarios=[],
    )
    simulator = DeakoSimulator(state=SimulatorState(devices=ha_devices), config=config)
    await simulator.start()

    if simulator.server is None:
        raise RuntimeError("Simulator failed to start: server is None after start()")

    port = simulator.server.sockets[0].getsockname()[1]
    http_port = (
        simulator.http_runner.addresses[0][1] if simulator.http_runner else 0
    )

    try:
        yield simulator, port, http_port
    finally:
        await simulator.shutdown()


async def send(writer: asyncio.StreamWriter, message: dict[str, Any]) -> None:
    """Write one CRLF-terminated JSON message, matching the hub's framing."""
    writer.write((json.dumps(message) + "\r\n").encode())
    await writer.drain()


async def recv(reader: asyncio.StreamReader, timeout: float = 2.0) -> dict[str, Any]:
    """Read one CRLF-terminated JSON message, failing fast on timeout."""
    line = await asyncio.wait_for(reader.readline(), timeout=timeout)
    if not line:
        raise EOFError("Connection closed by simulator")
    return json.loads(line.decode().strip())


async def device_list(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Perform the DEVICE_LIST handshake and collect the DEVICE_FOUND stream."""
    await send(
        writer,
        {
            "type": "DEVICE_LIST",
            "src": "test",
            "dst": "deako",
            "transactionId": "test-device-list",
        },
    )
    response = await recv(reader)
    found = [await recv(reader) for _ in range(response["data"]["number_of_devices"])]
    return response, found


class TestManifest:
    """The manifest is what tells Home Assistant how to discover and load the integration."""

    def test_manifest_exists_and_is_valid_json(self):
        """A malformed manifest prevents Home Assistant from loading the integration at all."""
        assert MANIFEST_PATH.exists(), f"Manifest not found: {MANIFEST_PATH}"
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        assert manifest["domain"] == "deako"
        assert manifest.get("config_flow") is True

    def test_manifest_has_no_requirements(self):
        """pydeako is vendored, so the manifest must not install it.

        An earlier revision asserted the opposite -- that requirements included
        a pinned "pydeako==..." -- which was right while the library came from
        PyPI. The library is now a thin in-repo copy at
        custom_components/deako/pydeako, so a requirement would install a second,
        different pydeako alongside the one actually imported.
        """
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        requirements = manifest["requirements"]
        assert requirements == [], (
            f"The vendored library must be the only pydeako; got {requirements}"
        )
        assert (
            INTEGRATION_DIR / "pydeako" / "deako" / "_deako.py"
        ).exists(), "The vendored pydeako copy the manifest relies on is missing"

    def test_manifest_advertises_no_zeroconf_discovery(self):
        """The manifest must not claim a discovery flow the code does not implement.

        This is outcome O8, the map's safety control. The house has three Deako
        nodes, telnet is exclusive, and one of the others serves SmartThings, so
        binding to a node nobody chose takes that connection hostage. A zeroconf
        block makes Home Assistant offer a discovered node for setup, and the
        config flow has no discovery step to handle it. The configured address
        is the only source of an address.

        The discovery *module* stays vendored for a future user-driven picker,
        which by design never auto-binds; what is deleted is the advertisement.
        """
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        assert "zeroconf" not in manifest, (
            f"Manifest must not advertise zeroconf discovery; got "
            f"{manifest.get('zeroconf')}"
        )


class TestDiscovery:
    """mDNS advertisement is how Home Assistant finds a hub without manual config."""

    @pytest.mark.asyncio
    async def test_advertises_both_hub_service_types(self, simulator):
        """A real hub publishes both types; publishing only one breaks a consumer.

        pydeako's DeakoDiscoverer browses _deako exclusively, so omitting it
        makes auto-discovery impossible regardless of the telnet server working.
        """
        sim, _, _ = simulator

        if not sim.service_info:
            pytest.skip("mDNS unavailable in this environment (FR-069 degradation)")

        advertised = {info.type for info in sim.service_info}
        assert DEAKO_SERVICE_TYPE in advertised, (
            f"{DEAKO_SERVICE_TYPE} is required for pydeako and Home Assistant "
            f"discovery; advertised types were {advertised}"
        )
        assert TELNET_SERVICE_TYPE in advertised, (
            f"Real hubs also publish {TELNET_SERVICE_TYPE}; advertised types "
            f"were {advertised}"
        )

    @pytest.mark.asyncio
    async def test_advertisements_carry_resolvable_address(self, simulator):
        """pydeako builds its address from ServiceInfo.addresses.

        A service registered without addresses resolves to an empty list in
        DeakoListener.__get_addresses and the hub is silently discarded, which
        looks identical to "no hub found".
        """
        sim, _, _ = simulator

        if not sim.service_info:
            pytest.skip("mDNS unavailable in this environment (FR-069 degradation)")

        for info in sim.service_info:
            assert info.addresses, (
                f"{info.name} advertised no addresses; pydeako would discard it."
            )


class TestTelnetContract:
    """The protocol surface pydeako drives on behalf of Home Assistant."""

    @pytest.mark.asyncio
    async def test_device_list_returns_count_then_device_found_stream(
        self, simulator, ha_devices
    ):
        """Device discovery is the integration's first call; zero devices aborts setup."""
        _, port, _ = simulator
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        try:
            response, found = await device_list(reader, writer)

            assert response["type"] == "DEVICE_LIST"
            assert response["status"] == "ok"
            assert response["data"]["number_of_devices"] == len(ha_devices), (
                "Device count must match configuration; the integration logs "
                "'received a count of zero devices' and gives up otherwise."
            )
            assert len(found) == len(ha_devices)
            assert {f["data"]["uuid"] for f in found} == {d.uuid for d in ha_devices}
        finally:
            writer.close()
            await writer.wait_closed()

    @pytest.mark.asyncio
    async def test_device_found_carries_fields_the_integration_maps(self, simulator):
        """Missing metadata would surface as unnamed or uncontrollable entities."""
        _, port, _ = simulator
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        try:
            _, found = await device_list(reader, writer)
            for message in found:
                data = message["data"]
                assert data["uuid"], "Entity unique_id derives from uuid"
                assert data["name"], "Entity friendly name derives from name"
                assert "capabilities" in data, "Dimmable support derives from capabilities"
                assert "power" in data["state"], "Light on/off state is required"
        finally:
            writer.close()
            await writer.wait_closed()

    @pytest.mark.asyncio
    async def test_control_changes_state_and_is_observable(self, simulator):
        """Turning a light on must persist, or Home Assistant shows a stale state.

        The resulting state is read back over the HTTP API rather than the
        telnet stream because a CONTROL also triggers a delayed EVENT broadcast;
        reading state out-of-band keeps this test independent of EVENT timing.
        """
        import aiohttp

        _, port, http_port = simulator
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        try:
            _, found = await device_list(reader, writer)
            target = next(
                f["data"]["uuid"]
                for f in found
                if "dim" in str(f["data"]["capabilities"])
            )

            await send(
                writer,
                {
                    "name": "CONTROL",
                    "src": "test",
                    "dst": "deako",
                    "transactionId": "test-control",
                    "data": {"uuid": target, "power": True, "dim": 42},
                },
            )
            ack = await recv(reader)
            assert ack["type"] == "CONTROL"
            assert ack["status"] == "ok", f"CONTROL rejected: {ack}"

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"http://127.0.0.1:{http_port}/api/devices/{target}"
                ) as resp:
                    assert resp.status == 200
                    device = await resp.json()

            state = device["state"]
            assert state["power"] is True, (
                f"Power change did not persist; state was {state}"
            )
            assert state["dim"] == 42, (
                f"Dim change did not persist; state was {state}"
            )
        finally:
            writer.close()
            await writer.wait_closed()

    @pytest.mark.asyncio
    async def test_device_poll_returns_state_with_error_status_quirk(self, simulator):
        """DEVICE_POLL reports status="error" even on success (validated hardware quirk).

        The integration must not treat this as a failure, so the simulator has
        to reproduce it faithfully rather than returning a sensible "ok".
        """
        _, port, _ = simulator
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        try:
            _, found = await device_list(reader, writer)
            target = found[0]["data"]["uuid"]

            await send(
                writer,
                {
                    "type": "DEVICE_POLL",
                    "src": "test",
                    "dst": "deako",
                    "transactionId": "test-poll",
                    "target": target,
                },
            )
            response = await recv(reader)

            assert response["type"] == "DEVICE_POLL"
            # Guard first: an error response also carries status="error", so
            # checking the quirk alone would pass on a malformed request.
            assert "code" not in response["data"], (
                f"DEVICE_POLL was rejected rather than answered: {response['data']}"
            )
            assert response["status"] == "error", (
                "Real hubs return status='error' on a successful DEVICE_POLL; "
                "returning 'ok' would hide a quirk the integration must tolerate."
            )
            assert response["data"]["uuid"] == target
            assert "power" in response["data"]["state"]
        finally:
            writer.close()
            await writer.wait_closed()


class TestHttpControlApi:
    """The HTTP API is how tests drive the simulator during an HA scenario."""

    @pytest.mark.asyncio
    async def test_devices_endpoint_lists_configured_devices(
        self, simulator, ha_devices
    ):
        """Scenario scripts read this endpoint to assert on simulator state."""
        import aiohttp

        _, _, http_port = simulator
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"http://127.0.0.1:{http_port}/api/devices"
            ) as resp:
                assert resp.status == 200
                payload = await resp.json()

        devices = payload["devices"] if isinstance(payload, dict) else payload
        assert len(devices) == len(ha_devices)


class TestHomeAssistantComponents:
    """Structural checks that require Home Assistant; they skip when it is absent."""

    def test_light_platform_exposes_required_entity_methods(self):
        """Home Assistant calls these on every light entity."""
        import sys

        sys.path.insert(0, str(REPO_ROOT / "custom_components"))
        try:
            from deako import light
        except ImportError as e:
            pytest.skip(f"Home Assistant not installed, cannot import light platform: {e}")

        assert hasattr(light, "async_setup_entry")
        assert hasattr(light, "DeakoLight")
        for method in ("async_turn_on", "async_turn_off", "async_update"):
            assert hasattr(light.DeakoLight, method), (
                f"DeakoLight missing required Home Assistant method: {method}"
            )
