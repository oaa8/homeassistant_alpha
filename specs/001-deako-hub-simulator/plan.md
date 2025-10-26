# Implementation Plan: Deako Hub and Device Simulator

**Branch**: `001-deako-hub-simulator` | **Date**: 2025-10-25 | **Spec**: [spec.md](./spec.md)  
**Input**: Feature specification from `/specs/001-deako-hub-simulator/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/commands/plan.md` for the execution workflow.

## Summary

**Primary Requirement**: Create a telnet-based Deako hub simulator that enables Home Assistant integration testing without physical hardware. Simulator must replicate critical protocol behaviors validated through hardware testing (100ms rate limiting, single-connection model, exact JSON message formats).

**Technical Approach**: Python 3.13+ asyncio-based telnet server with mDNS advertisement, JSON message parsing, in-memory device state management, and file-based configuration. Focus on simplicity over feature completeness—build minimum viable simulator first, add quirks only if integration testing proves they're necessary.


## Technical Context

**Language/Version**: Python 3.13+ (matches Home Assistant development requirements per constitution)  
**Primary Dependencies**: 
- `asyncio` (stdlib) - Non-blocking I/O for telnet connections
- `zeroconf` (PyPI) - mDNS service advertisement
- `pytest` (PyPI, dev) - Testing framework

**Storage**: In-memory device state only (no persistence required for test facility)  
**Testing**: pytest with 95% coverage target (constitution requirement)  
**Target Platform**: Windows 10+ and macOS 10.15+ (developer workstations)  
**Project Type**: Single project - command-line tool with pip installation  
**Performance Goals**: 
- Handle 10 commands/second (matches real hub throughput from research)
- <200ms response latency for all commands (matches real hub 5-200ms range)
- Support 1 active connection + queue passive connections (hardware-validated behavior)

**Constraints**: 
- NO threads/multiprocessing (constitution: asyncio only)
- NO YAML/TOML (constitution: JSON only)
- NO third-party logging frameworks (constitution: stdlib logging only)
- NO database (constitution: simplicity over cleverness)

**Scale/Scope**: 
- Single simulator instance = single hub
- Support 50 devices (typical residential installation based on research showing 37 devices)
- Run continuously for 24+ hours without restart (success criterion SC-004)


## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### ✅ I. Hardware Fidelity First
- **Status**: PASS
- **Evidence**: Spec includes 10 completed hardware validation tests (rate-limiting-systematic-test, multi-connection-test, dim-validation-test, device-state-test, whitespace-behavior-test, physical-button-behavior-test, error-code-validation-test, message-format-edge-cases-test, connection-lifecycle-test, performance-limits-test). All critical protocol behaviors documented in `research/` with test scripts in `tests/`.
- **Action**: None - comprehensive hardware validation already complete.

### ⚠️ II. Simplicity Over Cleverness
- **Status**: CONCERN - requires design decisions
- **Issues**:
  1. **FR-072 "Passive Rejection"**: Spec requires accepting socket connections but only making first functional. This is MORE complex than simple TCP RST rejection. Does the integration actually depend on this quirk, or can we start with simpler "reject second connection" approach?
  2. **HTTP API (FR-031 to FR-039)**: Requires full REST API for runtime control. For test facility, would "restart with different config file" be sufficient initially?
  3. **Scenario System (FR-042)**: Full scenario activation via HTTP API adds complexity. Could start with "different config files = different scenarios, restart to switch"?
  4. **Quirk Simulation (FR-024 to FR-030, FR-077-FR-083)**: Extensive quirk injection (whitespace, malformed JSON, message format edge cases). Which quirks actually break the integration? Should we add quirks incrementally as testing proves they're needed?
  5. **Rate Limiting Curve (FR-074)**: Simulating exact success rate curve (0ms=5%, 50ms=70%, 100ms=100%) is complex. Would simple "reject if <100ms since last command" be sufficient?
  
- **Proposed Approach**: Build **Minimum Viable Simulator** first (Phase 1), add complexity only when testing proves it's needed (Phase 2+). See "Complexity Tracking" section below.

