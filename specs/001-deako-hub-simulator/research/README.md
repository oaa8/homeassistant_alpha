# Deako Hub Research Documents Index

This directory contains detailed findings from hardware testing and protocol analysis of real Deako hub behavior.

**Test Hub**: 192.168.86.221:23  
**Testing Period**: January 2025 - October 2025

## Research Documents

### Protocol Analysis
- **`protocol-testing-2025-01-15.md`** - Initial protocol exploration
  - Early telnet protocol testing
  - Basic message format validation
  - Initial device discovery testing

### Rate Limiting Investigation
- **`rate-limiting-test-2025-10-17.md`** ❌ SUPERSEDED
  - Status: Flawed methodology (see systematic test)
  - Issue: Measured PowerShell execution speed, not network timing
  - Conclusion: Use systematic test results instead
  
- **`rate-limiting-systematic-test-2025-10-18.md`** ⭐ **DEFINITIVE**
  - Test Script: `../tests/test-rate-limiting-v2.ps1`
  - Status: ✅ Complete and validated
  - **Critical Findings**:
    - **100ms minimum** spacing required for 100% reliability
    - **0ms spacing** = 5% success (95% silently dropped)
    - **50ms spacing** = 70% success (30% silently dropped)
    - **100ms+ spacing** = 100% success
    - **Zero DEVICE_BUSY errors** ever observed
    - Hub uses **silent dropping** (no error messages)
  - Spec Updates: FR-023, FR-064, FR-074
  - Commands Tested: 110 CONTROL commands across 6 delay thresholds

### Connection Management
- **`multi-connection-test-2025-10-18.md`** ⭐ **DEFINITIVE**
  - Test Script: `../tests/test-multi-connection.ps1`
  - Status: ✅ Complete and validated
  - **Critical Findings**:
    - Hub **accepts** multiple TCP connections (no socket rejection)
    - Only **first connection is functional**
    - Subsequent connections are **"zombie connections"**
    - No error messages sent to non-functional connections
    - Model: **"Passive Rejection"** (accept but ignore)
  - Spec Updates: FR-072
  - Use Case Impact: Clients must track which connection is active

### Input Validation
- **`dim-validation-test-2025-10-18.md`** ⭐ **DEFINITIVE**
  - Test Script: `../tests/test-dim-edge-cases.ps1`
  - Status: ✅ Complete and validated
  - **Critical Findings**:
    - **Zero validation** of dim values exists
    - Hub accepts: `-1`, `101`, `255`, `1000`, `50.5`, `99.999`
    - All invalid values return `status: "ok"`
    - No REQUEST_INVALID errors ever generated
    - Negative values clamp to 0%
    - Values >100 clamp to 100%
    - Decimals are accepted (rounding behavior unknown)
  - Spec Updates: Complete rewrite of FR-071
  - **Simulator Implication**: Must replicate permissive behavior

### Device State Management
- **`device-state-test-2025-10-18.md`** ✅ **COMPLETE**
  - Test Script: `../tests/test-device-state.ps1`
  - Status: ✅ Complete with DEVICE_POLL validated
  - **Validated Findings**:
    - Hub accepts `power=true, dim=0` (light on at 0%)
    - Hub accepts `power=false, dim=100` (light off but dim stored)
    - Flexible state model (no rigid validation)
    - All combinations return `status: "ok"`
    - **DEVICE_POLL works** with correct format: `{"target": "uuid"}` at root level
    - **Critical Quirk**: Hub returns `status: "error"` even for successful DEVICE_POLL
    - Must check for populated `data` field, ignore misleading status field
  - **Follow-up Tests**:
    - Whitespace behavior test (completed)
    - Physical button behavior test (completed)

