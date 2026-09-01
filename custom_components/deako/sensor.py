"""Diagnostic sensors for Deako (wayfinder #23, extended by #26).

Five entity types ship, and they answer different questions:

  * **Node status**, one per switch, on the same device as that switch's light.
    `unavailable` alone is never a diagnosis -- it can mean the integration is
    down, the hub is down, or that one switch is unreachable -- so the cause is
    readable on the node itself, and "since when" comes free from its history.
  * **Reconnects since restart**, **seconds since last hub message** and
    **devices reporting**, on a device standing for the hub.

Wayfinder #26 adds the probe's own record: **last probed** and **last probe
value** per switch, and **last probe pass** plus the two census counts on the
hub. The per-switch pair is an attribution record rather than a diagnostic --
see DeakoLastProbeValue for what it is for and why it cannot be left
approximate, and DeakoRestoredProbeReading for why a restart must not put a
hole in it.

Wayfinder #39 adds **unacknowledged commands** on the hub: commands the hub
never answered at all. It is deliberately a different question from the node
status sensor's -- see DeakoDroppedCommands.

Wayfinder #45 adds a third per-switch record, **last probe outcome**, and three
more hub readings: **switches marked unreachable**, which counts the same set
the per-switch sensors report one at a time, and **asymmetry probes** plus
**asymmetry probes witnessed**, which are a measurement of an open question
rather than a diagnostic. Read DeakoUnreachableDevices on why the marked count
and the probe pair are supposed to differ, DeakoAsymmetryProbes on what is
being measured and what happens if it comes back empty, and
DeakoAsymmetryWitnessed on why the split is two entity states rather than two
attributes.

What the node status sensor honestly cannot say is set out on
DeakoNodeStatus below. Read it before building anything on top of this.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Mapping

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from .binary_sensor import hub_device_info
from .const import (
    DOMAIN,
    MANUFACTURER,
    NODE_STATUS_HUB_DISCONNECTED,
    NODE_STATUS_ONLINE,
    NODE_STATUS_OPTIONS,
    NODE_STATUS_UNREACHABLE,
    PROBE_DATA,
    PROBE_OUTCOME_ANSWERED,
    PROBE_OUTCOME_NO_ANSWER,
    PROBE_OUTCOME_OPTIONS,
    PROBE_VALUE_OFF,
    PROBE_VALUE_ON,
    PROBE_VALUE_OPTIONS,
)
from .probe import DeakoProber
from .pydeako.deako import Deako

_LOGGER: logging.Logger = logging.getLogger(__package__)


async def async_setup_entry(
    hass: HomeAssistant,
    config: ConfigEntry,
    add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Configure the platform."""
    client: Deako = hass.data[DOMAIN][config.entry_id]
    prober: DeakoProber = hass.data[PROBE_DATA][config.entry_id]

    add_entities(
        [
            DeakoHubReconnects(client, config),
            DeakoDroppedCommands(client, config),
            DeakoLastMessageAge(client, config),
            DeakoDevicesReporting(client, config),
            DeakoUnreachableDevices(client, config),
            DeakoAsymmetryProbes(client, config),
            DeakoAsymmetryWitnessed(client, config),
            DeakoLastProbePass(prober, client, config),
            DeakoProbeWitnessed(prober, client, config),
            DeakoProbeUnwitnessed(prober, client, config),
        ]
    )

    added: set[str] = set()

    @callback
    def add_nodes(uuids: list[str]) -> None:
        new = [uuid for uuid in uuids if uuid not in added]
        if not new:
            return
        added.update(new)
        entities: list[SensorEntity] = []
        for uuid in new:
            entities.append(DeakoNodeStatus(client, uuid))
            entities.append(DeakoLastProbed(prober, client, uuid))
            entities.append(DeakoLastProbeValue(prober, client, uuid))
            entities.append(DeakoLastProbeOutcome(prober, client, uuid))
        add_entities(entities)

    @callback
    def device_reported(uuid: str) -> None:
        """Give a device that reported after setup a status sensor too.

        Same straggler path the light platform uses (O10). Both platforms
        listen: the library keeps a list of listeners rather than one slot,
        precisely so neither can take this news away from the other.
        """
        add_nodes([uuid])

    client.add_device_added_listener(device_reported)
    config.async_on_unload(
        lambda: client.remove_device_added_listener(device_reported)
    )

    add_nodes(list(client.get_devices()))