### ✅ III. End-User Validation Required
- **Status**: PASS with plan
- **Approach**: After each phase, validate against real Home Assistant integration:
  - Phase 1 MVP: Integration discovers, connects, queries devices, controls devices
  - Phase 2+: Integration handles quirks/edge cases correctly
- **Documentation**: Validation results recorded in phase completion notes with: what was tested, how, what was observed

### ✅ IV. Test Facility, Not Product
- **Status**: PASS
- **Evidence**: Spec correctly identifies this as integration testing tool, not production system. No authentication, no security hardening, no cloud features in scope.
- **Alignment**: MVP approach prioritizes integration testing needs over simulator feature completeness.

### ✅ V. Long-Term Readability
- **Status**: PASS with requirements
- **Requirements**:
  - File headers with creation date, author, purpose, assumptions
  - Comments explain WHY (research references, hardware validation, quirk rationale)
  - Magic numbers named with hardware test references (e.g., `RATE_LIMIT_MS = 100  # Validated 2025-10-18: research/rate-limiting-systematic-test`)
  - Descriptive function/variable names (device_state, not dev_st)
  - Protocol quirks reference research docs
  
### ✅ VI. No Orphaned Work
- **Status**: PASS with tracking
- **Plan**:
  - Any TODOs/placeholders immediately tracked in `specs/001-deako-hub-simulator/tasks.md`
  - Research docs in `research/` referenced from spec.md
  - Test scripts in `tests/` referenced from research docs
  - Temp artifacts in `temp/` with date-stamped names
  - Before completion: audit for untracked TODOs

### ⚠️ VII. Comprehensive Testing Required
- **Status**: REQUIRES CLARIFICATION
- **Questions**:
  1. What does 95% coverage mean for a simulator? Test message parsing? Test state updates? Test telnet socket handling?
  2. How do we test mDNS advertisement without mocking OS-level networking?
  3. Should tests use real asyncio or mock event loop?
  4. Is integration testing (actually running Home Assistant against simulator) part of test coverage or separate validation?
  
- **Proposed Approach**: 
  - Unit tests: Message parsing, state management, command handling (95% coverage achievable)
  - Integration tests: Full message flow (send CONTROL, verify EVENT broadcast)
  - System tests: Home Assistant integration validation (manual, documented)
  - Defer: mDNS testing (may require real networking or complex mocks)

### Summary
- **BLOCKERS**: None - can proceed to Phase 0
- **CONCERNS**: Simplicity violations need review (passive rejection, HTTP API, quirk simulation)
- **CLARIFICATIONS NEEDED**: Testing strategy definition before implementation
- **ACTION**: Address concerns in Phase 0 research by defining MVP scope vs. full-spec scope


## Project Structure

### Documentation (this feature)

```text
specs/001-deako-hub-simulator/
├── spec.md              # Feature specification (already exists)
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output - consolidated research findings
├── data-model.md        # Phase 1 output - entities and state management
├── quickstart.md        # Phase 1 output - installation and usage guide
├── contracts/           # Phase 1 output - JSON message schemas
│   ├── messages.schema.json      # All protocol message formats
│   └── config.schema.json        # Configuration file format
├── tasks.md             # Phase 2 output (/speckit.tasks command)
├── research/            # Hardware validation tests (already exists)
│   └── *.md
├── tests/               # Test scripts (already exists)
│   └── *.ps1
└── temp/                # Temporary exploration artifacts
```

### Source Code (repository root)

```text
deako_simulator/                   # Main package directory
├── __init__.py                    # Package initialization
├── __main__.py                    # Entry point for `python -m deako_simulator`
├── cli.py                         # Command-line interface and argument parsing
├── config.py                      # Configuration loading and validation
├── models.py                      # Data models (Device, Message, etc.)
├── protocol.py                    # Protocol message parsing and formatting
├── server.py                      # Asyncio telnet server
├── mdns_service.py                # mDNS advertisement
├── state.py                       # Device state management
└── logging_config.py              # Logging setup

tests/                             # Test suite
├── test_protocol.py               # Message parsing/formatting tests
├── test_state.py                  # State management tests
├── test_config.py                 # Configuration validation tests
├── test_server.py                 # Server logic tests (mocked asyncio)
├── test_integration.py            # Full message flow tests
└── conftest.py                    # Pytest fixtures

pyproject.toml                     # Package metadata and dependencies
README.md                          # Quick start guide
LICENSE                            # MIT or similar
```

