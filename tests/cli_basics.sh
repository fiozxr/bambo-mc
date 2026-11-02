#!/usr/bin/env bash
# tests/cli_basics.sh - non-live CLI behavior (works against a fixture repo).
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=tests/lib.sh
. "$DIR/lib.sh"

t "cli basics"
FIX="$(make_fixture)"
export BAMBO_ROOT="$FIX"

out="$(BAMBO_ROOT="$FIX" "$ROOT/bambo" version 2>&1)"
check_contains "$out" "bambo-mc v2.0.0" "version prints tool version"

out="$(BAMBO_ROOT="$FIX" "$ROOT/bambo" help 2>&1)"
check_contains "$out" "bambo" "help runs"
check_contains "$out" "doctor" "help lists doctor"
check_contains "$out" "config" "help lists config"

out="$(BAMBO_ROOT="$FIX" "$ROOT/bambo" man 2>&1)"
check_contains "$out" "BAMBO(1)" "man page renders"

out="$(BAMBO_ROOT="$FIX" "$ROOT/bambo" status 2>&1)"
check_contains "$out" "STOPPED" "status shows stopped (fixture)"
check_contains "$out" "dash" "status shows dash"

out="$(BAMBO_ROOT="$FIX" "$ROOT/bambo" health --json 2>&1)"
echo "$out" | python3 -m json.tool >/dev/null 2>&1 && ok "health --json is valid JSON" || fail "health --json invalid"
check_contains "$out" '"tool_version":"2.0.0"' "health json carries tool_version"

if BAMBO_ROOT="$FIX" "$ROOT/bambo" no-such-command >/dev/null 2>&1; then
  fail "unknown command should exit nonzero"
else
  ok "unknown command exits nonzero"
fi

out="$(BAMBO_ROOT="$FIX" "$ROOT/bambo" config get motd 2>&1)"
check_contains "$out" "motd:" "config get motd works"

out="$(BAMBO_ROOT="$FIX" "$ROOT/bambo" config set maxPlayers 6 2>&1)"
check_contains "$out" "maxPlayers = 6" "config set maxPlayers works"
grep -q 'maxPlayers: 6' "$FIX/runtime/pnx.yml" && ok "config set wrote file" || fail "config set did not write"
grep -q 'Maximum number of players' "$FIX/runtime/pnx.yml" && ok "config set preserved comments" || fail "config set ate comments"

out="$(BAMBO_ROOT="$FIX" "$ROOT/bambo" config set motd "Hello World" 2>&1)"
grep -q 'motd: "Hello World"' "$FIX/runtime/pnx.yml" && ok "config set quotes values with spaces" || fail "config set quoting wrong"

# config diff between fixture live and template (they were identical before edits)
out="$(BAMBO_ROOT="$FIX" "$ROOT/bambo" config diff 2>&1)"
check_contains "$out" "maxPlayers" "config diff reports drift"

# backup refuses while nothing to do? run backup on fixture (no worlds -> ok)
out="$(BAMBO_ROOT="$FIX" "$ROOT/bambo" backup 2>&1)"
check_contains "$out" "nothing to back up" "backup handles missing worlds gracefully"

rm -rf "$FIX"
summary
