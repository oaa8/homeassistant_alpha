"""Support for Deako lights."""
import asyncio
import logging
from timeit import default_timer as timer
from typing import Any

from pydeako.deako import Deako

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from ..deako import ATOMIC_BOOL_FALSE, ATOMIC_BOOL_TRUE
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
    # is_refreshing: atomics.INT
    # is_additional_refresh_requested: atomics.INT
    # is_refreshing: AtomicBool
    # is_additional_refresh_requested: AtomicBool

    def __init__(self, client: Deako, uuid: str) -> None:
        """Save connection reference."""
        self.client = client
        self.uuid = uuid
        self.client.set_state_callback(self.uuid, self.on_update)
        # self.is_refreshing = atomics.atomic(1, atomics.INT)
        # self.is_refreshing.store(ATOMIC_BOOL_FALSE)
        # self.is_additional_refresh_requested = atomics.atomic(1, atomics.INT)
        # self.is_additional_refresh_requested.store(ATOMIC_BOOL_FALSE)
        # self.is_refreshing = AtomicBool(False)
        # self.is_additional_refresh_requested = AtomicBool(False)

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
        _LOGGER.debug("Turning on %s with dim %s", self.uuid, dim)
        await self.client.control_device(self.uuid, True, dim)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the device."""
        dim = None
        if ATTR_BRIGHTNESS in kwargs:
            dim = round(kwargs[ATTR_BRIGHTNESS] / 2.55, 0)
        await self._async_ensure_connection_and_wait()
        _LOGGER.debug("Turning off %s with dim %s", self.uuid, dim)
        await self.client.control_device(self.uuid, False, dim)

    async def _async_ensure_connection_and_wait(self) -> None:
        """Ensure connection and wait for device list."""
        _LOGGER.debug("Checking to make sure the connection is still available")
        _LOGGER.debug(
            "self.client.connection_manager.state.canceled=%s",
            self.client.connection_manager.state.canceled,
        )
        _LOGGER.debug(
            "self.client.connection_manager.state.connecting=%s",
            self.client.connection_manager.state.connecting,
        )
        _LOGGER.debug(
            "self.client.connection_manager.message_queue.qsize()=%s",
            self.client.connection_manager.message_queue.qsize(),
        )
        _LOGGER.debug(
            "self.client.connection_manager.tasks=%s",
            self.client.connection_manager.tasks,
        )
        _LOGGER.debug(
            "len(self.client.connection_manager.tasks)=%s",
            len(self.client.connection_manager.tasks),
        )
        if (
            # TODO:  Update (or finish updating) PyDeako to expose a way of listening for when the connection drops or is restored
            self.client.connection_manager is None
            or self.client.connection_manager.connection is None
            or not self.client.connection_manager.connection.is_connected()
            # Apparently connection.close() doesn't actually update the state so "is_connected()" will continue to be true even after an explicit close call
            # TODO:  Update PyDeako to update the state of the connection when it's closed
            or self.client.connection_manager.connection.socket is None
            or self.client.connection_manager.connection.socket.sock is None
            # PyDeako does not properly clear the cancellation state but cancellation will prevent new messages from being sent.  Until cancellation is fixed, reload everything if cancellation is detected
            # TODO:  Update PyDeako to properly deal with the cancellation state
            or self.client.connection_manager.state.canceled
        ):
            _LOGGER.error("The connection does not seem to be available anymore")
            # PyDeako's maintain_connection_worker() doesn't quite seem to work as desired.  Part of the problem may be due to the state management for the canceling state and the connecting state flags and how they're reset and interpreted.
            # If a lack of connection is deteced, reload the entier integration.  This will likely fail if it's due to a prolonged disconnection which should create a relatively clear signal in Home Assistant that something is wrong.  Additionally,
            # Home Assistant will automatically reload the integration periodically which will retry the connection
            await self.hass.config_entries.async_reload(
                # TODO:  Confirm that this is an appropriate method for acquiring the integration's ID
                self.registry_entry.config_entry_id
            )
            raise ConfigEntryNotReady("Detected a disconnected state")
        else:
            _LOGGER.debug("Connection appears to still be available")

    async def refresh_devices(self) -> None:
        """Refresh the device list."""
        if self.client.is_refreshing.cmpxchg_strong(
            expected=ATOMIC_BOOL_FALSE, desired=ATOMIC_BOOL_TRUE
        ).success:
            await self._async_ensure_connection_and_wait()
            _LOGGER.debug("Starting to refresh the devices with a 60 second wait")
            start = timer()
            # TODO:  Update PyDeako to somehow be able to call update_state after "finding" a device so that it goes beyond just storing in memory to actually notifying Home Assistant
            await self.client.find_devices(60)
            # I didn't realize that find_devices() only waits the first time.
            # TODO:  Update PyDeako to expose a legit interface for doing a refresh or at least knowing when the responses are finished
            # Yes, I could hack this by hijacking the incoming_json listener and forwarding calls back to the original one but hopefully I can figure something out that's clean PyDeako first

            time_used = timer() - start
            if time_used < 120:
                _LOGGER.debug(
                    "Waiting for the rest of the 20 seconds to elapse since only %.1f seconds were used",
                    time_used,
                )
                # For now, inject an artificial delay of about 20 seconds.  It seems to take a while to get all the data back so that should help serve to rate limit the refresh requests until proper waiting is implemented
                await asyncio.sleep(120 - time_used)
                # pass

            # TODO:  Think about thread safety here.  Not yet sure how that works in Python
            self.client.is_refreshing.store(ATOMIC_BOOL_FALSE)
            if self.client.is_additional_refresh_requested.cmpxchg_strong(
                expected=ATOMIC_BOOL_TRUE, desired=ATOMIC_BOOL_FALSE
            ).success:
                # Let's hold off on actually doing the extra refresh for now.  I don't feel like testing that yet
                # asyncio.ensure_future(self.refresh_devices(60))  # noqa: RUF006
                pass
        else:
            self.client.is_additional_refresh_requested.store(ATOMIC_BOOL_TRUE)
