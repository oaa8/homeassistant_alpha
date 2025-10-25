# Feature Specification: Deako Hub and Device Simulator

**Feature Branch**: `001-deako-hub-simulator`  
**Created**: October 15, 2025  
**Status**: Draft  
**Input**: User description: "I want to be able to test this codebase against a simulated Deako hub in a way that will fully exercise as much of the home assistant integration logic as possible. This means real telnet calls using real sockets. So what that means is that I'd like for you to write the specifications for a Deako simulator that can run here on Windows or MacOS with a real IP address such that anything discovering deako devices actually sees the simulator. It must replicate every single functionality (and quirk) of the deako hub and its devices. Additionally, it must have solid controls that will enable the right hooks for choosing all the scenarios to simulate"

## Hardware Validation Testing

All functional requirements have been validated against real Deako hub hardware (192.168.86.221:23) through systematic testing. **All 10 critical gap tests completed** as of October 20, 2025.

### Completed Hardware Tests

| Test | Research Document | Key Findings | Spec Impact |
|------|------------------|--------------|-------------|
| **#1: Rate Limiting** | [rate-limiting-systematic-test-2025-10-18.md](./research/rate-limiting-systematic-test-2025-10-18.md) | 100ms minimum spacing (not 800ms), silent dropping, no DEVICE_BUSY errors | FR-023, FR-064, FR-074 |
| **#2: Multi-Connection** | [multi-connection-test-2025-10-18.md](./research/multi-connection-test-2025-10-18.md) | Passive rejection: accepts connections but only first is functional | FR-072 |
| **#3: Dim Validation** | [dim-validation-test-2025-10-18.md](./research/dim-validation-test-2025-10-18.md) | No validation: accepts all values (-1, 101, 1000, decimals) | FR-071 |
| **#4: DEVICE_POLL** | [device-state-test-2025-10-18.md](./research/device-state-test-2025-10-18.md) | Works with correct format; quirk: returns status="error" on success | Multiple |
| **#5: Whitespace** | [whitespace-behavior-test-2025-10-18.md](./research/whitespace-behavior-test-2025-10-18.md) | Hub doesn't send whitespace, silently ignores client whitespace | FR-024, FR-026 |
| **#6: Physical Buttons** | [physical-button-behavior-test-2025-10-18.md](./research/physical-button-behavior-test-2025-10-18.md) | Immediate EVENTs with full state, toggle behavior, 436ms min interval | FR-075, FR-076 |
| **#7: Error Codes** | [error-code-validation-test-2025-10-18.md](./research/error-code-validation-test-2025-10-18.md) | Only 3 of 5 documented codes exist; malformed JSON silently dropped | FR-066, FR-077 |
| **#8: Message Format** | [message-format-edge-cases-test-2025-10-18.md](./research/message-format-edge-cases-test-2025-10-18.md) | Permissive parsing, uppercase types required, null="no change" | FR-078–FR-083 |
| **#9: Connection Lifecycle** | [connection-lifecycle-test-2025-10-18.md](./research/connection-lifecycle-test-2025-10-18.md) | No idle timeout (>5 min), immediate reconnect, robust disconnect handling | FR-084–FR-087 |
| **#10: Performance Limits** | [performance-limits-test-2025-10-20.md](./research/performance-limits-test-2025-10-20.md) | Silent degradation after burst (>50 cmd in 5s), 5-200ms response times, ~10 cmd/s max | FR-088–FR-091 |

### Test Scripts Location

All test scripts: `specs/001-deako-hub-simulator/tests/*.ps1`

### Critical Discoveries

1. **Rate Limiting Reality**: 100ms minimum (not 800ms documented), silent message dropping
2. **Connection Model**: Passive rejection (accepts multiple, only first functional)
3. **Input Permissiveness**: No validation on dim values, accepts all JSON with extra fields
4. **Error Codes**: Only 3 exist (REQUEST_UNKNOWN, REQUEST_MALFORMED, REQUEST_INVALID)
5. **Connection Lifecycle**: No timeout, immediate reconnect, broadcasts to idle connections
6. **DEVICE_POLL Quirk**: Returns status="error" even on successful query
7. **EVENT Format**: Always includes full device state (not deltas)
8. **Protection Mechanism**: Silent degradation after >50 commands in 5 seconds (no disconnect, no errors)
9. **Performance**: 5-200ms response times, ~10 cmd/s maximum throughput

## Clarifications

### Session 2025-10-25

- Q: When a device is added (via configuration file or HTTP API) without an explicit initial state, what should the default power and dim values be? → A: Require explicit state - no defaults. When adding a device, state (power and dim) must be explicitly specified. This enforces explicit test scenarios, predictable behavior free of assumptions, and clear intent in test configurations.
- Q: When a test scenario is activated via the HTTP API (POST /scenario/activate), what should happen to existing devices and active client connections? → A: Replace all devices, keep connections active. Scenario activation atomically replaces the entire device configuration with the scenario's device definitions, but client connections remain active. This mimics real-world behavior where devices can be added/removed from a hub while clients are connected, enabling tests of the integration's ability to handle dynamic device topology changes. Clients must re-query DEVICE_LIST to discover the new device set.

### Session 2025-10-15

- Q: How should the simulator handle shutdown signals (SIGTERM, SIGINT) from the operating system? → A: Graceful shutdown: Catch signals, close all client connections cleanly, flush logs, then exit within 5 seconds. This aligns with best practices for Python application lifecycle management and enables integration with process managers, container orchestration, and testing frameworks.
- Q: What logging library/framework should the simulator use for its observability requirements? → A: Standard Python logging: Use Python's built-in logging module with configurable handlers and formatters. This enables integration with existing logging infrastructure, supports multiple handlers (console, file, syslog), and allows developers to configure log levels and formats. JSON structured logging can be added as an optional formatter.
- Q: What concurrency model should the simulator use for handling multiple telnet connections and the HTTP API? → A: Asyncio: Use Python's asyncio for non-blocking I/O with async/await syntax. This is the modern Python standard for I/O-bound applications, aligns with Home Assistant and pydeako library usage, provides excellent performance for multiple concurrent connections, and integrates well with async HTTP frameworks (aiohttp, FastAPI).
- Q: How should the simulator be packaged and distributed for use by integration developers? → A: Python package (pip): Create installable package with pyproject.toml for pip/uv install. Supports editable installs (pip install -e . or uv pip install -e .) for local development, provides automatic entry points for command-line tools, clear dependency management, and works seamlessly with virtual environments. Compatible with uv for fast installation.
- Q: Which async HTTP framework should be used for the REST API control interface? → A: aiohttp: Mature, lightweight async HTTP server with excellent asyncio integration. Widely used, well-documented, provides all needed REST API features without unnecessary complexity, and integrates seamlessly with the asyncio-based telnet server.
- Q: Which control interface architecture should be implemented (HTTP REST API, CLI, configuration file with hot-reload, or hybrid)? → A: Hybrid (configuration file + HTTP REST API). Configuration file (YAML/JSON) provides version-controllable, reproducible test scenarios for initial setup. HTTP REST API enables runtime control, state inspection, and mid-test modifications. This combination supports both automated CI/CD testing and AI-agent-driven manual testing using existing tools (curl, Invoke-WebRequest). File interface = Infrastructure as Code for scenarios; HTTP interface = dynamic runtime control and observability.
- Q: Should the simulator enforce the documented 800ms rate limiting (DEVICE_BUSY responses) strictly, make it configurable, or ignore it based on observed reality? → A: Make rate limiting configurable but default to OFF/disabled. Real-world testing shows the hub handles messages much faster than the documented 800ms limit. Configuration allows testing both observed behavior (fast message handling) and documented edge cases (DEVICE_BUSY responses) when needed for specific test scenarios.
- Q: Should the configuration file support JSON only, YAML only, both formats, or a custom format? → A: JSON only. Start simple to avoid complexity; YAML support can be added later if needed. JSON is widely supported, machine-readable, and sufficient for initial implementation.
- Q: What minimum Python version should the simulator require (3.8+, 3.10+, 3.12+, 3.13+)? → A: Python 3.13+. This matches Home Assistant's current development requirement (verified from official developer documentation), ensuring the simulator works in the same environment where the integration is developed and tested.
- Q: Should device UUIDs be auto-generated, required in config, or support both approaches? → A: Auto-generate UUID v4 for devices when not explicitly provided in configuration; allow explicit UUIDs for reproducible tests. This reduces configuration burden while maintaining flexibility for scenarios requiring specific UUIDs.
- Q: How should the simulator be invoked (standalone command, module execution, both, or library import only)? → A: Support both standalone command (e.g., `deako-simulator` after pip install) and module execution (`python -m deako_simulator`). This provides convenience for quick usage and flexibility for debugging and custom environments.

