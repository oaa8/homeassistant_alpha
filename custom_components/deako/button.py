"""The manual census button (wayfinder #26).

Exempt from the governor, and it works while the on/off switch is off. Both
exemptions come from the same place: the hourly rule exists to stop the
integration writing to the mesh on its own account more often than it needs
to, and a person pressing a button is not the integration acting on its own
account.

It is also the answer to "is this thing working?", which is a question the
hourly cadence makes annoying to ask: without this, checking would mean
waiting up to an hour, and nobody checks a diagnostic they have to wait an
hour for.
"""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .binary_sensor import hub_device_info
from .const import DOMAIN, PROBE_DATA
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
    add_entities([DeakoRunCensusButton(prober, client, config)])


class DeakoRunCensusButton(ButtonEntity):
    """Run a reachability census now."""

    _attr_has_entity_name = True
    _attr_translation_key = "run_census"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = False

    def __init__(
        self, prober: DeakoProber, client: Deako, entry: ConfigEntry,
    ) -> None:
        """Bind to this entry's probe."""
        self.prober = prober
        self.client = client
        self._attr_unique_id = f"{entry.entry_id}_run_census"
        self._attr_device_info = hub_device_info(entry)

    @property
    def available(self) -> bool:
        """Always available.

        Pressing it with no connection fails loudly below, which is a better
        answer than a control that has quietly vanished -- O5's whole lesson is
        that a thing which cannot work should say so rather than look absent.
        """
        return True

    async def async_press(self) -> None:
        """Start a census, and return without waiting for it.

        A pass is about forty seconds of paced writes. Awaiting it here would
        hold the service call open for that long, which reads like a hang and
        would time out anything scripting it -- so the press only starts the
        thing, and the hub's last-probe-pass timestamp is what says it
        finished.
        """
        if not self.client.is_connected():
            raise HomeAssistantError(
                "There is no connection to the Deako hub, so no census can be "
                "run. Check the hub's connectivity sensor."
            )
        _LOGGER.info("Running a reachability census on request")
        self.prober.request_census()
