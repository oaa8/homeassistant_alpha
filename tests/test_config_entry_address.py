"""
Regression tests for Deako config-entry address resolution.

Module: tests/test_config_entry_address.py
Author: GitHub Copilot
Purpose: Guards `custom_components.deako.get_connection_address` against a
    regression in which a configured hub address could not be distinguished
    from an unconfigured one. Home Assistant stores a config entry's `options`
    and `data` as MappingProxyType, so both are always truthy-checkable objects
    and never None; earlier code tested `if entry.options is not None`, which
    is unconditionally true. That made the mDNS discovery branch unreachable
    and produced the literal address "None:None".

Key assumptions:
    - Home Assistant is not installed in this test environment, so the function
      under test is extracted from source and executed against stubs rather
      than imported. This keeps the test runnable in CI without the full HA
      dependency tree while still exercising the real, shipped code.
    - `MappingProxyType({})` faithfully reproduces HA's empty-options case; see
      homeassistant/config_entries.py (`self.options = MappingProxyType(options or {})`).
"""

from __future__ import annotations

import ast
from collections.abc import Awaitable
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import Callable

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
INTEGRATION_INIT = REPO_ROOT / "custom_components" / "deako" / "__init__.py"


def _load_get_connection_address():
    """Extract and compile get_connection_address without importing Home Assistant.

    Importing the integration module directly would pull in homeassistant,
    pydeako and atomics. Those are runtime dependencies of the integration but
    not of the simulator test suite, so the function is isolated via AST.
    """
    tree = ast.parse(INTEGRATION_INIT.read_text(encoding="utf-8"))
    func = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "get_connection_address"
    )

    namespace: dict = {
        "CONF_IP_ADDRESS": "ip_address",
        "CONF_PORT": "port",
        "HomeAssistant": object,
        "ConfigEntry": object,
        "Callable": Callable,
        "Awaitable": Awaitable,
    }
    exec(  # noqa: S102 - executing first-party source under test, not user input
        compile(ast.Module(body=[func], type_ignores=[]), str(INTEGRATION_INIT), "exec"),
        namespace,
    )
    return namespace["get_connection_address"]


get_connection_address = _load_get_connection_address()


def make_entry(options: dict | None = None, data: dict | None = None):
    """Build a config entry stub using HA's real MappingProxyType semantics."""
    return SimpleNamespace(
        options=MappingProxyType(options or {}),
        data=MappingProxyType(data or {}),
    )


async def _resolve(entry) -> str | None:
    get_address = await get_connection_address(None, entry)
    if get_address is None:
        return None
    return await get_address()


@pytest.mark.asyncio
async def test_no_configuration_falls_back_to_discovery():
    """An unconfigured entry must yield None so the caller uses mDNS discovery.

    This is the specific regression: `if entry.options is not None` was always
    true, so this case previously returned the address "None:None" and the
    mDNS branch could never run.
    """
    assert await _resolve(make_entry()) is None, (
        "Unconfigured entry must return None to signal mDNS discovery; "
        "returning an address string makes the discovery branch unreachable."
    )


@pytest.mark.asyncio
async def test_address_from_entry_data():
    """An address supplied at initial setup time lives in entry.data."""
    entry = make_entry(data={"ip_address": "10.0.0.5", "port": 23})
    assert await _resolve(entry) == "10.0.0.5:23"


@pytest.mark.asyncio
async def test_address_from_entry_options():
    """An address edited after setup lives in entry.options."""
    entry = make_entry(options={"ip_address": "1.2.3.4", "port": 8023})
    assert await _resolve(entry) == "1.2.3.4:8023"


@pytest.mark.asyncio
async def test_options_take_precedence_over_data():
    """Options represent the most recent user edit and must win over data."""
    entry = make_entry(
        options={"ip_address": "1.1.1.1", "port": 1},
        data={"ip_address": "2.2.2.2", "port": 2},
    )
    assert await _resolve(entry) == "1.1.1.1:1"


@pytest.mark.asyncio
async def test_empty_options_falls_through_to_data():
    """Empty options must not mask an address configured in data.

    HA populates options only once the user opens the options flow, so an
    entry configured at setup time has empty options and populated data.
    """
    entry = make_entry(options={}, data={"ip_address": "9.9.9.9", "port": 23})
    assert await _resolve(entry) == "9.9.9.9:23", (
        "Empty options must fall through to entry.data rather than "
        "short-circuiting on the presence of the options mapping."
    )
