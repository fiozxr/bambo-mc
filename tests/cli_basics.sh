#!/usr/bin/env bash
# tests/cli_basics.sh - non-live CLI behavior (works against a fixture repo).
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=tests/lib.sh
. "$DIR/lib.sh"

t "cli basics"
FIX="$(make_fixture)"
export BAMBO_ROOT="$FIX"
# Own the session name: otherwise these tests read the operator's live server and fail
# whenever it is running.
export BAMBO_SESSION="bambo-test-$$"

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
# ...and it must refuse BEFORE it stops a running server or takes a backup.
out="$(BAMBO_ROOT="$FIX" "$ROOT/bambo" rollback 99.99.99 2>&1)"
check_contains "$out" "not a release bambo pins" "unknown release is rejected up front"
[ -d "$FIX/runtime/backups" ] && [ -z "$(ls -A "$FIX/runtime/backups" 2>/dev/null)" ] \
  && ok "rejected rollback took no backup" || true

out="$(BAMBO_ROOT="$FIX" "$ROOT/bambo" man 2>&1)"
check_contains "$out" "rollback" "man page documents rollback"

# a fixture with a recorded previous jar: rollback --prev swaps both ways offline.
# Safe to run unconditionally now: BAMBO_SESSION above points these tests at their own
# tmux session, so --prev can no longer reach a live 'bambo-mc' server to stop it.
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

# ---- interactive prompts must not depend on stdin being the terminal ----
# 'curl -fsSL .../install.sh | bash' puts the script on stdin. When the menus checked
# '-t 0' they refused to run during that install, so it finished with NO server jar and
# a dashboard whose Start button could only ever fail.
if command -v setsid >/dev/null 2>&1; then
  out="$(setsid bash -c "BAMBO_ROOT='$FIX' '$ROOT/bambo' rollback" < /dev/null 2>&1)" || rc=1
  case "$out" in *"needs an interactive terminal"*) ok "no terminal at all: menu refuses with guidance" ;;
                 *) fail "no-terminal case did not refuse cleanly: $out" ;; esac
  case "$out" in *"No such device or address"*) fail "the tty probe leaked a bash error to the user" ;;
                *) ok "no leaked /dev/tty error text" ;; esac
else
  echo "  SKIP  no-terminal menu refusal (setsid unavailable)"
fi

# `script` can fail to hand out a pty when the machine is busy (an install downloading
# a jar next door was enough), so retry, and treat "no pty at all" as a skip rather
# than a failure - a test that only fails under load is worse than one that is skipped.
pty_out() {   # pty_out <lines-for-stdin> <command...>
  local inp="$1"; shift; local i out=""
  for i in 1 2 3; do
    out="$(printf '%s\n' "$inp" | script -qec "$*" /dev/null 2>&1)" && [ -n "$out" ] && break
    sleep 0.5
  done
  printf '%s' "$out"
}

if command -v script >/dev/null 2>&1; then
  out="$(pty_out '' "BAMBO_ROOT='$FIX' '$ROOT/bambo' rollback")"
  case "$out" in
    "")                       echo "  SKIP  piped-stdin menu behavior (no pty available)" ;;
    *"needs an interactive terminal"*) fail "menu still refuses when stdin is a pipe but a terminal exists: $(echo "$out" | head -2)" ;;
    *"Roll the server back"*)  ok "menu runs with piped stdin when a terminal exists (curl|bash shape)" ;;
    *)                         fail "unexpected menu output: $(echo "$out" | head -2)" ;;
  esac
else
  echo "  SKIP  piped-stdin menu behavior (script unavailable)"
fi

# ---- the config wizard must not receive its program on stdin ----
# 'python3 - <<HEREDOC' consumed stdin as the script itself, leaving an empty stream for
# the answers, so every question silently took its default.
if grep -q 'python3 - <<.*wizard\|ESX_DEFAULTS="$defaults" python3 - <<' "$ROOT/bambo"; then
  fail "wizard is fed through stdin again - answers would be swallowed"
else
  ok "wizard reads from a file, leaving stdin for the answers"
fi
grep -q 'python3 "$wiz"' "$ROOT/bambo" && ok "wizard program runs from a temp file" \
                                         || fail "wizard no longer runs from a temp file"

