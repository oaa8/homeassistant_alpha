"""The deako integration."""
from __future__ import annotations

import asyncio
import logging
from typing import Callable

import atomics
import pydeako
from pydeako.deako import Deako, DeviceListTimeout, FindDevicesTimeout
from pydeako.discover import DeakoDiscoverer

from homeassistant.components import zeroconf
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_IP_ADDRESS, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import DISCOVERER_ID, DOMAIN

_LOGGER: logging.Logger = logging.getLogger(__package__)

PLATFORMS: list[Platform] = [Platform.LIGHT]

ATOMIC_BOOL_FALSE = 0
ATOMIC_BOOL_TRUE = 1

TELNET_MESSAGE_DELAY = "telnet_message_receive_delay"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up deako from a config entry."""
    entry.async_on_unload(entry.add_update_listener(update_listener))
    # Hack to make help avoid calling a good connection a bad one
    pydeako.deako._deako.DEVICE_FOUND_POLLING_INTERVAL_S = 60

    await _initiate_connection(hass, entry)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if hass.data.get(DOMAIN, {}).get(entry.entry_id) is not None:
        await hass.data[DOMAIN][entry.entry_id].disconnect()

    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update Deako listeners."""

    set_delay_options_if_needed(hass, entry)
    preset_adddress_or_none = await get_connection_address(hass, entry)

    connection = hass.data.get(DOMAIN, {}).get(entry.entry_id)

    should_reconnect = False
    if connection is not None:
        if (
            (
                connection.__is_address_hardcoded
                and (
                    preset_adddress_or_none is None
                    or connection.__address != await preset_adddress_or_none()
                )
            )
            or not connection.__is_address_hardcoded
            and preset_adddress_or_none is not None
        ):
            should_reconnect = True
    else:
        should_reconnect = True

    if should_reconnect:
        if connection is not None:
            hass.data[DOMAIN].pop(entry.entry_id)
            await connection.disconnect()
        await _initiate_connection(hass, entry)


