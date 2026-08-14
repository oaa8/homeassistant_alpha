"""
Manager to SocketConnection, ensuring that there's always an
active connection. Uses two workers, one to check connectivity
through pinging, and one to check for messages to send.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable

from ..discover import DevicesNotFoundException
from ..models import (
    device_list_request,
    device_ping_request,
    state_change_request,
    ResponseType,
)
from .utils import _Connection
from ._request import _Request

_LOGGER: logging.Logger = logging.getLogger(__package__)

CONNECTED_POLLING_INTERVAL_S = 1
CONNECTION_TIMEOUT_S = 10
WORKER_WAIT_S = 0.5
PING_WORKER_WAIT_S = 10


@dataclass
class _ManagerState:
    """State for _Manager, used by workers."""

    connecting: bool = False
    canceled: bool = False
    logged_send_error = False


# pylint: disable-next=too-many-instance-attributes
class _Manager:
    """Manage the socket connection to Deako local integrations."""

    maintain_worker: asyncio.Task | None = None
    worker: asyncio.Task | None = None
    connection: _Connection | None = None
    tasks: set[asyncio.Task]
    client_name: str | None
    state: _ManagerState

    def __init__(
        self,
        get_address,
        incoming_json_callback,
        client_name: str | None = None,
        on_connect: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        """Initialize with get address function and incoming json callback."""
        self.get_address = get_address
        self.incoming_json_callback = incoming_json_callback
        self.pong_received = False
        # DEVIATION (O4): see maintain_connection_worker.
        self.pending_ping_id: str | None = None
        self.tasks = set()
        self.client_name = client_name
        self.state = _ManagerState()
        # DEVIATION (O7): fired every time a connection is established,
        # including reconnects, so cached state can be resynced.
        self.on_connect = on_connect

    async def init_connection(self) -> None:
        """Initialize the connection process."""
        if self.state.connecting:
            _LOGGER.error("Already attempting to connect")
            return
        self.state.connecting = True
        try:
            address, name = await self.get_address()
        except DevicesNotFoundException:
            _LOGGER.warning("No devices to connect to")
            self.create_connection_task()
            self.state.connecting = False
            return
        connection = _Connection(address, name, self.incoming_json)
        timeout = 0
        while not connection.is_connected() and timeout < CONNECTION_TIMEOUT_S:
            await asyncio.sleep(CONNECTED_POLLING_INTERVAL_S)
            timeout += CONNECTED_POLLING_INTERVAL_S
        if timeout == CONNECTION_TIMEOUT_S:
            _LOGGER.error("Timeout attempting to connect. Trying again")
            self.state.connecting = False
            connection.close()
            self.create_connection_task()
            return
        self.connection = connection
        # init connection watching
        if self.maintain_worker is None:
            self.state.canceled = False
            self.maintain_worker = asyncio.create_task(
                self.maintain_connection_worker()
            )
        self.state.connecting = False

        # DEVIATION (O7): stock resumed listening here and never asked the hub
        # what the state is now, so a change made during an outage could stay
        # wrong indefinitely. Fired after the connection is live and
        # `connecting` is cleared, so the callback can send immediately.
        if self.on_connect is not None:
            await self.on_connect()

    def is_connected(self) -> bool:
        """Report whether there is a live connection.

        DEVIATION (O5): stock offers no honest connection-state accessor.
        `_Connection.close()` does not move the state machine out of CONNECTED,
        so `is_connected()` alone keeps saying yes after a close; the socket
        check is what makes the answer truthful.
        """
        return (
            not self.state.canceled
            and self.connection is not None
            and self.connection.is_connected()
            and self.connection.socket.sock is not None
        )

    def close(self) -> None:
        """Close connection."""
        _LOGGER.debug("Closing connection and canceling workers")
        self.state.canceled = True

        # Cancel and clear all pending tasks
        for task in self.tasks:
            task.cancel()
        self.tasks.clear()

        if self.worker is not None:
            self.worker.cancel()
            self.worker = None
        if self.maintain_worker is not None:
            self.maintain_worker.cancel()
            self.maintain_worker = None
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def create_connection_task(self):
        """Create an async task to initiate connection."""
        # RUF006
        # pylint: disable-next=line-too-long
        # noqa keep reference via: https://stackoverflow.com/questions/71938799/python-asyncio-create-task-really-need-to-keep-a-reference
        # even if we don't care
        task = asyncio.create_task(self.init_connection())
        self.tasks.add(task)

        def remove_task(_task):
            try:
                self.tasks.remove(_task)
            except KeyError:
                pass  # already removed

        task.add_done_callback(remove_task)

    async def maintain_connection_worker(self) -> None:
        """Monitor connection and restart if there's a failure."""
        await asyncio.sleep(PING_WORKER_WAIT_S)
        while True:
            if self.state.canceled:
                break
            # DEVIATION (O4): stock set a bare pong_received flag that any
            # inbound PONG satisfied, regardless of which ping it answered, so
            # a late pong arriving in the next window could mask a dying
            # connection. Correlate on the transaction id that was sent.
            #
            # The hub is not known for certain to echo transactionId on a PONG
            # -- the simulator does, and it was built from observed hardware,
            # but no capture proves it on the real firmware. So a PONG that
            # carries no transaction id still counts. That is exactly stock
            # behaviour, never worse; if the spare switch rig confirms the echo,
            # the fallback can go.
            ping = device_ping_request(source=self.client_name)
            self.pending_ping_id = ping.get("transactionId")
            self.pong_received = False
            _LOGGER.debug("Pinging for responsiveness")
            await self.send_request(_Request(ping))
            await asyncio.sleep(PING_WORKER_WAIT_S)
            if self.pong_received:
                _LOGGER.debug("Pong received")
            else:
                _LOGGER.warning("Never received pong! Dumping this connection")
                self.close()
                self.create_connection_task()
                break

    def incoming_json(self, incoming_json: dict) -> None:
        """Handle incoming json."""
        response_type = incoming_json.get("type")
        if response_type == ResponseType.PONG:
            # DEVIATION (O4): only accept the pong that answers the ping
            # currently outstanding. See maintain_connection_worker for why an
            # id-less pong is still accepted.
            transaction_id = incoming_json.get("transactionId")
            if transaction_id is None or transaction_id == self.pending_ping_id:
                self.pong_received = True
            else:
                _LOGGER.debug(
                    "Ignoring pong for ping %s, waiting on %s",
                    transaction_id,
                    self.pending_ping_id,
                )
        else:
            self.incoming_json_callback(incoming_json)

    async def send_get_device_list(self) -> bool:
        """Send the device list request."""
        return await self.send_request(
            _Request(device_list_request(source=self.client_name)),
        )

    async def send_state_change(
        self,
        uuid,
        power,
        dim=None,
        completed_callback: Callable | None = None,
    ) -> None:
        """Send a state change request."""
        await self.send_request(
            _Request(
                state_change_request(
                    uuid, power, dim, source=self.client_name,
                ),
                completed_callback=completed_callback,
            )
        )

    async def send_request(self, req: _Request) -> bool:
        """Send a request."""
        if self.connection is not None:
            await self.connection.send_data(req.get_body_str())
            return True

        _LOGGER.warning("No connection to send data to")
        return False
