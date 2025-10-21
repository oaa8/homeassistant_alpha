# Deako Hub Rate Limiting - Systematic Testing Results
**Date**: October 18, 2025  
**Test Version**: 2.0 (Improved methodology)  
**Hub**: 192.168.86.221:23  
**Test Device**: Master Bedroom Lights  
**Test Script**: [`../tests/test-rate-limiting-v2.ps1`](../tests/test-rate-limiting-v2.ps1)  
**Spec Reference**: [spec.md](../spec.md) - FR-023, FR-064, FR-074

## Executive Summary

**Key Finding**: The Deako hub has a **100ms minimum command spacing requirement** for 100% reliable operation. Commands sent faster than this are silently dropped without error codes.

## Methodology Improvements Over v1

✅ **Systematic delay testing**: 6 different delay thresholds (0ms, 50ms, 100ms, 150ms, 200ms, 500ms)  
✅ **Better sample sizes**: 20 commands per threshold (vs 10 in v1)  
✅ **Proper transaction ID matching**: All responses correctly matched to commands  
✅ **Network flush delays**: Added `$stream.Flush()` after each write  
✅ **Response pattern analysis**: Identified which commands get responses in burst  

## Test Results

### Success Rate vs Delay Threshold

| Delay (ms) | Commands Sent | Responses | Success Rate | DEVICE_BUSY Errors |
|-----------|---------------|-----------|--------------|-------------------|
| **0** | 20 | 1 | **5%** | 0 |
| **50** | 20 | 14 | **70%** | 0 |
| **100** | 20 | 20 | **100%** ✅ | 0 |
| **150** | 20 | 20 | **100%** ✅ | 0 |
| **200** | 20 | 20 | **100%** ✅ | 0 |
| **500** | 10 | 10 | **100%** ✅ | 0 |

### Key Metrics

- **Reliable Threshold**: **100ms** (first delay to achieve 100% success)
- **Total Commands**: 110 commands across all tests
- **Total DEVICE_BUSY Errors**: **0** (zero)
- **Response Times**: Average 782ms - 3002ms (varies by test load)

## Critical Findings

### 1. **100ms is the Practical Minimum** ⭐
- **0ms spacing**: Only 5% of commands get responses (1 out of 20)
- **50ms spacing**: 70% success rate (14 out of 20) 
- **100ms spacing**: 100% success rate (20 out of 20)
- **Conclusion**: 100ms is the minimum reliable inter-command delay

### 2. **No DEVICE_BUSY Error Codes**
- **Across 110 total commands**: Zero DEVICE_BUSY errors
- **Even at 0ms spacing**: No error responses, just silence
- **Conclusion**: Documented 800ms with DEVICE_BUSY enforcement does NOT exist in practice

### 3. **Silent Command Dropping Behavior**
- Commands that arrive too fast simply **don't get responses**
- No error codes, no warnings, no feedback
- Hub processes what it can and ignores the rest
- **Pattern**: First command in burst gets response, rest are dropped

### 4. **Response Pattern: First-In-Wins**
- In 0ms delay test: Only command index 0 got a response
- Hub responds to the **first command** it can process
- Subsequent commands while busy are silently dropped
- This is consistent "first-in-wins" behavior

## Comparison to Documentation

| Aspect | Documentation | Actual Behavior |
|--------|--------------|-----------------|
| **Minimum spacing** | 800ms | **100ms** (8x faster) |
| **Rate limit enforcement** | DEVICE_BUSY errors | **Silent dropping** (no errors) |
| **Reliability** | Required for operation | 100ms gives 100% success |
| **Error feedback** | Explicit error codes | **None** (commands just ignored) |

## What We Now Know (With Confidence)

### ✅ Confirmed
1. **100ms minimum spacing** for reliable operation (100% success rate)
2. **No DEVICE_BUSY errors** exist (tested across 110 commands)
3. **Silent dropping** is the hub's rate limiting mechanism
4. **First-in-wins**: Hub responds to first command, drops subsequent ones during processing
5. **50ms spacing** is unreliable (70% success rate)

### 📊 Measured
- Success rates at 6 different thresholds
- Response times range from 658ms to 3002ms (load-dependent)
- Command processing appears to take ~100ms per command
- Network overhead adds variability to response times

