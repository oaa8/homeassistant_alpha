"""The deako integration."""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_IP_ADDRESS, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady

from .const import (
    CONFIG_ENTRY_VERSION,
    DEFAULT_PORT,
    DOMAIN,
    LEGACY_TELNET_DELAY,
    PROBE_DATA,
)
from .probe import DeakoProber
from .pydeako.deako import Deako, FindDevicesError

_LOGGER: logging.Logger = logging.getLogger(__package__)

PLATFORMS: list[Platform] = [
    Platform.LIGHT,
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.BUTTON,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up deako from a config entry."""
    entry.async_on_unload(entry.add_update_listener(update_listener))

    await _initiate_connection(hass, entry)

    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Bring an older config entry onto the current shape.

    Version 1 stored the address in `data` when it came from the initial setup
    dialog and in `options` when it came from the options screen, so the same
    installation could hold two answers to "which switch?" -- and it also kept a
    telnet send delay that pydeako 0.6.0 made meaningless.

    Version 2 keeps the address in `data` only, and drops the delay. The entry
    is updated in place, so `entry_id` and every entity unique id survive: the
    lights keep their history, their dashboards and their automations.
    """
    if entry.version > CONFIG_ENTRY_VERSION:
        # Downgrades are not supported; refuse rather than mangle the entry.
        return False

    if entry.version == 1:
        # Options represent the most recent user edit, so they win where both
        # locations were populated.
        merged = {**dict(entry.data), **dict(entry.options)}
        merged.pop(LEGACY_TELNET_DELAY, None)

        data: dict = {}
        if merged.get(CONF_IP_ADDRESS) is not None:
            data[CONF_IP_ADDRESS] = merged[CONF_IP_ADDRESS]
            data[CONF_PORT] = merged.get(CONF_PORT) or DEFAULT_PORT
        else:
            # Nothing to carry over. Setup will report the missing address
            # rather than the migration failing, which would strand the entry
            # and take the entities' history with it.
            _LOGGER.warning(
                "Config entry %s has no hub address to migrate; the address "
                "has to be set in the integration's options",
                entry.entry_id,
            )

        hass.config_entries.async_update_entry(
            entry, data=data, options={}, version=CONFIG_ENTRY_VERSION
        )
        _LOGGER.info(
            "Migrated Deako config entry %s to version %i",
            entry.entry_id,
            CONFIG_ENTRY_VERSION,
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    prober = hass.data.get(PROBE_DATA, {}).get(entry.entry_id)
    if prober is not None:
        # Before the connection goes, not after: a pass in flight would
        # otherwise spend its remaining commands on a socket that is being
        # torn down, and every one of them would be counted against a device
        # for a fault that is ours.
        await prober.stop()

    connection = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if connection is not None:
        await connection.disconnect()

    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        hass.data.get(PROBE_DATA, {}).pop(entry.entry_id, None)

    return unload_ok


async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry so a changed address takes effect.

    The telnet server is exclusive -- a second connection to the same node
    hangs rather than replacing the first -- so the old connection has to be
    closed before the new one is opened. A reload does exactly that, in that
    order, and replaces the hand-rolled reconnect dance that used to compare
    the running connection's address against the configured one.
    """
    await hass.config_entries.async_reload(entry.entry_id)


def get_connection_address(entry: ConfigEntry) -> str | None:
    """Return the configured "host:port", or None if none is configured.

    The config entry is the *only* source of an address. There is no discovery
    fallback and no automatic selection of any kind (outcome O8): the house has
    three Deako nodes, one of them serving SmartThings, and binding to the wrong
    one takes that connection hostage. An address that cannot be reached has to
    fail loudly rather than send us hunting for another node.

    Version 1 entries could hold the address in `options` instead; they are
    normalised by async_migrate_entry before this is ever called, so there is
    one place to look.
    """
    ip_address = entry.data.get(CONF_IP_ADDRESS)
    if ip_address is None:
        return None

    return f"{ip_address}:{entry.data.get(CONF_PORT) or DEFAULT_PORT}"


def _address_provider(address: str) -> Callable[[], Awaitable[tuple[str, str]]]:
    """Wrap a fixed address in the provider pydeako 0.6.0 expects.

    0.6.0 asks for (address, name) -- matching what DeakoDiscoverer yields --
    where 0.3.1 returned a bare address string.
    """

    async def get_address() -> tuple[str, str]:
        return address, "configured"

    return get_address


async def _initiate_connection(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Connect to the configured hub and enumerate its devices."""
    address = get_connection_address(entry)
    if address is None:
        raise ConfigEntryError(
            "No Deako hub address is configured. Set the address of the switch "
            "to connect to in this integration's options."
        )

    connection = Deako(_address_provider(address))

    await connection.connect()
    if not connection.is_connected():
        # connect() never raises: on failure it leaves a retry task running and
        # returns, so the only honest way to ask is to check. Without this the
        # first symptom of a wrong or unreachable address is a device-list
        # timeout ten seconds later, which reads like a hub problem.
        await connection.disconnect()
        raise ConfigEntryNotReady(
            f"Cannot reach the Deako switch at {address}. Check that the "
            "address is right and that nothing else is connected to it."
        )

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
        raise ConfigEntryNotReady(
            f"The Deako switch at {address} reported no devices"
        )

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = connection

    # The probe is created before the platforms so the switch entity can find
    # it, and started only after they are up. That order is load-bearing: the
    # switch restores the last on/off answer in async_added_to_hass, and a
    # governor already running could otherwise fire a startup pass on a house
    # whose owner had turned the probe off.
    prober = DeakoProber(connection)
    hass.data.setdefault(PROBE_DATA, {})[entry.entry_id] = prober

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    prober.start()
