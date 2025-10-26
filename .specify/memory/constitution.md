<!--
  Sync Impact Report - Constitution v1.4.0
  
  Version Change: 1.3.0 → 1.4.0 (Minor - new core principle added)
  
  Changes in v1.4.0:
  - ADDED: Principle VIII "Explicit Error Handling Required (NON-NEGOTIABLE)"
    - Prohibits catch-all exception handlers that swallow errors
    - Requires catching only specific expected exceptions
    - Mandates fail-fast behavior for unexpected errors
    - Requires clear error states instead of silent degradation
    - Requires documentation of expected vs unexpected exceptions
    - Rationale: Maintainability, predictability, debuggability
  - UPDATED: "Error Handling Philosophy" section in Development Standards to reference Principle VIII
  
  Previous Changes (v1.3.0):
  - "Code Documentation Standards" section added with mandatory file headers and WHY-focused comments
  - Principle V "Long-Term Readability" expanded with documentation requirements
  
  Previous Changes (v1.2.1):
  - "Tests Written for Debugging" requirement added to Principle VII
  - Fixed contradiction between Technology Constraints and Principle VII
  - Clarified hardware validation gate exempts trivial protocol elements
  - Strengthened TODO tracking (immediate, no delayed tracking)
  - Made compliance event-triggered instead of vague audits
  
  Core Principles:
  - I. Hardware Fidelity First
  - II. Simplicity Over Cleverness  
  - III. End-User Validation Required (NON-NEGOTIABLE)
  - IV. Test Facility, Not Product
  - V. Long-Term Readability
  - VI. No Orphaned Work (NON-NEGOTIABLE)
  - VII. Comprehensive Testing Required (NON-NEGOTIABLE)
  - VIII. Explicit Error Handling Required (NON-NEGOTIABLE) ← NEW
  
  Templates Requiring Review:
  ⚠ plan-template.md - Consider adding error handling to Constitution Check
  ⚠ spec-template.md - Consider adding error scenarios to requirements
  ⚠ tasks-template.md - Consider adding error handling validation tasks
  
  Follow-up TODOs:
  - Review templates to determine if error handling guidance should be explicit
-->

# Deako Home Assistant Integration Constitution

## Core Principles

### I. Hardware Fidelity First

**The simulator MUST replicate real hardware behavior, not documentation or assumptions.**

- All protocol behaviors MUST be validated against actual Deako hub hardware before implementation
- When documentation conflicts with observed hardware behavior, hardware wins
- Quirks, edge cases, and undocumented behaviors observed in real devices MUST be replicated
- Implementation decisions based on assumptions MUST be marked "PENDING HARDWARE VALIDATION" with explicit validation tests defined
- Research findings from hardware testing MUST be documented in `specs/[feature]/research/` with test scripts and raw data

**Rationale**: The simulator's sole purpose is enabling integration development without physical hardware. A simulator that doesn't match real hardware behavior is worse than useless—it creates false confidence and wastes debugging time when the integration fails against real devices.

---

### II. Simplicity Over Cleverness

**Choose the simplest solution that solves the problem. Avoid complexity until pain proves it necessary.**

- Direct, obvious implementations MUST be preferred over abstract, "flexible" architectures
- No design patterns, abstraction layers, or frameworks unless the complexity they prevent exceeds the complexity they introduce
- No "future-proofing" or "what if" engineering—solve today's problems today
- Code structure follows obvious file/function organization, not theoretical architecture diagrams
- Dependencies MUST be minimized—only add external libraries when building equivalent functionality would take significantly more time
- Configuration options MUST solve actual use cases, not theoretical scenarios

**Rationale**: This is a test facility, not a product. It will be maintained sporadically over years by people who've forgotten the context. Simple code with obvious structure is the only code that survives long-term maintenance. Over-engineering kills projects through maintenance burden and cognitive load.

---

### III. End-User Validation Required (NON-NEGOTIABLE)

**No code is complete until its end-user outcome is validated. "End user" means the integration developer testing against the simulator.**

