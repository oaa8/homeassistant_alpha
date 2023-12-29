"""Config flow for deako."""

import logging
from typing import Any

from pydeako.discover import DeakoDiscoverer, DevicesNotFoundException
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import zeroconf
from homeassistant.const import CONF_IP_ADDRESS, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN, NAME

_LOGGER = logging.getLogger(__name__)


class DeakoOptionsFlowHandler(config_entries.OptionsFlow):
    """Deako config flow options handler."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize HACS options flow."""
        self.config_entry = config_entry
        self.options = dict(config_entry.options)
        # self.discovered_devices = None

    # async def async_step_init(
    #         self, _user_input: dict[str, Any] | None = None, errors: dict[str, str] = None
    # ) -> FlowResult:  # pylint: disable=unused-argument
    #     """Manage the options."""
    #     return await self.async_step_user(_user_input, errors)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None, errors: dict[str, str] = None
    ) -> FlowResult:
        """Handle a flow initialized by the user."""
        # return self.async_show_menu(
        #     step_id="user", menu_options=[CONF_IPV4, CONF_PORT]
        # )

        if user_input is not None:
            return self.async_create_entry(
                title="Deako",
                data=user_input,
            )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_IP_ADDRESS,
                        default=self.config_entry.options.get(
                            CONF_IP_ADDRESS, "192.168.86.46"
                        ),
                    ): str,
                    vol.Required(
                        CONF_PORT, default=self.config_entry.options.get(CONF_PORT, 23)
                    ): int,
                }
            ),
            errors=errors,
        )


class DeakoFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Deako."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None, errors: dict[str, str] = None
    ) -> FlowResult:
        """Handle the user step of the config flow."""

        if user_input is not None:
            return self.async_create_entry(
                title="Deako",
                data=user_input,
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_IP_ADDRESS, default="192.168.86.46"): str,
                    vol.Required(CONF_PORT, default=23): int,
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> DeakoOptionsFlowHandler:
        """Get the options flow for this handler."""
        return DeakoOptionsFlowHandler(config_entry)


# async def _async_has_devices(hass: HomeAssistant) -> bool:
#     """Return if there are devices that can be discovered."""
#     _zc = await zeroconf.async_get_instance(hass)
#     discoverer = DeakoDiscoverer(_zc)

#     _LOGGER.error("Deako config_flow.py _async_has_devices")
#     try:
#         _LOGGER.error("Deako config_flow.py _async_has_devices try")
#         await discoverer.get_address()
#         _LOGGER.error("Deako config_flow.py _async_has_devices try await")
#         # address exists, there's at least one device
#         return True

#     except DevicesNotFoundException:
#         _LOGGER.error("Deako config_flow.py _async_has_devices except")
#         return False


# config_entry_flow.register_discovery_flow(DOMAIN, NAME, _async_has_devices)
