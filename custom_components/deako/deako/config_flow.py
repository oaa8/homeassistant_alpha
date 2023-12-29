"""Config flow for deako."""
from typing import Any

from homeassistant.components.dnsip.const import CONF_IPV4
from homeassistant.components.roborock.const import CONF_ENTRY_CODE
from homeassistant.const import CONF_PORT
from homeassistant.data_entry_flow import FlowResult
from pydeako.discover import DeakoDiscoverer, DevicesNotFoundException

from homeassistant import config_entries
from homeassistant.components import zeroconf
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_entry_flow

from .const import DOMAIN, NAME


class DeakoFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Deako."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    def __init__(self) -> None:
        """Initialize the config flow."""

    async def async_step_init(
            self, _user_input: dict[str, Any] | None = None
    ) -> FlowResult:  # pylint: disable=unused-argument
        """Manage the options."""
        return await self.async_step_user()

    async def async_step_user(
            self, _user_input: dict[str, Any] | None = None
    , CONF_PORT='23') -> FlowResult:
        """Handle a flow initialized by the user."""
        return self.async_show_menu(
            step_id="user", menu_options=[CONF_IPV4, CONF_PORT]
        )


class DeakoOptionsFlowHandler(config_entries.OptionsFlow):
    """Deako config flow options handler."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize HACS options flow."""
        self.config_entry = config_entry
        self.options = dict(config_entry.options)
        # self.discovered_devices = None

    async def async_step_init(
            self, _user_input: dict[str, Any] | None = None
    ) -> FlowResult:  # pylint: disable=unused-argument
        """Manage the options."""
        return await self.async_step_user()

    async def async_step_user(
            self, _user_input: dict[str, Any] | None = None
    , CONF_PORT='23') -> FlowResult:
        """Handle a flow initialized by the user."""
        return self.async_show_menu(
            step_id="user", menu_options=[CONF_IPV4, CONF_PORT]
        )

    async def _update_options(self) -> FlowResult:
        """Update config entry options."""
        return self.async_create_entry(title="", data=self.options)

async def _async_has_devices(hass: HomeAssistant) -> bool:
    """Return if there are devices that can be discovered."""
    _zc = await zeroconf.async_get_instance(hass)
    discoverer = DeakoDiscoverer(_zc)

    try:
        await discoverer.get_address()
        # address exists, there's at least one device
        return True

    except DevicesNotFoundException:
        return False


config_entry_flow.register_discovery_flow(DOMAIN, NAME, _async_has_devices)
