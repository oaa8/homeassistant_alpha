# Research & Design Decisions: Deako Hub Simulator

**Branch**: `001-deako-hub-simulator` | **Date**: 2025-10-25 | **Phase**: 0 (Research)  
**Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)

This document consolidates all design decisions for the Deako Hub Simulator implementation. Each decision is backed by hardware validation, best practices research, or constitutional requirements.

---

## 1. Asyncio Architecture Patterns

### Decision
Use **single event loop with coroutine-based handlers** architecture:
- Main event loop runs telnet server, HTTP API server, and mDNS registration concurrently
- Each client connection spawned as separate coroutine task
- Message processing happens in connection handler coroutines
- Shared state accessed through asyncio-safe patterns (no locks needed due to single-threaded event loop)

### Architecture Pattern
```python
async def main():
    # All services started concurrently
    telnet_server = await asyncio.start_server(handle_client, host, port)
    http_server = await start_http_api()
    mdns_service = await register_mdns()
    
    async with telnet_server:
        await telnet_server.serve_forever()

async def handle_client(reader: StreamReader, writer: StreamWriter):
    # One coroutine per connection
    while True:
        message = await read_message(reader)
        response = process_message(message)  # Synchronous state access
        await write_message(writer, response)
```

### Rationale
- **Simplicity**: No threading complexity, no locks, no race conditions
- **Hardware alignment**: Real hub handles connections serially (only first connection functional per FR-072)
- **Performance**: Asyncio sufficient for test facility (target: 10 commands/sec, asyncio handles thousands/sec)
- **Constitution compliance**: Matches "asyncio only, no threads" requirement (Constitution Principle II)

### Alternatives Considered
1. **Threading model**: Rejected - Constitution explicitly forbids threads, adds complexity
2. **Multi-process**: Rejected - Overkill for single-hub simulator, harder to share state
3. **Callback-based asyncio**: Rejected - Less readable than coroutine syntax

### Implementation Notes
- Use `asyncio.create_task()` for fire-and-forget operations (e.g., broadcasting EVENTs)
- Use `asyncio.gather()` for concurrent startup/shutdown of services
- Connection cleanup handled in `finally` blocks with `writer.close()` and `await writer.wait_closed()`

---

## 2. Message Framing Strategy

### Decision
Use **line-delimited JSON with CRLF terminators** (`\r\n`):
- Buffer incoming bytes until complete line found
- Parse each line as separate JSON message
- Handle partial messages by keeping read buffer between iterations
- Strict protocol adherence: CRLF only (no LF-only tolerance)

### Buffer Management Pattern
```python
async def read_message(reader: StreamReader) -> dict:
    """Read one complete JSON message terminated by CRLF."""
    line = await reader.readline()  # Reads until \n (includes \r\n)
    if not line:
        raise ConnectionClosed()
    
    # Validate CRLF termination
    if not line.endswith(b'\r\n'):
        raise ProtocolError("Message must end with CRLF")
    
    # Parse JSON (strip CRLF before parsing)
    return json.loads(line[:-2].decode('utf-8'))
```

### Rationale
- **Hardware validation**: Real hub uses CRLF line endings (validated in `research/message-format-edge-cases-test-2025-10-18.md`)
- **Protocol fidelity**: Strict CRLF requirement matches real hub behavior (integration must handle correctly)
- **Simplicity**: `StreamReader.readline()` handles buffering automatically, no manual buffer management needed
- **Edge case handling**: LF-only messages rejected per hardware behavior (FR-080)

### Alternatives Considered
1. **Fixed-length frames**: Rejected - Protocol is line-delimited, not length-prefixed
2. **Tolerant parsing (accept LF or CRLF)**: Rejected - Would hide integration bugs, real hub is strict
3. **Manual buffer management**: Rejected - `readline()` already provides robust buffering

### Hardware Alignment
- **Research reference**: `research/message-format-edge-cases-test-2025-10-18.md` - Hub rejects LF-only messages
- **Research reference**: `research/whitespace-behavior-test-2025-10-18.md` - Hub never sends whitespace-only messages
- **Test script**: `tests/test-message-format-edge-cases.ps1` - Validates CRLF requirement

### Error Handling
- **Incomplete JSON**: Return protocol error, keep connection open (per FR-029)
- **Invalid UTF-8**: Return protocol error with `status: "error"`, `error: "INVALID_UTF8"`
- **Missing CRLF**: Return protocol error (strict enforcement)
- **Connection closed mid-message**: Close connection gracefully, no error broadcast

---

## 3. mDNS Registration Lifecycle

### Decision
Use **fail-fast mDNS registration with graceful fallback**:
- Register mDNS service during startup (before accepting connections)
- Log warning and continue if registration fails (FR-069: must work without mDNS)
- Unregister during shutdown (best-effort, non-blocking)
- Use `zeroconf` library (PyPI, mature, asyncio-compatible)

### Registration Pattern
```python
async def register_mdns(port: int, service_name: str = "local-integration"):
    """Register mDNS service. Warn but don't fail if registration fails."""
    try:
        zeroconf = AsyncZeroconf()
        info = ServiceInfo(
            type_="_telnet._tcp.local.",
            name=f"{service_name}._telnet._tcp.local.",
            port=port,
            properties={},  # No additional properties needed
        )
        await zeroconf.async_register_service(info)
        logger.info(f"mDNS registered: {service_name}._telnet._tcp.local. on port {port}")
        return zeroconf, info
    except Exception as e:
        logger.warning(f"mDNS registration failed: {e}. Simulator will still accept direct connections.")
        return None, None

async def shutdown_mdns(zeroconf, info):
    """Unregister mDNS service. Non-blocking, best-effort."""
    if zeroconf and info:
        try:
            await asyncio.wait_for(
                zeroconf.async_unregister_service(info),
                timeout=2.0
            )
        except asyncio.TimeoutError:
            logger.warning("mDNS unregistration timed out")
        except Exception as e:
            logger.warning(f"mDNS unregistration failed: {e}")
        finally:
            await zeroconf.async_close()
```

