"""
Deako local integration constants.
"""

from enum import Enum

SOURCE = "pydeako_default"
DESTINATION = "deako"


class RequestType(str, Enum):
    """Request type enum."""

    CONTROL = "CONTROL"
    DEVICE_LIST = "DEVICE_LIST"
    PING = "PING"


class ResponseType(str, Enum):
    """Response type enum."""

    # DEVIATION (wayfinder #37/#39): the CONTROL acknowledgement. Stock 0.6.0
    # has four members and `_deako.incoming_json()` branches on exactly those,
    # so the hub's reply to every command we send matched nothing and was
    # silently discarded. It is the fastest honest signal in this protocol --
    # measured at 27.9-86.4ms against real firmware, against 1.6-2.4s for the
    # confirming EVENT -- and it is what drives the optimistic UI update.
    CONTROL = "CONTROL"
    DEVICE_FOUND = "DEVICE_FOUND"
    DEVICE_LIST = "DEVICE_LIST"
    EVENT = "EVENT"
    PONG = "PING"