**Structure Decision**: Single-project layout (Option 1) selected because:
- This is a standalone command-line tool, not a web/mobile app
- No frontend/backend separation needed
- Simple flat structure maximizes readability (constitution Principle V)
- All code in one package (`deako_simulator/`) keeps imports obvious
- Tests mirror source structure for easy navigation


## Design Decisions

> **Following critical review and user feedback, the following implementation approach was confirmed:**

### Decisions Made (2025-10-25)

1. **✅ Passive Rejection (Zombie Connections)**: KEEP - Tests critical scenario where Home Assistant connects when hub is already occupied by another client. Integration needs to detect "connected but not responding" and alert/retry. This is validated real hardware behavior (FR-072).

2. **✅ HTTP Control API**: KEEP - Better developer experience for test facility despite implementation complexity. HTTP provides familiar tools (curl, Invoke-WebRequest), standard error codes, and self-documenting REST endpoints. Simpler than custom telnet control protocol. Runs on separate port (8080) with no interference to hub protocol (port 23).

3. **✅ Named Scenario System**: KEEP - Configuration file defines named scenarios that can be activated via HTTP API. Provides version-controlled test cases, one-line test activation, and self-documentation. ~70 additional lines justified by better test facility UX (consistent with HTTP API decision).

4. **✅ Physical Button Simulation**: KEEP - Required to test integration's EVENT handling for external state changes (physical button presses while Home Assistant is connected). Enables testing real-world scenarios where device state changes independently of integration commands.

5. **✅ Rate Limiting SIMPLIFIED**: Drop exact success curve simulation (FR-074 removed). Simple approach: commands arriving <100ms after previous command are silently dropped. This tests the key integration behavior (proper command spacing) without unnecessary complexity.

6. **✅ Multi-Layer Testing Required**: Unit tests (message parsing, state management), integration tests (full message flows), system tests (Home Assistant integration validation). Target 95% coverage per constitution.

### Rationale

**Constitution Principle II (Simplicity)** and **Principle IV (Test Facility, Not Product)** were balanced:
- Features that improve test facility UX justify complexity (HTTP API, named scenarios)  
- Features that don't change tested integration behavior are simplified (rate limiting curve)
- Features that test real hardware behavior are kept (passive rejection, physical buttons)

All kept features are either:
1. **Hardware-validated behaviors** (passive rejection, physical buttons) that enable testing integration robustness
2. **Test facility UX improvements** (HTTP API, named scenarios) that make simulator easier to use

---

## Phase 0: Research & Decision Resolution

**Prerequisites**: User decision on MVP vs full-spec approach (see Complexity Tracking above)

**Objective**: Resolve all NEEDS CLARIFICATION items and document design decisions with rationale.

### Research Tasks

1. **Asyncio Architecture Patterns**
   - **Question**: How should telnet connections, message processing, and mDNS coexist in asyncio?
   - **Research**: Best practices for asyncio server architecture
   - **Output**: Connection handler design pattern, event loop structure
   - **Rationale**: Prevents callback spaghetti, ensures clean shutdown

2. **Message Framing Strategy**
   - **Question**: How to handle partial messages, message boundaries, connection buffering?
   - **Research**: Asyncio StreamReader/StreamWriter patterns for line-delimited protocols
   - **Output**: Buffer management strategy, newline handling, partial message queueing
   - **Rationale**: Real hub sends newline-delimited JSON; must handle partial reads

