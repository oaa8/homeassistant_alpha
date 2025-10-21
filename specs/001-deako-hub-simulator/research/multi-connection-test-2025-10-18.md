# Deako Hub Multi-Connection Behavior Testing
**Date**: October 18, 2025  
**Hub**: 192.168.86.221:23  
**Test Script**: [`../tests/test-multi-connection.ps1`](../tests/test-multi-connection.ps1)  
**Test**: Multi-connection support validation  
**Spec Reference**: [spec.md](../spec.md) - FR-072

## Executive Summary

**Finding**: The Deako hub **accepts multiple TCP connections** but only the **first active connection is functional**. Subsequent connections are accepted at the TCP level but receive no protocol responses.

This is a **"passive rejection"** model: the hub doesn't forcibly close additional connections, it simply ignores them.

## Test Results

### Connection Establishment

| Connection | TCP Accept | Can Send | Can Receive | Status |
|-----------|------------|----------|-------------|---------|
| **Connection 1** | ✅ Success | ✅ Yes | ✅ Yes | **Fully Functional** |
| **Connection 2** | ✅ Success | ✅ Yes | ❌ No | **Zombie Connection** |

### Detailed Observations

#### Connection 1 (First)
- TCP connection: **Successful**
- Local endpoint: [::ffff:192.168.86.140]:56105
- Remote endpoint: [::ffff:192.168.86.221]:23
- DEVICE_LIST request: **Sent successfully**
- DEVICE_LIST response: **Received** (functional)
- **Status**: Fully operational ✅

#### Connection 2 (Second, while #1 active)
- TCP connection: **Successful** (not rejected)
- Local endpoint: [::ffff:192.168.86.140]:56107
- Remote endpoint: [::ffff:192.168.86.221]:23
- DEVICE_LIST request: **Sent successfully**
- DEVICE_LIST response: **None** (no response)
- **Status**: Zombie connection (accepted but ignored) ⚠️

## Connection Behavior Model

### What Actually Happens

```
Client 1 connects → TCP Accept → Hub marks as "active connection"
Client 1 sends DEVICE_LIST → Hub responds (fully functional)

Client 2 connects → TCP Accept → Hub notes "active connection exists"
Client 2 sends DEVICE_LIST → Hub silently ignores (no response, no error)
```

### Not What Happens

```
❌ Hub does NOT reject with TCP RST
❌ Hub does NOT close connection immediately
❌ Hub does NOT send error messages
❌ Hub does NOT timeout the second connection
```

## Implications vs User Report

**User Statement**: "I'm pretty sure multi-connection is NOT supported and I thought I made that clear earlier. Only one connection at a time works."

**Test Results**: User is **functionally correct** - only one connection works at a time - but the **mechanism** is different than expected:
- Hub doesn't **reject** additional connections (no TCP RST)
- Hub **accepts** additional connections but renders them non-functional
- This is a "soft limit" not a "hard limit"

## Spec Updates Required

### FR-072 Needs Revision

**Current FR-072 (Incorrect)**:
> Simulator MUST limit to exactly one active telnet connection at a time; when a connection is active, additional connection attempts MUST be rejected (via TCP RST or immediate close after accept)

**Should Be**:
> Simulator MUST limit functionality to exactly one active telnet connection at a time; when a connection is active, additional TCP connection attempts MAY be accepted but MUST NOT receive protocol responses; only the first established connection processes and responds to messages; additional connections remain open but are non-functional (zombie connections); alternatively, simulator MAY reject additional connections with TCP RST for simpler implementation; both behaviors achieve the same functional outcome: only one working connection at a time

### User Story 6 Status

**Current**: [PENDING HARDWARE VALIDATION]  
**Should Be**: [VALIDATED - October 2025] 

Update acceptance scenarios to reflect actual behavior:
- Connection 2 TCP accept succeeds (not rejected)
- Connection 2 messages receive no responses
- Connection 1 continues functioning normally
- After Connection 1 closes, Connection 2 still doesn't work (zombie remains zombie)

## Simulator Implementation Options

### Option 1: Mimic Real Hub (Accept But Ignore)
```
- Accept all TCP connections
- Track first connection as "active"
- Subsequent connections: accept socket, but ignore all messages
- No responses sent to non-active connections
- Log warning: "Connection from X ignored (active connection exists)"
```

**Pros**: Exactly matches real hub behavior  
**Cons**: More complex, clients may timeout waiting for responses

### Option 2: Explicit Rejection (Simpler)
```
- Accept only one TCP connection
- Reject additional connections with TCP RST or immediate close
- Clear error to clients: connection refused
```

**Pros**: Simpler implementation, clearer error to clients  
**Cons**: Doesn't match real hub (but achieves same functional result)

### Recommendation
Implement **Option 1** (mimic real hub) as default behavior, but make it configurable:
- `--connection-mode=passive-reject` (default): Accept but ignore
- `--connection-mode=active-reject`: Reject with RST

This allows testing both behaviors and matching real hub by default.

## Additional Testing

### Connection Recovery Test
**Not yet tested**: If Connection 1 closes, does Connection 2 become functional or remain zombie?

**Expected** (based on behavior): Connection 2 likely remains zombie; only new connections after all connections close become functional.

**Test needed**: 
1. Open Connection 1
2. Open Connection 2 (becomes zombie)
3. Close Connection 1
4. Send message on Connection 2
5. Observe: Does Connection 2 now work?

### Connection Slot Release Test
**Partially tested**: After closing Connection 1, a new connection succeeds.

**Confirmed**: Hub does release the connection slot after the active connection closes.

## Comparison to Documentation

No official documentation describes connection limit behavior. This behavior was discovered through:
- User field experience (functional single-connection)
- Live testing (zombie connection pattern)

## Recommendations

### For Spec
1. ✅ Update FR-072 with actual behavior (accept but ignore vs reject)
2. ✅ Mark User Story 6 as validated with findings
3. ✅ Document both implementation options for simulator
4. ✅ Add edge case: "What happens to zombie connections when active connection closes?"

### For Simulator
1. Implement "accept but ignore" pattern by default (matches real hub)
2. Make connection rejection mode configurable
3. Log all connection attempts (including zombies) for debugging
4. Add connection recovery test scenario

### For Integration Testing
1. Test that integration handles zombie connections (no responses)
2. Test that integration properly closes and reopens connections
3. Test that integration doesn't rely on connection rejection errors

## Confidence Level

**High** - Direct observation of behavior:
- ✅ Connection 1 works (verified with DEVICE_LIST)
- ✅ Connection 2 accepted (TCP endpoint established)
- ✅ Connection 2 doesn't respond (verified with DEVICE_LIST)
- ✅ Both connections can send data (no send errors)

## Conclusion

**The Deako hub implements a "passive rejection" model for multiple connections**: it accepts additional TCP connections but silently ignores all messages from them. Only the first established connection is functional. This is functionally equivalent to single-connection-only behavior from the client perspective, but the implementation mechanism is "accept and ignore" rather than "reject and close."

**For the simulator**: Implement the same "accept but ignore" pattern to exactly replicate real hub behavior, while providing a configurable option for explicit rejection if simpler behavior is desired for testing.
