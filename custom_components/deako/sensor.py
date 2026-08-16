"""Diagnostic sensors for Deako (wayfinder #23).

Five entity types ship, and they answer different questions:

  * **Node status**, one per switch, on the same device as that switch's light.
    `unavailable` alone is never a diagnosis -- it can mean the integration is
    down, the hub is down, or that one switch is unreachable -- so the cause is
    readable on the node itself, and "since when" comes free from its history.
  * **Reconnects since restart**, **seconds since last hub message** and
    **devices reporting**, on a device standing for the hub.

What the node status sensor honestly cannot say is set out on
DeakoNodeStatus below. Read it before building anything on top of this.
"""
from __future__ import annotations

import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .binary_sensor import hub_device_info
from .const import (
    DOMAIN,
    MANUFACTURER,
    NODE_STATUS_HUB_DISCONNECTED,
    NODE_STATUS_ONLINE,
    NODE_STATUS_OPTIONS,
    NODE_STATUS_UNREACHABLE,
)
from .pydeako.deako import Deako

_LOGGER: logging.Logger = logging.getLogger(__package__)


async def async_setup_entry(
    hass: HomeAssistant,
    config: ConfigEntry,
    add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Configure the platform."""
    client: Deako = hass.data[DOMAIN][config.entry_id]

    add_entities(
        [
            DeakoHubReconnects(client, config),
            DeakoLastMessageAge(client, config),
            DeakoDevicesReporting(client, config),
        ]
    )

    added: set[str] = set()

    @callback
    def add_nodes(uuids: list[str]) -> None:
        new = [uuid for uuid in uuids if uuid not in added]
        if not new:
            return
        added.update(new)
        add_entities([DeakoNodeStatus(client, uuid) for uuid in new])

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
    truth, and it only exists once something has been asked for. So a node
    nobody has touched for a week reads `online` because nothing has
    contradicted it -- **this sensor cannot discover an unreachable switch, it
    can only confirm one the moment someone reaches for it.**

    Which is when the house currently finds out too, except that today it
    finds out silently and after this it says so.

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

    Read alongside the connectivity sensor, never on its own. 0.6.0 has no
    reconnect backoff -- a dead node is retried about six times a minute, and
    #19 measured that against real firmware -- so this counts connections that
    came *back*. A single long outage therefore adds one, and what this number
    really measures is how often the hub went away, not how long for.
    """

    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, client: Deako, entry: ConfigEntry) -> None:
        """Set up the counter."""
        super().__init__(client, entry, "reconnects")

    @property
    def native_value(self) -> int:
        """Return the count since this entry was set up."""
        return self.client.get_reconnect_count()

    async def async_added_to_hass(self) -> None:
        """A reconnect is a connection change, so this is the same signal."""
        self.client.add_connection_listener(self.on_connection_change)

    async def async_will_remove_from_hass(self) -> None:
        """Stop listening."""
        self.client.remove_connection_listener(self.on_connection_change)

    @callback
    def on_connection_change(self, connected: bool) -> None:
        """Write the new count out."""
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