- For simulator features: Must demonstrate the integration discovers/connects/controls as expected
- For protocol implementations: Must show actual integration code paths execute correctly
- For control APIs: Must demonstrate scenario activation produces intended testing conditions
- "Code written" ≠ "task done"—the task is done when the intended outcome is verified
- If validation isn't possible, this MUST be explicitly called out rather than claiming success
- Validation steps MUST be documented in task completion (what was tested, how, what was observed)

**Rationale**: The objective is never "characters in a file" or "function implemented"—it's "integration developer can test their code without hardware." Without end-user validation, we're optimizing for the wrong metric and shipping theater instead of utility.

---

### IV. Test Facility, Not Product

**The simulator exists to enable integration development. Design decisions MUST optimize for this purpose.**

- Simulator reliability > Simulator features—a working basic simulator beats a broken advanced one
- Development velocity for integration testing > Simulator code elegance
- Clear error messages when things go wrong > Graceful degradation  
- Observable behavior (logs, state inspection) > Hidden internal correctness
- Reproducible test scenarios > Dynamic runtime flexibility
- The integration is the customer; the simulator is infrastructure

**Rationale**: Remembering the purpose prevents scope creep and over-engineering. The simulator doesn't need to be "production ready" or handle edge cases beyond what integration testing requires. It needs to be reliable, debuggable, and enable rapid integration development iteration.

---

### V. Long-Term Readability

**Code must be understandable years later when all context is forgotten.**

- Functions do one thing with obvious names describing exactly what they do
- Comments explain WHY (rationale, quirks, hardware validation context), not WHAT (code explains what)
  - Document assumptions, motives, intent, expectations, and constraints WHILE writing
  - Explain WHY code is written a particular way to maximize maintainability
  - See "Code Documentation Standards" in Development Standards for detailed requirements
- Magic numbers MUST be named constants with comments explaining their source (e.g., "100ms minimum validated via hardware test 2025-10-18")
- Protocol quirks MUST have comments referencing the research document that discovered them
- Variable names are complete words, not abbreviations (device_uuid not dev_id)
- File organization follows obvious structure: models/, services/, api/ not clever architectural abstractions
- No "clever" code—explicit and verbose beats terse and implicit
- Every source file MUST have a header comment with creation date and author

**Rationale**: Future maintainers (including future you) will approach this cold, with context forgotten. They need to understand what the code does, why it does it that way, and what real-world behavior it's replicating. Readability is the only feature that compounds over time.

---

### VI. No Orphaned Work (NON-NEGOTIABLE)

**Every TODO, placeholder, stub, or incomplete work item MUST have a tracking task. Nothing gets forgotten.**

- **Every TODO/FIXME/HACK/PLACEHOLDER in code MUST have**:
  - A corresponding task in `specs/[feature]/tasks.md` with the exact location (file path, line number or function name)
  - A clear description of what needs to be done to remove the TODO
  - Acceptance criteria for completion
- **All artifacts MUST be organized by purpose and discoverability**:
  - **Durable artifacts** (needed long-term): Placed in proper structure and referenced from core files (`tasks.md`, `spec.md`, `plan.md`, `research.md`) so they're discoverable during `/speckit` command usage
  - **Temporary/one-off artifacts**: Placed in `specs/[feature]/temp/` or `specs/[feature]/to-delete/` with clear naming indicating they're disposable
  - **Test scripts**: Placed in `specs/[feature]/tests/` with descriptive names
  - **Research findings**: Placed in `specs/[feature]/research/` and referenced in spec.md or functional requirements
- **Random files scattered across the repo are FORBIDDEN**:
  - Every file MUST have a clear purpose and location
  - If you create a file, you MUST either integrate it into the proper structure OR mark it for deletion
  - No orphaned markdown files, scripts, or artifacts that future you won't find
