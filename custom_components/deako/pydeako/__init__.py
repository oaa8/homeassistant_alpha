"""
pydeako module provides the following:
 - models to interact with Deako devices locally with a socket connection
 - implementation of a Deako socket client
 - mdns discovery client

Vendored copy of pydeako 0.6.0 (MIT, (c) 2023 Deako Lighting -- see
LICENSE.txt), taken unmodified from PyPI and then edited in place. Upstream has
not shipped since 2024, and the behaviour this house needs cannot be reached
through the public surface, so the library is owned here rather than pinned.

Every local edit is marked `# DEVIATION (Ox)` and names the house outcome it
defends, so `diff` against stock 0.6.0 answers "what did we change and why",
and a future Deako release is a rebase rather than a rewrite.
"""
# pylint: disable=duplicate-code
from .discover import DeakoDiscoverer, DevicesNotFoundException
from .deako import Deako, FindDevicesError
from .models import (
    RequestType,
    ResponseType,
    device_list_request,
    device_ping_request,
    state_change_request,
)

__all__ = [
    'DeakoDiscoverer',
    'DevicesNotFoundException',
    'Deako',
    'FindDevicesError',
    'RequestType',
    'ResponseType',
    'device_list_request',
    'device_ping_request',
    'state_change_request',
]
