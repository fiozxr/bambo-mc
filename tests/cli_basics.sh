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
check_contains "$out" "bambo-mc v2.2.0" "version prints tool version"

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
check_contains "$out" '"tool_version":"2.2.0"' "health json carries tool_version"

out="$(BAMBO_ROOT="$FIX" "$ROOT/bambo" bootstrap --dry-run 2>&1)"
check_contains "$out" "(dry-run)" "bootstrap --dry-run previews"

if BAMBO_ROOT="$FIX" "$ROOT/bambo" no-such-command >/dev/null 2>&1; then
  fail "unknown command should exit nonzero"
else
  ok "unknown command exits nonzero"
fi

out="$(BAMBO_ROOT="$FIX" "$ROOT/bambo" config init 2>&1)"
[ -f "$FIX/bambo.conf" ] && ok "config init created bambo.conf" || fail "config init missing"
check_contains "$out" "created" "config init message"

out="$(BAMBO_ROOT="$FIX" "$ROOT/bambo" config set BAMBO_MAX_PLAYERS 6 2>&1)"
check_contains "$out" "BAMBO_MAX_PLAYERS = 6" "config set reports value"
grep -q 'BAMBO_MAX_PLAYERS=6' "$FIX/bambo.conf" && ok "config set wrote conf" || fail "config set did not write conf"

out="$(BAMBO_ROOT="$FIX" "$ROOT/bambo" config apply 2>&1)"
grep -q 'maxPlayers: 6' "$FIX/runtime/pnx.yml" && ok "config apply deployed maxPlayers" || fail "config apply did not deploy"
grep -q 'Maximum number of players' "$FIX/runtime/pnx.yml" && ok "config apply preserved comments" || fail "config apply ate comments"

out="$(BAMBO_ROOT="$FIX" "$ROOT/bambo" config show 2>&1)"
check_contains "$out" "max players" "config show lists entries"

out="$(BAMBO_ROOT="$FIX" "$ROOT/bambo" config wizard --defaults 2>&1)"
grep -q 'BAMBO_SERVER_NAME=' "$FIX/bambo.conf" && ok "config wizard --defaults ran" || fail "config wizard failed"

out="$(BAMBO_ROOT="$FIX" "$ROOT/bambo" motd "Test World" 2>&1)"
grep -q 'BAMBO_SERVER_NAME=Test World' "$FIX/bambo.conf" && ok "motd updated conf" || fail "motd did not update conf"
grep -q 'motd: "Test World"' "$FIX/runtime/pnx.yml" && ok "motd deployed" || fail "motd did not deploy"

out="$(BAMBO_ROOT="$FIX" "$ROOT/bambo" config diff 2>&1)"
check_contains "$out" "maxPlayers" "config diff reports drift"

# backup refuses while nothing to do? run backup on fixture (no worlds -> ok)
out="$(BAMBO_ROOT="$FIX" "$ROOT/bambo" backup 2>&1)"
check_contains "$out" "nothing to back up" "backup handles missing worlds gracefully"

rm -rf "$FIX"
summary
