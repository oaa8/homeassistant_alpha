"""
mDNS service advertisement for Deako Hub Simulator

Module: mdns_service.py
Created: 2025-10-26
Last Modified: 2026-08-11
Author: GitHub Copilot
Purpose: Register and unregister the mDNS services a real Deako hub publishes,
    so that Home Assistant and pydeako auto-discover the simulator exactly as
    they would discover physical hardware.

Key Assumptions:
    - Uses zeroconf library for mDNS/Bonjour/Avahi integration
    - A real hub publishes TWO service types simultaneously; both are registered
    - Graceful degradation if mDNS registration fails (FR-069)
    - Best-effort unregistration during shutdown

Related Requirements:
    - FR-001: Advertise via mDNS so the simulator is discoverable
    - FR-069: If mDNS fails, log WARNING and continue (simulator still works)

Related Research:
    - research.md decision 3: Fail-fast registration with graceful fallback
    - research/mdns-service-type-test-2026-08-11.md: live scan of production
      hubs proving both service types are published
"""

from __future__ import annotations

import asyncio
import logging
import socket
from typing import Optional, Sequence, Tuple, Union

from zeroconf import ServiceInfo
from zeroconf.asyncio import AsyncZeroconf


# Get logger with component tag
logger = logging.getLogger("deako_simulator.mdns")


# Service type browsed by pydeako's DeakoDiscoverer (DEAKO_TYPE) and declared
# in the Home Assistant integration manifest's "zeroconf" key. Discovery of the
# simulator is impossible without this type, so it is the primary registration.
DEAKO_SERVICE_TYPE = "_deako._tcp.local."

# Secondary type also published by real hubs. Nothing in the current discovery
# path consumes it, but it is registered so that anything scanning the network
# sees the same advertisement surface as physical hardware.
TELNET_SERVICE_TYPE = "_telnet._tcp.local."


