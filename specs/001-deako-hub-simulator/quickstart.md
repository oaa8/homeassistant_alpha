# Quickstart Guide: Deako Hub Simulator

**Branch**: `001-deako-hub-simulator` | **Date**: 2025-10-25  
**Audience**: Integration developers using the simulator for testing

This guide shows how to use the Deako Hub Simulator to test Home Assistant integrations without physical hardware.

---

## Installation

### Prerequisites

- Python 3.13 or later
- pip package manager

### Install from Source

```bash
# Clone repository
git clone https://github.com/oaa8/homeassistant_alpha.git
cd homeassistant_alpha

# Checkout simulator branch
git checkout 001-deako-hub-simulator

# Install simulator with dependencies
pip install -e .
```

---

## Basic Usage

### 1. Create Configuration File

Create `my-config.json` with your test devices:

```json
{
  "devices": [
    {
      "uuid": "a1b2c3d4-e5f6-4789-a012-b3c4d5e6f789",
      "name": "Kitchen Overhead",
      "capabilities": ["power", "dim"],
      "state": {"power": false, "dim": 0}
    },
    {
      "uuid": "b2c3d4e5-f6a7-4890-b123-c4d5e6f7a890",
      "name": "Living Room Main",
      "capabilities": ["power"],
      "state": {"power": false, "dim": null}
    }
  ],
  "network": {
    "host": "0.0.0.0",
    "port": 23,
    "http_port": 8080,
    "mdns_name": "local-integration"
  },
  "log_level": "INFO"
}
```

Validate your configuration:
```bash
jsonschema -i my-config.json specs/001-deako-hub-simulator/contracts/config.schema.json
```

### 2. Start Simulator

```bash
# Start with configuration file
deako-simulator my-config.json

# Expected output:
# [INFO] Loading configuration from my-config.json
# [INFO] Loaded 2 devices
# [INFO] Starting telnet server on 0.0.0.0:23
# [INFO] Starting HTTP API server on 0.0.0.0:8080
# [INFO] mDNS registered: local-integration._telnet._tcp.local. on port 23
# [INFO] Simulator ready
```

### 3. Connect Home Assistant

In Home Assistant:

1. Navigate to **Settings** → **Devices & Services**
2. Click **Add Integration**
3. Search for **Deako**
4. Integration should auto-discover via mDNS
5. Or manually configure with IP: `192.168.1.x:23`

---

## Testing Scenarios

### Scenario 1: Basic Device Control

**Objective**: Verify integration can discover, connect, and control devices

**Steps**:
1. Start simulator with 2-3 devices (mix of power-only and dimmable)
2. Add Deako integration in Home Assistant
3. Verify all devices appear in UI
4. Toggle power on/off via UI
5. Adjust dim level for dimmable devices
6. Confirm state changes reflected in UI

**Expected Behavior**:
- Discovery completes within 5 seconds
- All devices appear with correct names
- Power toggle responds within 2 seconds
- Dim changes respond within 2 seconds
- UI shows updated state after each change

### Scenario 2: Physical Button Simulation

**Objective**: Test integration handles external state changes (physical button presses)

**Setup**: Start simulator with HTTP API enabled

**Steps**:
```bash
# Press physical button (HTTP API)
curl -X POST http://localhost:8080/api/devices/a1b2c3d4-e5f6-4789-a012-b3c4d5e6f789/button

# Or change state directly
curl -X POST http://localhost:8080/api/devices/a1b2c3d4-e5f6-4789-a012-b3c4d5e6f789/state \
  -H "Content-Type: application/json" \
  -d '{"power": true, "dim": 75}'
```

**Expected Behavior**:
- Home Assistant receives EVENT message
- UI updates within 2 seconds without polling
- State changes persist across refreshes

### Scenario 3: Connection Recovery

**Objective**: Test integration handles connection loss and reconnection

**Steps**:
1. Start simulator, connect Home Assistant
2. Stop simulator (Ctrl+C)
3. Wait 10 seconds
4. Restart simulator with same config
5. Verify integration reconnects automatically

