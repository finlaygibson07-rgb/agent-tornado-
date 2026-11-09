#!/bin/bash
# agent tornado — double-click to start, or run it with a verb.
#
#   ./launch.command            start if needed, open the app, exit
#   ./launch.command stop       stop the bridge
#   ./launch.command status     is it up, and on which pid
#   TORNADO_PORT=8800 ./launch.command
#
# Nothing here stays running. The bridge is handed to its own session, so this
# window — and the Terminal that holds it — can be closed the moment it starts.
# All of that lives in hands.py, because the bridge already owns the port and the
# record of who is on it; this file only finds a python and says which verb.

set -uo pipefail

cd "$(dirname "$0")" || exit 1
PORT="${TORNADO_PORT:-8799}"
ACTION="${1:-start}"

fail() {
  echo
  echo "  agent tornado could not start."
  for line in "$@"; do
    echo "  $line"
  done
  echo
  read -r -p "  press return to close " _ || true
  exit 1
}

[ -f hands.py ] || fail \
  "hands.py is not next to this launcher." \
  "Keep the whole agent-tornado folder together."

# python3 3.9 or newer, stdlib only. Whatever is on PATH first, then the usual
# places, because a double-clicked script gets a thinner PATH than a shell does.
PYTHON=""
for candidate in python3 /usr/bin/python3 /opt/homebrew/bin/python3 /usr/local/bin/python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
      PYTHON="$candidate"
      break
    fi
  fi
done

[ -n "$PYTHON" ] || fail \
  "no python3 3.9 or newer was found." \
  "" \
  "Install Apple's developer tools (which include python3):" \
  "    xcode-select --install" \
  "or get a python from python.org, then double-click this file again."

case "$ACTION" in
  start)
    # --start is idempotent: a second run says "already running" and just brings
    # the window forward, so the port is never contested.
    exec "$PYTHON" hands.py --start --open --port "$PORT"
    ;;
  stop)
    exec "$PYTHON" hands.py --stop --port "$PORT"
    ;;
  status)
    exec "$PYTHON" hands.py --status --port "$PORT"
    ;;
  *)
    fail "unknown command: $ACTION" "Use start, stop, or status."
    ;;
esac
