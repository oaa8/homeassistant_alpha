"""Connection over socket."""
import asyncio

import logging
from typing import Any

from ..models import ResponseType
from ._manager import _Manager

_LOGGER: logging.Logger = logging.getLogger(__package__)


class FindDevicesError(Exception):
    """Unable to find devices."""

    def __init__(self, reason: str = "unknown") -> None:
        """Initialize with optional reason string."""
        self.reason = reason
        super().__init__()

    def __str__(self):
        return f"Failed to find devices: {self.reason}"


DEFAULT_DEVICE_LIST_TIMEOUT_S = 10
DEVICE_LIST_POLLING_INTERVAL_S = 1
DEVICE_FOUND_POLLING_INTERVAL_S = 1

# DEVIATION (O1): a slow hub must not stop the lights from appearing.
# Stock allowed DEVICE_FOUND_TIME_FACTOR_S = 2 seconds per expected device and
# then raised, failing config entry setup outright -- no lights in Home
# Assistant at all. That is replaced by one explicit, generous window for the
# whole enumeration, and by continuing with whatever arrived (see find_devices).
#
# 60s is a defensible placeholder, not a measurement: it comfortably exceeds
# the 2s x device count stock would have allowed for this house, and stays well
# inside Home Assistant's 300s setup ceiling. It only ever elapses in full when
# devices are genuinely missing, because the wait exits as soon as the expected
# count is reached. Replace it with a measured value once the spare switch rig
# has timed real enumeration.
DEVICE_FOUND_WINDOW_S = 60

CAPABILITY_DIMMABLE = "dim"