# wizard answers actually land, when a pty can be allocated
if command -v script >/dev/null 2>&1; then
  WFIX="$(make_fixture)"
  WANS='PTYTESTNAME\nsub\n9\nfalse\ntrue\n2\n1\n12\nfalse\nfalse\n2048M\n5\n127.0.0.1\n8899\n'
  for i in 1 2 3; do
    printf "$WANS" | script -qec "BAMBO_ROOT='$WFIX' '$ROOT/bambo' config wizard" /dev/null >/dev/null 2>&1
    grep -q 'BAMBO_SERVER_NAME=PTYTESTNAME' "$WFIX/bambo.conf" 2>/dev/null && break
    rm -f "$WFIX/bambo.conf"; sleep 0.5
  done
  if [ ! -s "$WFIX/bambo.conf" ]; then
    echo "  SKIP  wizard answer capture (no pty available)"
  elif grep -q 'BAMBO_MAX_PLAYERS=9' "$WFIX/bambo.conf"; then
    ok "wizard answers are written to bambo.conf"
  else
    fail "wizard ignored the typed answers: $(head -3 "$WFIX/bambo.conf" | tr '\n' ' ')"
  fi
  rm -rf "$WFIX"
fi

# ---- a fresh deployment must not stall on the engine's own first-run wizard ----
# With no runtime/pnx.yml, PowerNukkitX prompts for a language on the console and
# eventually exits without binding the port - and nothing can answer that prompt
# through `bambo start`. start() seeds the tracked template (language: eng) instead.
grep -q 'seeded runtime/pnx.yml' "$ROOT/bambo" \
  && ok "start seeds runtime/pnx.yml before first boot" \
  || fail "start no longer seeds pnx.yml - a wiped install will stall on the wizard"

# ---- the dashboard's release list must agree with the CLI's version table ----
# Two representations of the same fact (bash pnx_facts + Python RELEASES) is a drift
# hazard, so compare what each actually prints rather than trusting a comment.
cli_rel="$(BAMBO_ROOT="$FIX" "$ROOT/bambo" rollback --list 2>&1 \
  | sed -n 's/^  \([0-9][0-9.]*\)  *Bedrock  *\([^ ]*\)  *protocol  *\([^ ]*\).*/\1 \2 \3/p')"
dash_rel="$(python3 - "$ROOT/bin/bambo-dash.py" <<'PY'
import re, sys
src = open(sys.argv[1], encoding="utf-8").read()
blk = re.search(r"RELEASES = \[(.*?)\n\]", src, re.S).group(1)
for tag, proto, client in re.findall(r'\("([\d.]+)", "(\d+)", (?:"([\d.]+)"|None)\)', blk):
    print("%s %s %s" % (tag, client or "unknown", proto))
PY
)"
if [ -n "$cli_rel" ] && [ "$(printf '%s\n' "$cli_rel" | sort)" = "$(printf '%s\n' "$dash_rel" | sort)" ]; then
  ok "dashboard release list matches the CLI version table"
else
  fail "release tables drifted:
   CLI : $(echo "$cli_rel" | tr '\n' ';')
   DASH: $(echo "$dash_rel" | tr '\n' ';')"
fi

# ---- bambo uninstall: surgical, and never near the operator's real crontab ----
UT="$(mktemp -d)"
UA="$UT/app"
mkdir -p "$UA/runtime/worlds" "$UA/logs" "$UA/backups" "$UA/bin"
cp "$ROOT/bambo" "$UA/bambo"; chmod +x "$UA/bambo"
cp "$ROOT/install.sh" "$UA/install.sh"
cp "$ROOT/config.example" "$UA/config.example" 2>/dev/null || true
cp "$ROOT/config.example" "$UA/bambo.conf" 2>/dev/null || echo "BAMBO_MAX_PLAYERS=20" > "$UA/bambo.conf"
echo "t" > "$UA/dash.token"
echo level-data > "$UA/runtime/level-data"
# a crontab stand-in: -l prints the file, stdin installs it
printf '0 4 * * * /usr/bin/unrelated-job\n' > "$UT/crontab-content"
printf '30 3 * * * cd %s && ./bambo stop && ./bambo backup && ./bambo start >> %s/logs/cron-backup.log 2>&1\n' "$UA" "$UA" >> "$UT/crontab-content"
cat > "$UT/fakecrontab" <<'CT'
#!/usr/bin/env bash
if [ "${1:-}" = "-l" ]; then cat "$UT_CRONTAB" 2>/dev/null; exit 0; fi
cat > "$UT_CRONTAB"
CT
chmod +x "$UT/fakecrontab"
# the four wrappers this install made, plus a command that belongs to someone else
for c in bambo bambo-mc bambo-dash bambo-nettest; do
  printf '#!/usr/bin/env bash\nexec "%s/bambo" "$@"\n' "$UA" > "$UA/bin/$c"; chmod +x "$UA/bin/$c"
