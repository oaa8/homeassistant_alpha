#!/bin/bash
# Tear down the latest-HA test instance and its Python toolchain.
pkill -f "ha-venv-latest/bin/hass" 2>/dev/null && echo "stopped hass" || echo "hass not running"
sleep 3
rm -rf "$HOME/ha-test-latest" "$HOME/ha-venv-latest" "$HOME/mdns-check"
echo "removed latest-HA instance, venv and credentials"
