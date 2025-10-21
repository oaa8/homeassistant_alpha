# Deako Hub Whitespace Message Behavior Test
**Date**: October 18, 2025  
**Hub**: 192.168.86.221:23  
**Test Script**: [`../tests/test-whitespace-behavior.ps1`](../tests/test-whitespace-behavior.ps1)  
**Purpose**: Validate FR-026 whitespace handling assumptions  
**Spec Reference**: [spec.md](../spec.md) - FR-024, FR-026

## Executive Summary

**Key Finding**: The Deako hub **does NOT send or respond to whitespace messages** under any tested conditions. However, it **gracefully ignores** whitespace input from clients without breaking the connection.

**Spec Impact**: FR-026 whitespace handling appears to be based on defensive coding in the integration rather than observed hub behavior. The simulator may not need to implement whitespace message sending.

## Test Methodology

### Part 1: Hub Sends Whitespace? (30-second idle test)
- **Approach**: Connect and wait 30 seconds without sending any commands
- **Purpose**: Check if hub sends periodic whitespace for keep-alive
- **Result**: ❌ **Zero whitespace messages received**

### Part 2: Hub Responds to Whitespace? (Client-initiated)
Sent three types of whitespace to hub:
1. Empty line (just CRLF)
2. Spaces-only line (`"    "`)
3. Tab-only line (`"\t\t"`)

- **Result**: ❌ **No responses to any whitespace input**

### Part 3: Connection Survives Whitespace?
- Sent whitespace, then sent valid PING command
- **Result**: ✅ **Connection still functional** (PING response received)

### Part 4: Whitespace Flood Test
- Sent 100 empty lines rapidly
- Verified connection with PING
- **Result**: ✅ **Connection survived** (no disconnect, no errors)

## Test Results Summary

| Test | Result | Interpretation |
|------|--------|---------------|
| Hub sends whitespace during idle | ❌ NO | No keep-alive whitespace |
| Hub responds to client whitespace | ❌ NO | Whitespace ignored |
| Hub accepts whitespace gracefully | ✅ YES | No errors, no disconnect |
| Hub survives whitespace flood (100 lines) | ✅ YES | Robust to noise |

## Detailed Findings

### 1. No Whitespace Messages from Hub
- Tested: 30-second idle connection
- Expected (per FR-026): Possible whitespace keep-alive messages
- Actual: Zero messages of any kind
- Conclusion: Hub does NOT use whitespace for keep-alive

### 2. Hub Silently Ignores Client Whitespace
- Tested: Empty lines, spaces, tabs
- Expected (per FR-026): Unknown (defensive handling)
- Actual: No response, no error, no acknowledgment
- Conclusion: Whitespace is silently discarded

### 3. Whitespace Doesn't Break Protocol
- Tested: 100 rapid empty lines followed by PING
- Expected: Either error or connection drop (potential)
- Actual: All whitespace ignored, PING worked normally
- Conclusion: Hub is robust to whitespace noise

## Integration Code Analysis

The Home Assistant integration has whitespace handling code:
```python
# Defensive logic that strips and ignores whitespace
if message.strip() == "":
    continue
```

This appears to be **defensive programming** rather than handling observed hub behavior.

## Comparison with Protocol Testing (Jan 2025)

From `protocol-testing-2025-01-15.md`:
> "NO whitespace-only messages were observed during this test. This suggests:
> - Whitespace behavior may be firmware-version dependent
> - Whitespace messages may only occur under specific conditions"

**Current findings confirm**: Still no whitespace observed. If this is firmware-dependent, it's not present in current hub firmware.

## Implications for Simulator

### Option 1: Don't Implement Whitespace Sending
**Rationale**: Hub doesn't send whitespace, so simulator shouldn't either

**Pros**:
- Matches observed hardware behavior
- Simpler implementation
- No unnecessary network traffic

**Cons**:
- Won't test integration's whitespace handling code
- May miss edge cases if future firmware adds whitespace

### Option 2: Make Whitespace Configurable
**Rationale**: Support testing integration's defensive code

**Pros**:
- Can test integration's whitespace stripping logic
- Configurable for "what if" scenarios
- Future-proof if firmware changes

**Cons**:
- More complex implementation
- Tests behavior that doesn't exist in reality

### Recommendation: **Option 2 (Configurable)**

While hub doesn't send whitespace, the integration has defensive code to handle it. The simulator should support **optional whitespace injection** for testing purposes, but it should be:
- **Disabled by default** (matches real hub)
- **Configurable** via scenario config
- **Documented** as "integration defensive testing" not "hub behavior replication"

## Spec Updates Required

### FR-026: Whitespace Message Handling

**Current assumption**: "Handle whitespace-only messages that may be sent by hub"

**Proposed update**:
```markdown
FR-026: Whitespace Message Handling

**Observed Behavior**: Real Deako hub does NOT send whitespace messages 
and silently ignores whitespace from clients.

**Simulator Behavior**: 
- By default, do NOT send whitespace messages (matches real hub)
- Silently ignore whitespace lines received from clients (matches real hub)
- Optionally support whitespace injection via scenario config for testing 
  integration defensive code (disabled by default)

**Rationale**: Integration contains defensive whitespace handling code, 
but this behavior has not been observed on actual hardware. Supporting 
optional whitespace injection allows testing integration robustness without 
misrepresenting hub behavior.
```

## Confidence Level

**Very High** - Multiple test approaches confirm the same behavior:
- ✅ 30-second idle (no whitespace sent by hub)
- ✅ Client whitespace ignored (no responses)
- ✅ Connection survives whitespace (robust)
- ✅ Flood test passed (100 messages ignored)
- ✅ Consistent with January 2025 findings

## Test Statistics

- **Test Duration**: 30 seconds idle + active testing
- **Whitespace Lines Sent**: 103 (various formats)
- **Whitespace Lines Received**: 0
- **Connection Breaks**: 0
- **Errors**: 0

## Conclusion

The Deako hub **does not send whitespace messages** and **silently ignores whitespace input** from clients. The integration's whitespace handling code is defensive programming rather than handling observed hub behavior.

**For the simulator**: Implement whitespace as an **optional, configurable feature** (disabled by default) to test integration robustness, not to replicate hub behavior.

This finding validates that FR-026 should be updated to reflect:
1. Hub doesn't send whitespace (so simulator shouldn't by default)
2. Hub ignores whitespace gracefully (simulator must replicate this)
3. Optional whitespace injection for testing integration defensive code
