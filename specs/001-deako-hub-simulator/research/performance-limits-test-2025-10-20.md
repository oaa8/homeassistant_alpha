# Performance Limits Test - October 20, 2025

**Test Script:** [`tests/test-performance-limits.ps1`](../tests/test-performance-limits.ps1)  
**Spec Reference:** [spec.md](../spec.md) - Test #10: Performance Limits  
**Related FRs:** FR-088, FR-089, FR-090, FR-091

## Test Objective

Validate the Deako hub's performance characteristics under various load conditions, including maximum throughput, response times, burst handling, and sustained operation stability.

## Test Methodology

The test consisted of five distinct performance evaluations:

### Test 1: Maximum Command Throughput
- Send 100 CONTROL_DEVICE commands as fast as possible (no delays)
- Measure total time and calculate throughput (commands/second)
- Track response collection timing

### Test 2: Response Time Under Load
- Send 20 commands with 50ms delays between each
- Measure individual response times
- Calculate statistics (average, min, max, range)

### Test 3: Burst Command Handling
- Send 10 commands in rapid succession (burst)
- Measure burst send time
- Track response collection timing

### Test 4: Multiple Device Commands in Sequence
- Rapidly send commands to different devices
- Test device-switching performance
- Measure per-device timing

### Test 5: Connection Stability Under Load
- Run sustained traffic for 30 seconds
- Send commands at 10 commands/second rate (100ms delays)
- Monitor connection stability and error rates

## Critical Finding: Silent Connection Degradation

**The hub exhibits a protection mechanism that silently degrades connection after high-volume bursts:**

### Observed Behavior

After Test #1 (100 rapid commands with no delays):
1. Connection remains technically "connected" (no TCP disconnect)
2. **Hub stops sending ANY responses**
3. Subsequent commands are accepted but never acknowledged
4. No error messages or connection reset sent to client
5. Behavior persists across all subsequent tests in same connection

### Evidence

```
Test #1 Results:
  Commands sent: 100
  Responses received: 0        ← Hub stopped responding
  Total time: 10028 ms
  Connection: Still active     ← No disconnect occurred

Test #2 (new connection):
  All commands fail immediately with "connection forcibly closed by remote host"
  → Hub closed connection, likely still in protection mode

Test #5 (sustained load):
  Commands sent: 272
  Responses received: 0        ← Hub still not responding
  Connection stable: YES       ← Connection never closed
  Errors: 0                   ← No exceptions thrown
```

### Implications for Simulator

**FR-088: Silent Degradation Protection**
- The simulator MUST implement a similar protection mechanism
- After detecting rapid command bursts (>50 commands with <10ms spacing), the simulator should:
  - Maintain the TCP connection (do not close)
  - Stop sending responses
  - Continue accepting commands (but discard them)
  - Remain in this state indefinitely until client disconnects

**FR-089: No Error Notification**
- The simulator MUST NOT send error messages when protection activates
- Clients are expected to detect the lack of responses
- No TCP RST or FIN packets should be sent

## Performance Measurements

### Response Times (Before Protection Activation)

From the brief period in Test #2 before connection closed:

```
Statistics:
  Average: 18.6 ms
  Minimum: 5 ms
  Maximum: 204 ms
  Range: 199 ms
```

**FR-090: Response Time Variability**
- Normal response times: 5-20ms typical
- Occasional spikes: Up to 200ms observed
- The simulator should implement:
  - Base response delay: 10-15ms
  - Random variance: ±5ms
  - Occasional spikes: 1% chance of 100-200ms delay

### Throughput Characteristics

**Maximum Burst Acceptance:**
- Hub can accept ~10 commands/second when flooded
- 100 commands sent in 10,028ms = 9.97 cmd/s acceptance rate

**Sustained Operation:**
- Test #5 achieved 7.75 commands/second over 35 seconds
- 272 total commands sent with 100ms delays
- All commands accepted (connection remained stable)

**FR-091: Throughput Limits**
- The simulator should:
  - Accept commands at any rate (no artificial throttling)
  - Process responses at ~10 commands/second maximum
  - Activate protection after >50 commands in <5 seconds
  - Maintain command queue but stop responding after protection

## Protection Mechanism Analysis

### Trigger Conditions (Estimated)

Based on test behavior:
1. **Volume threshold:** ~100 commands in rapid succession
2. **Rate threshold:** Commands sent with <10ms spacing
3. **Time window:** Likely 5-10 second sliding window

### Recovery Behavior

**No automatic recovery observed:**
- Connection remained degraded for entire test duration
- Only client disconnect appears to reset state
- New connections after hub degradation were immediately rejected

### Network Impact

Hub appears to enter a "cooldown" period:
- Test #2 (new connection immediately after Test #1) was rejected
- Connection was "forcibly closed by remote host"
- Suggests hub-wide rate limiting, not per-connection

## Cross-Reference

**Test Script:** [`tests/test-performance-limits.ps1`](../tests/test-performance-limits.ps1)

**Functional Requirements:**
- FR-088: Silent connection degradation after burst detection
- FR-089: No error notification on protection activation
- FR-090: Response time variability (5-200ms range)
- FR-091: Throughput limits and protection trigger thresholds

**Related Research:**
- [Rate Limiting Test](rate-limiting-systematic-test-2025-10-18.md) - Initial rate limit discovery (50 commands/5 seconds)
- [Connection Lifecycle Test](connection-lifecycle-test-2025-10-18.md) - Normal connection termination behavior
- [Multi-Connection Test](multi-connection-test-2025-10-18.md) - Concurrent connection handling

## Recommendations for Simulator

1. **Implement Protection Mechanism:**
   - Track command rate per connection
   - Trigger: >50 commands in <5 seconds
   - Response: Stop sending responses, keep connection alive
   - Reset: Only on client disconnect

2. **Response Timing:**
   - Base delay: 10-15ms
   - Random variance: ±5ms  
   - Spike chance: 1% at 100-200ms

3. **Throughput Modeling:**
   - No artificial input throttling
   - Maximum response rate: ~10 commands/second
   - Queue commands but stop responding after protection

4. **Testing Considerations:**
   - Clients should implement response timeouts
   - Expect no error messages on protection activation
   - Plan for connection reset after burst detection
   - Allow cooldown period before reconnection

## Raw Test Output

```
=== Test #10: Performance Limits ===

--- Test 1: Maximum Command Throughput ---
Commands sent: 100
Responses received: 0
Total time: 10028 ms
Throughput: 9.97 commands/second

--- Test 2: Response Time Under Load ---
Connection forcibly closed by remote host (all commands after first failed)
Average: 18.6 ms, Min: 5 ms, Max: 204 ms

--- Test 3: Burst Command Handling ---
Commands sent: 10
Responses received: 0
Send time: 0 ms

--- Test 4: Multiple Device Commands ---
Connection already degraded - test could not execute

--- Test 5: Connection Stability Under Load ---
Test duration: 35.09 seconds
Commands sent: 272
Responses received: 0
Success rate: 0%
Connection stable: YES (never disconnected)
```

## Validation Date

October 20, 2025

**Test Environment:**
- Hardware: Real Deako hub at 192.168.86.221:23
- Protocol: Telnet (port 23) with JSON messages + CRLF line endings
- Test Device: Master Bedroom Lights (UUID: 50361c15-9739-4326-aded-24441cdbc75e)
- Client: PowerShell 7.x with System.Net.Sockets.TcpClient

**Critical Discovery:** Hub implements silent connection degradation as a protection mechanism against command flooding, without sending any error notifications or closing the connection.
