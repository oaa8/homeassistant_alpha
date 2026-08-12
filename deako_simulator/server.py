"""
Deako Hub Simulator - TCP Server Implementation

Module: server.py
Created: 2025-10-27
Last Modified: 2025-10-27
Author: GitHub Copilot

Purpose:
    Core TCP telnet server that implements the Deako hub protocol.
    Handles client connections, message routing, and protocol responses.

Key Assumptions:
    - Single active connection, additional connections are passive/zombie (FR-072)
    - Messages are line-delimited JSON with CRLF termination
    - PING responses are immediate, other messages may have delays
    - Connection lifecycle follows hardware-validated behavior

Related Requirements:
    - FR-001: mDNS service advertisement
    - FR-010: Graceful shutdown (SIGTERM/SIGINT, 5s timeout)
    - FR-048: Log connection events with client IP
    - FR-068: Log effective configuration at startup
    - FR-072: Passive rejection model for multi-client

Related Research:
    - research/connection-lifecycle-test-2025-10-18.md - Connection handling
    - research/multi-connection-test-2025-10-18.md - Multi-client behavior
"""

from __future__ import annotations

import asyncio
import json
import logging
import signal
from typing import Any, Optional, TYPE_CHECKING

from deako_simulator.config import Config
from deako_simulator.models import Device
from deako_simulator.state import SimulatorState
from deako_simulator.mdns_service import register_mdns, unregister_mdns
from deako_simulator.quirks import QuirkManager

if TYPE_CHECKING:
    from aiohttp.web import AppRunner
    from zeroconf import ServiceInfo, Zeroconf


# Get logger with component tag
logger = logging.getLogger("deako_simulator.telnet")
connection_logger = logging.getLogger("deako_simulator.connection")


