"""Binary sensor platform for integration_blueprint."""
import asyncio
import logging
from typing import Any

from atomicx import AtomicBool
from pydeako.deako import Deako

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER: logging.Logger = logging.getLogger(__package__)


async def async_setup_entry(
    hass: HomeAssistant,
    config: ConfigEntry,
    add_entities: AddEntitiesCallback,
) -> None:
    """Configure the platform."""
    client: Deako = hass.data[DOMAIN][config.entry_id]

    devices = client.get_devices()
    if len(devices) == 0:
        # If deako devices are advertising on mdns, we should be able to get at least one device
        _LOGGER.warning("No devices found from local integration")
        await client.disconnect()
        return
    lights = [DeakoLightSwitch(client, uuid) for uuid in devices]
    add_entities(lights)


class DeakoLightSwitch(LightEntity):
    """Deako LightEntity class."""

    client: Deako
    uuid: str
    is_refreshing: AtomicBool
    is_additional_refresh_requested: AtomicBool

    def __init__(self, client: Deako, uuid: str) -> None:
        """Save connection reference."""
        self.client = client
        self.uuid = uuid
        self.client.set_state_callback(self.uuid, self.on_update)
        self.is_refreshing = AtomicBool(False)
        self.is_additional_refresh_requested = AtomicBool(False)

    def on_update(self) -> None:
        """State update callback."""
        self.schedule_update_ha_state()

    @property
    def device_info(self) -> DeviceInfo:
        """Returns device info in HA digestable format."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.uuid)},
            name=self.name,
            manufacturer="Deako",
            model="dimmer"
            if ColorMode.BRIGHTNESS in self.supported_color_modes
            else "smart",
        )

    @property
    def unique_id(self) -> str:
        """Return the ID of this Deako light."""
        return self.uuid

    @property
    def name(self) -> str:
        """Return the name of the Deako light."""
        name = self.client.get_name(self.uuid)
        return name or f"Unknown device: {self.uuid}"

    @property
    def is_on(self) -> bool:
        """Return true if the light is on."""
        state = self.client.get_state(self.uuid)
        power = state.get("power", False)
        result = False
        if isinstance(power, bool):
            result = power

        # Return the current information but trigger a refresh so it can be updated
        asyncio.ensure_future(self.refresh_devices())  # noqa: RUF006
        return result

    @property
    def brightness(self) -> int:
        """Return the brightness of this light between 0..255."""
        state = self.client.get_state(self.uuid)

        # Return the current information but trigger a refresh so it can be updated
        asyncio.ensure_future(self.refresh_devices())  # noqa: RUF006
        return int(round(state.get("dim", 0) * 2.55))

    @property
    def supported_color_modes(self) -> set[ColorMode]:
        """Flag supported features."""
        color_modes: set[ColorMode] = set()
        state = self.client.get_state(self.uuid)
        if state.get("dim") is None:
            color_modes.add(ColorMode.ONOFF)
        else:
            color_modes.add(ColorMode.BRIGHTNESS)
        # Return the current information but trigger a refresh so it can be updated
        asyncio.ensure_future(self.refresh_devices())  # noqa: RUF006
        return color_modes

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the light."""
        dim = None
        if ATTR_BRIGHTNESS in kwargs:
            dim = round(kwargs[ATTR_BRIGHTNESS] / 2.55, 0)
        await self._async_ensure_connection_and_wait()
        await self.client.control_device(self.uuid, True, dim)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the device."""
        dim = None
        if ATTR_BRIGHTNESS in kwargs:
            dim = round(kwargs[ATTR_BRIGHTNESS] / 2.55, 0)
        await self._async_ensure_connection_and_wait()
        await self.client.control_device(self.uuid, False, dim)

    async def _async_ensure_connection_and_wait(self) -> None:
        """Ensure connection and wait for device list."""
        _LOGGER.debug("Checking to make sure the connection is still available")
        if not (
            # TODO:  Update (or finish updating) PyDeako to expose a way of listening for when the connection drops or is restored
            self.client.connection_manager is not None
            and self.client.connection_manager.connection is not None
            and self.client.connection_manager.connection.is_connected()
        ):
            # PyDeako's maintain_connection_worker() doesn't quite seem to work as desired.  Part of the problem may be due to the state management for the canceling state and the connecting state flags and how they're reset and interpreted.
            # If a lack of connection is deteced, reload the entier integration.  This will likely fail if it's due to a prolonged disconnection which should create a relatively clear signal in Home Assistant that something is wrong.  Additionally,
            # Home Assistant will automatically reload the integration periodically which will retry the connection
            await self.hass.config_entries.async_reload(
                # TODO:  Confirm that this is an appropriate method for acquiring the integration's ID
                self.registry_entry.config_entry_id
            )
            _LOGGER.error("The connection does not seem to be available anymore")
            raise ConfigEntryNotReady("Detected a disconnected state")
        else:
            _LOGGER.debug("Connection appears to still be available")

    async def refresh_devices(self) -> None:
        """Refresh the device list."""
        _LOGGER.debug("Checking if it's okay to start refreshing devices")
        if not self.is_refreshing.compare_exchange(True, True):
            await self._async_ensure_connection_and_wait()
            _LOGGER.debug("Starting to refresh the devices with a 60 second wait")
            await self.client.find_devices(60)

            # TODO:  Think about thread safety here.  Not yet sure how that works in Python
            self.is_refreshing.store(False)
            if self.is_additional_refresh_requested.compare_exchange(True, False):
                # Let's hold off on actually doing the extra refresh for now.  I don't feel like testing that yet
                # asyncio.ensure_future(self.refresh_devices(60))  # noqa: RUF006
                pass
        else:
            self.is_additional_refresh_requested.store(True)
            _LOGGER.debug("Skipping refresh because one is in progress")
