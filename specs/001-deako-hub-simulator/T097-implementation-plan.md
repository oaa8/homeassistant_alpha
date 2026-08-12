# T097 Implementation Plan: Home Assistant Integration Testing

**Created**: 2025-11-08  
**Status**: In Progress  
**Estimated Time**: 45-60 minutes

## Objective

Complete T097 by performing ACTUAL Home Assistant UI testing with the Deako simulator. This validates the simulator WORKS end-to-end with a real Home Assistant integration.

## Approach: Docker Container Method

Using official Home Assistant Docker image because:
- Official HA development approach
- Network host mode allows container to access localhost simulator
- Volume mounting for custom component
- Clean, reproducible environment
- No WSL startup issues

## Implementation Steps

### Phase 1: Infrastructure Setup (15-20 min)

1. **Install Docker Desktop for Windows** (10 min + download)
   - Download from docker.com
   - Install and start Docker Desktop
   - Validation: `docker --version` works

2. **Start Deako Simulator on Windows** (1 min)
   - Command: `python -m deako_simulator --config ha_test_config.json`
   - Verify: Telnet port 23, HTTP port 8080, mDNS registered
   - Keep running in background terminal

3. **Create HA Config Directory** (1 min)
   - Create `ha_config/` directory
   - Copy `custom_components/deako/` into `ha_config/custom_components/`
   - This directory will be mounted as volume in container

4. **Run Home Assistant Container** (5 min)
   - Command: `docker run -d --name homeassistant --privileged -v ${PWD}/ha_config:/config --network=host ghcr.io/home-assistant/home-assistant:stable`
   - `--network=host`: Allows container to access localhost:23 simulator
   - `--privileged`: Required for HA to function properly
   - Validation: Container starts, HA accessible at http://localhost:8123

### Phase 2: Home Assistant Setup (10 min)

5. **Complete HA Onboarding** (5 min)
   - Access http://localhost:8123
   - Wait for startup (2-3 min)
   - Create user account
   - Set location
   - Skip analytics

6. **Add Deako Integration** (5 min)
   - Settings → Devices & Services → Add Integration
   - Search for "Deako"
   - Verify auto-discovery finds simulator
   - Complete integration setup

### Phase 3: Test 9 Scenarios (20-30 min)

7. **Scenario 1: Auto-discovery** (2 min)
   - Expected: Integration discovers simulator via mDNS
   - Test: Check integration config shows discovered hub
   - Document: Screenshot of discovery confirmation

8. **Scenario 2: All devices appear** (2 min)
   - Expected: All 3 devices from ha_test_config.json visible
   - Test: Navigate to Devices & Services → Deako → Devices
   - Verify: dining-room-overhead, living-room-overhead, kitchen-overhead
   - Document: Screenshot of device list

9. **Scenario 3: Power on/off** (3 min)
   - Expected: Toggle devices on/off in UI, state changes
   - Test: Toggle each device, check simulator logs for CONTROL/EVENT
   - Test both: power-only and dimmable devices
   - Document: Screenshot of device controls

10. **Scenario 4: Dim level changes** (3 min)
    - Expected: Brightness slider changes dim level
    - Test: Adjust sliders for living-room and kitchen devices
    - Verify: Simulator logs show CONTROL with dim values
    - Document: Screenshot of brightness controls

11. **Scenario 5: State updates from API** (3 min)
    - Expected: External state change reflects in HA UI
    - Test: `curl -X POST http://localhost:8080/api/devices/{uuid}/state -H 'Content-Type: application/json' -d '{"power":true,"dim":75}'`
    - Verify: HA UI updates automatically (EVENT broadcast working)
    - Document: Screenshot of UI update

12. **Scenario 6: Connection recovery** (5 min)
    - Expected: Integration reconnects after simulator restart
    - Test: Stop simulator (Ctrl+C), wait 10s, restart
    - Verify: Integration reconnects, device states persist, controls work
    - Document: HA logs showing reconnection

13. **Scenario 7: Physical button simulation** (3 min)
    - Expected: Physical button press toggles device in HA
    - Test: `curl -X POST http://localhost:8080/api/devices/{uuid}/button`
    - Verify: Device toggles in UI, test multiple presses
    - Document: Screenshot of toggle behavior

### Phase 4: Documentation & Validation (5-10 min)

14. **Document Results** (5 min)
    - Create `validations/validation-T097-{timestamp}-{status}.md`
    - For each scenario: Expected, Actual, Pass/Fail, Screenshots
    - Include simulator logs excerpt showing protocol messages

15. **Mark T097 Complete** (1 min)
    - Only if ALL 9 scenarios pass
    - Update `specs/001-deako-hub-simulator/tasks.md`
    - Change `[ ] T097` to `[X] T097`

16. **Run Validation** (2 min)
    - Use `execute_prompt` with validation prompt
    - Arguments: task_ids=T097, feature_path=specs/001-deako-hub-simulator
    - Do NOT proceed to next task until validation passes

## Critical Rules

⚠️ **DO NOT mark T097 complete until ALL 9 scenarios pass**  
⚠️ **DO NOT proceed to T098 until execute_prompt validation passes**  
⚠️ **This is REAL end-to-end testing, not programmatic validation**

## Success Criteria

- ✅ Simulator discovered via mDNS
- ✅ All devices visible in HA UI
- ✅ Power controls work
- ✅ Dim controls work
- ✅ State updates propagate
- ✅ Connection recovery works
- ✅ Physical button simulation works
- ✅ All interactions logged properly
- ✅ Validation report created with screenshots

## Notes

- Keep simulator running in background terminal during all tests
- Take screenshots of EVERY scenario for documentation
- Check simulator logs frequently to verify protocol messages
- If any scenario fails, debug before proceeding
- Docker container can be stopped with `docker stop homeassistant` and removed with `docker rm homeassistant`

## Current Status

**Next Step**: Install Docker Desktop for Windows