3. **mDNS Registration Lifecycle**
   - **Question**: When to register mDNS? How to handle registration failures? How to clean up on shutdown?
   - **Research**: zeroconf library usage patterns, error handling, service lifecycle
   - **Output**: mDNS startup/shutdown sequence, fallback behavior on port conflicts
   - **Rationale**: Constitution requires graceful degradation on mDNS failures (FR-069)

4. **Testing Strategy Definition**
   - **Question**: What's testable with unit tests vs integration tests vs manual validation?
   - **Research**: Asyncio testing patterns, mock strategies for network I/O
   - **Output**: Test pyramid definition (unit/integration/system), coverage targets per layer
   - **Rationale**: Constitution requires 95% coverage; need clear test boundaries

5. **Configuration Validation Approach**
   - **Question**: Validate on load (fail fast) or lazily (flexible)? What validation errors matter?
   - **Research**: JSON schema validation libraries, error message patterns
   - **Output**: Config validation rules, error message format, fail-fast vs warn strategy
   - **Rationale**: FR-043 requires descriptive validation errors with exact field paths

6. **State Consistency Model**
   - **Question**: How to ensure state updates and EVENT broadcasts are atomic? Handle concurrent access?
   - **Research**: Asyncio task synchronization patterns, atomic state updates
   - **Output**: State locking strategy (if needed), command serialization approach
   - **Rationale**: FR-070 requires per-device command queuing; FR-020 requires consistent broadcasts

### Decision Documentation

For each research task, document in `research.md`:
- **Decision**: What approach was chosen
- **Rationale**: Why this solves the problem better than alternatives
- **Alternatives Considered**: What else was evaluated and why rejected
- **Hardware Alignment**: How this matches real hub behavior (if applicable)
- **Simplicity Impact**: How this affects code complexity and maintainability

### Outputs
- `specs/001-deako-hub-simulator/research.md` with all decisions documented
- Clear answer to MVP vs full-spec from user
- Testing strategy defined (what 95% coverage means)

---

## Phase 1: MVP Implementation (Core Protocol)

**Prerequisites**: Phase 0 complete, user confirms MVP approach

**Objective**: Build minimum viable simulator that enables P1 user stories (discovery, connection, device queries, control).

### 1.1 Data Models

**File**: `deako_simulator/models.py`

**Entities**:
- `Device`: UUID, name, capabilities ("power" or "power+dim"), state (power: bool, dim: int|None)
- `Message`: type, transactionId, src, dst, timestamp, status, data (dict)
- `Config`: devices (list), network settings (IP, port, mDNS name), log level

**Rationale**: Simple data classes with explicit fields; no ORM, no database, just Python dataclasses or named tuples.

**Testing**: Unit tests for validation (UUID format, dim range 0-100, required fields)

### 1.2 Configuration Management

**File**: `deako_simulator/config.py`

**Functions**:
- `load_config(path: str) -> Config`: Parse JSON, validate structure
- `validate_device(device_dict) -> Device`: Check required fields, UUID format, dim range
- `get_default_config() -> Config`: Zero-config defaults (localhost, 3 sample devices)

**Validation Rules** (FR-043):
- Devices must have: uuid (optional), name (required), capabilities (required), state.power (required), state.dim (required if power+dim)
- Dim values: 0-100 range
- UUID format: if provided, must be valid UUID
- Descriptive errors: `"devices[2].state.dim: value 150 exceeds maximum 100"`

**Testing**: Config loading with valid/invalid JSON, missing fields, out-of-range values

### 1.3 Protocol Message Handling

**File**: `deako_simulator/protocol.py`

**Functions**:
- `parse_message(line: str) -> Message | None`: Parse JSON line, return Message or None on error
- `format_response(message: Message) -> str`: Format Message to JSON with CRLF
- `create_device_found(device: Device, timestamp: int) -> Message`: Build DEVICE_FOUND message
- `create_event(device_uuid: str, state: dict, timestamp: int) -> Message`: Build EVENT message

**Message Types Supported**:
- PING: Echo back with status "ok"
- DEVICE_LIST: Return device count
- DEVICE_POLL: Return device state (power + dim)
- CONTROL: Update device state, return status "ok"