### Whitespace Behavior
- **`whitespace-behavior-test-2025-10-18.md`** ⭐ **DEFINITIVE**
  - Test Script: `../tests/test-whitespace-behavior.ps1`
  - Status: ✅ Complete and validated
  - **Critical Findings**:
    - Hub **does NOT send** whitespace messages (30-second idle test)
    - Hub **silently ignores** all whitespace from clients
    - Empty lines, spaces, tabs, mixed whitespace all ignored
    - Hub survives whitespace flood (100 lines) without disconnect
    - Connection remains fully functional after whitespace
  - Spec Updates: FR-024, FR-026 should be optional/configurable (not default)
  - **Simulator Implication**: Whitespace injection should be optional quirk, not default

### Physical Button Behavior  
- **`physical-button-behavior-test-2025-10-18.md`** ⭐ **DEFINITIVE**
  - Test Script: `../tests/test-physical-button-behavior.ps1`
  - Status: ✅ Complete and validated (manual testing with real button presses)
  - **Critical Findings**:
    - Physical button presses immediately generate EVENT messages
    - Each press generates separate EVENT (toggle behavior)
    - Minimum interval observed: 436ms (natural mechanical/human limit)
    - No artificial debouncing by hub
    - **EVENTs include FULL state** (power + dim), not just changed fields
    - Commands and physical buttons work independently (no conflicts)
  - Spec Updates: NEW FR-075 (full state in EVENTs), NEW FR-076 (button simulation API)
  - **Simulator Implication**: Must broadcast full device state in all EVENTs

### Error Code Validation
- **`error-code-validation-test-2025-10-18.md`** ⭐ **DEFINITIVE**
  - Test Script: `../tests/test-error-codes.ps1`
  - Status: ✅ Complete and validated
  - **Critical Findings**:
    - Only **3 of 5** documented error codes actually exist
    - ✅ **REQUEST_UNKNOWN** exists (invalid message type)
    - ✅ **REQUEST_MALFORMED** exists (invalid JSON syntax)
    - ✅ **REQUEST_INVALID** exists (missing required fields)
    - ❌ **DEVICE_BUSY** does NOT exist (confirmed with 10 rapid commands)
    - ❌ **DEVICE_UNKNOWN** does NOT exist (returns REQUEST_INVALID instead)
    - Malformed JSON is **silently ignored** (no response at all)
  - Spec Updates: FR-066 updated, NEW FR-077 (malformed JSON silent drop)
  - **Simulator Implication**: Only implement 3 real error codes, malformed JSON = silent drop

### Message Format Edge Cases
- **`message-format-edge-cases-test-2025-10-18.md`** ⭐ **DEFINITIVE**
  - Test Script: `../tests/test-message-format-edge-cases.ps1`
  - Status: ✅ Complete and validated
  - **Critical Findings**:
    - ✅ **Extra fields** in messages: Accepted and ignored
    - ✅ **Field order**: Independent (any order works)
    - ❌ **Case sensitivity**: Type field must be uppercase ("PING" not "ping")
    - ✅ **Whitespace in JSON**: Ignored (standard JSON parsing)
    - ✅ **Optional timestamp**: Not required in client messages
    - ✅ **Null values**: Interpreted as "no change" (dim=null keeps brightness)
    - ✅ **Unicode characters**: Supported (tested with emoji)
    - ⚠️ **Very long strings**: May be silently dropped (1000-char src field no response)
  - Spec Updates: NEW FR-078 through FR-083 (6 new requirements)
  - **Simulator Implication**: Permissive JSON parsing, uppercase type enforcement, string length limits