- **Memory aids MUST be external and structured**:
  - You are inherently forgetful—compensate with systems, not willpower
  - Important context goes in: `tasks.md` (next actions), `spec.md` (requirements), `research.md` (discoveries), code comments (implementation rationale)
  - Break large content into digestible, well-named files with clear navigation
  - Each file MUST be discoverable from the "entry point" files read by `/speckit` commands

**Rationale**: You will forget. Systems prevent forgetting. Orphaned TODOs and scattered files create technical debt that compounds. Every TODO without a tracking task is a future bug. Every random file is future confusion. Disciplined organization and tracking is the only defense against inherent forgetfulness.

---

### VII. Comprehensive Testing Required (NON-NEGOTIABLE)

**Tests MUST achieve 95%+ coverage validating functionality across all layers, not just executing lines.**

- **Coverage Target**: 95%+ of lines MUST be validated against end-user requirements, not just executed
  - Each line's purpose for end users MUST be tested in every scenario where that line executes
  - All branches, conditions, and code paths MUST be tested with realistic scenarios
  - Coverage below 80% indicates architectural problems requiring redesign
- **Multi-Layer Validation (Component Interaction Testing)**: Tests MUST validate how components work together, not just isolated units
  - **Protocol + Logic**: Message parsing triggers correct state changes
  - **Component Interactions**: Commands affect state AND subsequent queries reflect those changes
  - **End-to-End Flows**: Full request/response cycles work as expected
  - **Contract Compatibility**: External integrations receive expected formats
  - **The goal**: Catch integration bugs where individual components work in isolation but fail when connected
  - **Example**: Testing dim command requires valid JSON accepted AND device state changes, dim command affects state AND subsequent polls reflect the change, Home Assistant sends command AND receives expected response format (not sufficient: testing JSON parser alone without state effects)
- **Deterministic Design**: Tests MUST be reliable and reproducible
  - **No flaky tests**: Tests pass reliably or are removed/fixed immediately
  - **No sleep/wait patterns**: Use event-driven synchronization, dependency injection, or deterministic time control
  - **Reproducible failures**: Same input always produces same output
  - **Injectable dependencies**: External systems (time, random, network) can be controlled in tests
  - **Isolated test state**: No test depends on execution order or previous test state
  - Code that cannot be tested deterministically MUST be redesigned
  - **Focus on design, not run counts**: The goal is tests that are inherently reliable by design, not tests that need to be run repeatedly to prove stability
- **Architecture for Testability**: Code architecture MUST enable high test coverage
  - Dependencies MUST be injectable to enable isolation and mocking
  - Side effects MUST be contained and testable (I/O, network, time, random)
  - Complex functions MUST be decomposed into testable units
  - If code cannot reach 95% coverage with legitimate tests, refactor it until it can
- **Legitimate Tests Only**: No fake tests just to hit coverage numbers
  - Each test MUST validate actual functionality against requirements
  - Tests MUST fail when behavior is broken, pass when behavior is correct
  - Assertions MUST verify observable outcomes, not implementation details
  - Tests MUST represent real usage scenarios from end-user perspective
- **Tests Written for Debugging**: Tests MUST empower whoever hits a failure to understand and fix it quickly
  - **Document the "why"**: Each test MUST include a docstring/comment explaining:
    - What end-user scenario this validates (trace back to requirements/user story)
    - Why this expectation exists (the rationale, not just "it should work")
    - What assumptions are being made (about state, environment, timing, etc.)
  - **Make failures informative**: Assertion messages MUST state expected vs actual AND what it means for the end user
    - ❌ Bad: `assert dim_value == 50`
    - ✅ Good: `assert dim_value == 50, f"Dim command should update device state to 50% but got {dim_value}% - integration won't see state change"`
  - **Enable informed refactoring**: Someone refactoring should be able to:
    - Understand what end-user scenario would break if test fails
    - Evaluate whether the original expectation is still valid for current requirements
    - Update test appropriately if requirements legitimately changed
    - Know what to check/validate if they need to modify the behavior
  - **Link to requirements**: Tests MUST reference the spec/requirement they validate (in docstring or test name)
    - Example: `test_dim_command_updates_state_FR023()` or `# Validates FR-023: Dim commands update device state`
