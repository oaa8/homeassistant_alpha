"""Constants for Deako."""
# Base component constants
NAME = "Deako"
DOMAIN = "deako"
DOMAIN_DATA = f"{DOMAIN}_data"

# Icons
ICON = "mdi:format-quote-close"

# Platforms
LIGHT = "light"
PLATFORMS = [LIGHT]

# The hub's own device, which the four hub-level diagnostic entities hang off
# (wayfinder #23). Per-node diagnostics deliberately do not live here: the node
# status sensor sits on the same device as its light, so "which switch, and
# why" is answerable in one place rather than by cross-referencing.
HUB_DEVICE_NAME = "Deako hub"
HUB_DEVICE_MODEL = "Local integration"
MANUFACTURER = "Deako"

# Node status readings, in the order of how much they explain. `unreachable`
# is command-triggered and cannot be discovered unasked; see the entity's own
# documentation and wayfinder #13.
NODE_STATUS_ONLINE = "online"
NODE_STATUS_UNREACHABLE = "unreachable"
NODE_STATUS_HUB_DISCONNECTED = "hub_disconnected"
NODE_STATUS_OPTIONS = [
    NODE_STATUS_ONLINE,
    NODE_STATUS_UNREACHABLE,
    NODE_STATUS_HUB_DISCONNECTED,
]

CONNECTION_ID = "connection_id"

# Where the active reachability probe hangs off hass.data (wayfinder #26).
# A key of its own rather than a slot inside the domain's entry map, which
# holds nothing but entry_id -> connection and is read that way by four
# platforms.
PROBE_DATA = f"{DOMAIN}_probe"

# What the probe last wrote to a switch. `unknown` until it has written
# anything, which is a different fact from having written `off` -- and the
# difference matters, because this pair exists to attribute a light that moved
# with nobody asking (wayfinder #25).
PROBE_VALUE_ON = "on"
PROBE_VALUE_OFF = "off"
PROBE_VALUE_OPTIONS = [PROBE_VALUE_ON, PROBE_VALUE_OFF]

# The address of the hub is a safety control, not a convenience: the house has
# three Deako nodes, the telnet server is exclusive, and one of the other nodes
# serves SmartThings. The configured address is the only source of an address --
# nothing discovers, and nothing falls back. The default is prefilled because
# this integration is published only so HACS can reach it, not to serve others.
DEFAULT_IP_ADDRESS = "192.168.86.46"
DEFAULT_PORT = 23

# The config entry shape. Version 1 scattered the address across `data` and
# `options` depending on whether the initial dialog or the options screen was
# used, and carried a telnet send delay that 0.6.0 made meaningless.
CONFIG_ENTRY_VERSION = 2

# Dropped by the migration to version 2. pydeako 0.6.0 removed the send queue
# this used to space out, so the setting could only ever have done nothing.
LEGACY_TELNET_DELAY = "telnet_message_receive_delay"