### Session 2025-10-16

- Q: When configuring test scenarios (via JSON config file or HTTP API), how should scenario definitions be structured? → A: Full scenario descriptors: Each scenario is a complete JSON object defining all devices, states, enabled quirks, timing configurations, and expected behaviors in one atomic definition. This provides reproducible, version-controlled test cases with zero ambiguity, predictable CI/CD outcomes, and maximum debuggability.
- Q: When a scenario configuration file contains invalid or incomplete data (e.g., missing required fields, invalid UUIDs, out-of-range dim levels), how should the simulator respond? → A: Explicit validation: Validate all scenario data on load; reject invalid scenarios with descriptive error messages indicating exactly what fields/values are invalid. This catches configuration errors early (shift-left), provides actionable debugging information, and ensures CI/CD reliability by failing fast with clear guidance.
- Q: How should simulator logs be organized and structured for operational debugging and troubleshooting? → A: Single unified log: All events (connections, messages, API calls, errors) written to one log file with severity levels and component tags. This simplifies log management, enables chronological event correlation, and works well with standard log analysis tools.
- Q: How should runtime configuration (network settings, ports, API keys, log levels) be specified for different deployment environments (local dev, CI/CD, container)? → A: CLI arguments with precedence: Support command-line flags (--port, --log-level, --bind-ip) that override both env vars and config file; full precedence chain: CLI > env vars > config > defaults. This provides maximum flexibility: config files for baseline/scenarios (version-controlled), env vars for CI/Docker deployment, CLI for debugging overrides.
- Q: When mDNS service registration fails (port 5353 conflict, permissions issue, network unavailable), how should the simulator respond? → A: Configurable behavior: Default mode gracefully degrades (log WARNING with failure reason and guidance, continue startup); strict mode (--require-mdns CLI flag) treats mDNS as mandatory and fails startup with clear error. This enables protocol tests to run without mDNS while allowing discovery-focused tests to enforce mDNS availability.
- Q: When multiple clients send simultaneous control commands for the same device, how should the simulator handle concurrent modifications? → A: Serialize with acknowledgment: Queue control commands per device; process sequentially; acknowledge each command before processing next; broadcast each state change as it completes. This replicates likely real hardware behavior (physical devices serialize for safety), provides deterministic test outcomes, surfaces integration race conditions, and maintains clear audit trails for debugging.
- Q: When a control command contains invalid data values (out-of-range dim level like -1 or 150, non-numeric values, invalid boolean), how should the simulator respond? → A: Explicit error response: Return status "error" with error code REQUEST_INVALID and descriptive message indicating exact validation failure (e.g., "dim value 150 exceeds maximum 100"). This aligns with documented API error codes, enforces API contract, surfaces integration bugs immediately in testing, and provides actionable debugging feedback. NOTE: This behavior should be validated against real Deako hub when testing invalid dim values outside 0-100 range to ensure simulator matches actual hardware response.
- Q: How many simultaneous telnet connections should the simulator support, and what should happen when additional clients attempt to connect? → A: Single connection limit: Accept only one active telnet connection at a time; reject additional connection attempts (TCP RST or immediate close) while a connection is active; accept new connections after the previous connection closes. This matches reported real Deako hub constraint of single-connection-only behavior. NOTE: CRITICAL - This behavior MUST be validated against real Deako hub hardware before implementation planning to confirm: (1) whether hub truly limits to 1 connection or allows multiple, (2) exact rejection mechanism used (RST, graceful close, queue), and (3) any connection timeout behavior. Do not assume single-connection limit without hardware testing evidence.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Basic Hub Discovery and Connection (Priority: P1)

As an integration developer, I want to run the Deako simulator on my local machine so that the Home Assistant Deako integration can discover and connect to it using the same mDNS/Zeroconf discovery mechanism used with real hardware, allowing me to verify basic connectivity without physical devices.

**Why this priority**: This is the foundation for all testing. Without discovery and connection, no other functionality can be tested. This represents the minimum viable product.

**Independent Test**: Can be fully tested by starting the simulator, running Home Assistant with the Deako integration, and verifying that: (1) the integration discovers the simulated hub via mDNS/Zeroconf, (2) establishes a telnet connection on port 23, (3) receives initial handshake/welcome messages, and (4) maintains the connection. Delivers immediate value by replacing physical hardware for connection testing.

**Acceptance Scenarios**:

1. **Given** the simulator is started on Windows or MacOS, **When** a device scans for mDNS services with type "_telnet" and name "local-integration", **Then** the simulator must be discoverable with hostname, IP address, and port 23
2. **Given** the simulator is discoverable, **When** a telnet client connects to the simulator's IP on port 23, **Then** the simulator must accept the connection and maintain an open socket
3. **Given** a telnet connection is established, **When** the connection is idle, **Then** the simulator must send periodic keep-alive messages or handle inactivity as a real hub does
4. **Given** a telnet connection exists, **When** the client disconnects, **Then** the simulator must properly close the connection and allow reconnection

---

### User Story 2 - Device Discovery and State Queries (Priority: P1)

As an integration developer, I want the simulator to respond to device discovery commands with a configurable list of virtual light devices so that I can test how the integration handles device enumeration, state queries, and metadata retrieval without physical devices.

**Why this priority**: Device discovery and state reading are core to the integration's operation. This is essential for testing the integration's ability to list and display devices in Home Assistant.

**Independent Test**: Can be fully tested by connecting to the simulator via telnet, sending the device discovery command (e.g., JSON message requesting device list), and verifying that: (1) the simulator responds with a device count, (2) returns device metadata (UUID, name, capabilities), (3) responds to state queries with power and dim level, and (4) device list persists across queries. Delivers value by enabling testing of the light entity setup in Home Assistant.

**Acceptance Scenarios**:

1. **Given** the simulator has a configured set of virtual devices, **When** the client sends a "find devices" command, **Then** the simulator must respond with the total device count followed by individual device metadata messages
2. **Given** a device exists in the simulator, **When** the client queries that device's state by UUID, **Then** the simulator must respond with current power state (on/off) and dim level (0-100)
3. **Given** devices are configured with different capabilities, **When** the client requests device metadata, **Then** the simulator must correctly report whether each device supports dimming (dimmer vs. smart switch)
4. **Given** multiple state query requests, **When** no control commands have been issued, **Then** the simulator must return consistent state across all queries
5. **Given** the telnet connection drops and reconnects, **When** the client requests the device list again, **Then** the simulator must return the same configured devices (state persistence)

---

### User Story 3 - Device Control and State Updates (Priority: P1)

As an integration developer, I want to send control commands to simulated devices and receive state change confirmations so that I can verify the integration's ability to turn lights on/off and adjust brightness levels through the telnet protocol.

