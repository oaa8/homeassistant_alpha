#!/usr/bin/env bash
# Port preconditions for the WSL end-to-end harnesses. Sourced, not run.
#
# Why this exists (wayfinder #24). wsl_validate_setup_rebuild.sh pointed its
# "unreachable address" check at 127.0.0.1:8099 as a port nothing serves. On
# 2026-08-15 that was untrue: a concurrent session had a simulator bound to
# 8099 on the Windows side, and WSL's mirrored networking makes Windows'
# loopback reachable from inside WSL. The check connected to an aiohttp server,
# got `HTTP/1.0 400 Bad Request`, and so the integration's
# `Cannot reach the Deako switch` never fired -- setup failed later at the
# device-list timeout instead, leaving the entry in `setup_retry` and turning
# the assertion green while it was measuring "connects to something that is not
# a Deako hub". Same commit, 26/28 with the port occupied and 28/28 with it
# free.
#
# Three rules follow, and every function here exists to serve one of them.
#
#   1. Probe, do not read the socket table. `ss -ltnp` inside WSL cannot see a
#      Windows-side listener through mirrored networking -- the occupant above
#      was invisible to `ss` and showed up only on a raw connect. Any port
#      diagnostic that reads the socket table will confidently say "nothing is
#      there".
#   2. Relocate, then refuse. Sessions on this map run concurrently by design,
#      so aborting on the first busy port would only invert the collision. Try
#      several candidates, take the first where nothing answers, and abort only
#      if something answers on all of them -- naming what answered.
#   3. Prove the precondition rather than assume it. A port that stands for
#      "nothing is here", and a port a harness is about to bind, are both
#      claims about the machine, and both are cheap to measure.
#
# What the probe can and cannot tell you here. #24 asked for a connection
# *refused*, which is the textbook proof that nothing is listening. Measured on
# this rig, that proof is not available: from inside WSL a free loopback port in
# this range never refuses -- 8097 and 8098 were still silent after 12s with no
# RST -- while Windows itself refuses the same ports in ~2s. Mirrored
# networking swallows the reset. An occupied port, Windows-side or Linux-side,
# answers in ~0.03s either way. So the discriminator that actually exists is
# **did anything answer**, and a silent port is as dead as this environment can
# demonstrate. That is weaker than a refusal, which is why the assertions that
# depend on a dead port are also coupled to the log line they expect rather
# than resting on the probe alone.

# How long to wait for an answer. An occupant answers in milliseconds; the wait
# is really the price of confirming silence, paid once per candidate port.
PORT_PROBE_TIMEOUT_S="${PORT_PROBE_TIMEOUT_S:-2}"

# port_state <host> <port> [timeout_s]
# Echoes open | refused | silent | error:<class>. `open` is the only answer
# that means something is there; `refused` and `silent` both mean nothing
# answered, and are reported apart because the difference says which side of
# the WSL boundary the port lives on.
port_state() {
    python3 - "$1" "$2" "${3:-$PORT_PROBE_TIMEOUT_S}" <<'PY'
import socket
import sys

host, port, timeout = sys.argv[1], int(sys.argv[2]), float(sys.argv[3])
sock = socket.socket()
sock.settimeout(timeout)
try:
    sock.connect((host, port))
    print("open")
except ConnectionRefusedError:
    print("refused")
except (socket.timeout, TimeoutError):
    print("silent")
except OSError as exc:
    print(f"error:{type(exc).__name__}")
finally:
    sock.close()
PY
}

# port_answers <host> <port> [timeout_s]
# True when something is on the port. An error that is neither a refusal nor a
# timeout counts as "something", because an unexplained result is not proof of
# an empty port.
port_answers() {
    case "$(port_state "$1" "$2" "${3:-$PORT_PROBE_TIMEOUT_S}")" in
        refused | silent) return 1 ;;
        *) return 0 ;;
    esac
}

# port_occupant <host> <port>
# One line describing whatever answered, so a refusal to run says what it found
# rather than just that it found something. Waits for a banner first -- the
# Deako protocol and this repo's simulator say nothing until spoken to, so an
# HTTP request is sent as a second attempt to make the occupant identify
# itself. That request is what finally identified #24's occupant.
port_occupant() {
    python3 - "$1" "$2" <<'PY'
import socket
import sys


def read_some(sock, timeout):
    sock.settimeout(timeout)
    try:
        return sock.recv(256)
    except OSError:
        return b""


host, port = sys.argv[1], int(sys.argv[2])
sock = socket.socket()
sock.settimeout(2)
try:
    sock.connect((host, port))
except OSError as exc:
    print(f"nothing answered ({type(exc).__name__})")
    raise SystemExit

banner = read_some(sock, 1.0)
if not banner:
    try:
        sock.sendall(b"GET / HTTP/1.0\r\n\r\n")
    except OSError:
        pass
    else:
        banner = read_some(sock, 2.0)
sock.close()

lines = [line for line in banner.decode("utf-8", "replace").splitlines() if line.strip()]
print(lines[0].strip()[:120] if lines else "accepted the connection and said nothing")
PY
}

# first_silent_port <host> <label> <candidate>...
# Echoes the first candidate where nothing answers. Every candidate that is
# occupied is reported to stderr as it is skipped, so a run that had to
# relocate says so. Returns 1, with what answered, when every candidate is
# taken -- there is no safe way to continue, because the point of the port is
# that nothing is on it.
first_silent_port() {
    local host="$1" label="$2" port state
    shift 2
    for port in "$@"; do
        state=$(port_state "$host" "$port")
        case "$state" in
            refused | silent)
                echo "$port"
                return 0
                ;;
        esac
        echo "  $label: $host:$port is $state -- $(port_occupant "$host" "$port")" >&2
    done
    echo "  $label: something answered on every candidate ($(echo "$*" | tr ' ' ','))." >&2
    echo "  Refusing to run: a port has to be measured empty before a check can rest" >&2
    echo "  on it, and a listener on the Windows side is invisible to ss(8) here." >&2
    return 1
}

# describe_port <host> <port>
# The measured state, plus whatever answered when something did. For
# assertions that report the precondition they measured instead of assuming it
# held.
describe_port() {
    local state
    state=$(port_state "$1" "$2")
    case "$state" in
        refused | silent) echo "$state (nothing answered)" ;;
        *) echo "$state -- $(port_occupant "$1" "$2")" ;;
    esac
}
