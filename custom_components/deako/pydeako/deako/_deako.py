"""Connection over socket."""
import asyncio

import logging
from typing import Any, Callable

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


class DeviceCommandError(Exception):
    """A command could not be delivered to the hub.

    DEVIATION (O5): stock had no way to say this. control_device() awaited a
    send that logged its own failure and returned nothing, so a command issued
    while disconnected was swallowed -- the light appeared to accept it and
    then did not move.
    """

    def __init__(self, reason: str = "unknown") -> None:
        """Initialize with optional reason string."""
        self.reason = reason
        super().__init__()

    def __str__(self):
        return f"Failed to send command to the hub: {self.reason}"


DEFAULT_DEVICE_LIST_TIMEOUT_S = 10
DEVICE_LIST_POLLING_INTERVAL_S = 1
DEVICE_FOUND_POLLING_INTERVAL_S = 1

# DEVIATION (O1): a slow hub must not stop the lights from appearing.
# Stock allowed DEVICE_FOUND_TIME_FACTOR_S = 2 seconds per expected device and
# then raised, failing config entry setup outright -- no lights in Home
# Assistant at all. That is replaced by one explicit window for the whole
# enumeration, and by continuing with whatever arrived (see find_devices).
#
# 15s, and no longer a guess: the spare switch rig timed the real hub
# delivering all 37 devices in 487-705ms across repeated starts (wayfinder
# #17), so this is twenty times the measured worst case. It replaces a 60s
# placeholder, which only ever elapsed in full when a device was genuinely
# missing -- and then stalled setup for a minute every time.
#
# Waiting less is also cheaper than it used to be. A straggler that arrives
# after the window is no longer lost: its DEVICE_FOUND is announced and an
# entity is built for it then (DEVIATION O10, record_device). The window now
# decides how long the lights are late, not whether they appear.
DEVICE_FOUND_WINDOW_S = 15

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
            # DEVIATION (O5): pushed so a consumer can mark everything
            # unavailable the moment the hub goes away, instead of serving
            # cached state that stopped being true.
            on_connection_change=self.notify_connection_listeners,
        )
        self.devices: dict[str, Any] = {}
        self.expected_devices = 0
        # DEVIATION (O5): listeners for connection up/down.
        self.connection_listeners: list[Callable[[bool], None]] = []
        # DEVIATION (O10): fired when a device reports for the first time. A
        # device that was silent during enumeration has no entity at all, so
        # there is no per-device callback to reach -- this is how a late
        # arrival gets one.
        self.device_added_callback: Callable[[str], None] | None = None

    def add_connection_listener(
        self, listener: Callable[[bool], None],
    ) -> None:
        """Register a listener for connection up/down (DEVIATION, O5)."""
        if listener not in self.connection_listeners:
            self.connection_listeners.append(listener)

    def remove_connection_listener(
        self, listener: Callable[[bool], None],
    ) -> None:
        """Unregister a connection listener (DEVIATION, O5)."""
        if listener in self.connection_listeners:
            self.connection_listeners.remove(listener)

    def notify_connection_listeners(self, connected: bool) -> None:
        """Tell every listener the connection state changed (DEVIATION, O5).

        One listener raising must not cost the others their notification --
        that would leave part of the house looking healthy and part of it not.
        """
        for listener in list(self.connection_listeners):
            try:
                listener(connected)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                _LOGGER.error("Connection listener failed: %s", exc)

    def set_device_added_callback(
        self, callback: Callable[[str], None] | None,
    ) -> None:
        """Set the callback for a device reporting for the first time.

        DEVIATION (O10): see device_added_callback.
        """
        self.device_added_callback = callback

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
        # DEVIATION (O10): a device that missed enumeration is visible, not
        # silently absent -- and it has to be able to come back. Whether this
        # is the first time we have heard of it decides which callback below
        # can carry the news, so it is answered before the write.
        is_new = uuid not in self.devices
        if is_new:
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

        # DEVIATION (O10): a first-time device has no per-device callback yet,
        # because nothing has been built to listen for it. Announce it so one
        # can be created -- this is the late DEVICE_FOUND arriving.
        if is_new and self.device_added_callback is not None:
            try:
                self.device_added_callback(uuid)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                _LOGGER.error("Device added callback failed: %s", exc)

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
        """Send a state change to the hub.

        DEVIATION (O5): commands issued while disconnected must fail visibly.
        Stock awaited a send whose failure only ever reached a log line, so the
        light took the command, reported nothing wrong, and did not move.
        """

        def completed_callback():
            self.update_state(uuid, power, dim)

        sent = await self.connection_manager.send_state_change(
            uuid, power, dim, completed_callback=completed_callback
        )
        if not sent:
            raise DeviceCommandError(
                "no live connection to the hub"
                if not self.is_connected()
                else "the hub did not accept the command"
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