### Client Library Behavior (pydeako)
- **`zero-dim-pydeako-regression-2026-08-12.md`** ⭐ **DEFINITIVE**
  - Harness: `../e2e/zero_dim_experiment.py`, `../e2e/zero_dim_sim_runner.py`,
    `../e2e/wsl_run_zero_dim_experiment.sh`
  - Raw captures: `data/zero-dim-pydeako-0.6.0.json`, `data/zero-dim-pydeako-0.3.1.json`
  - Target: **the simulator**, not real hardware (research ticket
    [deako-house-wayfinder#12](https://github.com/oaa8/deako-house-wayfinder/issues/12))
  - **Critical Findings**:
    - pydeako 0.6.0's `dim or old_dim` **discards an explicit zero dim** from the
      cached state; the wire command and the hub state are correct (display bug)
    - The **inbound EVENT path is poisoned too** — an out-of-band change to 0%
      is discarded as well
    - 0.6.0 **never fires `complete_callback()`**, so the optimistic local echo is
      gone and the EVENT path is the only cache writer
    - A `find_devices()` refresh **repairs** the cache (~120 s in practice)
    - 0.3.1 handles zero correctly but **wipes cached dim to `None`** on a plain
      on/off, which makes the integration's `brightness` property raise `TypeError`
    - Home Assistant 2025.11.0 **never sends brightness 0** to the integration, but
      **brightness 1 becomes a falsy `0.0`** via the integration's own conversion

### Connection Lifecycle
- **`connection-lifecycle-test-2025-10-18.md`** ⭐ **DEFINITIVE**
  - Test Script: `../tests/test-connection-lifecycle.ps1`
  - Status: ✅ Complete and validated
  - **Critical Findings**:
    - ✅ **No idle timeout** (connection survived 5+ minutes idle)
    - ✅ **PING keepalive works** (9 PINGs over 5 minutes)
    - ✅ **Graceful disconnect** (FIN) handled cleanly
    - ✅ **Immediate reconnection** allowed (< 1 second)
    - ✅ **Ungraceful disconnect** (RST) handled robustly
    - ✅ **Incomplete message buffering** (hub buffers then cleans up on disconnect)
    - Hub broadcasts EVENTs to idle connections continuously
  - Spec Updates: NEW FR-084 through FR-087 (4 new connection requirements)
  - **Simulator Implication**: No timeout by default, immediate reconnect support, robust disconnect handling

- **`device-state-testing-2025-10-16.md`** - Earlier state exploration
  - Status: Historical record, see 2025-10-18 version

### Concrete Findings Archive
- **`CONCRETE-FINDINGS-2025-10-16.md`** - Early consolidated findings
  - Status: Historical snapshot
  - Note: Findings have been superseded by systematic testing

## Cross-References

### By Spec Requirement
| Spec FR | Research Document | Status |
|---------|------------------|--------|
| FR-023 | Rate Limiting Systematic | ✅ Validated |
| FR-024 | Whitespace Behavior | ✅ Validated |
| FR-026 | Whitespace Behavior | ✅ Validated |
| FR-064 | Rate Limiting Systematic | ✅ Validated |
| FR-066 | Error Code Validation | ✅ Validated |
| FR-071 | Dim Validation | ✅ Validated |
| FR-072 | Multi-Connection | ✅ Validated |
| FR-074 | Rate Limiting Systematic | ✅ Validated |
| FR-075 | Physical Button Behavior | ✅ Validated |
| FR-076 | Physical Button Behavior | ✅ Validated |
| FR-077 | Error Code Validation | ✅ Validated |
| FR-078 | Message Format Edge Cases | ✅ Validated |
| FR-079 | Message Format Edge Cases | ✅ Validated |
| FR-080 | Message Format Edge Cases | ✅ Validated |
| FR-081 | Message Format Edge Cases | ✅ Validated |
| FR-082 | Message Format Edge Cases | ✅ Validated |
| FR-083 | Message Format Edge Cases | ✅ Validated |
| FR-084 | Connection Lifecycle | ✅ Validated |
| FR-085 | Connection Lifecycle | ✅ Validated |
| FR-086 | Connection Lifecycle | ✅ Validated |
| FR-087 | Connection Lifecycle | ✅ Validated |

### By Test Script
| Test Script | Research Document |
|-------------|------------------|
| `test-rate-limiting-v2.ps1` | `rate-limiting-systematic-test-2025-10-18.md` |
| `test-multi-connection.ps1` | `multi-connection-test-2025-10-18.md` |
| `test-dim-edge-cases.ps1` | `dim-validation-test-2025-10-18.md` |
| `test-device-state.ps1` | `device-state-test-2025-10-18.md` |
| `test-device-poll-systematic.ps1` | `device-state-test-2025-10-18.md` |
| `test-device-poll-final.ps1` | `device-state-test-2025-10-18.md` |
| `test-whitespace-behavior.ps1` | `whitespace-behavior-test-2025-10-18.md` |
| `test-physical-button-behavior.ps1` | `physical-button-behavior-test-2025-10-18.md` |
| `test-error-codes.ps1` | `error-code-validation-test-2025-10-18.md` |
| `test-message-format-edge-cases.ps1` | `message-format-edge-cases-test-2025-10-18.md` |
| `test-connection-lifecycle.ps1` | `connection-lifecycle-test-2025-10-18.md` |

## Key Insights Summary

### Hub Behavior Patterns
1. **Permissive Input Handling**: Hub accepts virtually all inputs without validation
2. **Silent Failure Mode**: No error messages for rate limiting or zombie connections
3. **Simple State Model**: Flexible power/dim combinations allowed
4. **Single Active Connection**: Multi-connection support via passive rejection
5. **No Idle Timeout**: Connections survive 5+ minutes with no messages
6. **Immediate Reconnection**: No cooldown period between connections
7. **Robust Disconnect Handling**: Graceful and ungraceful disconnects both handled cleanly
8. **Full State Broadcasting**: EVENTs always include complete device state

### Documentation vs. Reality
| Documentation Claim | Actual Behavior | Impact |
|-------------------|-----------------|--------|
| 800ms rate limit | 100ms minimum | 8x faster than documented |
| DEVICE_BUSY errors | Silent dropping | No error handling needed |
| Dim value validation | No validation | Simulator must accept all values |
| Single connection enforcement | Passive rejection | Different error handling model |
| 5 error codes | Only 3 exist | Simplified error handling |
| Whitespace heartbeat | Not sent by hub | Optional quirk only |
| Delta-only EVENTs | Full state in EVENTs | More data in broadcasts |

### Simulator Implementation Priorities
1. ✅ **100ms rate limiting** with silent dropping
2. ✅ **Passive rejection** for multiple connections
3. ✅ **No input validation** for dim values (accept all, clamp internally)
4. ✅ **State management** - DEVICE_POLL validated (with status="error" quirk)
5. ✅ **No idle timeout** by default (> 5 minutes tested)
6. ✅ **Immediate reconnection** support
7. ✅ **Robust disconnect handling** (graceful & ungraceful)
8. ✅ **Full state in EVENTs** (not delta updates)
9. ✅ **3 error codes only** (REQUEST_UNKNOWN, REQUEST_MALFORMED, REQUEST_INVALID)
10. ✅ **Permissive JSON parsing** with uppercase type enforcement

## Testing Statistics
- **Total Commands Tested**: 300+
- **Test Sessions**: 9 major tests
- **Spec Corrections**: 17 functional requirements added/corrected
- **Blocker Bugs**: 0 (hub works correctly, docs were wrong)
- **Open Investigations**: 1 remaining (Test #10: Performance limits)

## Current Status: October 18, 2025
- ✅ Rate limiting fully characterized (Test #1)
- ✅ Connection management fully characterized (Test #2)
- ✅ Input validation fully characterized (Test #3)
- ✅ State management fully characterized (Test #4)
- ✅ Whitespace behavior fully characterized (Test #5)
- ✅ Physical button behavior fully characterized (Test #6)
- ✅ Error code validation fully characterized (Test #7)
- ✅ Message format edge cases fully characterized (Test #8)
- ✅ Connection lifecycle fully characterized (Test #9)
- 🔄 Performance limits testing pending (Test #10)