**Why this priority**: Control functionality is the core value proposition of the integration. Users expect to control their lights through Home Assistant, making this critical for MVP.

**Independent Test**: Can be fully tested by sending device control commands via telnet (e.g., turn on device X with dim level Y) and verifying that: (1) the simulator acknowledges the command, (2) updates internal device state, (3) subsequent state queries return the new state, and (4) the simulator sends unsolicited state update messages to connected clients. Delivers immediate value by enabling end-to-end testing of light control in Home Assistant.

**Acceptance Scenarios**:

1. **Given** a device is off, **When** a control command to turn it on is sent, **Then** the simulator must acknowledge the command and update the device state to on
2. **Given** a dimmable device, **When** a control command specifies a dim level (0-100), **Then** the simulator must store and report that dim level in subsequent state queries
3. **Given** a device state changes, **When** clients are connected, **Then** the simulator must broadcast unsolicited state update messages to all connected clients
4. **Given** rapid consecutive control commands for the same device, **When** each command specifies different states, **Then** the simulator must process them sequentially and settle on the final commanded state
5. **Given** a control command for a non-existent device UUID, **When** the command is received, **Then** the simulator must respond with an error message or silently ignore (matching real hub behavior)

---

### User Story 4 - Protocol Timing and Message Quirks (Priority: P2)

As an integration developer, I want the simulator to replicate known timing behaviors and protocol quirks of the real Deako hub so that I can test the integration's resilience to whitespace-only messages, message buffering issues, and variable response times.

**Why this priority**: The integration code contains multiple workarounds for protocol quirks (whitespace message handling, message buffer management, response timing). These must be testable to prevent regressions.

**Independent Test**: Can be fully tested by configuring the simulator to inject protocol quirks and verifying that: (1) the integration handles whitespace-only messages without errors, (2) message buffer doesn't overflow with buffered whitespace, (3) the integration recovers from delayed responses, and (4) error logging triggers appropriately. Delivers value by catching edge case bugs before production.

**Acceptance Scenarios**:

1. **Given** the simulator is configured to send whitespace-only messages, **When** these messages are interspersed with valid JSON messages, **Then** the integration must continue processing valid messages without error
2. **Given** the simulator sends a high volume of whitespace characters, **When** the empty message count exceeds 1000, **Then** the integration must detect this and trigger reconnection logic
3. **Given** a control command is sent, **When** the simulator is configured with a response delay, **Then** the response must arrive after the configured delay matching real hub behavior
4. **Given** multiple JSON messages arrive in a single telnet read, **When** messages are not newline-separated, **Then** the simulator must send them in the same format as the real hub (testing message buffer handling)
5. **Given** a device discovery command, **When** the simulator sends device metadata messages, **Then** there must be configurable delays between messages to simulate real hub timing

---

### User Story 5 - Configurable Test Scenarios (Priority: P2)

As an integration developer, I want to configure the simulator's behavior through a control interface so that I can simulate various test scenarios including device additions/removals, connection failures, slow responses, and error conditions without restarting the simulator.

**Why this priority**: Runtime configurability enables comprehensive testing of integration robustness, error handling, and recovery logic. This turns the simulator into a powerful testing tool.

**Independent Test**: Can be fully tested by starting the simulator with a control API (CLI, HTTP, or config file), modifying simulator behavior during runtime, and verifying that: (1) new devices appear in discovery, (2) removed devices disappear, (3) injected errors trigger integration error handling, and (4) behavior changes take effect immediately. Delivers value by enabling automated test suites and scenario-based testing.

**Acceptance Scenarios**:

1. **Given** the simulator is running with a control interface, **When** a new device is added via the control API, **Then** the next device discovery must include the new device
2. **Given** devices exist in the simulator, **When** a device is removed via the control API, **Then** subsequent device lists must not include that device
3. **Given** a control interface command to inject connection failures, **When** the next client connection attempt occurs, **Then** the simulator must refuse the connection or drop immediately after accepting
4. **Given** a control interface command to enable slow response mode, **When** any command is received, **Then** all responses must be delayed by the configured duration
5. **Given** a control interface command to simulate message loss, **When** specific message types are configured to drop, **Then** those messages must not be sent to clients
6. **Given** a control interface command to inject malformed JSON, **When** enabled, **Then** the simulator must send invalid JSON messages at configured intervals
7. **Given** the simulator is configured to simulate intermittent disconnections, **When** clients are connected, **Then** the simulator must randomly close connections based on configured probability

---

### User Story 6 - Multi-Client Connection Handling (Priority: P2) [PENDING HARDWARE VALIDATION]

**NOTE**: This user story is based on an assumption that real Deako hubs support multiple simultaneous connections. However, field reports suggest the hub may limit to a single active connection. This story MUST be validated against real Deako hub hardware before implementation. If the hub only supports single connection, this story should be revised to test single-connection enforcement and proper connection rejection mechanisms instead.

As an integration developer, I want the simulator to accurately replicate the real Deako hub's connection behavior so that I can test how the integration handles connection limits, whether that's single-connection-only with rejection handling or multi-client with state synchronization.

**Why this priority**: Connection behavior testing ensures the integration handles real hub constraints correctly, preventing production issues related to connection management.

