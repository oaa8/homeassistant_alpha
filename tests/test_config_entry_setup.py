"""Tests for Deako config entry setup: address, validation and migration.

Module: tests/test_config_entry_setup.py
Author: GitHub Copilot
Purpose: Guards the three things the integration's setup layer has to get
    right, all of which have been wrong at some point in this repo's history:

    1. The configured address is the *only* source of an address. There is no
       discovery fallback, so a wrong or missing address can never turn into a
       connection to some other Deako node. The house has three nodes, the
       telnet server is exclusive, and one of the others serves SmartThings.
    2. The address field is validated at the point the user types it, rather
       than becoming a ten-second connection timeout, or the literal address
       "None:None" as it did when `if entry.options is not None` was always
       true and the address was read from the wrong mapping.
    3. A version 1 config entry migrates in place -- the address consolidated
       into `data`, the dead telnet delay dropped -- so entities, history and
       dashboards survive, because `entry_id` never changes.

Key assumptions:
    - Home Assistant is not installed in this test environment, so the code
      under test is extracted from source with `ast` and executed against
      stubs rather than imported. This keeps the suite runnable without the
      full HA dependency tree while still exercising the real, shipped code.
    - `MappingProxyType({})` faithfully reproduces HA's empty-options case; see
      homeassistant/config_entries.py (`self.options = MappingProxyType(options or {})`).
"""

from __future__ import annotations

import ast
import ipaddress
import re
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
INTEGRATION_DIR = REPO_ROOT / "custom_components" / "deako"
INTEGRATION_INIT = INTEGRATION_DIR / "__init__.py"
INTEGRATION_CONFIG_FLOW = INTEGRATION_DIR / "config_flow.py"

DEFAULT_PORT = 23
LEGACY_TELNET_DELAY = "telnet_message_receive_delay"


def _extract(source_path: Path, names: set[str], namespace: dict) -> dict:
    """Execute the named top-level definitions from a module, and nothing else.

    Importing the integration would pull in homeassistant, which is not a
    dependency of this suite. Extracting by AST runs the real shipped source
    without its imports, so the tests cannot drift from the code they guard.
    """
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    wanted: list[ast.stmt] = []

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in names:
                wanted.append(node)
        elif isinstance(node, ast.Assign):
            targets = {t.id for t in node.targets if isinstance(t, ast.Name)}
            if targets & names:
                wanted.append(node)

    found = {
        node.name if hasattr(node, "name") else node.targets[0].id
        for node in wanted
    }
    missing = names - found
    assert not missing, f"{source_path.name} no longer defines {sorted(missing)}"

    exec(  # noqa: S102 - executing first-party source under test, not user input
        compile(ast.Module(body=wanted, type_ignores=[]), str(source_path), "exec"),
        namespace,
    )
    return namespace


_INIT_NS = _extract(
    INTEGRATION_INIT,
    {"get_connection_address", "async_migrate_entry"},
    {
        "CONF_IP_ADDRESS": "ip_address",
        "CONF_PORT": "port",
        "DEFAULT_PORT": DEFAULT_PORT,
        "LEGACY_TELNET_DELAY": LEGACY_TELNET_DELAY,
        "CONFIG_ENTRY_VERSION": 2,
        "_LOGGER": SimpleNamespace(
            info=lambda *a, **k: None,
            warning=lambda *a, **k: None,
            debug=lambda *a, **k: None,
        ),
        "ConfigEntry": object,
        "HomeAssistant": object,
    },
)
get_connection_address = _INIT_NS["get_connection_address"]
async_migrate_entry = _INIT_NS["async_migrate_entry"]

_FLOW_NS = _extract(
    INTEGRATION_CONFIG_FLOW,
    {"_LABEL", "_HOSTNAME", "validate_host", "validate_port",
     "_address_already_configured"},
    {
        "ipaddress": ipaddress,
        "re": re,
        "CONF_IP_ADDRESS": "ip_address",
        "CONF_PORT": "port",
        "DEFAULT_PORT": DEFAULT_PORT,
        "DOMAIN": "deako",
    },
)
validate_host = _FLOW_NS["validate_host"]
validate_port = _FLOW_NS["validate_port"]
address_already_configured = _FLOW_NS["_address_already_configured"]


def make_entry(
    data: dict | None = None, options: dict | None = None, version: int = 2
):
    """Build a config entry stub using HA's real MappingProxyType semantics."""
    return SimpleNamespace(
        entry_id="entry-1",
        version=version,
        data=MappingProxyType(data or {}),
        options=MappingProxyType(options or {}),
    )


class _ConfigEntries:
    """The slice of hass.config_entries the code under test touches."""

    def __init__(self, entries: list | None = None) -> None:
        self._entries = entries or []

    def async_entries(self, _domain):
        return self._entries

    def async_update_entry(self, entry, **changes):
        for key, value in changes.items():
            if key in ("data", "options"):
                value = MappingProxyType(dict(value))
            setattr(entry, key, value)
        return True