class DeakoNodeStatus(SensorEntity):
    """Why this particular switch is or is not answering.

    Three readings, in the order of how much they explain:

      * `hub_disconnected` -- there is no connection to the hub, so nothing can
        be said about any switch. It dominates, because a disconnected hub
        makes every other reading meaningless.
      * `unreachable` -- this switch was commanded twice running and neither
        change was ever witnessed. See below for what that does and does not
        mean.
      * `online` -- nothing contradicts it.

    **`online` is the absence of evidence, not evidence of health.** There is
    no reachability field anywhere in this protocol: `DEVICE_LIST` counts an
    unreachable switch, `DEVICE_FOUND` streams it every sweep at the usual
    speed, `DEVICE_POLL` answers for it normally, and a `CONTROL` to a switch
    that has been out of the wall for months is still acknowledged
    `status: "ok"` in about 110 ms. Only the confirming `EVENT` tells the
    truth, and it only exists once something has been asked for.

    Until wayfinder #26 that made this sensor blind between actuations: a node
    nobody had touched for a week read `online` because nothing had
    contradicted it. The active probe closes that gap by reaching for every
    switch hourly on nobody's behalf, so a week of silence now means a week of
    passes that were answered. What has not changed is where the evidence comes
    from -- this still reports the absence of contradiction, and the probe's
    job is to make sure a contradiction would have had the chance to arrive.

    The light on this same device deliberately stays available while this
    reads `unreachable`, so the next attempt can still be made -- and that
    attempt is the cheapest thing that can clear the mark.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "node_status"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = NODE_STATUS_OPTIONS
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = False

    def __init__(self, client: Deako, uuid: str) -> None:
        """Bind to one device."""
        self.client = client
        self.uuid = uuid
        self._attr_unique_id = f"{uuid}_node_status"
        # The same device as the light, so "which switch, and why" is one
        # place rather than two.
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, uuid)},
            name=client.get_name(uuid),
            manufacturer=MANUFACTURER,
        )

    @property
    def available(self) -> bool:
        """Always available.

        A diagnosis that disappears when things go wrong is not a diagnosis.
        """
        return True

    @property
    def native_value(self) -> str:
        """Return the most explanatory reading that currently applies."""
        if not self.client.is_connected():
            return NODE_STATUS_HUB_DISCONNECTED
        if not self.client.is_reachable(self.uuid):
            return NODE_STATUS_UNREACHABLE
        return NODE_STATUS_ONLINE

    async def async_added_to_hass(self) -> None:
        """Listen for both things that can move this reading."""
        self.client.add_connection_listener(self.on_connection_change)
        self.client.add_reachability_listener(self.on_reachability_change)

    async def async_will_remove_from_hass(self) -> None:
        """Stop listening."""
        self.client.remove_connection_listener(self.on_connection_change)
        self.client.remove_reachability_listener(self.on_reachability_change)

    @callback
    def on_connection_change(self, connected: bool) -> None:
        """The hub came or went; every node's reading moves with it."""
        self.schedule_update_ha_state()

    @callback
    def on_reachability_change(self, uuid: str, reachable: bool) -> None:
        """One device's reachability moved; ignore the other devices'."""
        if uuid != self.uuid:
            return
        _LOGGER.info(
            "%s is now %s",
            self.entity_id,
            NODE_STATUS_ONLINE if reachable else NODE_STATUS_UNREACHABLE,
        )
        self.schedule_update_ha_state()


