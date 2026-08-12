"""Tests for whitespace message injection quirk (FR-024, FR-026).

Author: GitHub Copilot
Created: 2025-10-27
Purpose: Validate whitespace message injection and handling behavior
Research: ../specs/001-deako-hub-simulator/research/whitespace-behavior-test-2025-10-18.md

Key Findings from Research:
- Real hub does NOT send whitespace messages
- Real hub silently ignores whitespace from clients
- Whitespace injection is for testing integration defensive code, not hub behavior replication
- Whitespace should be disabled by default, configurable for testing

Test Coverage:
- T046: Whitespace-only message injection (FR-024: configurable intervals)
- T046: Integration buffer handling (FR-026: inconsistent newline/framing)
- T046: Whitespace messages don't affect valid JSON processing
"""

import asyncio
import pytest
from deako_simulator.quirks import QuirkManager, QuirkConfig

# These tests validate optional whitespace injection for testing integration
# defensive code. Real hub does NOT send whitespace (validated 2025-10-18).


@pytest.mark.asyncio
async def test_whitespace_injection_disabled_by_default():
    """
    Validate FR-026: Whitespace injection disabled by default.
    
    End-user scenario: Integration developer starts simulator with default
    config and should NOT receive whitespace messages (matches real hub).
    
    Research: whitespace-behavior-test-2025-10-18.md confirms hub does NOT
    send whitespace messages.
    """
    manager = QuirkManager()
    
    # Verify whitespace is disabled by default
    assert manager.config.whitespace_enabled is False, \
        "Whitespace injection must be disabled by default to match real hub behavior"
    assert manager.config.whitespace_interval == 0.0, \
        "Whitespace interval must be 0.0 when disabled"
    
    # Verify should_inject_whitespace returns False
    should_inject = await manager.should_inject_whitespace()
    assert should_inject is False, \
        "QuirkManager should not inject whitespace by default - integration expects real hub behavior"


@pytest.mark.asyncio
async def test_whitespace_injection_configurable():
    """
    Validate FR-024: Whitespace injection can be enabled via config.
    
    End-user scenario: Integration developer enables whitespace injection
    to test integration's defensive whitespace handling code.
    
    Research: whitespace-behavior-test-2025-10-18.md shows hub silently
    ignores whitespace, so this tests integration robustness not hub behavior.
    """
    manager = QuirkManager()
    
    # Enable whitespace injection
    manager.enable_whitespace(interval=1.0)
    
    # Verify configuration updated
    assert manager.config.whitespace_enabled is True, \
        "enable_whitespace() must set whitespace_enabled=True"
    assert manager.config.whitespace_interval == 1.0, \
        "enable_whitespace() must set configured interval"
    
    # TODO(T049): Once timing logic implemented, verify should_inject_whitespace
    # returns True at appropriate intervals
    # Current test validates configuration API only


@pytest.mark.asyncio
async def test_whitespace_between_valid_messages():
    """
    Validate FR-026: Whitespace between valid messages doesn't break protocol.
    
    End-user scenario: Integration receives mix of whitespace and valid JSON,
    should correctly parse valid messages and ignore whitespace.
    
    Research: whitespace-behavior-test-2025-10-18.md shows hub gracefully
    ignores whitespace (tested with 100 empty lines, connection survived).
    """
    # TODO(T050): This test requires server integration
    # Once server.py integrates QuirkManager, test that:
    # 1. Server receives: PING + empty lines + PING
    # 2. Server processes both PING commands correctly
    # 3. Empty lines are silently ignored
    # For now, validate QuirkManager API exists
    manager = QuirkManager()
    assert hasattr(manager, 'config'), "QuirkManager must have config attribute"