- **Coverage Exceptions Require Justification**:
  - Any code below 95% coverage MUST have documented rationale
  - Below 80% coverage REQUIRES architectural redesign—percentage too low
  - Exceptions logged in `specs/[feature]/test-coverage-exceptions.md` with:
    - Exact code location and current coverage percentage
    - Technical reason why higher coverage isn't achievable
    - Alternative validation strategy employed
    - Date of decision and reviewer approval

**Rationale**: The simulator's correctness is non-negotiable—incorrect behavior destroys trust and wastes integration developer time. Comprehensive, deterministic tests are the only way to prove correctness and prevent regressions. Low coverage or flaky tests indicate architectural problems that must be fixed, not accepted. Testing is not optional; it's how we know the simulator works.

---

### VIII. Explicit Error Handling Required (NON-NEGOTIABLE)

**The system MUST fail predictably. Catch-all exception handlers that swallow errors are prohibited.**

- **Catch specific expected exceptions only**: Each try/except block MUST catch only the specific exception types that are expected and recoverable in that context
- **Document expected exceptions**: Every try/except block MUST have a comment explaining:
  - What specific error condition is expected (e.g., "Network timeout during device discovery")
  - Why it's expected and recoverable (e.g., "Device may be powered off, retry later")
  - What recovery action is taken (e.g., "Log warning, continue with other devices")
- **No bare except or Exception handlers**: Patterns like `except:` or `except Exception:` are FORBIDDEN unless:
  - Immediately followed by re-raising with additional context
  - Used at application boundary (e.g., top-level error handler) with explicit logging and graceful shutdown
  - Explicitly justified in code comment with specific rationale
- **Fail fast for unexpected errors**: When an exception is not expected and recoverable, let it propagate—do not catch and ignore
  - Unexpected errors indicate bugs or invalid assumptions that MUST be fixed, not hidden
  - Silent failures make debugging exponentially harder and create data corruption risks
  - The system crashing with a clear stack trace is better than continuing in undefined state
- **Clear error states over degradation**: When an error prevents normal operation:
  - System MUST enter a clear, observable error state (e.g., connection state = "failed", device status = "unavailable")
  - Error state MUST be logged with full context (what failed, why it matters, how to fix)
  - User-facing operations MUST return explicit error responses, not partial success or silent failures
  - No "best effort" fallbacks that hide that something went wrong
- **Test error paths explicitly**: Every exception handler MUST have a corresponding test that:
  - Triggers the specific error condition
  - Validates the recovery behavior or error state
  - Confirms error is logged with sufficient context for debugging
  - See Principle VII for test coverage requirements
- **Rationale in code**: When catching broad exception types is unavoidable:
  - Comment MUST explain why specific exception catching isn't possible
  - Comment MUST list the specific error scenarios being handled
  - Consider whether this indicates an architectural problem requiring redesign

**Examples**:

```python
# ❌ FORBIDDEN: Swallows all errors silently
try:
    result = risky_operation()
except:
    pass  # Violates principle - what errors? why ignore them?

# ❌ FORBIDDEN: Catches everything without context
try:
    result = risky_operation()
except Exception as e:
    logger.error(f"Error: {e}")  # Loses stack trace, no recovery, continues anyway
    result = None

# ✅ GOOD: Catches specific expected error with documented recovery
try:
    device_state = await hub.query_device(uuid)
except DeviceNotFoundError:
    # EXPECTED: Device may be powered off or disconnected during discovery
    # RECOVERY: Mark device as unavailable and retry in next poll cycle
    logger.warning(f"Device {uuid} not responding, marking unavailable")
    device_state = DeviceState(uuid=uuid, status="unavailable")
except NetworkTimeoutError:
    # EXPECTED: Network interruption during query (hub may be restarting)
    # RECOVERY: Re-raise to trigger connection recovery at higher level
    logger.error(f"Network timeout querying device {uuid}, connection lost")
    raise ConnectionLostError(f"Hub connection timeout during device query") from None

# ✅ ACCEPTABLE: Catch-all at application boundary with explicit handling
def main():
    try:
        run_simulator()
    except KeyboardInterrupt:
        logger.info("Shutdown requested by user")
        cleanup_resources()
    except Exception as e:
        # APPLICATION BOUNDARY: Last-resort handler for unexpected errors
        # Logs full context and performs graceful shutdown
        logger.critical(f"Unexpected error: {e}", exc_info=True)
        cleanup_resources()
        sys.exit(1)  # Explicit failure, not silent continue
```