def set_delay_options_if_needed(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Set the options if needed."""

    telnet_message_delay = None
    if (
        entry.options is not None
        and entry.options.get(TELNET_MESSAGE_DELAY) is not None
    ):
        telnet_message_delay = entry.options.get(TELNET_MESSAGE_DELAY)
    elif entry.data is not None and entry.data.get(TELNET_MESSAGE_DELAY) is not None:
        telnet_message_delay = entry.data.get(TELNET_MESSAGE_DELAY)

    if telnet_message_delay is not None:
        value = float(telnet_message_delay)
        if value < 1e-5:
            _LOGGER.info(
                "Requested telnet delay is %s which is close to zero.  Updating it to zero",
                value,
            )
            value = 0
        _LOGGER.info(
            "Changing telnet message delay from %s to %s",
            pydeako.deako._manager.WORKER_WAIT_S,
            value,
        )
        pydeako.deako._manager.WORKER_WAIT_S = value


async def get_connection_address(
    hass: HomeAssistant, entry: ConfigEntry
) -> Callable[[], str] or None:
    """Get the connection address."""

    get_address = None

    if entry.options is not None:

        async def get_address_method() -> str:
            return (
                f"{entry.options.get(CONF_IP_ADDRESS)}:{entry.options.get(CONF_PORT)}"
            )

        get_address = get_address_method
        _LOGGER.info("Test: %s", await get_address_method())
        _LOGGER.info("Test: %s", await get_address())
    elif entry.data is not None:

        async def get_address_method() -> str:
            return f"{entry.data.get(CONF_IP_ADDRESS)}:{entry.data.get(CONF_PORT)}"

        get_address = get_address_method
        _LOGGER.info("Test: %s", await get_address_method())
        _LOGGER.info("Test: %s", await get_address())
    return get_address


async def _initiate_connection(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Initiate Deako connection."""
    hass_data = hass.data.setdefault(DOMAIN, {})
    if hass_data is None or not isinstance(hass_data, dict):
        hass_data = {}
        hass.data[DOMAIN] = hass_data

    telnet_message_delay = None
    is_address_hardcoded = False
    if entry.options is not None:
        is_address_hardcoded = True

        async def get_address_method() -> str:
            return (
                f"{entry.options.get(CONF_IP_ADDRESS)}:{entry.options.get(CONF_PORT)}"
            )

        get_address = get_address_method
        if entry.options.get(TELNET_MESSAGE_DELAY) is not None:
            telnet_message_delay = entry.options.get(TELNET_MESSAGE_DELAY)
    elif entry.data is not None:
        is_address_hardcoded = True
        if entry.data.get(TELNET_MESSAGE_DELAY) is not None:
            telnet_message_delay = entry.data.get(TELNET_MESSAGE_DELAY)

        async def get_address_method() -> str:
            return f"{entry.data.get(CONF_IP_ADDRESS)}:{entry.data.get(CONF_PORT)}"

        get_address = get_address_method
    else:
        if hass_data.get(DISCOVERER_ID) is None:
            _zc = await zeroconf.async_get_instance(hass)
            _dd = DeakoDiscoverer(_zc)
            hass_data[DISCOVERER_ID] = _dd

        discoverer: DeakoDiscoverer = hass_data.get(DISCOVERER_ID)
        get_address = discoverer.get_address

    set_delay_options_if_needed(hass, entry)

    connection = Deako(get_address)

    if is_address_hardcoded:
        connection.__is_address_hardcoded = True
        connection.__address = await get_address()
    await connection.connect()
    try:
        await connection.find_devices()
    except FindDevicesTimeout as exc:
        _LOGGER.warning("No devices expected")
        await connection.disconnect()
        raise ConfigEntryNotReady(exc) from exc
    except DeviceListTimeout as exc:
        _LOGGER.warning("No devices expected")
        await connection.disconnect()
        raise ConfigEntryNotReady(exc) from exc

    devices = connection.get_devices()
    if len(devices) == 0:
        await connection.disconnect()
        raise ConfigEntryNotReady(devices)

    # Quick hack to get manage refreshes
    connection.is_refreshing = atomics.atomic(1, atomics.INT)
    connection.is_refreshing.store(ATOMIC_BOOL_FALSE)
    connection.is_additional_refresh_requested = atomics.atomic(1, atomics.INT)
    connection.is_additional_refresh_requested.store(ATOMIC_BOOL_FALSE)
    overwrite_parse_data_implementation(hass, entry, connection)
    hass.data[DOMAIN][entry.entry_id] = connection

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)


def overwrite_parse_data_implementation(
    hass: HomeAssistant, entry: ConfigEntry, connection: Deako
) -> None:
    """Overwrite the parse_data implementation."""

    def new_parse_data(self, data: bytes) -> None:
        """Replacement parse_data method that replaces self.message_buffer with an empty string if it only contains whitespace before calling the original implementation."""

        if (
            (self.message_buffer is not None)
            and (self.message_buffer.strip() == "")
            and len(self.message_buffer) > 0
        ):
            _LOGGER.info(
                "Replacing message buffer with empty string after seeing %s whitespace characters",
                len(self.message_buffer),
            )
            self.message_buffer = ""

        raw_string = data.decode("utf-8")
        if (raw_string is not None) and (raw_string.strip() == ""):
            if self.empty_message_counter is None:
                self.empty_message_counter = 0
            self.empty_message_counter += 1
            if self.empty_message_counter > 1000:
                _LOGGER.error(
                    "Received %s empty messages in a row.  Reloading integration to reconnect",
                    self.empty_message_counter,
                )
                asyncio.ensure_future(hass.config_entries.async_reload(entry.entry_id))  # noqa: RUF006
        else:
            self.empty_message_counter = 0
        pydeako.deako.utils._connection._Connection.__old_parse_data(self, data)

    _LOGGER.info(
        "Reassigning _Connection's implementation of parse_data to protect against streams of whitespace"
    )

    # This is to protect against what appeared to be a stream of whitespace characters that took the entire home assistant instance down
    # An additional protective method would be to reconnect once a certain number of whitespace characters are seen in a row with an empty buffer.
    if not hasattr(pydeako.deako.utils._connection._Connection, "__old_parse_data"):
        pydeako.deako.utils._connection._Connection.__old_parse_data = (
            pydeako.deako.utils._connection._Connection.parse_data
        )
        pydeako.deako.utils._connection._Connection.parse_data = new_parse_data
