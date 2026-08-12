# Changelog

All notable changes to the Deako Hub Simulator will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2025-10-30

### Initial Release

First functional release of the Deako Hub Simulator - a hardware-validated test facility for Home Assistant integration development.

### Features

#### Discovery and Network (FR-001 to FR-005)
- **mDNS/Zeroconf Auto-Discovery**: Simulator advertises itself as `_telnet._tcp.local.` service
- **Configurable Network Binding**: Supports binding to localhost or LAN IP addresses
- **Cross-Platform**: Runs on Windows and macOS without platform-specific changes
- **Customizable mDNS Service**: Configurable service name and hostname for discovery

#### Telnet Protocol Implementation (FR-006 to FR-010)
- **Asyncio-Based Server**: Non-blocking telnet server using Python's asyncio
- **Single Active Connection Model**: Passive rejection of additional connections (matches real hub behavior)
- **Graceful Shutdown**: Proper signal handling (SIGTERM/SIGINT) with clean connection closure
- **Connection Lifecycle Management**: Detects disconnections, handles cleanup

#### Device Simulation (FR-011 to FR-015)
- **Configurable Virtual Devices**: Support for multiple devices with unique UUIDs
- **Device Types**: Dimmable lights (power + dim) and on/off switches (power only)
- **State Management**: Maintains power and dim state per device
- **Runtime Device Management**: Add/remove devices via HTTP API without restart

#### Protocol Implementation (FR-016 to FR-023, FR-063 to FR-083)
- **DEVICE_LIST Command**: Returns device count and streams DEVICE_FOUND messages
- **DEVICE_POLL Command**: Queries current device state (with hardware-validated quirks)
- **CONTROL Command**: Updates device state (power and dim control)
- **EVENT Broadcasts**: Unsolicited state change notifications to all connected clients
- **CRLF Line Endings**: Proper `\r\n` message framing per protocol spec
- **Rate Limiting**: 100ms minimum spacing per device with "first-in-wins" behavior
- **Per-Device Command Queueing**: Deterministic sequential processing per FR-070

#### Hardware-Validated Behaviors (10 validation tests completed)

**Rate Limiting** (FR-023, FR-064)
- 100ms minimum spacing between commands to same device (not 800ms documented)
- Silent dropping of rapid commands (no DEVICE_BUSY errors)
- Research: `research/rate-limiting-systematic-test-2025-10-18.md`

**Multi-Connection Handling** (FR-072, FR-007)
- Passive rejection model: accepts TCP connections but only first is functional
- Zombie connections receive no responses
- Research: `research/multi-connection-test-2025-10-18.md`

**Dim Value Validation** (FR-071)
- Accepts all numeric values without errors (negative, >100, decimals)
- Internal clamping to 0-100 range
- Research: `research/dim-validation-test-2025-10-18.md`

**DEVICE_POLL Quirk**
- Returns `status="error"` even on successful query (real hub behavior)
- Research: `research/device-state-test-2025-10-18.md`

**Whitespace Handling** (FR-024, FR-026, FR-077)
- Silently ignores whitespace-only messages
- Silently ignores malformed JSON without disconnecting
- Research: `research/whitespace-behavior-test-2025-10-18.md`

**Physical Button Simulation** (FR-075, FR-076)
- Immediate EVENT broadcasts with full device state
- Toggle power behavior (on→off, off→on)
- Research: `research/physical-button-behavior-test-2025-10-18.md`

**Error Code Validation** (FR-066, FR-077)
- Only 3 error codes exist: REQUEST_UNKNOWN, REQUEST_MALFORMED, REQUEST_INVALID
- DEVICE_BUSY and DEVICE_UNKNOWN do not exist on real hub
- Research: `research/error-code-validation-test-2025-10-18.md`

**Message Format Parsing** (FR-078 to FR-083)
- Permissive parsing: accepts extra fields, any field order
- Uppercase message types required (case-sensitive)
- Null values interpreted as "no change"
- Research: `research/message-format-edge-cases-test-2025-10-18.md`

**Connection Lifecycle** (FR-084 to FR-087)
- No idle timeout (connections survive >5 minutes idle)
- Immediate reconnection allowed (<1 second)
- Handles both graceful (FIN) and ungraceful (RST) disconnects
- Research: `research/connection-lifecycle-test-2025-10-18.md`

**Performance Limits** (FR-088 to FR-091)
- Response times: 5-200ms typical
- Maximum throughput: ~10 commands/second
- Silent degradation after burst (>50 commands in 5 seconds)
- Research: `research/performance-limits-test-2025-10-20.md`

#### Protocol Quirks Simulation (FR-024 to FR-030)
- **Whitespace Injection**: Configurable whitespace-only message injection
- **Response Delays**: Per-message-type or global delay configuration
- **Malformed JSON**: Configurable injection of invalid JSON for resilience testing
- **Partial Messages**: Support for simulating truncated message delivery

#### HTTP API Control Interface (FR-031 to FR-039, FR-061)
- **REST API on Port 8080**: Separate from telnet port 23
- **Device Management**: GET/POST/PATCH/DELETE endpoints for devices
- **Scenario Activation**: POST `/api/scenarios/{name}/activate`
- **Physical Button Simulation**: POST `/api/devices/{uuid}/button`
- **State Inspection**: GET `/api/status`, `/api/devices`, `/api/clients`
- **Quirk Control**: Enable/disable protocol quirks at runtime
- **Connection Control**: Force disconnect, refuse connections, simulate latency
- **Non-Disruptive**: HTTP API runs independently without affecting telnet connections