### Rationale
- **Hardware alignment**: Real hub advertises via mDNS (`_telnet._tcp.local.` service type per FR-001)
- **Robustness**: Test facility must work even if mDNS fails (firewall, permissions, etc.)
- **Constitution compliance**: Graceful degradation per Principle IV (test facility, not product)
- **Developer UX**: Clear warning when mDNS unavailable, suggests manual IP connection

### Alternatives Considered
1. **Require mDNS (fail if registration fails)**: Rejected - Too brittle for test facility
2. **Skip mDNS entirely**: Rejected - Integration testing needs mDNS discovery validation
3. **Retry mDNS on failure**: Rejected - Adds complexity, test facility can work without it

### Hardware Alignment
- **Protocol spec**: Service type `_telnet`, service name `local-integration`, port 23
- **Research reference**: Hardware hub uses standard mDNS announcement (no custom properties)

### Port Conflict Handling
- **Detection**: `zeroconf` will raise exception if port already in use
- **Fallback**: Log error, suggest alternate port via `--port` CLI flag
- **No auto-port-selection**: Would break manual connection attempts (IP:port must be predictable)

---

## 4. Testing Strategy Definition

### Decision
Use **three-layer test pyramid** with 95% coverage target:

#### Layer 1: Unit Tests (70% of tests, 95% coverage)
- **Scope**: Message parsing, state management, validation logic
- **Tools**: `pytest` with standard fixtures
- **Mocking**: Mock `StreamReader`/`StreamWriter`, no real sockets
- **Example tests**:
  - `test_parse_control_message()` - Valid/invalid JSON parsing
  - `test_device_state_update()` - State transitions, dim levels
  - `test_rate_limiting_logic()` - Command spacing validation
  - `test_config_validation()` - Schema validation, error messages

#### Layer 2: Integration Tests (25% of tests)
- **Scope**: Full message flows (connect → send → receive → disconnect)
- **Tools**: `pytest-asyncio` with real asyncio event loop
- **Mocking**: Use test telnet client, no mock sockets
- **Example tests**:
  - `test_device_list_flow()` - DEVICE_LIST → response → DEVICE_FOUND stream
  - `test_control_acknowledgment()` - CONTROL → ack → EVENT sequence
  - `test_passive_rejection()` - Two connections, second ignored
  - `test_event_broadcast()` - EVENT sent to all active connections

#### Layer 3: System Tests (5% of tests, manual validation)
- **Scope**: Real Home Assistant integration validation
- **Tools**: Manual testing with HA dev environment
- **Validation**: P1/P2/P3 user stories from spec.md
- **Example scenarios**:
  - HA discovers simulator via mDNS
  - HA connects and queries devices
  - HA controls device (on/off/dim)
  - HA handles connection loss/reconnection

### Coverage Targets
- **Overall**: 95% line coverage (constitution requirement)
- **Critical paths**: 100% coverage (message parsing, state updates, rate limiting)
- **Error handling**: 90% coverage (some edge cases hard to trigger)
- **mDNS code**: Excluded from coverage (external library, manual validation)

### Rationale
- **Constitution compliance**: Meets 95% coverage requirement (Principle VII)
- **Pyramid balance**: Most tests are fast unit tests, fewer slow integration tests
- **Practical validation**: System tests ensure real-world usage works (constitution Principle III)
- **Maintenance**: Unit tests catch regressions quickly, integration tests validate protocols

### Alternatives Considered
1. **Only unit tests**: Rejected - Doesn't validate protocol flows, asyncio interactions
2. **Only integration tests**: Rejected - Slow, hard to debug, poor coverage of edge cases
3. **Mock asyncio event loop**: Rejected - Hides asyncio bugs, better to test real event loop

### Testing Tools
- **pytest**: Test runner and assertion framework
- **pytest-asyncio**: Asyncio fixture support (`@pytest.mark.asyncio`)
- **pytest-cov**: Coverage measurement
- **pytest-timeout**: Prevent hanging tests (5s timeout default)

### Async Testing Patterns
```python
@pytest.mark.asyncio
async def test_control_message_flow():
    """Test full CONTROL message flow with real asyncio."""
    # Start simulator in background task
    server_task = asyncio.create_task(start_simulator())
    
    # Connect as client
    reader, writer = await asyncio.open_connection('127.0.0.1', 23)
    
    # Send CONTROL
    control = {"name": "CONTROL", "transactionId": "123", "data": {...}}
    writer.write(json.dumps(control).encode() + b'\r\n')
    await writer.drain()
    
    # Read acknowledgment
    ack = await read_message(reader)
    assert ack["name"] == "CONTROL"
    assert ack["status"] == "ok"
    
    # Read EVENT
    event = await read_message(reader)
    assert event["name"] == "EVENT"
    
    # Cleanup
    writer.close()
    await writer.wait_closed()
    server_task.cancel()
```

