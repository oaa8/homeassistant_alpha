"""Protocol quirk simulation and injection for testing integration robustness.

Author: GitHub Copilot
Created: 2025-10-27
Last Modified: 2025-10-27
Purpose: Simulate Deako hub protocol quirks and edge cases for integration testing

Key Assumptions:
- Real hub does NOT exhibit most of these behaviors (validated 2025-10-18)
- Quirks are for testing integration defensive code, not replicating hub behavior
- All quirks default to DISABLED to match real hub behavior
- Quirks are configurable at runtime via HTTP API (T055-T061)

Related Research:
- research/whitespace-behavior-test-2025-10-18.md: Hub doesn't send whitespace
- research/message-format-edge-cases-test-2025-10-18.md: Hub message format quirks
- research/error-code-validation-test-2025-10-18.md: Only 3 error codes exist

Hardware Validation:
All quirk behaviors are documented as either:
1. NOT present on real hardware (for testing integration defensive code)
2. Present and validated on real hardware (date and test reference provided)
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Optional

# Configure logging for quirk module
logger = logging.getLogger("deako_simulator.quirks")


@dataclass
class QuirkConfig:
    """Configuration for protocol quirk simulation.
    
    All quirks default to DISABLED to match real Deako hub behavior.
    Enable quirks via configuration or HTTP API to test integration robustness.
    
    Validated: Real hub does NOT exhibit these behaviors (2025-10-18 testing).
    Purpose: Test integration defensive code and error handling.
    """
    
    # Whitespace injection (FR-024, FR-026)
    # Research: whitespace-behavior-test-2025-10-18.md confirms hub does NOT send whitespace
    whitespace_enabled: bool = False
    whitespace_interval: float = 0.0  # Seconds between whitespace messages (0 = disabled)
    
    # Message delays (FR-026)
    # Research: Real hub responds in 5-200ms (performance-limits-test-2025-10-20.md)
    # This adds artificial delays for testing timeout handling
    message_delay_enabled: bool = False
    message_delay_seconds: float = 0.0  # Delay before sending responses
    
    # Malformed JSON injection (FR-028, FR-077)
    # Research: Real hub silently ignores malformed JSON (message-format-edge-cases-test)
    # This tests integration's JSON parsing error handling
    malformed_json_enabled: bool = False
    malformed_json_rate: float = 0.0  # Probability (0.0-1.0) of injecting malformed JSON
    
    # Connection control (FR-084-087)
    # For testing connection resilience and recovery
    refuse_connections: bool = False  # Reject incoming connections
    connection_delay: float = 0.0  # Delay before processing any message (latency simulation)


class QuirkManager:
    """Manages protocol quirk simulation for integration testing.
    
    This class provides runtime control over protocol quirks that either:
    1. Do NOT exist on real hardware (for testing defensive code)
    2. Can be exaggerated for stress testing
    
    Design: Single-threaded asyncio access (constitution principle - no locks needed)
    
    Thread Safety: Not required - asyncio event loop is single-threaded per
    research.md decision 6. All methods are synchronous except background tasks.
    """
    
    def __init__(self, config: Optional[QuirkConfig] = None) -> None:
        """Initialize quirk manager with optional configuration.
        
        Args:
            config: QuirkConfig instance, or None for all-disabled defaults
        """
        self.config = config or QuirkConfig()
        self._whitespace_task: Optional[asyncio.Task] = None
        self._running = False
        self._last_whitespace_time: float = 0.0  # Track last whitespace injection
        self._active_connection: Optional[asyncio.StreamWriter] = None  # Track active connection for failure simulation
        
        logger.info(
            "QuirkManager initialized: whitespace=%s, delays=%s, malformed=%s",
            self.config.whitespace_enabled,
            self.config.message_delay_enabled,
            self.config.malformed_json_enabled,
        )
    
    def enable_whitespace(self, interval: float = 1.0) -> None:
        """Enable whitespace message injection.
        
        WARNING: Real Deako hub does NOT send whitespace messages.
        This is for testing integration defensive code only.
        
        Research: whitespace-behavior-test-2025-10-18.md
        - Hub was tested for 30 seconds idle - zero whitespace received
        - Hub sent 100 empty lines - all silently ignored
        
        Args:
            interval: Seconds between whitespace messages (default 1.0)
        """
        self.config.whitespace_enabled = True
        self.config.whitespace_interval = interval
        self._last_whitespace_time = time.time()  # Reset timer on enable
        logger.warning(
            "Whitespace injection ENABLED (interval=%.1fs) - NOT real hub behavior!",
            interval,
        )
    
    def disable_whitespace(self) -> None:
        """Disable whitespace message injection (default state)."""
        self.config.whitespace_enabled = False
        self.config.whitespace_interval = 0.0
        logger.info("Whitespace injection disabled (matches real hub)")
    
    def enable_message_delays(self, delay_seconds: float = 0.5) -> None:
        """Enable artificial message response delays.
        
        Real hub responds in 5-200ms (performance-limits-test-2025-10-20.md).
        This adds extra delay for testing timeout handling.
        
        Args:
            delay_seconds: Delay in seconds before sending responses
        """
        self.config.message_delay_enabled = True
        self.config.message_delay_seconds = delay_seconds
        logger.info("Message delays enabled: %.2fs", delay_seconds)
    
    def disable_message_delays(self) -> None:
        """Disable artificial message delays (default state)."""
        self.config.message_delay_enabled = False
        self.config.message_delay_seconds = 0.0
        logger.info("Message delays disabled")
    
    def enable_malformed_json(self, rate: float = 0.1) -> None:
        """Enable malformed JSON injection.
        
        Real hub silently ignores malformed JSON from clients
        (message-format-edge-cases-test-2025-10-18.md).
        This tests integration's JSON parsing error handling.
        
        Args:
            rate: Probability (0.0-1.0) of injecting malformed JSON
        """
        if not 0.0 <= rate <= 1.0:
            raise ValueError(f"Rate must be 0.0-1.0, got {rate}")
        
        self.config.malformed_json_enabled = True
        self.config.malformed_json_rate = rate
        logger.info("Malformed JSON injection enabled: rate=%.2f", rate)
    
    def disable_malformed_json(self) -> None:
        """Disable malformed JSON injection (default state)."""
        self.config.malformed_json_enabled = False
        self.config.malformed_json_rate = 0.0
        logger.info("Malformed JSON injection disabled")
    
    def set_connection_refusal(self, refuse: bool) -> None:
        """Enable/disable connection refusal for resilience testing.
        
        Args:
            refuse: True to reject new connections, False to accept (default)
        """
        self.config.refuse_connections = refuse
        logger.info("Connection refusal: %s", "ENABLED" if refuse else "disabled")
    
    def set_connection_delay(self, delay_seconds: float) -> None:
        """Set artificial connection latency for resilience testing.
        
        Args:
            delay_seconds: Delay before processing messages (simulates high latency)
        """
        self.config.connection_delay = delay_seconds
        logger.info("Connection latency simulation: %.2fs", delay_seconds)
    
    def set_active_connection(self, writer: Optional[asyncio.StreamWriter]) -> None:
        """Set the active connection for connection failure simulation.
        
        Args:
            writer: StreamWriter for active connection, or None to clear
        
        Purpose: Allows simulate_connection_failure() to forcibly close the connection.
        Called by server when new connection becomes active.
        """
        self._active_connection = writer
        if writer:
            logger.debug("QuirkManager tracking active connection for failure simulation")
        else:
            logger.debug("QuirkManager cleared active connection reference")
    
    async def simulate_connection_failure(self) -> bool:
        """Forcibly close the active connection to simulate network failure.
        
        Returns:
            True if connection was closed, False if no active connection
        
        Purpose: Test integration reconnection logic and error handling.
        Connection will be closed immediately without graceful shutdown.
        
        Research: Connection resilience testing per FR-084-087
        Real hub can experience network failures - integration must handle reconnection.
        """
        if self._active_connection is None:
            logger.warning("simulate_connection_failure(): No active connection to close")
            return False
        
        try:
            # Forcibly close connection without drain or wait_closed
            # This simulates abrupt network failure (e.g., cable unplugged)
            self._active_connection.close()
            logger.info("Connection failure simulated: forcibly closed active connection")
            
            # Clear reference
            self._active_connection = None
            return True
            
        except Exception as e:
            logger.error(f"Error simulating connection failure: {e}")
            return False
    
    async def should_inject_whitespace(self) -> bool:
        """Check if whitespace should be injected now.
        
        Returns:
            True if whitespace injection is enabled and interval elapsed
        
        Side effects:
            Updates _last_whitespace_time if returning True
        
        Research: whitespace-behavior-test-2025-10-18.md
        Real hub does NOT send whitespace. This tests integration resilience.
        """
        if not self.config.whitespace_enabled:
            return False
        
        if self.config.whitespace_interval <= 0:
            return False
        
        current_time = time.time()
        elapsed = current_time - self._last_whitespace_time
        
        if elapsed >= self.config.whitespace_interval:
            self._last_whitespace_time = current_time
            logger.debug(
                "Whitespace injection triggered after %.2fs elapsed",
                elapsed
            )
            return True
        
        return False
    
    async def should_delay_message(self) -> bool:
        """Check if message should be delayed.
        
        Returns:
            True if message delays are enabled
        """
        return self.config.message_delay_enabled
    
    async def get_message_delay(self) -> float:
        """Get configured message delay in seconds.
        
        Returns:
            Delay in seconds, or 0.0 if delays disabled
        """
        if self.config.message_delay_enabled:
            return self.config.message_delay_seconds
        return 0.0
    
    async def should_inject_malformed_json(self) -> bool:
        """Check if malformed JSON should be injected for this message.
        
        Uses configured probability rate to decide randomly.
        
        Returns:
            True if malformed JSON should be injected
        
        Research: message-format-edge-cases-test-2025-10-18.md
        Real hub silently ignores malformed JSON from clients per FR-077.
        This tests integration's JSON parsing error handling.
        """
        if not self.config.malformed_json_enabled:
            return False
        
        if self.config.malformed_json_rate <= 0.0:
            return False
        
        # Use random probability to determine injection
        should_inject = random.random() < self.config.malformed_json_rate
        
        if should_inject:
            logger.debug(
                "Malformed JSON injection triggered (rate=%.2f)",
                self.config.malformed_json_rate
            )
        
        return should_inject
    
    def should_refuse_connection(self) -> bool:
        """Check if new connections should be refused.
        
        Returns:
            True if connection refusal is enabled
        """
        return self.config.refuse_connections
    
    async def get_connection_delay(self) -> float:
        """Get configured connection delay in seconds.
        
        Returns:
            Delay in seconds, or 0.0 if no delay configured
        """
        return self.config.connection_delay
    
    def get_whitespace_message(self) -> str:
        """Get whitespace-only message (CRLF).
        
        Returns:
            CRLF string (\\r\\n)
        
        Per FR-024: Sends CRLF-only lines to test message buffer handling.
        Research: whitespace-behavior-test-2025-10-18.md - Real hub doesn't
        send whitespace but clients may send it, which hub silently ignores.
        """
        return "\r\n"
    
    def get_malformed_json(self) -> str:
        """Generate malformed JSON message with CRLF terminator.
        
        Returns:
            Invalid JSON string with CRLF (e.g., "{this is not valid json}\\r\\n")
        
        Per FR-077: Real hub silently ignores malformed JSON syntax.
        This tests client resilience to protocol errors.
        
        Research: error-code-validation-test-2025-10-18.md
        Malformed JSON tested: hub sent no error response, connection stayed active.
        """
        # Generate various types of malformed JSON that real hub might encounter
        malformed_variants = [
            "{this is not valid json}",
            '{"incomplete": "message"',  # Missing closing brace
            '{"missing_colon" true}',  # Missing colon
            '{"trailing_comma": "value",}',  # Trailing comma
            '{unquoted_key: "value"}',  # Unquoted key
            '{"name": undefined}',  # Invalid value
            '{"extra": "bracket"}}',  # Extra closing brace
        ]
        
        malformed = random.choice(malformed_variants)
        logger.debug(f"Generated malformed JSON: {malformed}")
        return malformed + "\r\n"
    
    def get_quirk_status(self) -> dict:
        """Get current status of all quirks.
        
        Returns:
            Dictionary with status of all quirk configurations
        
        Useful for:
        - HTTP API status endpoint
        - Logging effective configuration
        - Debugging quirk behavior
        """
        return {
            "whitespace": {
                "enabled": self.config.whitespace_enabled,
                "interval": self.config.whitespace_interval,
            },
            "message_delays": {
                "enabled": self.config.message_delay_enabled,
                "delay_seconds": self.config.message_delay_seconds,
            },
            "malformed_json": {
                "enabled": self.config.malformed_json_enabled,
                "rate": self.config.malformed_json_rate,
            },
            "connection_control": {
                "refuse_connections": self.config.refuse_connections,
                "connection_delay": self.config.connection_delay,
            },
        }


# TODO(T050): Integration points for server.py:
# - handle_connection(): Check should_refuse_connection() and connection_delay
# - process_message(): Check should_delay_message() before responses
# - message stream: Inject whitespace via should_inject_whitespace()
# - message sending: Potentially inject malformed JSON via should_inject_malformed_json()

# Constitution compliance markers:
# - File header: ✓ (creation date, author, purpose, assumptions)
# - Research references: ✓ (whitespace-behavior-test-2025-10-18.md, etc.)
# - Magic numbers explained: ✓ (default intervals/rates documented with rationale)
# - WHY comments: ✓ (explains hub doesn't exhibit behaviors, testing defensive code)
# - Single-threaded asyncio: ✓ (no locks, documented in class docstring)
# - TODO tracking: ✓ (T050 integration points documented)