**Independent Test**: Can be fully tested by opening multiple telnet connections to the simulator simultaneously (or testing single-connection rejection if that's the real hub behavior) and verifying the appropriate behavior based on real hardware constraints. If multi-client: all clients receive device discovery responses, state changes from one client are broadcast to others, each client maintains independent command/response flow, and disconnection of one client doesn't affect others. If single-client: second connection is rejected appropriately, first client continues functioning, and new connection succeeds after first disconnects. Delivers value by identifying connection management issues.

**Acceptance Scenarios** [TO BE REVISED AFTER HARDWARE VALIDATION]:

**IF Real Hub Supports Multiple Connections:**

1. **Given** the simulator accepts multiple connections, **When** two clients connect simultaneously, **Then** both must successfully establish connections and receive responses
2. **Given** multiple clients are connected, **When** one client sends a control command, **Then** all clients must receive the state update broadcast message
3. **Given** two clients send commands simultaneously, **When** commands affect the same device, **Then** the simulator must serialize command processing and broadcast final state to all clients
4. **Given** multiple clients are connected, **When** one client disconnects, **Then** other clients must continue functioning normally
5. **Given** a client performs device discovery, **When** another client is connected, **Then** discovery responses must not interfere with the other client's message stream

**IF Real Hub Limits to Single Connection (REPORTED BEHAVIOR):**

1. **Given** a client is connected to the simulator, **When** a second client attempts to connect, **Then** the second connection attempt must be rejected (via TCP RST or immediate close matching real hub mechanism)
2. **Given** a client is connected, **When** it disconnects, **Then** a new client connection attempt must succeed immediately
3. **Given** a client is connected, **When** a second client attempts to connect and is rejected, **Then** the first client must continue functioning normally without interruption
4. **Given** connection rejection occurs, **When** logged, **Then** the log must indicate the rejection reason and client IP for debugging

---

### User Story 7 - Connection Resilience and Recovery (Priority: P3)

As an integration developer, I want the simulator to support testing connection loss and recovery scenarios so that I can verify the integration's reconnection logic, state restoration, and error handling when network issues occur.

**Why this priority**: Connection resilience is important for production reliability but can be tested after core functionality works. This validates the integration's recovery mechanisms.

**Independent Test**: Can be fully tested by configuring the simulator to simulate network issues and verifying that: (1) the integration detects connection loss, (2) attempts reconnection, (3) re-discovers devices after reconnection, (4) restores device state, and (5) resumes normal operation. Delivers value by ensuring the integration recovers gracefully from network issues.

**Acceptance Scenarios**:

1. **Given** an established connection, **When** the simulator forcibly closes the connection, **Then** the integration must detect the disconnection and attempt to reconnect
2. **Given** the simulator is configured to refuse connections temporarily, **When** reconnection attempts occur, **Then** the integration must retry with appropriate backoff intervals
3. **Given** a connection is re-established after failure, **When** the client requests device discovery, **Then** the simulator must respond with the same device list as before
4. **Given** device states changed before connection loss, **When** the connection is restored, **Then** state queries must reflect the current state (state persistence)
5. **Given** the simulator simulates high latency, **When** commands are sent, **Then** the integration must handle timeouts appropriately without crashing

---

### User Story 8 - Logging and Observability (Priority: P3)

As an integration developer, I want the simulator to provide detailed logging of all protocol interactions so that I can diagnose issues, understand message flow, and verify that the integration sends correct commands in the expected format.

**Why this priority**: Observability is crucial for debugging but not required for basic functionality. This makes troubleshooting much more efficient.

**Independent Test**: Can be fully tested by enabling simulator logging and verifying that: (1) all incoming messages are logged with timestamps, (2) all outgoing messages are logged, (3) connection events are logged, (4) configuration changes are logged, and (5) logs are easily filterable by client or message type. Delivers value by accelerating debugging and issue resolution.

**Acceptance Scenarios**:

1. **Given** the simulator is running with logging enabled, **When** any telnet message is received, **Then** it must be logged with timestamp, client identifier, and full message content
2. **Given** the simulator sends a response, **When** the message is transmitted, **Then** it must be logged with the same detail as received messages
3. **Given** a client connects or disconnects, **When** the event occurs, **Then** it must be logged with client IP, timestamp, and connection duration
4. **Given** simulator configuration changes via control interface, **When** changes are applied, **Then** the configuration change must be logged with previous and new values
5. **Given** logging is configured with different verbosity levels, **When** the level is set to debug, **Then** all protocol details must be logged; when set to info, only major events must be logged

---

### Edge Cases

- What happens when a client sends commands faster than the configured message delay allows the simulator to respond?
- How does the simulator handle telnet protocol negotiation sequences (IAC, DO, DONT, WILL, WONT)?
- What happens when a device control command specifies an invalid dim level (e.g., -1, 101, non-numeric)? → RESOLVED: Return REQUEST_INVALID error with descriptive message; validate against real hardware
- How does the simulator handle extremely long device names or UUIDs that exceed expected buffer sizes?
- What happens when JSON messages are truncated or split across multiple telnet reads?
- How does the simulator handle clients that never send commands but hold connections open indefinitely?
- What happens when mDNS service registration fails (port 5353 in use)? → RESOLVED: Configurable behavior with --require-mdns flag
- How does the simulator handle system suspension/resume on the host machine?
- What happens when the simulator receives unrecognized JSON message types?
- How does the simulator handle UTF-8 encoded special characters in device names?
- What happens when multiple instances of the simulator try to start on the same machine?
- How does the simulator handle clients that disconnect without proper TCP close (abrupt network loss)?
- When multiple clients send simultaneous control commands for the same device, how are concurrent modifications handled? → RESOLVED: Per-device command queues with sequential processing and acknowledgment

## Requirements *(mandatory)*

### Functional Requirements

#### Discovery and Network

- **FR-001**: Simulator MUST advertise itself via mDNS/Zeroconf using service type "_telnet" with service name "local-integration" on the local network (verified against real hub and official API documentation)
- **FR-002**: Simulator MUST bind to a configurable IP address and port (default port 23) for telnet connections
- **FR-003**: Simulator MUST run on both Windows and MacOS operating systems without requiring platform-specific changes to configuration
- **FR-004**: Simulator MUST support binding to localhost (127.0.0.1) for isolated testing or to a LAN IP address for network-wide discovery
- **FR-005**: Simulator MUST allow configuration of the mDNS service name and hostname advertised to clients

#### Connection Management

- **FR-006**: Simulator MUST accept telnet connections on the configured port; implemented using Python asyncio with non-blocking I/O and async/await syntax for handling connections
- **FR-072**: Simulator MUST limit functionality to exactly one active telnet connection at a time to match real Deako hub behavior (validated October 2025); when a connection is active, additional TCP connection attempts MAY be accepted but MUST NOT receive protocol responses (passive rejection model matching real hub: accept socket but ignore all messages from non-active connections); only the first established connection processes and responds to messages; new connections MUST become functional after the previous active connection closes
- **FR-007**: Simulator MUST track which connection is the active connection and only send responses to that connection; zombie connections (accepted but inactive) MUST be logged for debugging but receive no protocol responses
- **FR-008**: Simulator MUST handle telnet protocol negotiation (IAC sequences) in a manner consistent with real Deako hubs
- **FR-009**: Simulator MUST detect client disconnections and properly clean up client session state
- **FR-010**: Simulator MUST support graceful shutdown that closes all client connections cleanly; MUST catch OS signals (SIGTERM, SIGINT), close all client connections with proper TCP close sequences, flush all logs, and exit within 5 seconds

#### Device Simulation

- **FR-011**: Simulator MUST support configuration of multiple virtual light devices with unique UUIDs; UUIDs are auto-generated (UUID v4 format) when not explicitly provided in configuration
- **FR-012**: Each virtual device MUST have configurable properties: UUID (optional, auto-generated if omitted), name, device type (dimmer or smart switch), initial state (required: power and dim must be explicitly specified)
- **FR-013**: Each virtual device MUST maintain internal state including: power (on/off), dim level (0-100 for dimmers only); state MUST be explicitly provided when adding devices via configuration file or HTTP API (no default state values to ensure explicit, predictable test scenarios)
- **FR-014**: Simulator MUST persist device state changes within a session (state survives across multiple queries)
- **FR-015**: Simulator MUST support runtime addition and removal of virtual devices through control interface

#### Protocol Implementation

- **FR-016**: Simulator MUST implement the "find devices" command that returns: device count, followed by individual device metadata messages (UUID, name, capabilities)
- **FR-017**: Simulator MUST implement device state query commands that return: power state (boolean), dim level (0-100 or null for non-dimmable)
- **FR-018**: Simulator MUST implement device control commands that accept: device UUID, target power state, optional dim level
- **FR-019**: Simulator MUST send control command acknowledgments in the same format as real Deako hubs
- **FR-020**: Simulator MUST broadcast unsolicited state update messages to all connected clients when device state changes
- **FR-075**: Simulator MUST include full device state in all EVENT messages, not just changed fields (verified October 2025: real hub includes both power and dim in EVENTs even when only power changed); EVENT format: `{"type": "EVENT", "src": "deako", "timestamp": <unix-epoch>, "data": {"eventType": "DEVICE_STATE_CHANGE", "target": "<device-uuid>", "state": {"power": <boolean>, "dim": <0-100 or null>}}}`; this enables clients to reconstruct complete device state from any EVENT without needing separate state queries
- **FR-076**: Simulator MUST support simulating physical button presses via HTTP API endpoint POST /devices/{uuid}/button; button press MUST toggle device power state (true→false, false→true) and immediately broadcast EVENT message to all connected telnet clients with full device state; button presses and CONTROL commands operate independently without conflicts (verified October 2025: physical button after CONTROL command works correctly); no artificial debouncing delay required (accept button press requests as fast as rate limiting allows, minimum ~100ms spacing)
- **FR-070**: Simulator MUST serialize control commands on a per-device basis: maintain a command queue for each device UUID, process commands sequentially, acknowledge each command before processing the next, and broadcast state change after each completed command; this ensures deterministic behavior and replicates likely real hardware serialization for device safety
- **FR-021**: Simulator MUST use JSON message format with required fields: transactionId (UUID v4 format) for solicited requests, type, src, dst, timestamp for responses, status ("ok" | "error") for responses, and data payload
- **FR-022**: Simulator MUST properly handle message framing (newline-delimited JSON or hub's actual framing)
- **FR-023**: Simulator MUST process commands at approximately 100ms per command to match real hub behavior (verified through systematic testing: 100ms spacing achieves 100% response rate, 50ms achieves 70%, 0ms achieves 5%); commands arriving while processing previous commands MUST be silently dropped without response (no DEVICE_BUSY errors); this replicates real hub's "first-in-wins" behavior where only the first command in a burst gets processed; optional DEVICE_BUSY error mode (configurable, defaults to OFF) can be enabled for testing integration error handling but should be clearly marked as non-realistic behavior

#### Protocol Quirks and Edge Cases

- **FR-024**: Simulator MUST support injection of whitespace-only messages at configurable intervals
- **FR-025**: Simulator MUST support sending messages with inconsistent newline/framing to test message buffer handling
- **FR-026**: Simulator MUST support configuration of response delays for all message types (per-message-type or global)
- **FR-027**: Simulator MUST handle commands for non-existent device UUIDs by responding with status "error" and data.code "DEVICE_UNKNOWN" (verified against official API documentation)
- **FR-071**: Simulator MUST accept all numeric dim values without validation errors, returning status "ok" (matching real hub behavior verified October 2025: tested values -1, 0, 50.5, 101, 255, 1000 all returned OK); simulator SHOULD clamp values internally to 0-100 range (negative values → 0, values >100 → 100) and truncate decimals to integers; simulator MUST NOT send REQUEST_INVALID errors for out-of-range dim values; optional strict validation mode (configurable via control API, defaults OFF) MAY enable REQUEST_INVALID errors for testing integration input validation, but this mode must be clearly documented as non-realistic behavior not matching real hub
- **FR-028**: Simulator MUST support injection of malformed JSON messages at configurable rates
- **FR-029**: Simulator MUST handle rapid successive commands for the same device by processing sequentially
- **FR-030**: Simulator MUST support simulation of partial message delivery (truncated JSON) to test buffer handling
- **FR-063**: Simulator MUST use CRLF line endings (`\r\n`) for all JSON messages, not just LF (`\n`) (verified requirement from official API documentation)
- **FR-064**: Simulator MUST NOT send DEVICE_BUSY errors by default (verified through testing: 110 commands at various speeds produced zero DEVICE_BUSY errors); real hub silently drops commands instead of sending error codes; optional testing mode can enable DEVICE_BUSY errors for integration testing purposes but this mode should be clearly documented as non-realistic behavior used only for testing error handling code paths
- **FR-065**: Simulator MUST send unsolicited EVENT messages before completing DEVICE_LIST response to replicate real hub behavior observed in testing
- **FR-074**: Simulator MUST replicate real hub's success rate curve based on command spacing: 0ms spacing yields ~5% response rate (1 out of 20 commands), 50ms spacing yields ~70% response rate (14 out of 20 commands), 100ms spacing yields 100% response rate (20 out of 20 commands); this replicates the first-command-wins pattern where only the first command in a burst receives a response and subsequent commands are silently dropped
- **FR-066**: Simulator MUST include status "error" field and error code in data.code for all error responses, using codes that exist on real hardware (verified October 2025): REQUEST_UNKNOWN (invalid message type), REQUEST_MALFORMED (valid JSON missing required fields), REQUEST_INVALID (invalid data values including non-existent device UUID); codes that do NOT exist on real hardware: DEVICE_BUSY (hub silently drops instead), DEVICE_UNKNOWN (hub returns REQUEST_INVALID with message "device could not be found"); optional testing modes may enable DEVICE_BUSY for error handling testing but must be clearly documented as non-realistic behavior
- **FR-077**: Simulator MUST silently ignore malformed JSON syntax (invalid JSON structure) without sending error responses or disconnecting the client (verified October 2025: real hub ignores invalid JSON like `{this is not valid json}` with no response); REQUEST_MALFORMED error code is only for valid JSON missing required message fields, not for JSON syntax errors; connection must remain functional after malformed JSON is received
- **FR-078**: Simulator MUST accept messages with extra/unknown fields and silently ignore them (verified October 2025: real hub accepts PING with extra fields like "extraField1", "extraField2", etc. and processes message normally); this permissive parsing enables protocol evolution where newer clients can work with older hubs
- **FR-079**: Simulator MUST enforce case-sensitive message type field (verified October 2025: real hub rejects lowercase "ping" with REQUEST_UNKNOWN error, requires uppercase "PING"); all message type strings must be uppercase: "PING", "CONTROL", "DEVICE_LIST", "DEVICE_POLL", "EVENT", "DEVICE_FOUND"
- **FR-080**: Simulator MUST accept JSON fields in any order (verified October 2025: real hub correctly parses JSON with fields in non-standard order like src, dst, type, transactionId); standard JSON parser behavior, do not rely on field ordering
- **FR-081**: Simulator MUST NOT require timestamp field in client-to-hub messages (verified October 2025: real hub accepts PING without timestamp field); timestamp field is optional for requests, hub adds timestamp to responses
- **FR-082**: Simulator MUST accept null values in state fields and interpret them as "no change" for that field (verified October 2025: real hub accepts CONTROL with dim=null and keeps current brightness); example: {"power": true, "dim": null} means turn on but don't change brightness
- **FR-083**: Simulator SHOULD implement reasonable string length limits for message fields (verified October 2025: real hub may silently drop messages with very long strings like 1000-char src field); practical limit likely 256-512 characters; beyond limits, silently drop message without error response to replicate real hub behavior

#### Connection Lifecycle

- **FR-084**: Simulator MUST NOT enforce idle timeout by default (verified October 2025: real hub allows idle connections to survive > 5 minutes with no messages sent); optional configurable timeout can be added for testing specific scenarios via HTTP API (/config/timeout), but default behavior is no timeout; idle connections continue receiving unsolicited EVENT broadcasts
- **FR-085**: Simulator MUST allow immediate reconnection after disconnect with no enforced delay (verified October 2025: real hub accepts new connection < 1 second after previous disconnect); connection resources must be released immediately on close to support rapid reconnect; no "cooldown" period between connections from same client
- **FR-086**: Simulator MUST handle both graceful (FIN) and ungraceful (RST) client disconnects without crashing or leaking resources (verified October 2025: real hub cleanly handles both TCP graceful shutdown and abrupt socket closure); properly clean up client state, device subscriptions, and buffered messages on disconnect regardless of disconnect method
- **FR-087**: Simulator MUST buffer incomplete messages (messages without CRLF line ending) until complete line received or connection closes (verified October 2025: real hub buffers incomplete JSON like `{"message":"PING"` without error until CRLF arrives or connection drops); on disconnect with incomplete buffer, discard buffer contents without generating error; maximum buffer size should be reasonable (e.g., 64KB) to prevent memory exhaustion attacks

#### Control Interface

- **FR-031**: Simulator MUST provide a hybrid control interface consisting of: (1) Configuration file (JSON format) for initial setup, test scenario definitions, and version-controlled reproducible configurations; and (2) HTTP REST API for runtime control, state inspection, scenario activation, and dynamic modifications during test execution. The HTTP API MUST bind to a configurable port (default 8080, separate from telnet port 23) and provide endpoints for all runtime operations (device management, scenario activation, state queries, quirk injection, client management). HTTP API implemented using aiohttp for asyncio-compatible non-blocking operation.
- **FR-032**: Control interface MUST support adding devices with: UUID, name, device type, initial state (via both config file and HTTP POST /devices)
- **FR-033**: Control interface MUST support removing devices by UUID (via both config file and HTTP DELETE /devices/{uuid})
- **FR-034**: Control interface MUST support modifying device state directly (bypassing protocol commands) for scenario setup (via HTTP PATCH /devices/{uuid}/state)
- **FR-035**: Control interface MUST support enabling/disabling protocol quirks: whitespace injection, message delays, malformed JSON, connection drops (via HTTP POST /quirks/enable and /quirks/disable)
- **FR-036**: Control interface MUST support configuration of message delay timings and rate limiting behavior including: global/per-message-type delays, rate limiting enable/disable, and rate limit threshold (e.g., 800ms) (via HTTP PATCH /config/timing)
- **FR-037**: Control interface MUST support triggering immediate disconnect of specific clients or all clients (via HTTP DELETE /clients/{id} or DELETE /clients)
- **FR-038**: Control interface MUST support querying current simulator state: connected clients, device list, current configuration (via HTTP GET /status, GET /devices, GET /clients, GET /config)
- **FR-039**: Control interface HTTP API MUST be accessible without disrupting active telnet connections (runs on separate port with independent thread/async context)

#### Configuration

- **FR-040**: Simulator MUST load initial configuration from a file (JSON format)
- **FR-041**: Configuration file MUST support defining: network settings (IP, port, mDNS name), HTTP API port, initial device list, default protocol behaviors
- **FR-042**: Configuration file MUST support defining test scenarios as complete, self-contained JSON objects that include all devices, states, enabled quirks, timing configurations, and expected behaviors; scenarios can be activated by name via control interface (HTTP POST /scenario/activate endpoint) for reproducible testing; scenario activation atomically replaces the entire device configuration with the scenario's device definitions while keeping client connections active, enabling tests of dynamic device topology changes
- **FR-043**: Simulator MUST validate all scenario data on load with explicit validation rules: required fields presence, UUID format correctness, value range compliance (dim: 0-100, valid device types, valid capability strings); invalid scenarios MUST be rejected with descriptive error messages indicating exact field paths and validation failures (e.g., "scenarios[2].devices[5].dim: value 150 exceeds maximum 100")
- **FR-044**: Simulator MUST support default configuration values allowing zero-configuration startup for basic testing
- **FR-067**: Simulator MUST support configuration precedence chain: CLI arguments > environment variables > config file > built-in defaults; command-line flags (--port, --bind-ip, --log-level, --config, --api-port) override environment variables (DEAKO_SIM_PORT, DEAKO_SIM_BIND_IP, DEAKO_SIM_LOG_LEVEL, DEAKO_SIM_CONFIG, DEAKO_SIM_API_PORT) which override config file values
- **FR-068**: Simulator MUST log the effective configuration on startup showing the source of each setting (CLI/env/config/default) for operational transparency
- **FR-069**: Simulator MUST support --require-mdns CLI flag that makes mDNS registration mandatory; when enabled, simulator fails startup with clear error if mDNS registration fails; when disabled (default), simulator logs WARNING on mDNS failure and continues with telnet/HTTP services
- **FR-061**: Configuration file MUST support defining HTTP API endpoints as disabled (api_enabled: false) for scenarios where only file-based configuration is needed without runtime control

#### Logging and Observability

- **FR-045**: Simulator MUST log all events to a single unified log file with: timestamp, severity level (DEBUG/INFO/WARNING/ERROR), component tag (telnet/http/simulator/connection), client identifier (where applicable), and event details; implemented using Python's standard logging module with configurable handlers (console, file) and formatters
- **FR-046**: Simulator MUST log all received telnet messages with: timestamp, client identifier, full message content, component tag "telnet.recv"
- **FR-047**: Simulator MUST log all sent telnet messages with: timestamp, client identifier, full message content, component tag "telnet.send"
- **FR-048**: Simulator MUST log connection events: client connections, disconnections, errors with client IP, timestamps, and component tag "connection"
- **FR-049**: Simulator MUST log HTTP API requests and responses with: endpoint, method, status code, client IP, component tag "http"
- **FR-050**: Simulator MUST log configuration changes via control interface with: changed settings, old/new values, component tag "config"
- **FR-051**: Simulator MUST support configurable log levels: debug, info, warning, error
- **FR-052**: Simulator MUST write logs to both console output and optional log file
- **FR-053**: Log entries MUST include component tags enabling filtering by subsystem (e.g., grep for "telnet" or "http" events)

#### Error Handling

- **FR-054**: Simulator MUST handle port binding failures gracefully and report clear error messages
- **FR-055**: Simulator MUST handle mDNS registration failures based on configuration: in default mode, log WARNING with specific failure reason (port conflict, permissions, network unavailable) and actionable guidance, then continue startup with telnet/HTTP services fully functional; in strict mode (--require-mdns flag), treat mDNS registration as mandatory and fail startup with clear error message
- **FR-056**: Simulator MUST handle malformed JSON commands without crashing
- **FR-057**: Simulator MUST handle unexpected client disconnections without affecting other connected clients
- **FR-058**: Simulator MUST continue operating if log file writing fails (fall back to console-only logging)
- **FR-062**: Simulator MUST validate configuration files on startup and provide detailed error messages for validation failures including exact field paths, expected vs. actual values, and constraint violations; invalid scenarios are rejected but simulator continues if at least one valid scenario (or default configuration) exists

### Key Entities

- **VirtualDevice**: Represents a simulated Deako light device with UUID, name, device type (dimmer/switch), current power state (on/off), current dim level (0-100), and capability flags. Maintains state throughout simulator lifecycle.

- **ClientSession**: Represents a connected telnet client with socket connection, unique session identifier, connection timestamp, message queue for outbound messages, and session state. Multiple sessions can exist simultaneously.

- **Message**: Represents protocol messages exchanged between clients and simulator with message type (device_discovery, state_query, control_command, state_update, etc.), payload (JSON content), target device UUID (if applicable), timestamp, and source client identifier. Messages flow bidirectionally.

- **SimulatorConfiguration**: Represents runtime configuration with network settings (IP, port, mDNS name), device definitions, protocol behavior settings (message delays, quirk enablement), logging configuration, and active test scenario. Can be modified at runtime via control interface.

- **TestScenario**: Represents a complete, self-contained collection of configuration settings that can be activated to simulate specific testing conditions. Each scenario is an atomic JSON object defining all devices, their states, enabled quirks, timing configurations, and expected behavior descriptions. Scenarios are version-controllable, reproducible test cases that can be loaded by name via control interface.

## Research Findings *(live protocol testing)*

### Session 2025-01-15 - Real Deako Hub Protocol Testing

**Test Environment**: Connected to real Deako hub at 192.168.86.221:23 via telnet

**Official Documentation Source**: https://github.com/DeakoLights/local-integrations/blob/master/API.md

#### Discovered Protocol Details

**Message Structure**:
```json
// Solicited Request (client → hub)
{
  "transactionId": "UUID-v4",  // Required for all solicited requests
  "type": "MESSAGE_TYPE",
  "dst": "deako",              // Always "deako" for hub
  "src": "CLIENT_NAME",        // Client identifier
  "data": {...}                // Message-specific payload
}

// Solicited Response (hub → client)
{
  "transactionId": "SAME_UUID",  // Matches request UUID
  "type": "MESSAGE_TYPE",
  "dst": "CLIENT_NAME",
  "src": "deako",
  "timestamp": 1760591917,       // Unix epoch timestamp
  "status": "ok" | "error",      // Request status
  "data": {...}
}

// Unsolicited Message (hub → client)
{
  "type": "MESSAGE_TYPE",
  "src": "deako",
  "timestamp": 1760591917,
  "data": {...}
}
```

**Critical Protocol Requirements**:
- All messages MUST be single-line JSON terminated with CRLF (`\r\n`)
- Minimum 800ms spacing required between messages sent to hub
- TransactionId MUST be UUID v4 format for request/response matching
- Hub sends unsolicited EVENT messages before DEVICE_LIST responses

**Message Types Observed**:

1. **DEVICE_LIST**: Request device count
   - Request: `{"transactionId": "uuid", "type": "DEVICE_LIST", "dst": "deako", "src": "client"}`
   - Response: `{"type": "DEVICE_LIST", "transactionId": "uuid", ..., "status": "ok", "data": {"number_of_devices": 37}}`
   - Hub sends EVENT messages before responding to DEVICE_LIST

2. **DEVICE_FOUND**: Unsolicited device metadata stream
   - Sent immediately after DEVICE_LIST response
   - One message per device with: uuid, name, capabilities, state
   - Example: `{"type": "DEVICE_FOUND", "src": "deako", "timestamp": 1760591917, "data": {"name": "Master Bedroom Lights", "uuid": "50361c15-9739-4326-aded-24441cdbc75e", "capabilities": "power+dim", "state": {"power": true, "dim": 39}}}`

3. **EVENT (DEVICE_STATE_CHANGE)**: Unsolicited state updates
   - Sent when device state changes (manual control, other clients, etc.)
   - Example: `{"type": "EVENT", "src": "deako", "timestamp": 1760591877, "data": {"eventType": "DEVICE_STATE_CHANGE", "target": "uuid", "state": {"power": true}}}`
   - Can arrive at any time, including during DEVICE_LIST processing

4. **CONTROL**: Change device state
   - Request: `{"transactionId": "uuid", "type": "CONTROL", "dst": "deako", "src": "client", "data": {"target": "device-uuid", "state": {"power": true, "dim": 50}}}`
   - Response includes status, timestamp

5. **PING**: Keep-alive mechanism
   - Request: `{"transactionId": "uuid", "type": "PING", "dst": "deako", "src": "client"}`
   - Response: `{"transactionId": "uuid", "type": "PING", ..., "status": "ok"}`

6. **DEVICE_POLL**: Query individual device state
   - Request: `{"transactionId": "uuid", "type": "DEVICE_POLL", "dst": "deako", "src": "client", "data": {"target": "device-uuid"}}`

**Device Capabilities**:
- `"power"`: On/off only (switches, fans)
- `"power+dim"`: On/off plus dim level 0-100 (dimmers)

**State Structure**:
- Power: boolean `{"power": true}` or `{"power": false}`
- Dim: integer 0-100 `{"dim": 39}` (only present for power+dim devices)

**Error Handling** (from API.md):
- `DEVICE_BUSY`: Hub processing other requests (retry)
- `DEVICE_UNKNOWN`: Target device UUID not found
- `REQUEST_UNKNOWN`: Unsupported request type
- `REQUEST_MALFORMED`: Invalid JSON structure
- `REQUEST_INVALID`: Invalid data values (e.g., bad UUID format)

**mDNS Discovery** (CORRECTED):
- Service Type: `"_telnet"` (NOT "_deako._tcp.local." as initially assumed)
- Service Name: `"local-integration"`
- Port: 23 (telnet)
- Connection Flow: Discover via mDNS → Connect to IP:23 → Send DEVICE_LIST

**Observed Quirks**:
- Unsolicited EVENT messages arrive before DEVICE_LIST response completes
- DEVICE_FOUND messages stream rapidly after DEVICE_LIST (37 devices in ~1 second)
- No initial handshake or welcome message on connection
- Hub tolerates multiple connections simultaneously
- Messages are NOT prefixed with whitespace in this test (may vary by hub firmware)

**Test Results Summary**:
- ✅ TCP connection established successfully
- ✅ DEVICE_LIST request acknowledged with correct transactionId
- ✅ Received 37 DEVICE_FOUND messages with complete metadata
- ✅ Unsolicited EVENT messages received during DEVICE_LIST processing
- ✅ All messages follow documented JSON structure
- ✅ Both "power" and "power+dim" capabilities observed
- ✅ State includes power (boolean) and dim (0-100) fields

#### Specification Updates Required

The following functional requirements have been updated based on research:

- ✅ **FR-001**: mDNS service type MUST be "_telnet" with service name "local-integration" (verified against official API documentation)
- ✅ **FR-021**: TransactionId (UUID v4) required for all solicited requests
- ✅ **FR-023**: Updated with actual timing behavior - 100ms processing per command, silent dropping instead of errors (verified through systematic testing October 2025)
- ✅ **FR-027**: Non-existent device UUIDs return error response with `status: "error"` and `data.code: "DEVICE_UNKNOWN"`
- ✅ **FR-063**: All messages use CRLF (`\r\n`) line endings
- ✅ **FR-064**: Updated to reflect that DEVICE_BUSY errors do NOT occur in real hubs; silent dropping is actual behavior (verified: 110 commands tested, zero DEVICE_BUSY errors)
- ✅ **FR-065**: Unsolicited EVENT messages sent before DEVICE_LIST response completes
- ✅ **FR-066**: All error responses include `status: "error"` and error code in `data.code`
- ✅ **FR-074**: NEW - Success rate curve based on command spacing (0ms=5%, 50ms=70%, 100ms=100%) replicates first-command-wins pattern
- ✅ **FR-075**: NEW - EVENT messages must include full device state (power + dim), not just changed fields (verified October 2025: physical button tests confirmed full state always included)
- ✅ **FR-076**: NEW - Physical button simulation via HTTP API, toggle behavior, immediate EVENT broadcast, no conflicts with CONTROL commands (verified October 2025: minimum ~430ms between physical button presses, no debouncing needed)
- ✅ **FR-066**: UPDATED - Only 3 of 5 documented error codes actually exist (verified October 2025: REQUEST_UNKNOWN, REQUEST_MALFORMED, REQUEST_INVALID exist; DEVICE_BUSY and DEVICE_UNKNOWN do not exist)
- ✅ **FR-077**: NEW - Malformed JSON silently ignored (no error response), REQUEST_MALFORMED only for valid JSON missing fields
- ✅ **FR-078**: NEW - Extra/unknown fields accepted and ignored (permissive parsing for protocol evolution)
- ✅ **FR-079**: NEW - Message type field is case-sensitive (must be uppercase like "PING" not "ping")
- ✅ **FR-080**: NEW - JSON field order independent (standard JSON parser behavior)
- ✅ **FR-081**: NEW - Timestamp field optional in client messages (hub adds to responses)
- ✅ **FR-082**: NEW - Null values in state fields mean "no change" (verified: dim=null keeps current brightness)
- ✅ **FR-083**: NEW - String length limits exist (~256-512 chars practical limit, very long strings silently dropped)
- ✅ **FR-084**: NEW - No idle timeout by default (verified: connection survives > 5 minutes idle, continues receiving EVENTs)
- ✅ **FR-085**: NEW - Immediate reconnection allowed (verified: < 1 second reconnect works, no cooldown period)
- ✅ **FR-086**: NEW - Robust disconnect handling (verified: graceful FIN and ungraceful RST both handled cleanly)
- ✅ **FR-087**: NEW - Incomplete message buffering (verified: incomplete JSON buffered, discarded on disconnect)

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Integration developers can discover and connect to the simulator using the unmodified Home Assistant Deako integration within 30 seconds of simulator startup
- **SC-002**: Simulator successfully handles at least 5 simultaneous telnet client connections without message loss or cross-contamination
- **SC-002-REVISED**: [PENDING HARDWARE VALIDATION] Simulator accurately replicates real Deako hub connection behavior (reported as single-connection-only); if hub limits to 1 connection, simulator must reject additional attempts with same mechanism as real hub; if hub allows multiple, original SC-002 applies; validation against real hardware required before finalizing this criterion
- **SC-003**: All device control commands (power on/off, dim level changes) are processed and confirmed within 500ms under normal configuration
- **SC-004**: Simulator can run continuously for 24 hours while handling at least 10,000 control commands without memory leaks or crashes
- **SC-005**: Protocol quirk injection (whitespace messages, delays, malformed JSON) triggers appropriate error handling in the integration 100% of the time without causing integration crashes
- **SC-006**: Test scenarios can be configured and activated through the control interface with changes taking effect within 1 second
- **SC-007**: All protocol messages (sent and received) are logged with sufficient detail to reconstruct the complete message flow during debugging
- **SC-008**: Simulator startup completes within 5 seconds with default configuration on standard development hardware; can be invoked via standalone command (e.g., `deako-simulator`) or module execution (`python -m deako_simulator`); distributed as pip-installable Python package with pyproject.toml supporting editable installs (pip install -e . or uv pip install -e .) for local development workflow; supports configuration via CLI arguments, environment variables, and config file with precedence CLI > env > config > defaults
- **SC-009**: Integration developers can create and configure a new test scenario in under 5 minutes using the control interface or configuration file
- **SC-010**: 95% of real Deako hub protocol behaviors identified in the integration code are accurately replicated by the simulator

## Assumptions

1. **Protocol Documentation**: Assumed that the protocol implementation can be reverse-engineered from the pydeako library and integration code, as official protocol documentation may not be available
2. **Message Format**: Assumed JSON-based protocol with newline-delimited messages based on integration code analysis
3. **Python Implementation**: Assumed simulator will be implemented in Python for maintainability and ecosystem compatibility, though not strictly required
4. **Single Hub**: Assumed simulator represents a single hub instance; multiple hubs would require multiple simulator instances
5. **IPv4**: Assumed IPv4 networking; IPv6 support not required initially
6. **Device Types**: Assumed only two device types (dimmer, smart switch) based on current integration support
7. **State Persistence**: Assumed device states only need to persist during simulator runtime, not across restarts, unless configured otherwise
8. **Control Interface**: Assumed HTTP REST API as the most flexible control interface option, but CLI or file-based alternatives are acceptable
9. **No Authentication**: Assumed simulator does not implement authentication on telnet or control interfaces for testing simplicity
10. **Testing Focus**: Assumed primary use case is automated integration testing, not production use or end-user scenarios

## Open Questions

None - all requirements are specified with reasonable defaults based on integration code analysis.

## Dependencies

- **pydeako library**: Simulator protocol implementation must align with pydeako library expectations (version 0.3.1 as indicated in manifest.json)
- **mDNS/Zeroconf library**: Requires mDNS service advertisement capability (python-zeroconf library)
- **HTTP framework**: Requires aiohttp for asyncio-compatible REST API control interface
- **asyncio**: Python 3.13+ built-in asyncio for concurrent connection handling
- **Python logging**: Python 3.13+ built-in logging module for observability
- **Network availability**: Requires available network interface, port 23 (or configured port) for telnet, and port 8080 (or configured port) for HTTP API
- **Python runtime**: Requires Python 3.13+ (matching Home Assistant's current development requirement)
- **Package management**: Distributed as pip-installable package with pyproject.toml; supports pip or uv for installation

## Out of Scope

- **Cloud connectivity**: Simulator does not replicate any cloud-based Deako services or remote access features
- **Firmware updates**: Simulator does not simulate firmware update protocols or version management
- **Physical device behaviors**: Simulator does not replicate electrical characteristics, dimming curves, or hardware-specific behaviors beyond protocol responses
- **Mobile app protocol**: Simulator does not implement any mobile app-specific protocols if different from the local API
- **Production deployment**: Simulator is for testing only; no security hardening or production-ready deployment features
- **Real device proxy**: Simulator does not act as a proxy or gateway to real Deako devices
- **Automated test framework**: While the simulator enables testing, creating comprehensive automated test suites is out of scope for the simulator itself
- **Integration with CI/CD**: Simulator provides the foundation for CI/CD integration but does not include CI/CD pipeline configuration
- **Performance stress testing**: While the simulator must handle normal load, extreme stress testing beyond typical integration testing scenarios is out of scope

## Notes

- The integration code reveals several workarounds for protocol issues (whitespace handling, message buffering, connection management). The simulator must replicate these issues to validate that workarounds function correctly.
- The configurable `telnet_message_receive_delay` parameter in the integration (default 0.1s) suggests timing sensitivity. The simulator should make delays configurable to test this parameter's effectiveness.
- The integration implements custom `parse_data` logic to handle whitespace message streams, suggesting this is a known protocol quirk that must be replicated.
- The integration uses atomic operations for state management, suggesting potential race conditions or concurrency issues that the multi-client simulator should help surface.
- Consider implementing the simulator as a standalone Python package that can be installed via pip for easy distribution to other developers

---

## Appendix: Hardware Testing Research

All functional requirements above have been validated through systematic hardware testing. Research documents contain detailed findings, test methodologies, and raw data.

### Complete Research Index

1. **[Rate Limiting (100ms minimum)](./research/rate-limiting-systematic-test-2025-10-18.md)** - FR-023, FR-064, FR-074  
   Test: [`tests/test-rate-limiting-v2.ps1`](./tests/test-rate-limiting-v2.ps1)

2. **[Multi-Connection (Passive Rejection)](./research/multi-connection-test-2025-10-18.md)** - FR-072  
   Test: [`tests/test-multi-connection.ps1`](./tests/test-multi-connection.ps1)

3. **[Dim Validation (No Validation)](./research/dim-validation-test-2025-10-18.md)** - FR-071  
   Test: [`tests/test-dim-edge-cases.ps1`](./tests/test-dim-edge-cases.ps1)

4. **[Device State & DEVICE_POLL](./research/device-state-test-2025-10-18.md)** - Multiple FRs  
   Tests: [`tests/test-device-state.ps1`](./tests/test-device-state.ps1), [`tests/test-device-poll-systematic.ps1`](./tests/test-device-poll-systematic.ps1)

5. **[Whitespace Behavior](./research/whitespace-behavior-test-2025-10-18.md)** - FR-024, FR-026  
   Test: [`tests/test-whitespace-behavior.ps1`](./tests/test-whitespace-behavior.ps1)

6. **[Physical Button Behavior](./research/physical-button-behavior-test-2025-10-18.md)** - FR-075, FR-076  
   Test: [`tests/test-physical-button-behavior.ps1`](./tests/test-physical-button-behavior.ps1)

7. **[Error Code Validation (3 of 5 exist)](./research/error-code-validation-test-2025-10-18.md)** - FR-066, FR-077  
   Test: [`tests/test-error-codes.ps1`](./tests/test-error-codes.ps1)

8. **[Message Format Edge Cases](./research/message-format-edge-cases-test-2025-10-18.md)** - FR-078 through FR-083  
   Test: [`tests/test-message-format-edge-cases.ps1`](./tests/test-message-format-edge-cases.ps1)

9. **[Connection Lifecycle (No timeout, immediate reconnect)](./research/connection-lifecycle-test-2025-10-18.md)** - FR-084 through FR-087  
   Test: [`tests/test-connection-lifecycle.ps1`](./tests/test-connection-lifecycle.ps1)

10. **[Performance Limits (Silent degradation, response timing)](./research/performance-limits-test-2025-10-20.md)** - NOTE: Originally documented FR-088 through FR-091 but removed from spec per user feedback; behavior observed may have been temporary hub overload rather than designed protection mechanism  
   Test: [`tests/test-performance-limits.ps1`](./tests/test-performance-limits.ps1)

### Testing Statistics
- **Tests Completed**: 9 of 10
- **Commands Tested**: 300+
- **Test Duration**: ~30 minutes total
- **FRs Added/Updated**: 17 (FR-071 through FR-087)
- **Critical Discoveries**: 7 major discrepancies between documentation and reality

