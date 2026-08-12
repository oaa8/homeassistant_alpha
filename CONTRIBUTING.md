# Contributing to Deako Hub Simulator

Thank you for your interest in contributing to the Deako Hub Simulator! This document provides guidelines for contributing to the project.

## Table of Contents

- [Development Setup](#development-setup)
- [Testing Guidelines](#testing-guidelines)
- [Code Style Guidelines](#code-style-guidelines)
- [Commit Message Format](#commit-message-format)
- [Pull Request Process](#pull-request-process)
- [Constitution Compliance](#constitution-compliance)

---

## Development Setup

### Prerequisites

- Python 3.13 or later
- Git
- pip package manager

### Setup Steps

```bash
# 1. Clone the repository
git clone https://github.com/oaa8/homeassistant_alpha.git
cd homeassistant_alpha

# 2. Checkout the simulator branch
git checkout 001-deako-hub-simulator

# 3. Create a virtual environment (recommended)
python -m venv venv

# Windows
venv\Scripts\activate

# macOS/Linux
source venv/bin/activate

# 4. Install in editable mode with dev dependencies
pip install -e .

# 5. Install test dependencies
pip install pytest pytest-asyncio pytest-cov pytest-timeout

# 6. Verify installation
python -m deako_simulator --help
```

### Project Structure

```
deako_simulator/       # Main package source code
├── __init__.py       # Package metadata
├── cli.py            # Command-line interface
├── server.py         # Telnet server implementation
├── api.py            # HTTP API implementation
├── protocol.py       # Message parsing and formatting
├── models.py         # Data structures
├── config.py         # Configuration management
├── state.py          # Simulator state management
├── quirks.py         # Protocol quirks simulation
├── mdns_service.py   # mDNS/Zeroconf registration
└── logging_config.py # Logging setup

tests/                # Test suite
├── conftest.py       # Pytest configuration and fixtures
├── test_*.py         # Test files organized by module

specs/001-deako-hub-simulator/  # Design documentation
├── spec.md           # Functional requirements
├── plan.md           # Technical implementation plan
├── data-model.md     # Data structures and entities
├── research.md       # Hardware validation findings
└── quickstart.md     # User guide
```

---

## Testing Guidelines

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage report
pytest --cov=deako_simulator --cov-report=term-missing --cov-report=html

# Run specific test file
pytest tests/test_server.py

# Run specific test
pytest tests/test_server.py::test_telnet_server_starts

# Run with verbose output
pytest -v

# Run with detailed output (shows print statements)
pytest -s

# Run in parallel (requires pytest-xdist)
pytest -n auto
```

### Test Coverage Requirements

Per **Constitution Principle VII**, this project requires **95% test coverage** with **no flaky tests**.

**Coverage Exceptions** (documented in `test-coverage-exceptions.md`):
- mDNS registration (manual validation only)
- CLI argument parsing (tested manually)
- Signal handlers (tested manually)

**Test Requirements**:
1. **Deterministic**: Tests must pass reliably, no random failures
2. **Isolated**: Each test must be independent, no execution order dependencies
3. **Fast**: Test suite should complete in < 30 seconds
4. **Documented**: Every test must have a docstring explaining the end-user scenario validated
5. **Assertions with messages**: All assertions should include failure messages explaining impact

### Writing Tests

**Template**:
```python
async def test_feature_name():
    """
    Test <specific behavior> to validate <user story requirement>.
    
    End-user scenario: <How does this affect integration developers?>
    
    Validates: FR-XXX (Functional Requirement from spec.md)
    Research: research/<validation-test>.md (if hardware-validated)
    """
    # Arrange: Set up test fixtures
    state = SimulatorState([sample_device()])
    
    # Act: Perform the action being tested
    result = await state.update_device_state(uuid, power=True)
    
    # Assert: Verify expected outcome with meaningful error messages
    assert result.state.power is True, \
        "Device power should be True after update - integration won't see state change"
```

**Test Organization**:
- `test_<module>.py`: Unit tests for individual modules
- `test_integration_<feature>.py`: Integration tests for complete workflows
- `test_<scenario>.py`: End-to-end scenario tests

---

## Code Style Guidelines

This project follows the **Constitution** (`.specify/memory/constitution.md`) principles:

### Core Principles

1. **Hardware Fidelity First**: Replicate real hardware behavior, not documentation
2. **Simplicity Over Cleverness**: Choose obvious solutions over clever abstractions
3. **End-User Validation Required**: No code is complete until validated
4. **Test Facility, Not Product**: Optimize for reliability and debuggability
5. **Long-Term Readability**: Code must be maintainable by future developers
6. **No Orphaned Work**: All TODOs must be tracked in `tasks.md`
7. **Comprehensive Testing**: 95% coverage, no flaky tests
8. **Explicit Error Handling**: Catch specific exceptions, fail fast on unexpected errors

### File Headers (Required)

Every Python source file must have a module-level docstring:

```python
"""
deako_simulator.server
~~~~~~~~~~~~~~~~~~~~~~

Telnet server implementation for Deako Hub Simulator.

This module implements the asyncio-based telnet server that handles client
connections, message routing, and protocol quirk simulation. It replicates
the connection lifecycle and message handling behaviors validated against
real Deako hub hardware (192.168.86.221:23).

Key Design Decisions:
- Single active connection with passive rejection (FR-072)
- Per-device command queueing for determinism (FR-070)
- Fire-and-forget EVENT broadcasting (research.md decision 6)

Hardware Validation:
- research/connection-lifecycle-test-2025-10-18.md
- research/multi-connection-test-2025-10-18.md
- research/rate-limiting-systematic-test-2025-10-18.md

Author: GitHub Copilot
Created: 2025-10-25
Last Modified: 2025-10-30
"""
```

### Comment Requirements

**WHY not WHAT**: Comments should explain reasoning, not restate code.

❌ Bad:
```python
# Loop through devices
for device in devices:
    # Update state
    device.state = new_state
```

✅ Good:
```python
# Per FR-042: Scenario activation replaces ALL devices atomically.
# This mimics real hub behavior where devices can be added/removed
# while clients remain connected. Clients must re-query DEVICE_LIST
# to discover new topology (validated 2025-10-25).
for device in scenario.devices:
    state.add_device(device)
```

**Hardware Validation References**: Link to research documents for validated behaviors:

```python
# Rate limit: 100ms minimum spacing per device (not 800ms documented)
# Validated 2025-10-18: research/rate-limiting-systematic-test-2025-10-18.md
# Real hub silently drops commands arriving <100ms apart ("first-in-wins")
MIN_COMMAND_SPACING_MS = 100
```

### Error Handling (Principle VIII)

**Catch specific exceptions only**:

❌ Bad:
```python
try:
    device = state.get_device(uuid)
except:  # Bare except swallows all errors!
    return None
```

✅ Good:
```python
try:
    device = state.get_device(uuid)
except KeyError:
    # Expected: Device not found (user provided invalid UUID)
    # Recovery: Return 404 error to caller
    logger.warning(f"Device not found: {uuid}")
    return None
# Unexpected exceptions (AttributeError, TypeError, etc.) propagate
# and cause immediate failure with full traceback for debugging
```

**Justification for catch-all handlers**:

If you MUST use `except Exception:`, document why:

```python
try:
    return await handler(request)
except web.HTTPException:
    raise  # Re-raise HTTP exceptions (already formatted)
except Exception as e:
    # Justification: This is the HTTP API error boundary. Must catch
    # all exceptions to prevent aiohttp from returning HTML error pages
    # instead of JSON responses. All exceptions logged with full traceback.
    logger.exception("Unexpected error in HTTP handler")
    return web.json_response({"error": "internal_error"}, status=500)
```

### Naming Conventions

- **Modules**: `lowercase_with_underscores.py`
- **Classes**: `CapitalizedWords` (PascalCase)
- **Functions/Variables**: `lowercase_with_underscores`
- **Constants**: `ALL_CAPS_WITH_UNDERSCORES`
- **Private**: Prefix with single underscore `_private_function()`

### Import Order

1. Standard library imports
2. Third-party imports
3. Local application imports

```python
import asyncio
import json
from typing import Optional

import aiohttp
from zeroconf import AsyncZeroconf

from deako_simulator.models import Device, DeviceState
from deako_simulator.protocol import parse_message, format_response
```

### Type Hints (Encouraged)

While not strictly required, type hints improve maintainability:

```python
def update_device_state(
    uuid: str,
    power: Optional[bool] = None,
    dim: Optional[int] = None
) -> Device:
    """Update device state with null=no-change semantics (FR-082)."""
    ...
```

---

## Commit Message Format

### Format

```
<type>(<scope>): <subject>

<body>

<footer>
```

### Types

- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `test`: Test additions or modifications
- `refactor`: Code refactoring (no behavior change)
- `perf`: Performance improvements
- `chore`: Build process, dependencies, tooling

### Examples

**Feature**:
```
feat(api): add physical button simulation endpoint

Add POST /api/devices/{uuid}/button endpoint to simulate physical
button presses. Toggles device power and broadcasts EVENT to all
telnet connections.

Validates: FR-076 (Physical button behavior)
Research: research/physical-button-behavior-test-2025-10-18.md
```

**Bug Fix**:
```
fix(protocol): handle null dim values correctly

Fix dim validation to treat null as "no change" per FR-082.
Real hub accepts null dim values without error.

Fixes: #42
```

**Documentation**:
```
docs(quickstart): add CI/CD integration examples

Add GitHub Actions workflow example for automated integration testing.
Shows simulator startup, test execution, and cleanup.
```

### Commit Guidelines

1. **Atomic commits**: One logical change per commit
2. **Present tense**: "Add feature" not "Added feature"
3. **Imperative mood**: "Fix bug" not "Fixes bug"
4. **Reference issues**: Include issue numbers when applicable
5. **Reference requirements**: Include FR-XXX or SC-XXX from spec.md
6. **Hardware validation**: Link research documents for validated behaviors

---

## Pull Request Process

### Before Submitting

1. **Run tests**: Ensure all tests pass
   ```bash
   pytest
   ```

2. **Check coverage**: Verify coverage meets 95% target
   ```bash
   pytest --cov=deako_simulator --cov-report=term-missing
   ```

3. **Run formatter** (if using):
   ```bash
   black deako_simulator tests
   ```

4. **Update documentation**: Reflect changes in relevant .md files

5. **End-user validation**: Test with real Home Assistant integration if possible

### PR Template

```markdown
## Description
Brief description of changes

## Motivation
Why is this change needed? What problem does it solve?

## Testing
- [ ] All tests pass
- [ ] New tests added for new functionality
- [ ] Coverage remains ≥95%
- [ ] Manually tested with Home Assistant integration (if applicable)

## Related Issues
Closes #XX

## Functional Requirements
Implements: FR-XXX, FR-YYY
Validates: SC-XXX

## Hardware Validation
Research: research/<test-name>.md (if applicable)

## Constitution Compliance
- [ ] Principle I: Hardware fidelity maintained
- [ ] Principle II: Simple, obvious implementation
- [ ] Principle III: End-user outcome validated
- [ ] Principle V: Code documented with WHY comments
- [ ] Principle VI: No untracked TODOs
- [ ] Principle VII: Tests added, coverage maintained
- [ ] Principle VIII: Explicit error handling
```

### Review Process

1. **Automated checks**: All CI checks must pass
2. **Code review**: At least one maintainer approval required
3. **Testing verification**: Reviewer should verify test coverage and quality
4. **Documentation review**: Ensure changes documented in relevant .md files
5. **Constitution compliance**: Verify all principles followed

### Merge Requirements

- ✅ All tests passing
- ✅ Coverage ≥95%
- ✅ One approval from maintainer
- ✅ Constitution principles followed
- ✅ Documentation updated
- ✅ No merge conflicts

---

## Constitution Compliance

### Key Requirements

1. **Hardware Fidelity** (Principle I)
   - All protocol behaviors validated against real Deako hub
   - Research documents in `specs/001-deako-hub-simulator/research/`
   - Comments reference specific validation tests

2. **Simplicity** (Principle II)
   - Direct implementations preferred over abstractions
   - No design patterns unless complexity justified
   - Minimal dependencies

3. **End-User Validation** (Principle III)
   - Test with Home Assistant integration
   - Document validation in task completion
   - "Code written" ≠ "task done"

4. **Test Facility Focus** (Principle IV)
   - Reliability > Features
   - Clear error messages
   - Observable behavior (logging)

5. **Readability** (Principle V)
   - File headers with creation date, purpose, assumptions
   - WHY-focused comments
   - Hardware validation references
   - Magic numbers explained with sources

6. **No Orphaned Work** (Principle VI)
   - All TODOs tracked in `tasks.md`
   - Format: `# TODO(TXXX): Description`
   - No FIXME/HACK/PLACEHOLDER without tracking

7. **Comprehensive Testing** (Principle VII)
   - 95% coverage target
   - No flaky tests
   - Tests document WHY
   - Assertion messages with context

8. **Explicit Error Handling** (Principle VIII)
   - Catch specific exceptions only
   - Document expected vs unexpected errors
   - Fail fast on unexpected errors
   - Justify any catch-all handlers

### Validation Checklist

Before marking work complete:

- [ ] File headers present (creation date, author, purpose, assumptions)
- [ ] TODOs tracked in `tasks.md` with exact locations
- [ ] Hardware behaviors reference research documents
- [ ] Magic numbers explained with sources
- [ ] Tests added with 95% coverage
- [ ] Tests are deterministic (no flaky tests)
- [ ] Tests document WHY (docstrings, assertion messages)
- [ ] Error handling explicit (no catch-all except blocks)
- [ ] Code follows simplicity principle
- [ ] End-user validation complete (tested with integration)

---

## Questions?

- **Design decisions**: See `specs/001-deako-hub-simulator/research.md`
- **Functional requirements**: See `specs/001-deako-hub-simulator/spec.md`
- **Implementation plan**: See `specs/001-deako-hub-simulator/plan.md`
- **User guide**: See `specs/001-deako-hub-simulator/quickstart.md`
- **Constitution**: See `.specify/memory/constitution.md`

For questions not covered here, open an issue on GitHub.

---

## License

This project is part of the Deako Home Assistant integration. See [LICENSE](LICENSE) for details.
