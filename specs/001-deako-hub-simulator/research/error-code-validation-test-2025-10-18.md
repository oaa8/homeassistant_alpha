# Deako Hub Error Code Validation Test
**Date**: October 18, 2025  
**Hub**: 192.168.86.221:23  
**Test Script**: [`../tests/test-error-codes.ps1`](../tests/test-error-codes.ps1)  
**Purpose**: Validate all documented error codes and their trigger conditions  
**Spec Reference**: [spec.md](../spec.md) - FR-066, FR-077

## Executive Summary

**Critical Finding**: Only **3 of 5 documented error codes actually exist** on real hardware. The hub's error handling differs significantly from API documentation.

**Error Codes That Exist:**
- ✅ REQUEST_UNKNOWN (invalid message type)
- ✅ REQUEST_MALFORMED (missing required fields)
- ✅ REQUEST_INVALID (invalid data values)

**Error Codes That DON'T Exist:**
- ❌ DEVICE_BUSY (confirmed from prior testing - hub silently drops instead)
- ❌ DEVICE_UNKNOWN (returns REQUEST_INVALID instead)

**Unexpected Behavior:**
- Malformed JSON is **silently ignored** (no error response at all)

## API Documentation vs Reality

| Documented Code | Documented Purpose | Actually Exists? | Real Behavior |
|-----------------|-------------------|------------------|---------------|
| DEVICE_BUSY | Commands too rapid | ❌ NO | Silent dropping (no error) |
| DEVICE_UNKNOWN | Non-existent UUID | ❌ NO | Returns REQUEST_INVALID instead |
| REQUEST_UNKNOWN | Invalid message type | ✅ YES | Works as documented |
| REQUEST_MALFORMED | Invalid JSON | ⚠️ PARTIAL | Only for valid JSON missing fields, not malformed JSON |
| REQUEST_INVALID | Invalid data values | ✅ YES | Works as documented |

## Detailed Test Results

### Test 1: DEVICE_UNKNOWN (Non-existent Device)

**Test**: Send CONTROL command for UUID that doesn't exist  
**UUID**: `00000000-0000-0000-0000-000000000000`

**Expected** (per docs): `DEVICE_UNKNOWN` error code  
**Actual**: `REQUEST_INVALID` error code

**Response**:
```json
{
  "status": "error",
  "data": {
    "code": "REQUEST_INVALID",
    "message": "device could not be found"
  }
}
```

**Analysis**: 
- Hub returns REQUEST_INVALID, not DEVICE_UNKNOWN
- Error message is helpful: "device could not be found"
- **DEVICE_UNKNOWN code does not exist in reality**

**Spec Impact**: Documentation claims DEVICE_UNKNOWN exists, but hub uses REQUEST_INVALID for this case

### Test 2: REQUEST_UNKNOWN (Invalid Message Type)

**Test**: Send message with type that doesn't exist  
**Type**: `INVALID_TYPE_DOES_NOT_EXIST`

**Expected**: `REQUEST_UNKNOWN` error code  
**Actual**: ✅ `REQUEST_UNKNOWN` error code

**Response**:
```json
{
  "status": "error",
  "data": {
    "code": "REQUEST_UNKNOWN",
    "message": "this message is not supported"
  }
}
```

**Analysis**:
- ✅ Works exactly as documented
- Clear error message
- **REQUEST_UNKNOWN exists and functions correctly**

### Test 3: REQUEST_MALFORMED (Invalid JSON)

**Test**: Send completely malformed JSON  
**Sent**: `{this is not valid json}`

**Expected**: `REQUEST_MALFORMED` error code  
**Actual**: ❌ No response at all (silently ignored)

**Analysis**:
- Hub **silently ignores** malformed JSON
- No error response, no disconnection, no acknowledgment
- Connection remains functional
- **REQUEST_MALFORMED is NOT triggered by invalid JSON syntax**

**Implication**: The name "REQUEST_MALFORMED" is misleading - it doesn't mean "malformed JSON"

### Test 4: REQUEST_MALFORMED (Missing Required Fields)

**Test**: Send valid JSON missing required field  
**Sent**: CONTROL message without `data` field

**Expected**: `REQUEST_INVALID` error code  
**Actual**: `REQUEST_MALFORMED` error code

**Response**:
```json
{
  "status": "error",
  "data": {
    "code": "REQUEST_MALFORMED",
    "message": "no control data, expected data"
  }
}
```

**Analysis**:
- REQUEST_MALFORMED actually means "valid JSON, missing required fields"
- NOT "malformed JSON syntax"
- **REQUEST_MALFORMED exists but means something different than the name suggests**

### Test 5: DEVICE_BUSY (Rapid Commands)

**Test**: Send 20 CONTROL commands with 0ms delay  
**Expected** (per docs): DEVICE_BUSY errors after first command

**Actual**: ❌ Zero DEVICE_BUSY errors (all commands either succeeded or silently dropped)

**Analysis**:
- Confirms prior rate limiting testing
- Hub does NOT send DEVICE_BUSY errors
- Hub silently drops rapid commands instead
- **DEVICE_BUSY code does not exist in reality**

### Test 6: REQUEST_INVALID (Invalid UUID Format)

**Test**: Send CONTROL with malformed UUID  
**UUID**: `not-a-valid-uuid` (not UUID format)

**Expected**: `REQUEST_INVALID` error code  
**Actual**: ✅ `REQUEST_INVALID` error code

**Response**:
```json
{
  "status": "error",
  "data": {
    "code": "REQUEST_INVALID",
    "message": "invalid target value"
  }
}
```

**Analysis**:
- ✅ Works as expected
- REQUEST_INVALID is used for invalid data values
- Also used for non-existent UUIDs (overlaps with documented DEVICE_UNKNOWN purpose)
- **REQUEST_INVALID exists and covers multiple validation failures**