def _detect_local_ip() -> Optional[str]:
    """Determine the LAN IP that peers would use to reach this host.

    Connecting a UDP socket sends no traffic but forces the OS to select the
    outbound interface, which is more reliable than resolving the hostname on
    machines with multiple adapters (VPN, WSL, Docker) where the hostname
    frequently maps to a loopback or virtual address remote clients cannot use.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # This address is never contacted; it only selects a route.
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError as e:
        logger.debug(f"Could not detect local IP for mDNS advertisement: {e}")
        return None
    finally:
        sock.close()


async def register_mdns(
    port: int,
    hostname: str = "local-integration",
    service_name: Optional[str] = None,
) -> Tuple[Optional[AsyncZeroconf], list[ServiceInfo]]:
    """
    Register the mDNS services that make the simulator discoverable.

    Publishes both service types a real Deako hub publishes so that Home
    Assistant's discovery flow and pydeako's DeakoDiscoverer both find the
    simulator without any manual IP configuration.

    Args:
        port: Telnet port number the simulator is listening on
        hostname: Base instance name for the advertised services
        service_name: Optional override for the instance name (default: hostname)

    Returns:
        tuple: (AsyncZeroconf instance, list of registered ServiceInfo).
               Returns (None, []) if nothing could be registered.

    Raises:
        None - Failures are logged but not raised (graceful degradation per FR-069)

    Hardware Validation:
        A live scan of two production hubs on 2026-08-11 returned:
            HUB-SERIAL-A._deako._tcp.local.     -> 192.168.86.31:23
            HUB-SERIAL-B._deako._tcp.local.     -> 192.168.86.46:23
            local-integration-3._telnet._tcp.local. -> 192.168.86.31:23
            local-integration-2._telnet._tcp.local. -> 192.168.86.46:23
        Both types resolve to the same host and telnet port, confirming a hub
        advertises the pair rather than either type alone.
    """
    if service_name is None:
        service_name = hostname

    # pydeako builds its connection address from info.addresses; a ServiceInfo
    # registered without addresses yields an empty list there and the discovered
    # hub is silently discarded.
    local_ip = _detect_local_ip()
    addresses = [socket.inet_aton(local_ip)] if local_ip else []

    try:
        zeroconf = AsyncZeroconf()
    except Exception as e:
        # FR-069: Graceful degradation - log warning but don't fail
        logger.warning(
            f"mDNS unavailable: {e}. "
            f"Simulator will still accept direct connections on port {port}."
        )
        return None, []

    registered: list[ServiceInfo] = []

    for service_type in (DEAKO_SERVICE_TYPE, TELNET_SERVICE_TYPE):
        full_service_name = f"{service_name}.{service_type}"
        try:
            info = ServiceInfo(
                type_=service_type,
                name=full_service_name,
                port=port,
                addresses=addresses,
                # No TXT records: real hubs publish none.
                properties={},
                server=f"{service_name}.local.",
            )
            await zeroconf.async_register_service(info)
            registered.append(info)
            logger.info(f"mDNS registered: {full_service_name} on port {port}")

        except Exception as e:
            # One type failing must not stop the other from serving discovery,
            # so each registration is isolated.
            logger.warning(
                f"mDNS registration failed for {full_service_name}: {e}"
            )

    if not registered:
        logger.warning(
            f"No mDNS services registered. "
            f"Simulator will still accept direct connections on port {port}."
        )
        try:
            await zeroconf.async_close()
        except Exception as e:
            logger.debug(f"Error closing zeroconf after failed registration: {e}")
        return None, []

    return zeroconf, registered


async def unregister_mdns(
    zeroconf: Optional[AsyncZeroconf],
    info: Union[ServiceInfo, Sequence[ServiceInfo], None] = None,
) -> None:
    """
    Unregister mDNS services during simulator shutdown.

    Best-effort cleanup - failures are logged but don't prevent shutdown.
    Uses a 2 second total timeout to prevent hanging the shutdown process.

    Args:
        zeroconf: AsyncZeroconf instance from register_mdns()
        info: ServiceInfo or sequence of ServiceInfo from register_mdns().
              A single instance is still accepted so older call sites keep working.

    Returns:
        None

    Raises:
        None - All failures are caught and logged

    Rationale:
        Unregistration is best-effort because the simulator is shutting down
        anyway and mDNS records expire naturally. The 2s cap keeps shutdown
        within the 5s budget required by FR-010.
    """
    if zeroconf is None or info is None:
        # Nothing to unregister (registration failed or not attempted)
        return

    infos = [info] if isinstance(info, ServiceInfo) else list(info)

    if infos:
        try:
            await asyncio.wait_for(
                asyncio.gather(
                    *(zeroconf.async_unregister_service(i) for i in infos)
                ),
                timeout=2.0,
            )
            logger.info(f"mDNS unregistered successfully ({len(infos)} services)")

        except asyncio.TimeoutError:
            logger.warning("mDNS unregistration timed out (2s)")

        except Exception as e:
            logger.warning(f"mDNS unregistration failed: {e}")

    # Always close zeroconf instance
    try:
        await zeroconf.async_close()
    except Exception as e:
        logger.debug(f"Error closing zeroconf: {e}")


# Module-level notes
"""
Implementation Notes:
---------------------
1. Service Types
   - "_deako._tcp.local." is authoritative for discovery. pydeako hardcodes it
     as DEAKO_TYPE in pydeako/discover/_discover.py, and the Home Assistant
     integration manifest lists it under "zeroconf". If the simulator does not
     publish this type, neither Home Assistant nor pydeako can find it.
   - "_telnet._tcp.local." is additionally published by real hubs and is kept
     for fidelity with hardware.
   - An earlier revision registered ONLY "_telnet._tcp.local.", which silently
     defeated auto-discovery; see research/mdns-service-type-test-2026-08-11.md.

2. Graceful Degradation (FR-069):
   - Registration failures don't stop the simulator
   - Simulator still accepts direct IP:port connections
   - Useful when:
     * Firewall blocks mDNS (UDP 5353)
     * Multiple simulators on same network (name conflict)
     * Running in Docker/VM without mDNS support
     * User permissions don't allow mDNS

3. No TXT Records:
   - Real Deako hubs don't publish TXT records
   - Only service name, address and port are advertised

4. Timeout Strategy:
   - Registration: No timeout (fail-fast or succeed)
   - Unregistration: 2s total timeout (best-effort cleanup)
   - Total shutdown budget: 5s (FR-010)

Constitution Compliance:
-----------------------
- Principle I (Hardware Fidelity): Service types match a live hub scan
- Principle II (Simplicity): Minimal implementation, no overengineering
- Principle IV (Test Facility): Graceful degradation for test environments
- Principle V (Readability): Comments explain WHY, not WHAT
- Principle VIII (Error Handling): Explicit exception handling, clear logging
"""
