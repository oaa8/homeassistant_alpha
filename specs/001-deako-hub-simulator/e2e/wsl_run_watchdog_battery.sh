#!/usr/bin/env bash
# Run the watchdog reconnect battery (wayfinder #19).
#
# WHY WSL AND NOT WINDOWS: pydeako's _SocketConnection.connect_socket passes the
# port to sock_connect as a *str*. getaddrinfo tolerates that on POSIX; on
# Windows it raises and no connection is ever made. True of stock 0.3.1, stock
# 0.6.0, and the vendored copy alike.
#
# With --simulator the whole thing stays on loopback and advertises no mDNS, so
# the real house cannot be reached or confused by it. Without it, every argument
# is passed straight through, and the target address is whatever you supply --
# nothing about any installation is baked in here.
#
# Usage (inside WSL):
#   bash specs/001-deako-hub-simulator/e2e/wsl_run_watchdog_battery.sh --simulator \
#       --probe-device 'Test 1' --phases pong enumerate blackhole
#   bash specs/001-deako-hub-simulator/e2e/wsl_run_watchdog_battery.sh \
#       --host <addr> --wait-for-node 1800 --log ~/wf19.log

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
WORK_DIR="${BATTERY_WORK_DIR:-$HOME/deviation-checks}"

mkdir -p "$WORK_DIR"

if [ ! -x "$WORK_DIR/venv/bin/python" ]; then
    echo "== Creating virtualenv in $WORK_DIR/venv"
    python3 -m venv "$WORK_DIR/venv"
fi
"$WORK_DIR/venv/bin/pip" -q install aiohttp zeroconf jsonschema

cd "$REPO_ROOT"
exec "$WORK_DIR/venv/bin/python" tools/deako_watchdog_battery.py "$@"