### What's NOT Tested
- **mDNS registration**: Manual validation only (external library, OS-dependent)
- **HTTP API security**: No authentication testing (test facility only)
- **Long-running stability**: No 24-hour endurance tests (manual validation)
- **Performance benchmarks**: No load testing (target 10 cmd/sec easily met)

---

## 5. Configuration Validation Approach

### Decision
Use **fail-fast validation with descriptive errors**:
- Validate configuration on load (before starting services)
- Use JSON Schema for structure validation
- Add semantic validation for business rules
- Provide exact field paths in error messages (FR-043)
- Exit with non-zero code on validation failure (fail-fast)

### Validation Pattern
```python
def load_config(config_path: Path) -> Config:
    """Load and validate configuration. Exit on validation errors."""
    # 1. Load JSON
    try:
        with open(config_path) as f:
            raw_config = json.load(f)
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON in {config_path}: {e}")
        sys.exit(1)
    
    # 2. JSON Schema validation (structure)
    try:
        validate(raw_config, CONFIG_SCHEMA)
    except ValidationError as e:
        print(f"ERROR: Config validation failed at '{e.json_path}': {e.message}")
        sys.exit(1)
    
    # 3. Semantic validation (business rules)
    errors = []
    for idx, device in enumerate(raw_config['devices']):
        # Validate UUID format
        if not is_valid_uuid(device['uuid']):
            errors.append(f"devices[{idx}].uuid: Invalid UUID format")
        
        # Validate dim capability
        if 'dim' in device and device['power'] is None:
            errors.append(f"devices[{idx}]: 'dim' requires 'power' capability")
    
    if errors:
        print(f"ERROR: Config validation failed:")
        for error in errors:
            print(f"  - {error}")
        sys.exit(1)
    
    return Config.from_dict(raw_config)
```

### Error Message Format
```
ERROR: Config validation failed at 'devices[2].uuid': Invalid UUID format
ERROR: Config validation failed at 'devices[5]': 'dim' requires 'power' capability
ERROR: Config validation failed at 'network.port': Port must be 1-65535
```

### Rationale
- **Fail-fast principle**: Catch config errors before simulator starts (saves debugging time)
- **Developer UX**: Exact field paths (FR-043) make errors easy to fix
- **Constitution compliance**: Simplicity over flexibility - config must be correct (Principle II)
- **JSON Schema benefits**: Standard validation library, self-documenting schema

### Alternatives Considered
1. **Warn and use defaults**: Rejected - Silent failures lead to confusing test behavior
2. **Lazy validation**: Rejected - Errors discovered mid-test are harder to debug
3. **Custom validation code**: Rejected - JSON Schema provides standard, readable validation

### Validation Rules

#### Required Fields
- `devices[]`: At least one device required
- `devices[].uuid`: Must be valid UUID v4 format
- `devices[].name`: Non-empty string
- `devices[].capabilities`: Array with "power" and/or "dim"

#### Optional Fields with Defaults
- `network.host`: Default `"0.0.0.0"` (listen on all interfaces)
- `network.port`: Default `23` (standard telnet)
- `network.mdns_name`: Default `"local-integration"`
- `log_level`: Default `"INFO"`

#### Semantic Rules
- Device UUIDs must be unique across all devices
- Dim capability requires power capability
- Port must be 1-65535
- Log level must be DEBUG/INFO/WARNING/ERROR

### Hardware Alignment
- **UUID format**: Real hub uses lowercase UUID v4 strings (no hyphens in JSON, but standard format accepted)
- **Capabilities**: Real hub devices have "power" or "power+dim" (FR-005)

### Configuration Schema Location
- Schema defined in `deako_simulator/config_schema.json`
- Loaded at runtime for validation
- Used for IDE autocomplete (if editor supports JSON Schema)

---

## 6. State Consistency Model

### Decision
Use **single-threaded asyncio with synchronous state access** (no locks):
- All state mutations happen in main event loop (single-threaded)
- Command processing is synchronous (no `await` during state updates)
- EVENT broadcasting is asynchronous (fire-and-forget tasks)
- Per-device command queueing via asyncio Queue (FR-070)

### State Management Pattern
```python
class SimulatorState:
    """Thread-safe state manager (safe because asyncio is single-threaded)."""
    
    def __init__(self, devices: list[Device]):
        self.devices: dict[str, Device] = {d.uuid: d for d in devices}
        self.connections: list[StreamWriter] = []  # Active connections
        self.last_command_time: dict[str, float] = {}  # Per-device rate limiting
        self.command_queues: dict[str, asyncio.Queue] = {
            d.uuid: asyncio.Queue() for d in devices
        }
    
    def update_device_state(self, uuid: str, power: bool, dim: int | None) -> Device:
        """Update device state synchronously. Returns updated device."""
        device = self.devices[uuid]
        device.power = power
        device.dim = dim
        return device
    
    async def broadcast_event(self, event: dict):
        """Send EVENT to all active connections asynchronously."""
        # Create tasks for all connections (fire-and-forget)
        tasks = [
            asyncio.create_task(self._send_event(conn, event))
            for conn in self.connections
        ]
        # Don't wait for completion (non-blocking broadcast)
    
    async def _send_event(self, writer: StreamWriter, event: dict):
        """Send single EVENT. Handle write failures gracefully."""
        try:
            message = json.dumps(event) + '\r\n'
            writer.write(message.encode())
            await writer.drain()
        except Exception as e:
            logger.warning(f"Failed to send EVENT: {e}")
            # Remove dead connection
            self.connections.remove(writer)
```

