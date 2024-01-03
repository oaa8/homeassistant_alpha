"""The deako integration."""
from __future__ import annotations

import logging

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

    connection = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if connection is not None:
        hass.data[DOMAIN].pop(entry.entry_id)
        await connection.disconnect()

    await _initiate_connection(hass, entry)


async def _initiate_connection(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Initiate Deako connection."""
    hass_data = hass.data.setdefault(DOMAIN, {})
    if hass_data is None or not isinstance(hass_data, dict):
        hass_data = {}
        hass.data[DOMAIN] = hass_data

    if entry.options is not None:

        async def get_address_method() -> str:
            return (
                f"{entry.options.get(CONF_IP_ADDRESS)}:{entry.options.get(CONF_PORT)}"
            )

        get_address = get_address_method

    elif entry.data is not None:

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

    connection = Deako(get_address)
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
    hass.data[DOMAIN][entry.entry_id] = connection

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