**Rationale**: Silent failures and swallowed exceptions are the root cause of the hardest-to-debug problems. When errors are caught and ignored, the system continues in an undefined state where assumptions are violated and subsequent behavior is unpredictable. This creates cascading failures, data corruption, and debugging sessions that waste hours chasing symptoms instead of root causes. Explicit error handling makes the system maintainable and predictable. A crash with a clear stack trace is a gift—it tells you exactly what broke and where. Catching that crash and continuing with corrupted state is technical debt that compounds exponentially.

---

## Technology Constraints

**These constraints prevent technology proliferation and ensure long-term maintainability:**

- **Language**: Python 3.13+ (matches Home Assistant development requirements)
- **Concurrency**: Python asyncio only (no threads, no multiprocessing—keep it simple)
- **HTTP Framework**: aiohttp (lightweight, async-native, sufficient for control API needs)
- **Configuration**: JSON only (no YAML, no TOML—one format, universally supported)
- **Distribution**: pip-installable package with pyproject.toml (standard Python packaging)
- **Logging**: Python standard library logging module (no third-party logging frameworks)
- **Testing Philosophy**: End goal is validating integration behavior, but achieving this requires comprehensive testing of simulator internals with 95%+ coverage (see Principle VII)

**New dependencies require explicit justification**: What problem does this solve? Why can't standard library or existing dependencies handle it? What's the maintenance cost?

---

## Development Standards

### Hardware Validation Gate

Before implementing protocol behavior that affects device interaction or state management:

1. Behavior MUST be validated against real Deako hub hardware OR
2. Marked "PENDING HARDWARE VALIDATION" with explicit validation test script defined
3. Research findings documented in `specs/[feature]/research/[test-name]-YYYY-MM-DD.md`
4. Test scripts placed in `specs/[feature]/tests/test-[name].ps1`

**Note**: Trivial protocol elements (basic HTTP status codes, standard JSON structure) don't require hardware validation unless they affect device behavior.

### Completion Definition

A task is complete when:

1. Code written and committed
2. End-user outcome validated (integration works as expected)
3. Validation steps documented in commit message or task notes
4. Any quirks/edge cases commented in code with research document references

### Configuration Management

- CLI arguments > Environment variables > Config file > Built-in defaults (precedence chain)
- All configuration options MUST have sensible defaults enabling zero-config startup
- Configuration validation MUST fail fast with explicit error messages
- Effective configuration MUST be logged on startup showing source of each value

### Error Handling Philosophy

**See Principle VIII "Explicit Error Handling Required" for core requirements.**

Additional implementation guidance:

- Fail fast with clear error messages over silent degradation
- Log enough context to diagnose issues without reproducing them
- Every error message MUST include: what failed, why it matters, how to fix it
- User errors (bad config, invalid commands) ≠ bugs—guide users, don't crash
- Distinguish expected recoverable errors from unexpected bugs (see Principle VIII examples)

### Code Documentation Standards

**All code MUST document the WHY, not the WHAT. The code itself explains what it does; comments explain why it exists and why it's written that way.**

#### File Header Requirements

Every source file MUST begin with a header comment containing:

