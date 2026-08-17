"""Connection over socket."""
import asyncio

import logging
import time
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

# DEVIATION (wayfinder #23): the command-witness reachability detector.
#
# There is no reachability signal in this protocol. #13 measured every
# candidate against a switch that had been pulled out of the wall months
# earlier and was still registered: it enumerates every sweep, it answers
# DEVICE_POLL with its last known state, and a CONTROL to it is acknowledged
# `status: "ok"` in ~110ms. Only one thing tells the truth -- the confirming
# EVENT never arrives. So the detector is a command that goes unwitnessed, and
# the actuation someone already performed is the probe.
#
# 5 seconds: 3x the 1.60s measured between the acknowledgement and the
# confirming EVENT on real hardware, and comfortably over the ~2.4s #17 saw.
WITNESS_WINDOW_S = 5

# Two consecutive misses, never one. One miss is a lost mesh frame; two
# commanded-and-unwitnessed changes on the same device is the pattern a person
# is already complaining about. Any EVENT for the device clears it, from any
# source -- including one a second attempt provokes, which is why the light
# entity deliberately stays available while its node reads `unreachable`.
MISSES_TO_UNREACHABLE = 2

# DEVIATION (wayfinder #25/#26): bring the second miss forward.
#
# #23 left "two consecutive misses" meaning two misses whenever they happened
# to occur -- which, for a switch nobody touches, could be months apart, and
# for the hourly probe would be two cadences apart. Two misses an hour apart do
# not describe one fault; they describe two, and in between the device may have
# come back and gone again. A single retry puts both misses inside a minute,
# which is what the rule was written to mean.
#
# It re-sends the command that was missed rather than the current cached state,
# because the cache did not move -- no EVENT arrived, which is the whole
# premise -- so echoing it would ask for something nobody asked for. Sent once
# per command, never for a device already marked (there is nothing left to
# confirm), and cancelled by anything that answers the question first.
RETRY_DELAY_S = 30


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
        #
        # A list rather than the single slot this used to be: the light and the
        # node status sensor both have to build an entity for a late arrival,
        # and one setter would have let whichever platform loaded second take
        # the news away from the first.
        self.device_added_listeners: list[Callable[[str], None]] = []
        # DEVIATION (wayfinder #23): per-sweep enumeration accounting. The
        # device cache above is never cleared -- a device missing from a later
        # sweep leaves its old entry in place forever -- so which uuids
        # actually reported *this* time has to be tracked outside it.
        self.sweep_listeners: list[Callable[[], None]] = []
        self.sweep_observed: set[str] = set()
        self.sweep_expected = 0
        self.sweep_timer: asyncio.Task | None = None
        self.last_sweep_reporting: int | None = None
        self.last_sweep_expected: int | None = None
        self.last_sweep_missing: list[str] = []
        # DEVIATION (wayfinder #23): the command-witness detector's state.
        # `unreachable` is about the device and survives a reconnect;
        # `pending_witness` is about one command in flight and does not.
        self.reachability_listeners: list[Callable[[str, bool], None]] = []
        self.unreachable: set[str] = set()
        self.consecutive_misses: dict[str, int] = {}
        self.pending_witness: dict[str, asyncio.Task] = {}
        # DEVIATION (wayfinder #26): when the mesh last spoke for each device,
        # on the monotonic clock. The probe skips a device the passive detector
        # has already confirmed this cycle, and "already confirmed" is a
        # question about time, so the answer has to be kept rather than
        # inferred from the miss counters -- those are cleared by a witness and
        # so cannot say when it happened.
        self.last_witness: dict[str, float] = {}
        # DEVIATION (wayfinder #26): the retries that bring a second miss
        # forward. See RETRY_DELAY_S.
        self.pending_retry: dict[str, asyncio.Task] = {}

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
        if not connected:
            # DEVIATION (wayfinder #23): a command whose window was still open
            # when the socket died proves nothing about the device -- the EVENT
            # could not have reached us whether or not the hub sent one. Void
            # those windows rather than let a hub outage mark every light
            # somebody happened to touch as unreachable.
            self.void_pending_witnesses()
        for listener in list(self.connection_listeners):
            try:
                listener(connected)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                _LOGGER.error("Connection listener failed: %s", exc)

    def add_device_added_listener(
        self, listener: Callable[[str], None],
    ) -> None:
        """Register a listener for a device reporting for the first time.

        DEVIATION (O10): see device_added_listeners.
        """
        if listener not in self.device_added_listeners:
            self.device_added_listeners.append(listener)

    def remove_device_added_listener(
        self, listener: Callable[[str], None],
    ) -> None:
        """Unregister a device-added listener (DEVIATION, O10)."""
        if listener in self.device_added_listeners:
            self.device_added_listeners.remove(listener)

    def add_reachability_listener(
        self, listener: Callable[[str, bool], None],
    ) -> None:
        """Register a listener for a device becoming (un)reachable.

        DEVIATION (wayfinder #23): called with (uuid, reachable).
        """
        if listener not in self.reachability_listeners:
            self.reachability_listeners.append(listener)

    def remove_reachability_listener(
        self, listener: Callable[[str, bool], None],
    ) -> None:
        """Unregister a reachability listener (DEVIATION, wayfinder #23)."""
        if listener in self.reachability_listeners:
            self.reachability_listeners.remove(listener)

    def notify_reachability_listeners(
        self, uuid: str, reachable: bool,
    ) -> None:
        """Announce a device's reachability changing (wayfinder #23)."""
        for listener in list(self.reachability_listeners):
            try:
                listener(uuid, reachable)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                _LOGGER.error("Reachability listener failed: %s", exc)

    def add_sweep_listener(self, listener: Callable[[], None]) -> None:
        """Register a listener for an enumeration sweep concluding."""
        if listener not in self.sweep_listeners:
            self.sweep_listeners.append(listener)

    def remove_sweep_listener(self, listener: Callable[[], None]) -> None:
        """Unregister a sweep listener (DEVIATION, wayfinder #23)."""
        if listener in self.sweep_listeners:
            self.sweep_listeners.remove(listener)

    def is_reachable(self, uuid: str) -> bool:
        """Report whether this device has gone unwitnessed twice running.

        DEVIATION (wayfinder #23). Note what this cannot say: a device nobody
        has commanded reads reachable, because nothing contradicts it. The
        detector confirms an unreachable switch the moment someone reaches for
        it; it cannot go and discover one.
        """
        return uuid not in self.unreachable

    def get_unreachable(self) -> set[str]:
        """Return the uuids currently marked unreachable."""
        return set(self.unreachable)

    def get_last_sweep(self) -> tuple[int | None, int | None, list[str]]:
        """Return (reporting, expected, missing uuids) for the last sweep.

        DEVIATION (wayfinder #23). Reporting and expected are None until a
        sweep has concluded, which is a different fact from "zero devices
        reported".
        """
        return (
            self.last_sweep_reporting,
            self.last_sweep_expected,
            list(self.last_sweep_missing),
        )

    def seconds_since_last_message(self) -> float | None:
        """Return how long ago the hub last said anything, in seconds."""
        return self.connection_manager.seconds_since_last_message()

    def get_reconnect_count(self) -> int:
        """Return how many times the connection has been rebuilt."""
        return self.connection_manager.reconnect_count

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
                # DEVIATION (wayfinder #23): the count is the hub answering
                # "how many am I about to announce", so it opens a sweep.
                self.begin_sweep(self.expected_devices)
            elif in_data["type"] == ResponseType.DEVICE_FOUND:
                subdata = in_data["data"]
                state = subdata["state"]
                if subdata.get("capabilities") is not None:
                    dimmable = CAPABILITY_DIMMABLE in subdata["capabilities"]
                else:
                    # support older local api versions
                    dimmable = state.get("dim") is not None
                self.observe_in_sweep(subdata["uuid"])
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
                # DEVIATION (wayfinder #23): an EVENT is the only message the
                # mesh sources, so it is the only thing that witnesses a
                # device. Done before update_state, which returns early for a
                # device that is not in the cache -- the witness still counts.
                self.witness_device(subdata["target"])
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
        if is_new:
            for listener in list(self.device_added_listeners):
                try:
                    listener(uuid)
                except Exception as exc:  # pylint: disable=broad-except
                    _LOGGER.error("Device added listener failed: %s", exc)

    def begin_sweep(self, expected: int) -> None:
        """Open a new enumeration sweep (DEVIATION, wayfinder #23).

        Every DEVICE_LIST response opens one -- at setup, and again on every
        reconnect resync. The previous sweep's numbers stay readable until this
        one concludes, so nothing ever reports a half-filled count as a result.
        """
        self.cancel_sweep_timer()
        self.sweep_observed = set()
        self.sweep_expected = expected
        # The sweep concludes when the promised devices have all arrived, or
        # when the enumeration window runs out -- whichever happens first. The
        # window is the same one find_devices() waits out, because a device
        # that has not reported by then is exactly what a shortfall is.
        self.sweep_timer = asyncio.create_task(self.sweep_window())

    def observe_in_sweep(self, uuid: str) -> None:
        """Record that this uuid reported in the sweep now open."""
        if self.sweep_timer is None:
            # A DEVICE_FOUND with no sweep open: a late arrival announcing
            # itself after the window closed, or the hub volunteering one.
            # It is a real report, but it is not part of a sweep's arithmetic.
            return
        self.sweep_observed.add(uuid)
        if len(self.sweep_observed) >= self.sweep_expected:
            self.finish_sweep()

    async def sweep_window(self) -> None:
        """Conclude the open sweep once the enumeration window elapses."""
        await asyncio.sleep(DEVICE_FOUND_WINDOW_S)
        self.finish_sweep()

    def finish_sweep(self) -> None:
        """Publish the concluded sweep's numbers (DEVIATION, wayfinder #23).

        `missing` is every uuid we have ever been told about that did not
        report this time. It reads against the device cache deliberately: that
        cache is never cleared, so it is the only record of a device the hub
        has stopped mentioning.

        Ten hardware sweeps across two days never once fell short, so this is a
        tripwire for something never yet seen rather than a live signal -- but
        it is nearly free, and it is the only thing that would catch the sweep
        changing behaviour.
        """
        self.cancel_sweep_timer()
        self.last_sweep_reporting = len(self.sweep_observed)
        self.last_sweep_expected = self.sweep_expected
        self.last_sweep_missing = sorted(
            set(self.devices) - self.sweep_observed
        )
        if self.last_sweep_missing:
            _LOGGER.warning(
                "Sweep reported %i of %i devices; %i known device(s) did not "
                "report: %s",
                self.last_sweep_reporting,
                self.last_sweep_expected,
                len(self.last_sweep_missing),
                ", ".join(self.last_sweep_missing),
            )
        for listener in list(self.sweep_listeners):
            try:
                listener()
            except Exception as exc:  # pylint: disable=broad-exception-caught
                _LOGGER.error("Sweep listener failed: %s", exc)

    def cancel_sweep_timer(self) -> None:
        """Stop the open sweep's window, if one is running."""
        if self.sweep_timer is not None:
            self.sweep_timer.cancel()
            self.sweep_timer = None

    def watch_for_witness(
        self, uuid: str, power: bool | None = None, dim: int | None = None,
        is_retry: bool = False,
    ) -> None:
        """Start the window in which a command has to be witnessed.

        DEVIATION (wayfinder #23). A second command to the same device
        restarts the window rather than opening a second one: the question is
        always "was the most recent thing we asked for carried out", and the
        acknowledgement cannot answer it -- the hub answers `status: "ok"` in
        ~110ms for a device that has been out of the wall for months.

        The command itself is carried into the window (wayfinder #26) so a
        first miss can be retried with the thing that was actually asked for.
        A superseding command cancels any retry the previous one had pending:
        that retry exists to confirm a miss, and a newer command asks the
        question again more directly.
        """
        existing = self.pending_witness.pop(uuid, None)
        if existing is not None:
            existing.cancel()
        self.cancel_retry(uuid)
        self.pending_witness[uuid] = asyncio.create_task(
            self.witness_window(uuid, power, dim, is_retry)
        )

    async def witness_window(
        self, uuid: str, power: bool | None = None, dim: int | None = None,
        is_retry: bool = False,
    ) -> None:
        """Count a miss if the commanded change is never witnessed."""
        await asyncio.sleep(WITNESS_WINDOW_S)
        self.pending_witness.pop(uuid, None)
        misses = self.consecutive_misses.get(uuid, 0) + 1
        self.consecutive_misses[uuid] = misses
        _LOGGER.warning(
            "Commanded %s and saw no state change within %is (miss %i of %i)",
            uuid,
            WITNESS_WINDOW_S,
            misses,
            MISSES_TO_UNREACHABLE,
        )
        if misses >= MISSES_TO_UNREACHABLE:
            if uuid in self.devices and uuid not in self.unreachable:
                self.unreachable.add(uuid)
                _LOGGER.warning(
                    "%s is unreachable: %i commanded changes in a row were "
                    "never witnessed",
                    uuid,
                    misses,
                )
                self.notify_reachability_listeners(uuid, False)
            return

        # DEVIATION (wayfinder #26): a first miss on a device nothing has
        # condemned yet gets its second miss asked for now rather than whenever
        # somebody next reaches for that light. Never after a retry's own miss:
        # that one either marks the device above or leaves the count where a
        # third command would be a third question, not a confirmation.
        if not is_retry and power is not None and uuid not in self.unreachable:
            self.schedule_retry(uuid, power, dim)

    def schedule_retry(
        self, uuid: str, power: bool, dim: int | None,
    ) -> None:
        """Re-ask, once, in RETRY_DELAY_S (DEVIATION, wayfinder #26)."""
        self.cancel_retry(uuid)
        self.pending_retry[uuid] = asyncio.create_task(
            self.retry_command(uuid, power, dim)
        )

    async def retry_command(
        self, uuid: str, power: bool, dim: int | None,
    ) -> None:
        """Send the missed command again, so the second miss lands now.

        DEVIATION (wayfinder #26). Three things can make this pointless
        between being scheduled and firing, and all three are checked rather
        than assumed: the device answered (the mark is gone and so is this
        task, cancelled by witness_device), the device was condemned by some
        other route, or the hub went away -- in which case a send would fail
        and, worse, a failed send is not evidence about the device.
        """
        await asyncio.sleep(RETRY_DELAY_S)
        self.pending_retry.pop(uuid, None)
        if uuid in self.unreachable:
            return
        if not self.is_connected():
            _LOGGER.debug(
                "Not retrying %s: there is no connection to the hub", uuid,
            )
            return
        _LOGGER.info(
            "Re-sending the unwitnessed command to %s to confirm the miss",
            uuid,
        )
        sent = await self.connection_manager.send_state_change(uuid, power, dim)
        if not sent:
            _LOGGER.warning("Could not re-send the command to %s", uuid)
            return
        self.watch_for_witness(uuid, power, dim, is_retry=True)

    def cancel_retry(self, uuid: str) -> None:
        """Drop a pending retry for this device (wayfinder #26)."""
        pending = self.pending_retry.pop(uuid, None)
        if pending is not None:
            pending.cancel()

    def get_last_witness(self, uuid: str) -> float | None:
        """Return when the mesh last spoke for this device, or None.

        DEVIATION (wayfinder #26). On the monotonic clock, so it is only ever
        read as a difference and survives an NTP correction. None means nothing
        has ever witnessed this device in this process -- which is the normal
        state of a quiet house, not a fault.
        """
        return self.last_witness.get(uuid)

    def witness_device(self, uuid: str) -> None:
        """Record that the mesh has spoken for this device (wayfinder #23).

        Any EVENT counts, from any source -- our own command, another hub, or
        somebody pressing the switch on the wall. All three prove the same
        thing: something reached this device and it answered for itself.
        """
        self.last_witness[uuid] = time.monotonic()
        pending = self.pending_witness.pop(uuid, None)
        if pending is not None:
            pending.cancel()
        # A retry only exists to confirm a miss, and this is the answer it was
        # waiting for (wayfinder #26).
        self.cancel_retry(uuid)
        self.consecutive_misses.pop(uuid, None)
        if uuid in self.unreachable:
            self.unreachable.discard(uuid)
            _LOGGER.info("%s answered again; it is reachable", uuid)
            self.notify_reachability_listeners(uuid, True)

    def void_pending_witnesses(self) -> None:
        """Discard every open witness window (DEVIATION, wayfinder #23).

        The marks already made survive -- they are about the devices, not
        about this socket -- but a window that was still open proves nothing
        now, because we would not have heard the EVENT either way.

        The retries go with them (wayfinder #26): a retry is a command, and a
        command sent into a dead socket is not a question the device ever
        heard. The next connection re-enumerates and the probe's own governor
        decides when to ask again.
        """
        for task in self.pending_witness.values():
            task.cancel()
        self.pending_witness = {}
        for task in self.pending_retry.values():
            task.cancel()
        self.pending_retry = {}

    async def connect(self) -> None:
        """Initiate the connection sequence."""
        await self.connection_manager.init_connection()

    async def disconnect(self) -> None:
        """Close the connection."""
        # DEVIATION (wayfinder #23): the diagnostics' own timers are ours to
        # clean up. Left running they would fire against a torn-down entry.
        self.cancel_sweep_timer()
        self.void_pending_witnesses()
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
        sent = await self.connection_manager.send_state_change(uuid, power, dim)
        if not sent:
            raise DeviceCommandError(
                "no live connection to the hub"
                if not self.is_connected()
                else "the hub did not accept the command"
            )

        # DEVIATION (wayfinder #23): the command that just left is the probe.
        # Started only once the bytes are away, so a send that never happened
        # is not counted against the device. The command travels with the
        # window (wayfinder #26) so a first miss can be re-asked.
        self.watch_for_witness(uuid, power, dim)

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
