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
from .utils import _Connection, ConnectionState
from ._request import _Request

_LOGGER: logging.Logger = logging.getLogger(__package__)

# DEVIATION (wayfinder #41): what used to be one 10 s per-attempt budget,
# spent a second at a time by a poll that never asked whether the socket had
# already failed, is now three named numbers with three different jobs.
#
# CONNECT_TIMEOUT_S bounds the TCP connect and nothing else. A refused connect
# no longer costs any of it -- the socket's own state change ends the wait in
# under a millisecond -- but a node that answers no SYN at all still has to be
# given up on by us, because the kernel would take ~2 minutes to do it. #38
# measured the 7-11 s outages and found the 7/8/10 s cases were SYN retransmits
# against a silent node, which no amount of event-driving touches; this keeps
# our budget for that case exactly where it was.
CONNECT_TIMEOUT_S = 10
# HANDSHAKE_PONG_TIMEOUT_S is the new gate: a socket is not a connection until
# the hub has answered on it. See init_connection.
HANDSHAKE_PONG_TIMEOUT_S = 3
# Backoff between failed attempts: immediate first attempt, then 1, 2, 4, 8,
# capped. The cap is 10 s deliberately -- that is the cadence #19 measured as
# survivable against a dead node, so steady state is never more aggressive than
# the code already running in the house.
RETRY_BACKOFF_START_S = 1
RETRY_BACKOFF_MAX_S = 10
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
        on_connection_attempt: Callable[[], None] | None = None,
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
        # DEVIATION (wayfinder #41): #32 closed with the loose end that there
        # was no instrument that would explain the next burst of drops. These
        # two are it, for the price of an attribute on the existing sensor.
        #
        # They are deliberately separate questions. A node that answers no SYN
        # is a node that is away; a socket that opens and then never answers a
        # ping is the *stuck exclusive slot* -- the shape #32 caught and read as
        # a node symptom, and the reason this change exists at all.
        self.failed_connection_attempts = 0
        self.unanswered_connection_attempts = 0
        self.on_connection_attempt = on_connection_attempt
        # Woken by anything an in-flight connection attempt is waiting on: a
        # transition of the socket's state machine, or the pong that proves the
        # hub is there. One event rather than two because only one attempt can
        # be in flight at a time -- state.connecting guarantees it.
        self._attempt_event = asyncio.Event()
        # Delay before the *next* retry. Zero means none has been served yet,
        # so the first attempt after a loss is immediate; one clean reconnect on
        # cutover night cost 1 s, so a settle delay before the first attempt
        # would tax the good case for the bad one. It is never zero again until
        # a connection is proven -- an unbounded retry loop is what the old
        # 10.02 s was accidentally preventing.
        self._retry_delay_s: float = 0

    async def init_connection(self) -> None:
        """Build a connection, and do not report one until the hub answers.

        DEVIATION (wayfinder #41). Two things were wrong here, and the second
        one is why this was worth touching.

        The loop this replaces polled ``connection.is_connected()`` once a
        second up to a 10 s budget and never asked whether the socket had
        already *failed*. A connect refused in under a millisecond therefore
        cost the full 10 s, and a successful connect still cost one poll tick.
        The signal to wait on already existed -- the O5 deviation announces
        every transition of ``_Connection.state``, and every path that loses the
        socket runs through it.

        And ``is_connected()`` was satisfied by a TCP handshake alone: it never
        required the hub to have said anything. Deako's telnet server is
        exclusive, and on an ESP32 the network stack completes the handshake a
        layer below the telnet application, so a *stuck* slot -- the previous
        session not yet released -- accepts our connection and then serves
        nothing across it. #32 caught exactly that for 13 s, during which Home
        Assistant showed 37 available lights serving cached state and would have
        taken commands into a socket going nowhere. Our own reconnect is the
        second connector the map has always warned about.

        So a socket is now only a connection once a **correlated PONG** has come
        back over it. A ping is used rather than the device-list resync because
        it is symmetric across first connect and reconnect, is one small message
        rather than a 37-device burst, and sends no ``CONTROL``, so no light
        moves.
        """
        if self.state.connecting:
            _LOGGER.error("Already attempting to connect")
            return
        self.state.connecting = True
        try:
            address, name = await self.get_address()
        except DevicesNotFoundException:
            _LOGGER.warning("No devices to connect to")
            self.fail_attempt()
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
            #
            # DEVIATION (wayfinder #41): and it is now also what ends the wait
            # below, so a refusal is known when it happens rather than when a
            # timer next looks.
            on_state_change=self.on_connection_state_change,
        )

        loop = asyncio.get_running_loop()
        connected = await self.wait_until(
            lambda: connection.state != ConnectionState.NOT_STARTED,
            loop.time() + CONNECT_TIMEOUT_S,
        ) and connection.is_connected()
        if not connected:
            _LOGGER.warning(
                "Could not open a socket to %s. Trying again",
                connection.format_name(),
            )
            self.abandon(connection)
            return

        if not await self.handshake(connection):
            # The socket opened and the hub said nothing back. Reported
            # separately because it is the stuck-slot shape, not an absent node.
            self.unanswered_connection_attempts += 1
            _LOGGER.warning(
                "Socket to %s opened but the hub did not answer a ping in %ss. "
                "Not reporting this as a connection",
                connection.format_name(),
                HANDSHAKE_PONG_TIMEOUT_S,
            )
            self.abandon(connection)
            return

        self.connection = connection
        # init connection watching
        #
        # DEVIATION (wayfinder #41): started only now, and this ordering is
        # load-bearing. maintain_connection_worker uses the same
        # pending_ping_id / pong_received slot the handshake above needs, so a
        # worker running during the handshake would answer its question -- and
        # quietly restore the stock behaviour the O4 deviation exists to
        # prevent. The handshake is finished before the worker exists.
        if self.maintain_worker is None:
            self.state.canceled = False
            self.maintain_worker = asyncio.create_task(
                self.maintain_connection_worker()
            )
        self.state.connecting = False
        self._retry_delay_s = 0
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
            # back rather than attempts that were made.
            #
            # DEVIATION (wayfinder #41): and it now counts connections the hub
            # has *answered on*. Before this it counted arrivals at a socket,
            # which is why #32's ten reconnects were not ten node failures --
            # some of them were us knocking on a door that had not finished
            # closing, and logging each knock as an arrival. The counter's
            # meaning changes at this release and recorder history is not
            # comparable across it. Attempts that failed are counted separately,
            # as attributes on the same sensor.
            self.reconnect_count += 1
        if was_reconnect and self.on_connect is not None:
            await self.on_connect()

    async def handshake(self, connection: _Connection) -> bool:
        """Ask the hub to say something, and report whether it did.

        DEVIATION (wayfinder #41): the gate that makes a socket a connection.
        One PING, and the *correlated* PONG within HANDSHAKE_PONG_TIMEOUT_S --
        correlation being the same strictness the O4 watchdog uses, and proven
        against real firmware in #19, which captured the hub echoing the
        transaction id.

        Sent over the connection directly rather than through send_request,
        because `self.connection` is deliberately still unset: nothing may
        observe this socket as live until the answer is in.
        """
        ping = device_ping_request(source=self.client_name)
        self.pending_ping_id = ping.get("transactionId")
        self.pong_received = False
        if not await connection.send_data(_Request(ping).get_body_str()):
            return False
        loop = asyncio.get_running_loop()
        return await self.wait_until(
            # A socket that dies mid-handshake fails the attempt immediately
            # rather than serving out the budget.
            lambda: self.pong_received or not connection.is_connected(),
            loop.time() + HANDSHAKE_PONG_TIMEOUT_S,
        ) and self.pong_received

    async def wait_until(self, predicate, deadline: float) -> bool:
        """Wait for predicate() to hold, or for the deadline to pass.

        DEVIATION (wayfinder #41): this is the poll's replacement. Everything a
        connection attempt waits on -- the socket's state machine and the
        arrival of the pong -- pokes `_attempt_event`, so the wait ends when the
        thing happens rather than on the next tick of a timer.

        Cleared before the predicate is read, so a wakeup that arrived while we
        were not waiting is not lost: whatever set it has already had its effect
        on the predicate by the time it is asked.
        """
        loop = asyncio.get_running_loop()
        while True:
            self._attempt_event.clear()
            if predicate():
                return True
            remaining = deadline - loop.time()
            if remaining <= 0:
                return False
            try:
                await asyncio.wait_for(self._attempt_event.wait(), remaining)
            except (asyncio.TimeoutError, TimeoutError):
                return predicate()

    def on_connection_state_change(self) -> None:
        """Announce the transition, and wake any attempt waiting on it."""
        self._attempt_event.set()
        self.notify_connection_change()

    def abandon(self, connection: _Connection) -> None:
        """Give up on a connection that never proved itself, and retry."""
        connection.close()
        self.notify_connection_change()
        self.fail_attempt()

    def fail_attempt(self) -> None:
        """Record a failed attempt and schedule the next one.

        DEVIATION (wayfinder #41): the retry cadence lives here, in one place,
        and is deliberate rather than emergent. It used to be
        `CONNECTION_TIMEOUT_S` showing through -- a flat 10.02 s between
        attempts that nobody chose, and which #19 recorded as a measured churn
        rate of 6/min. Delay is never zero: `create_connection_task` ->
        `init_connection` -> refusal in under a millisecond -> repeat is bounded
        only by event-loop scheduling, and that flat 10 s was the only thing
        serialising retries.
        """
        self.failed_connection_attempts += 1
        self.state.connecting = False
        if self._retry_delay_s <= 0:
            self._retry_delay_s = RETRY_BACKOFF_START_S
        else:
            self._retry_delay_s = min(
                self._retry_delay_s * 2, RETRY_BACKOFF_MAX_S,
            )
        if self.on_connection_attempt is not None:
            try:
                self.on_connection_attempt()
            except Exception as exc:  # pylint: disable=broad-exception-caught
                _LOGGER.error("Connection attempt listener failed: %s", exc)
        self.create_connection_task(self._retry_delay_s)

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
        # DEVIATION (wayfinder #41): an attempt in flight is about to be
        # cancelled at its next await, so the code that would have cleared this
        # never runs. Left set, it makes every future init_connection return
        # "Already attempting to connect" and nothing ever reconnects again.
        self.state.connecting = False

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

    def create_connection_task(self, delay: float = 0):
        """Create an async task to initiate connection, after `delay` seconds.

        DEVIATION (wayfinder #41): the delay is how backoff is served. It is
        held here rather than inside init_connection so that close() cancelling
        `self.tasks` also cancels a retry that has not fired yet.
        """
        # RUF006
        # pylint: disable-next=line-too-long
        # noqa keep reference via: https://stackoverflow.com/questions/71938799/python-asyncio-create-task-really-need-to-keep-a-reference
        # even if we don't care
        task = asyncio.create_task(self.connect_after(delay))
        self.tasks.add(task)

        def remove_task(_task):
            try:
                self.tasks.remove(_task)
            except KeyError:
                pass  # already removed

        task.add_done_callback(remove_task)

    async def connect_after(self, delay: float) -> None:
        """Wait out the backoff, then attempt a connection."""
        if delay > 0:
            _LOGGER.info("Retrying the hub connection in %ss", delay)
            await asyncio.sleep(delay)
        await self.init_connection()

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
                # DEVIATION (wayfinder #41): the handshake waits on this.
                self._attempt_event.set()
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
        transaction_id: str | None = None,
        completed_callback: Callable | None = None,
    ) -> bool:
        """Send a state change request, reporting whether it was sent.

        DEVIATION (wayfinder #39): the transaction id is now the caller's to
        choose. Stock minted one inside `state_change_request()` with `uuid4()`
        and threw it away, which made the acknowledgement impossible to
        correlate -- and the ack names no target, so correlation is the only
        way to know which command it answers.
        """
        return await self.send_request(
            _Request(
                state_change_request(
                    uuid, power, dim,
                    source=self.client_name,
                    transaction_id=transaction_id,
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
