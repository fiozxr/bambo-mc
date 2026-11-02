#!/usr/bin/env bash
# tests/run.sh - run the non-live test suite.
# Usage: bash tests/run.sh [--live]
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$DIR/.." && pwd)"
export ROOT

LIVE=0
[ "${1:-}" = "--live" ] && LIVE=1

echo "== bambo-mc test suite (root: $ROOT) =="
echo "  command: $0 $*"

bash "$DIR/cli_basics.sh" || R1=1
bash "$DIR/dash_smoke.sh" || R2=1
[ -f "$ROOT/empty-serve/run-tests.sh" ] && bash "$ROOT/empty-serve/run-tests.sh" || R3=1

if [ "$LIVE" = 1 ]; then
  echo
  echo "== live server cycle (this starts and stops the real server) =="
  (cd "$ROOT" && ./bambo doctor) || { echo "doctor failed - aborting live test"; exit 1; }
  (cd "$ROOT" && ./bambo start) || { echo "start failed"; exit 1; }
  sleep 5
  (cd "$ROOT" && ./bambo status) | grep -q RUNNING || { echo "server did not reach RUNNING"; (cd "$ROOT" && ./bambo stop); exit 1; }
  echo "  live: server RUNNING (ok)"
  (cd "$ROOT" && ./bambo stop) || exit 1
  echo "  live: stop OK"
fi

echo
if [ -z "${R1:-}${R2:-}${R3:-}" ]; then
  echo "RESULT: ALL TEST SUITES PASSED"
  exit 0
else
  echo "RESULT: SOME TEST SUITES FAILED"
  exit 1
fi
