"""Device and message data models.

Author: GitHub Copilot
Created: 2025-10-25
Last Modified: 2025-10-25
Purpose: Core data structures for device state and protocol messages

Key Assumptions:
- Device UUIDs are lowercase UUID v4 format
- Dim capability requires power capability (FR-005)
- Dim values range 0-100 (validated per research/dim-validation-test-2025-10-18.md)
- State updates use null for "no change" (FR-082)

Related Research:
- specs/001-deako-hub-simulator/research/dim-validation-test-2025-10-18.md
- specs/001-deako-hub-simulator/data-model.md
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
import re


@dataclass
class DeviceState:
    """Represents the current state of a Deako device.
    
    Attributes:
        power: Device power state (on=True, off=False)
        dim: Dim level percentage (0-100), None for power-only devices
        
    Validated Behavior (research/dim-validation-test-2025-10-18.md):
    - Real hub accepts any numeric dim value without error
    - Values <0 clamped to 0, >100 clamped to 100
    - Decimal values truncated to integers
    """
    power: bool
    dim: Optional[int] = None
    
    def __post_init__(self) -> None:
        """Validate state after initialization."""
        if self.dim is not None:
            # Clamp dim to valid range per hardware behavior
            if not isinstance(self.dim, (int, float)):
                raise ValueError(f"dim must be numeric, got {type(self.dim)}")
            self.dim = int(max(0, min(100, self.dim)))


@dataclass
class Device:
    """Represents a Deako device (light switch/dimmer).
    
    Attributes:
        uuid: Unique device identifier (lowercase UUID v4)
        name: Human-readable device name
        capabilities: List of capabilities ("power" or ["power", "dim"])
        state: Current device state
        
    Validation Rules (FR-005):
    - UUID must be valid UUID v4 format
    - Name must be non-empty
    - Capabilities must include "power"
    - If "dim" in capabilities, "power" must also be present
    - state.dim must be None for power-only devices
    """
    uuid: str
    name: str
    capabilities: list[str]
    state: DeviceState
    
    # UUID v4 pattern: lowercase, 8-4-4-4-12 hex digits
    UUID_PATTERN = re.compile(
        r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
    )
    
    def __post_init__(self) -> None:
        """Validate device after initialization."""
        # Validate UUID format
        if not self.UUID_PATTERN.match(self.uuid):
            raise ValueError(
                f"uuid must be lowercase UUID v4 format, got '{self.uuid}'"
            )
        
        # Validate name
        if not self.name or not self.name.strip():
            raise ValueError("name must be non-empty")
        
        # Validate capabilities
        if not self.capabilities:
            raise ValueError("capabilities must not be empty")
        
        if "power" not in self.capabilities:
            raise ValueError("capabilities must include 'power'")
        
        # Validate dim capability requires power
        if "dim" in self.capabilities and "power" not in self.capabilities:
            raise ValueError(
                "dim capability requires power capability (FR-005)"
            )
        
        # Validate dim state consistency
        if "dim" not in self.capabilities and self.state.dim is not None:
            raise ValueError(
                f"Device '{self.name}' has dim state but no dim capability"
            )
        
        # Validate only known capabilities
        valid_capabilities = {"power", "dim"}
        unknown = set(self.capabilities) - valid_capabilities
        if unknown:
            raise ValueError(
                f"Unknown capabilities: {unknown}. Valid: {valid_capabilities}"
            )
    
    def update_state(
        self,
        power: Optional[bool] = None,
        dim: Optional[int] = None
    ) -> Device:
        """Update device state, returning self for method chaining.
        
        Args:
            power: New power state, or None to keep current
            dim: New dim level, or None to keep current
            
        Returns:
            Self (for method chaining)
            
        Note (FR-082): null/None means "no change", validated in
        research/device-state-test-2025-10-18.md
        """
        if power is not None:
            self.state.power = power
        
        if dim is not None:
            if "dim" not in self.capabilities:
                raise ValueError(
                    f"Device '{self.name}' does not have dim capability"
                )
            self.state.dim = max(0, min(100, int(dim)))
        
        return self