#### Configuration Management (FR-040 to FR-044, FR-062, FR-067 to FR-069)
- **JSON Configuration Files**: Initial setup and scenario definitions
- **Scenario Support**: Named scenarios for quick test state switching
- **Atomic Scenario Activation**: Replace all devices while keeping connections active
- **Configuration Precedence**: CLI arguments > environment variables > config file > defaults
- **Validation on Load**: Explicit validation with descriptive error messages
- **Default Configuration**: Zero-config startup with 3 sample devices
- **Effective Config Logging**: Shows source of each setting (CLI/env/config/default)
- **Optional mDNS**: `--require-mdns` flag for strict mDNS validation

#### Logging and Observability (FR-045 to FR-053)
- **Comprehensive Logging**: All protocol interactions, connections, state changes
- **Component Tags**: Filter logs by subsystem (telnet/http/simulator/connection)
- **Structured Format**: Timestamp, severity, component, client ID, event details
- **Configurable Log Levels**: DEBUG, INFO, WARNING, ERROR
- **Dual Output**: Console and optional log file
- **Message Content Logging**: Full JSON content of all sent/received messages
- **HTTP Request Logging**: Method, endpoint, status code, response time

#### Error Handling (FR-054 to FR-058, FR-062)
- **Port Binding Failures**: Clear error messages with actionable guidance
- **mDNS Failures**: Configurable behavior (warn and continue or fail startup)
- **Malformed JSON**: Graceful handling without crashes
- **Connection Failures**: Isolated error handling (one client failure doesn't affect others)
- **Log File Failures**: Falls back to console-only logging

### Test Coverage

- **340 Tests Passing**: Comprehensive test suite across all modules
- **79% Code Coverage**: Documented exceptions for CLI and mDNS (manual validation only)
- **Target: 95% Coverage**: After CLI implementation completion
- **No Flaky Tests**: All tests deterministic and reliable
- **Hardware Validation**: All critical behaviors validated against real Deako hub

### Test Organization

- **Unit Tests**: Individual module testing (models, protocol, state, config)
- **Integration Tests**: Complete workflow testing (discovery, device list, control, events)
- **Edge Case Tests**: Error scenarios, quirks, connection resilience
- **End-to-End Tests**: Complete integration cycles with real asyncio event loops

### Documentation

- **README.md**: Quick start guide with installation, examples, troubleshooting
- **CONTRIBUTING.md**: Development setup, testing guidelines, code style, constitution compliance
- **quickstart.md**: Comprehensive user guide with testing scenarios and CI/CD examples
- **spec.md**: Complete functional requirements (91 FRs) and success criteria (10 SCs)
- **plan.md**: Technical implementation plan with architecture decisions
- **data-model.md**: Entity definitions and message formats
- **research.md**: Hardware validation findings and design decisions (26 decisions documented)

### Constitution Compliance

All 8 Constitution Principles followed:

1. **Hardware Fidelity First**: 10 hardware validation tests completed
2. **Simplicity Over Cleverness**: Direct implementations, minimal abstractions
3. **End-User Validation Required**: Tested with Home Assistant integration
4. **Test Facility, Not Product**: Optimized for reliability and debuggability
5. **Long-Term Readability**: File headers, WHY comments, hardware validation references
6. **No Orphaned Work**: All TODOs tracked in tasks.md
7. **Comprehensive Testing**: 95% coverage target, no flaky tests
8. **Explicit Error Handling**: Specific exception catching, fail-fast behavior

### Known Limitations

- **CLI Not Yet Complete**: Manual validation only (T084-T087 pending)
- **mDNS Manual Validation**: Excluded from automated coverage (hardware-dependent)
- **No Cloud Connectivity**: Simulator is local-only (by design)
- **No Firmware Updates**: Static simulator behavior (by design)
- **No Production Deployment**: Test facility only (by design)

### Dependencies

- Python 3.13+ (matches Home Assistant development requirements)
- aiohttp >= 3.9.0 (HTTP API server)
- zeroconf >= 0.131.0 (mDNS/Zeroconf discovery)
- jsonschema >= 4.20.0 (Configuration validation)

### Installation

```bash
# Clone repository
git clone https://github.com/oaa8/homeassistant_alpha.git
cd homeassistant_alpha

# Checkout simulator branch
git checkout 001-deako-hub-simulator

# Install with dependencies
pip install -e .

# Run simulator
python -m deako_simulator
```

### Hardware Validation References

All protocol behaviors validated against real Deako hub (192.168.86.221:23) October 2025:

1. `research/rate-limiting-systematic-test-2025-10-18.md`
2. `research/multi-connection-test-2025-10-18.md`
3. `research/dim-validation-test-2025-10-18.md`
4. `research/device-state-test-2025-10-18.md`
5. `research/whitespace-behavior-test-2025-10-18.md`
6. `research/physical-button-behavior-test-2025-10-18.md`
7. `research/error-code-validation-test-2025-10-18.md`
8. `research/message-format-edge-cases-test-2025-10-18.md`
9. `research/connection-lifecycle-test-2025-10-18.md`
10. `research/performance-limits-test-2025-10-20.md`

### Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, testing guidelines, and code style requirements.

### License

See [LICENSE](LICENSE) for details.

---

## [Unreleased]

### Planned for Future Releases

- Complete CLI implementation (T084-T087)
- Additional scenario examples
- Performance optimizations
- Enhanced quirk simulation modes
- Additional test patterns documentation

---

[0.1.0]: https://github.com/oaa8/homeassistant_alpha/releases/tag/v0.1.0
[Unreleased]: https://github.com/oaa8/homeassistant_alpha/compare/v0.1.0...HEAD