**Expected Behavior**:
- Integration detects connection loss
- Integration attempts reconnection
- Devices become available after reconnection
- State syncs correctly after reconnection

### Scenario 4: Multiple Clients (Passive Rejection)

**Objective**: Test integration handles zombie connections correctly

**Steps**:
1. Start simulator
2. Connect Home Assistant (client 1)
3. Connect second client manually via telnet (client 2)
4. Send commands from client 1 → should work
5. Send commands from client 2 → should be ignored (passive rejection)

**Expected Behavior**:
- First connection (HA) remains functional
- Second connection receives no responses (zombie)
- First connection unaffected by second connection

### Scenario 5: Rate Limiting

**Objective**: Test integration respects 100ms rate limit per device

**Steps**:
1. Start simulator
2. Send rapid CONTROL commands to same device (<100ms apart)
3. Observe simulator logs

**Expected Behavior**:
- Commands spaced <100ms are silently dropped
- Commands spaced ≥100ms are processed
- No error messages for rate-limited commands
- Integration backs off and retries

---

## Named Scenarios

Use predefined scenarios for quick state switching:

### Configuration

```json
{
  "devices": [...],
  "scenarios": [
    {
      "name": "all-on",
      "description": "All lights on at 100%",
      "device_states": {
        "a1b2c3d4-e5f6-4789-a012-b3c4d5e6f789": {"power": true, "dim": 100},
        "b2c3d4e5-f6a7-4890-b123-c4d5e6f7a890": {"power": true, "dim": null}
      }
    },
    {
      "name": "evening",
      "description": "Evening ambiance lighting",
      "device_states": {
        "a1b2c3d4-e5f6-4789-a012-b3c4d5e6f789": {"power": true, "dim": 40},
        "b2c3d4e5-f6a7-4890-b123-c4d5e6f7a890": {"power": false, "dim": null}
      }
    }
  ]
}
```

### Activate via HTTP API

```bash
# Switch to "all-on" scenario
curl -X POST http://localhost:8080/api/scenarios/all-on/activate

# Switch to "evening" scenario  
curl -X POST http://localhost:8080/api/scenarios/evening/activate
```

**Benefits**:
- One-line test state setup
- Reproducible test conditions
- Version-controlled test scenarios

---

## HTTP API Reference

Base URL: `http://localhost:8080/api`

### Get Device State

```bash
GET /devices/{uuid}

# Example
curl http://localhost:8080/api/devices/a1b2c3d4-e5f6-4789-a012-b3c4d5e6f789

# Response
{
  "uuid": "a1b2c3d4-e5f6-4789-a012-b3c4d5e6f789",
  "name": "Kitchen Overhead",
  "capabilities": ["power", "dim"],
  "state": {"power": true, "dim": 75}
}
```

### Update Device State

```bash
POST /devices/{uuid}/state
Content-Type: application/json

{
  "power": true,
  "dim": 75
}

# Example
curl -X POST http://localhost:8080/api/devices/a1b2c3d4-e5f6-4789-a012-b3c4d5e6f789/state \
  -H "Content-Type: application/json" \
  -d '{"power": true, "dim": 75}'
```

### Simulate Physical Button Press

```bash
POST /devices/{uuid}/button

# Example (toggle power)
curl -X POST http://localhost:8080/api/devices/a1b2c3d4-e5f6-4789-a012-b3c4d5e6f789/button
```

Button press behavior:
- If `power=false`: Turn on to previous dim level (or 100% if was 0%)
- If `power=true`: Turn off
- Triggers EVENT broadcast to all telnet connections

### List All Devices

```bash
GET /devices

# Example
curl http://localhost:8080/api/devices

# Response
{
  "devices": [
    {"uuid": "...", "name": "Kitchen Overhead", ...},
    {"uuid": "...", "name": "Living Room Main", ...}
  ]
}
```

### Activate Scenario