**Error Handling**:
- Malformed JSON: silently ignore (FR-077)
- Unknown message type: return REQUEST_UNKNOWN error (FR-066)
- Missing required fields: return REQUEST_MALFORMED error (FR-066)
- Invalid device UUID: return REQUEST_INVALID error (FR-066)

**Testing**: Parse valid/invalid messages, format responses, error code generation

### 1.4 State Management

**File**: `deako_simulator/state.py`

**Class**: `SimulatorState`
- Attributes: `devices: dict[str, Device]` (UUID -> Device mapping)
- Methods:
  - `get_device(uuid: str) -> Device | None`
  - `update_device_state(uuid: str, power: bool | None, dim: int | None) -> Device`: Update and return new state
  - `get_all_devices() -> list[Device]`

**State Update Logic**:
- Power and dim can be independently updated
- Null values mean "no change" (FR-082)
- Updates are synchronous (no locking needed for MVP; asyncio is single-threaded)

**Testing**: State updates, null handling, device lookup

### 1.5 Telnet Server

**File**: `deako_simulator/server.py`

**Class**: `DeakoSimulator`
- Attributes: `state: SimulatorState`, `active_connection: StreamWriter | None`, `config: Config`
- Methods:
  - `async def start()`: Start asyncio server, register mDNS, log startup
  - `async def handle_connection(reader: StreamReader, writer: StreamWriter)`: Main connection handler
  - `async def process_message(msg: Message, writer: StreamWriter)`: Route message to handler
  - `async def broadcast_event(device_uuid: str, new_state: dict)`: Send EVENT to active connection
  - `async def shutdown()`: Close connections, unregister mDNS, clean exit

**Connection Handling** (Passive Rejection per FR-072):
- Accept ALL incoming connections (no rejection)
- Track first connection as `active_connection: StreamWriter`
- Additional connections are "zombie" - accepted but receive no responses
- Only `active_connection` receives protocol responses
- On disconnect: if disconnecting connection == `active_connection`, set to None; next connection in queue becomes active
- **Rationale**: Replicates real hardware behavior; enables testing "Home Assistant connects when hub occupied" scenario

**Message Flow**:
1. Read line from StreamReader (asyncio handles buffering)
2. Parse message with `protocol.parse_message()`
3. Route to handler (ping_handler, device_list_handler, control_handler)
4. Send response with `writer.write()` + `await writer.drain()`

**DEVICE_LIST Flow** (FR-016, FR-065):
1. Send response with device count
2. For each device: send DEVICE_FOUND message with 100ms delay (FR-023)
3. **Note**: Real hub sends EVENTs before DEVICE_LIST completes (FR-065) - this quirk must be implemented to match hardware behavior

**CONTROL Flow** (FR-018, FR-019, FR-020):
1. Update device state via `state.update_device_state()`
2. Send acknowledgment with status "ok"
3. Broadcast EVENT to active connection (if exists)

**Rate Limiting** (Simplified per Design Decisions):
- Track `last_command_time: float` per device
- If `time.time() - last_command_time < 0.1`: silently drop command (no response)
- Else: process command, update `last_command_time`
- **Rationale**: Matches real hub "first-in-wins" behavior (FR-023) with simple implementation; tests integration's command spacing without complex success curve simulation

**Testing**: Mock StreamReader/StreamWriter, test message routing, connection rejection, rate limiting

### 1.6 mDNS Advertisement

**File**: `deako_simulator/mdns_service.py`

**Functions**:
- `register_mdns(port: int, hostname: str, name: str) -> Zeroconf`: Register "_telnet" service
- `unregister_mdns(zc: Zeroconf)`: Clean shutdown

**Configuration** (FR-001):
- Service type: `"_telnet._tcp.local."`
- Service name: `"local-integration"`
- Port: 23 (or configured port)

**Error Handling** (FR-069):
- Default mode: Log WARNING on failure, continue without mDNS
- Strict mode (`--require-mdns`): Exit with error if mDNS fails

**Testing**: Defer (requires real networking or complex mocking)

### 1.7 Command-Line Interface

