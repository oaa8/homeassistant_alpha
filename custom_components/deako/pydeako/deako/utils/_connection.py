"""
Class that manages a socket connection to a deako device.
"""

import asyncio
import json
import logging
from enum import Enum
from typing import Callable

from ._socket import _SocketConnection

_LOGGER: logging.Logger = logging.getLogger(__package__)


class UnknownStateException(Exception):
    """Unknown state."""


class ConnectionState(Enum):
    """Enum for connection states."""

    UNKNOWN = -1
    NOT_STARTED = 0
    CONNECTED = 1
    ERROR = 2
    CLOSED = 3


class _Connection:
    """
    Representation of a local socket connection to a Deako device.
    Continuously reads socket for messages async.
    """

    # pylint: disable=too-many-instance-attributes

    address: str
    name: str
    message_buffer: str
    loop: asyncio.AbstractEventLoop
    socket: _SocketConnection
    tasks: set[asyncio.Task]

    def __init__(
        self,
        address: str,
        name: str,
        on_data_callback: Callable[[dict], None],
        on_state_change: Callable[[], None] | None = None,
    ) -> None:
        """Setup and start a socket connection."""
        self.address = address
        self.name = name
        self.loop = asyncio.get_running_loop()
        self._state = ConnectionState.NOT_STARTED
        self.on_data_callback = on_data_callback
        # DEVIATION (O5): fired on every state transition of this socket, so
        # that "the connection just died" is something the caller is told
        # rather than something it has to go and ask about on a timer. Assigned
        # before init_run() so the first CONNECTED is not missed; _state is set
        # directly above so constructing a connection does not itself announce
        # a transition.
        self.on_state_change = on_state_change
        self.message_buffer = ""
        self.socket = _SocketConnection(address, self.loop)
        self.tasks = set()
        self.init_run()

    @property
    def state(self) -> ConnectionState:
        """Return the current state of this socket."""
        return self._state

    @state.setter
    def state(self, value: ConnectionState) -> None:
        """Set the state, announcing real transitions.

        DEVIATION (O5): every path that loses the socket -- a failed send, a
        read error, and the FIN that read_socket() turns into ERROR -- runs
        through here, so one hook covers all of them.
        """
        if value == self._state:
            return
        self._state = value
        if self.on_state_change is not None:
            try:
                self.on_state_change()
            except Exception as exc:  # pylint: disable=broad-exception-caught
                _LOGGER.error("Connection state listener failed: %s", exc)

    async def send_data(self, data_to_send: str) -> bool:
        """Send data to socket, reporting whether it left the machine.

        DEVIATION (O5): stock swallowed the failure and returned None, so a
        command issued over a dead socket was indistinguishable from one that
        was delivered. The caller needs to be able to tell.
        """
        _LOGGER.debug("[%s] Sending data: %s", self.address, data_to_send)
        try:
            await self.socket.send_bytes(str.encode(data_to_send))
        except Exception as exc:  # pylint: disable=broad-exception-caught
            _LOGGER.error("Error sending data: %s", exc)
            self.state = ConnectionState.ERROR
            return False
        return True

    async def read_socket(self) -> None:
        """Read data from socket."""
        try:
            data = await self.socket.read_bytes()
        except Exception as exc:  # pylint: disable=broad-exception-caught
            _LOGGER.error("Error receiving data: %s", exc)
            self.state = ConnectionState.ERROR
            return

        # DEVIATION (O4): after a network blip the lights have to work again
        # without anyone reloading anything -- and stock cannot get there from
        # a clean close. When the peer sends FIN, sock_recv() returns b"" and
        # keeps returning it, so run() spins here forever. Worse, that spin
        # never yields: sock_recv completes synchronously at EOF, so awaiting
        # it does not suspend, and the asyncio event loop is starved outright.
        # The ping watchdog then never runs, the connection is never rebuilt,
        # and inside Home Assistant the whole event loop stops.
        #
        # Observed, not theorised: dropping the connection from the simulator
        # pinned a core at ~97% and hung the process indefinitely.
        if not data:
            _LOGGER.warning(
                "[%s] Connection closed by the hub", self.format_name(),
            )
            self.state = ConnectionState.ERROR
            return

        self.parse_data(data)

    def parse_data(self, data: bytes) -> None:
        """
        Parse incoming bytes into json as expected. Possible to have
        data come in multiple chunks and multiple messages.
        """
        raw_string = data.decode("utf-8")
        _LOGGER.debug(
            "[%s] Raw message received: %s",
            self.format_name(),
            raw_string,
        )
        messages = raw_string.strip().split("\r\n")
        for message_str in messages:
            self.message_buffer = self.message_buffer + message_str
            try:
                message_json = json.loads(self.message_buffer)
                self.on_data_callback(message_json)
                self.message_buffer = ""
            except json.decoder.JSONDecodeError:
                _LOGGER.debug("Got partial message: %s", self.message_buffer)

    def init_run(self) -> None:
        """Init the run sequence and store run task."""
        # RUF006
        # pylint: disable-next=line-too-long
        # noqa keep reference via: https://stackoverflow.com/questions/71938799/python-asyncio-create-task-really-need-to-keep-a-reference
        # even if we don't care
        task = self.loop.create_task(self.run())

        def remove_task(_task):
            self.tasks.remove(_task)

        task.add_done_callback(remove_task)
        self.tasks.add(task)

    def close(self) -> None:
        """Close our socket and cancel all pending tasks."""
        self.socket.close_socket()
        for task in self.tasks:
            task.cancel()

    def is_connected(self) -> bool:
        """Return whether or not connected."""
        return self.state == ConnectionState.CONNECTED

    async def run(self) -> None:
        """State machine."""
        while True:
            if self.state == ConnectionState.NOT_STARTED:
                try:
                    await self.socket.connect_socket()
                    self.state = ConnectionState.CONNECTED
                    _LOGGER.info(
                        "Connected to Deako local integrations with %s",
                        self.format_name(),
                    )
                # pylint: disable-next=broad-exception-caught
                except Exception as exc:
                    _LOGGER.error(
                        "Failed to connect %s because %s",
                        self.format_name(),
                        exc,
                    )
                    self.state = ConnectionState.ERROR
            elif self.state == ConnectionState.CONNECTED:
                try:
                    await self.read_socket()
                # pylint: disable-next=broad-exception-caught
                except Exception as exc:
                    _LOGGER.error(
                        "Failed to read socket %s because %s",
                        self.format_name(),
                        exc,
                    )
                    self.state = ConnectionState.ERROR
            elif self.state == ConnectionState.ERROR:
                try:
                    self.close()
                    self.state = ConnectionState.CLOSED
                # pylint: disable-next=broad-exception-caught
                except Exception as exc:
                    _LOGGER.error(
                        "Failed to close socket %s because %s",
                        self.format_name(),
                        exc,
                    )
                    self.state = ConnectionState.CLOSED
            elif self.state == ConnectionState.CLOSED:
                # this socket is toast
                break
            else:
                _LOGGER.error("Unknown state: %s", self.state)
                raise UnknownStateException(f"Unknown state: {self.state}")

    def format_name(self) -> str:
        """Format name."""
        return f"{self.name}@{self.address}"