```bash
POST /scenarios/{name}/activate

# Example
curl -X POST http://localhost:8080/api/scenarios/all-on/activate

# Response
{
  "scenario": "all-on",
  "devices_updated": 2
}
```

### List Scenarios

```bash
GET /scenarios

# Example
curl http://localhost:8080/api/scenarios

# Response
{
  "scenarios": [
    {"name": "all-on", "description": "All lights on at 100%"},
    {"name": "evening", "description": "Evening ambiance"}
  ]
}
```

---

## Telnet Protocol Testing

For low-level protocol testing, connect directly via telnet:

```bash
# Connect to simulator
telnet localhost 23

# Send DEVICE_LIST request (with CRLF)
{"name": "DEVICE_LIST", "transactionId": "test-001"}

# Expected response:
{"name": "DEVICE_LIST", "transactionId": "test-001", "status": "ok", "data": {"deviceCount": 2}, "timestamp": 1729881234567}
{"name": "DEVICE_FOUND", "data": {"uuid": "a1b2c3d4-...", "name": "Kitchen Overhead", ...}, "timestamp": 1729881234568}
{"name": "DEVICE_FOUND", "data": {"uuid": "b2c3d4e5-...", "name": "Living Room Main", ...}, "timestamp": 1729881234569}

# Send CONTROL request
{"name": "CONTROL", "transactionId": "ctrl-001", "data": {"uuid": "a1b2c3d4-e5f6-4789-a012-b3c4d5e6f789", "power": true, "dim": 75}}

# Expected responses:
{"name": "CONTROL", "transactionId": "ctrl-001", "status": "ok", "timestamp": 1729881234670}
{"name": "EVENT", "data": {"uuid": "a1b2c3d4-...", "name": "Kitchen Overhead", "power": true, "dim": 75, "eventType": "DEVICE_STATE_CHANGE"}, "timestamp": 1729881236670}
```

**Important**: All messages must end with CRLF (`\r\n`). Most telnet clients send this automatically when you press Enter.

---

## Common Patterns

### Pattern 1: Automated Integration Tests

```python
import asyncio
import json

async def test_device_control():
    """Test control message flow."""
    # Connect to simulator
    reader, writer = await asyncio.open_connection('localhost', 23)
    
    # Send CONTROL
    control = {
        "name": "CONTROL",
        "transactionId": "test-001",
        "data": {"uuid": "a1b2c3d4-...", "power": True, "dim": 75}
    }
    writer.write(json.dumps(control).encode() + b'\r\n')
    await writer.drain()
    
    # Read acknowledgment
    ack_line = await reader.readline()
    ack = json.loads(ack_line[:-2].decode())
    assert ack["status"] == "ok"
    
    # Read EVENT
    event_line = await reader.readline()
    event = json.loads(event_line[:-2].decode())
    assert event["name"] == "EVENT"
    assert event["data"]["power"] == True
    assert event["data"]["dim"] == 75
```

### Pattern 2: Continuous Integration Setup

```yaml
# .github/workflows/integration-test.yml
name: Integration Tests
on: [push]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      
      - name: Start Deako Simulator
        run: |
          deako-simulator test-config.json &
          sleep 2  # Wait for startup
      
      - name: Run Integration Tests
        run: |
          pytest tests/integration/ --simulator=localhost:23
      
      - name: Stop Simulator
        run: pkill deako-simulator
```

### Pattern 3: Manual Testing with Scenarios

```bash
# Terminal 1: Start simulator with test scenarios
deako-simulator test-scenarios.json --log-level DEBUG

# Terminal 2: Activate scenarios for different tests
curl -X POST http://localhost:8080/api/scenarios/all-off/activate
# ... test something ...

curl -X POST http://localhost:8080/api/scenarios/evening/activate
# ... test something else ...

curl -X POST http://localhost:8080/api/scenarios/all-on/activate
# ... test another thing ...
```

---

## Troubleshooting

### Simulator won't start

