# Deako Hub Simulator - Documentation Index

**Spec Location**: `specs/001-deako-hub-simulator/`  
**Last Updated**: October 18, 2025

## Quick Navigation

| Document | Purpose | Status |
|----------|---------|--------|
| [spec.md](./spec.md) | Main specification document | ✅ Active, validated |
| [tests/README.md](./tests/README.md) | Test scripts index | ✅ Complete |
| [research/README.md](./research/README.md) | Research findings index | ✅ Complete |
| [checklists/requirements.md](./checklists/requirements.md) | Implementation checklist | ⏳ Pending |

## Overview

This specification defines a Deako hub and device simulator for testing the Home Assistant integration against simulated hardware. All functional requirements have been **validated against real hardware** (hub at 192.168.86.221:23) through systematic testing.

## Testing Summary

**Total Test Sessions**: 7  
**Commands Tested**: 127+  
**Spec Corrections**: 5 functional requirements updated  
**Critical Bugs Found**: 0 (hub works, documentation was wrong)

### Completed Tests

| # | Test Name | Status | Key Finding | Spec Impact |
|---|-----------|--------|-------------|-------------|
| 1 | Rate Limiting | ✅ Complete | 100ms minimum (not 800ms), silent dropping | FR-023, FR-064, FR-074 |
| 2 | Multi-Connection | ✅ Complete | Passive rejection (accepts but ignores) | FR-072 |
| 3 | Dim Validation | ✅ Complete | No validation (accepts all values) | FR-071 |
| 4 | Device State | ✅ Complete | Flexible model + DEVICE_POLL quirk | Multiple FRs |
| 5 | Whitespace | ✅ Complete | Hub doesn't send/respond to whitespace | FR-024, FR-026 optional |
| 6 | Physical Buttons | ✅ Complete | Immediate EVENTs, toggle behavior, full state | FR-075, FR-076 NEW |

## Critical Findings

### 1. Rate Limiting (100ms, not 800ms)
- **Documented**: 800ms spacing, DEVICE_BUSY errors
- **Actual**: 100ms minimum, silent dropping, no errors
- **Test**: `tests/test-rate-limiting-v2.ps1`
- **Research**: `research/rate-limiting-systematic-test-2025-10-18.md`

### 2. Multi-Connection Behavior (Passive Rejection)
- **Documented**: Single connection enforcement with rejection
- **Actual**: Accepts multiple connections, only first is functional
- **Test**: `tests/test-multi-connection.ps1`
- **Research**: `research/multi-connection-test-2025-10-18.md`

### 3. Dim Value Validation (None Exists)
- **Documented**: Validates 0-100 range, returns REQUEST_INVALID
- **Actual**: Accepts all values (-1, 1000, decimals), always returns "ok"
- **Test**: `tests/test-dim-edge-cases.ps1`
- **Research**: `research/dim-validation-test-2025-10-18.md`

### 4. DEVICE_POLL Status Quirk (Returns "error" on Success)
- **Documented**: Returns status="ok" on success
- **Actual**: Returns status="error" even when successful (hub firmware bug)
- **Test**: `tests/test-device-poll-systematic.ps1`
- **Research**: `research/device-state-test-2025-10-18.md`

## Hub Behavior Patterns

### Permissive Design
The hub accepts virtually all inputs without validation:
- ✅ Invalid dim values (-1, 1000, 50.5)
- ✅ All power/dim combinations (power=true + dim=0)
- ✅ Multiple TCP connections (zombie connections)
- ✅ Commands faster than documented limit

### Silent Failure Mode
The hub rarely returns errors:
- No DEVICE_BUSY errors (silently drops commands)
- No validation errors (accepts bad inputs)
- No connection rejection (zombie connections)

### Critical Quirks for Simulator

| Quirk | Impact | Must Replicate |
|-------|--------|----------------|
| 100ms rate limit with silent dropping | High | ✅ Yes |
| Passive rejection of 2nd+ connections | Medium | ✅ Yes |
| No dim value validation | High | ✅ Yes |
| DEVICE_POLL returns status="error" | High | ✅ Yes |
| Accepts all power/dim combinations | Medium | ✅ Yes |

## File Organization