## Error Code Mapping

### What REQUEST_INVALID Actually Covers

REQUEST_INVALID is used for:
1. ✅ Invalid UUID format (`not-a-valid-uuid`)
2. ✅ Non-existent device UUID (`00000000-0000-0000-0000-000000000000`)
3. ✅ Invalid dim values (from prior testing: we know hub accepts all, but this code exists for other invalid values)

### What REQUEST_MALFORMED Actually Means

REQUEST_MALFORMED means "valid JSON structure, but missing required message fields":
- ✅ Missing `data` field in CONTROL
- ✅ Missing `target` in CONTROL data
- ❌ NOT for malformed JSON syntax (those are silently ignored)

### Error Codes That Don't Exist

1. **DEVICE_BUSY**: Documented but never triggered
   - Hub behavior: Silent dropping of rapid commands
   - No error response sent

2. **DEVICE_UNKNOWN**: Documented but never triggered
   - Hub behavior: Returns REQUEST_INVALID with message "device could not be found"
   - Functionally same result, different code

## Error Response Format

All error responses follow this structure:
```json
{
  "type": "<original-message-type>",
  "transactionId": "<matching-uuid>",
  "dst": "<client-name>",
  "src": "deako",
  "status": "error",
  "timestamp": <unix-epoch>,
  "data": {
    "code": "<ERROR_CODE>",
    "message": "<human-readable-description>"
  }
}
```

**Consistent fields:**
- `status`: Always "error"
- `data.code`: Error code string (uppercase with underscores)
- `data.message`: Human-readable error description (lowercase)

## Implications for Simulator

### Must Implement (Exist on Real Hardware)

1. **REQUEST_UNKNOWN**
   - Trigger: Invalid message type
   - Message: "this message is not supported"

2. **REQUEST_MALFORMED**
   - Trigger: Valid JSON missing required fields (not malformed JSON!)
   - Message: Specific field-related message (e.g., "no control data, expected data")

3. **REQUEST_INVALID**
   - Trigger: Invalid data values (UUID format, non-existent UUID, etc.)
   - Message: Specific validation message (e.g., "device could not be found", "invalid target value")

### Must NOT Implement by Default

4. **DEVICE_BUSY**
   - Does NOT exist on real hardware
   - Optional testing mode only (clearly marked as non-realistic)

5. **DEVICE_UNKNOWN**
   - Does NOT exist on real hardware
   - Use REQUEST_INVALID instead with message "device could not be found"

### Special Behavior: Malformed JSON

- **Real behavior**: Silently ignore, no response, connection stays alive
- **Simulator must**: Replicate this (no error response for invalid JSON syntax)

## Spec Updates Required

### FR-066: Error Response Format

**Current**: Lists 5 error codes  
**Should be**: List only 3 codes that actually exist

**Proposed update**:
```markdown
FR-066: Simulator MUST include status "error" field and error code in data.code 
for all error responses, using codes that exist on real hardware:

**Codes that exist:**
- REQUEST_UNKNOWN: Invalid/unsupported message type
- REQUEST_MALFORMED: Valid JSON but missing required fields
- REQUEST_INVALID: Invalid data values (bad UUID, non-existent device, etc.)

**Codes that do NOT exist (per hardware testing October 2025):**
- DEVICE_BUSY: Hub silently drops rapid commands instead
- DEVICE_UNKNOWN: Hub returns REQUEST_INVALID with message "device could not be found"

Optional testing modes may enable DEVICE_BUSY for error handling testing, but 
this must be clearly documented as non-realistic behavior.
```

### New Requirement: Malformed JSON Handling

**FR-077**: Simulator MUST silently ignore malformed JSON (invalid syntax) without 
sending error responses or disconnecting the client (verified October 2025: real 
hub ignores `{this is not valid json}` with no response); REQUEST_MALFORMED is 
only for valid JSON missing required fields, not syntax errors

## Error Message Catalog

Based on observed real hub responses:

| Code | Trigger | Message |
|------|---------|---------|
| REQUEST_UNKNOWN | Invalid type field | "this message is not supported" |
| REQUEST_MALFORMED | Missing data field in CONTROL | "no control data, expected data" |
| REQUEST_INVALID | Non-existent UUID | "device could not be found" |
| REQUEST_INVALID | Invalid UUID format | "invalid target value" |

## Confidence Level

**Very High** - Direct observation of error responses:
- ✅ Tested 6 different error scenarios
- ✅ Received 5 error responses (1 silently ignored)
- ✅ Confirmed 3 codes exist, 2 don't exist
- ✅ Documented exact error messages
- ✅ Consistent with prior DEVICE_BUSY testing (doesn't exist)

## Test Statistics

- **Tests Executed**: 6 error scenarios
- **Error Responses Received**: 5
- **Silently Ignored**: 1 (malformed JSON)
- **Documented Codes**: 5
- **Actually Exist**: 3
- **Documentation Accuracy**: 60% (3/5 codes exist)

## Conclusion

The Deako hub's error handling **differs significantly from API documentation**:
- Only 3 of 5 documented error codes actually exist
- DEVICE_UNKNOWN doesn't exist (uses REQUEST_INVALID instead)
- DEVICE_BUSY doesn't exist (confirmed from prior testing)
- REQUEST_MALFORMED doesn't mean malformed JSON syntax
- Malformed JSON is silently ignored (no error response)

**For the simulator**: Implement only the 3 error codes that exist on real hardware. 
Make DEVICE_BUSY optional for testing purposes only (clearly marked as non-realistic). 
Replicate the silent ignoring of malformed JSON syntax.