**Error**: `Address already in use`

**Solution**: Another process is using port 23 or 8080
```bash
# Find process using port
lsof -i :23
lsof -i :8080

# Change port in config
{"network": {"port": 2323, "http_port": 8888}}
```

### mDNS discovery not working

**Error**: Integration doesn't auto-discover simulator

**Solutions**:
1. Check firewall allows mDNS (UDP port 5353)
2. Connect manually using IP:port
3. Check simulator logs for mDNS registration success
4. Verify mDNS service name matches integration expectations

### Integration shows "Unavailable"

**Possible causes**:
- Simulator not running
- Wrong IP/port configured
- Firewall blocking connections
- Integration using wrong port (23 for telnet, not 8080)

**Debug**:
```bash
# Test connection manually
telnet localhost 23

# Check simulator is listening
netstat -an | grep :23

# Check simulator logs
deako-simulator config.json --log-level DEBUG
```

### Commands not working

**Symptom**: CONTROL commands sent but nothing happens

**Possible causes**:
1. **Rate limiting**: Commands too fast (<100ms apart)
   - Solution: Add delays between commands
2. **Invalid UUID**: Device UUID doesn't exist
   - Solution: Check UUID matches config
3. **Second connection (zombie)**: Only first connection functional
   - Solution: Ensure only one active connection

---

## Configuration Examples

### Minimal Config (1 device)

```json
{
  "devices": [
    {
      "uuid": "12345678-1234-4123-8123-123456789012",
      "name": "Test Light",
      "capabilities": ["power"],
      "state": {"power": false, "dim": null}
    }
  ]
}
```

### Typical Home (10 devices, mixed types)

```json
{
  "devices": [
    {"uuid": "...", "name": "Kitchen Overhead", "capabilities": ["power", "dim"], "state": {"power": false, "dim": 0}},
    {"uuid": "...", "name": "Kitchen Under-Cabinet", "capabilities": ["power", "dim"], "state": {"power": false, "dim": 0}},
    {"uuid": "...", "name": "Living Room Main", "capabilities": ["power", "dim"], "state": {"power": false, "dim": 0}},
    {"uuid": "...", "name": "Living Room Accent", "capabilities": ["power", "dim"], "state": {"power": false, "dim": 0}},
    {"uuid": "...", "name": "Bedroom Overhead", "capabilities": ["power", "dim"], "state": {"power": false, "dim": 0}},
    {"uuid": "...", "name": "Bedroom Closet", "capabilities": ["power"], "state": {"power": false, "dim": null}},
    {"uuid": "...", "name": "Bathroom Vanity", "capabilities": ["power"], "state": {"power": false, "dim": null}},
    {"uuid": "...", "name": "Hallway", "capabilities": ["power"], "state": {"power": false, "dim": null}},
    {"uuid": "...", "name": "Garage", "capabilities": ["power"], "state": {"power": false, "dim": null}},
    {"uuid": "...", "name": "Porch", "capabilities": ["power"], "state": {"power": false, "dim": null}}
  ],
  "network": {
    "host": "0.0.0.0",
    "port": 23,
    "http_port": 8080,
    "mdns_name": "local-integration"
  },
  "scenarios": [
    {"name": "all-off", "description": "All lights off", "device_states": {...}},
    {"name": "all-on", "description": "All lights on at 100%", "device_states": {...}},
    {"name": "evening", "description": "Evening lighting", "device_states": {...}}
  ],
  "log_level": "INFO"
}
```

---

## Next Steps

- **Implementation Development**: See `plan.md` for implementation phases
- **Protocol Details**: See `spec.md` for complete functional requirements
- **API Reference**: See `contracts/messages.schema.json` for message schemas
- **Hardware Validation**: See `research/` for real hub behavior tests

---

## Support

- **Issues**: File on GitHub repository
- **Documentation**: See `spec.md`, `data-model.md`, `research.md`
- **Protocol Reference**: https://github.com/DeakoLights/deako-api (official API docs)