### Command Processing Flow
```python
async def process_control(state: SimulatorState, command: dict) -> dict:
    """Process CONTROL command with rate limiting and queueing."""
    uuid = command['data']['uuid']
    
    # 1. Check rate limiting (synchronous)
    now = time.time()
    last_time = state.last_command_time.get(uuid, 0)
    if (now - last_time) < 0.1:  # 100ms minimum
        # Silently drop (FR-075)
        logger.debug(f"Rate limit: dropped command for {uuid}")
        return None  # No acknowledgment sent
    
    # 2. Update state synchronously (no race conditions)
    power = command['data'].get('power')
    dim = command['data'].get('dim')
    device = state.update_device_state(uuid, power, dim)
    state.last_command_time[uuid] = now
    
    # 3. Send acknowledgment immediately (synchronous response)
    ack = {
        "name": "CONTROL",
        "transactionId": command['transactionId'],
        "status": "ok",
        "timestamp": int(now * 1000)
    }
    
    # 4. Broadcast EVENT asynchronously (fire-and-forget)
    event = create_event(device)
    await state.broadcast_event(event)
    
    return ack
```

### Rationale
- **No locks needed**: Asyncio event loop is single-threaded, no concurrent mutations
- **Simple reasoning**: Synchronous state updates are easy to understand and debug
- **Hardware alignment**: Real hub queues commands per-device (FR-070)
- **Constitution compliance**: Simplicity over threading complexity (Principle II)

### Alternatives Considered
1. **Threading with locks**: Rejected - Constitution forbids threads, adds complexity
2. **Async state updates**: Rejected - No benefit (no I/O during state updates), harder to reason about
3. **Actor model (one task per device)**: Rejected - Overkill for simple state management

### Per-Device Command Queueing (FR-070)
```python
async def queue_command(state: SimulatorState, uuid: str, command: dict):
    """Queue command for device. Process serially."""
    queue = state.command_queues[uuid]
    await queue.put(command)

async def device_command_processor(state: SimulatorState, uuid: str):
    """Process commands for one device serially."""
    queue = state.command_queues[uuid]
    while True:
        command = await queue.get()
        try:
            await process_control(state, command)
        except Exception as e:
            logger.error(f"Command processing failed for {uuid}: {e}")
        finally:
            queue.task_done()
```

### Hardware Alignment
- **Research reference**: `research/rate-limiting-systematic-test-2025-10-18.md` - Commands within 100ms silently dropped
- **Research reference**: `research/device-state-test-2025-10-18.md` - State updates reflected in EVENTs
- **Protocol behavior**: Real hub processes commands serially per device, concurrent across devices

### Race Condition Analysis
**Q**: What if two clients send CONTROL for same device simultaneously?
**A**: Asyncio event loop processes messages serially:
1. Client 1's CONTROL arrives → processed → state updated → EVENT broadcast starts
2. Client 2's CONTROL arrives → queued in device queue
3. Client 2's CONTROL processed after Client 1's completes
4. No race condition possible (single-threaded event loop)

**Q**: What if EVENT broadcast fails mid-send?
**A**: Each connection gets independent task:
1. Connection A send succeeds → EVENT delivered
2. Connection B send fails → logged, connection removed, other connections unaffected
3. Fire-and-forget pattern ensures no blocking

---

## Summary of Key Decisions

| Decision Area | Choice | Primary Rationale |
|--------------|--------|-------------------|
| **Architecture** | Single event loop, coroutine handlers | Simplicity, constitution compliance (no threads) |
| **Message Framing** | Line-delimited JSON with strict CRLF | Hardware fidelity, integration testing accuracy |
| **mDNS Lifecycle** | Fail-fast registration with graceful fallback | Robustness for test facility, clear error messages |
| **Testing Strategy** | Three-layer pyramid (unit/integration/system) | 95% coverage, fast feedback, real-world validation |
| **Config Validation** | Fail-fast with JSON Schema + semantic rules | Developer UX, exact error locations, early failure detection |
| **State Consistency** | Single-threaded synchronous state access | No locks, simple reasoning, asyncio-safe by design |

---

## Hardware Validation References

All decisions validated against real Deako hub (192.168.86.221:23):

1. **Message Format**: `research/message-format-edge-cases-test-2025-10-18.md`
2. **Rate Limiting**: `research/rate-limiting-systematic-test-2025-10-18.md`
3. **Connection Model**: `research/multi-connection-test-2025-10-18.md`
4. **Device State**: `research/device-state-test-2025-10-18.md`
5. **Whitespace Handling**: `research/whitespace-behavior-test-2025-10-18.md`
6. **Physical Buttons**: `research/physical-button-behavior-test-2025-10-18.md`
7. **Error Codes**: `research/error-code-validation-test-2025-10-18.md`
8. **Dim Validation**: `research/dim-validation-test-2025-10-18.md`
9. **Connection Lifecycle**: `research/connection-lifecycle-test-2025-10-18.md`
10. **Performance Limits**: `research/performance-limits-test-2025-10-20.md`

All test scripts available in `tests/` directory.

---

## 7. HTTP API Implementation with aiohttp

### Decision
Use **aiohttp AppRunner pattern for concurrent servers**:
- Run aiohttp web server alongside asyncio telnet server in same event loop
- Share SimulatorState between telnet and HTTP handlers via app[state_key]
- Use AppRunner + TCPSite for manual lifecycle control (not web.run_app())
- Start both servers concurrently with asyncio.gather()

