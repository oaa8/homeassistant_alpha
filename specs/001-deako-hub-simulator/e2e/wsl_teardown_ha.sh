#!/bin/bash
# Tear down the throwaway HA test instance.
pkill -f "ha-venv/bin/hass" 2>/dev/null && echo "stopped hass" || echo "hass not running"
sleep 2
rm -rf "$HOME/ha-test" "$HOME/ha-venv" "$HOME/ha-e2e"
echo "removed throwaway HA instance, venvs and config (including its credentials)"
