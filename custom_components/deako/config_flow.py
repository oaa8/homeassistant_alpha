"""Config flow for deako.

The address is a required, validated field, and it is the only source of an
address the integration has (outcome O8). Nothing here discovers anything: the
vendored discovery module stays in the tree for a future user-driven picker, but
no flow calls it, so no flow can bind to a node the user did not name.
"""

from __future__ import annotations

import ipaddress
import logging
import re
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_IP_ADDRESS, CONF_PORT
from homeassistant.core import HomeAssistant, callback

from .const import (
    CONFIG_ENTRY_VERSION,
    DEFAULT_IP_ADDRESS,
    DEFAULT_PORT,
    DOMAIN,
    NAME,
)

_LOGGER = logging.getLogger(__name__)

# Labels are 1-63 characters of letters, digits and hyphens, not starting or
# ending with a hyphen. Deliberately permissive about the whole name so a local
# ".local" or bare host name is accepted alongside an IP address.
_LABEL = r"(?!-)[A-Za-z0-9-]{1,63}(?<!-)"
_HOSTNAME = re.compile(rf"^{_LABEL}(\.{_LABEL})*\.?$")

ERROR_INVALID_HOST = "invalid_host"
ERROR_INVALID_PORT = "invalid_port"
ERROR_ALREADY_CONFIGURED = "already_configured"


def validate_host(value: Any) -> str:
    """Return the cleaned host, or raise ValueError explaining why not.

    An unconfigured or malformed address used to become the literal address
    "None:None" and then a ten-second connection timeout. Rejecting it at the
    point the user types it is the whole point of making the field required.
    """
    host = str(value or "").strip()
    if not host:
        raise ValueError("an address is required")

    # A pasted "192.168.86.46:23" or "http://..." would otherwise sail through
    # and be concatenated with the port into nonsense. IPv6 literals are
    # rejected by the same rule, and that is honest rather than incidental:
    # the library connects with AF_INET and parses its address by splitting on
    # ":", so an IPv6 address cannot reach a hub however it is entered.
    if any(character in host for character in " \t/\\@"):
        raise ValueError("an address cannot contain spaces, slashes or '@'")
    if ":" in host:
        raise ValueError(
            "enter an IPv4 address or host name only; the port has its own "
            "field, and IPv6 is not supported by the hub connection"
        )

    try:
        ipaddress.IPv4Address(host)
    except ValueError:
        if not _HOSTNAME.match(host):
            raise ValueError(
                "not an IPv4 address or a host name"
            ) from None

    return host


def validate_port(value: Any) -> int:
    """Return the port as an int, or raise ValueError explaining why not."""
    try:
        port = int(value)
    except (TypeError, ValueError):
        raise ValueError("a port has to be a whole number") from None

    if not 1 <= port <= 65535:
        raise ValueError("a port has to be between 1 and 65535")

    return port


def _validate(user_input: dict[str, Any]) -> tuple[str, int, dict[str, str]]:
    """Validate a submitted form, returning (host, port, errors)."""
    errors: dict[str, str] = {}

    try:
        host = validate_host(user_input.get(CONF_IP_ADDRESS))
    except ValueError as exc:
        _LOGGER.debug("Rejected hub address: %s", exc)
        host = ""
        errors[CONF_IP_ADDRESS] = ERROR_INVALID_HOST

    try:
        port = validate_port(user_input.get(CONF_PORT, DEFAULT_PORT))
    except ValueError as exc:
        _LOGGER.debug("Rejected hub port: %s", exc)
        port = DEFAULT_PORT
        errors[CONF_PORT] = ERROR_INVALID_PORT

    return host, port, errors


def _address_already_configured(
    hass: HomeAssistant, host: str, port: int, ignore_entry_id: str | None = None
) -> bool:
    """Report whether another config entry already holds this address.

    Deako's telnet server is exclusive: a second connection to the same node
    hangs rather than replacing the first, so two entries pointing at one switch
    would have this integration blocking itself.
    """
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.entry_id == ignore_entry_id:
            continue
        # A version 1 entry that has not been migrated yet still keeps its
        # address in options.
        existing = {**dict(entry.data), **dict(entry.options)}
        if existing.get(CONF_IP_ADDRESS) != host:
            continue
        if (existing.get(CONF_PORT) or DEFAULT_PORT) == port:
            return True

    return False


def _schema(host: str, port: int) -> vol.Schema:
    """Build the address form, prefilled with the values shown to the user."""
    return vol.Schema(
        {
            vol.Required(CONF_IP_ADDRESS, default=host): str,
            vol.Required(CONF_PORT, default=port): vol.Coerce(int),
        }
    )


class DeakoOptionsFlowHandler(config_entries.OptionsFlow):
    """Edit the configured address after setup.

    Home Assistant 2025.12 made `OptionsFlow.config_entry` read-only, so the
    old constructor -- which assigned to it -- raises on any attempt to open
    this screen. The entry is supplied by the flow manager; nothing has to be
    stored here, which is why there is no __init__ at all.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Show and handle the address form."""
        entry = self.config_entry
        host = entry.data.get(CONF_IP_ADDRESS, DEFAULT_IP_ADDRESS)
        port = entry.data.get(CONF_PORT) or DEFAULT_PORT
        errors: dict[str, str] = {}

        if user_input is not None:
            host, port, errors = _validate(user_input)

            if not errors and _address_already_configured(
                self.hass, host, port, ignore_entry_id=entry.entry_id
            ):
                errors[CONF_IP_ADDRESS] = ERROR_ALREADY_CONFIGURED

            if not errors:
                # The address lives in `data`, in one place. Updating it fires
                # the entry's update listener, which reloads the integration so
                # the old connection is closed before the new one is opened.
                self.hass.config_entries.async_update_entry(
                    entry, data={CONF_IP_ADDRESS: host, CONF_PORT: port}
                )
                return self.async_create_entry(title="", data={})

            host = user_input.get(CONF_IP_ADDRESS, host)

        return self.async_show_form(
            step_id="init", data_schema=_schema(host, port), errors=errors
        )


class DeakoFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Deako."""

    VERSION = CONFIG_ENTRY_VERSION

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the user step of the config flow."""
        host = DEFAULT_IP_ADDRESS
        port = DEFAULT_PORT
        errors: dict[str, str] = {}

        if user_input is not None:
            host, port, errors = _validate(user_input)

            if not errors and _address_already_configured(self.hass, host, port):
                return self.async_abort(reason=ERROR_ALREADY_CONFIGURED)

            if not errors:
                return self.async_create_entry(
                    title=NAME, data={CONF_IP_ADDRESS: host, CONF_PORT: port}
                )

            host = user_input.get(CONF_IP_ADDRESS, host)

        return self.async_show_form(
            step_id="user", data_schema=_schema(host, port), errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> DeakoOptionsFlowHandler:
        """Get the options flow for this handler."""
        return DeakoOptionsFlowHandler()