### Implementation Pattern
```python
from aiohttp import web

async def create_http_app(state: SimulatorState) -> web.Application:
    """Create HTTP API application sharing simulator state."""
    app = web.Application()
    
    # Store shared state in app
    STATE_KEY = web.AppKey("simulator_state", SimulatorState)
    app[STATE_KEY] = state
    
    # Register routes
    app.add_routes([
        web.get('/api/devices', list_devices),
        web.get('/api/devices/{uuid}', get_device),
        web.post('/api/devices/{uuid}/state', update_device_state),
        web.post('/api/devices/{uuid}/button', simulate_button_press),
        web.post('/api/scenarios/{name}/activate', activate_scenario),
    ])
    
    return app

async def start_http_api(state: SimulatorState, host: str, port: int):
    """Start HTTP API server using AppRunner for manual control."""
    app = await create_http_app(state)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    logger.info(f"HTTP API server started on {host}:{port}")
    return runner

async def main():
    state = SimulatorState(devices)
    
    # Start both servers concurrently
    telnet_server = await asyncio.start_server(
        lambda r, w: handle_telnet_connection(r, w, state),
        host='0.0.0.0',
        port=23
    )
    http_runner = await start_http_api(state, '0.0.0.0', 8080)
    
    try:
        async with telnet_server:
            await telnet_server.serve_forever()
    finally:
        await http_runner.cleanup()
```

### HTTP Handler Pattern
```python
async def update_device_state(request: web.Request) -> web.Response:
    """Update device state via HTTP API."""
    STATE_KEY = web.AppKey("simulator_state", SimulatorState)
    state = request.app[STATE_KEY]
    
    uuid = request.match_info['uuid']
    data = await request.json()
    
    # Update state (same code as telnet CONTROL handler)
    device = state.update_device_state(
        uuid, 
        data.get('power'), 
        data.get('dim')
    )
    
    # Broadcast EVENT to all telnet connections
    await state.broadcast_event(create_event(device))
    
    return web.json_response({
        'uuid': device.uuid,
        'state': {'power': device.power, 'dim': device.dim}
    })
```

### Rationale
- **AppRunner pattern**: Provides manual lifecycle control; web.run_app() would block
- **Shared state**: Both servers access same SimulatorState = consistent behavior
- **Concurrent operation**: asyncio.gather() runs both servers in same event loop
- **Clean shutdown**: AppRunner.cleanup() properly closes HTTP server

### Alternatives Considered
1. **web.run_app()**: Rejected - Blocks event loop, can't run telnet server alongside
2. **Separate processes**: Rejected - Constitution forbids, complicates state sharing
3. **HTTP-only (no telnet)**: Rejected - Must replicate real hub's telnet protocol

### aiohttp Version Requirements
- **Minimum version**: 3.8.0 (for Python 3.13 compatibility)
- **Recommended**: 3.9+ for improved asyncio integration
- **Dependencies**: attrs, multidict, yarl (auto-installed)

### Error Handling in HTTP Handlers
```python
@web.middleware
async def error_middleware(request, handler):
    """Convert exceptions to JSON error responses."""
    try:
        return await handler(request)
    except KeyError:
        return web.json_response(
            {'error': 'Device not found'}, 
            status=404
        )
    except ValueError as e:
        return web.json_response(
            {'error': str(e)}, 
            status=400
        )
    except Exception as e:
        logger.exception("Unexpected error in HTTP handler")
        return web.json_response(
            {'error': 'Internal server error'}, 
            status=500
        )

app = web.Application(middlewares=[error_middleware])
```

---

## 8. JSON Schema Validation Integration

### Decision
Use **jsonschema library with fail-fast validation** at config load time:
- Validate configuration against schema before starting simulator
- Use ValidationError.json_path for exact field path reporting (FR-043)
- Perform structural validation (JSON Schema) + semantic validation (Python logic)
- Exit immediately on validation failure (fail-fast)

### Implementation Pattern
```python
import json
import jsonschema
from pathlib import Path

def load_config(config_path: Path) -> Config:
    """Load and validate configuration file."""
    # 1. Load JSON
    try:
        with open(config_path) as f:
            raw_config = json.load(f)
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON in {config_path}:")
        print(f"  Line {e.lineno}, column {e.colno}: {e.msg}")
        sys.exit(1)
    except FileNotFoundError:
        print(f"ERROR: Config file not found: {config_path}")
        sys.exit(1)
    
    # 2. Load schema
    schema_path = Path(__file__).parent / "contracts" / "config.schema.json"
    with open(schema_path) as f:
        schema = json.load(f)
    
    # 3. JSON Schema validation (structure)
    try:
        jsonschema.validate(raw_config, schema)
    except jsonschema.ValidationError as e:
        print(f"ERROR: Config validation failed:")
        print(f"  Field: {e.json_path}")
        print(f"  Error: {e.message}")
        if e.context:
            print(f"  Details:")
            for ctx_error in e.context:
                print(f"    - {ctx_error.json_path}: {ctx_error.message}")
        sys.exit(1)
    
    # 4. Semantic validation (business rules)
    errors = validate_semantic_rules(raw_config)
    if errors:
        print("ERROR: Config validation failed:")
        for error in errors:
            print(f"  - {error}")
        sys.exit(1)
    
    return Config.from_dict(raw_config)

def validate_semantic_rules(config: dict) -> list[str]:
    """Validate business rules not covered by JSON Schema."""
    errors = []
    
    # Check UUID uniqueness
    uuids = [d['uuid'] for d in config['devices']]
    if len(uuids) != len(set(uuids)):
        duplicates = [u for u in set(uuids) if uuids.count(u) > 1]
        errors.append(f"Duplicate device UUIDs: {', '.join(duplicates)}")
    
    # Check dim requires power
    for idx, device in enumerate(config['devices']):
        if 'dim' in device['capabilities'] and 'power' not in device['capabilities']:
            errors.append(
                f"devices[{idx}] ('{device['name']}'): "
                f"'dim' capability requires 'power' capability"
            )
    
    # Check scenario references valid devices
    if 'scenarios' in config:
        for scenario in config['scenarios']:
            for uuid in scenario['device_states'].keys():
                if uuid not in uuids:
                    errors.append(
                        f"Scenario '{scenario['name']}': "
                        f"references unknown device UUID {uuid}"
                    )
    
    return errors
```

