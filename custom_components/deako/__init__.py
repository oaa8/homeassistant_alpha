"""The deako integration."""
from __future__ import annotations

import logging
from collections.abc import Awaitable
from typing import Callable

from homeassistant.components import zeroconf
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_IP_ADDRESS, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import DISCOVERER_ID, DOMAIN
from .pydeako.deako import Deako, FindDevicesError
from .pydeako.discover import DeakoDiscoverer

_LOGGER: logging.Logger = logging.getLogger(__package__)

PLATFORMS: list[Platform] = [Platform.LIGHT]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up deako from a config entry."""
    entry.async_on_unload(entry.add_update_listener(update_listener))

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

    preset_adddress_or_none = await get_connection_address(hass, entry)

    connection = hass.data.get(DOMAIN, {}).get(entry.entry_id)

    should_reconnect = False
    if connection is not None:
        if (
            (
                connection.__is_address_hardcoded
                and (
                    preset_adddress_or_none is None
                    or connection.__address != (await preset_adddress_or_none())[0]
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


async def get_connection_address(
    hass: HomeAssistant, entry: ConfigEntry
) -> Callable[[], Awaitable[tuple[str, str]]] | None:
    """Resolve the manually configured hub address, or None to use discovery.

    Home Assistant always wraps a config entry's options and data in a
    MappingProxyType, so neither is ever None -- even when the user configured
    nothing. Presence therefore has to be tested on CONF_IP_ADDRESS itself;
    testing the mapping would always succeed and yield the address "None:None".

    pydeako 0.6.0 expects the provider to return (address, name), matching what
    DeakoDiscoverer yields; 0.3.1 returned a bare address string.
    """
    for source in (entry.options, entry.data):
        ip_address = source.get(CONF_IP_ADDRESS) if source else None
        if ip_address is None:
            continue

        address = f"{ip_address}:{source.get(CONF_PORT)}"

        async def get_address_method(address: str = address) -> tuple[str, str]:
            return address, "configured"

        return get_address_method

    return None


async def _initiate_connection(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Initiate Deako connection."""
    hass_data = hass.data.setdefault(DOMAIN, {})
    if hass_data is None or not isinstance(hass_data, dict):
        hass_data = {}
        hass.data[DOMAIN] = hass_data

    is_address_hardcoded = False
    get_address = await get_connection_address(hass, entry)

    if get_address is not None:
        is_address_hardcoded = True
    else:
        if hass_data.get(DISCOVERER_ID) is None:
            _zc = await zeroconf.async_get_instance(hass)
            _dd = DeakoDiscoverer(_zc)
            hass_data[DISCOVERER_ID] = _dd

        discoverer: DeakoDiscoverer = hass_data.get(DISCOVERER_ID)
        get_address = discoverer.get_address

    connection = Deako(get_address)

    if is_address_hardcoded:
        connection.__is_address_hardcoded = True
        connection.__address = (await get_address())[0]
    await connection.connect()
    try:
        await connection.find_devices()
    except FindDevicesError as exc:
        # 0.6.0 collapsed FindDevicesTimeout and DeviceListTimeout into this
        # one error. It now only fires when the hub never answered the device
        # list request at all -- a partial enumeration is no longer fatal, see
        # DEVIATION (O1) in the vendored find_devices().
        _LOGGER.warning("Could not enumerate devices: %s", exc)
        await connection.disconnect()
        raise ConfigEntryNotReady(exc) from exc

    devices = connection.get_devices()
    if len(devices) == 0:
        await connection.disconnect()
        raise ConfigEntryNotReady(devices)

    hass.data[DOMAIN][entry.entry_id] = connection

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