```python
"""
Module: [brief description of module purpose]
Author: GitHub Copilot
Created: YYYY-MM-DD
Last Modified: YYYY-MM-DD

Purpose:
[2-3 sentences explaining what problem this module solves and why it exists]

Key Assumptions:
- [Assumption 1 about environment, hardware, protocol, etc.]
- [Assumption 2]

Related Research:
- [Link to relevant research docs if applicable]
"""
```

**Example**:
```python
"""
Module: Device state management for Deako hub simulator
Author: GitHub Copilot
Created: 2025-10-25
Last Modified: 2025-10-25

Purpose:
Maintains in-memory device state that matches real Deako hub behavior.
Handles state transitions, validation, and persistence for integration testing.

Key Assumptions:
- Device state persists only in memory (no disk writes required for test facility)
- State changes are synchronous (matches observed hardware behavior)
- UUID format is validated but not cryptographically verified

Related Research:
- specs/001-deako-hub-simulator/research/device-state-test-2025-10-18.md
"""
```

#### Inline Comment Requirements

Comments MUST document:

1. **Assumptions**: What preconditions, environmental factors, or protocol behaviors are assumed
   ```python
   # ASSUMPTION: Hub accepts dim values 0-100 even though spec says 1-99
   # Validated 2025-10-18 via hardware test - see research/dim-validation-test-2025-10-18.md
   if not 0 <= dim_value <= 100:
       raise ValueError(f"Dim value {dim_value} outside valid range 0-100")
   ```

2. **Motives/Intent**: Why this approach was chosen over alternatives
   ```python
   # Using dict instead of dataclass because we need dynamic attribute access
   # for generic message handling (hardware sends varying field sets)
   device_state = {}
   ```

3. **Expectations**: What behavior is expected and why
   ```python
   # EXPECT: Connection closes after 60s idle (hardware behavior)
   # Integration must implement keepalive or reconnect logic
   IDLE_TIMEOUT = 60
   ```

4. **Constraints**: Limitations, edge cases, or boundaries
   ```python
   # CONSTRAINT: Maximum 100 concurrent connections (hardware limit)
   # Exceeding this will cause oldest connection to be dropped
   MAX_CONNECTIONS = 100
   ```

5. **Hardware Quirks**: Behavior that matches real devices but seems odd
   ```python
   # QUIRK: Hub returns success but ignores dim commands to devices in "off" state
   # This is validated hardware behavior, not a bug - see research/physical-button-behavior-test-2025-10-18.md
   if device_state["power"] == "off":
       return {"status": "success"}  # Accepted but ignored
   ```

6. **Rationale for Complexity**: When violating "Simplicity Over Cleverness"
   ```python
   # RATIONALE: Using connection pool instead of simple socket because:
   # - Hardware exhibits rate limiting that requires connection reuse (validated 2025-10-17)
   # - Creating new connections for each request triggers backoff (50+ req/sec)
   # - Simpler approach (new connection per request) doesn't match hardware behavior
   # See: specs/001-deako-hub-simulator/research/rate-limiting-systematic-test-2025-10-18.md
   ```

#### What NOT to Comment