done
printf '#!/usr/bin/env bash\nexec /opt/other/keep-me\n' > "$UA/bin/other-tool"
chmod +x "$UA/bin/other-tool"

run_uninstall() {
  BAMBO_ROOT="$UA" BAMBO_SESSION="bambo-ut-$$" BAMBO_DASH_SESSION="bambo-utd-$$" \
  BAMBO_CRONTAB_BIN="$UT/fakecrontab" UT_CRONTAB="$UT/crontab-content" \
    "$ROOT/bambo" uninstall "$@" --prefix="$UA/bin"
}

# the confirmation gate must be reachable without a terminal; setsid removes the
# controlling tty so this cannot block waiting on whoever is running the suite
if command -v setsid >/dev/null 2>&1; then
  out="$(setsid bash -c "UT_CRONTAB='$UT/crontab-content' BAMBO_ROOT='$UA' BAMBO_SESSION='bambo-ut-$$' BAMBO_DASH_SESSION='bambo-utd-$$' BAMBO_CRONTAB_BIN='$UT/fakecrontab' '$ROOT/bambo' uninstall --prefix='$UA/bin'" < /dev/null 2>&1)"
  check_contains "$out" "pass --yes" "uninstall asks before removing anything"
  [ -f "$UA/bin/bambo" ] && ok "a refused uninstall removes no wrappers" || fail "refused uninstall still removed wrappers"
  grep -q 'bambo backup' "$UT/crontab-content" && ok "a refused uninstall leaves the crontab alone" \
                                                || fail "refused uninstall edited the crontab"
else
  echo "  SKIP  uninstall confirmation path (setsid unavailable)"
fi

out="$(run_uninstall --yes 2>&1)"
[ ! -e "$UA/bin/bambo" ] && ok "uninstall removes this install's wrappers" || fail "our wrapper survived uninstall"
[ -f "$UA/bin/other-tool" ] && ok "an unrelated command in the same dir is left alone" \
                             || fail "uninstall deleted a command that was not ours"
grep -q unrelated-job "$UT/crontab-content" && ok "unrelated crontab entries survive" \
                                             || fail "uninstall destroyed someone else's cron job"
grep -q 'bambo backup' "$UT/crontab-content" && fail "the nightly backup job was left behind" \
                                             || ok "uninstall removes the nightly backup job"
ls "$UA"/backups/crontab.backup.pre-uninstall-* >/dev/null 2>&1 \
  && ok "the previous crontab is kept so this is undoable" || fail "no crontab backup was written"
[ -f "$UA/runtime/level-data" ] && ok "worlds and backups survive by default" \
                                || fail "uninstall deleted data without --purge"
[ -s "$UA/bambo.conf" ] && ok "bambo.conf survives by default" || fail "uninstall deleted bambo.conf without --purge"

out="$(run_uninstall --yes --purge 2>&1)"
[ ! -e "$UA/runtime" ] && ok "--purge deletes runtime data" || fail "--purge left runtime in place"
[ ! -e "$UA/bambo.conf" ] && ok "--purge deletes bambo.conf" || fail "--purge kept bambo.conf"
[ ! -e "$UA/dash.token" ] && ok "--purge deletes the dashboard token" || fail "--purge kept dash.token"
[ -f "$UA/bambo.conf" ] && ok "bambo.conf survives the non-purge run" || true
[ -f "$UA/bambo" ] && ok "the app folder and its git history are never deleted" \
                    || fail "--purge deleted the app folder itself"

# --purge must refuse a directory that is not a bambo-mc root
NB="$(mktemp -d)"; mkdir -p "$NB/runtime" "$NB/bin"; echo precious > "$NB/runtime/precious"
out="$(BAMBO_ROOT="$NB" BAMBO_SESSION="bambo-nb-$$" BAMBO_DASH_SESSION="bambo-nbd-$$" \
        BAMBO_CRONTAB_BIN="$UT/fakecrontab" UT_CRONTAB="$UT/crontab-content" \
        "$ROOT/bambo" uninstall --yes --purge --prefix="$NB/bin" 2>&1)"
check_contains "$out" "does not look like a bambo-mc root" "purge refuses a directory that is not the app"
[ -f "$NB/runtime/precious" ] && ok "bystander data in an unrelated runtime dir survives" \
                               || fail "purge deleted an unrelated runtime directory"
rm -rf "$UT" "$NB"

summary

