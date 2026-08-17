"""The probe's on/off switch (wayfinder #26).

A switch rather than a config-flow option, and the difference is the point:
this is reachable from a phone, in the middle of the night, without opening
Settings -- and the house has already had a nine-day outage during which the
options flow itself was returning 500 ([#3]).

It stops **automatic** passes only. The census button beside it still works
when this is off, because a human asking is the consent model the whole
design rests on, and taking that away would leave someone who turned the probe
off with no way to ask a question about their own house.
"""
from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .binary_sensor import hub_device_info
from .const import PROBE_DATA
from .probe import DeakoProber

_LOGGER: logging.Logger = logging.getLogger(__package__)


async def async_setup_entry(
    hass: HomeAssistant,
    config: ConfigEntry,
    add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Configure the platform."""
    prober: DeakoProber = hass.data[PROBE_DATA][config.entry_id]
    add_entities([DeakoProbeSwitch(prober, config)])


class DeakoProbeSwitch(SwitchEntity, RestoreEntity):
    """Whether the hourly reachability probe runs on its own.

    **Default on, and restored across restarts.** Defaulting off would ship the
    decision #25 made and then not take it; restoring is what makes turning it
    off mean anything, since a setting that quietly comes back at the next
    Home Assistant restart is worse than no setting at all -- it would look
    respected and not be.

    Turning it off is a real risk, which is why the hub's last-probe-pass
    timestamp exists: with the probe off, every node status reads `online`
    because nothing is contradicting it, and the house looks perfectly healthy
    while nothing is being checked. The timestamp is the only thing that shows
    it.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "probe_enabled"
    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_entity_category = EntityCategory.CONFIG
    _attr_should_poll = False

    def __init__(self, prober: DeakoProber, entry: ConfigEntry) -> None:
        """Bind to this entry's probe."""
        self.prober = prober
        self._attr_unique_id = f"{entry.entry_id}_probe_enabled"
        self._attr_device_info = hub_device_info(entry)
        self._attr_is_on = prober.enabled

    @property
    def available(self) -> bool:
        """Always available.

        A control that disappears when the hub does would leave somebody
        unable to turn the probe off during exactly the incident that made
        them want to.
        """
        return True

    async def async_added_to_hass(self) -> None:
        """Restore the last answer, or default to on if there is none."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in (STATE_ON, STATE_OFF):
            self._attr_is_on = last_state.state == STATE_ON
        self.prober.set_enabled(bool(self._attr_is_on))
        _LOGGER.debug(
            "The reachability probe starts %s",
            "on" if self._attr_is_on else "off (restored)",
        )

    async def async_turn_on(self, **kwargs: object) -> None:
        """Let automatic passes run again."""
        self._attr_is_on = True
        self.prober.set_enabled(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: object) -> None:
        """Stop automatic passes.

        A pass already in flight is left to finish. Tearing one down halfway
        would leave part of the house probed and the census counts describing
        nothing in particular, and the pass is over in well under a minute.
        """
        self._attr_is_on = False
        self.prober.set_enabled(False)
        self.async_write_ha_state()
