"""Hub-level connectivity diagnostics for Deako (wayfinder #23).

One entity: whether there is a live connection to the bound hub. It is what
drives every node's `hub_disconnected` reading, and it carries the bound
address as an attribute -- manual address selection is this map's safety
control, and it has to stay readable even while the options flow is somewhere
else.
"""
from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import get_connection_address
from .const import (
    DOMAIN,
    HUB_DEVICE_MODEL,
    HUB_DEVICE_NAME,
    MANUFACTURER,
)
from .pydeako.deako import Deako

_LOGGER: logging.Logger = logging.getLogger(__package__)


def hub_device_info(entry: ConfigEntry) -> DeviceInfo:
    """Describe the hub itself, which the hub-level diagnostics hang off."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=HUB_DEVICE_NAME,
        manufacturer=MANUFACTURER,
        model=HUB_DEVICE_MODEL,
    )


async def async_setup_entry(
    hass: HomeAssistant,
    config: ConfigEntry,
    add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Configure the platform."""
    client: Deako = hass.data[DOMAIN][config.entry_id]
    add_entities([DeakoHubConnected(client, config)])


class DeakoHubConnected(BinarySensorEntity):
    """Whether the integration currently holds a connection to the hub."""

    _attr_has_entity_name = True
    _attr_translation_key = "hub_connected"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    # Nothing polls. The library pushes every transition of the socket's own
    # state machine, which is what makes "the hub went away" arrive in about
    # half a second rather than whenever something next reads this (O5).
    _attr_should_poll = False

    def __init__(self, client: Deako, entry: ConfigEntry) -> None:
        """Bind to the connection this entry owns."""
        self.client = client
        self._address = get_connection_address(entry)
        self._attr_unique_id = f"{entry.entry_id}_hub_connected"
        self._attr_device_info = hub_device_info(entry)

    @property
    def available(self) -> bool:
        """Always available.

        This is the entity whose whole job is to say "not connected". Letting
        it go unavailable with the connection would delete the reading at
        exactly the moment it becomes worth having, and leave history unable to
        tell an outage from an integration that was never loaded.
        """
        return True

    @property
    def is_on(self) -> bool:
        """Return whether the connection is live."""
        return self.client.is_connected()

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        """Expose the address this entry is bound to.

        An attribute rather than an entity: it never changes, so recording it
        as state buys nothing. It has to stay visible because the house has
        three Deako nodes, one of them serving SmartThings, and which one this
        is bound to is a safety question ([#8], [#3]).
        """
        return {"hub_address": self._address}

    async def async_added_to_hass(self) -> None:
        """Start listening for the connection going up and down."""
        self.client.add_connection_listener(self.on_connection_change)

    async def async_will_remove_from_hass(self) -> None:
        """Stop listening for connection changes."""
        self.client.remove_connection_listener(self.on_connection_change)

    @callback
    def on_connection_change(self, connected: bool) -> None:
        """Write the new answer out."""
        _LOGGER.debug("Hub connectivity is now %s", connected)
        self.schedule_update_ha_state()