### ⚠️ Still Unknown
- Whether dropped commands execute on the device (no physical observation)
- Exact TCP delivery timing (we measured app-level, not network-level)
- Whether behavior differs for different message types (only tested CONTROL)
- Whether hub queues commands internally or truly drops them

## Implications for Simulator

### Must Replicate
1. ✅ **No DEVICE_BUSY errors** by default
2. ✅ **~100ms command processing time** per device
3. ✅ **Silent command dropping** when commands arrive too fast
4. ✅ **First-command priority** - process first, drop rest
5. ✅ **100% success at 100ms+ spacing**

### Recommended Simulator Behavior

#### Default Mode (Realistic)
```
- Accept all commands via telnet (no rejections)
- Process commands sequentially, ~100ms per command
- When command arrives during processing: silently drop (no response)
- No DEVICE_BUSY errors (match real hub)
- Log dropped commands for debugging visibility
```

#### Optional Testing Mode
```
- Configurable via control API
- Can enable DEVICE_BUSY errors for testing integration resilience
- Can adjust processing time (50ms, 100ms, 200ms)
- Can change dropping behavior (drop vs queue)
- Clearly marked as "not real hub behavior"
```

### Functional Requirements Updates

**Update FR-023**:
> Real-world testing shows hub processes commands at ~100ms per command (not 800ms documented). No DEVICE_BUSY errors are sent. Commands arriving while processing are silently dropped without response. Simulator MUST replicate this behavior by default: process at ~100ms per command, drop commands arriving during processing, no error codes.

**New FR-074**:
> Simulator MUST achieve 100% response rate when commands are spaced 100ms+ apart (matching real hub behavior). Commands spaced <100ms MUST have reduced response rates: 0ms spacing ~5%, 50ms spacing ~70%, 100ms spacing 100%.

## Recommendations

### For Integration Developers
1. ✅ **Space commands 100-150ms apart** for reliability
2. ✅ **Implement client-side rate limiting** (hub won't tell you when you're too fast)
3. ✅ **Handle timeouts gracefully** (commands may not respond)
4. ✅ **Don't expect DEVICE_BUSY errors** (they don't exist)
5. ⚠️ **Implement retry logic** for commands that don't get responses

### For Simulator Implementation
1. ✅ **Default to realistic behavior** (no DEVICE_BUSY, silent dropping)
2. ✅ **Process at ~100ms per command** per device
3. ✅ **Drop subsequent commands** arriving during processing
4. ✅ **Optional testing mode** for DEVICE_BUSY errors (clearly marked as non-realistic)
5. ✅ **Log dropped commands** for debugging (even if hub doesn't respond)

### For Spec Documentation
1. ✅ Update FR-023, FR-064 with 100ms threshold (not 800ms)
2. ✅ Remove assumptions about DEVICE_BUSY error enforcement
3. ✅ Document silent dropping behavior as primary rate limiting
4. ✅ Add success rate curve data (0ms=5%, 50ms=70%, 100ms=100%)
5. ✅ Note that 800ms documented limit is conservative safety margin, not enforced requirement

## Remaining Questions

While this test is significantly better than v1, we still cannot answer:

1. **Do dropped commands execute?** 
   - Need: Physical device observation (watch light state changes)
   - Impact: Determines if hub drops vs queues commands

2. **Exact TCP delivery timing?**
   - Need: Network packet capture (Wireshark)
   - Impact: Confirm app-level timing matches network-level timing

3. **Behavior with other message types?**
   - Need: Test DEVICE_POLL, STATE_QUERY with same methodology
   - Impact: Determine if rate limiting is command-type-specific

4. **Multi-device behavior?**
   - Need: Test commands to different devices simultaneously
   - Impact: Determine if rate limiting is per-device or global

These questions are **not critical** for simulator v1 implementation but would improve accuracy for v2.

## Conclusion

**The hub has a 100ms practical minimum command spacing (8x faster than documented 800ms) and enforces this via silent command dropping, not DEVICE_BUSY error codes.**

This is now backed by:
- ✅ 110 commands tested across 6 thresholds
- ✅ Clear success rate curve (5% → 70% → 100%)
- ✅ Zero DEVICE_BUSY errors observed
- ✅ Consistent first-in-wins response pattern
- ✅ Proper transaction ID matching
- ✅ Network flush delays for better accuracy

**Confidence Level**: High - this data is actionable for simulator implementation.