### Error Message Format Examples
```
ERROR: Config validation failed:
  Field: $.devices[2].state.dim
  Error: 150 is greater than the maximum of 100

ERROR: Config validation failed:
  Field: $.devices[5].uuid
  Error: 'invalid-uuid' does not match '^[0-9a-f]{8}-...' pattern
  
ERROR: Config validation failed:
  - devices[3] ('Bedroom Closet'): 'dim' capability requires 'power' capability
  - Duplicate device UUIDs: a1b2c3d4-e5f6-4789-a012-b3c4d5e6f789
```

### Rationale
- **json_path property**: Provides exact field location per FR-043 requirement
- **Two-stage validation**: JSON Schema catches structure errors, Python catches semantic errors
- **Fail-fast**: Configuration errors caught before any simulator state created
- **Clear error messages**: Developers can immediately identify and fix issues

### Alternatives Considered
1. **Pydantic**: Rejected - Adds dependency, JSON Schema already provides validation
2. **Lazy validation**: Rejected - Errors discovered during runtime harder to debug
3. **Warning instead of error**: Rejected - Invalid config should fail immediately

### jsonschema Library Version
- **Minimum version**: 4.0.0 (for json_path support)
- **Recommended**: 4.20+ (latest stable)
- **Draft version**: Draft 7 (widely supported, matches our schemas)

### Performance Considerations
- **Config validation is one-time cost at startup**: Acceptable overhead
- **Schema is loaded from file**: Consider caching if config reloaded at runtime
- **No validation needed for runtime messages**: Protocol messages validated by parsing logic

---

## 9. pytest-asyncio Testing Patterns

### Decision
Use **pytest-asyncio with separate test event loop per test**:
- Mark async tests with @pytest.mark.asyncio decorator
- Use pytest-asyncio's event_loop fixture for test isolation
- Test asyncio servers by creating real StreamReader/StreamWriter connections
- Avoid port conflicts with dynamic port allocation (port=0)

### Test Structure Pattern
```python
import pytest
import asyncio
from deako_simulator import SimulatorState, handle_connection

@pytest.mark.asyncio
async def test_device_list_flow():
    """Test DEVICE_LIST request/response flow."""
    # Setup: Create simulator state
    devices = [
        Device(uuid="test-uuid-1", name="Test Device 1", ...),
        Device(uuid="test-uuid-2", name="Test Device 2", ...)
    ]
    state = SimulatorState(devices)
    
    # Start test server on dynamic port
    server = await asyncio.start_server(
        lambda r, w: handle_connection(r, w, state),
        host='127.0.0.1',
        port=0  # Dynamic port allocation
    )
    port = server.sockets[0].getsockname()[1]
    
    async with server:
        # Connect as client
        reader, writer = await asyncio.open_connection('127.0.0.1', port)
        
        try:
            # Send DEVICE_LIST request
            request = {"name": "DEVICE_LIST", "transactionId": "test-001"}
            writer.write(json.dumps(request).encode() + b'\r\n')
            await writer.drain()
            
            # Read response
            response_line = await reader.readline()
            response = json.loads(response_line[:-2].decode())
            
            # Assertions
            assert response['name'] == 'DEVICE_LIST'
            assert response['transactionId'] == 'test-001'
            assert response['status'] == 'ok'
            assert response['data']['deviceCount'] == 2
            
            # Read DEVICE_FOUND messages
            found_devices = []
            for _ in range(2):
                device_line = await reader.readline()
                device = json.loads(device_line[:-2].decode())
                assert device['name'] == 'DEVICE_FOUND'
                found_devices.append(device['data']['uuid'])
            
            assert set(found_devices) == {'test-uuid-1', 'test-uuid-2'}
            
        finally:
            writer.close()
            await writer.wait_closed()
```

### Fixture Patterns
```python
import pytest
import asyncio

@pytest.fixture
def simulator_state():
    """Create test simulator state with sample devices."""
    devices = [
        Device(
            uuid="11111111-1111-4111-8111-111111111111",
            name="Test Light 1",
            capabilities=["power", "dim"],
            state=DeviceState(power=False, dim=0)
        ),
        Device(
            uuid="22222222-2222-4222-8222-222222222222",
            name="Test Light 2",
            capabilities=["power"],
            state=DeviceState(power=False, dim=None)
        ),
    ]
    return SimulatorState(devices)

@pytest.fixture
async def test_server(simulator_state):
    """Start test server on dynamic port, yield port, cleanup."""
    server = await asyncio.start_server(
        lambda r, w: handle_connection(r, w, simulator_state),
        host='127.0.0.1',
        port=0
    )
    port = server.sockets[0].getsockname()[1]
    
    async with server:
        yield port  # Tests use this port
    # Server automatically closed after yield

@pytest.mark.asyncio
async def test_with_fixture(test_server):
    """Test using server fixture."""
    port = test_server
    reader, writer = await asyncio.open_connection('127.0.0.1', port)
    # ... test logic ...
```