- ❌ **Obvious code**: `i += 1  # Increment i` (code is self-explanatory)
- ❌ **Restating code**: `get_device()  # Gets the device` (adds no information)
- ❌ **TODO without tracking**: Use proper TODO(T###) format with task reference
- ❌ **Outdated comments**: Update or delete when code changes

#### Function/Method Documentation

Every non-trivial function MUST have a docstring explaining:
- **Purpose**: What problem it solves (not what it does line-by-line)
- **Parameters**: WHY each parameter exists, any constraints/assumptions
- **Returns**: What it returns and WHY that format/structure
- **Raises**: Expected exceptions and WHEN they occur (the triggering condition)

```python
def validate_dim_command(device_uuid: str, dim_value: int) -> bool:
    """
    Validates dim command matches real Deako hub behavior.
    
    Purpose:
    Hardware accepts dim values 0-100 (not 1-99 per spec) and silently
    clamps out-of-range values. This validator replicates that behavior
    so integration developers see the same responses during testing.
    
    Parameters:
    - device_uuid: Device identifier. MUST be valid UUID format because
      hardware rejects malformed UUIDs with specific error code.
    - dim_value: Target brightness 0-100. Hardware accepts this range
      despite spec claiming 1-99 (validated 2025-10-18).
    
    Returns:
    True if command is valid. False triggers error response to match
    hardware behavior when device doesn't exist.
    
    Raises:
    ValueError: If UUID format invalid (matches hardware error behavior)
    
    Related Research:
    - specs/001-deako-hub-simulator/research/dim-validation-test-2025-10-18.md
    """
    # Implementation...
```

**Rationale**: Code without context is archaeological work. Comments documenting assumptions, motives, and constraints enable future maintainers (including future you) to understand not just WHAT the code does, but WHY it exists and why it's written that way. This is essential for informed refactoring, debugging, and evolution.

### Work Tracking and Organization

**Preventing forgotten work and maintaining discoverability:**

#### TODO/Placeholder Management

Every TODO/FIXME/HACK/PLACEHOLDER/STUB in code or documentation requires:

1. **Task entry** in `specs/[feature]/tasks.md` with:
   - Exact location: file path, line number range or function/class name
   - Clear description of completion criteria
   - Priority and dependencies
   - Link to relevant spec/research context if applicable

2. **Format in code**:
   ```python
   # TODO(T042): Implement hardware-validated rate limiting
   # See: specs/001-deako-hub-simulator/tasks.md#T042
   # Research: specs/001-deako-hub-simulator/research/rate-limiting-systematic-test-2025-10-18.md
   ```

3. **Immediate tracking required**: As soon as you write a TODO/placeholder, you MUST immediately add it to tasks.md
   - **Rationale**: AI agents have limited context windows and will forget to go back to untracked items
   - **No exceptions**: Don't rely on "I'll track it later" - track it NOW or it will be forgotten

4. **Regular audit**: Before marking any feature complete, search codebase for TODO/FIXME/HACK/PLACEHOLDER and verify all are tracked

#### File Organization Rules

**Durable Artifacts** (keep and maintain):
- `specs/[feature]/spec.md` - Requirements and user stories
- `specs/[feature]/plan.md` - Implementation plan  
- `specs/[feature]/tasks.md` - Task list with TODO tracking
- `specs/[feature]/research/` - Hardware testing findings (dated, descriptive names)
- `specs/[feature]/tests/` - Test scripts (descriptive names: `test-[capability]-[date].ps1`)
- `specs/[feature]/contracts/` - API contracts (if applicable)
- Core implementation files in proper source structure

**Temporary Artifacts** (mark for deletion):
- `specs/[feature]/temp/` - Exploratory work, scratch files
- `specs/[feature]/to-delete/` - Obsolete files pending cleanup
- Files MUST have descriptive names indicating purpose and disposability
- Example: `temp/experiment-rate-limiting-2025-10-25.md`

**Discoverability Chain**:
1. `/speckit` commands read: `tasks.md`, `spec.md`, `plan.md`, `research.md`
2. These files MUST reference/link to other durable artifacts
3. Research findings MUST be referenced in spec.md functional requirements
4. Test scripts MUST be referenced in research documents
5. If a file isn't in this chain, it's either temporary or orphaned

**Forbidden Patterns**:
- ❌ Random markdown files at repo root or arbitrary locations
- ❌ Scripts in unlabeled directories without clear purpose
- ❌ "Notes" or "scratch" files outside `temp/` directories
- ❌ Duplicate information across multiple unlinked files
- ❌ Files with generic names like `test.py`, `notes.md`, `temp.txt`

#### Content Organization Principles

- **Chunk by topic**: Break large documents into focused files at natural boundaries (typically around 500 lines when navigation becomes difficult)
- **Clear navigation**: Use table of contents, section links, explicit file references
- **Single source of truth**: Don't duplicate—reference and link
- **Descriptive naming**: File names MUST indicate content and purpose
- **Timestamp everything**: ALL recorded information MUST include date/timestamp to distinguish new from old discoveries

#### Timestamp Requirements

**Mandatory timestamps for ALL artifacts and discoveries** (format: YYYY-MM-DD for dates, ISO 8601 for timestamps):

1. **Research Documents**:
   - File name MUST include date: `[topic]-YYYY-MM-DD.md`
   - Example: `rate-limiting-systematic-test-2025-10-18.md`
   - First line MUST include test date and time if relevant

2. **Test Scripts**:
   - File name MUST include date: `test-[capability]-YYYY-MM-DD.ps1`
   - Example: `test-physical-button-behavior-2025-10-18.ps1`
   - Header comment MUST include creation/last-run date

3. **Spec Updates**:
   - Functional requirements added/modified MUST note date in comment
   - Example: `# FR-075 added 2025-10-18 based on hardware testing`
   - Clarifications section MUST date each Q&A session
   - Example: `### Session 2025-10-25` (already done correctly in current spec)

4. **Task Updates**:
   - Task status changes MUST include timestamp in task notes
   - Example: `T042: Completed 2025-10-25 - validated against real hub`
   - Blocked tasks MUST timestamp when blocked and reason

5. **Code Comments** (for discoveries/quirks):
   - Hardware validation results MUST include test date
   - Example: `# Validated 2025-10-18: Hub accepts out-of-range dim values`
   - TODOs MUST include creation date
   - Example: `# TODO(T042) [2025-10-25]: Implement rate limiting`

6. **Planning Documents**:
   - Decisions MUST include date of decision
   - Architecture changes MUST timestamp the change and rationale
   - Example: `**Decision [2025-10-25]**: Use asyncio for concurrency (rationale...)`

7. **Temporary Artifacts**:
   - File names in `temp/` MUST include date
   - Example: `temp/experiment-connection-pooling-2025-10-25.md`
   - Clear when artifact is disposable based on age

**Rationale for Timestamps**:
- Distinguishes fresh discoveries from old assumptions
- Enables chronological reconstruction of understanding evolution
- Makes it obvious which artifacts are current vs outdated
- Helps future you (and others) understand context and timing
- Prevents confusion about "when did we learn this?"
- Makes temporary artifacts' age visible for cleanup decisions

---

## Governance

### Constitution Authority

This constitution supersedes all other development practices, architectural decisions, or "best practices" documentation. When conflicts arise, the constitution wins.

### Amendments

Constitution amendments require:

1. Documented rationale for the change
2. Impact analysis on existing code and principles
3. Version bump following semantic versioning:
   - **MAJOR**: Backward-incompatible governance changes or principle removals
   - **MINOR**: New principles added or material expansions to existing principles  
   - **PATCH**: Clarifications, wording improvements, non-semantic refinements
4. Update of dependent templates in `.specify/templates/`

### Complexity Justification

When violating "Simplicity Over Cleverness":

1. Document the simpler alternative considered
2. Explain concrete pain that complexity prevents
3. Show evidence the pain exists (not theoretical)
4. Add complexity justification to implementation plan

### Compliance

- Before committing code, MUST self-audit for constitution compliance
- Implementation plans MUST include "Constitution Check" section
- Violations found during development MUST be either fixed or explicitly justified with evidence
- Before marking any feature complete, MUST audit for orphaned TODOs and untracked placeholders
- Before closing a feature branch, MUST clean up temp/ and to-delete/ artifacts
- All new artifacts MUST include appropriate timestamps per "Timestamp Requirements" section
- Test coverage MUST meet 95% target; any exceptions below 95% require documented justification in `specs/[feature]/test-coverage-exceptions.md`
- Tests MUST be deterministic by design (no flaky tests tolerated)
- Error handling MUST comply with Principle VIII (no catch-all exception handlers without justification)

**Version**: 1.4.0 | **Ratified**: 2025-10-25 | **Last Amended**: 2025-10-25