**File**: `deako_simulator/cli.py`

**Arguments**:
- `--config PATH`: Config file path (default: use built-in defaults)
- `--port PORT`: Telnet port (default: 23, overrides config)
- `--bind-ip IP`: Bind address (default: 127.0.0.1, overrides config)
- `--log-level LEVEL`: Log level (default: INFO, overrides config)
- `--require-mdns`: Fail if mDNS registration fails (default: False)

**Precedence** (FR-067): CLI > env vars > config file > defaults

**Main Flow**:
1. Parse arguments
2. Load config (if --config provided)
3. Apply CLI overrides
4. Setup logging
5. Create SimulatorState from config
6. Create DeakoSimulator
7. Start server (asyncio.run)
8. Handle SIGINT/SIGTERM for graceful shutdown (FR-010)

**Testing**: Argument parsing, precedence chain, default values

### 1.8 Logging

**File**: `deako_simulator/logging_config.py`

**Setup**:
- Format: `[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s`
- Handlers: Console (always), File (optional, not in MVP)
- Levels: DEBUG, INFO, WARNING, ERROR

**Log Events** (FR-045 to FR-053):
- Startup: effective configuration
- Connections: client IP, connect/disconnect events
- Messages: received (type, transactionId), sent (type, status)
- State changes: device UUID, old state, new state
- Errors: what failed, why, how to fix

**Testing**: Verify log messages emitted (capture with pytest caplog)

### 1.9 Package Setup

**File**: `pyproject.toml`

**Metadata**:
- Name: `deako-simulator`
- Version: 0.1.0
- Python: >=3.13
- Dependencies: `zeroconf`
- Dev dependencies: `pytest`, `pytest-asyncio`, `pytest-cov`
- Entry points: `deako-simulator = deako_simulator.cli:main`

**Installation**:
- `pip install -e .` (editable for development)
- `deako-simulator --help` (entry point works)

**Testing**: Install in fresh venv, run entry point

### Phase 1 Outputs

**Generated Files**:
- `specs/001-deako-hub-simulator/data-model.md`: Entities, state structure, message formats
- `specs/001-deako-hub-simulator/contracts/messages.schema.json`: JSON schemas for all message types
- `specs/001-deako-hub-simulator/contracts/config.schema.json`: JSON schema for config file
- `specs/001-deako-hub-simulator/quickstart.md`: Installation, basic usage, example config

**Source Code**:
- All files in `deako_simulator/` package
- All test files in `tests/`
- `pyproject.toml`, `README.md`

**Validation Criteria** (Constitution Principle III):
1. Install simulator: `pip install -e .`
2. Start simulator: `deako-simulator` (uses default config)
3. Verify mDNS: Simulator appears in network as "local-integration._telnet._tcp.local."
4. Connect via telnet: `telnet 127.0.0.1 23`
5. Send DEVICE_LIST: Receive device count + DEVICE_FOUND messages
6. Send CONTROL: Device state updates, receive EVENT
7. Home Assistant integration: Discovers simulator, controls devices

---

## Phase 2: Enhancements (If Testing Proves Necessary)

**Prerequisites**: Phase 1 complete, integration testing identifies missing features

**Objective**: Add complexity only when testing reveals it's needed.

### 2.1 HTTP Control API (If Config-Only Insufficient)

**Trigger**: Testing shows "restart to change config" is too slow or disruptive

**Implementation**:
- Add `deako_simulator/api.py` with aiohttp application
- Endpoints: GET /devices, POST /devices, DELETE /devices/{uuid}, PATCH /devices/{uuid}/state
- Run HTTP server on separate port (8080) alongside telnet server
- Share SimulatorState between telnet and HTTP servers

### 2.2 Protocol Quirks (If Integration Breaks Without Them)

**Trigger**: Integration fails against MVP but works with real hub

**Quirks to Add** (in order of likelihood):
1. EVENTs before DEVICE_LIST completion (FR-065): If integration's DEVICE_LIST parsing breaks
2. Whitespace messages (FR-024): If integration's empty message handling breaks
3. Malformed JSON injection (FR-028): If integration crashes on bad messages
4. Null state field handling (FR-082): If integration mishandles dim=null

