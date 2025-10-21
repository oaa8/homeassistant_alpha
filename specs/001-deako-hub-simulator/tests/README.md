# Deako Hub Hardware Test Scripts

This directory contains PowerShell test scripts for validating actual Deako hub behavior against the simulator specification.

**Test Hub**: 192.168.86.221:23  
**Test Device**: Master Bedroom Lights (UUID: `50361c15-9739-4326-aded-24441cdbc75e`)  
**Protocol**: Telnet-based JSON with CRLF line endings

## Test Scripts Index

### Rate Limiting Tests
- **`test-rate-limiting.ps1`** - Initial rapid-fire test (deprecated, see v2)
  - Status: ❌ Flawed methodology (measured script speed not network timing)
  - Date: October 17, 2025
  - Results: See `../research/rate-limiting-test-2025-10-17.md`

- **`test-rate-limiting-v2.ps1`** ⭐ 
  - Status: ✅ Definitive test with systematic delay testing
  - Date: October 18, 2025
  - Results: See `../research/rate-limiting-systematic-test-2025-10-18.md`
  - **Key Findings**:
    - 100ms minimum spacing for 100% reliability (not 800ms as documented)
    - 0ms spacing = 5% success rate
    - 50ms spacing = 70% success rate
    - 100ms+ spacing = 100% success rate
    - Zero DEVICE_BUSY errors observed (hub silently drops commands)
  - Spec Impact: Updated FR-023, FR-064, FR-074

### Connection Management Tests
- **`test-multi-connection.ps1`** ⭐
  - Status: ✅ Validated multi-connection behavior
  - Date: October 18, 2025
  - Results: See `../research/multi-connection-test-2025-10-18.md`
  - **Key Findings**:
    - Hub accepts multiple TCP connections (no rejection)
    - Only first connection is functional ("passive rejection")
    - Subsequent connections are "zombie connections" (silent)
    - No error messages for non-functional connections
  - Spec Impact: Updated FR-072

### Validation Tests
- **`test-dim-edge-cases.ps1`** ⭐
  - Status: ✅ Validated dim value handling
  - Date: October 18, 2025
  - Results: See `../research/dim-validation-test-2025-10-18.md`
  - **Key Findings**:
    - Hub accepts ALL numeric dim values without validation
    - No REQUEST_INVALID errors for out-of-range values
    - Accepts: -1, 101, 255, 1000, 50.5, 99.999
    - All return `status: "ok"`
  - Spec Impact: Complete rewrite of FR-071

### State Management Tests
- **`test-device-state.ps1`** 
  - Status: ⚠️ Incomplete - DEVICE_POLL investigation needed
  - Date: October 18, 2025
  - Results: See `../research/device-state-test-2025-10-18.md`
  - **Partial Findings**:
    - Hub accepts all power/dim combinations
    - Power=true + dim=0 is valid
    - Power=false + dim=100 is valid
    - Flexible state model (no rigid validation)
  - **Open Questions**:
    - Does DEVICE_POLL message type work?
    - How to query current device state?
    - State persistence after commands?

### DEVICE_POLL Investigation ✅ COMPLETE
- **`test-device-poll-systematic.ps1`** ⭐
  - Status: ✅ Identified correct format and hub quirk
  - Date: October 18, 2025
  - **Key Findings**:
    - Correct format: `{"target": "uuid"}` at root level (NOT in data field)
    - Hub returns `status: "error"` even on SUCCESS (misleading!)
    - Response data field contains full device info (name, uuid, capabilities, state)
    - Must ignore status field and check for populated data field
  - Spec Impact: Must implement DEVICE_POLL with status="error" quirk

- **`test-device-poll-final.ps1`** ⭐
  - Status: ✅ Validated DEVICE_POLL works reliably
  - Date: October 18, 2025
  - **Validation**: Changed device state, polled it, confirmed response accuracy
  - **Critical Quirk**: Hub firmware bug returns status="error" for successful queries

### Whitespace Behavior Tests ✅ COMPLETE
- **`test-whitespace-behavior.ps1`** ⭐
  - Status: ✅ Comprehensive whitespace testing
  - Date: October 18, 2025
  - Results: See `../research/whitespace-behavior-test-2025-10-18.md`
  - **Key Findings**:
    - Hub does NOT send whitespace messages (30-second idle test)
    - Hub silently ignores whitespace from clients (no responses)
    - Hub survives whitespace flood (100 lines) without disconnect
    - Connection remains functional after whitespace
  - Spec Impact: FR-024, FR-026 should be optional/configurable (not default behavior)

### Physical Button Behavior Tests ✅ COMPLETE
- **`test-physical-button-behavior.ps1`** ⭐
  - Status: ✅ Manual testing with real button presses
  - Date: October 18, 2025
  - Results: See `../research/physical-button-behavior-test-2025-10-18.md`
  - **Key Findings**:
    - Physical button presses immediately generate EVENT messages
    - Each press generates separate EVENT (toggle behavior)
    - Minimum interval observed: 436ms (natural mechanical/human limit)
    - No artificial debouncing by hub
    - EVENTs include full state (power + dim), not just changed fields
    - Commands and physical buttons work independently (no conflicts)
  - Spec Impact: NEW FR-075 (full state in EVENTs), NEW FR-076 (button simulation API)