def make_hass(entries: list | None = None):
    """Build a hass stub exposing only config_entries."""
    return SimpleNamespace(config_entries=_ConfigEntries(entries))


# ---------------------------------------------------------------------------
# The configured address is the only source of an address.
# ---------------------------------------------------------------------------


def test_address_comes_from_entry_data():
    """The address the user configured is the address that gets used."""
    entry = make_entry(data={"ip_address": "10.0.0.5", "port": 23})
    assert get_connection_address(entry) == "10.0.0.5:23"


def test_unconfigured_entry_yields_no_address():
    """No address configured must mean no address -- never a fallback.

    The regression this guards is twofold: `if entry.options is not None` was
    always true, so an unconfigured entry produced the literal address
    "None:None"; and the branch it guarded went looking for a node over mDNS,
    which could bind to the switch SmartThings is using.
    """
    assert get_connection_address(make_entry()) is None, (
        "An unconfigured entry must yield None so setup reports a missing "
        "address, rather than producing an address or discovering a node."
    )


def test_options_are_not_a_source_of_address():
    """After migration the address lives in one place, and options is not it."""
    entry = make_entry(options={"ip_address": "1.2.3.4", "port": 8023})
    assert get_connection_address(entry) is None, (
        "Reading options as well as data is what allowed one installation to "
        "hold two different answers to 'which switch?'"
    )


def test_missing_port_falls_back_to_the_default():
    """An address without a port is still usable; the port has a known default."""
    entry = make_entry(data={"ip_address": "10.0.0.5"})
    assert get_connection_address(entry) == "10.0.0.5:23"


# ---------------------------------------------------------------------------
# Address validation, at the point the user types it.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "host",
    ["192.168.86.46", "10.0.0.5", "deako-hub", "deako.local", "DEAKO.local."],
)
def test_valid_hosts_are_accepted(host):
    """IPv4 addresses and host names both name a switch unambiguously."""
    assert validate_host(host) == host


def test_host_is_stripped():
    """A pasted address usually arrives with whitespace around it."""
    assert validate_host("  192.168.86.46 ") == "192.168.86.46"


@pytest.mark.parametrize(
    "host",
    [
        None,
        "",
        "   ",
        "192.168.86.46:23",  # the port has its own field
        "fd00::1",  # AF_INET only, and "host:port" cannot express it
        "http://192.168.86.46",
        "192.168.86.46/hub",
        "192 168 86 46",
        "-nope",
        "no_underscores",
    ],
)
def test_invalid_hosts_are_rejected(host):
    """A malformed address must fail in the form, not ten seconds into setup."""
    with pytest.raises(ValueError):
        validate_host(host)


@pytest.mark.parametrize("port,expected", [(23, 23), ("23", 23), (8023, 8023)])
def test_valid_ports_are_accepted(port, expected):
    """The port arrives from the form as either an int or a string."""
    assert validate_port(port) == expected


@pytest.mark.parametrize("port", [0, -1, 65536, "twenty-three", None, ""])
def test_invalid_ports_are_rejected(port):
    """A port outside the usable range cannot name a switch."""
    with pytest.raises(ValueError):
        validate_port(port)


# ---------------------------------------------------------------------------
# Two entries must not fight over one switch.
# ---------------------------------------------------------------------------


def test_duplicate_address_is_detected():
    """Deako's telnet server is exclusive, so a second entry would self-block."""
    hass = make_hass([make_entry(data={"ip_address": "10.0.0.5", "port": 23})])
    assert address_already_configured(hass, "10.0.0.5", 23) is True


def test_duplicate_check_sees_an_unmigrated_entry():
    """A version 1 entry still keeps its address in options until it migrates."""
    hass = make_hass(
        [make_entry(options={"ip_address": "10.0.0.5", "port": 23}, version=1)]
    )
    assert address_already_configured(hass, "10.0.0.5", 23) is True


def test_a_different_node_is_not_a_duplicate():
    """Different nodes are the normal case; only the same one is a conflict."""
    hass = make_hass([make_entry(data={"ip_address": "10.0.0.5", "port": 23})])
    assert address_already_configured(hass, "10.0.0.6", 23) is False


def test_editing_an_entry_does_not_conflict_with_itself():
    """Re-saving the options screen without changing the address must work."""
    entry = make_entry(data={"ip_address": "10.0.0.5", "port": 23})
    hass = make_hass([entry])
    assert (
        address_already_configured(
            hass, "10.0.0.5", 23, ignore_entry_id=entry.entry_id
        )
        is False
    )


# ---------------------------------------------------------------------------
# Migration: consolidate the address, drop the dead delay, keep the entry.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_migration_moves_the_address_from_options_into_data():
    """An address edited on the old options screen has to survive the upgrade."""
    entry = make_entry(
        data={"ip_address": "2.2.2.2", "port": 2},
        options={"ip_address": "1.1.1.1", "port": 1},
        version=1,
    )
    hass = make_hass([entry])

    assert await async_migrate_entry(hass, entry) is True
    assert dict(entry.data) == {"ip_address": "1.1.1.1", "port": 1}, (
        "Options held the most recent user edit, so they must win."
    )
    assert dict(entry.options) == {}
    assert entry.version == 2


