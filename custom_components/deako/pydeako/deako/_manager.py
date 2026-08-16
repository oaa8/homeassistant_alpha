"""
Manager to SocketConnection, ensuring that there's always an
active connection. Uses two workers, one to check connectivity
through pinging, and one to check for messages to send.
"""

import asyncio
import logging
import time
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
        on_connection_change: Callable[[bool], None] | None = None,
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
        # DEVIATION (O7): fired when a connection is *re*established, so cached
        # state can be resynced. Not on the first connection: the caller
        # enumerates with find_devices() immediately after connect(), and
        # firing here as well made every setup request the device list twice.
        self.on_connect = on_connect
        self.has_connected_before = False
        # DEVIATION (O5): fired with the new answer whenever is_connected()
        # changes, so a consumer can show "broken" instead of serving cached
        # state that stopped being true. Every transition is announced from
        # notify_connection_change, which dedupes, so callers may prod it
        # whenever they suspect the answer moved.
        self.on_connection_change = on_connection_change
        self.reported_connected = False
        # DEVIATION (wayfinder #23): the two hub-level numbers the diagnostic
        # entities report, kept here because this is the only place that sees
        # every inbound message and every completed connection.
        #
        # A monotonic clock, not wall time: the age of the last message has to
        # stay honest across an NTP correction or a suspend, and it is only
        # ever read as a difference.
        self.last_message_at: float | None = None
        self.reconnect_count = 0

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
        connection = _Connection(
            address,
            name,
            self.incoming_json,
            # DEVIATION (O5): the socket dies in _Connection, not here -- a FIN
            # or a failed send moves it to ERROR without anything in the
            # manager being told. Hooking the transition is what makes
            # "unavailable" arrive in half a second rather than waiting on the
            # next ping window.
            on_state_change=self.notify_connection_change,
        )
        timeout = 0
        while not connection.is_connected() and timeout < CONNECTION_TIMEOUT_S:
            await asyncio.sleep(CONNECTED_POLLING_INTERVAL_S)
            timeout += CONNECTED_POLLING_INTERVAL_S
        if timeout == CONNECTION_TIMEOUT_S:
            _LOGGER.error("Timeout attempting to connect. Trying again")
            self.state.connecting = False
            connection.close()
            self.notify_connection_change()
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
        # is_connected() needs `self.connection` set and `canceled` cleared,
        # neither of which was true when the socket announced CONNECTED above,
        # so that transition reported "still down". Ask again now that all
        # three parts of the answer agree.
        self.notify_connection_change()

        # DEVIATION (O7): stock resumed listening here and never asked the hub
        # what the state is now, so a change made during an outage could stay
        # wrong indefinitely. Fired after the connection is live and
        # `connecting` is cleared, so the callback can send immediately.
        #
        # Skipped on the very first connection, where the caller's own
        # find_devices() does the enumerating. Firing on both was observed
        # sending two full DEVICE_LIST requests 38ms apart at every setup --
        # harmless, since devices are keyed by uuid, but it doubles the
        # enumeration burst on a hub with three dozen devices for nothing.
        was_reconnect = self.has_connected_before
        self.has_connected_before = True
        if was_reconnect:
            # DEVIATION (wayfinder #23): counted here rather than at the point
            # the connection is dropped, so it counts connections that came
            # back rather than attempts that were made. There is no backoff in
            # 0.6.0 -- a dead node is retried about 6 times a minute (#19) --
            # so a count of attempts would measure the length of one outage,
            # not the number of them.
            self.reconnect_count += 1
        if was_reconnect and self.on_connect is not None:
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

    def notify_connection_change(self) -> None:
        """Announce a change in is_connected() to the listener, if any.

        DEVIATION (O5): when it's broken, you have to be able to tell. This is
        the push half of that -- is_connected() is the answer, and this is what
        says "the answer just moved" so nothing has to poll for it.

        Deduped on the last value reported, because it is called from several
        places that each only *suspect* a transition: the socket's own state
        machine, the end of a connection attempt, and close().
        """
        connected = self.is_connected()
        if connected == self.reported_connected:
            return
        self.reported_connected = connected
        _LOGGER.info(
            "Connection to the hub is now %s",
            "up" if connected else "down",
        )
        if self.on_connection_change is None:
            return
        try:
            self.on_connection_change(connected)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            _LOGGER.error("Connection change listener failed: %s", exc)

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

        # DEVIATION (O5): close() is how the ping watchdog drops a blackholed
        # connection, so this is the path a hub that stopped answering takes.
        # Without this the entities would stay looking healthy until something
        # else happened to ask.
        self.notify_connection_change()

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
            # The correlation is strict: only the pong carrying this window's
            # transaction id counts. The real firmware does echo it -- captured
            # from the spare node, which answered
            #   {"type":"PING","transactionId":"wf19-ping-0002",
            #    "dst":"deako_watchdog_battery","src":"deako","status":"ok",...}
            # -- so an uncorrelatable pong is not a hub we can prove is alive,
            # and treating it as one would quietly restore the stock behaviour
            # this deviation exists to prevent.
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

    def seconds_since_last_message(self) -> float | None:
        """Return how long ago the hub last said anything, in seconds.

        DEVIATION (wayfinder #23): None until the hub has said something at
        all, which is a different fact from "it has been quiet for 0 seconds"
        and must not be reported as one.
        """
        if self.last_message_at is None:
            return None
        return time.monotonic() - self.last_message_at

    def incoming_json(self, incoming_json: dict) -> None:
        """Handle incoming json."""
        # DEVIATION (wayfinder #23): stamped at the inbound choke point,
        # *before* the PONG filtering below, because the pongs are the only
        # thing a healthy but idle hub reliably says. Stamping after the filter
        # would make the age climb without bound on a house where nobody
        # touches a light, which is the normal case -- ten hardware runs with
        # no manipulation produced zero EVENTs (#10).
        self.last_message_at = time.monotonic()

        response_type = incoming_json.get("type")
        if response_type == ResponseType.PONG:
            # DEVIATION (O4): only accept the pong that answers the ping
            # currently outstanding. A pong with no transaction id answers
            # nothing, and neither does any pong arriving before the first ping
            # went out, when there is no outstanding id to answer. See
            # maintain_connection_worker.
            transaction_id = incoming_json.get("transactionId")
            if (
                self.pending_ping_id is not None
                and transaction_id == self.pending_ping_id
            ):
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
    ) -> bool:
        """Send a state change request, reporting whether it was sent."""
        return await self.send_request(
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
            # DEVIATION (O5): a send that failed on a dead socket used to be
            # reported as success, because send_data returned None either way.
            # A command issued while disconnected has to fail visibly.
            return await self.connection.send_data(req.get_body_str())

        _LOGGER.warning("No connection to send data to")
        return False
