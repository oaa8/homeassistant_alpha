"""The registered-but-unreachable device (wayfinder #13, #23).

This is the house's real failure mode, and the only fault this simulator models
that is **observed hub behaviour** rather than injection of something the hub
does not do. A switch pulled out of the wall months earlier is still on the
node's books, and wayfinder #13 measured what that looks like on the wire,
twice, against firmware 3.21.9-prod-2025.232. Then a whole-house scan found six
of 37 devices in exactly that state -- one of them powered, in daily use, and
invisible to both hubs in both directions.

Four things stay identical to a healthy device and one changes:

  * it still enumerates, in its usual position -- ten sweeps across two days
    never once omitted one;
  * it still answers ``DEVICE_POLL`` with its last known state, because that
    reads the node's own profile rather than the device;
  * it still acknowledges ``CONTROL`` with ``status: "ok"``, in about 110 ms;
  * a press on the wall reaches nobody either -- the house's closet light was
    physically on while both hubs believed it off;
  * **the confirming EVENT never arrives.**

That last line is the entire signal, and the integration's whole detector rests
on it. Two of these are load-bearing in a way that is easy to get wrong: a
simulator that errors on the command, or that updates the device's cached state
optimistically, lets the integration pass a test the real hub fails.
"""

import asyncio
import json

import aiohttp
import pytest

from deako_simulator.config import Config, NetworkConfig
from deako_simulator.models import Device, DeviceState
from deako_simulator.server import DeakoSimulator
from deako_simulator.state import SimulatorState

DIMMER_UUID = "11111111-1111-4111-8111-111111111111"
SWITCH_UUID = "33333333-3333-4333-8333-333333333333"

# The simulator delays a CONTROL's EVENT by ~2s, matching hardware. Proving one
# never comes therefore means outwaiting that with room to spare, which is why
# these tests carry their own timeout rather than the suite's 5s default.
SILENCE_WINDOW_S = 3.5


@pytest.fixture
def test_devices():
    """A dimmer that will be marked unreachable, and a healthy control."""
    return [
        Device(
            uuid=DIMMER_UUID,
            name="Master Closet Light",
            capabilities=["power", "dim"],
            state=DeviceState(power=True, dim=100),
        ),
        Device(
            uuid=SWITCH_UUID,
            name="Hallway",
            capabilities=["power"],
            state=DeviceState(power=False),
        ),
    ]


@pytest.fixture
async def simulator_port(test_devices):
    """Start the simulator on dynamic ports with those two devices."""
    state = SimulatorState(devices=test_devices)
    config = Config(
        devices=test_devices,
        network=NetworkConfig(
            host="127.0.0.1", port=0, http_port=0, mdns_name="test-unreachable"
        ),
        log_level="DEBUG",
        scenarios=[],
    )
    simulator = DeakoSimulator(state=state, config=config)
    await simulator.start()
    port = simulator.server.sockets[0].getsockname()[1]
    http_port = (
        simulator.http_runner.addresses[0][1] if simulator.http_runner else 0
    )
    yield (port, http_port, simulator)
    await simulator.shutdown()


async def send_message(writer: asyncio.StreamWriter, message: dict) -> None:
    """Send JSON message with CRLF termination."""
    writer.write(json.dumps(message).encode() + b"\r\n")
    await writer.drain()


async def read_message(reader: asyncio.StreamReader) -> dict:
    """Read one CRLF-terminated JSON message."""
    line = await reader.readline()
    if not line:
        raise EOFError("Connection closed")
    return json.loads(line[:-2].decode("utf-8"))


async def drain_messages(reader: asyncio.StreamReader, seconds: float) -> list:
    """Collect everything the hub says for a while, then stop."""
    collected = []
    loop = asyncio.get_running_loop()
    deadline = loop.time() + seconds
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            return collected
        try:
            collected.append(
                await asyncio.wait_for(read_message(reader), timeout=remaining)
            )
        except asyncio.TimeoutError:
            return collected