class Deako:
    """Deako specific socket api."""

    connection_manager: _Manager
    devices: dict[str, Any]
    expected_devices: int

    def __init__(self, get_address, client_name: str | None = None) -> None:
        """Init manager for Deako local integration."""
        self.connection_manager = _Manager(
            get_address,
            self.incoming_json,
            client_name=client_name,
            # DEVIATION (O7): after a reconnect, Home Assistant must show
            # current state. See resync_devices.
            on_connect=self.resync_devices,
        )
        self.devices: dict[str, Any] = {}
        self.expected_devices = 0

    def update_state(
        self, uuid: str, power: bool, dim: int | None = None,
    ) -> None:
        """Update an in memory device's state."""
        if uuid not in self.devices:
            return

        self.devices[uuid]["state"]["power"] = power
        # DEVIATION (O9): brightness must be reported correctly, including
        # zero. Stock wrote `dim or old_dim`, which cannot tell "dim is zero"
        # from "dim was not mentioned": an explicit dim=0 fell through to the
        # previous brightness, leaving the hub at 0% while Home Assistant
        # reported 204. Dimmables genuinely do omit dim on plain on/off, so the
        # absent case still has to preserve the old value -- test for None.
        if dim is not None:
            self.devices[uuid]["state"]["dim"] = dim

        if "callback" in self.devices[uuid]:
            self.devices[uuid]["callback"]()

    def set_state_callback(self, uuid: str, callback) -> None:
        """Add a state update listener."""
        if uuid in self.devices:
            self.devices[uuid]["callback"] = callback

    def incoming_json(self, in_data: dict) -> None:
        """Parse incoming socket data which is json."""
        try:
            if in_data["type"] == ResponseType.DEVICE_LIST:
                subdata = in_data["data"]
                self.expected_devices = subdata["number_of_devices"]
            elif in_data["type"] == ResponseType.DEVICE_FOUND:
                subdata = in_data["data"]
                state = subdata["state"]
                if subdata.get("capabilities") is not None:
                    dimmable = CAPABILITY_DIMMABLE in subdata["capabilities"]
                else:
                    # support older local api versions
                    dimmable = state.get("dim") is not None
                self.record_device(
                    subdata["name"],
                    subdata["uuid"],
                    dimmable,
                    state["power"],
                    state.get("dim"),
                )
            elif in_data["type"] == ResponseType.EVENT:
                subdata = in_data["data"]
                state = subdata["state"]
                self.update_state(
                    subdata["target"], state["power"], state.get("dim"),
                )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            _LOGGER.error("Failed to parse %s: %s", in_data, exc)

    # pylint: disable-next=too-many-arguments
    def record_device(
        self, name: str, uuid: str, dimmable: bool,
        power: bool, dim: int | None = None,
    ) -> None:
        """Store a device in local memory."""
        if uuid not in self.devices:
            self.devices[uuid] = {"state": {}}

        self.devices[uuid]["name"] = name
        self.devices[uuid]["uuid"] = uuid
        self.devices[uuid]["dimmable"] = dimmable
        self.devices[uuid]["state"]["power"] = power
        self.devices[uuid]["state"]["dim"] = dim

        # DEVIATION (O7): stock updated the cache and stopped there, so a
        # DEVICE_FOUND never reached Home Assistant -- the old integration only
        # ever surfaced a refresh through entity property reads. Resyncing on
        # reconnect updates nothing visible without this.
        callback = self.devices[uuid].get("callback")
        if callback is not None:
            callback()

    async def connect(self) -> None:
        """Initiate the connection sequence."""
        await self.connection_manager.init_connection()

    async def disconnect(self) -> None:
        """Close the connection."""
        self.connection_manager.close()

    def is_connected(self) -> bool:
        """Report whether there is a live connection to the hub.

        DEVIATION (O5): when it's broken, you have to be able to tell. Stock
        exposes no honest way to ask -- find_devices() returns success against
        a dead socket, so a hub that vanished a day ago looks identical to a
        healthy one. The availability model and the diagnostic entities both
        need a real answer.
        """
        return self.connection_manager.is_connected()

    async def resync_devices(self) -> None:
        """Re-request the device list so cached state matches the hub.

        DEVIATION (O7): while the connection is down, events are simply not
        delivered -- nothing stores or replays them -- and stock never asks the
        hub what the state is now once the watchdog rebuilds the connection, so
        a change made during an outage can stay wrong indefinitely.

        find_devices() cannot be reused for this. It never resets
        expected_devices or devices, so on a second call both of its wait loops
        fall through immediately; it would look like a resync while waiting for
        nothing. This sends the request and lets the DEVICE_FOUND responses
        land through record_device(), which now notifies listeners.
        """
        _LOGGER.info("Requesting device list to resync state after connect")
        success = await self.connection_manager.send_get_device_list()
        if not success:
            _LOGGER.warning("Could not request device list on connect")

    def get_devices(self) -> dict:
        """Get the devices that have been recorded."""
        return self.devices

    async def find_devices(
        self,
        timeout=DEFAULT_DEVICE_LIST_TIMEOUT_S,
    ) -> None:
        """Request the device list."""
        _LOGGER.info("Finding devices")
        success = await self.connection_manager.send_get_device_list()
        if not success:
            raise FindDevicesError("Failed to send device list request")
        remaining = timeout
        # wait for device list
        while self.expected_devices == 0 and remaining > 0:
            _LOGGER.debug(
                "waiting for device list... time remaining: %is", remaining,
            )
            await asyncio.sleep(DEVICE_LIST_POLLING_INTERVAL_S)
            remaining -= DEVICE_LIST_POLLING_INTERVAL_S

        # if we get a response, expected_devices will be at least 1
        if self.expected_devices == 0:
            raise FindDevicesError(
                "Timed out waiting for device list response",
            )

        remaining = DEVICE_FOUND_WINDOW_S
        while len(self.devices) != self.expected_devices and remaining > 0:
            _LOGGER.debug(
                "waiting for devices... expected: %i, received: "
                + "%i, time remaining: %is",
                self.expected_devices,
                len(self.devices),
                remaining,
            )
            await asyncio.sleep(DEVICE_FOUND_POLLING_INTERVAL_S)
            remaining -= DEVICE_FOUND_POLLING_INTERVAL_S
        _LOGGER.debug("found %i devices", len(self.devices))

        # DEVIATION (O1): stock raised FindDevicesError here, failing config
        # entry setup and leaving the house with no lights at all. Continue
        # with the devices that did report; a shortfall is surfaced as
        # unavailable entities rather than as a dead integration, and it is no
        # longer silent the way the old DEVICE_FOUND_POLLING_INTERVAL_S = 60
        # trick made it (that did not slow a poll, it made this check
        # unreachable).
        if len(self.devices) != self.expected_devices:
            _LOGGER.warning(
                "Enumeration fell short after %is: hub reported %i devices "
                "but only %i were received. Continuing with those.",
                DEVICE_FOUND_WINDOW_S,
                self.expected_devices,
                len(self.devices),
            )

    async def control_device(
        self, uuid: str, power: bool, dim: int | None = None
    ) -> None:
        """Add control request to queue."""

        def completed_callback():
            self.update_state(uuid, power, dim)

        await self.connection_manager.send_state_change(
            uuid, power, dim, completed_callback=completed_callback
        )

    def get_name(self, uuid: str) -> str | None:
        """Get a device's name by uuid."""
        device_data = self.devices.get(uuid)
        if device_data is None:
            return None

        # name should exist if we have data on this device
        return device_data["name"]

    def get_state(self, uuid: str) -> dict | None:
        """Get a device's state by uuid."""
        device_data = self.devices.get(uuid)
        if device_data is None:
            return None

        # state should exist if we have data on this device
        return device_data["state"]

    def is_dimmable(self, uuid: str) -> bool | None:
        """Get whether a device is dimmable by uuid."""
        device_data = self.devices.get(uuid)
        if device_data is None:
            return None

        # dimmable should exist if we have data on this device
        return device_data["dimmable"]
