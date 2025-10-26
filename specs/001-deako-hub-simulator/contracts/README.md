# JSON Schema Contracts

This directory contains JSON Schema definitions for the Deako Hub Simulator protocol and configuration.

## Files

### config.schema.json

Defines the structure for simulator configuration files.

**Usage:**
```bash
# Validate configuration file
jsonschema -i config.json contracts/config.schema.json
```

**IDE Support:**
Add to VS Code `settings.json`:
```json
{
  "json.schemas": [
    {
      "fileMatch": ["**/deako-*.config.json"],
      "url": "./contracts/config.schema.json"
    }
  ]
}
```

### messages.schema.json

Defines all protocol message formats (DEVICE_LIST, CONTROL, EVENT, etc.).

**Usage:**
```python
import json
import jsonschema

# Validate message
with open('contracts/messages.schema.json') as f:
    schema = json.load(f)

message = {"name": "CONTROL", "transactionId": "123", ...}
jsonschema.validate(message, schema)
```

## Validation Rules

### Configuration Validation

- At least one device required
- Device UUIDs must be unique and valid UUID v4 format
- Devices with "dim" capability must also have "power" capability
- Ports must be in range 1-65535
- Log level must be DEBUG/INFO/WARNING/ERROR
- Scenario device UUIDs must reference existing devices

### Message Validation

- All messages must have required "name" field
- Request messages must include "transactionId"
- Response messages must include "status" and "timestamp"
- UUIDs must match pattern: `^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$`
- Dim levels must be 0-100
- Power state must be boolean

## Hardware Quirks Encoded in Schemas

### DEVICE_POLL Response

The schema enforces `status: "error"` for DEVICE_POLL responses, matching real hub behavior (FR-023):

```json
{
  "devicePollResponse": {
    "properties": {
      "status": {
        "const": "error",
        "description": "QUIRK: Real hub always returns 'error' even on success"
      }
    }
  }
}
```

## Testing with Schemas

Schemas enable contract testing:

```python
def test_control_message_format():
    """Ensure CONTROL messages match schema."""
    message = simulator.create_control_response("tx-123")
    jsonschema.validate(message, messages_schema)
```

## References

- **Data Model**: [../data-model.md](../data-model.md) - Entity definitions and relationships
- **Specification**: [../spec.md](../spec.md) - Functional requirements and protocol details
- **Hardware Tests**: [../research/](../research/) - Validation against real hub