### Timeout Handling
```python
import pytest

@pytest.mark.asyncio
@pytest.mark.timeout(5)  # Fail test if takes >5 seconds
async def test_with_timeout():
    """Test with timeout to catch hanging tests."""
    # Test logic that should complete quickly
    pass

# Or use asyncio.wait_for for specific operations
@pytest.mark.asyncio
async def test_operation_timeout():
    """Test with per-operation timeout."""
    reader, writer = await asyncio.open_connection('127.0.0.1', port)
    
    try:
        response = await asyncio.wait_for(
            reader.readline(),
            timeout=2.0  # 2 second timeout for this operation
        )
    except asyncio.TimeoutError:
        pytest.fail("Response not received within 2 seconds")
```

### Testing Rate Limiting
```python
@pytest.mark.asyncio
async def test_rate_limiting():
    """Test 100ms rate limit per device."""
    reader, writer = await asyncio.open_connection('127.0.0.1', port)
    
    # Send two CONTROL commands rapidly (<100ms apart)
    control1 = {
        "name": "CONTROL",
        "transactionId": "ctrl-1",
        "data": {"uuid": "test-uuid-1", "power": True}
    }
    control2 = {
        "name": "CONTROL",
        "transactionId": "ctrl-2",
        "data": {"uuid": "test-uuid-1", "power": False}
    }
    
    # Send both without delay
    writer.write(json.dumps(control1).encode() + b'\r\n')
    writer.write(json.dumps(control2).encode() + b'\r\n')
    await writer.drain()
    
    # Read response - should only get one acknowledgment (second silently dropped)
    ack = await reader.readline()
    response = json.loads(ack[:-2].decode())
    assert response['transactionId'] == 'ctrl-1'  # First command processed
    
    # Wait to ensure no second response arrives
    try:
        second_response = await asyncio.wait_for(reader.readline(), timeout=0.5)
        # If we get here, rate limiting failed
        pytest.fail("Second command should have been rate-limited")
    except asyncio.TimeoutError:
        pass  # Expected - no second response
```

### pytest-asyncio Configuration
```python
# pytest.ini or pyproject.toml
[tool.pytest.ini_options]
asyncio_mode = "auto"  # Automatically detect async tests
asyncio_default_fixture_loop_scope = "function"  # New event loop per test
```

### Rationale
- **Dynamic ports (port=0)**: Avoids test conflicts, supports parallel test execution
- **Separate event loop per test**: Test isolation, no state pollution between tests
- **Real connections**: Tests actual asyncio behavior, not mocked streams
- **Timeout protection**: Prevents hanging tests from blocking CI/CD

### Alternatives Considered
1. **Mock StreamReader/StreamWriter**: Rejected - Doesn't test real asyncio behavior
2. **Fixed test ports**: Rejected - Causes conflicts in parallel test runs
3. **Shared event loop**: Rejected - State pollution between tests

### pytest-asyncio Version Requirements
- **Minimum version**: 0.21.0 (for auto mode support)
- **Recommended**: 0.23+ (latest stable)
- **Python 3.13 compatibility**: Confirmed in 0.23+

---

## 10. asyncio StreamReader/StreamWriter Best Practices

### Decision
Use **readline() with proper error handling and cleanup**:
- Use readline() for CRLF-delimited messages (simpler than manual buffering)
- Detect client disconnection by checking for empty bytes (b'')
- Always close writer and wait for wait_closed() in finally block
- Handle OSError/ConnectionResetError for abrupt disconnections

### Connection Handler Pattern
```python
async def handle_connection(
    reader: asyncio.StreamReader, 
    writer: asyncio.StreamWriter,
    state: SimulatorState
):
    """Handle single telnet connection."""
    client_addr = writer.get_extra_info('peername')
    logger.info(f"Connection from {client_addr}")
    
    try:
        while True:
            # Read one line (CRLF-terminated)
            try:
                line = await reader.readline()
            except (OSError, ConnectionResetError) as e:
                logger.info(f"Client {client_addr} disconnected: {e}")
                break
            
            # Check for disconnection (empty bytes = EOF)
            if not line:
                logger.info(f"Client {client_addr} closed connection")
                break
            
            # Validate CRLF termination
            if not line.endswith(b'\r\n'):
                logger.warning(f"Message from {client_addr} missing CRLF: {line!r}")
                continue  # Ignore malformed message per FR-077
            
            # Parse and process message
            try:
                message = json.loads(line[:-2].decode('utf-8'))
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                logger.debug(f"Invalid JSON from {client_addr}: {e}")
                continue  # Silently ignore per FR-077
            
            # Process message and send response
            response = await process_message(message, state)
            if response:  # response may be None (rate-limited)
                writer.write(json.dumps(response).encode() + b'\r\n')
                await writer.drain()
    
    except Exception as e:
        logger.exception(f"Unexpected error handling connection from {client_addr}")
    
    finally:
        # Always clean up writer
        try:
            writer.close()
            await writer.wait_closed()
        except Exception as e:
            logger.debug(f"Error closing writer for {client_addr}: {e}")
        
        logger.info(f"Connection closed for {client_addr}")
```

