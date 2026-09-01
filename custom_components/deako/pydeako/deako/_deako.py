"""Connection over socket."""
import asyncio

import logging
import time
from typing import Any, Callable
from uuid import uuid4

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

# DEVIATION (wayfinder #37/#39): how long a CONTROL has to be acknowledged
# before we call it dropped.
#
# The hub answers a CONTROL in 27.9-86.4ms -- measured against real firmware
# (3.21.9-prod-2025.232) on the spare node while resolving #39, and matching
# the 50-290ms #37 worked from. Two seconds is therefore about seven times the
# worst number anyone has seen.
#
# It has to stay comfortably *under* WITNESS_WINDOW_S, and that ordering is the
# whole point rather than a detail. A command the hub never took must be
# settled as a drop before the witness window would otherwise expire and count
# it against the device, because those are two different faults:
#
#   no ack          -> the *hub* never took the command
#   ack, no EVENT   -> the *switch* did not move (the #23 detector)
#
# Conflating them is what the house does today: a hub-dropped command opens a
# witness window on a command the mesh never saw, and the device wears the
# miss.
ACK_WINDOW_S = 2

# DEVIATION (wayfinder #43/#45): the asymmetry measurement, and nothing else.
#
# #43 left one question that twelve days of history cannot separate. A switch
# marked `unreachable` that then emits an EVENT has two readings that fit every
# measurement taken so far:
#
#   intermittent -- genuinely reachable for a couple of minutes, then gone
#   asymmetric   -- it can report but never obey, so `online` was never true
#
# The median life of a cleared mark is 2.2 minutes, so the hourly probe will
# nearly always miss the window. The only instrument that fits inside it is a
# single CONTROL sent the moment the EVENT lands, and that is all this is.
#
# **It defends against nothing.** Asymmetry has never been observed, and this
# map's rule is that mechanisms are not kept against faults nobody has seen. So
# it does not gate the clear -- the mark clears on the EVENT, as it already did
# -- it counts no misses, it can neither set nor lift a mark, and if the
# measurement comes back empty nothing is built on it.
ASYMMETRY_WINDOW_S = WITNESS_WINDOW_S


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
            # DEVIATION (wayfinder #41): a failed attempt is not a connection
            # change -- down stays down -- so the attempt counters would sit
            # stale on the sensor until something else moved. This is the poke.
            on_connection_attempt=self.notify_attempt_listeners,
        )
        self.devices: dict[str, Any] = {}
        self.expected_devices = 0
        # DEVIATION (O5): listeners for connection up/down.
        self.connection_listeners: list[Callable[[bool], None]] = []
        # DEVIATION (wayfinder #41): listeners for a connection attempt that
        # failed. Separate from the above because a failed attempt changes no
        # state anyone can see -- it only moves a counter.
        self.attempt_listeners: list[Callable[[], None]] = []
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
        # on the monotonic clock. The probe decides whether a device answered
        # by asking whether the mesh spoke for it *after* the write went out,
        # and that is a question about time, so the answer has to be kept
        # rather than inferred from the miss counters -- those are cleared by a
        # witness and so cannot say when it happened.
        self.last_witness: dict[str, float] = {}
        # DEVIATION (wayfinder #26): the retries that bring a second miss
        # forward. See RETRY_DELAY_S.
        self.pending_retry: dict[str, asyncio.Task] = {}
        # DEVIATION (wayfinder #37/#39): the CONTROL acknowledgement, which
        # stock never read at all.
        #
        # `pending_acks` is the correlation table, keyed by the transaction id
        # sent with each command, because the ack carries no target uuid -- an
        # ack that cannot be correlated cannot be attributed to a device. It is
        # also the drop detector: an entry that ages out without an ack is a
        # command the hub never took.
        #
        # `optimistic` is the set of devices currently showing a commanded
        # value rather than a witnessed one. Deliberately *not* in the device
        # cache: the active probe reads get_state() and echoes it back at the
        # mesh hourly, so optimism in the cache would be re-commanded forever,
        # and a wrong optimistic dim would not merely display -- the probe
        # would physically set the light to it.
        self.optimistic_callbacks: dict[str, Callable[[dict | None], None]] = {}
        self.optimistic: set[str] = set()
        self.pending_acks: dict[str, dict] = {}
        self.witness_transaction: dict[str, str] = {}
        self.dropped_commands = 0
        self.drop_listeners: list[Callable[[], None]] = []
        # DEVIATION (wayfinder #43/#45): the asymmetry measurement. See
        # ASYMMETRY_WINDOW_S. Nothing reads these but the sensor that reports
        # them, and nothing branches on them.
        self.pending_asymmetry: dict[str, asyncio.Task] = {}
        self.asymmetry_probes = 0
        self.asymmetry_witnessed = 0
        # DEVIATION (wayfinder #45): the attribution record for the write the
        # measurement sends. Its own, rather than the probe pass's
        # `last_probed` pair: bumping that would point a timestamp at a write
        # that produced no pass outcome, and `last_probe_outcome` is read
        # against it to know which pass a verdict belongs to.
        self.asymmetry_last: dict[str, Any] | None = None
        self.asymmetry_listeners: list[Callable[[], None]] = []

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
            #
            # The outstanding commands go the same way and for the same reason
            # (wayfinder #39): they are discarded, never counted as drops.
            self.void_pending_acks()
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
        """Return how many times the connection has been rebuilt.

        DEVIATION (wayfinder #41): this counts connections the hub has
        *answered on*. Before #41 it counted arrivals at a socket, which is why
        #32's ten reconnects were not ten node failures. The meaning changes at
        that release and recorder history is not comparable across it.
        """
        return self.connection_manager.reconnect_count

    def get_failed_attempt_count(self) -> int:
        """Return how many connection attempts did not produce a connection.

        DEVIATION (wayfinder #41): #32 closed with the loose end that there was
        no instrument that would explain the next burst. This is it, and it is
        the number the reconnect count deliberately no longer contains.
        """
        return self.connection_manager.failed_connection_attempts

    def get_unanswered_attempt_count(self) -> int:
        """Return how many attempts opened a socket the hub never answered on.

        DEVIATION (wayfinder #41): the stuck-slot shape specifically -- TCP up,
        nothing served across it. A subset of the failed attempts, and the one
        worth telling apart, because it is us knocking on a door that has not
        finished closing rather than a node that is away.
        """
        return self.connection_manager.unanswered_connection_attempts

    def add_attempt_listener(self, listener: Callable[[], None]) -> None:
        """Register a listener for a failed connection attempt (#41)."""
        if listener not in self.attempt_listeners:
            self.attempt_listeners.append(listener)

    def remove_attempt_listener(self, listener: Callable[[], None]) -> None:
        """Unregister a failed-attempt listener (wayfinder #41)."""
        if listener in self.attempt_listeners:
            self.attempt_listeners.remove(listener)

    def notify_attempt_listeners(self) -> None:
        """Announce that a connection attempt failed (wayfinder #41)."""
        for listener in list(self.attempt_listeners):
            try:
                listener()
            except Exception as exc:  # pylint: disable=broad-exception-caught
                _LOGGER.error("Connection attempt listener failed: %s", exc)

    def get_dropped_command_count(self) -> int:
        """Return how many commands the hub never acknowledged.

        DEVIATION (wayfinder #39). 0.3.1 held commands 500ms apart through a
        send queue; 0.6.0 deleted the queue and spaces nothing, against a hub
        that silently drops commands arriving under ~100ms apart. Nobody has
        put those two facts together against real traffic, and this is the
        instrument that will: it counts commands sent and never answered.

        It counts the *hub* refusing to take a command, never a switch failing
        to move -- that is the node status sensor's job, and keeping the two
        apart is the point (see ACK_WINDOW_S).
        """
        return self.dropped_commands

    def add_drop_listener(self, listener: Callable[[], None]) -> None:
        """Register a listener for a command the hub never took."""
        if listener not in self.drop_listeners:
            self.drop_listeners.append(listener)

    def remove_drop_listener(self, listener: Callable[[], None]) -> None:
        """Unregister a dropped-command listener (wayfinder #39)."""
        if listener in self.drop_listeners:
            self.drop_listeners.remove(listener)

    def notify_drop_listeners(self) -> None:
        """Announce that the dropped-command count moved (wayfinder #39)."""
        for listener in list(self.drop_listeners):
            try:
                listener()
            except Exception as exc:  # pylint: disable=broad-exception-caught
                _LOGGER.error("Dropped-command listener failed: %s", exc)

    def set_optimistic_callback(
        self, uuid: str, callback: Callable[[dict | None], None],
    ) -> None:
        """Register where a device's optimistic state should be shown.

        DEVIATION (wayfinder #37/#39). Called with the commanded state when the
        hub acknowledges a command, and with None when that optimism has to be
        given up and the entity recomputed from the witnessed cache.

        Separate from set_state_callback() on purpose, and that separation is
        the decision #37 made: truth and display are kept in different places,
        so what we merely asked for can never be mistaken for what the mesh
        reported.
        """
        self.optimistic_callbacks[uuid] = callback

    def apply_optimism(
        self, uuid: str, power: bool, dim: int | None = None,
    ) -> None:
        """Show the commanded state now, before anything has confirmed it.

        DEVIATION (wayfinder #37/#39). The ack is not the switch reporting
        back: #13 proved a switch pulled out of the wall months earlier is
        still acknowledged `status: "ok"`, and only its EVENT never comes. So
        this is optimism, knowingly -- it says the hub took the command, and
        the witness window is what holds it to account.
        """
        callback = self.optimistic_callbacks.get(uuid)
        if callback is None:
            return
        state: dict[str, Any] = {"power": power}
        # An omitted dim is a brightness nobody mentioned -- turn_off sends
        # none -- and must leave whatever is displayed alone, not read as zero.
        if dim is not None:
            state["dim"] = dim
        self.optimistic.add(uuid)
        try:
            callback(state)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            _LOGGER.error("Optimistic callback failed for %s: %s", uuid, exc)

    def clear_optimism(self, uuid: str) -> None:
        """Give up on a commanded value and fall back to what was witnessed.

        DEVIATION (wayfinder #37/#39). The flip back in the UI is the only
        feedback anyone gets that the light did not answer, so it is a feature
        rather than a cosmetic tidy-up.
        """
        if uuid not in self.optimistic:
            return
        self.optimistic.discard(uuid)
        callback = self.optimistic_callbacks.get(uuid)
        if callback is None:
            return
        try:
            callback(None)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            _LOGGER.error("Optimistic callback failed for %s: %s", uuid, exc)

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
                # DEVIATION (wayfinder #43/#45): read before witness_device()
                # clears it, because the whole question is about switches that
                # were marked at the moment they spoke.
                was_marked = subdata["target"] in self.unreachable
                # DEVIATION (wayfinder #23): an EVENT is the only message the
                # mesh sources, so it is the only thing that witnesses a
                # device. Done before update_state, which returns early for a
                # device that is not in the cache -- the witness still counts.
                self.witness_device(subdata["target"])
                self.update_state(
                    subdata["target"], state["power"], state.get("dim"),
                )
                if was_marked:
                    # Ordered *after* update_state deliberately: the echo has
                    # to carry the value this EVENT just brought, not the stale
                    # one it replaced, or the measurement would fight whatever
                    # actually moved the light (wayfinder #44).
                    self.probe_asymmetry(subdata["target"])
            elif in_data["type"] == ResponseType.CONTROL:
                # DEVIATION (wayfinder #37/#39): the acknowledgement, which
                # stock discarded because ResponseType had no member for it.
                self.acknowledge_command(
                    in_data.get("transactionId"), in_data.get("status"),
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

    def register_ack(
        self, transaction_id: str, uuid: str, power: bool, dim: int | None,
    ) -> None:
        """Remember a command so its acknowledgement can be matched to it.

        DEVIATION (wayfinder #37/#39). Registered *before* the bytes go out,
        deliberately: the hub answers in tens of milliseconds and there must be
        no window, however small, in which its ack could arrive against an
        empty table and be discarded as uncorrelatable.

        The timeout is armed separately, once the write has actually returned
        (see arm_ack_window) -- a write that blocks is not a hub that ignored
        us, and counting it as one would put a fault of ours into the number
        the pacing question is waiting on.

        Each command gets its own entry rather than one per device. Two
        commands to the same light are two questions, and if the hub takes one
        and drops the other, that is one drop -- collapsing them by uuid would
        lose it.
        """
        self.pending_acks[transaction_id] = {
            "uuid": uuid,
            "power": power,
            "dim": dim,
            "task": None,
        }

    def arm_ack_window(self, transaction_id: str) -> None:
        """Start the clock on a command that has actually left (#39).

        Nothing to arm if the hub answered while the write was still in hand,
        or if the command was discarded meanwhile.
        """
        entry = self.pending_acks.get(transaction_id)
        if entry is None or entry["task"] is not None:
            return
        entry["task"] = asyncio.create_task(self.ack_window(transaction_id))

    def discard_pending_ack(self, transaction_id: str) -> None:
        """Drop a correlation entry without counting it (wayfinder #39)."""
        entry = self.pending_acks.pop(transaction_id, None)
        if entry is not None and entry["task"] is not None:
            entry["task"].cancel()

    def acknowledge_command(
        self, transaction_id: str | None, status: str | None,
    ) -> None:
        """Handle the hub taking a command (DEVIATION, wayfinder #37/#39).

        Correlation is strict, following the precedent #22 set for pongs: an
        ack we cannot match answers nothing, and treating it as an answer to
        whatever happens to be outstanding is the four-year-old bug found in
        the Lua driver, where `reply.transactionId == reply.transactionId`
        compared a value to itself. The echo is not assumed -- it was measured
        on real firmware while resolving #39, 3/3 with no target uuid in the
        reply.
        """
        entry = (
            self.pending_acks.pop(transaction_id, None)
            if transaction_id is not None
            else None
        )
        if entry is None:
            _LOGGER.debug(
                "Ignoring an acknowledgement for %s; no command is waiting on "
                "it", transaction_id,
            )
            return
        if entry["task"] is not None:
            entry["task"].cancel()

        if status != "ok":
            # Never observed. The hub answering something other than "ok" is
            # not the same fault as it saying nothing, so it is not counted as
            # a drop -- but it is not evidence about the switch either, so the
            # witness window this command opened goes with it.
            _LOGGER.warning(
                "The hub refused the command to %s: status=%s",
                entry["uuid"], status,
            )
            self.cancel_witness_for(transaction_id, entry["uuid"])
            return

        # Only ever shown while a witness window is open to take it back
        # again. With no window nothing would ever revert it, and the entity
        # would sit on a value nothing confirmed -- which is worse than the
        # slow update this replaces. That happens when the switch's own EVENT
        # beat the ack, in which case the truth is already on display and a
        # guess must not be written over it.
        if entry["uuid"] not in self.pending_witness:
            _LOGGER.debug(
                "Not showing the commanded state for %s: nothing is left "
                "waiting to confirm or revert it", entry["uuid"],
            )
            return

        self.apply_optimism(entry["uuid"], entry["power"], entry["dim"])

    async def ack_window(self, transaction_id: str) -> None:
        """Count a drop if the hub never answers (wayfinder #39).

        The ack, and only the ack, decides this. An EVENT arriving in the
        meantime is deliberately *not* accepted as evidence that the hub took
        this particular command, and that is not an oversight -- it was
        measured. Six commands fired at one device in a burst produce one ack
        and five drops, but a single EVENT for that device; excusing a drop on
        a witness would have written five of them off as one. The EVENT is
        about the device, the ack is about the command, and only one of them
        can answer the question this counter asks. (A wall switch somebody
        happened to press would excuse a real drop the same way.)

        The cost of that strictness is an ack arriving after the window --
        possible in principle, never seen: the hub answers in 27.9-86.4ms
        against a 2s window. If it ever starts happening, this number climbing
        is itself worth knowing.
        """
        await asyncio.sleep(ACK_WINDOW_S)
        entry = self.pending_acks.pop(transaction_id, None)
        if entry is None:
            return
        uuid = entry["uuid"]

        self.dropped_commands += 1
        _LOGGER.warning(
            "The hub did not acknowledge the command to %s within %ss; "
            "treating it as dropped (%i so far)",
            uuid, ACK_WINDOW_S, self.dropped_commands,
        )
        # This command never reached the mesh, so it says nothing about the
        # device -- the same reasoning as void_pending_witnesses(). Without
        # this the device would wear a miss for the hub's failure, and #26's
        # retry would spend a real physical command confirming it.
        self.cancel_witness_for(transaction_id, uuid)
        self.notify_drop_listeners()

    def void_pending_acks(self) -> None:
        """Forget every outstanding command (DEVIATION, wayfinder #39).

        Called when the connection goes away. A command in flight when the
        socket died is not evidence about anything -- the ack could not have
        reached us whether or not the hub sent one -- so these are discarded
        rather than counted, exactly as void_pending_witnesses() discards the
        windows it cannot answer.
        """
        for entry in self.pending_acks.values():
            if entry["task"] is not None:
                entry["task"].cancel()
        self.pending_acks = {}

    def cancel_witness_for(self, transaction_id: str | None, uuid: str) -> None:
        """Close the witness window this command opened, if it still owns it.

        DEVIATION (wayfinder #39). A newer command may have taken the window
        over since, and that newer question is still live -- so the transaction
        id is checked rather than the uuid alone.

        The optimism goes with the window. It is the window that would have
        taken it back, so leaving one without the other would strand a
        commanded value on the entity with nothing left to revert it -- which
        is exactly what happens when a light is commanded twice in quick
        succession and the hub drops the second one.
        """
        if self.witness_transaction.get(uuid) != transaction_id:
            return
        self.witness_transaction.pop(uuid, None)
        pending = self.pending_witness.pop(uuid, None)
        if pending is not None:
            pending.cancel()
        self.clear_optimism(uuid)
        self.cancel_retry(uuid)

    def watch_for_witness(
        self, uuid: str, power: bool | None = None, dim: int | None = None,
        is_retry: bool = False, transaction_id: str | None = None,
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

        The transaction id rides along too (wayfinder #39), so that a command
        the hub turns out never to have taken can withdraw its own window
        without disturbing a newer one.
        """
        existing = self.pending_witness.pop(uuid, None)
        if existing is not None:
            existing.cancel()
        self.cancel_retry(uuid)
        if transaction_id is not None:
            self.witness_transaction[uuid] = transaction_id
        else:
            self.witness_transaction.pop(uuid, None)
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
        self.witness_transaction.pop(uuid, None)
        # DEVIATION (wayfinder #37/#39): the same expiry that counts a miss
        # gives up the optimistic value. Nothing new is scheduled for it: a
        # healthy light confirms at 2.4s worst case, so this only fires when
        # the command genuinely was not carried out.
        self.clear_optimism(uuid)
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
        if not await self.send_command(uuid, power, dim, is_retry=True):
            _LOGGER.warning("Could not re-send the command to %s", uuid)

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
        self.witness_transaction.pop(uuid, None)
        # The truth has arrived and update_state() is about to write it, so
        # there is no longer anything optimistic on display (wayfinder #39).
        self.optimistic.discard(uuid)
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
        self.witness_transaction = {}
        # Nothing is left to revert these, so they are given up now rather
        # than left showing a commanded value forever (wayfinder #39).
        for uuid in list(self.optimistic):
            self.clear_optimism(uuid)
        for task in self.pending_retry.values():
            task.cancel()
        self.pending_retry = {}
        # The asymmetry measurement goes too (wayfinder #45): its command was
        # in flight on a socket that died, so it is not evidence either way.
        for task in self.pending_asymmetry.values():
            task.cancel()
        self.pending_asymmetry = {}

    # -- the asymmetry measurement (DEVIATION, wayfinder #43/#45) -----------

    def add_asymmetry_listener(self, listener: Callable[[], None]) -> None:
        """Register a listener for the asymmetry counts moving."""
        if listener not in self.asymmetry_listeners:
            self.asymmetry_listeners.append(listener)

    def remove_asymmetry_listener(self, listener: Callable[[], None]) -> None:
        """Unregister an asymmetry listener."""
        if listener in self.asymmetry_listeners:
            self.asymmetry_listeners.remove(listener)

    def notify_asymmetry_listeners(self) -> None:
        """Tell whoever reports the measurement that it moved."""
        for listener in list(self.asymmetry_listeners):
            try:
                listener()
            except Exception as exc:  # pylint: disable=broad-exception-caught
                _LOGGER.error("Asymmetry listener failed: %s", exc)

    def get_asymmetry_counts(self) -> tuple[int, int]:
        """Return (probes sent, probes witnessed) for the measurement."""
        return self.asymmetry_probes, self.asymmetry_witnessed

    def get_asymmetry_last(self) -> dict[str, Any] | None:
        """Return the attribution record for the most recent measurement.

        DEVIATION (wayfinder #45). `witnessed` is None while the window is
        still open, which is a different fact from a measurement that came back
        unwitnessed -- and the running counts, not this, are the tally.
        """
        return self.asymmetry_last

    def probe_asymmetry(self, uuid: str) -> None:
        """Ask a just-spoken marked switch whether it can also obey.

        DEVIATION (wayfinder #43/#45). See ASYMMETRY_WINDOW_S for why this
        exists and what it is forbidden from doing.

        One command per clear, on marked devices only -- so roughly one extra
        write an hour in this house, against the 37 the hourly pass already
        sends. A second EVENT arriving while one is still in flight is not a
        second question, so it is ignored rather than stacked.
        """
        if uuid in self.pending_asymmetry:
            return
        if not self.is_connected():
            return
        self.pending_asymmetry[uuid] = asyncio.create_task(
            self.asymmetry_probe(uuid)
        )

    async def asymmetry_probe(self, uuid: str) -> None:
        """Send one CONTROL and record only whether it was witnessed.

        DEVIATION (wayfinder #43/#45).

        The echo is the device's own cache, refreshed by the EVENT that
        triggered this a moment ago, so this cannot drive a light anywhere it
        did not just report being. That ordering is the whole safety argument
        and it is asserted by where probe_asymmetry() is called from.

        Sent with `observe_only`, which is what keeps this a measurement: no
        witness window opens, so no miss is counted, no retry is scheduled, and
        nothing here can set or lift a mark. The verdict is read from
        `last_witness` afterwards instead -- the same evidence the probe's own
        pass uses, read without arming the machinery that acts on it.

        **It is a write, so it is attributable** (wayfinder #45). This is a
        second writer to the mesh, and #25's rule is that a probe write leaves
        a record, because such a write is invisible in the recorder -- it
        drives the light to the value Home Assistant already believes. The
        record is its own rather than the pass's `last_probed` pair, which
        would otherwise point at a write that produced no pass outcome, and is
        written at the send rather than on completion, so a restart inside the
        window cannot take the evidence of the write with it.
        """
        try:
            state = self.get_state(uuid) or {}
            power = bool(state.get("power", False))
            # Same rule as the pass: a dim only ever travels with `on`.
            dim = state.get("dim") if power else None

            sent_at = time.monotonic()
            if not await self.send_command(
                uuid, power, dim, observe_only=True,
            ):
                _LOGGER.debug(
                    "Could not measure asymmetry on %s: the command did not "
                    "leave", uuid,
                )
                return

            self.asymmetry_probes += 1
            # Written and published *here*, the moment the bytes are away,
            # rather than reconstructed when the window closes (wayfinder #45,
            # following #25's rule for the probe pass's own record). This is a
            # command that can physically move a light, and it is invisible in
            # the recorder for the same reason the pass's writes are -- it
            # drives the light to the value Home Assistant already believes. A
            # record written only on completion would be lost by a restart
            # inside the window, which is exactly when somebody would later ask
            # what moved a light.
            record: dict[str, Any] = {
                "uuid": uuid,
                "name": self.get_name(uuid),
                "power": power,
                "dim": dim,
                "witnessed": None,
            }
            self.asymmetry_last = record
            self.notify_asymmetry_listeners()

            await asyncio.sleep(ASYMMETRY_WINDOW_S)

            seen = self.last_witness.get(uuid)
            witnessed = seen is not None and seen >= sent_at
            if witnessed:
                self.asymmetry_witnessed += 1
            record["witnessed"] = witnessed
            _LOGGER.warning(
                "Asymmetry measurement on %s: it reported, and the CONTROL "
                "sent straight back at it was %s (%i of %i witnessed so far)",
                uuid,
                "witnessed" if witnessed else "NOT witnessed",
                self.asymmetry_witnessed,
                self.asymmetry_probes,
            )
            # A measurement on another device may have started meanwhile and
            # taken the slot, in which case the newer write is the one worth
            # showing. The verdict is not lost -- it is in the counts and in
            # the line above.
            if self.asymmetry_last is record:
                self.notify_asymmetry_listeners()
        finally:
            self.pending_asymmetry.pop(uuid, None)

    async def connect(self) -> None:
        """Initiate the connection sequence."""
        await self.connection_manager.init_connection()

    async def disconnect(self) -> None:
        """Close the connection."""
        # DEVIATION (wayfinder #23): the diagnostics' own timers are ours to
        # clean up. Left running they would fire against a torn-down entry.
        self.cancel_sweep_timer()
        self.void_pending_acks()
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
        if not await self.send_command(uuid, power, dim):
            raise DeviceCommandError(
                "no live connection to the hub"
                if not self.is_connected()
                else "the hub did not accept the command"
            )

    async def send_command(
        self, uuid: str, power: bool, dim: int | None = None,
        is_retry: bool = False, observe_only: bool = False,
    ) -> bool:
        """Put one CONTROL on the wire and start watching for its answers.

        DEVIATION (wayfinder #39). Two answers are now expected, and they are
        different questions: the hub's acknowledgement, which says the command
        was taken and drives the optimistic UI update, and the switch's EVENT,
        which says the light actually moved (wayfinder #23).

        `observe_only` (wayfinder #45) opens neither. The ack is still
        correlated -- whether the *hub* took a command is a fact about the hub,
        and the drop counter should not develop a blind spot -- but no witness
        window opens, so the command counts no miss against the device, starts
        no retry, and cannot set or lift a mark. It also shows nothing
        optimistically, because acknowledge_command() only does that while a
        witness window is open to take it back again. Used by the asymmetry
        measurement, which must observe the detector without feeding it.
        """
        transaction_id = str(uuid4())
        # Registered before the send, armed after it: see register_ack.
        self.register_ack(transaction_id, uuid, power, dim)
        sent = await self.connection_manager.send_state_change(
            uuid, power, dim, transaction_id=transaction_id,
        )
        if not sent:
            # A command that never left the machine is not a dropped command,
            # and it is not evidence about the device either.
            self.discard_pending_ack(transaction_id)
            return False

        if not self.is_connected():
            # The socket died while this was going out. Whether the bytes
            # landed is unknowable, so nothing is counted and nothing is
            # watched -- the same reasoning void_pending_witnesses() runs on,
            # applied to the one command that was mid-flight when it ran.
            self.discard_pending_ack(transaction_id)
            return False

        self.arm_ack_window(transaction_id)
        if not observe_only:
            # DEVIATION (wayfinder #23): the command that just left is the
            # probe. Started only once the bytes are away, so a send that never
            # happened is not counted against the device. The command travels
            # with the window (wayfinder #26) so a first miss can be re-asked.
            self.watch_for_witness(uuid, power, dim, is_retry, transaction_id)
        return True

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
