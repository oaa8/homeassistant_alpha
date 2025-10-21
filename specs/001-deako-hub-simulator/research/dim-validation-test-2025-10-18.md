# Deako Hub Dim Value Validation Testing
**Date**: October 18, 2025  
**Hub**: 192.168.86.221:23  
**Test Device**: Master Bedroom Lights (50361c15-9739-4326-aded-24441cdbc75e)  
**Test Script**: [`../tests/test-dim-edge-cases.ps1`](../tests/test-dim-edge-cases.ps1)  
**Test**: Edge case dim value validation  
**Spec Reference**: [spec.md](../spec.md) - FR-071

## Executive Summary

**Critical Finding**: The Deako hub **accepts ALL dim values without validation** - including negative numbers, values >100, and decimals. The hub returns `status: "ok"` for all values and presumably clamps or truncates them internally.

**FR-071 is INCORRECT** - the spec assumes REQUEST_INVALID errors for out-of-range values, but this doesn't occur in reality.

## Test Results

### All Test Cases Passed (100% OK Status)

| Dim Value | Category | Expected | Actual | Error Code |
|-----------|----------|----------|--------|------------|
| **-1** | Invalid (negative) | ERROR | ✅ OK | None |
| **0** | Edge (minimum?) | OK or ERROR | ✅ OK | None |
| **1** | Valid (control) | OK | ✅ OK | None |
| **50** | Valid (control) | OK | ✅ OK | None |
| **50.5** | Invalid (decimal) | ERROR | ✅ OK | None |
| **100** | Valid (control) | OK | ✅ OK | None |
| **101** | Invalid (>max) | ERROR | ✅ OK | None |
| **255** | Invalid (way >max) | ERROR | ✅ OK | None |
| **1000** | Invalid (extreme) | ERROR | ✅ OK | None |

### Key Statistics

- **Total tests**: 9 dim values
- **Invalid values** (< 0 or > 100): 4
- **Errors received**: **0** (zero)
- **OK responses**: **9** (100%)
- **REQUEST_INVALID codes**: **0** (zero)

## Critical Findings

### 1. **No Dim Value Validation**

The hub accepts **any numeric dim value** without error:
- ✅ Negative values (-1) → OK
- ✅ Zero (0) → OK  
- ✅ Above maximum (101, 255, 1000) → OK
- ✅ Decimal values (50.5) → OK
- ✅ All valid values (1-100) → OK

**Conclusion**: Hub performs **no validation** on dim values in control commands.

### 2. **Silent Value Handling**

Since invalid values return `status: "ok"`, the hub must be:
- **Clamping** values to 0-100 range internally (e.g., 1000 → 100, -1 → 0)
- **Truncating** decimals to integers (e.g., 50.5 → 50)
- Processing them without error

We cannot determine the exact internal behavior without physical observation of the light.

### 3. **Zero is Valid**

- dim=0 returns `status: "ok"`
- This likely represents minimum brightness or off state
- Spec should clarify: is dim=0 equivalent to power=false?

### 4. **Decimals Accepted**

- dim=50.5 returns `status: "ok"`
- JSON allows numbers with decimals
- Hub likely truncates to integer internally

## FR-071 Validation

**Current FR-071**:
> Simulator MUST validate all control command data values and respond with status "error" and data.code "REQUEST_INVALID" for: dim levels outside 0-100 range, non-numeric dim values, invalid boolean values for power state, malformed UUID formats; error response MUST include descriptive message indicating exact validation failure (e.g., "dim value 150 exceeds maximum 100"); NOTE: validation behavior for out-of-range dim levels should be confirmed against real Deako hub hardware to ensure simulator matches actual device response

**Test Results**: ❌ **INCORRECT**

The hub does **NOT**:
- Validate dim ranges (accepts -1, 101, 1000)
- Send REQUEST_INVALID errors
- Send error messages for out-of-range values
- Reject decimal values

