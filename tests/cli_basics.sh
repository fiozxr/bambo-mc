#!/usr/bin/env bash
# tests/cli_basics.sh - non-live CLI behavior (works against a fixture repo).
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=tests/lib.sh
. "$DIR/lib.sh"

t "cli basics"
FIX="$(make_fixture)"
export BAMBO_ROOT="$FIX"

# the declared version, not a hard-coded one: the assertions below still prove the
# CLI reports it consistently, but a release bump no longer needs test edits.
TV="$(sed -n 's/^BAMBO_VERSION="\{0,1\}\([^"]*\)"\{0,1\}$/\1/p' "$ROOT/bambo" | head -1)"
[ -n "$TV" ] && ok "version is declared in bambo ($TV)" || fail "could not read BAMBO_VERSION from $ROOT/bambo"

DASH_TV="$(sed -n 's/^TOOL_VERSION = "\{0,1\}\([^"]*\)"\{0,1\}$/\1/p' "$ROOT/bin/bambo-dash.py" | head -1)"
[ "$DASH_TV" = "$TV" ] && ok "dashboard version matches the CLI ($DASH_TV)" \
                       || fail "dashboard says $DASH_TV but CLI says $TV - bump them together"

out="$(BAMBO_ROOT="$FIX" "$ROOT/bambo" version 2>&1)"
check_contains "$out" "bambo-mc v$TV" "version prints tool version"

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
check_contains "$out" '"tool_version":"'"$TV"'"' "health json carries tool_version"

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
[ "$(stat -c %a "$FIX/bambo.conf")" = "600" ] && ok "bambo.conf perms 600" || fail "bambo.conf perms not 600"

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

# ---- worlds ----
out="$(BAMBO_ROOT="$FIX" "$ROOT/bambo" world list 2>&1)"
check_contains "$out" "world" "world list works"

out="$(BAMBO_ROOT="$FIX" "$ROOT/bambo" world create test1 2>&1)"
[ -d "$FIX/runtime/worlds/test1" ] && ok "world create copied template" || fail "world create failed: $out"

out="$(BAMBO_ROOT="$FIX" "$ROOT/bambo" world create test3 2>&1)"
[ -d "$FIX/runtime/worlds/test3" ] && ok "second world created" || fail "second world create failed: $out"

out="$(BAMBO_ROOT="$FIX" "$ROOT/bambo" world rename test1 test2 2>&1)"
[ -d "$FIX/runtime/worlds/test2" ] && [ ! -d "$FIX/runtime/worlds/test1" ] && ok "world rename works" || fail "world rename failed: $out"

out="$(BAMBO_ROOT="$FIX" "$ROOT/bambo" world default test3 2>&1)"
grep -q 'defaultLevelName: test3' "$FIX/runtime/pnx.yml" && ok "world default updates pnx" || fail "world default failed: $out"

out="$(BAMBO_ROOT="$FIX" "$ROOT/bambo" world delete test2 2>&1)"
[ -d "$FIX/runtime/.trash/worlds" ] && [ ! -d "$FIX/runtime/worlds/test2" ] && ok "world delete moved to trash" || fail "world delete failed: $out"

if BAMBO_ROOT="$FIX" "$ROOT/bambo" world delete test3 >/dev/null 2>&1; then
  fail "deleting default world should be refused"
else
  ok "deleting default world is refused"
fi

# ---- user/utilities guard when server is down ----
if BAMBO_ROOT="$FIX" "$ROOT/bambo" user ban someone >/dev/null 2>&1; then
  fail "user command should require a running server"
else
  ok "user commands guard when server down"
fi
if BAMBO_ROOT="$FIX" "$ROOT/bambo" plugins >/dev/null 2>&1; then
  fail "plugins should require a running server"
else
  ok "plugins guards when server down"
fi

# ---- invented features ----
out="$(BAMBO_ROOT="$FIX" BAMBO_UPDATE_OFFLINE=1 "$ROOT/bambo" update check 2>&1)"
check_contains "$out" "installed:" "update check runs offline"

out="$(BAMBO_ROOT="$FIX" "$ROOT/bambo" maintenance status 2>&1)"
check_contains "$out" "auto-restart" "maintenance status works"

out="$(BAMBO_ROOT="$FIX" "$ROOT/bambo" audit 2>&1)"
check_contains "$out" "no audit log" "audit viewer handles absence"

out="$(BAMBO_ROOT="$FIX" "$ROOT/bambo" docs runbook 2>&1)"
check_contains "$out" "# Runbook" "docs runbook opens"

out="$(BAMBO_ROOT="$FIX" "$ROOT/bambo" user info Steve 2>&1)"
check_contains "$out" "player: Steve" "user info runs"
check_contains "$out" "operator: no" "user info defaults"

out="$(BAMBO_ROOT="$FIX" "$ROOT/bambo" world trash restore test2 2>&1)"
[ -d "$FIX/runtime/worlds/test2" ] && ok "world trash restore works" || fail "world trash restore failed: $out"

if BAMBO_ROOT="$FIX" "$ROOT/bambo" world trash purge nope >/dev/null 2>&1; then
  fail "purge unknown should fail"
else
  ok "purge guards unknown"
fi

# backup snapshots the fixture world now
out="$(BAMBO_ROOT="$FIX" "$ROOT/bambo" backup 2>&1)"
check_contains "$out" "snapshot" "backup snapshots fixture worlds"

# ---- setup --ask guard ----
if BAMBO_ROOT="$FIX" "$ROOT/bambo" setup --ask </dev/null >/dev/null 2>&1; then
  fail "setup --ask should require an interactive terminal"
else
  ok "setup --ask guards non-interactive"
fi

# ---- rollback: must be reachable, and must swap jars AND facts both ways ----
out="$(BAMBO_ROOT="$FIX" "$ROOT/bambo" rollback --list 2>&1)"
check_contains "$out" "known releases" "rollback --list is dispatchable"
check_contains "$out" "current" "rollback --list shows the current jar"

if BAMBO_ROOT="$FIX" "$ROOT/bambo" rollback 99.99.99 >/dev/null 2>&1; then
  fail "rollback to an unknown version should fail"
else
  ok "rollback rejects an unknown version"
fi

out="$(BAMBO_ROOT="$FIX" "$ROOT/bambo" man 2>&1)"
check_contains "$out" "rollback" "man page documents rollback"

# a fixture with a recorded previous jar: rollback --prev swaps both ways offline.
# Skipped when the real server is up: the tmux session name is fixed, so --prev
# would stop and restart the actual 'bambo-mc' session rather than the fixture.
if command -v tmux >/dev/null 2>&1 && tmux has-session -t bambo-mc 2>/dev/null; then
  echo "  SKIP  rollback --prev swap tests (live 'bambo-mc' session; --prev would stop it)"
else
RB_FIX="$(make_fixture)"
mkdir -p "$RB_FIX/runtime"
echo NEWJAR > "$RB_FIX/runtime/powernukkitx.jar"
echo OLDJAR > "$RB_FIX/runtime/powernukkitx.jar.prev"
cat > "$RB_FIX/runtime/bambo.state.json" <<'EOF'
{"tag":"3.0.6","sha256":"aaa","size":"8","protocol":"2225","client_version":"1.26.60",
 "prev_tag":"3.0.5","prev_sha256":"bbb","prev_size":"8","prev_protocol":"2193","prev_client_version":"1.26.50"}
EOF
out="$(BAMBO_ROOT="$RB_FIX" "$ROOT/bambo" rollback --prev 2>&1)"
check_contains "$out" "PNX 3.0.5" "rollback --prev reports the version it restored"
check "$(cat "$RB_FIX/runtime/powernukkitx.jar")" "OLDJAR" "rollback --prev installs the previous jar"
check "$(cat "$RB_FIX/runtime/powernukkitx.jar.prev")" "NEWJAR" "rollback --prev keeps the outgoing jar for undo"
out="$(BAMBO_ROOT="$RB_FIX" "$ROOT/bambo" version 2>&1)"
check_contains "$out" "PNX 3.0.5" "state follows the jar (tag)"
check_contains "$out" "protocol 2193" "state follows the jar (protocol)"
out="$(BAMBO_ROOT="$RB_FIX" "$ROOT/bambo" rollback --prev 2>&1)"
check_contains "$out" "PNX 3.0.6" "rollback --prev is repeatable (toggles back)"
check "$(cat "$RB_FIX/runtime/powernukkitx.jar")" "NEWJAR" "second --prev restores the newer jar"

# --prev must refuse when the previous jar has no recorded version
NOFACT="$(make_fixture)"
mkdir -p "$NOFACT/runtime"
echo CUR > "$NOFACT/runtime/powernukkitx.jar"
echo ORPHAN > "$NOFACT/runtime/powernukkitx.jar.prev"
cat > "$NOFACT/runtime/bambo.state.json" <<'EOF'
{"tag":"3.0.6","sha256":"aaa","size":"4","protocol":"2225","client_version":"1.26.60"}
EOF
out="$(BAMBO_ROOT="$NOFACT" "$ROOT/bambo" rollback --prev 2>&1)"
check_contains "$out" "no recorded version" "rollback --prev refuses an unrecorded previous jar"
check "$(cat "$NOFACT/runtime/powernukkitx.jar")" "CUR" "refused rollback leaves the jar untouched"
fi

summary