@pytest.mark.asyncio
async def test_migration_keeps_an_address_that_only_data_holds():
    """The common case: configured once, at setup, never edited afterwards."""
    entry = make_entry(data={"ip_address": "9.9.9.9", "port": 23}, version=1)
    hass = make_hass([entry])

    assert await async_migrate_entry(hass, entry) is True
    assert dict(entry.data) == {"ip_address": "9.9.9.9", "port": 23}


@pytest.mark.asyncio
async def test_migration_drops_the_telnet_delay():
    """0.6.0 removed the send queue, so the setting could only mislead."""
    entry = make_entry(
        data={"ip_address": "9.9.9.9", "port": 23, LEGACY_TELNET_DELAY: 0.1},
        options={LEGACY_TELNET_DELAY: 0.5},
        version=1,
    )
    hass = make_hass([entry])

    assert await async_migrate_entry(hass, entry) is True
    assert LEGACY_TELNET_DELAY not in entry.data
    assert LEGACY_TELNET_DELAY not in entry.options
    assert dict(entry.data) == {"ip_address": "9.9.9.9", "port": 23}


@pytest.mark.asyncio
async def test_migration_survives_an_entry_with_no_address():
    """A hopeless entry must still migrate, so its entities keep their history.

    Failing the migration would strand the config entry; setup reports the
    missing address instead, and the user fixes it in the options screen.
    """
    entry = make_entry(data={LEGACY_TELNET_DELAY: 0.1}, version=1)
    hass = make_hass([entry])

    assert await async_migrate_entry(hass, entry) is True
    assert dict(entry.data) == {}
    assert entry.version == 2
    assert get_connection_address(entry) is None


@pytest.mark.asyncio
async def test_migration_supplies_the_default_port_when_none_was_stored():
    """Old entries predating the port field must not migrate to port None."""
    entry = make_entry(data={"ip_address": "9.9.9.9"}, version=1)
    hass = make_hass([entry])

    assert await async_migrate_entry(hass, entry) is True
    assert dict(entry.data) == {"ip_address": "9.9.9.9", "port": DEFAULT_PORT}


@pytest.mark.asyncio
async def test_migration_of_the_entry_the_house_is_actually_running():
    """The literal shape read off the house's disk, recorded in wayfinder #3.

    Worth a test of its own because two details are easy to miss and neither was
    invented here. The house entry was created by the **discovery flow**, so it
    carries a `source` of zeroconf and a `discovery_keys` record that the
    migration has no business rewriting. And the stored telnet delay is
    `0.0001`, chosen to sit just above the deployed code's 1e-5 floor -- a live
    setting rather than an inert default, so dropping it is a real change.
    """
    entry = make_entry(
        data={"ip_address": "192.168.86.46", "port": 23},
        options={
            "ip_address": "192.168.86.46",
            "port": 23,
            LEGACY_TELNET_DELAY: 0.0001,
        },
        version=1,
    )
    entry.source = "zeroconf"
    entry.unique_id = None
    entry.discovery_keys = MappingProxyType(
        {"zeroconf": ("231M000000000000._deako._tcp.local.",)}
    )
    hass = make_hass([entry])

    assert await async_migrate_entry(hass, entry) is True
    assert dict(entry.data) == {"ip_address": "192.168.86.46", "port": 23}
    assert dict(entry.options) == {}
    assert entry.version == 2
    assert get_connection_address(entry) == "192.168.86.46:23"

    # Provenance is Home Assistant's record, not ours. The migration passes
    # neither to async_update_entry, so both must be exactly as they were.
    assert entry.source == "zeroconf"
    assert dict(entry.discovery_keys) == {
        "zeroconf": ("231M000000000000._deako._tcp.local.",)
    }
    assert entry.entry_id == "entry-1", (
        "The entry must be updated in place; a new entry_id would orphan every "
        "entity and take its history with it."
    )


@pytest.mark.asyncio
async def test_a_current_entry_is_left_alone():
    """Migration only runs on old versions; a current entry must not change."""
    entry = make_entry(data={"ip_address": "9.9.9.9", "port": 23}, version=2)
    hass = make_hass([entry])

    assert await async_migrate_entry(hass, entry) is True
    assert dict(entry.data) == {"ip_address": "9.9.9.9", "port": 23}
    assert entry.version == 2


@pytest.mark.asyncio
async def test_a_future_entry_is_refused_rather_than_mangled():
    """A downgrade must not rewrite an entry it does not understand."""
    entry = make_entry(data={"ip_address": "9.9.9.9", "port": 23}, version=3)
    hass = make_hass([entry])

    assert await async_migrate_entry(hass, entry) is False
    assert entry.version == 3