@pytest.mark.asyncio
async def test_unreachable_device_still_enumerates(simulator_port):
    """It appears in every sweep, in its usual position.

    Wayfinder #13 spent this ticket's first two days on the hypothesis that the
    sweep omits an unreachable device, and disproved it: ten sweeps, ten
    complete enumerations, one unchanging uuid set. A simulator that dropped
    the device from the stream would be modelling a hypothesis rather than the
    hardware.
    """
    port, http_port, simulator = simulator_port
    simulator.quirk_manager.set_unreachable_devices({DIMMER_UUID})

    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        await send_message(writer, {"type": "DEVICE_LIST", "transactionId": "s1"})
        messages = await drain_messages(reader, 1.0)

        listing = [m for m in messages if m["type"] == "DEVICE_LIST"][0]
        found = [m for m in messages if m["type"] == "DEVICE_FOUND"]

        assert listing["data"]["number_of_devices"] == 2, \
            "The count includes the unreachable device"
        assert [m["data"]["uuid"] for m in found] == [DIMMER_UUID, SWITCH_UUID], \
            "Both devices announce, in the usual order"
    finally:
        writer.close()
        await writer.wait_closed()


@pytest.mark.asyncio
async def test_unreachable_device_answers_device_poll(simulator_port):
    """The poll reads the node's cache, so it answers exactly as usual.

    #13 proved this by racing the poll against changes made out of band
    through a second hub: six transitions, six follows, the poll never once
    leading the EVENT. It is a cache echo, which is why the integration
    deliberately never sends one.
    """
    port, http_port, simulator = simulator_port
    simulator.quirk_manager.set_unreachable_devices({DIMMER_UUID})

    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        await send_message(
            writer,
            {"type": "DEVICE_POLL", "transactionId": "p1", "target": DIMMER_UUID},
        )
        response = await asyncio.wait_for(read_message(reader), timeout=1.0)

        assert response["type"] == "DEVICE_POLL"
        assert response["status"] == "error", "The constant, not a signal"
        assert response["data"]["uuid"] == DIMMER_UUID
        assert response["data"]["state"] == {"power": True, "dim": 100}, \
            "It answers with the last state a real device confirmed"
    finally:
        writer.close()
        await writer.wait_closed()


@pytest.mark.asyncio
@pytest.mark.timeout(20)
async def test_unreachable_device_acks_control_but_never_reports(simulator_port):
    """The whole of it: acknowledged, unmoved, and silent.

    Three assertions, and each one is a way a lazier simulator would let the
    integration pass a test the real hub fails.
    """
    port, http_port, simulator = simulator_port
    simulator.quirk_manager.set_unreachable_devices({DIMMER_UUID})

    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        await send_message(
            writer,
            {
                "type": "CONTROL",
                "transactionId": "c1",
                "data": {"target": DIMMER_UUID, "state": {"power": False, "dim": 0}},
            },
        )

        # 1. The acknowledgement is a plain "ok". The hub answers this way in
        #    ~110 ms for a device that does not physically exist any more, so
        #    an integration that treats the ack as success is already wrong.
        ack = await asyncio.wait_for(read_message(reader), timeout=1.0)
        assert ack["type"] == "CONTROL" and ack["status"] == "ok", \
            f"Expected a plain ok acknowledgement, got {ack!r}"

        # 2. Nothing follows it. The EVENT is the only device-sourced message
        #    in this protocol, and it never comes. Waited well past the ~2s the
        #    simulator delays a real one by.
        silence = await drain_messages(reader, 3.5)
        assert silence == [], \
            f"An unreachable device must never report; got {silence!r}"

        # 3. The cached state did not move. The real hub never optimistically
        #    updates -- the dead switch in the house still read power:true
        #    after being commanded off and acked.
        device = simulator.state.get_device(DIMMER_UUID)
        assert (device.state.power, device.state.dim) == (True, 100), \
            "Cached state is stale, never invented"
    finally:
        writer.close()
        await writer.wait_closed()


@pytest.mark.asyncio
@pytest.mark.timeout(20)
async def test_reachable_device_still_reports(simulator_port):
    """The control, without which none of the above proves anything.

    #13's detector was only believable because the live switch was witnessed
    every time in the same run the dead one was not.
    """
    port, http_port, simulator = simulator_port
    simulator.quirk_manager.set_unreachable_devices({DIMMER_UUID})

    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        await send_message(
            writer,
            {
                "type": "CONTROL",
                "transactionId": "c2",
                "data": {"target": SWITCH_UUID, "state": {"power": True}},
            },
        )

        ack = await asyncio.wait_for(read_message(reader), timeout=1.0)
        assert ack["type"] == "CONTROL" and ack["status"] == "ok"

        messages = await drain_messages(reader, 3.5)
        events = [m for m in messages if m["type"] == "EVENT"]
        assert len(events) == 1, \
            f"The reachable device must be witnessed; got {messages!r}"
        assert events[0]["data"]["eventType"] == "DEVICE_STATE_CHANGE"
        assert events[0]["data"]["target"] == SWITCH_UUID
        assert events[0]["data"]["state"]["power"] is True

        device = simulator.state.get_device(SWITCH_UUID)
        assert device.state.power is True
    finally:
        writer.close()
        await writer.wait_closed()


