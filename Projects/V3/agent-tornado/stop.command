#!/bin/bash
# agent tornado — double-click to stop the bridge.
#
# This is the one obvious way out: the app window closing does not stop the
# bridge (it outlives windows on purpose), so stopping is a deliberate act.
# It is a wrapper rather than a second implementation — launch.command owns the
# python lookup and hands.py owns the shutdown — and it only adds the pause, so
# that a double-click shows you the result instead of closing instantly.

set -uo pipefail

cd "$(dirname "$0")" || exit 1

./launch.command stop
code=$?

echo
read -r -p "  press return to close " _ || true
exit "$code"
