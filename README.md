# Deako Alpha HA integration

Component to integrate with Deako using the public local api.

**This component will set up the following platforms.**

Platform | Description
-- | --
`Lights` | Control your lights

---

## Deako Hub Simulator

For integration developers: This repository also includes a **Deako Hub Simulator** for testing the Home Assistant integration without physical hardware.

### Quick Start

```bash
# Install simulator from source
cd /path/to/homeassistant_alpha
pip install -e .

# Run simulator with default config (3 sample devices)
python -m deako_simulator

# Or run as standalone command
deako-simulator

# Or with custom configuration file
deako-simulator my-config.json

# With command-line options
deako-simulator --port 23 --http-port 8080 --log-level DEBUG
```

### Features

- **Auto-Discovery**: mDNS/Zeroconf service advertisement (`_telnet._tcp.local.`)
- **Telnet Protocol**: Full implementation of Deako hub telnet protocol (port 23)
- **HTTP API**: Runtime control and state inspection (port 8080)
- **Named Scenarios**: Quick test state switching with predefined device configurations
- **Physical Button Simulation**: Trigger external state changes via HTTP API
- **Hardware-Validated Behaviors**: Rate limiting, connection handling, protocol quirks replicated from real hub testing
- **Configurable Quirks**: Inject whitespace, delays, malformed messages for resilience testing
- **Connection Resilience**: Simulate network failures, connection refusal, high latency
- **Comprehensive Logging**: All protocol messages, connection events, state changes with component tags

### Example Configuration

Create `my-config.json`:

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
      "name": "Living Room",
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
  "scenarios": [
    {
      "name": "all-on",
      "description": "All lights on at 100%",
      "device_states": {
        "a1b2c3d4-e5f6-4789-a012-b3c4d5e6f789": {"power": true, "dim": 100},
        "b2c3d4e5-f6a7-4890-b123-c4d5e6f7a890": {"power": true, "dim": null}
      }
    }
  ],
  "log_level": "INFO"
}
```

Start with config: `deako-simulator my-config.json`

### HTTP API Quick Reference

```bash
# List all devices
curl http://localhost:8080/api/devices

# Get device state
curl http://localhost:8080/api/devices/{uuid}

# Update device state
curl -X POST http://localhost:8080/api/devices/{uuid}/state \
  -H "Content-Type: application/json" \
  -d '{"power": true, "dim": 75}'

# Simulate physical button press (toggle power)
curl -X POST http://localhost:8080/api/devices/{uuid}/button

# Activate named scenario
curl -X POST http://localhost:8080/api/scenarios/all-on/activate

# List available scenarios
curl http://localhost:8080/api/scenarios
```

### Testing with Home Assistant

1. Start simulator: `deako-simulator my-config.json`
2. In Home Assistant, go to **Settings** → **Devices & Services**
3. Click **Add Integration**, search for **Deako**
4. Integration auto-discovers simulator via mDNS
5. Or manually configure with IP: `192.168.1.x:23`

All devices from your config will appear in Home Assistant with full control support.

### Documentation

- **[Quickstart Guide](specs/001-deako-hub-simulator/quickstart.md)**: Detailed usage guide with testing scenarios
- **[Specification](specs/001-deako-hub-simulator/spec.md)**: Complete functional requirements and protocol details
- **[Data Model](specs/001-deako-hub-simulator/data-model.md)**: Device structures and message formats
- **[Research](specs/001-deako-hub-simulator/research.md)**: Hardware validation testing and findings

### Troubleshooting

**Simulator won't start - "Address already in use"**
```bash
# Find process using port
lsof -i :23
# Use different port
deako-simulator --port 2323 my-config.json
```

**Integration doesn't discover simulator**
- Check firewall allows mDNS (UDP port 5353)
- Connect manually using IP:port instead
- Check simulator logs: `deako-simulator --log-level DEBUG`

**Commands not working**
- Verify device UUID matches config
- Check rate limiting (100ms minimum between commands to same device)
- Ensure only one telnet connection active (simulator uses passive rejection model)
- Check simulator logs for error messages

### Requirements

- Python 3.13 or later
- Dependencies: aiohttp>=3.9.0, zeroconf>=0.131.0, jsonschema>=4.20.0
- Network access for ports 23 (telnet) and 8080 (HTTP API)

---

## Home Assistant Integration Installation

1. Go to HACS/Integration in Home Assistant
2. In the upper right, click the three dots
3. Click "custom repositories"
4. Under "Repository", enter the url for Deako Alpha HA integration: [https://github.com/DeakoLights/homeassistant_alpha]()
5. Under "Category", select "Integration"
6. "Add"
7. Install Deako Alpha HA integration
8. Restart Home Assistant
9. Go to Configuration/Integrations
10. Deako should now be in the list of searchable integrations and auto discovered

## Manual Installation

1. Using the tool of choice open the directory (folder) for your HA configuration (where you find `configuration.yaml`).
2. If you do not have a `custom_components` directory (folder) there, you need to create it. It's highly recommended using the custom components manager [HACS](https://hacs.xyz/).
3. In the `custom_components` directory (folder) create a new folder called `deako`.
4. Download _all_ the files from the `custom_components/deako/` directory (folder) in this repository.
5. Place the files you downloaded in the new directory (folder) you created.
6. Restart Home Assistant
7. Deako should now be in the list of searchable integrations

## Configuration

Configuration is done automatically during integration setup.