@pytest.mark.asyncio
@pytest.mark.timeout(20)
async def test_unreachable_device_is_deaf_to_the_wall_too(simulator_port):
    """A press on the wall reaches nobody either.

    `Master Closet Light` was physically on while both hubs believed it off, so
    the invisibility runs in both directions. Modelling only the outbound half
    would let a detector "recover" a device by means the house does not have.
    """
    port, http_port, simulator = simulator_port
    simulator.quirk_manager.set_unreachable_devices({DIMMER_UUID})

    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        # Make this the active connection, which is what EVENTs are sent to.
        await send_message(writer, {"type": "PING", "transactionId": "ping"})
        await asyncio.wait_for(read_message(reader), timeout=1.0)

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"http://127.0.0.1:{http_port}/api/devices/{DIMMER_UUID}/button"
            ) as resp:
                assert resp.status == 200
                body = await resp.json()
        assert body["unreachable"] is True

        silence = await drain_messages(reader, 1.0)
        assert silence == [], \
            f"A press on an unreachable switch is unheard; got {silence!r}"

        device = simulator.state.get_device(DIMMER_UUID)
        assert device.state.power is True, \
            "The hub's view of it did not move, because the mesh never heard"
    finally:
        writer.close()
        await writer.wait_closed()


@pytest.mark.asyncio
@pytest.mark.timeout(20)
async def test_unreachable_can_be_driven_over_http(simulator_port):
    """The e2e harness drives this over HTTP, so that path is proven here.

    An unknown uuid is refused rather than silently accepted: a typo in a test
    script that quietly marked nothing unreachable would produce a green run
    that proved the opposite of what it claimed.
    """
    port, http_port, simulator = simulator_port

    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"http://127.0.0.1:{http_port}/api/control/unreachable",
            json={"uuids": [DIMMER_UUID]},
        ) as resp:
            assert resp.status == 200
            assert (await resp.json())["unreachable"] == [DIMMER_UUID]
        assert simulator.quirk_manager.is_unreachable(DIMMER_UUID)

        async with session.post(
            f"http://127.0.0.1:{http_port}/api/control/unreachable",
            json={"uuids": ["99999999-9999-4999-8999-999999999999"]},
        ) as resp:
            assert resp.status == 404
        assert simulator.quirk_manager.is_unreachable(DIMMER_UUID), \
            "A refused request must not clear what was already set"

        async with session.post(
            f"http://127.0.0.1:{http_port}/api/control/unreachable",
            json={"uuids": []},
        ) as resp:
            assert resp.status == 200
        assert not simulator.quirk_manager.is_unreachable(DIMMER_UUID)


@pytest.mark.asyncio
@pytest.mark.timeout(20)
async def test_clearing_the_mark_restores_reporting(simulator_port):
    """A device that comes back is witnessed again.

    The integration's mark clears on any EVENT, so the simulator has to be able
    to produce one again once the device is back on the mesh -- otherwise the
    end-to-end recovery path could never be exercised.
    """
    port, http_port, simulator = simulator_port
    simulator.quirk_manager.set_unreachable_devices({DIMMER_UUID})
    simulator.quirk_manager.set_unreachable_devices(set())

    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        await send_message(
            writer,
            {
                "type": "CONTROL",
                "transactionId": "c3",
                "data": {"target": DIMMER_UUID, "state": {"power": False, "dim": 0}},
            },
        )
        ack = await asyncio.wait_for(read_message(reader), timeout=1.0)
        assert ack["status"] == "ok"

        messages = await drain_messages(reader, 3.5)
        events = [m for m in messages if m["type"] == "EVENT"]
        assert len(events) == 1, f"Expected the device to report; got {messages!r}"
        assert events[0]["data"]["target"] == DIMMER_UUID
    finally:
        writer.close()
        await writer.wait_closed()
