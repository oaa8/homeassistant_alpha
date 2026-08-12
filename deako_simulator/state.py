"""
Deako Hub Simulator - State Management

Author: GitHub Copilot
Created: 2025-10-26
Last Modified: 2025-10-26

Purpose:
    Manages runtime simulator state including device states, active connections,
    rate limiting tracking, and per-device command queues.

Key Assumptions:
    - Single-threaded asyncio access (no locks needed per research.md decision 6)
    - First connection is active, additional connections are zombie (FR-072)
    - Commands spaced <100ms apart are rate-limited per device (FR-023)
    - Per-device command serialization via asyncio.Queue (FR-070)

Related Research:
    - research/rate-limiting-systematic-test-2025-10-18.md - 100ms rate limit validation
    - research/multi-connection-test-2025-10-18.md - Passive rejection behavior
    - research.md - Single-threaded asyncio design decision
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

from .models import Device

logger = logging.getLogger("deako_simulator.state")


class SimulatorState:
    """
    Manages simulator runtime state.
    
    Thread-safe by design because asyncio event loop is single-threaded.
    All state mutations happen synchronously in the event loop.
    """
    
    def __init__(self, devices: list[Device]) -> None:
        """
        Initialize simulator state with device list.
        
        Args:
            devices: List of Device objects to simulate
        """
        # Device storage: UUID -> Device mapping
        self.devices: dict[str, Device] = {d.uuid: d for d in devices}
        
        # Connection management
        self.connections: list[asyncio.StreamWriter] = []
        self.active_connection: Optional[asyncio.StreamWriter] = None
        
        # Rate limiting tracking: UUID -> last command timestamp
        # Per research/rate-limiting-systematic-test-2025-10-18.md:
        # Commands within 100ms are silently dropped (first-in-wins)
        self.last_command_time: dict[str, float] = {}
        
        # Per-device command queues for serialization (FR-070)
        # Commands for same device processed serially to ensure deterministic behavior
        self.command_queues: dict[str, asyncio.Queue[dict[str, Any]]] = {
            d.uuid: asyncio.Queue() for d in devices
        }
        
        logger.info(f"SimulatorState initialized with {len(devices)} devices")
    
    def get_device(self, uuid: str) -> Optional[Device]:
        """
        Retrieve device by UUID.
        
        Args:
            uuid: Device UUID to look up
            
        Returns:
            Device object if found, None otherwise
        """
        return self.devices.get(uuid)
    
    def update_device_state(
        self,
        uuid: str,
        power: Optional[bool] = None,
        dim: int | float | None = None,
    ) -> Device:
        """
        Update device state. Null values mean "no change" per FR-082.
        
        Args:
            uuid: Device UUID to update
            power: New power state (None = no change)
            dim: New dim level 0-100 (None = no change)
            
        Returns:
            Updated Device object
            
        Raises:
            KeyError: If device UUID not found
        """
        device = self.devices[uuid]
        
        # Update power if provided (not None)
        if power is not None:
            device.state.power = power
        
        # Update dim if provided (not None)
        # Per FR-071 and research/dim-validation-test-2025-10-18.md:
        # Accept all numeric values, clamp to 0-100, truncate decimals
        if dim is not None:
            # Clamp to valid range
            if dim < 0:
                dim = 0
            elif dim > 100:
                dim = 100
            # Truncate decimals (real hub accepts 50.7 -> 50)
            dim = int(dim)
            device.state.dim = dim
        
        logger.debug(f"Device {uuid} state updated: power={device.state.power}, dim={device.state.dim}")
        return device
    
    def get_all_devices(self) -> list[Device]:
        """
        Get list of all devices.
        
        Returns:
            List of all Device objects
        """
        return list(self.devices.values())
    
    def add_device(self, device: Device) -> None:
        """
        Add a new device to simulator.
        
        Args:
            device: Device object to add
            
        Note:
            Used by HTTP API for runtime device management.
            Creates command queue for the new device.
        """
        self.devices[device.uuid] = device
        self.command_queues[device.uuid] = asyncio.Queue()
        logger.info(f"Device added: {device.uuid} ({device.name})")
    
    def remove_device(self, uuid: str) -> None:
        """
        Remove a device from simulator.
        
        Args:
            uuid: Device UUID to remove
            
        Raises:
            KeyError: If device UUID not found
        """
        device = self.devices.pop(uuid)
        del self.command_queues[uuid]
        logger.info(f"Device removed: {uuid} ({device.name})")
    
    def is_rate_limited(self, uuid: str) -> bool:
        """
        Check if device is rate-limited (command within 100ms of previous).
        
        Per research/rate-limiting-systematic-test-2025-10-18.md:
        - Minimum 100ms spacing between commands per device
        - Commands arriving <100ms after previous are silently dropped
        - "First-in-wins" behavior matches real hub
        
        Args:
            uuid: Device UUID to check
            
        Returns:
            True if rate-limited (should drop command), False otherwise
        """
        now = time.time()
        last_time = self.last_command_time.get(uuid, 0)
        
        # 100ms = 0.1 seconds
        if (now - last_time) < 0.1:
            logger.debug(f"Rate limit: Command for device {uuid} dropped (< 100ms since last)")
            return True
        
        return False
    
    def update_command_time(self, uuid: str) -> None:
        """
        Update last command timestamp for device.
        
        Args:
            uuid: Device UUID
        """
        self.last_command_time[uuid] = time.time()
    
    def set_active_connection(self, writer: asyncio.StreamWriter) -> None:
        """
        Set the active (functional) connection.
        
        Per FR-072 and research/multi-connection-test-2025-10-18.md:
        - First connection is active and receives responses
        - Additional connections are "zombie" - accepted but passive
        
        Args:
            writer: StreamWriter for active connection
        """
        if self.active_connection is None:
            self.active_connection = writer
            addr = writer.get_extra_info('peername')
            logger.info(f"Connection from {addr} is now active")
        else:
            addr = writer.get_extra_info('peername')
            logger.info(f"Connection from {addr} accepted but passive (zombie) - another client active")
    
    def is_active_connection(self, writer: asyncio.StreamWriter) -> bool:
        """
        Check if connection is the active (functional) one.
        
        Args:
            writer: StreamWriter to check
            
        Returns:
            True if this is the active connection, False if zombie
        """
        return writer is self.active_connection
    
    def clear_active_connection(self, writer: asyncio.StreamWriter) -> None:
        """
        Clear active connection if it matches the given writer.
        
        Args:
            writer: StreamWriter being disconnected
        """
        if writer is self.active_connection:
            addr = writer.get_extra_info('peername')
            logger.info(f"Active connection from {addr} disconnected")
            self.active_connection = None
    
    def add_connection(self, writer: asyncio.StreamWriter) -> None:
        """
        Add a connection to the connection list.
        
        Args:
            writer: StreamWriter to add
        """
        self.connections.append(writer)
        addr = writer.get_extra_info('peername')
        logger.info(f"Connection added from {addr} (total: {len(self.connections)})")
    
    def remove_connection(self, writer: asyncio.StreamWriter) -> None:
        """
        Remove a connection from the connection list.
        
        Args:
            writer: StreamWriter to remove
        """
        if writer in self.connections:
            self.connections.remove(writer)
            addr = writer.get_extra_info('peername')
            logger.info(f"Connection removed from {addr} (total: {len(self.connections)})")
    
    async def broadcast_event(self, event: dict[str, Any]) -> None:
        """
        Broadcast EVENT to active connection only (passive rejection model).
        
        Per FR-072: Only active connection receives EVENTs.
        Fire-and-forget pattern - don't wait for completion.
        
        Args:
            event: Event dictionary to broadcast
        """
        if self.active_connection is None:
            logger.debug("No active connection - EVENT not broadcast")
            return
        
        # Send to active connection only
        asyncio.create_task(self._send_event(self.active_connection, event))
        logger.debug("EVENT broadcast initiated to active connection")
    
    async def _send_event(self, writer: asyncio.StreamWriter, event: dict[str, Any]) -> None:
        """
        Send EVENT to a single connection.
        
        Handles write failures gracefully by removing dead connections.
        
        Args:
            writer: StreamWriter to send to
            event: Event dictionary to send
        """
        import json
        
        try:
            message = json.dumps(event) + '\r\n'
            writer.write(message.encode())
            await writer.drain()
            logger.debug(f"EVENT sent successfully")
        except (OSError, ConnectionResetError) as e:
            addr = writer.get_extra_info('peername')
            logger.warning(f"Failed to send EVENT to {addr}: {e}")
            # Remove dead connection
            self.remove_connection(writer)
            self.clear_active_connection(writer)
        except Exception as e:
            logger.exception(f"Unexpected error sending EVENT: {e}")
