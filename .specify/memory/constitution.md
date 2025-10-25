<!--
  Sync Impact Report - Constitution v1.1.1
  
  Version Change: 1.1.0 → 1.1.1 (Patch - clarifications and expanded guidance)
  
  Changes in v1.1.1:
  - EXPANDED: "Content Organization Principles" to include comprehensive timestamp
    requirements for all recorded information, not just research files
  - CLARIFIED: Timestamp formats and placement requirements
  - ADDED: Examples of timestamp usage across different artifact types
  
  Previous Principles (Unchanged):
  - I. Hardware Fidelity First
  - II. Simplicity Over Cleverness  
  - III. End-User Validation Required (NON-NEGOTIABLE)
  - IV. Test Facility, Not Product
  - V. Long-Term Readability
  - VI. No Orphaned Work (NON-NEGOTIABLE)
  
  Templates Requiring Review:
  ✅ plan-template.md - Reviewed, no changes needed
  ✅ spec-template.md - Reviewed, no changes needed
  ✅ tasks-template.md - Reviewed, no changes needed
  
  Follow-up TODOs:
  - None - all placeholders resolved
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
- Magic numbers MUST be named constants with comments explaining their source (e.g., "100ms minimum validated via hardware test 2025-10-18")
- Protocol quirks MUST have comments referencing the research document that discovered them
- Variable names are complete words, not abbreviations (device_uuid not dev_id)
- File organization follows obvious structure: models/, services/, api/ not clever architectural abstractions
- No "clever" code—explicit and verbose beats terse and implicit

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

## Technology Constraints

**These constraints prevent technology proliferation and ensure long-term maintainability:**

- **Language**: Python 3.13+ (matches Home Assistant development requirements)
- **Concurrency**: Python asyncio only (no threads, no multiprocessing—keep it simple)
- **HTTP Framework**: aiohttp (lightweight, async-native, sufficient for control API needs)
- **Configuration**: JSON only (no YAML, no TOML—one format, universally supported)
- **Distribution**: pip-installable package with pyproject.toml (standard Python packaging)
- **Logging**: Python standard library logging module (no third-party logging frameworks)
- **Testing**: Validation against real integration code (not unit tests of simulator internals)

**New dependencies require explicit justification**: What problem does this solve? Why can't standard library or existing dependencies handle it? What's the maintenance cost?

---

## Development Standards

### Hardware Validation Gate

Before implementing any protocol behavior:

1. Behavior MUST be validated against real Deako hub hardware OR
2. Marked "PENDING HARDWARE VALIDATION" with explicit validation test script defined
3. Research findings documented in `specs/[feature]/research/[test-name]-YYYY-MM-DD.md`
4. Test scripts placed in `specs/[feature]/tests/test-[name].ps1`

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

- Fail fast with clear error messages over silent degradation
- Log enough context to diagnose issues without reproducing them
- Every error message MUST include: what failed, why it matters, how to fix it
- User errors (bad config, invalid commands) ≠ bugs—guide users, don't crash

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

3. **Regular audit**: Before marking any phase complete, search codebase for TODO/FIXME/HACK/PLACEHOLDER and verify all are tracked

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

- **Chunk by topic**: Break large documents into focused files (max ~500 lines)
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

- All code reviews MUST verify constitution compliance
- Implementation plans MUST include "Constitution Check" section
- Violations found during development MUST be either fixed or explicitly justified with evidence
- Before marking any work phase complete, MUST audit for orphaned TODOs and untracked placeholders
- Regular audits of `temp/` and `to-delete/` directories to ensure timely cleanup
- All new artifacts MUST include appropriate timestamps per "Timestamp Requirements" section

**Version**: 1.1.1 | **Ratified**: 2025-10-25 | **Last Amended**: 2025-10-25