### 2.3 Physical Button Simulation (If Needed for Testing)

**Trigger**: Integration's physical button handling needs testing

**Implementation**:
- Add HTTP endpoint: POST /devices/{uuid}/button
- Toggle device power state
- Broadcast EVENT to telnet clients
- Add inter-button-press delay enforcement (~100ms minimum)

### 2.4 Advanced Rate Limiting (If Simple Throttling Insufficient)

**Trigger**: Integration's rate limit handling fails with simple "reject fast commands"

**Implementation**:
- Track recent command timestamps (sliding window)
- Calculate success probability based on spacing
- Randomly drop commands based on probability curve (FR-074)

### Phase 2 Decision Points

Before implementing any Phase 2 item:
1. Document what integration behavior failed without it
2. Verify the quirk exists on real hardware (re-validate if needed)
3. Confirm simpler alternatives don't solve the problem
4. Update `research.md` with justification

---

## Phase 3: Testing & Validation

**Objective**: Achieve 95% test coverage per constitution requirements.

### 3.1 Unit Tests

**Coverage Target**: 95% of lines in `models.py`, `config.py`, `protocol.py`, `state.py`

**Test Files**:
- `tests/test_models.py`: Device/Message validation, UUID generation
- `tests/test_config.py`: Config loading, validation errors, precedence
- `tests/test_protocol.py`: Message parsing, response formatting, error codes
- `tests/test_state.py`: State updates, null handling, device lookup

**Approach**: Pure functions, no I/O, deterministic, fast

### 3.2 Integration Tests

**Coverage Target**: Full message flows (DEVICE_LIST → DEVICE_FOUND stream, CONTROL → EVENT broadcast)

**Test File**: `tests/test_integration.py`

**Tests**:
- Device discovery flow: Send DEVICE_LIST, receive count + DEVICE_FOUND messages
- Control flow: Send CONTROL, verify state update + EVENT broadcast
- Error flows: Invalid UUID → REQUEST_INVALID, unknown type → REQUEST_UNKNOWN
- Rate limiting: Rapid commands → only first succeeds

**Approach**: Mock StreamReader/StreamWriter, use real SimulatorState, deterministic timing (no sleep)

### 3.3 System Tests (Manual Validation)

**Coverage Target**: Integration with Home Assistant (end-user validation per constitution)

**Test Scenarios**:
1. Discovery: Home Assistant finds simulator via mDNS
2. Connection: Integration connects to telnet port
3. Device list: Integration queries and displays devices
4. Control: Turn on/off devices, adjust brightness via HA UI
5. State sync: Manual changes via telnet update HA UI
6. Reconnection: Kill connection, verify HA reconnects

**Documentation**: Record test results in phase completion notes (what tested, how, observed behavior)

### 3.4 Coverage Exceptions

**Deferred Testing**:
- mDNS registration: Requires real networking or complex mocks (defer unless proves problematic)
- Signal handling: Difficult to test reliably cross-platform (manual validation sufficient)

**Documentation**: If coverage <95%, document in `specs/001-deako-hub-simulator/test-coverage-exceptions.md` with rationale

---

## Implementation Sequence

**Assuming MVP approach approved**:

1. **Phase 0**: Research asyncio patterns, testing strategy, config validation → `research.md`
2. **Phase 1**: Implement MVP (models → config → protocol → state → server → CLI → logging)
3. **Phase 3**: Write tests (unit → integration → manual validation with Home Assistant)
4. **Phase 2**: Add enhancements ONLY if testing reveals gaps

**Total Estimated Effort**: 
- Phase 0: 2-4 hours (research and documentation)
- Phase 1: 8-12 hours (implementation)
- Phase 3: 4-6 hours (testing)
- Phase 2: TBD (depends on what testing reveals)

---

## Next Steps

**All design decisions finalized (2025-10-25)**. Ready to proceed with implementation.

---

## Phase Completion Log

