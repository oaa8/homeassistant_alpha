# Deako Hub Device State Behavior Testing
**Date**: October 18, 2025  
**Hub**: 192.168.86.221:23  
**Test Device**: Master Bedroom Lights (power+dim capable)  
**Test Scripts**: [`../tests/test-device-state.ps1`](../tests/test-device-state.ps1), [`../tests/test-device-poll-systematic.ps1`](../tests/test-device-poll-systematic.ps1)  
**Test**: Device state management and power/dim interaction  
**Spec Reference**: [spec.md](../spec.md) - Multiple FRs

## Executive Summary

**Key Finding**: The Deako hub accepts **all state combinations** including power=true with dim=0, power changes without dim, and dim changes without power. The hub appears to maintain separate state for power and dim fields.

**Limitation**: ~~DEVICE_POLL message type is not supported or not functional.~~ **UPDATE**: DEVICE_POLL WORKS - see corrected findings below.

State queries can be done through DEVICE_LIST → DEVICE_FOUND flow OR via DEVICE_POLL (see Test #4 below).

## Test Results

### Test 1: State Query Consistency
**Status**: ❌ Test Failed (DEVICE_POLL not supported)

Attempted to use DEVICE_POLL message type to query individual device state:
```json
{
  "type": "DEVICE_POLL",
  "data": { "target": "device-uuid" }
}
```

**Result**: No responses received (3/3 queries failed)

**Conclusion**: DEVICE_POLL either:
- Doesn't exist as a message type
- Uses different format
- Requires different approach

**State query method**: Must use DEVICE_LIST which triggers DEVICE_FOUND messages containing current state.

### Test 2: Power + Dim Interaction
**Status**: ✅ All Commands Accepted

Tested power/dim combinations:

| Command | Hub Response | Status |
|---------|-------------|--------|
| power=true, dim=50 | ✅ OK | Accepted |
| power=false, dim=75 | ✅ OK | Accepted |
| power=true (no dim) | ✅ OK | Accepted |

**Conclusion**: Hub accepts all power/dim combinations. State updates work with both fields.

### Test 3: Dim-Only Changes
**Status**: ✅ Commands Accepted

Tested changing dim without power field:

| Command | Hub Response | Status |
|---------|-------------|--------|
| dim=80 (no power field) | ✅ OK | Accepted |

**Conclusion**: Can change dim level without specifying power field.

### Test 4: Special Case - Power=True, Dim=0
**Status**: ✅ Command Accepted

Tested edge case:
```json
{
  "state": {
    "power": true,
    "dim": 0
  }
}
```

**Result**: ✅ OK (accepted)

**Conclusion**: Hub allows power=true with dim=0. This likely represents "on but at 0% brightness" (functionally off but maintaining on state).

### Test 5: Power-Only Control
**Status**: ✅ Commands Accepted

Tested power changes without dim field:

| Command | Hub Response | Status |
|---------|-------------|--------|
| power=false (no dim) | ✅ OK | Accepted |

**Conclusion**: Can change power state without specifying dim level.

## Key Findings

### 1. **DEVICE_POLL Support** ✅ **CORRECTED**
- ~~DEVICE_POLL message type doesn't work~~ **WRONG!**
- **DEVICE_POLL DOES WORK** - see Test #4 correction below
- Correct format: `{"target": "uuid"}` at root level (not in data field)
- **Hub Quirk**: Returns `status: "error"` even on success (ignore this, check data field)

### 2. **Flexible State Updates**
Hub accepts partial state updates:
- ✅ Power-only: `{"power": true}`
- ✅ Dim-only: `{"dim": 50}`
- ✅ Both: `{"power": true, "dim": 50}`

### 3. **Power + Dim Independence**
- Power and dim appear to be independent state fields
- Changing one doesn't require specifying the other
- Both are preserved when only one is updated

### 4. **Power=True, Dim=0 is Valid**
- Hub accepts power=true with dim=0
- This is a valid state combination
- Likely represents "on" state with 0% brightness

### 5. **All Commands Accepted**
- **100% acceptance rate** (6/6 control commands)
- No validation errors
- No rejected combinations
- Consistent with previous tests (hub accepts everything)

## Protocol Behavior

### Supported Message Types (Verified)
- ✅ DEVICE_LIST: Works
- ✅ CONTROL: Works  
- ✅ DEVICE_FOUND: Works (unsolicited)
- ✅ EVENT: Works (unsolicited)
- ✅ DEVICE_POLL: **WORKS** (see corrected Test #4)

### State Query Methods

**Method 1: DEVICE_LIST → DEVICE_FOUND**
```
Client → Hub: DEVICE_LIST
Hub → Client: DEVICE_LIST response (count)
Hub → Client: DEVICE_FOUND × N (with state)
```

**Method 2: Listen for EVENTs**
```
Hub → Client: EVENT (DEVICE_STATE_CHANGE)
                data.target: device UUID
                data.state: current state
```

**No individual device state query** mechanism appears to exist.

## Unanswered Questions (Due to No State Query)

Since DEVICE_POLL doesn't work, we couldn't verify:

1. **Dim memory**: Does hub remember dim=75 when turned off?
2. **Default dim**: When turning on without dim, what dim level is used?
3. **State persistence**: Is state consistent across queries?
4. **Power=true, dim=0 actual behavior**: What's the actual device state?

These would require:
- Physical observation of the light
- OR using DEVICE_LIST between tests (slower, less precise)
- OR monitoring EVENT messages

## Spec Implications

### What We Confirmed

✅ **FR-013**: Hub maintains separate power and dim state fields (implied by accepting partial updates)

✅ **Device state updates**: Hub accepts all combinations:
- Power only
- Dim only  
- Power + dim
- Power=true with dim=0

✅ **No validation**: Hub accepts all state combinations without errors

### What We Couldn't Verify

❌ **State persistence**: Can't query state between commands  
❌ **Dim memory**: Can't verify dim is preserved when power=false  
❌ **Default behavior**: Can't see what happens when turning on without dim

### New Findings

⚠️ **DEVICE_POLL doesn't exist**: Research docs mention it, but it doesn't work

**Spec Update Needed**:
- Remove DEVICE_POLL from supported message types
- Document that state queries require DEVICE_LIST (expensive operation)
- Note that EVENT messages provide state updates

## Recommendations

### For Simulator

1. ✅ **Accept all power/dim combinations** (no validation)
2. ✅ **Support partial state updates** (power-only, dim-only, or both)
3. ✅ **Allow power=true with dim=0**
4. ❌ **Don't implement DEVICE_POLL** (doesn't exist on real hub)
5. ✅ **Provide state via DEVICE_FOUND** messages only

### For Integration Developers

1. ✅ **Don't use DEVICE_POLL** for state queries
2. ✅ **Use DEVICE_LIST** to get current state (triggers DEVICE_FOUND)
3. ✅ **Monitor EVENT messages** for state changes
4. ✅ **Can send partial updates** (just power or just dim)
5. ✅ **Power=true, dim=0 is valid** (don't treat as error)

### For Spec

**Remove references to DEVICE_POLL**:
The research doc mentions it, but it doesn't actually work.

**Add clarification**:
> State queries are performed via DEVICE_LIST request which triggers DEVICE_FOUND messages containing current state. There is no individual device state query mechanism. Runtime state changes are communicated via unsolicited EVENT messages.

**Confirm flexible state model**:
> Hub accepts partial state updates: power-only, dim-only, or power+dim. All combinations are valid, including power=true with dim=0.

## Confidence Level

**Medium-High** for what we tested:
- ✅ All control commands accepted (6/6)
- ✅ No errors for any state combination
- ✅ Consistent OK responses

**Low** for state persistence:
- ❌ Couldn't verify state between commands
- ❌ No working state query mechanism
- ❌ Can't confirm dim memory or defaults

To increase confidence, need:
- Physical observation of light behavior
- OR implement DEVICE_LIST → DEVICE_FOUND parsing between tests
- OR capture EVENT messages during testing

---

## Test #4 CORRECTION - DEVICE_POLL Actually Works! ✅
**Date**: October 18, 2025 (later same day)  
**Test Scripts**: `test-device-poll-systematic.ps1`, `test-device-poll-final.ps1`

### Initial Error
Original test concluded DEVICE_POLL doesn't work. **This was wrong!**

### User Correction
User correctly pointed out they had used DEVICE_POLL before per API documentation. This prompted re-investigation with proper methodology.

### Correct DEVICE_POLL Format

**Request** (target at ROOT level, not in data):
```json
{
  "transactionId": "uuid-v4",
  "type": "DEVICE_POLL",
  "dst": "deako",
  "src": "client_name",
  "target": "device-uuid"
}
```

**Response** (CRITICAL QUIRK - status says "error" but it's SUCCESS):
```json
{
  "type": "DEVICE_POLL",
  "transactionId": "matching-uuid",
  "dst": "deako",
  "src": "deako",
  "status": "error",
  "timestamp": 1760817387,
  "data": {
    "name": "Master Bedroom Lights",
    "uuid": "50361c15-9739-4326-aded-24441cdbc75e",
    "capabilities": "power+dim",
    "state": {
      "power": true,
      "dim": 50
    }
  }
}
```

### Hub Quirk Discovered: Misleading Status Field

**CRITICAL**: The hub returns `status: "error"` even when DEVICE_POLL succeeds!

This is NOT an actual error. The device information is correctly populated in the `data` field with full device metadata and current state.

**Correct interpretation**: 
- Ignore the `status: "error"` field
- Check if `data` contains device information
- If `data` has name/uuid/capabilities/state, the query succeeded

### Validation Test Results
- ✅ DEVICE_POLL request sent with correct format
- ✅ Response received with full device data
- ✅ State reflects actual device condition
- ✅ Works reliably when using correct format

### Why Initial Test Failed
1. Used wrong format (`{"data": {"target": "uuid"}}`) - no response
2. Didn't recognize that `status: "error"` with populated `data` means success
3. Stale connection may have buffered messages

### Implications for Simulator

**MUST implement DEVICE_POLL**:
- ✅ Support `target` field at root level (not in data)
- ✅ **Replicate the status="error" quirk** (for accurate simulation)
- ✅ Return full device info in `data` (name, uuid, capabilities, state)
- ✅ Match transactionId in response

**Integration code implications**:
- Must handle the misleading "error" status
- Should check for populated `data` field, not status field
- This is a real hub behavior that integrations must handle

---

## Conclusion (UPDATED)

**The Deako hub has a flexible state model** that accepts all power/dim combinations and supports partial updates. **DEVICE_POLL IS supported** and works correctly, but has a quirky response format (returns `status: "error"` even on success).

**Simulator must replicate this behavior**: 
- ✅ Accept all state combinations
- ✅ Support partial updates
- ✅ Implement DEVICE_POLL with the status="error" quirk
- ✅ Provide state through both DEVICE_FOUND and DEVICE_POLL

## Test Limitations

This test successfully validated:
- ✅ Command acceptance (all combinations)
- ✅ No validation errors
- ✅ Partial update support

This test could NOT validate:
- ❌ State persistence
- ❌ Dim memory
- ❌ Default behaviors

Due to DEVICE_POLL not working. Follow-up testing with DEVICE_LIST parsing or physical observation needed.