### Broadcasting to Multiple Clients Pattern
```python
async def broadcast_event(state: SimulatorState, event: dict):
    """Send EVENT to all active connections."""
    message = json.dumps(event) + '\r\n'
    message_bytes = message.encode()
    
    # Create tasks for all connections
    tasks = []
    for writer in state.connections.copy():  # Copy to avoid mutation during iteration
        task = asyncio.create_task(
            send_to_connection(writer, message_bytes, state.connections)
        )
        tasks.append(task)
    
    # Wait for all sends to complete (with timeout)
    if tasks:
        await asyncio.wait(tasks, timeout=5.0)

async def send_to_connection(
    writer: asyncio.StreamWriter, 
    message: bytes,
    connections: list[asyncio.StreamWriter]
):
    """Send message to single connection, remove if fails."""
    try:
        writer.write(message)
        await writer.drain()
    except (OSError, ConnectionResetError) as e:
        logger.debug(f"Failed to send to connection: {e}")
        # Remove dead connection
        if writer in connections:
            connections.remove(writer)
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass  # Already closed or error closing
```

### Client Disconnection Detection
```python
# Method 1: Empty readline() result
line = await reader.readline()
if not line:
    # Client disconnected cleanly (sent EOF)
    break

# Method 2: Exception handling
try:
    line = await reader.readline()
except ConnectionResetError:
    # Client disconnected abruptly
    break
except OSError as e:
    # Network error or client disconnect
    logger.warning(f"Connection error: {e}")
    break

# Method 3: Check if stream is closing
if reader.at_eof():
    # No more data available, client closed
    break
```

### Buffer Limit Considerations
```python
# Default limit is 64 KiB - sufficient for our use case
# Our largest message (DEVICE_FOUND with 50 devices) is ~10 KB

# If needed, can adjust limit when starting server
server = await asyncio.start_server(
    handle_connection,
    host='0.0.0.0',
    port=23,
    limit=2**16  # 64 KiB (default)
)

# For protocol messages averaging ~200 bytes, default is fine
```

### Rationale
- **readline() simplicity**: Handles buffering automatically, perfect for line-delimited protocol
- **Explicit cleanup**: finally block ensures resources released even on exception
- **Disconnection detection**: Multiple methods provide robustness
- **Fire-and-forget broadcast**: create_task() prevents blocking on slow clients

### Alternatives Considered
1. **Manual buffer management**: Rejected - readline() is simpler and less error-prone
2. **Synchronous socket API**: Rejected - Blocks event loop, incompatible with async architecture
3. **Ignore disconnection errors**: Rejected - Leads to resource leaks

### StreamReader/StreamWriter Lifecycle
```
1. Connection established → (reader, writer) created by start_server()
2. Handler coroutine spawned automatically
3. Handler reads/writes via reader.readline() / writer.write()
4. Client disconnects → reader.readline() returns b'' or raises exception
5. Handler exits (finally block)
6. writer.close() called → sends FIN packet
7. await writer.wait_closed() → waits for TCP close to complete
8. Resources cleaned up
```

---

## 11. Library Version Requirements Summary

### Core Dependencies

| Library | Minimum Version | Recommended | Purpose | Python 3.13 Compatible |
|---------|----------------|-------------|---------|----------------------|
| **aiohttp** | 3.8.0 | 3.9+ | HTTP API server | ✅ Yes |
| **zeroconf** | 0.47.0 | 0.131+ | mDNS service advertisement | ✅ Yes |
| **jsonschema** | 4.0.0 | 4.20+ | Config validation | ✅ Yes |

### Development Dependencies

| Library | Minimum Version | Recommended | Purpose |
|---------|----------------|-------------|---------|
| **pytest** | 7.0.0 | 8.0+ | Test framework |
| **pytest-asyncio** | 0.21.0 | 0.23+ | Async test support |
| **pytest-cov** | 4.0.0 | 5.0+ | Coverage reporting |
| **pytest-timeout** | 2.1.0 | 2.2+ | Test timeouts |

### pyproject.toml Configuration
```toml
[project]
name = "deako-simulator"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = [
    "aiohttp>=3.9.0",
    "zeroconf>=0.131.0",
    "jsonschema>=4.20.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "pytest-cov>=5.0.0",
    "pytest-timeout>=2.2.0",
]

[project.scripts]
deako-simulator = "deako_simulator.cli:main"

[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
testpaths = ["tests"]
python_files = ["test_*.py"]
python_functions = ["test_*"]
addopts = [
    "--strict-markers",
    "--cov=deako_simulator",
    "--cov-report=term-missing",
    "--cov-report=html",
]

[tool.coverage.run]
source = ["deako_simulator"]
omit = ["*/tests/*", "*/test_*.py"]

[tool.coverage.report]
exclude_lines = [
    "pragma: no cover",
    "def __repr__",
    "raise AssertionError",
    "raise NotImplementedError",
    "if __name__ == .__main__.:",
    "if TYPE_CHECKING:",
]
```

---

## Next Steps (Phase 1)

With research complete, proceed to Phase 1 design artifacts:

1. **data-model.md**: Entity definitions (Device, Message, Config)
2. **contracts/**: JSON schemas for protocol messages and configuration
3. **quickstart.md**: Installation guide, basic usage examples, test scenarios
4. **Agent context update**: Run `update-agent-context.ps1 -AgentType copilot`

All Phase 1 artifacts will reference decisions from this research document.
