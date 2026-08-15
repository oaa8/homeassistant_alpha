"""
Deako Hub Simulator - HTTP API

Author: GitHub Copilot
Created: 2025-10-28
Last Modified: 2025-10-28

Purpose:
    HTTP API for runtime device management and scenario control.
    Provides REST endpoints for:
    - Device queries and state updates
    - Physical button simulation
    - Scenario activation
    - Runtime configuration

Key Assumptions:
    - HTTP API shares SimulatorState with telnet server (single source of truth)
    - State updates via HTTP broadcast EVENTs to telnet clients
    - AppRunner pattern for concurrent server operation per research.md
    - JSON request/response format for all endpoints

Related Research:
    - research.md decision 7: AppRunner pattern for concurrent servers
    - FR-042: Scenario activation atomically replaces devices
    - FR-076: Physical button simulation via HTTP API
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import logging
from typing import Optional

import time
from aiohttp import web
from aiohttp.web import Application, Request, Response, AppRunner, TCPSite, StreamResponse

from deako_simulator.state import SimulatorState
from deako_simulator.config import Config
from deako_simulator.protocol import create_event
from deako_simulator.quirks import QuirkManager

logger = logging.getLogger("deako_simulator.http")

# AppKey for storing shared state per research.md pattern
STATE_KEY = web.AppKey("simulator_state", SimulatorState)
CONFIG_KEY = web.AppKey("simulator_config", Config)
QUIRK_KEY = web.AppKey("quirk_manager", QuirkManager)  # T071: For connection resilience control


def create_http_app(state: SimulatorState, config: Config, quirk_manager: QuirkManager) -> Application:
    """
    Create HTTP API application with routes and shared state.
    
    Args:
        state: SimulatorState instance shared with telnet server
        config: Configuration with scenarios
        quirk_manager: QuirkManager for connection resilience control (T071)
        
    Returns:
        aiohttp Application with routes registered
        
    Routes:
        GET /api/devices - List all devices
        GET /api/devices/{uuid} - Get single device
        POST /api/devices/{uuid}/state - Update device state
        POST /api/devices/{uuid}/button - Simulate physical button
        GET /api/scenarios - List available scenarios
        POST /api/scenarios/{name}/activate - Activate scenario
        POST /api/control/disconnect - Disconnect active connection (T071)
        POST /api/control/refuse-connections - Enable/disable connection refusal (T071)
        POST /api/control/latency - Set connection latency (T071)
        POST /api/control/withhold - Withhold devices from enumeration (#16)
        POST /api/control/deliver/{uuid} - Deliver a withheld device late (#16)
    """
    # Order matters: logging_middleware runs first (outermost), then error_middleware
    app = Application(middlewares=[logging_middleware, error_middleware])
    
    # Store shared state in app (per research.md decision 7)
    app[STATE_KEY] = state
    app[CONFIG_KEY] = config
    app[QUIRK_KEY] = quirk_manager  # T071: Store quirk manager for control endpoints
    
    # Register routes
    app.add_routes([
        web.get('/api/devices', list_devices),
        web.get('/api/devices/{uuid}', get_device),
        web.post('/api/devices/{uuid}/state', update_device_state),
        web.post('/api/devices/{uuid}/button', simulate_button_press),
        web.get('/api/scenarios', list_scenarios),
        web.post('/api/scenarios/{name}/activate', activate_scenario),
        # T071: Connection resilience control endpoints
        web.post('/api/control/disconnect', disconnect_active_connection),
        web.post('/api/control/refuse-connections', set_refuse_connections),
        web.post('/api/control/latency', set_connection_latency),
        # wayfinder #16 (O10): enumeration shortfall and late arrival
        web.post('/api/control/withhold', set_withheld_devices),
        web.post('/api/control/deliver/{uuid}', deliver_device_late),
    ])
    
    logger.info("HTTP API application created with 11 routes")
    return app


RequestHandler = Callable[[Request], Awaitable[StreamResponse]]


@web.middleware
async def logging_middleware(request: Request, handler: RequestHandler) -> StreamResponse:
    """
    Middleware for comprehensive HTTP request/response logging per FR-049.
    
    Logs all HTTP requests with:
    - Method (GET, POST, etc.)
    - Endpoint (path)
    - Client IP address
    - Component tag "http"
    
    Logs all HTTP responses with:
    - Status code
    - Response time (milliseconds)
    
    This middleware runs BEFORE error_middleware to ensure all requests
    are logged even if they result in errors.
    """
    start_time = time.time()
    client_ip = request.remote
    method = request.method
    path = request.path
    
    # Log incoming request per FR-049
    logger.info(f"[http] {method} {path} from {client_ip}")
    
    # Process request
    try:
        response = await handler(request)
        status = response.status
    except web.HTTPException as e:
        # HTTP exceptions (redirects, errors) have status codes
        status = e.status
        raise
    except Exception:
        # Unexpected errors will be handled by error_middleware
        # Log as 500 and re-raise
        status = 500
        raise
    finally:
        # Always log response (even on error) per FR-049
        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(f"[http] {status} {method} {path} - {elapsed_ms:.1f}ms")
    
    return response


@web.middleware
async def error_middleware(request: Request, handler: RequestHandler) -> StreamResponse:
    """
    Middleware for consistent JSON error responses.
    
    Catches exceptions and returns proper HTTP error codes with JSON body.
    
    Exception handling strategy (Principle VIII):
    - web.HTTPException: Re-raise (already formatted properly)
    - KeyError: 404 Not Found (device/scenario doesn't exist)
    - ValueError: 400 Bad Request (invalid input)
    - Exception: 500 Internal Error (unexpected, logged for debugging)
    
    Justification for catch-all Exception handler:
    Per Constitution Principle VIII, catch-all handlers require justification.
    This middleware is the HTTP API error boundary - it MUST catch all exceptions
    to prevent aiohttp from returning HTML error pages instead of JSON responses.
    All exceptions are logged with full traceback for debugging. This is the ONLY
    acceptable use of catch-all in this codebase per architecture decision.
    """
    try:
        return await handler(request)
    except web.HTTPException:
        # Re-raise HTTP exceptions (they're already formatted)
        raise
    except KeyError as e:
        # Device or scenario not found
        logger.warning(f"Resource not found: {e}")
        return web.json_response(
            {"error": "not_found", "message": str(e)},
            status=404
        )
    except ValueError as e:
        # Invalid input
        logger.warning(f"Invalid request: {e}")
        return web.json_response(
            {"error": "invalid_request", "message": str(e)},
            status=400
        )
    except Exception as e:
        # Unexpected error
        # NOTE: This is the ONLY catch-all in codebase. Justified because:
        # 1. This is the HTTP API error boundary
        # 2. Must return JSON (not HTML) for all errors
        # 3. Exception details logged with full traceback
        # 4. Prevents aiohttp default HTML error pages
        logger.exception(f"Unexpected error in HTTP handler: {e}")
        return web.json_response(
            {"error": "internal_error", "message": "An unexpected error occurred"},
            status=500
        )


async def list_devices(request: Request) -> Response:
    """
    GET /api/devices - List all devices.
    
    Returns:
        JSON array of devices with uuid, name, capabilities, state
        
    Example response:
        [
            {
                "uuid": "11111111-1111-4111-8111-111111111111",
                "name": "Kitchen Light",
                "capabilities": ["power", "dim"],
                "state": {"power": true, "dim": 50}
            },
            ...
        ]
    """
    state = request.app[STATE_KEY]
    
    devices = state.get_all_devices()
    response_data = [
        {
            "uuid": device.uuid,
            "name": device.name,
            "capabilities": device.capabilities,
            "state": {
                "power": device.state.power,
                "dim": device.state.dim
            }
        }
        for device in devices
    ]
    
    return web.json_response(response_data)


async def get_device(request: Request) -> Response:
    """
    GET /api/devices/{uuid} - Get single device.
    
    Args:
        uuid: Device UUID from path parameter
        
    Returns:
        JSON object with device details
        
    Raises:
        404: Device not found
        
    Example response:
        {
            "uuid": "11111111-1111-4111-8111-111111111111",
            "name": "Kitchen Light",
            "capabilities": ["power", "dim"],
            "state": {"power": true, "dim": 50}
        }
    """
    state = request.app[STATE_KEY]
    uuid = request.match_info['uuid']
    
    device = state.get_device(uuid)
    if device is None:
        raise web.HTTPNotFound(
            text='{"error": "not_found", "message": "Device not found"}',
            content_type='application/json'
        )
    
    response_data = {
        "uuid": device.uuid,
        "name": device.name,
        "capabilities": device.capabilities,
        "state": {
            "power": device.state.power,
            "dim": device.state.dim
        }
    }
    
    return web.json_response(response_data)


async def update_device_state(request: Request) -> Response:
    """
    POST /api/devices/{uuid}/state - Update device state.
    
    Args:
        uuid: Device UUID from path parameter
        
    Request body:
        {
            "power": true,    // Optional: new power state
            "dim": 50         // Optional: new dim level (0-100)
        }
        
    Returns:
        JSON object with updated device state
        
    Side effects:
        - Broadcasts EVENT to all telnet clients per FR-075
        
    Raises:
        404: Device not found
        400: Invalid request body
        
    Example response:
        {
            "uuid": "11111111-1111-4111-8111-111111111111",
            "state": {"power": true, "dim": 50}
        }
    """
    state = request.app[STATE_KEY]
    uuid = request.match_info['uuid']
    
    # Parse request body
    try:
        data = await request.json()
    except Exception as e:
        raise web.HTTPBadRequest(
            text='{"error": "invalid_json", "message": "Request body must be valid JSON"}',
            content_type='application/json'
        )
    
    # Log configuration change per FR-049
    logger.info(f"[http] Configuration change: updating device {uuid} state: {data}")
    
    # Check device exists
    device = state.get_device(uuid)
    if device is None:
        raise web.HTTPNotFound(
            text='{"error": "not_found", "message": "Device not found"}',
            content_type='application/json'
        )
    
    # Update device state
    power = data.get('power')
    dim = data.get('dim')
    
    updated_device = state.update_device_state(uuid, power=power, dim=dim)
    
    # Broadcast EVENT to telnet clients (FR-075: full state, not deltas)
    event = create_event(
        device_uuid=updated_device.uuid,
        state={
            "power": updated_device.state.power,
            "dim": updated_device.state.dim
        },
        timestamp=int(time.time() * 1000)
    )
    await state.broadcast_event(event)
    
    response_data = {
        "uuid": updated_device.uuid,
        "state": {
            "power": updated_device.state.power,
            "dim": updated_device.state.dim
        }
    }
    
    return web.json_response(response_data)


async def simulate_button_press(request: Request) -> Response:
    """
    POST /api/devices/{uuid}/button - Simulate physical button press.
    
    Implements FR-076: Physical button simulation
    - Toggles device power (false→true, true→false)
    - Dim level unchanged
    - Broadcasts EVENT immediately with full state
    - No conflicts with CONTROL commands
    
    Args:
        uuid: Device UUID from path parameter
        
    Returns:
        JSON object with updated device state
        
    Side effects:
        - Toggles device power state
        - Broadcasts EVENT to all telnet clients
        
    Raises:
        404: Device not found
        
    Research reference: research/physical-button-behavior-test-2025-10-18.md
    - Validated: toggle behavior, full state in EVENT
    - Validated: no conflicts with CONTROL commands
    - Validated: minimum ~430ms between physical button presses
    
    Example response:
        {
            "uuid": "11111111-1111-4111-8111-111111111111",
            "state": {"power": false, "dim": 50}
        }
    """
    state = request.app[STATE_KEY]
    uuid = request.match_info['uuid']
    
    # Check device exists
    device = state.get_device(uuid)
    if device is None:
        raise web.HTTPNotFound(
            text='{"error": "not_found", "message": "Device not found"}',
            content_type='application/json'
        )
    
    # Toggle power (FR-076: true→false, false→true)
    new_power = not device.state.power
    
    # Log configuration change per FR-049
    logger.info(f"[http] Configuration change: simulating button press on device {uuid} (power: {device.state.power} → {new_power})")
    
    # Update state, keeping dim unchanged
    updated_device = state.update_device_state(uuid, power=new_power, dim=None)
    
    # Broadcast EVENT immediately with full state (FR-076)
    # Per research/physical-button-behavior-test-2025-10-18.md:
    # Physical button EVENTs are immediate, no 2s delay like CONTROL
    event = create_event(
        device_uuid=updated_device.uuid,
        state={
            "power": updated_device.state.power,
            "dim": updated_device.state.dim
        },
        timestamp=int(time.time() * 1000)
    )
    await state.broadcast_event(event)
    
    response_data = {
        "uuid": updated_device.uuid,
        "state": {
            "power": updated_device.state.power,
            "dim": updated_device.state.dim
        }
    }
    
    return web.json_response(response_data)


async def list_scenarios(request: Request) -> Response:
    """
    GET /api/scenarios - List available scenarios.
    
    Returns:
        JSON array of scenarios with name and description
        
    Example response:
        [
            {
                "name": "evening_mode",
                "description": "Evening lighting: dim lights to 30%"
            },
            ...
        ]
    """
    config = request.app[CONFIG_KEY]
    
    scenarios = [
        {
            "name": scenario.name,
            "description": scenario.description
        }
        for scenario in config.scenarios
    ]
    
    return web.json_response(scenarios)


async def activate_scenario(request: Request) -> Response:
    """
    POST /api/scenarios/{name}/activate - Activate named scenario.
    
    Implements FR-042: Scenario activation
    - Atomically replaces all device states
    - Telnet connections remain active (do not disconnect)
    - Broadcasts DEVICE_STATE_CHANGE EVENTs for changed devices
    - Returns count of devices updated
    
    Per spec.md clarifications 2025-10-25:
    - Clients must re-query DEVICE_LIST to discover new device topology
    - Scenario activation does not automatically push device list to clients
    
    Args:
        name: Scenario name from path parameter
        
    Returns:
        JSON object with count of devices updated
        
    Side effects:
        - Updates all device states atomically
        - Broadcasts EVENTs for state changes
        - Telnet connections remain active
        
    Raises:
        404: Scenario not found
        
    Example response:
        {
            "scenario": "evening_mode",
            "devices_updated": 3
        }
    """
    state = request.app[STATE_KEY]
    config = request.app[CONFIG_KEY]
    scenario_name = request.match_info['name']
    
    # Find scenario
    scenario = next(
        (s for s in config.scenarios if s.name == scenario_name),
        None
    )
    
    if scenario is None:
        raise web.HTTPNotFound(
            text='{"error": "not_found", "message": "Scenario not found"}',
            content_type='application/json'
        )
    
    # Log configuration change per FR-049
    logger.info(f"[http] Configuration change: activating scenario '{scenario_name}'")
    
    # Atomically update all device states per FR-042
    devices_updated = 0
    for device_uuid, new_state in scenario.device_states.items():
        try:
            updated_device = state.update_device_state(
                device_uuid,
                power=new_state.power,
                dim=new_state.dim
            )
            devices_updated += 1
            
            # Broadcast EVENT for each device state change
            event = create_event(
                device_uuid=updated_device.uuid,
                state={
                    "power": updated_device.state.power,
                    "dim": updated_device.state.dim
                },
                timestamp=int(time.time() * 1000)
            )
            await state.broadcast_event(event)
            
        except KeyError:
            # Device in scenario doesn't exist - log warning and continue
            logger.warning(
                f"Scenario '{scenario_name}' references unknown device {device_uuid} - skipping"
            )
    
    logger.info(f"[http] Configuration change: scenario '{scenario_name}' activated - {devices_updated} devices updated")
    
    response_data = {
        "scenario": scenario_name,
        "devices_updated": devices_updated
    }
    
    # Note per spec.md clarifications 2025-10-25:
    # Clients must re-query DEVICE_LIST to discover new device topology.
    # Scenario activation does not automatically push device list to clients.
    
    return web.json_response(response_data)


async def disconnect_active_connection(request: Request) -> Response:
    """
    POST /api/control/disconnect - Forcibly disconnect active telnet connection.
    
    Purpose: Test integration reconnection logic and error handling per T071.
    Simulates network failure or hub restart scenario.
    
    Request: Empty body
    Response: {"status": "ok", "disconnected": true/false}
    
    User Story 7: Connection resilience testing
    Research: Connection lifecycle test validates disconnection behavior
    
    Expected: Connection closed immediately
    Actual: QuirkManager.simulate_connection_failure() closes writer
    Impact: Integration must detect disconnection and attempt reconnection
    """
    quirk_manager = request.app[QUIRK_KEY]
    
    # Simulate connection failure (forcibly close active connection)
    success = await quirk_manager.simulate_connection_failure()
    
    logger.info(f"[http] Control operation: disconnect active connection - success={success}")
    
    return web.json_response({
        "status": "ok",
        "disconnected": success
    })


async def set_refuse_connections(request: Request) -> Response:
    """
    POST /api/control/refuse-connections - Enable/disable connection refusal.
    
    Purpose: Test integration behavior when hub refuses connections per T071.
    Simulates hub being busy, overloaded, or in maintenance mode.
    
    Request: {"refuse": true/false}
    Response: {"status": "ok", "refuse_connections": true/false}
    
    User Story 7: Connection resilience testing
    
    Expected: New connections refused (closed immediately) if enabled
    Actual: QuirkManager.set_connection_refusal() updates configuration
    Impact: Integration must handle connection refused gracefully
    """
    quirk_manager = request.app[QUIRK_KEY]
    
    try:
        data = await request.json()
        refuse = data.get("refuse", False)
        
        if not isinstance(refuse, bool):
            return web.json_response(
                {"error": "refuse must be boolean"},
                status=400
            )
        
        quirk_manager.set_connection_refusal(refuse)
        
        logger.info(f"[http] Control operation: refuse_connections={refuse}")
        
        return web.json_response({
            "status": "ok",
            "refuse_connections": refuse
        })
        
    except (ValueError, KeyError) as e:
        return web.json_response(
            {"error": f"Invalid request: {e}"},
            status=400
        )


async def set_connection_latency(request: Request) -> Response:
    """
    POST /api/control/latency - Set artificial connection latency (high latency simulation).
    
    Purpose: Test integration behavior under high latency network conditions per T071.
    Simulates slow network, satellite connection, or congested network.
    
    Request: {"delay_seconds": 0.0-10.0}
    Response: {"status": "ok", "connection_delay": <seconds>}
    
    User Story 7: Connection resilience testing
    
    Expected: Delay applied before processing any message on new connections
    Actual: QuirkManager.set_connection_delay() updates configuration
    Impact: Integration must handle slow responses without timing out
    """
    quirk_manager = request.app[QUIRK_KEY]
    
    try:
        data = await request.json()
        delay_seconds = data.get("delay_seconds", 0.0)
        
        if not isinstance(delay_seconds, (int, float)):
            return web.json_response(
                {"error": "delay_seconds must be a number"},
                status=400
            )
        
        if delay_seconds < 0 or delay_seconds > 10:
            return web.json_response(
                {"error": "delay_seconds must be between 0 and 10"},
                status=400
            )
        
        quirk_manager.set_connection_delay(float(delay_seconds))
        
        logger.info(f"[http] Control operation: connection_delay={delay_seconds}s")
        
        return web.json_response({
            "status": "ok",
            "connection_delay": delay_seconds
        })
        
    except (ValueError, KeyError) as e:
        return web.json_response(
            {"error": f"Invalid request: {e}"},
            status=400
        )


async def set_withheld_devices(request: Request) -> Response:
    """
    POST /api/control/withhold - Hold devices back from the DEVICE_FOUND stream.

    Request: {"uuids": ["<uuid>", ...]}  (an empty list clears withholding)
    Response: {"status": "ok", "withheld": ["<uuid>", ...]}

    Purpose (wayfinder #16, outcome O10): produce an enumeration shortfall.
    DEVICE_LIST still reports the full count; the withheld devices simply never
    announce themselves, so the client is told to expect N and receives N-1.

    This injects a missing message and nothing else. How the real hub reports a
    switch that is registered but unreachable is an open question (wayfinder
    #13) and is not being guessed at here.
    """
    state = request.app[STATE_KEY]
    quirk_manager = request.app[QUIRK_KEY]

    try:
        data = await request.json()
    except (ValueError, KeyError) as e:
        return web.json_response({"error": f"Invalid request: {e}"}, status=400)

    uuids = data.get("uuids", [])
    if not isinstance(uuids, list) or not all(isinstance(u, str) for u in uuids):
        return web.json_response(
            {"error": "uuids must be a list of strings"},
            status=400
        )

    unknown = [u for u in uuids if state.get_device(u) is None]
    if unknown:
        return web.json_response(
            {"error": "not_found", "message": f"Unknown devices: {unknown}"},
            status=404
        )

    quirk_manager.set_withheld_devices(set(uuids))

    logger.info(f"[http] Control operation: withhold devices {sorted(uuids)}")

    return web.json_response({"status": "ok", "withheld": sorted(uuids)})


async def deliver_device_late(request: Request) -> Response:
    """
    POST /api/control/deliver/{uuid} - Announce a withheld device right now.

    Response: {"status": "ok", "delivered": true, "was_withheld": true/false}

    Purpose (wayfinder #16, outcome O10): the late DEVICE_FOUND. A device that
    missed enumeration reports on its own, without the client asking again, and
    the entity that was showing unavailable has to come back to life.

    Stops withholding the device and writes a DEVICE_FOUND for it to the active
    connection, in the same shape the enumeration stream uses.
    """
    from deako_simulator.protocol import create_device_found, format_response

    state = request.app[STATE_KEY]
    quirk_manager = request.app[QUIRK_KEY]
    uuid = request.match_info['uuid']

    device = state.get_device(uuid)
    if device is None:
        raise web.HTTPNotFound(
            text='{"error": "not_found", "message": "Device not found"}',
            content_type='application/json'
        )

    was_withheld = quirk_manager.release_device(uuid)

    writer = state.active_connection
    if writer is None or writer.is_closing():
        return web.json_response({
            "status": "ok",
            "delivered": False,
            "was_withheld": was_withheld,
            "message": "no active connection to deliver on",
        })

    line = format_response(create_device_found(device))
    logger.info(f"[http] Control operation: late DEVICE_FOUND for {uuid}")
    writer.write(line.encode('utf-8'))
    await writer.drain()

    return web.json_response({
        "status": "ok",
        "delivered": True,
        "was_withheld": was_withheld,
    })


async def start_http_api(
    state: SimulatorState,
    config: Config,
    quirk_manager: QuirkManager,
    host: str,
    port: int
) -> AppRunner:
    """
    Start HTTP API server using AppRunner pattern.
    
    Per research.md decision 7: Use AppRunner for manual lifecycle control.
    This allows running HTTP server alongside telnet server in same event loop.
    
    Args:
        state: SimulatorState shared with telnet server
        config: Configuration with scenarios
        quirk_manager: QuirkManager for connection resilience control (T071)
        host: Bind address (e.g., "0.0.0.0" or "127.0.0.1")
        port: HTTP server port (e.g., 8080)
        
    Returns:
        AppRunner instance (caller must call runner.cleanup() on shutdown)
        
    Example usage:
        runner = await start_http_api(state, config, quirk_manager, "0.0.0.0", 8080)
        # ... server runs ...
        await runner.cleanup()  # On shutdown
    """
    app = create_http_app(state, config, quirk_manager)
    runner = AppRunner(app)
    await runner.setup()
    
    site = TCPSite(runner, host, port)
    await site.start()
    
    # Get actual bound port (useful when port=0 for dynamic allocation)
    actual_port = site._server.sockets[0].getsockname()[1]
    logger.info(f"HTTP API server started on {host}:{actual_port}")
    
    return runner