## Comparison to Documentation

No official documentation describes dim value validation behavior. The spec's FR-071 was based on assumptions about proper input validation, but the real hub has a "trust the client" model.

## Implications

### For Integration Developers

✅ **Good news**: Invalid dim values won't break the integration  
⚠️ **Concern**: No feedback on invalid inputs (silent clamping)  
📝 **Recommendation**: Implement client-side validation (0-100 range)

### For Simulator

**Must replicate real hub behavior**:
- Accept **all numeric dim values** without validation
- Return `status: "ok"` for all values
- Clamp internally (likely: < 0 → 0, > 100 → 100)
- Truncate decimals to integers
- **Do NOT send REQUEST_INVALID errors** for out-of-range values

### For Spec

**FR-071 needs complete rewrite**:

**OLD (Incorrect)**:
> Simulator MUST validate all control command data values and respond with status "error" and data.code "REQUEST_INVALID" for: dim levels outside 0-100 range...

**NEW (Correct)**:
> Simulator MUST accept all numeric dim values without validation errors, returning status "ok" (matching real hub behavior verified October 2025); simulator SHOULD clamp values internally: negative values to 0, values >100 to 100, and truncate decimals to integers; simulator MUST NOT send REQUEST_INVALID errors for out-of-range dim values; optional strict validation mode (configurable, defaults OFF) can enable REQUEST_INVALID errors for testing integration input validation, but this mode should be clearly marked as non-realistic behavior

## Additional Testing Questions

### Not Yet Tested

1. **Physical behavior**: What brightness does the light show for:
   - dim=-1 (clamped to 0? off?)
   - dim=101 (clamped to 100? max brightness?)
   - dim=1000 (clamped to 100?)

2. **Non-numeric values**: What happens with:
   - dim="fifty" (string)
   - dim=null
   - dim=true (boolean)
   - Missing dim field entirely

3. **Zero semantics**: 
   - Is dim=0 the same as power=false?
   - Can a light be power=true with dim=0?

4. **Decimal precision**:
   - Is 50.9 rounded to 51 or truncated to 50?

## Recommendations

### Immediate Actions

1. ✅ **Update FR-071** to remove validation requirements
2. ✅ **Add new FR** for clamping behavior
3. ✅ **Document** that REQUEST_INVALID errors don't exist for dim values
4. ✅ **Clarify** dim=0 semantics (valid minimum or off state)

### Optional Follow-up Tests

1. Test non-numeric dim values (strings, null, boolean)
2. Monitor physical light during extreme values test
3. Test power=true with dim=0 combination
4. Test decimal rounding vs truncation (50.9, 50.1)

## Confidence Level

**Very High** - Direct testing with 9 different values:
- ✅ All invalid values accepted (4/4)
- ✅ All valid values accepted (5/5)
- ✅ Zero REQUEST_INVALID errors (0/9)
- ✅ All responses had status "ok"
- ✅ Consistent behavior across all test cases

## Conclusion

**The Deako hub performs NO validation on dim values.** It accepts any numeric value and returns `status: "ok"`, presumably clamping or truncating internally. The spec's FR-071 assumption about REQUEST_INVALID errors for out-of-range values is **incorrect** and must be revised to match actual hub behavior.

**Simulator must accept all numeric dim values without errors** to accurately replicate real hub behavior. Optional strict validation mode can be added for testing purposes but should default to OFF.

## Test Data

```json
// All of these received status: "ok"
{"dim": -1}      // Negative
{"dim": 0}       // Zero (edge case)
{"dim": 1}       // Valid minimum
{"dim": 50}      // Valid middle  
{"dim": 50.5}    // Decimal
{"dim": 100}     // Valid maximum
{"dim": 101}     // Above max
{"dim": 255}     // Way above max
{"dim": 1000}    // Extreme value
```

Response times: 77ms - 590ms (varied, no pattern related to value validity)