class DeakoHubDiagnosticSensor(SensorEntity):
    """Shared wiring for the hub-level diagnostics."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = False

    def __init__(self, client: Deako, entry: ConfigEntry, key: str) -> None:
        """Bind to the connection this entry owns."""
        self.client = client
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = hub_device_info(entry)

    @property
    def available(self) -> bool:
        """Always available; these describe the outage, so they outlive it."""
        return True


class DeakoHubReconnects(DeakoHubDiagnosticSensor):
    """How many times the connection has been rebuilt since startup.

    Read alongside the connectivity sensor, never on its own. This counts
    connections that came *back*, so a single long outage adds one, and what
    this number really measures is how often the hub went away, not how long
    for.

    Wayfinder #41 changed what counts as coming back, and the change is not
    cosmetic: a connection is only counted once the hub has answered a ping on
    it. Before that, a TCP handshake was enough -- and Deako's telnet server is
    exclusive, so a *stuck* slot accepted our socket and served nothing across
    it. #32's ten reconnects therefore were not ten node failures; some of them
    were this integration knocking on a door that had not finished closing and
    logging each knock as an arrival. **Recorder history is not comparable
    across the release that shipped #41.**

    The attempts that do not get there are on the attributes rather than in the
    state, because they answer a different question -- what the reconnect was
    doing -- and #32 closed with no instrument for it at all.
    """

    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, client: Deako, entry: ConfigEntry) -> None:
        """Set up the counter."""
        super().__init__(client, entry, "reconnects")

    @property
    def native_value(self) -> int:
        """Return the count since this entry was set up."""
        return self.client.get_reconnect_count()

    @property
    def extra_state_attributes(self) -> dict[str, int]:
        """Report what the attempts did, not just the ones that arrived.

        Wayfinder #41. `unanswered_attempts` is a subset of `failed_attempts`
        and is the one to read first: it is the stuck exclusive slot -- socket
        open, hub silent -- rather than a node that is simply away.
        """
        return {
            "failed_attempts": self.client.get_failed_attempt_count(),
            "unanswered_attempts": self.client.get_unanswered_attempt_count(),
        }

    async def async_added_to_hass(self) -> None:
        """A reconnect is a connection change, so this is the same signal."""
        self.client.add_connection_listener(self.on_connection_change)
        # A failed attempt changes nothing anyone can see, so it has its own
        # signal or the attributes would only refresh when something else moved.
        self.client.add_attempt_listener(self.on_attempt)

    async def async_will_remove_from_hass(self) -> None:
        """Stop listening."""
        self.client.remove_connection_listener(self.on_connection_change)
        self.client.remove_attempt_listener(self.on_attempt)

    @callback
    def on_connection_change(self, connected: bool) -> None:
        """Write the new count out."""
        self.schedule_update_ha_state()

    @callback
    def on_attempt(self) -> None:
        """Write the new attempt attributes out."""
        self.schedule_update_ha_state()


class DeakoDroppedCommands(DeakoHubDiagnosticSensor):
    """Commands the hub never acknowledged, since startup.

    The instrument for a question this map has deferred rather than answered
    (wayfinder #37/#39). 0.3.1 held commands 500ms apart through a send queue;
    0.6.0 deleted the queue and spaces nothing, against a hub that silently
    drops commands arriving under ~100ms apart. Whether the house is losing
    scene commands right now is unmeasured, and this is what measures it.

    It counts one thing only: a `CONTROL` we sent and the hub never answered.
    A switch that was commanded and did not move is a different fault and is
    reported by its own node status sensor. Conflating them is what the
    integration did before this shipped.

    An entity rather than an attribute, deliberately: the recorder keeps 60
    days here while long-term statistics never purge (#6), and this number has
    to accumulate across a window longer than anyone will sit and watch.
    """

    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, client: Deako, entry: ConfigEntry) -> None:
        """Set up the counter."""
        super().__init__(client, entry, "dropped_commands")

    @property
    def native_value(self) -> int:
        """Return the count since this entry was set up."""
        return self.client.get_dropped_command_count()

    async def async_added_to_hass(self) -> None:
        """Write the count out whenever it moves."""
        self.client.add_drop_listener(self.on_drop)

    async def async_will_remove_from_hass(self) -> None:
        """Stop listening."""
        self.client.remove_drop_listener(self.on_drop)

    @callback
    def on_drop(self) -> None:
        """Publish the new count."""
        self.schedule_update_ha_state()


class DeakoLastMessageAge(DeakoHubDiagnosticSensor):
    """How long since the hub last said anything at all.

    The silent-degradation detector. It is stamped at the library's inbound
    choke point *before* pong filtering, deliberately: the pings are the only
    thing a healthy but idle hub reliably says, and ten hardware runs with no
    manipulation produced zero `EVENT`s. On a healthy connection this therefore
    sits inside one ping window; a value that climbs past it means the hub has
    gone quiet without closing the socket, which is the fault mode the ping
    watchdog takes 19 s to catch.

    This is the one diagnostic that has to be sampled rather than pushed --
    it changes continuously by doing nothing. Home Assistant's own poll
    interval does that, and it reads an in-memory clock: nothing here goes near
    the hub.

    **A healthy connection makes this read a near-constant number, and that is
    aliasing rather than a stuck entity.** Home Assistant samples every 30 s
    and the watchdog pings every 10 s, so every sample lands on the same phase
    of the ping cycle -- an end-to-end run against the simulator read exactly
    3.3 s twice in a row. It is left that way deliberately: a flat baseline
    makes any climb obvious on a graph, and the alternative is inventing a
    cadence to break the harmonic with. What it means is that "the number is
    moving" is never the evidence this entity is working; the evidence is that
    it climbs when the hub goes quiet, which
    ``wsl_validate_diagnostic_entities.sh`` phase 5 makes it do.
    """

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_suggested_display_precision = 0
    _attr_should_poll = True

    def __init__(self, client: Deako, entry: ConfigEntry) -> None:
        """Set up the age reading."""
        super().__init__(client, entry, "last_message_age")

    @property
    def native_value(self) -> float | None:
        """Return the age in seconds, or None if the hub has never spoken.

        None rather than zero: "we have not heard from it yet" is a different
        fact from "we heard from it just now", and recording the second when
        the first is true is how a dead integration comes to look healthy.
        """
        age = self.client.seconds_since_last_message()
        if age is None:
            return None
        return round(age, 1)


class DeakoDevicesReporting(DeakoHubDiagnosticSensor):
    """How many devices reported in the last enumeration sweep.

    A tripwire, not a live signal. Ten hardware sweeps across two days returned
    37 of 37 every time, with an identical uuid set -- including one sweep
    taken against a switch that had been out of the wall for months, and one
    against a house where six devices were unreachable. The sweep has never
    once omitted a device, so this reads full essentially always.

    It is kept because it is nearly free and it is the only thing that would
    catch the sweep starting to behave differently. Nothing should be built on
    top of it, and in particular the `missing_uuids` attribute is a record of
    something never yet seen rather than a source of suspicion.

    The count is tracked outside the library's device cache on purpose: that
    cache is never cleared, so a device missing from a later sweep leaves its
    old entry sitting there and a cache lookup could never notice.
    """

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "devices"

    def __init__(self, client: Deako, entry: ConfigEntry) -> None:
        """Set up the sweep reading."""
        super().__init__(client, entry, "devices_reporting")

    @property
    def native_value(self) -> int | None:
        """Return how many devices reported, or None before the first sweep."""
        reporting, _expected, _missing = self.client.get_last_sweep()
        return reporting

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Expose what was expected and what did not turn up."""
        _reporting, expected, missing = self.client.get_last_sweep()
        return {
            "expected_devices": expected,
            "missing_uuids": missing,
        }

    async def async_added_to_hass(self) -> None:
        """Update when a sweep concludes -- setup, and every resync after."""
        self.client.add_sweep_listener(self.on_sweep)

    async def async_will_remove_from_hass(self) -> None:
        """Stop listening."""
        self.client.remove_sweep_listener(self.on_sweep)

    @callback
    def on_sweep(self) -> None:
        """Write the concluded sweep's numbers out."""
        self.schedule_update_ha_state()


class DeakoUnreachableDevices(DeakoHubDiagnosticSensor):
    """How many switches are currently marked `unreachable`.

    The third hub number (wayfinder #43, built in #45), and the one that reads
    the mark itself rather than a pass. It is `len(get_unreachable())` -- the
    same set the per-switch node status sensors report one at a time.

    **There is exactly one condition under which it and those sensors disagree,
    and it is not rare: a hub outage.** `DeakoNodeStatus` makes
    `hub_disconnected` dominate, on the reasoning that a disconnected hub makes
    every other reading meaningless -- so while the connection is down, every
    node reads `hub_disconnected` and *none* reads `unreachable`, while this
    still counts the marks, because a mark is about the device and survives a
    reconnect. Measured by hand on the rig: hub killed with one switch marked,
    this read `1` against zero sensors reading `unreachable`, and they agreed
    again the moment the connection came back.

    That is deliberate rather than a defect -- this hub's diagnostics are
    always available precisely so they outlive the outage they describe (#23)
    -- but it is written down here because it will show in the house
    routinely: the node that flaps every 6-12 minutes, and the ten drops in
    thirteen minutes #32 recorded after cutover, are all windows where the
    dashboard shows a count with nothing to match it against.

    **Expect it to differ from the probe pair too, and do not try to reconcile
    them.** They answer different questions and they are not even taken at the
    same moment. This is a *snapshot*: what is marked right now. The pair is a
    *verdict*: of the devices the last pass wrote to, how many answered. A mark
    needs two misses, and #26's confirming retry lands 30 s after a pass has
    already published its numbers -- so a switch that failed a pass is not yet
    marked when that pass's counts are written, and a switch marked days ago is
    not in that pass's numbers at all.

    Not restored across a restart, unlike the probe records. The mark lives in
    memory and is genuinely gone when Home Assistant comes back up, so zero is
    the truth at that moment rather than a hole -- and restoring a count of
    marks that no longer exist would be the invention this map keeps warning
    about.
    """

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "devices"

    def __init__(self, client: Deako, entry: ConfigEntry) -> None:
        """Set up the count."""
        super().__init__(client, entry, "unreachable_devices")

    @property
    def native_value(self) -> int:
        """Return how many switches are marked right now."""
        return len(self.client.get_unreachable())

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Expose which ones, so the number is followable."""
        return {"unreachable_uuids": sorted(self.client.get_unreachable())}

    async def async_added_to_hass(self) -> None:
        """Move whenever a mark is set or lifted."""
        self.client.add_reachability_listener(self.on_reachability_change)

    async def async_will_remove_from_hass(self) -> None:
        """Stop listening."""
        self.client.remove_reachability_listener(self.on_reachability_change)

    @callback
    def on_reachability_change(self, uuid: str, reachable: bool) -> None:
        """Any device's mark moving changes this count."""
        self.schedule_update_ha_state()


class DeakoAsymmetryProbes(DeakoHubDiagnosticSensor):
    """The asymmetry measurement, and nothing more (wayfinder #43/#45).

    #43 left one question that twelve days of house history could not settle.
    A switch marked `unreachable` that then emits an `EVENT` is either
    **intermittent** -- genuinely reachable for a couple of minutes -- or
    **asymmetric**, able to report but never to obey, in which case `online`
    was never true. The median life of a cleared mark is 2.2 minutes, so the
    hourly pass will nearly always miss the window; the only instrument that
    fits inside it is a single `CONTROL` sent the instant the `EVENT` lands.

    This reports it, as **two counts that are both entity states**, and that
    is the whole design rather than a detail. `witnessed` climbing with the
    total says intermittent; a total that climbs while `witnessed` stays put
    says asymmetric.

    **The split has to be two states, because long-term statistics only keep a
    state.** This map preferred entities to log lines because the recorder
    holds 60 days while statistics never purge (#10, #23), and the sample here
    accrues a few clears a day -- so the question is asked months later by
    construction. Asked directly, Home Assistant stores a statistics row of
    `state`, `sum`, `change`, `last_reset` and **no attributes at all**: a
    split carried in attributes would leave "847 probes sent" as the only
    surviving fact, which cannot separate the two readings and is therefore
    not a measurement. So the witnessed count is `DeakoAsymmetryWitnessed`
    beside this one, and `unwitnessed` is the difference of two series that
    both outlive the retention window.

    **It builds no defence and nothing branches on it.** Asymmetry has never
    been observed and this map does not keep mechanisms against faults nobody
    has seen -- so if this comes back empty, nothing is built on it and the
    measurement is what gets deleted.

    **The attributes are an attribution record, not the measurement** (wayfinder
    #45). This sends a real `CONTROL`, and #25's rule is that a probe write
    must be attributable, because it is invisible in the recorder: it drives
    the light to the value Home Assistant already believes, so `light.X` reads
    the same before and after. `last_device` and `last_value` say what left the
    building, written at the send rather than reconstructed afterwards, so the
    row exists even if Home Assistant restarts inside the window.

    Attributes are the right home for *that* job and the wrong one for the
    split above: attribution is a question asked within days of a light moving,
    comfortably inside the 60 days ordinary history keeps.

    It deliberately does **not** write the probe pass's `last_probed` pair.
    Doing so would point that timestamp at a write which produced no pass
    outcome, and `DeakoLastProbeOutcome` is read against it to know which pass
    a verdict belongs to.

    `last_witnessed` is `None` while the window is open -- a different fact
    from a measurement that came back unwitnessed. The two counts, not these
    attributes, are the tally: the attributes describe the most recent write
    only.

    **Reading the verdict back out of history takes one query parameter.** The
    write increments this sensor's state, so it lands as an ordinary recorded
    row; the verdict arrives five seconds later and changes attributes only, so
    the default history view -- and the Home Assistant history UI -- collapses
    it, and every row then reads `last_witnessed: None` as though nothing ever
    resolved. Ask with `significant_changes_only=0` and both rows are there.
    Measured on the rig: 3 rows by default against 5 with the flag, the extra
    two carrying `witnessed=False`. Nothing is lost either way -- each write is
    its own row, so an overwrite by a later measurement cannot bury an earlier
    one -- but the default reading is misleading and it is worth knowing before
    somebody concludes the instrument is broken.
    """

    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "probes"

    def __init__(self, client: Deako, entry: ConfigEntry) -> None:
        """Set up the count."""
        super().__init__(client, entry, "asymmetry_probes")

    @property
    def native_value(self) -> int:
        """Return how many asymmetry probes have been sent since startup."""
        probes, _witnessed = self.client.get_asymmetry_counts()
        return probes

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Expose the split, and what the last measurement wrote."""
        probes, witnessed = self.client.get_asymmetry_counts()
        attrs: dict[str, object] = {
            "witnessed": witnessed,
            "unwitnessed": probes - witnessed,
        }
        last = self.client.get_asymmetry_last()
        if last is None:
            attrs.update({
                "last_device": None,
                "last_device_uuid": None,
                "last_value": None,
                "last_dim": None,
                "last_witnessed": None,
            })
            return attrs
        attrs.update({
            "last_device": last["name"],
            "last_device_uuid": last["uuid"],
            "last_value": PROBE_VALUE_ON if last["power"] else PROBE_VALUE_OFF,
            "last_dim": last["dim"],
            "last_witnessed": last["witnessed"],
        })
        return attrs

    async def async_added_to_hass(self) -> None:
        """Move whenever a measurement concludes."""
        self.client.add_asymmetry_listener(self.on_measurement)

    async def async_will_remove_from_hass(self) -> None:
        """Stop listening."""
        self.client.remove_asymmetry_listener(self.on_measurement)

    @callback
    def on_measurement(self) -> None:
        """Write the new split out."""
        self.schedule_update_ha_state()


class DeakoAsymmetryWitnessed(DeakoHubDiagnosticSensor):
    """How many asymmetry measurements the switch actually answered.

    The other half of the measurement, and a state rather than an attribute
    for one reason: **long-term statistics keep a state and nothing else.**
    Asked directly, Home Assistant stores `state`, `sum`, `change` and
    `last_reset` per statistics row, with no attributes -- so a split carried
    on `DeakoAsymmetryProbes` alone would purge with ordinary history at 60
    days, leaving a total number of probes that cannot separate #43's two
    readings from each other.

    Read against its twin: climbing together is **intermittent**, a total
    climbing while this stays flat is **asymmetric**. Both series outlive the
    retention window, so the question can still be answered by somebody who
    asks it next year -- which is the timescale this instrument was built for,
    since a marked switch clears only a few times a day.

    Deliberately the witnessed count rather than the unwitnessed one. Both
    would do, since the pair and the difference carry the same information, but
    a `TOTAL_INCREASING` series that stays at zero is the asymmetric reading
    showing itself plainly, and a flat line is easier to trust than a line that
    tracks its twin.
    """

    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = "probes"

    def __init__(self, client: Deako, entry: ConfigEntry) -> None:
        """Set up the count."""
        super().__init__(client, entry, "asymmetry_witnessed")

    @property
    def native_value(self) -> int:
        """Return how many measurements were answered."""
        _probes, witnessed = self.client.get_asymmetry_counts()
        return witnessed

    async def async_added_to_hass(self) -> None:
        """Move whenever a measurement concludes."""
        self.client.add_asymmetry_listener(self.on_measurement)

    async def async_will_remove_from_hass(self) -> None:
        """Stop listening."""
        self.client.remove_asymmetry_listener(self.on_measurement)

    @callback
    def on_measurement(self) -> None:
        """Write the new count out."""
        self.schedule_update_ha_state()


class DeakoRestoredProbeReading(RestoreEntity):
    """Carry a probe reading across a restart.

    **A restart must be invisible to this record**, and leaving it out was a
    mistake the map owner caught. The argument for leaving it out was that the
    recorder holds the history, so nothing is lost. That is wrong about what a
    restart actually does: Home Assistant writes a *new* `unknown` state for
    every unrestored entity as it comes up, so the record does not merely pause
    -- it gains a false interval saying nobody knew when this switch was last
    probed. We did know. It was in the previous row.

    That matters more here than on an ordinary sensor. This pair exists to
    attribute a light that moved with nobody asking, at three in the morning,
    read back weeks later. An `unknown` stretch across the exact window
    somebody is asking about is the failure this entity was built to prevent,
    arriving by a different door.

    Restoring invents nothing: the value written back is the one this
    installation recorded, and a probe timestamp that is genuinely old still
    reads old.
    """

    _restored_state: str | None = None
    _restored_attributes: Mapping[str, Any] = {}

    async def async_added_to_hass(self) -> None:
        """Take back the last reading this installation recorded."""
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is None or last.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return
        self._restored_state = last.state
        self._restored_attributes = last.attributes

    def restored_timestamp(self) -> datetime | None:
        """Return the restored reading as a datetime, if it parses."""
        if self._restored_state is None:
            return None
        return dt_util.parse_datetime(self._restored_state)

    def restored_count(self) -> int | None:
        """Return the restored reading as a count, if it parses."""
        if self._restored_state is None:
            return None
        try:
            return int(float(self._restored_state))
        except ValueError:
            return None


class DeakoProbeNodeSensor(SensorEntity, DeakoRestoredProbeReading):
    """Shared wiring for the per-switch probe records.

    On the same device as that switch's light and its node status, because
    those three are read together: what the probe last sent, when it sent it,
    and what the switch has been saying since.
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = False

    def __init__(
        self, prober: DeakoProber, client: Deako, uuid: str, key: str,
    ) -> None:
        """Bind to one device."""
        self.prober = prober
        self.uuid = uuid
        self._attr_translation_key = key
        self._attr_unique_id = f"{uuid}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, uuid)},
            name=client.get_name(uuid),
            manufacturer=MANUFACTURER,
        )

    @property
    def available(self) -> bool:
        """Always available.

        A record of what was written to a switch has to survive the switch
        going quiet -- that is the case it exists for.
        """
        return True

    async def async_added_to_hass(self) -> None:
        """Listen for this device being probed, and take back the last one."""
        await super().async_added_to_hass()
        self.prober.add_device_listener(self.on_probe)

    async def async_will_remove_from_hass(self) -> None:
        """Stop listening."""
        self.prober.remove_device_listener(self.on_probe)

    @callback
    def on_probe(self, uuid: str) -> None:
        """One device was probed; ignore the other devices'."""
        if uuid != self.uuid:
            return
        self.schedule_update_ha_state()


class DeakoLastProbed(DeakoProbeNodeSensor):
    """When the probe last wrote to this switch.

    Half of the attribution record (wayfinder #25). On its own it answers "was
    the integration writing to this light at 03:14?", which is the question
    somebody asks after a light they did not touch was on when they got up.
    """

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(
        self, prober: DeakoProber, client: Deako, uuid: str,
    ) -> None:
        """Set up the timestamp."""
        super().__init__(prober, client, uuid, "last_probed")

    @property
    def native_value(self) -> datetime | None:
        """Return when this switch was last probed, or None if never."""
        probed = self.prober.get_probed_at(self.uuid)
        if probed is not None:
            return probed
        return self.restored_timestamp()


class DeakoLastProbeValue(DeakoProbeNodeSensor):
    """What the probe last sent to this switch.

    The other half, and the one the accepted risk actually rests on.

    The probe echoes each device's cached state back at it. If that cache was
    wrong -- which needs a device that drifted while off the mesh and has since
    come back -- the echo is a live command driving a light to a value nobody
    asked for. **And the recorder would show nothing at all**, because the
    light moves *to* the state Home Assistant already believes: `light.X` reads
    `off` before and `off` after, with no state change to record.

    So this pair is the only possible witness to the one hazard #25 chose to
    accept rather than prevent. A reading that is plausible but not actually
    what left the building defeats the entire arrangement, which is why it is
    written at the send in probe.py rather than reconstructed from a summary.

    The level rides as an attribute rather than as a second entity: brightness
    is only meaningful alongside `on`, and this pair is already 74 entities.
    """

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = PROBE_VALUE_OPTIONS

    def __init__(
        self, prober: DeakoProber, client: Deako, uuid: str,
    ) -> None:
        """Bind to one device."""
        super().__init__(prober, client, uuid, "last_probe_value")

    @property
    def native_value(self) -> str | None:
        """Return the power state that was sent, or None if never probed."""
        value = self.prober.get_probe_value(self.uuid)
        if value is not None:
            power, _dim = value
            return PROBE_VALUE_ON if power else PROBE_VALUE_OFF
        if self._restored_state in PROBE_VALUE_OPTIONS:
            return self._restored_state
        return None

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Expose the brightness that went with it, if any."""
        value = self.prober.get_probe_value(self.uuid)
        if value is not None:
            return {"dim": value[1]}
        if self._restored_state in PROBE_VALUE_OPTIONS:
            # The level is half the reading, so it has to come back with it --
            # `on` alone cannot say which brightness a light was driven to.
            return {"dim": self._restored_attributes.get("dim")}
        return {"dim": None}


class DeakoLastProbeOutcome(DeakoProbeNodeSensor):
    """Whether this switch answered the last pass that wrote to it.

    The third of the per-switch records (wayfinder #43 decision 5, built in
    #45). `last_probed` says when we wrote and `last_probe_value` says what we
    sent; neither says whether the switch did anything about it. The pass
    computed exactly that per uuid and then threw it away into two hub counts,
    so the only per-device answer available was the node status sensor -- which
    is a running verdict shaped by two misses and a retry, not a record of one
    pass.

    #44 named that gap as one of the reasons attributing a light that moved on
    its own took a week: with a hub count of "2 did not answer" and 37
    switches, nothing said *which two*.

    `unknown` until a pass that wrote to this switch has concluded, and it then
    holds that verdict until the next pass concludes. It deliberately does not
    blank itself when the next pass sends -- an `unknown` stretch through the
    middle of the record is precisely the failure DeakoRestoredProbeReading
    exists to prevent -- so it is always read alongside `last_probed`, which
    says which pass it belongs to.
    """

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = PROBE_OUTCOME_OPTIONS

    def __init__(
        self, prober: DeakoProber, client: Deako, uuid: str,
    ) -> None:
        """Bind to one device."""
        super().__init__(prober, client, uuid, "last_probe_outcome")

    @property
    def native_value(self) -> str | None:
        """Return whether it answered, or None if no pass has concluded."""
        answered = self.prober.get_probe_answered(self.uuid)
        if answered is not None:
            return (
                PROBE_OUTCOME_ANSWERED if answered
                else PROBE_OUTCOME_NO_ANSWER
            )
        if self._restored_state in PROBE_OUTCOME_OPTIONS:
            return self._restored_state
        return None


class DeakoProbePassSensor(DeakoHubDiagnosticSensor, DeakoRestoredProbeReading):
    """Shared wiring for the hub-level probe readings."""

    def __init__(
        self, prober: DeakoProber, client: Deako, entry: ConfigEntry, key: str,
    ) -> None:
        """Bind to the probe this entry owns."""
        super().__init__(client, entry, key)
        self.prober = prober

    async def async_added_to_hass(self) -> None:
        """Update whenever a pass concludes, and take back the last one."""
        await super().async_added_to_hass()
        self.prober.add_pass_listener(self.on_pass)

    async def async_will_remove_from_hass(self) -> None:
        """Stop listening."""
        self.prober.remove_pass_listener(self.on_pass)

    @callback
    def on_pass(self) -> None:
        """Write the concluded pass's numbers out."""
        self.schedule_update_ha_state()


class DeakoLastProbePass(DeakoProbePassSensor):
    """When the last probe pass completed.

    This one exists to show the probe **stopping**, which no per-device record
    can. The on/off switch can turn the probe off; if that happened and were
    forgotten, every node status would read `online` and the house would look
    perfectly healthy, because nothing would be reaching for anything to
    contradict it. That is precisely the trap #3 caught in the act -- an
    integration reporting itself healthy while doing nothing at all -- and a
    timestamp that stops advancing is visible in a way that a log line which
    stops appearing is not.

    It advances only on a pass that ran to the end. A pass abandoned when the
    hub went away is not a census, and recording it as one would hide exactly
    the condition this is watching for. It survives a restart, for the same
    reason: coming back as `unknown` would read as "no pass has ever run",
    which is the one thing this entity must never say when it is not true.
    """

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(
        self, prober: DeakoProber, client: Deako, entry: ConfigEntry,
    ) -> None:
        """Set up the timestamp."""
        super().__init__(prober, client, entry, "last_probe_pass")

    async def async_added_to_hass(self) -> None:
        """Update on each pass, and hand the restored one to the governor."""
        await super().async_added_to_hass()
        restored = self.restored_timestamp()
        if restored is not None:
            self.prober.seed_last_pass(restored)

    @property
    def native_value(self) -> datetime | None:
        """Return when the last completed pass finished."""
        last = self.prober.last_pass_at
        if last is not None:
            return last
        # Only reachable if the restored value would not parse, in which case
        # the governor did not take it either.
        return self.restored_timestamp()


class DeakoProbeWitnessed(DeakoProbePassSensor):
    """How many devices answered in the last pass.

    Numeric on purpose. This recorder keeps ordinary history for 60 days (#6),
    but long-term statistics never purge -- so a number, unlike a status
    string, still exists in five years. The drop rate is the thing #10 said
    nobody knows, and this is the entity that outlives the retention window
    long enough to answer it.

    Counted as a census of the writes, which since wayfinder #45 is also a
    census of the house: every device is written to every pass. #26 skipped a
    device the passive detector had heard from and counted it as answering
    anyway, so this number silently included devices nothing had asked -- and
    on one measured pass that put a switch simultaneously marked `unreachable`
    inside "35 answering".
    """

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "devices"

    def __init__(
        self, prober: DeakoProber, client: Deako, entry: ConfigEntry,
    ) -> None:
        """Set up the count."""
        super().__init__(prober, client, entry, "probe_witnessed")

    @property
    def native_value(self) -> int | None:
        """Return how many answered, or None before the first pass."""
        witnessed = self.prober.witnessed
        if witnessed is not None:
            return witnessed
        return self.restored_count()


class DeakoProbeUnwitnessed(DeakoProbePassSensor):
    """How many devices did not answer in the last pass.

    The one that matters, and the reason the pair is kept rather than a single
    count and a total: this is the house's mesh drop rate, sampled hourly, and
    it has never been measured. Numeric for the same reason as its twin, and
    restored across a restart for a reason that follows from being numeric:
    an `unknown` gap is a hole in a long-term statistic that never purges.
    """

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "devices"

    def __init__(
        self, prober: DeakoProber, client: Deako, entry: ConfigEntry,
    ) -> None:
        """Set up the count."""
        super().__init__(prober, client, entry, "probe_unwitnessed")

    @property
    def native_value(self) -> int | None:
        """Return how many did not answer, or None before the first pass."""
        unwitnessed = self.prober.unwitnessed
        if unwitnessed is not None:
            return unwitnessed
        return self.restored_count()