### Error Code Validation Tests ✅ COMPLETE
- **`test-error-codes.ps1`** ⭐
  - Status: ✅ Systematic error code validation
  - Date: October 18, 2025
  - Results: See `../research/error-code-validation-test-2025-10-18.md`
  - **Key Findings**:
    - Only 3 of 5 documented error codes exist
    - ✅ REQUEST_UNKNOWN (invalid message type)
    - ✅ REQUEST_MALFORMED (invalid JSON syntax)
    - ✅ REQUEST_INVALID (missing required fields)
    - ❌ DEVICE_BUSY does not exist (confirmed with 10 rapid commands)
    - ❌ DEVICE_UNKNOWN does not exist (returns REQUEST_INVALID instead)
    - Malformed JSON is silently ignored (no response at all)
  - Spec Impact: FR-066 updated, NEW FR-077 (malformed JSON silent drop)

### Message Format Edge Case Tests ✅ COMPLETE
- **`test-message-format-edge-cases.ps1`** ⭐
  - Status: ✅ JSON parsing robustness validation
  - Date: October 18, 2025
  - Results: See `../research/message-format-edge-cases-test-2025-10-18.md`
  - **Key Findings**:
    - ✅ Extra fields in messages: Accepted and ignored
    - ✅ Field order: Independent (any order works)
    - ❌ Case sensitivity: Type field must be uppercase ("PING" not "ping")
    - ✅ Whitespace in JSON: Ignored (standard JSON parsing)
    - ✅ Optional timestamp: Not required in client messages
    - ✅ Null values: Interpreted as "no change" (dim=null keeps brightness)
    - ✅ Unicode characters: Supported (tested with emoji)
    - ⚠️ Very long strings: May be silently dropped (1000-char src field no response)
  - Spec Impact: NEW FR-078 through FR-083 (6 new requirements)

### Connection Lifecycle Tests ✅ COMPLETE
- **`test-connection-lifecycle.ps1`** ⭐
  - Status: ✅ Comprehensive connection lifecycle validation
  - Date: October 18, 2025
  - Results: See `../research/connection-lifecycle-test-2025-10-18.md`
  - **Key Findings**:
    - ✅ No idle timeout (connection survived 5+ minutes idle)
    - ✅ PING keepalive works (9 PINGs over 5 minutes)
    - ✅ Graceful disconnect (FIN) handled cleanly
    - ✅ Immediate reconnection allowed (< 1 second)
    - ✅ Ungraceful disconnect (RST) handled robustly
    - ✅ Incomplete message buffering (hub buffers then cleans up on disconnect)
    - Hub broadcasts EVENTs to idle connections continuously
  - Spec Impact: NEW FR-084 through FR-087 (4 new connection requirements)

## Utility Scripts
- **`get-device-list.ps1`** - Simple script to list all devices on hub

## Running Tests

All tests connect directly to the hardware hub at 192.168.86.221:23. To run a test:

```powershell
pwsh -File tests/<test-name>.ps1
```

## Test Results Cross-Reference

| Test | Research Document | Spec Requirements | Status |
|------|------------------|------------------|--------|
| Rate Limiting v2 | `research/rate-limiting-systematic-test-2025-10-18.md` | FR-023, FR-064, FR-074 | ✅ Complete |
| Multi-Connection | `research/multi-connection-test-2025-10-18.md` | FR-072 | ✅ Complete |
| Dim Validation | `research/dim-validation-test-2025-10-18.md` | FR-071 | ✅ Complete |
| Device State | `research/device-state-test-2025-10-18.md` | Multiple | ✅ Complete |
| DEVICE_POLL | `research/device-state-test-2025-10-18.md` | Multiple | ✅ Complete |
| Whitespace | `research/whitespace-behavior-test-2025-10-18.md` | FR-024, FR-026 | ✅ Complete |
| Physical Buttons | `research/physical-button-behavior-test-2025-10-18.md` | FR-075, FR-076 | ✅ Complete |
| Error Codes | `research/error-code-validation-test-2025-10-18.md` | FR-066, FR-077 | ✅ Complete |
| Message Formats | `research/message-format-edge-cases-test-2025-10-18.md` | FR-078 to FR-083 | ✅ Complete |
| Connection Lifecycle | `research/connection-lifecycle-test-2025-10-18.md` | FR-084 to FR-087 | ✅ Complete |

## Test Methodology Notes

### Lessons Learned
1. **Timing Measurements**: PowerShell `Measure-Command` measures script execution, not network timing. Use controlled delays between commands instead.
2. **Fresh Connections**: Stale connections may buffer messages. Create fresh connection for isolated tests.
3. **Response Collection**: Wait sufficient time (2-3 seconds) to collect all responses before concluding no response was received.
4. **Hub Quirks**: 
   - Silent dropping of rapid commands (no errors)
   - Passive rejection of multiple connections (no errors)
   - No validation of command parameters (always returns "ok")
   - No idle timeout on connections (tested > 5 minutes)
   - Immediate reconnection allowed (no cooldown)

### Best Practices
- Use `Start-Sleep -Milliseconds 200` between commands for reliability
- Always flush stream: `$stream.Flush()`
- Clear pending messages before critical tests
- Test multiple iterations to identify patterns vs. one-off behavior
- Cross-reference with API documentation before concluding features don't exist
- For connection lifecycle tests, allow sufficient time (5+ minutes) for idle timeout detection
- Capture unsolicited EVENTs during tests (physical button presses provide real-world data)

## Total Test Statistics
- **Total commands sent**: 300+
- **Test sessions**: 9
- **Spec updates**: 17 functional requirements added/corrected (FR-071 through FR-087)
- **Critical bugs found**: 0 (hub works as designed, documentation gaps identified)
- **Test time**: ~30 minutes total execution time

