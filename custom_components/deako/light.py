"""Support for Deako lights.

The entity layer converges on Home Assistant core's own Deako integration,
which does this job better than the fork did: state is held in `_attr_`
attributes and recomputed when the hub says something, rather than being
rebuilt inside property getters that each kicked off a background refresh.

What core does not have, and this adds, is the availability model (outcomes O5
and O10): core's entity is `_attr_available = True` and stays that way, so a
hub that vanished a day ago looks exactly like a healthy one. Here:

  * the connection going down marks every light unavailable, pushed from the
    library rather than discovered on a timer;
  * a device that never reported has no entity, which Home Assistant already
    shows as unavailable rather than deleting -- and a late DEVICE_FOUND
    creates one, which is the part that was missing;
  * a command sent while disconnected raises instead of being swallowed.
"""
import logging
from typing import Any

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .pydeako.deako import Deako, DeviceCommandError

_LOGGER: logging.Logger = logging.getLogger(__package__)

MODEL_SMART = "smart"
MODEL_DIMMER = "dimmer"


async def async_setup_entry(
    hass: HomeAssistant,
    config: ConfigEntry,
    add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Configure the platform."""
    client: Deako = hass.data[DOMAIN][config.entry_id]

    added: set[str] = set()

    @callback
    def add_devices(uuids: list[str]) -> None:
        new = [uuid for uuid in uuids if uuid not in added]
        if not new:
            return
        added.update(new)
        add_entities([DeakoLightEntity(client, uuid) for uuid in new])

    @callback
    def device_reported(uuid: str) -> None:
        """Build an entity for a device that reported after setup.

        O10: the hub's device list gives a count and no identities, so a
        device that stayed silent during enumeration cannot even be named on a
        first-ever setup -- only counted. On every later start it is named,
        because Home Assistant kept its registry entry and shows it as
        unavailable. Either way, when it finally reports, this is what turns it
        back into a working light without a restart.
        """
        _LOGGER.info("Device %s reported after setup; adding it now", uuid)
        add_devices([uuid])

    # Registered before the devices already in hand are added, so a straggler
    # arriving in between is picked up here rather than falling in the gap.
    # add_devices() dedupes, so whichever sees it first wins.
    client.set_device_added_callback(device_reported)
    config.async_on_unload(lambda: client.set_device_added_callback(None))

    add_devices(list(client.get_devices()))


class DeakoLightEntity(LightEntity):
    """Deako LightEntity class."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_is_on = False
    # O6: nothing polls. State arrives on pushed EVENT messages and on the
    # DEVICE_FOUND stream the library requests on every (re)connect, which is
    # what `local_push` in the manifest now claims. Home Assistant's default
    # 30s poll would only re-read the same cache.
    _attr_should_poll = False

    client: Deako

    def __init__(self, client: Deako, uuid: str) -> None:
        """Save connection reference."""
        self.client = client
        self.uuid = uuid
        self._attr_unique_id = uuid

        # O6: dimmability comes from the library, which reads it from the
        # device's declared capabilities. The fork inferred it from whether
        # `dim` happened to be present in the reported state, which says
        # "this dimmer is currently at an unknown level", not "this is not a
        # dimmer".
        dimmable = client.is_dimmable(uuid)

        model = MODEL_SMART
        self._attr_color_mode = ColorMode.ONOFF
        if dimmable:
            model = MODEL_DIMMER
            self._attr_color_mode = ColorMode.BRIGHTNESS

        # Declaring the active mode as well as the supported set is what
        # current Home Assistant requires: without it every state write is
        # rejected as "does not report a color mode", which is exactly how the
        # house sat frozen for nine days.
        self._attr_supported_color_modes = {self._attr_color_mode}

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, uuid)},
            name=client.get_name(uuid),
            manufacturer="Deako",
            model=model,
        )

        client.set_state_callback(uuid, self.on_update)
        self.update()  # set initial state

    async def async_added_to_hass(self) -> None:
        """Start listening for the connection going up and down (O5)."""
        self.client.add_connection_listener(self.on_connection_change)

    async def async_will_remove_from_hass(self) -> None:
        """Stop listening for connection changes."""
        self.client.remove_connection_listener(self.on_connection_change)

    @property
    def available(self) -> bool:
        """Return whether this light can currently be trusted or commanded.

        O5, the map's known trap: with no connection there is no way to know
        what any light is doing, and reporting the last thing we heard is what
        made a dead integration look identical to a healthy one in history.
        """
        return self.client.is_connected()

    def on_update(self) -> None:
        """State update callback.

        The only path by which state reaches Home Assistant. It fires on pushed
        EVENT messages, and -- since the vendored DEVIATION (O7) -- also on the
        DEVICE_FOUND replies to the device list request issued on every
        (re)connect. Nothing polls on top of it.
        """
        self.update()
        # A DEVICE_FOUND can land between constructing this entity and Home
        # Assistant adopting it, and writing state before then raises.
        if self.hass is not None:
            self.schedule_update_ha_state()

    @callback
    def on_connection_change(self, connected: bool) -> None:
        """Push the new availability out (O5).

        Called from the library the moment the socket dies or comes back, so
        the lights grey out in a bounded time -- half a second for a socket the
        hub closes, one ping window for one that goes quiet -- rather than
        whenever something next happens to read this entity.
        """
        _LOGGER.debug(
            "Connection %s; %s is now %s",
            "up" if connected else "down",
            self.entity_id,
            "available" if connected else "unavailable",
        )
        self.schedule_update_ha_state()

    async def control_device(self, power: bool, dim: int | None = None) -> None:
        """Control entity state via client."""
        try:
            await self.client.control_device(self.uuid, power, dim)
        except DeviceCommandError as exc:
            # O5: silently swallowing this is what let the house look healthy
            # while nothing it was told to do actually happened.
            raise HomeAssistantError(
                f"Could not send the command to {self.entity_id}: {exc.reason}"
            ) from exc

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the light."""
        dim = None
        if ATTR_BRIGHTNESS in kwargs:
            dim = round(kwargs[ATTR_BRIGHTNESS] / 2.55, 0)
        _LOGGER.debug("Turning on %s with dim %s", self.uuid, dim)
        await self.control_device(True, dim)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the device.

        Home Assistant's LIGHT_TURN_OFF_SCHEMA has no brightness field, so the
        fork's ATTR_BRIGHTNESS branch here could never run. Deleted rather than
        kept as a decoration (wayfinder #12).
        """
        _LOGGER.debug("Turning off %s", self.uuid)
        await self.control_device(False)

    def update(self) -> None:
        """Recompute cached state from the client's view of the device."""
        state = self.client.get_state(self.uuid) or {}
        self._attr_is_on = bool(state.get("power", False))
        if (
            self._attr_supported_color_modes is not None
            and ColorMode.BRIGHTNESS in self._attr_supported_color_modes
        ):
            # A dimmable device that has reported power but not yet a level
            # leaves `dim` as None, which is a missing reading rather than a
            # brightness of zero -- but there is nothing better to show until
            # one arrives, and multiplying None raises.
            self._attr_brightness = round((state.get("dim") or 0) * 2.55)
