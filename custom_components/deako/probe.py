"""The active reachability probe (wayfinder #25, built in #26).

#23 shipped a detector that can only confirm an unreachable switch the moment
somebody reaches for it. That leaves the per-node status sensor reading
`online` essentially always, because in a quiet house nothing reaches for
anything -- ten hardware runs with no manipulation produced zero `EVENT`s. The
diagnostic was therefore largely decorative, and #10's stated first job for
these diagnostics is measurement.

This is the missing half: something that reaches for every light on its own.

**It is not a new detection mechanism.** `control_device()` already opens a
witness window, so the probe is a caller loop -- an idempotent `CONTROL`
echoing each device's own cached state back at it, which asks the mesh the only
question this protocol can answer. A device that answers emits an `EVENT` and
is witnessed; one that has left the mesh is acknowledged `status: "ok"` in
about 110ms and says nothing, exactly as the switch pulled out of the wall did
in #13.

**The risk was accepted deliberately, not overlooked.** A device that drifted
out of sync while off the mesh and has since come back carries a hub cache that
is wrong, and this loop would drive it to that wrong value -- a light moving in
the night with nobody asking. #25 weighed it and shipped anyway: the flip has
never been observed, the map's own rule is that mechanisms are not kept against
faults nobody has seen, and the containment rules on offer aimed the write at
*more* dangerous populations rather than fewer.

What the ruling requires instead is that if it ever does fire, it is
attributable. It would otherwise be invisible: the probe drives the light *to*
the value Home Assistant already believes, so `light.X` reads the same before
and after and the recorder shows nothing at all. The per-switch
`last_probed` / `last_probe_value` pair is the only possible witness, which is
why they are written here at the moment the bytes leave, rather than
reconstructed afterwards from a pass summary.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from datetime import datetime

from homeassistant.util import dt as dt_util

from .pydeako.deako import Deako, DeviceCommandError
from .pydeako.deako._deako import DEVICE_FOUND_WINDOW_S, WITNESS_WINDOW_S

_LOGGER: logging.Logger = logging.getLogger(__package__)

# Hourly, and the cadence is not a config option: #25 struck the dial, because
# every option is permanent surface and one nobody turns twice is not worth it.
PROBE_INTERVAL_S = 3600

# Above the hub's silent-drop threshold, which is the one number in the vendor
# documentation #13 found to be true: commands closer together than 800ms are
# dropped with no reply at all, so a client that trusts acknowledgements and
# does not pace itself loses them invisibly. #13's own whole-house scans ran at
# 900ms and 2500ms and flagged an identical six both times, so this sits above
# the proven-good spacing as well as the documented one.
#
# 37 devices at this spacing is a ~41s pass.
PROBE_SPACING_S = 1.1

# The pass concludes one witness window after the last command, so the device
# commanded last gets the same 5s to answer as the one commanded first.
PASS_SETTLE_S = WITNESS_WINDOW_S + 2

# Startup waits out the enumeration window before the first pass. A straggler
# that reports late still gets an entity (O10) and would otherwise miss the
# first census entirely -- and probing a device the hub has not finished
# announcing is asking a question about our own timing, not about the mesh.
FIRST_PASS_DELAY_S = DEVICE_FOUND_WINDOW_S

TRIGGER_SCHEDULED = "scheduled"
TRIGGER_MANUAL = "manual"


class DeakoProber:
    """Runs probe passes, and governs how often they are allowed to happen.

    **One governor, three triggers.** Hourly, on startup once enumeration has
    settled, and on reconnect -- and no *automatic* pass may run within an hour
    of the last attempt, whichever trigger asked. That single rule is what
    makes startup and reconnect bring the next pass forward rather than being
    separate cases with separate hazards.

    It is load-bearing rather than tidy. 0.6.0 has no reconnect backoff: #19
    measured a dead node being retried about six times a minute against real
    firmware, and this house has a node that flaps every 6-12 minutes. An
    ungoverned probe-on-reconnect would therefore be a 37-device write storm
    every few minutes, aimed by definition at a mesh that is already unwell.

    The manual census is exempt, because a human asking is the consent model
    this whole design rests on.
    """

    def __init__(self, client: Deako) -> None:
        """Bind to the connection whose devices this probes."""
        self._client = client
        self._enabled = True
        self._wake = asyncio.Event()
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None
        self._census_task: asyncio.Task | None = None

        # Governor state, on the monotonic clock: it is only ever read as a
        # difference, and must not move when the wall clock is corrected.
        self._next_due = time.monotonic() + FIRST_PASS_DELAY_S
        # When the previous pass finished. A device the passive detector
        # witnessed *since* then needs no write from us: its cache is
        # device-fresh and probing it could only tell us what we know.
        #
        # The end of the previous pass, emphatically not its start. A pass
        # witnesses nearly every device it touches -- that is what a successful
        # probe is -- so measuring from the start would let each pass's own
        # answers excuse the next one, and the probe would write once and then
        # skip the house forever while reporting a full census. Observed doing
        # exactly that before this line said "end".
        self._cycle_end = time.monotonic()

        # What the entities read. `last_pass_at` deliberately advances only on
        # a pass that *completed*: its job is to show the probe stopping, so a
        # pass abandoned halfway must not leave it looking like a census
        # happened.
        self._last_pass_at: datetime | None = None
        self._witnessed: int | None = None
        self._unwitnessed: int | None = None
        self._probed_at: dict[str, datetime] = {}
        self._probe_value: dict[str, tuple[bool, int | None]] = {}

        self._pass_listeners: list[Callable[[], None]] = []
        self._device_listeners: list[Callable[[str], None]] = []

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        """Begin governing. Nothing is sent until the first pass falls due."""
        if self._task is not None:
            return
        self._client.add_connection_listener(self._on_connection_change)
        self._task = asyncio.create_task(self._governor())

    async def stop(self) -> None:
        """Stop governing and abandon any pass in flight.

        A pass abandoned here has already written its per-switch attribution
        records for the commands it sent, which is the point: those record what
        left the building, and unloading the entry does not un-send them.
        """
        self._client.remove_connection_listener(self._on_connection_change)
        for task in (self._task, self._census_task):
            if task is not None:
                task.cancel()
        self._task = None
        self._census_task = None

    # -- what the entities read -------------------------------------------

    @property
    def enabled(self) -> bool:
        """Whether automatic passes are allowed to run."""
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        """Turn automatic passes on or off.

        Turning it back on wakes the governor, so a house that has been
        unprobed for longer than the interval gets its census immediately
        rather than at the top of some hour it cannot see.
        """
        if enabled == self._enabled:
            return
        self._enabled = enabled
        _LOGGER.info(
            "The reachability probe is now %s",
            "enabled" if enabled else "disabled",
        )
        self._wake.set()

    @property
    def last_pass_at(self) -> datetime | None:
        """When the last *completed* pass finished, or None if none has."""
        return self._last_pass_at

    @property
    def witnessed(self) -> int | None:
        """How many devices answered for themselves in the last pass."""
        return self._witnessed

    @property
    def unwitnessed(self) -> int | None:
        """How many devices did not answer in the last pass."""
        return self._unwitnessed

    def get_probed_at(self, uuid: str) -> datetime | None:
        """When this device was last written to by the probe."""
        return self._probed_at.get(uuid)

    def get_probe_value(self, uuid: str) -> tuple[bool, int | None] | None:
        """The (power, dim) the probe last sent to this device."""
        return self._probe_value.get(uuid)

    def add_pass_listener(self, listener: Callable[[], None]) -> None:
        """Register a listener for a pass concluding."""
        if listener not in self._pass_listeners:
            self._pass_listeners.append(listener)

    def remove_pass_listener(self, listener: Callable[[], None]) -> None:
        """Unregister a pass listener."""
        if listener in self._pass_listeners:
            self._pass_listeners.remove(listener)

    def add_device_listener(self, listener: Callable[[str], None]) -> None:
        """Register a listener for one device being probed."""
        if listener not in self._device_listeners:
            self._device_listeners.append(listener)

    def remove_device_listener(self, listener: Callable[[str], None]) -> None:
        """Unregister a per-device listener."""
        if listener in self._device_listeners:
            self._device_listeners.remove(listener)

    # -- triggers ----------------------------------------------------------

    def request_census(self) -> None:
        """Run a pass now, governor and on/off switch both bypassed.

        Scheduled rather than awaited so the button press returns immediately:
        a pass takes the better part of a minute, and a service call that
        blocks for that long looks like a hang.
        """
        if self._census_task is not None and not self._census_task.done():
            _LOGGER.info("A census is already running; ignoring the request")
            return
        self._census_task = asyncio.create_task(self._run_census())

    async def _run_census(self) -> None:
        """Body of the manual census."""
        if self._lock.locked():
            _LOGGER.info(
                "A probe pass is already in flight; the census it would have "
                "run is that one"
            )
            return
        await self._attempt_pass(TRIGGER_MANUAL)

    def _on_connection_change(self, connected: bool) -> None:
        """Bring the next pass forward when the hub comes back.

        Only ever a nudge: the governor decides whether anything happens, which
        is what stops the flapping node from turning a reconnect into a write
        storm.
        """
        if connected:
            self._wake.set()

    # -- the governor ------------------------------------------------------

    async def _governor(self) -> None:
        """Wait for a pass to fall due, then run one if it is allowed."""
        while True:
            self._wake.clear()
            remaining = self._next_due - time.monotonic()
            if remaining > 0:
                try:
                    await asyncio.wait_for(self._wake.wait(), remaining)
                except (TimeoutError, asyncio.TimeoutError):
                    pass
                # Whether the wait ended in a nudge or in the clock running
                # out, the decision is made from the state, never from which
                # of the two woke us.
                continue

            if not self._enabled:
                _LOGGER.debug("A pass is due but the probe is turned off")
                await self._wake.wait()
                continue

            if not self._client.is_connected():
                # Not deferred by the governor, because nothing was sent: the
                # pass stays due, and the reconnect that fixes this is exactly
                # what wakes us to run it.
                _LOGGER.info(
                    "A probe pass is due but there is no connection to the "
                    "hub; waiting for one"
                )
                await self._wake.wait()
                continue

            await self._attempt_pass(TRIGGER_SCHEDULED)

    async def _attempt_pass(self, trigger: str) -> None:
        """Run one pass, and hold the hourly budget against it either way.

        The budget is spent on the *attempt*, not on the success. A pass that
        the hub abandoned halfway still wrote to the mesh, and the flapping
        node is the case that decides this: charging only successes would let a
        node that drops the connection mid-pass earn a fresh 37-device attempt
        every time it came back.
        """
        async with self._lock:
            self._next_due = time.monotonic() + PROBE_INTERVAL_S
            cutoff = self._cycle_end

            probed: dict[str, float] = {}
            skipped: list[str] = []
            aborted = False

            try:
                for uuid in list(self._client.get_devices()):
                    if not self._client.is_connected():
                        aborted = True
                        break

                    witness = self._client.get_last_witness(uuid)
                    if witness is not None and witness >= cutoff:
                        # The passive detector already has this one, from a
                        # real actuation rather than from a write of ours.
                        skipped.append(uuid)
                        continue

                    if not await self._probe_device(uuid):
                        aborted = True
                        break
                    probed[uuid] = time.monotonic()
                    await asyncio.sleep(PROBE_SPACING_S)

                if aborted:
                    _LOGGER.warning(
                        "The %s probe pass was abandoned after %i of %i "
                        "devices: the connection to the hub went away",
                        trigger,
                        len(probed) + len(skipped),
                        len(self._client.get_devices()),
                    )
                    return

                await asyncio.sleep(PASS_SETTLE_S)
                self._conclude_pass(trigger, probed, skipped)
            finally:
                # Closed here rather than at the top, so this pass's own
                # answers cannot excuse the next one from asking again.
                self._cycle_end = time.monotonic()

    async def _probe_device(self, uuid: str) -> bool:
        """Echo one device's cached state back to it, and record that we did.

        Returns whether the command was sent. The record is written on the way
        out rather than afterwards, because it is an attribution record for a
        write: what matters is that the bytes left, and a pass that dies before
        it finishes must not take the evidence of its own writes with it.
        """
        state = self._client.get_state(uuid) or {}
        power = bool(state.get("power", False))
        # Only ever alongside `power: true`. Home Assistant's own turn_off
        # sends no dim, and a dim carried on an off command is a brightness
        # somebody did not ask for.
        dim = state.get("dim") if power else None

        try:
            await self._client.control_device(uuid, power, dim)
        except DeviceCommandError as exc:
            _LOGGER.warning("Could not probe %s: %s", uuid, exc.reason)
            return False

        self._probed_at[uuid] = dt_util.utcnow()
        self._probe_value[uuid] = (power, dim)
        _LOGGER.debug(
            "Probed %s by echoing power=%s dim=%s", uuid, power, dim,
        )
        self._notify_device(uuid)
        return True

    def _conclude_pass(
        self, trigger: str, probed: dict[str, float], skipped: list[str],
    ) -> None:
        """Publish what the pass found.

        A device counts as answering if the mesh spoke for it after we wrote to
        it -- and the ones skipped count as answering too, because the passive
        detector heard from them this cycle for real. The pair of numbers is a
        census of the house either way, which is what makes them worth keeping
        forever.
        """
        witnessed = [
            uuid for uuid, sent_at in probed.items()
            if (seen := self._client.get_last_witness(uuid)) is not None
            and seen >= sent_at
        ]

        self._last_pass_at = dt_util.utcnow()
        self._witnessed = len(skipped) + len(witnessed)
        self._unwitnessed = len(probed) - len(witnessed)

        log = _LOGGER.warning if self._unwitnessed else _LOGGER.info
        log(
            "The %s probe pass finished: %i of %i answered (%i were already "
            "witnessed this cycle and were not written to), %i did not",
            trigger,
            self._witnessed,
            self._witnessed + self._unwitnessed,
            len(skipped),
            self._unwitnessed,
        )
        self._notify_pass()

    # -- listener plumbing -------------------------------------------------

    def _notify_pass(self) -> None:
        """Tell the hub-level entities a pass concluded."""
        for listener in list(self._pass_listeners):
            try:
                listener()
            except Exception as exc:  # pylint: disable=broad-exception-caught
                _LOGGER.error("Probe pass listener failed: %s", exc)

    def _notify_device(self, uuid: str) -> None:
        """Tell one device's entities it was just probed."""
        for listener in list(self._device_listeners):
            try:
                listener(uuid)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                _LOGGER.error("Probe device listener failed: %s", exc)