### Phase 0: Research & Decision Resolution ✅ COMPLETE (2025-10-25)

**Objective**: Resolve all technical unknowns and document design decisions

**Artifacts Generated**:
- ✅ `research.md` - Consolidated design decisions for all 6 research tasks:
  1. Asyncio Architecture Patterns → Single event loop with coroutine handlers
  2. Message Framing Strategy → Line-delimited JSON with strict CRLF validation
  3. mDNS Registration Lifecycle → Fail-fast with graceful fallback
  4. Testing Strategy Definition → Three-layer pyramid (unit 70%, integration 25%, system 5%)
  5. Configuration Validation Approach → Fail-fast with JSON Schema + semantic rules
  6. State Consistency Model → Single-threaded synchronous access (no locks)

**Key Decisions**:
- Architecture: Single asyncio event loop, no threads per constitution
- Message framing: Use `StreamReader.readline()` for CRLF-delimited JSON
- mDNS: Best-effort registration, continue without if fails
- Testing: pytest with 95% coverage target, three layers (unit/integration/system)
- Config: Fail-fast validation with JSON Schema, exact error field paths
- State: Single-threaded event loop eliminates need for locks

**All research tasks resolved. Phase 0 complete.**

---

### Phase 1: Design Artifacts ✅ COMPLETE (2025-10-25)

**Objective**: Generate design artifacts for implementation reference

**Artifacts Generated**:
- ✅ `data-model.md` - Entity definitions (Device, Message, Config) with:
  - Field specifications and validation rules
  - State transition diagrams
  - Entity relationships
  - Python type hints examples
  - Hardware validation references
  
- ✅ `contracts/config.schema.json` - JSON Schema for configuration:
  - Device structure with UUID, name, capabilities, state
  - Network settings (host, port, http_port, mdns_name)
  - Scenario definitions for named test cases
  - Validation rules encoded (UUID format, dim range 0-100, unique UUIDs)
  
- ✅ `contracts/messages.schema.json` - JSON Schema for protocol messages:
  - DEVICE_LIST request/response
  - DEVICE_FOUND (server push)
  - CONTROL request/response
  - EVENT (state change broadcast)
  - PING request/response
  - DEVICE_POLL request/response with FR-023 quirk (status="error" on success)
  
- ✅ `contracts/README.md` - Schema usage guide and validation instructions
  
- ✅ `quickstart.md` - Usage guide for integration developers:
  - Installation instructions
  - Basic usage (config → start → connect HA)
  - 5 testing scenarios (basic control, button simulation, connection recovery, passive rejection, rate limiting)
  - Named scenario system
  - HTTP API reference (8 endpoints)
  - Telnet protocol testing examples
  - Common patterns (automated tests, CI setup, manual testing)
  - Troubleshooting guide
  - Configuration examples

- ✅ `.github/copilot-instructions.md` - Updated agent context with Python 3.13+ and in-memory state

**Constitution Re-check (Post-Design)**:
- ✅ Principle II (Simplicity): Artifacts document simple patterns, no overengineering
- ✅ Principle V (Readability): Clear documentation for future context resumption
- ✅ Principle VI (No Orphaned Work): All artifacts cross-referenced

**Phase 1 complete. Ready for Phase 2 (Implementation).**

---

## Next Steps

1. **Phase 2**: Implementation
   - Create Python package structure (`deako_simulator/`)
   - Implement data models with dataclasses
   - Implement configuration loading with JSON Schema validation
   - Implement protocol message handlers
   - Implement asyncio telnet server with connection management
   - Implement HTTP API with aiohttp
   - Implement CLI entry point
   - Add logging throughout

2. **Phase 3**: Testing
   - Write unit tests (message parsing, state management, validation)
   - Write integration tests (full message flows, asyncio event loop)
   - Manual validation with Home Assistant integration
   - Target 95% coverage per constitution

**Estimated Timeline**:
- Phase 2 (Implementation): 12-16 hours
- Phase 3 (Testing): 6-8 hours

Total remaining: ~18-24 hours for complete, tested simulator.