```
specs/001-deako-hub-simulator/
├── README.md ← YOU ARE HERE
├── spec.md ← Main specification
├── tests/
│   ├── README.md ← Test scripts index
│   ├── test-rate-limiting-v2.ps1 ⭐ Definitive
│   ├── test-multi-connection.ps1 ⭐ Definitive
│   ├── test-dim-edge-cases.ps1 ⭐ Definitive
│   ├── test-device-poll-systematic.ps1 ⭐ Definitive
│   ├── test-device-poll-final.ps1 ⭐ Validation
│   └── [other test scripts]
├── research/
│   ├── README.md ← Research findings index
│   ├── rate-limiting-systematic-test-2025-10-18.md ⭐
│   ├── multi-connection-test-2025-10-18.md ⭐
│   ├── dim-validation-test-2025-10-18.md ⭐
│   ├── device-state-test-2025-10-18.md ⭐
│   └── [other research docs]
└── checklists/
    └── requirements.md ← Implementation tracking
```

## For Future Context (Memory Wipe Recovery)

If you're reading this after a memory wipe:

1. **Start here**: Read this README to understand the structure
2. **Understand scope**: Read `spec.md` sections 1-3 (overview, clarifications, user stories)
3. **Review findings**: Read the 4 starred research docs in `research/`
4. **Check tests**: Review the 5 starred test scripts in `tests/`
5. **Find details**: Use the README files in tests/ and research/ as indexes

### Key Facts to Remember

- **Hub IP**: 192.168.86.221:23 (hardware test hub)
- **Test Device**: Master Bedroom Lights (UUID: 50361c15-9739-4326-aded-24441cdbc75e)
- **Protocol**: Telnet-based JSON with CRLF line endings
- **Discovery**: mDNS service type "_telnet", service name "local-integration"
- **Message Format**: Single-line JSON, transactionId = UUID v4

### Critical Implementation Requirements

1. **100ms rate limiting** (not 800ms) with silent dropping
2. **Passive rejection** for multiple connections (accept but ignore 2nd+)
3. **No validation** of dim values (accept all, clamp internally)
4. **DEVICE_POLL quirk**: Return status="error" with populated data field
5. **Flexible state model**: Accept all power/dim combinations

## Cross-References

### Spec Requirements → Research Documents
- FR-023 (Rate Limiting) → `research/rate-limiting-systematic-test-2025-10-18.md`
- FR-064 (Error Handling) → `research/rate-limiting-systematic-test-2025-10-18.md`
- FR-071 (Dim Validation) → `research/dim-validation-test-2025-10-18.md`
- FR-072 (Connection Limit) → `research/multi-connection-test-2025-10-18.md`
- FR-074 (Rate Limit Curve) → `research/rate-limiting-systematic-test-2025-10-18.md`

### Research Documents → Test Scripts
- Rate Limiting → `tests/test-rate-limiting-v2.ps1`
- Multi-Connection → `tests/test-multi-connection.ps1`
- Dim Validation → `tests/test-dim-edge-cases.ps1`
- Device State/DEVICE_POLL → `tests/test-device-poll-systematic.ps1`

## Current Status

✅ **Specification Phase**: Complete  
✅ **Hardware Validation**: Complete  
⏳ **Implementation Phase**: Not started  
⏳ **Testing Phase**: Not started

All critical hub behaviors have been characterized and documented. The specification is **ready for implementation** with high confidence in simulator accuracy.

## Next Steps

1. Review this README and the main spec.md
2. Read the 4 definitive research documents
3. Run `/speckit.plan` to generate implementation plan
4. Begin simulator development with validated protocol details

## Notes for AI Agents

- **Always check the README files first** - they index everything
- **Don't guess hub behavior** - reference the research docs
- **Test scripts are in tests/** - properly organized
- **Research docs are in research/** - properly organized
- **All findings are cross-referenced** - use the tables above
- **User confirmed DEVICE_POLL works** - don't conclude it doesn't exist

## Change Log

- **2025-10-18**: Created comprehensive documentation structure
- **2025-10-18**: Organized scattered test files into tests/ directory
- **2025-10-18**: Created README files for tests/ and research/
- **2025-10-18**: Corrected DEVICE_POLL findings (initially wrong, now validated)
- **2025-10-18**: Added cross-reference tables for easy navigation