class DeakoSimulator:
    """
    Main simulator class implementing Deako hub protocol over TCP.
    
    Handles:
    - TCP server lifecycle (start/stop)
    - mDNS service registration
    - Client connection management
    - Protocol message routing
    - Graceful shutdown
    
    Thread-safe by design (asyncio single-threaded event loop).
    """
    
    def __init__(
        self,
        state: SimulatorState,
        config: Config,
        quirk_manager: Optional[QuirkManager] = None,
    ) -> None:
        """
        Initialize simulator with state and configuration.
        
        Args:
            state: SimulatorState instance managing device state
            config: Config instance with network and device settings
            quirk_manager: Optional QuirkManager for protocol quirk injection
        """
        self.state = state
        self.config = config
        self.quirk_manager = quirk_manager or QuirkManager()
        self.server: asyncio.Server | None = None
        self.http_runner: AppRunner | None = None  # HTTP API server runner (T058)
        self.zeroconf: Zeroconf | None = None
        # register_mdns publishes one ServiceInfo per advertised service type
        # (_deako and _telnet), so this holds a list rather than a single entry.
        self.service_info: list[ServiceInfo] = []
        self._shutdown_event: asyncio.Event = asyncio.Event()
        self._whitespace_task: asyncio.Task[None] | None = None
        
        logger.debug(
            f"DeakoSimulator initialized with {len(state.devices)} devices"
        )
    
    async def start(self) -> None:
        """
        Start the simulator server.
        
        Actions:
        1. Start TCP telnet and HTTP servers concurrently (T058: asyncio.gather)
        2. Register mDNS service for discovery
        3. Log effective configuration per FR-068
        4. Set up signal handlers for graceful shutdown
        
        Per research.md decision 7: Both servers run in same event loop,
        sharing SimulatorState for consistent behavior.
        
        Raises:
            OSError: If port is already in use or bind fails
            RuntimeError: If server fails to start
            
        Research References:
            - FR-001: mDNS registration for discovery
            - FR-010: Graceful shutdown requirements
            - FR-068: Log effective configuration
        """
        # Log effective configuration per FR-068
        self._log_effective_config()
        
        # Start both servers concurrently per T058 using asyncio.gather()
        # This allows them to start simultaneously in the same event loop
        telnet_task = asyncio.create_task(self._start_telnet_server())
        http_task = asyncio.create_task(self._start_http_server())
        
        try:
            await asyncio.gather(telnet_task, http_task)
        except Exception as e:
            logger.error(f"Failed to start servers: {e}")
            # Clean up any partial startup
            if self.server:
                self.server.close()
            if self.http_runner:
                await self.http_runner.cleanup()
            raise
        
        # Start per-device command processor tasks per FR-070
        # Per research.md decision 6: Deterministic command processing via per-device queues
        # This ensures commands for same device are processed sequentially
        self._start_command_processors()
        
        # Register mDNS service for discovery (non-blocking, graceful degradation)
        self.zeroconf, self.service_info = await register_mdns(
            port=self.config.network.port,
            hostname=self.config.network.mdns_name,
        )
        
        # Set up signal handlers for graceful shutdown
        self._setup_signal_handlers()
        
        # Start whitespace injection task if enabled (FR-024)
        if self.quirk_manager.config.whitespace_enabled:
            self._whitespace_task = asyncio.create_task(
                self._whitespace_injector()
            )
            logger.debug("Started whitespace injection background task")
        
        logger.info("Simulator started successfully")
    
    async def _start_telnet_server(self) -> None:
        """
        Start TCP telnet server (internal helper for concurrent startup).
        
        Called by start() via asyncio.gather() for concurrent initialization.
        """
        try:
            # Create server with 64KB limit per FR-087 (max message buffer)
            # This prevents memory exhaustion from malicious clients sending huge messages
            self.server = await asyncio.start_server(
                self._handle_connection,
                host=self.config.network.host,
                port=self.config.network.port,
                reuse_address=True,  # Allow immediate reconnection per FR-085
                reuse_port=False,
                limit=64 * 1024,  # 64KB buffer limit per FR-087
            )
            
            # Get actual bound address (useful if port=0 for random port)
            addrs = ', '.join(
                f"{sock.getsockname()[0]}:{sock.getsockname()[1]}"
                for sock in self.server.sockets
            )
            logger.info(f"Telnet server listening on {addrs}")
            
        except OSError as e:
            logger.error(f"Failed to start telnet server: {e}")
            raise RuntimeError(f"Could not bind to {self.config.network.host}:{self.config.network.port}") from e
    
    async def _start_http_server(self) -> None:
        """
        Start HTTP API server (internal helper for concurrent startup).
        
        Called by start() via asyncio.gather() for concurrent initialization.
        HTTP API shares SimulatorState with telnet server (single source of truth).
        """
        try:
            from deako_simulator.api import start_http_api
            self.http_runner = await start_http_api(
                state=self.state,
                config=self.config,
                quirk_manager=self.quirk_manager,  # T071: Pass quirk manager for control endpoints
                host=self.config.network.host,
                port=self.config.network.http_port
            )
            logger.info(f"HTTP API server started on {self.config.network.host}:{self.config.network.http_port}")
        except Exception as e:
            logger.error(f"Failed to start HTTP API server: {e}")
            # Note: HTTP API failure is not fatal - telnet server still functional
            # This allows simulator to work even if HTTP port is unavailable
            self.http_runner = None
    
    def _log_effective_config(self) -> None:
        """
        Log effective configuration at startup per FR-068.
        
        Shows source of each setting (config file vs defaults).
        Helps operators understand active configuration.
        """
        logger.info("=== Effective Configuration ===")
        logger.info(f"Network.host: {self.config.network.host}")
        logger.info(f"Network.port: {self.config.network.port}")
        logger.info(f"Network.http_port: {self.config.network.http_port}")
        logger.info(f"Network.mdns_name: {self.config.network.mdns_name}")
        logger.info(f"Devices: {len(self.state.devices)} configured")
        
        # Log device summary
        power_only = sum(1 for d in self.state.devices.values() if 'dim' not in d.capabilities)
        dimmable = len(self.state.devices) - power_only
        logger.info(f"  - Power-only devices: {power_only}")
        logger.info(f"  - Dimmable devices: {dimmable}")
        
        logger.info("================================")
    
    def _start_command_processors(self) -> None:
        """
        Start command processor tasks for each device per FR-070.
        
        Purpose:
            - Ensure deterministic command processing per device
            - Serialize commands for same device (sequential processing)
            - Allow concurrent processing across different devices
            
        Behavior:
            - Spawn one async task per device
            - Each task processes commands from device-specific queue
            - Commands acknowledged before next command starts
            - Errors handled gracefully without blocking queue
            
        Research References:
            - FR-070: Per-device command serialization required
            - research.md decision 6: Asyncio single-threaded, no locks needed
        """
        for device_uuid in self.state.devices.keys():
            # Spawn processor task for this device
            asyncio.create_task(self._device_command_processor(device_uuid))
            logger.debug(f"Started command processor for device {device_uuid}")
    
    async def _device_command_processor(self, device_uuid: str) -> None:
        """
        Process commands for a single device sequentially.
        
        Args:
            device_uuid: Device UUID to process commands for
            
        Behavior:
            - Run forever (until simulator shutdown)
            - Dequeue commands from device-specific queue
            - Process each command fully before starting next
            - Send acknowledgment for each command
            - Broadcast EVENT after state change
            - Handle errors without blocking subsequent commands
            
        Error Handling:
            - Log errors and continue processing
            - Queue never blocks due to one bad command
            - Device remains functional even after errors
            
        Research References:
            - FR-070: Sequential processing per device
            - research.md: Command queueing pattern
        """
        queue = self.state.command_queues[device_uuid]
        logger.debug(f"Command processor running for device {device_uuid}")
        
        try:
            while True:
                # Get next command from queue (blocks until available)
                command_data = await queue.get()
                
                try:
                    # Unpack command data
                    message = command_data['message']
                    writer = command_data['writer']
                    client_ip = command_data['client_ip']
                    
                    # Process the command
                    await self._process_control_command(
                        message, writer, client_ip, device_uuid
                    )
                    
                except Exception as e:
                    # Log error but continue processing queue
                    logger.error(
                        f"Error processing command for device {device_uuid}: {e}",
                        exc_info=True
                    )
                    
                finally:
                    # Mark task as done so queue.join() works if needed
                    queue.task_done()
                    
        except asyncio.CancelledError:
            # Graceful shutdown
            logger.debug(f"Command processor for device {device_uuid} cancelled")
            raise
    
    def _setup_signal_handlers(self) -> None:
        """
        Set up signal handlers for graceful shutdown per FR-010.
        
        Handles SIGTERM and SIGINT (Ctrl+C) to trigger clean shutdown.
        Shutdown timeout: 5 seconds maximum.
        
        Note: On Windows, signal handlers are not supported in ProactorEventLoop.
        This is acceptable for tests and development. For production use on Windows,
        consider using alternative shutdown mechanisms.
        """
        try:
            loop = asyncio.get_running_loop()
            
            def signal_handler(signum: int) -> None:
                """Trigger graceful shutdown when SIGTERM or SIGINT arrives.

                Only sets the shutdown event rather than tearing down directly:
                signal callbacks run in the event loop, so the actual cleanup
                is left to the main serve loop where it can await connection
                closure within the 5 second budget required by FR-010.
                """
                logger.info(f"Received signal {signum}, initiating graceful shutdown...")
                self._shutdown_event.set()
            
            # Register handlers for SIGTERM and SIGINT
            # Note: Not supported on Windows ProactorEventLoop
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(sig, lambda s=sig: signal_handler(s))
        except NotImplementedError:
            # Windows ProactorEventLoop doesn't support signal handlers
            # This is acceptable - tests can call shutdown() directly
            logger.debug("Signal handlers not available on this platform (likely Windows)")
    
    async def _whitespace_injector(self) -> None:
        """
        Background task that injects whitespace-only messages per FR-024.
        
        Behavior:
            - Run forever until cancelled
            - Check if whitespace injection is due
            - Send CRLF-only lines to active connection
            - Used to test integration buffer handling
            
        Research References:
            - FR-024: Whitespace injection at configurable intervals
            - research/whitespace-behavior-test-2025-10-18.md - Real hub
              doesn't send whitespace, this tests defensive code
        """
        logger.info("Whitespace injector task started")
        
        try:
            while True:
                # Check if injection is due
                if await self.quirk_manager.should_inject_whitespace():
                    # Get active connection writer
                    active_writer = self.state.active_connection
                    
                    if active_writer:
                        whitespace = self.quirk_manager.get_whitespace_message()
                        
                        try:
                            active_writer.write(whitespace.encode('utf-8'))
                            await active_writer.drain()
                            logger.debug("Injected whitespace message to active connection")
                        except Exception as e:
                            logger.warning(f"Failed to inject whitespace: {e}")
                
                # Sleep briefly to avoid busy loop
                await asyncio.sleep(0.1)
                
        except asyncio.CancelledError:
            logger.debug("Whitespace injector task cancelled")
            raise
    
    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter
    ) -> None:
        """
        Handle a single client connection.
        
        Args:
            reader: StreamReader for receiving data
            writer: StreamWriter for sending data
            
        Behavior:
            - Check quirk manager for connection refusal (FR-028, T050)
            - Apply connection delay if configured (latency simulation)
            - Log connection establishment with client IP (FR-048)
            - Process messages until disconnect or error
            - Clean up writer in finally block
            - Log disconnection with duration
            
        Research References:
            - research/connection-lifecycle-test-2025-10-18.md
            - research/multi-connection-test-2025-10-18.md - Passive rejection
        """
        # Get client address for logging
        peername = writer.get_extra_info('peername')
        client_ip = f"{peername[0]}:{peername[1]}" if peername else "unknown"
        
        # Check if connections should be refused (quirk injection for resilience testing)
        if self.quirk_manager.should_refuse_connection():
            connection_logger.info(
                f"Connection from {client_ip} REFUSED (quirk enabled)"
            )
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                # EXPECTED: Various I/O errors during connection close (ConnectionError, OSError, etc.)
                # WHY EXPECTED: Client may have disconnected, socket in bad state during refusal quirk
                # RECOVERY: Silent ignore - connection being refused anyway, cleanup is best-effort
                # RATIONALE: Catch-all acceptable here because all close() errors handled identically
                pass
            return
        
        # Apply connection delay if configured (latency simulation)
        connection_delay = await self.quirk_manager.get_connection_delay()
        if connection_delay > 0:
            logger.debug(
                f"Applying connection delay: {connection_delay}s for {client_ip}"
            )
            await asyncio.sleep(connection_delay)
        
        # Log connection event per FR-048
        connection_logger.info(f"Connection from {client_ip}")
        
        # Register as active connection (passive rejection model per FR-072)
        self.state.set_active_connection(writer)
        
        # Register with quirk manager for connection failure simulation (T069, T070)
        self.quirk_manager.set_active_connection(writer)
        
        # Track connection start time for duration logging
        import time
        connect_time = time.time()
        
        # Message buffer for incomplete messages per FR-087
        # Maximum 64KB to prevent memory exhaustion attacks
        MAX_MESSAGE_BUFFER = 64 * 1024  # 64KB per FR-087
        buffer = ""
        decoder = json.JSONDecoder()

        async def drain_buffer(current_buffer: str) -> str:
            """Parse complete JSON messages from buffer and process them."""
            nonlocal writer
            while current_buffer:
                stripped = current_buffer.lstrip("\r\n ")
                if stripped != current_buffer:
                    current_buffer = stripped
                if not current_buffer:
                    break

                try:
                    message_obj, index = decoder.raw_decode(current_buffer)
                except json.JSONDecodeError:
                    # Check if we have a complete line (ends with CRLF or LF)
                    # If so, it's malformed JSON that should be silently ignored per FR-077
                    crlf_pos = current_buffer.find('\r\n')
                    lf_pos = current_buffer.find('\n')
                    
                    if crlf_pos >= 0:
                        # Complete line with CRLF - malformed JSON, skip it per FR-077
                        malformed_line = current_buffer[:crlf_pos]
                        logger.debug(
                            f"Silently ignoring malformed JSON per FR-077: {malformed_line[:50]}..."
                        )
                        current_buffer = current_buffer[crlf_pos + 2:]
                        continue
                    elif lf_pos >= 0:
                        # Complete line with LF only - malformed JSON, skip it per FR-077
                        malformed_line = current_buffer[:lf_pos]
                        logger.debug(
                            f"Silently ignoring malformed JSON per FR-077: {malformed_line[:50]}..."
                        )
                        current_buffer = current_buffer[lf_pos + 1:]
                        continue
                    else:
                        # No line terminator yet - incomplete data, wait for more
                        break

                raw_json = current_buffer[:index]
                current_buffer = current_buffer[index:]

                if current_buffer.startswith("\r\n"):
                    current_buffer = current_buffer[2:]
                elif current_buffer.startswith("\n"):
                    current_buffer = current_buffer[1:]

                logger.info(f"[RECV] {client_ip}: {raw_json}")

                is_active = self.state.is_active_connection(writer)
                logger.debug(
                    f"Connection check for {client_ip}: is_active={is_active}, "
                    f"writer={id(writer)}, active_connection={id(self.state.active_connection) if self.state.active_connection else None}"
                )
                if not is_active:
                    logger.debug(
                        f"Ignoring message from zombie connection {client_ip} (passive rejection per FR-072)"
                    )
                    continue

                await self._process_message(raw_json + "\r\n", writer, client_ip)

            return current_buffer

        try:
            while True:
                raw = await reader.read(4096)

                if not raw:
                    buffer = await drain_buffer(buffer)
                    connection_logger.info(
                        f"Connection from {client_ip} closed by client "
                        f"(graceful or ungraceful disconnect per FR-086)"
                    )
                    break

                if len(raw) > MAX_MESSAGE_BUFFER:
                    connection_logger.warning(
                        f"Connection from {client_ip}: chunk size {len(raw)} bytes "
                        f"exceeds 64KB limit, dropping (FR-087)"
                    )
                    buffer = ""
                    continue

                try:
                    chunk = raw.decode("utf-8")
                except UnicodeDecodeError:
                    logger.debug(
                        f"Connection from {client_ip}: non-UTF8 data received, ignoring"
                    )
                    continue

                buffer += chunk

                if len(buffer) > MAX_MESSAGE_BUFFER:
                    connection_logger.warning(
                        f"Connection from {client_ip}: message buffer {len(buffer)} bytes "
                        f"exceeds 64KB limit, dropping (FR-087)"
                    )
                    buffer = ""
                    continue

                buffer = await drain_buffer(buffer)
                
        except asyncio.CancelledError:
            connection_logger.info(f"Connection from {client_ip} cancelled (shutdown)")
            raise
            
        except (ConnectionResetError, BrokenPipeError) as e:
            # Ungraceful disconnect (RST) per FR-086
            # Handle cleanly without affecting other connections
            connection_logger.info(
                f"Connection from {client_ip} reset by peer (ungraceful disconnect per FR-086): {e}"
            )
            
        except Exception as e:
            import traceback
            connection_logger.warning(f"Connection from {client_ip} unexpected error: {e}")
            connection_logger.warning(f"Traceback: {traceback.format_exc()}")
            
        finally:
            # Clear active connection if this was the active one (FR-072)
            # Per research/multi-connection-test-2025-10-18.md: When active connection closes,
            # clear the slot so new connections can become active
            if self.state.is_active_connection(writer):
                self.state.clear_active_connection(writer)
                connection_logger.info(
                    f"Active connection from {client_ip} closed, slot released"
                )
            else:
                connection_logger.info(
                    f"Zombie connection from {client_ip} closed"
                )
            
            # Clear quirk manager's active connection reference (T069, T070)
            self.quirk_manager.set_active_connection(None)
            
            # Clean up writer per asyncio best practices
            try:
                writer.close()
                await writer.wait_closed()
            except Exception as e:
                logger.debug(f"Error closing writer for {client_ip}: {e}")
            
            # Log disconnection with duration
            duration = time.time() - connect_time
            connection_logger.info(
                f"Connection from {client_ip} closed (duration: {duration:.1f}s)"
            )
    
    async def _process_message(
        self,
        line: str,
        writer: asyncio.StreamWriter,
        client_ip: str
    ) -> None:
        """
        Process a single message from a client.
        
        Args:
            line: Raw message line (JSON with CRLF)
            writer: StreamWriter to send response
            client_ip: Client IP address for logging
            
        Behavior:
            - Parse message using protocol.parse_message()
            - Route by message type to appropriate handler
            - Apply message delays if configured (FR-026, T050)
            - Inject malformed JSON if configured (FR-028, T050)
            - Handle malformed messages per FR-077 (silently ignore)
            - Handle unknown message types per FR-066 (REQUEST_UNKNOWN error)
            
        Research References:
            - FR-077: Malformed JSON silently ignored
            - FR-066: REQUEST_UNKNOWN error for invalid message types
            - FR-026: Response delays for message types
        """
        from deako_simulator.protocol import (
            parse_message,
            format_response,
            create_ping_response,
            create_error_response,
            create_device_list_response,
            create_device_poll_response,
        )
        
        logger.debug(f"[DEBUG] _process_message called for {client_ip}")
        
        # Parse message
        message = parse_message(line)
        
        logger.debug(f"[DEBUG] Parsed message: {message}")
        
        # Silently ignore malformed messages per FR-077
        if message is None:
            logger.debug(f"[DEBUG] Message is None, returning")
            return
        
        # Extract message type (accept both 'type' and 'name' for compatibility)
        # Real Deako hub uses 'type', but keep 'name' as fallback
        message_type = message.get('type', message.get('name', '')).upper()
        transaction_id = message.get('transactionId', 'unknown')
        
        # Apply message delay if configured (FR-026 quirk injection)
        if await self.quirk_manager.should_delay_message():
            delay = await self.quirk_manager.get_message_delay()
            if delay > 0:
                logger.debug(
                    f"Applying message delay: {delay}s for {message_type}"
                )
                await asyncio.sleep(delay)
        
        # Route to appropriate handler
        if message_type == 'PING':
            response = await self._handle_ping(message)
        elif message_type == 'DEVICE_LIST':
            response = await self._handle_device_list(message, writer, client_ip)
        elif message_type == 'DEVICE_POLL':
            response = await self._handle_device_poll(message)
        elif message_type == 'CONTROL':
            response = await self._handle_control(message, writer, client_ip)
        else:
            # Unknown message type - return REQUEST_UNKNOWN error per FR-066
            client_name = message.get('src', 'unknown')
            response = create_error_response(
                transaction_id=transaction_id,
                error_code="REQUEST_UNKNOWN",
                message=f"Unknown message type: {message_type}",
                client_name=client_name
            )
        
        # Send response (if not already sent by handler)
        if response:
            # Check if malformed JSON should be injected (FR-028 quirk)
            if await self.quirk_manager.should_inject_malformed_json():
                response_line = self.quirk_manager.get_malformed_json()
                logger.debug(f"Injecting malformed JSON instead of response")
            else:
                response_line = format_response(response)
            
            # Log sent message per FR-047 (timestamp, client IP, full content)
            logger.info(f"[SEND] {client_ip}: {response_line.rstrip()}")
            
            writer.write(response_line.encode('utf-8'))
            await writer.drain()
    
    async def _handle_ping(self, message: dict[str, Any]) -> dict[str, Any]:
        """
        Handle PING request per FR-021.
        
        Args:
            message: Parsed PING message dict
            
        Returns:
            PING response dict with status="ok" and timestamp
            
        Research References:
            - FR-021: PING requires transactionId, echo with status="ok"
        """
        from deako_simulator.protocol import create_ping_response
        
        transaction_id = message.get('transactionId', 'unknown')
        client_name = message.get('src', 'unknown')
        return create_ping_response(transaction_id, client_name)
    
    async def _handle_device_list(
        self,
        message: dict[str, Any],
        writer: asyncio.StreamWriter,
        client_ip: str,
    ) -> dict[str, Any] | None:
        """
        Handle DEVICE_LIST request per FR-016.
        
        Args:
            message: Parsed DEVICE_LIST message dict
            writer: StreamWriter to send DEVICE_FOUND messages
            client_ip: Client IP for logging
            
        Returns:
            None. The response and the DEVICE_FOUND stream are both written
            directly to the writer here, so there is nothing for the caller
            to send afterwards.

        Side Effects:
            - Writes the DEVICE_LIST response, then one DEVICE_FOUND per device
            - EVENTs may interleave after the response per FR-065 (asynchronous)

        Why the stream is written inline and undelayed:
            Hardware validation measured the real hub emitting the DEVICE_LIST
            response followed immediately by the full DEVICE_FOUND stream --
            32-37 devices delivered in ~89ms average, with no inter-message
            spacing. Streaming from a spawned task or inserting per-device
            delays would both be slower than the hardware and would race the
            client's read loop. FR-023's 100ms minimum applies to inbound
            CONTROL commands per device, not to outbound DEVICE_FOUND messages.

        Research References:
            - FR-016: DEVICE_LIST returns count, followed by DEVICE_FOUND stream
            - FR-065: EVENTs are never buffered ahead of the response; the
              validated sequence is response -> DEVICE_FOUND stream -> any
              EVENTs triggered by genuine external state changes
            - research/device-list-event-ordering-test-2025-10-25.md (10/10 tests,
              zero pre-response EVENTs)
        """
        from deako_simulator.protocol import (
            create_device_found,
            create_device_list_response,
            format_response,
        )

        transaction_id = message.get('transactionId', 'unknown')
        client_name = message.get('src', 'unknown')

        devices = self.state.get_all_devices()

        response = create_device_list_response(
            len(devices), transaction_id, client_name
        )
        response_line = format_response(response)
        logger.info(f"[SEND] {client_ip}: {response_line.rstrip()}")
        writer.write(response_line.encode('utf-8'))
        await writer.drain()

        for device in devices:
            try:
                df_line = format_response(create_device_found(device))
                logger.info(f"[SEND] {client_ip}: {df_line.rstrip()}")
                writer.write(df_line.encode('utf-8'))
                await writer.drain()
            except (ConnectionResetError, BrokenPipeError) as e:
                # Client hung up mid-stream; the real hub simply stops writing.
                logger.debug(
                    f"Client {client_ip} disconnected during DEVICE_FOUND stream: {e}"
                )
                break

        return None
    
    async def _handle_device_poll(self, message: dict[str, Any]) -> dict[str, Any]:
        """
        Handle DEVICE_POLL request per FR-017.
        
        Args:
            message: Parsed DEVICE_POLL message dict
            
        Returns:
            DEVICE_POLL response dict with device state (or error)
            
        Error Handling:
            - Missing 'uuid' field: REQUEST_MALFORMED (FR-066)
            - Non-existent device UUID: REQUEST_INVALID (FR-066)
            - Device not found message: "device could not be found"
            
        QUIRK: Returns status="error" even on successful query (FR-023)
        
        Research References:
            - FR-017: DEVICE_POLL returns current device state
            - FR-023: DEVICE_POLL returns status="error" on success (hardware quirk)
            - FR-066: Error codes for validation failures
            - research/device-state-test-2025-10-18.md: Validates status="error" quirk
        """
        from deako_simulator.protocol import create_device_poll_response, create_error_response
        
        transaction_id = message.get('transactionId', 'unknown')
        client_name = message.get('src', 'unknown')
        
        # Validate request structure - must have data.target field per FR-017
        if 'data' not in message or 'target' not in message.get('data', {}):
            return create_error_response(
                transaction_id=transaction_id,
                error_code="REQUEST_MALFORMED",
                message="Missing required field: data.target",
                message_type="DEVICE_POLL",
                client_name=client_name
            )
        
        device_uuid = message['data']['target']
        
        # Get device from state
        device = self.state.get_device(device_uuid)
        
        # Handle non-existent device per FR-066
        if device is None:
            return create_error_response(
                transaction_id=transaction_id,
                error_code="REQUEST_INVALID",
                message=f"device could not be found: {device_uuid}",
                message_type="DEVICE_POLL",
                client_name=client_name
            )
        
        # Return device state with status="error" quirk per FR-023
        return create_device_poll_response(device, transaction_id, client_name)
    
    async def _handle_control(
        self,
        message: dict[str, Any],
        writer: asyncio.StreamWriter,
        client_ip: str,
    ) -> dict[str, Any] | None:
        """
        Handle CONTROL request per FR-018 and FR-070.
        
        Args:
            message: Parsed CONTROL message dict
            writer: StreamWriter to send responses
            client_ip: Client IP for logging
            
        Returns:
            CONTROL response dict (or None if rate-limited or enqueued)
            
        Behavior (FR-070 compliant):
            - Validate request structure (transactionId, data.uuid, data.power or data.dim)
            - Check per-device rate limiting (100ms minimum spacing per FR-023)
            - If rate-limited: silently drop command, return None (no response)
            - Otherwise: ENQUEUE command to device-specific queue for serial processing
            - Return None immediately (processor task will send acknowledgment)
            
        Error Handling:
            - Missing required fields: REQUEST_MALFORMED (FR-066) - returned immediately
            - Non-existent device UUID: REQUEST_INVALID (FR-066) - returned immediately
            - Rate-limited: no response (silent drop per FR-023)
            
        Side Effects:
            - Enqueues command to device-specific queue (per FR-070)
            - Command processor task handles actual state update and acknowledgment
            
        Research References:
            - FR-018: CONTROL command structure and requirements
            - FR-023: Rate limiting (100ms minimum, silent drop)
            - FR-070: Per-device command serialization (MUST requirement)
            - research/rate-limiting-systematic-test-2025-10-18.md: Validated 100ms minimum
            - research.md decision 6: Deterministic serial processing per device
        """
        from deako_simulator.protocol import create_error_response
        
        transaction_id = message.get('transactionId', 'unknown')
        client_name = message.get('src', 'unknown')
        
        # Validate request structure - must have data field
        if 'data' not in message:
            return create_error_response(
                transaction_id=transaction_id,
                error_code="REQUEST_MALFORMED",
                message="Missing required field: data",
                message_type="CONTROL",
                client_name=client_name
            )
        
        data = message['data']

        # Support legacy payloads that use `target` or embed state under `data.state`
        device_uuid = data.get('uuid') or data.get('target')

        if device_uuid is None:
            return create_error_response(
                transaction_id=transaction_id,
                error_code="REQUEST_MALFORMED",
                message="Missing required field: data.uuid",
                message_type="CONTROL",
                client_name=client_name
            )

        # Extract desired state allowing nested "state" payloads
        nested_state = data.get('state') if isinstance(data.get('state'), dict) else {}
        power = data.get('power')
        dim = data.get('dim')

        if power is None and 'power' in nested_state:
            power = nested_state['power']
        if dim is None and 'dim' in nested_state:
            dim = nested_state['dim']

        if power is None and dim is None:
            return create_error_response(
                transaction_id=transaction_id,
                error_code="REQUEST_MALFORMED",
                message="Missing required field: data.power or data.dim",
                message_type="CONTROL",
                client_name=client_name
            )
        
        # Check if device exists
        device = self.state.get_device(device_uuid)
        if device is None:
            return create_error_response(
                transaction_id=transaction_id,
                error_code="REQUEST_INVALID",
                message=f"device could not be found: {device_uuid}",
                message_type="CONTROL",
                client_name=client_name
            )
        
        # Check rate limiting per device (100ms minimum per FR-023)
        # Per research/rate-limiting-systematic-test-2025-10-18.md:
        # - Commands arriving <100ms after previous are silently dropped
        # - "First-in-wins" behavior matches real hub
        # - No response sent for rate-limited commands
        if self.state.is_rate_limited(device_uuid):
            # Silently drop command - no response
            logger.debug(
                f"CONTROL command for device {device_uuid} rate-limited (dropped)"
            )
            return None  # Signal to _process_message: don't send response
        
        # Update last command time for rate limiting
        self.state.update_command_time(device_uuid)
        
        # Enqueue command to device-specific queue per FR-070
        # The command processor task will:
        # 1. Dequeue command
        # 2. Update device state
        # 3. Send acknowledgment
        # 4. Broadcast EVENT
        # This ensures sequential processing per device
        # Mutate message payload so downstream processor sees normalized fields
        normalized_data = dict(data)
        normalized_data['uuid'] = device_uuid
        normalized_data.pop('target', None)
        normalized_data.pop('state', None)
        if power is not None:
            normalized_data['power'] = power
        if dim is not None:
            normalized_data['dim'] = dim

        message['data'] = normalized_data

        command_data = {
            'message': message,
            'writer': writer,
            'client_ip': client_ip
        }
        
        await self.state.command_queues[device_uuid].put(command_data)
        logger.debug(f"CONTROL command enqueued for device {device_uuid}")
        
        # Return None - processor task will send acknowledgment per FR-070
        # This ensures acknowledgment sent AFTER processing, not before
        return None
    
    async def _process_control_command(
        self,
        message: dict[str, Any],
        writer: asyncio.StreamWriter,
        client_ip: str,
        device_uuid: str,
    ) -> None:
        """
        Process a CONTROL command from the device queue.
        
        Args:
            message: Parsed CONTROL message dict
            writer: StreamWriter to send acknowledgment
            client_ip: Client IP for logging
            device_uuid: Device UUID (already validated)
            
        Behavior:
            - Extract power and dim values from message
            - Update device state
            - Send acknowledgment to client
            - Broadcast EVENT to all connections after delay
            
        This method is called by the device command processor task,
        ensuring sequential processing per device per FR-070.
        
        Research References:
            - FR-070: Sequential processing ensures determinism
            - FR-075: EVENT contains full device state
            - research/physical-button-behavior-test-2025-10-18.md: EVENT timing
        """
        from deako_simulator.protocol import create_control_response, format_response
        
        transaction_id = message.get('transactionId', 'unknown')
        client_name = message.get('src', 'unknown')
        data = message['data']
        power = data.get('power')
        dim = data.get('dim')
        
        # Update device state
        try:
            updated_device = self.state.update_device_state(device_uuid, power, dim)
        except KeyError:
            # Device was removed - this shouldn't happen since we validated earlier
            logger.error(f"Device {device_uuid} disappeared during command processing")
            return
        
        # Send acknowledgment per FR-018
        response = create_control_response(transaction_id, status="ok", client_name=client_name)
        response_line = format_response(response)
        
        # Log sent message per FR-047
        logger.info(f"[SEND] {client_ip}: {response_line.rstrip()}")
        
        try:
            writer.write(response_line.encode('utf-8'))
            await writer.drain()
        except (ConnectionResetError, BrokenPipeError) as e:
            # Client disconnected - log and continue
            logger.debug(f"Client {client_ip} disconnected during CONTROL response: {e}")
            return
        
        # Spawn async task to broadcast EVENT after ~2s delay per research findings
        # Per research/physical-button-behavior-test-2025-10-18.md:
        # - EVENT broadcast occurs ~2 seconds after CONTROL acknowledgment
        # - EVENT contains full device state (power + dim), not just changed fields
        asyncio.create_task(
            self._broadcast_event_after_delay(updated_device, delay=2.0)
        )
    
    async def _broadcast_event_after_delay(self, device: Device, delay: float = 2.0) -> None:
        """
        Broadcast EVENT message after a delay.
        
        Args:
            device: Device instance with updated state
            delay: Delay in seconds before broadcasting (default 2.0)
            
        Behavior:
            - Wait for specified delay
            - Create EVENT message with full device state (power + dim)
            - Broadcast to active connection only
            - Handle broadcast failures gracefully
            
        Research References:
            - FR-075: EVENT contains full device state, not deltas
            - research/physical-button-behavior-test-2025-10-18.md: ~2s delay validated
        """
        from deako_simulator.protocol import create_event
        
        # Wait for delay
        await asyncio.sleep(delay)
        
        # Create EVENT message with full device state per FR-075
        # Include both power and dim, not just changed fields
        state = {
            "name": device.name,
            "power": device.state.power,
            "dim": device.state.dim
        }
        
        event_message = create_event(device.uuid, state)
        
        # Broadcast to active connection
        # Per FR-072: Only active connection receives EVENTs
        await self.state.broadcast_event(event_message)
    
    async def shutdown(self) -> None:
        """
        Gracefully shutdown the simulator per FR-010.
        
        Actions:
        1. Cancel background tasks (whitespace injector)
        2. Close TCP server (stop accepting new connections)
        3. Close all active client connections
        4. Unregister mDNS service
        5. Flush logs
        6. Cleanup resources
        
        Timeout: 5 seconds maximum per FR-010
        Signal handling: SIGTERM/SIGINT caught by _setup_signal_handlers()
        
        Raises:
            None - Best effort cleanup, errors are logged
        """
        logger.info("Shutting down simulator...")
        
        # Cancel whitespace injector task if running
        if self._whitespace_task and not self._whitespace_task.done():
            self._whitespace_task.cancel()
            try:
                await self._whitespace_task
            except asyncio.CancelledError:
                logger.debug("Whitespace injector task cancelled successfully")
            except Exception as e:
                logger.warning(f"Error cancelling whitespace task: {e}")
        
        try:
            # Close server to stop accepting new connections
            if self.server:
                self.server.close()
                await asyncio.wait_for(
                    self.server.wait_closed(),
                    timeout=2.0
                )
                logger.info("Telnet server closed")
        
        except asyncio.TimeoutError:
            logger.warning("Server close timeout (2s)")
        except Exception as e:
            logger.warning(f"Error closing server: {e}")
        
        # Note: Client connections are closed automatically when server closes
        # Each connection's _handle_connection finally block handles cleanup
        # No need to track and close connections explicitly
        
        # Clean up HTTP API server (T058)
        if self.http_runner:
            try:
                await asyncio.wait_for(
                    self.http_runner.cleanup(),
                    timeout=2.0
                )
                logger.info("HTTP API server closed")
            except asyncio.TimeoutError:
                logger.warning("HTTP API shutdown timeout (2s)")
            except Exception as e:
                logger.warning(f"Error closing HTTP API: {e}")
        
        # Unregister mDNS service (best effort, 2s timeout)
        try:
            await unregister_mdns(self.zeroconf, self.service_info)
        except Exception as e:
            logger.warning(f"Error unregistering mDNS: {e}")
        
        # Flush logs to ensure all messages written
        import logging
        for handler in logging.root.handlers:
            handler.flush()
        
        logger.info("Simulator shutdown complete")
    
    async def run_until_shutdown(self) -> None:
        """
        Run the simulator until shutdown signal received.
        
        Blocks until:
        - SIGTERM/SIGINT signal received
        - Manual shutdown() call
        - Unrecoverable error
        
        Example:
            >>> simulator = DeakoSimulator(state, config)
            >>> await simulator.start()
            >>> await simulator.run_until_shutdown()
        """
        try:
            # Wait for shutdown signal
            await self._shutdown_event.wait()
        finally:
            # Always clean up
            await self.shutdown()


# Implementation notes for future tasks:
"""
Upcoming Implementation (T029-T032):
------------------------------------

T029: Implement message processing loop in _handle_connection()
    - Parse incoming messages using protocol.parse_message()
    - Detect disconnection via empty readline()
    - Route messages to process_message()

T030: Implement process_message() method
    - Route by message type to handlers
    - Implement PING handler first
    - Handle unknown message types (FR-066)
    - Handle malformed messages (FR-077)

T031: Already implemented above in shutdown()

T032: Add detailed logging
    """
