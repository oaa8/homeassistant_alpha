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

CONNECTION_ID = "connection_id"

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