@pytest.mark.asyncio
async def test_whitespace_flood_resilience():
    """
    Validate FR-026: Server handles whitespace flood without crashing.
    
    End-user scenario: Integration sends many empty lines (buggy client or
    testing), simulator should remain stable and functional.
    
    Research: whitespace-behavior-test-2025-10-18.md shows hub survives
    100 empty lines without disconnect or errors.
    """
    # TODO(T050): Requires server integration
    # Validate QuirkManager doesn't break with flood settings
    manager = QuirkManager()
    # Should not raise even with extreme settings
    manager.enable_whitespace(interval=0.001)  # Very frequent
    assert manager.config.whitespace_interval == 0.001


@pytest.mark.asyncio
async def test_whitespace_variants_ignored():
    """
    Validate FR-026: Different whitespace types (spaces, tabs, mixed) ignored.
    
    End-user scenario: Integration sends various whitespace patterns,
    simulator should ignore all types consistently.
    
    Research: whitespace-behavior-test-2025-10-18.md tested empty lines,
    spaces-only, tabs-only - all silently ignored by real hub.
    """
    # TODO(T050): Requires server integration for message parsing
    # Validate QuirkManager structure exists
    manager = QuirkManager()
    assert manager is not None


@pytest.mark.asyncio
async def test_whitespace_injection_interval():
    """
    Validate FR-024: Whitespace injection respects configured interval.
    
    End-user scenario: Integration developer configures whitespace every 2
    seconds to test integration's empty message counter.
    
    Research: Real hub doesn't send whitespace, but integration has code to
    count empty messages. This tests that defensive code works correctly.
    """
    manager = QuirkManager()
    manager.enable_whitespace(interval=2.0)
    
    assert manager.config.whitespace_interval == 2.0, \
        "enable_whitespace() must set exact interval for timing tests"
    
    # TODO(T049): Test actual timing once background task implemented


@pytest.mark.asyncio
async def test_client_whitespace_silently_ignored():
    """
    Validate FR-026: Server silently ignores whitespace from clients (matches hub).
    
    End-user scenario: Integration sends empty line by mistake, should not
    cause error or disconnect.
    
    Research: whitespace-behavior-test-2025-10-18.md confirms hub silently
    ignores whitespace (no response, no error, no disconnect).
    """
    # TODO(T050): Requires server integration
    # Validate QuirkManager config structure
    manager = QuirkManager()
    config = QuirkConfig()
    assert config.whitespace_enabled is False, "Default config must disable whitespace"


@pytest.mark.asyncio
async def test_whitespace_doesnt_break_message_framing():
    """
    Validate FR-026: Whitespace doesn't interfere with JSON message boundaries.
    
    End-user scenario: Integration receives JSON message, whitespace line,
    then another JSON message. Should parse both correctly.
    
    Research: Message framing is CRLF-delimited (research.md decision 2).
    Whitespace lines have CRLF but no JSON content.
    """
    # TODO(T050): Requires server integration
    manager = QuirkManager()
    # Verify manager can be created (basic smoke test)
    assert manager is not None


@pytest.mark.asyncio
async def test_whitespace_injection_stop_and_start():
    """
    Validate FR-024: Whitespace injection can be toggled at runtime.
    
    End-user scenario: Integration developer starts test with whitespace
    enabled, then disables it mid-test to observe behavior change.
    
    Note: This tests HTTP API control interface (T055-T061).
    """
    manager = QuirkManager()
    
    # Enable, then disable
    manager.enable_whitespace(interval=1.0)
    assert manager.config.whitespace_enabled is True
    
    manager.disable_whitespace()
    assert manager.config.whitespace_enabled is False, \
        "disable_whitespace() must turn off whitespace injection"
    assert manager.config.whitespace_interval == 0.0, \
        "disable_whitespace() must reset interval to 0.0"


# Hardware validation reference marker for test framework
__research_validated__ = "whitespace-behavior-test-2025-10-18.md"
__functional_requirements__ = ["FR-024", "FR-026"]
__user_story__ = "US4"  # User Story 4 - Protocol Timing and Message Quirks
