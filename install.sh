#!/usr/bin/env bash
# bambo-mc installer.
#
# Run from inside the repo:        ./install.sh
# Or the classic one-liner shape:  curl https://example/install.sh | bash
#
# What it does: detects the app, analyses this machine, ensures the server jar is
# present (downloading+verifying it if not), installs a global 'bambo' command, then
# launches ONLY the admin dashboard. It never starts the game server, so you can stop
# it for testing and installing won't bring it back.
#
#   ./install.sh              user-local: ~/.local/share/bambo-mc symlink + ~/.local/bin
#   sudo ./install.sh --system  system-wide: /opt + /usr/local/bin (needs root)
#   ./install.sh --prefix=DIR   custom command dir
#   ./install.sh --uninstall    remove wrappers we created
#   ./install.sh --no-launch    install but do not open the dashboard
#   ./install.sh --jar          force (re)download the server jar
set -uo pipefail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-}")" 2>/dev/null && pwd || echo "")"
REPO=""; PREFIX=""; SYSTEM=0; UNINSTALL=0; LAUNCH=1; FORCEJAR=0; CHECK=0

# ---- locate the app folder (works run-from-repo AND via 'curl | bash') ----
locate_repo() {
  [ -n "${BAMBO_REPO:-}" ] && { echo "$BAMBO_REPO"; return 0; }
  [ -n "$SELF_DIR" ] && [ -x "$SELF_DIR/bambo" ] && { echo "$SELF_DIR"; return 0; }
  [ -x "./bambo" ] && [ -d "./runtime" ] && { (cd . && pwd); return 0; }
  for c in "$HOME/bambo-mc" "$PWD/bambo-mc" /opt/bambo-mc; do
    [ -x "$c/bambo" ] && { echo "$c"; return 0; }; done
  return 1
}

usage(){ sed -n '2,20p' "$0" 2>/dev/null | sed 's/^# \{0,1\}//'; }

for a in "$@"; do
  case "$a" in
    --check)    CHECK=1 ;;
    --version)  echo "bambo-mc installer"; exit 0 ;;
    --system)   SYSTEM=1 ;;
    --uninstall) UNINSTALL=1 ;;
    --no-launch) LAUNCH=0 ;;
    --jar)      FORCEJAR=1 ;;
    --prefix=*) PREFIX="${a#*=}" ;;
    -h|--help)  usage; exit 0 ;;
    *) printf 'bambo install: unknown option %s\n\n' "$a"; usage; exit 2 ;;
  esac
done

if [ "$SYSTEM" = 1 ]; then BIN="${PREFIX:-/usr/local/bin}"; else BIN="${PREFIX:-${XDG_BIN_HOME:-$HOME/.local/bin}}"; fi
CMDS=(bambo bambo-mc bambo-dash bambo-nettest)

# ---- spinner (ASCII, safe under any locale; only animates on a real terminal) ----
FRAMES='|/-\'; SPIN_PID=""; MSG=""
_spinner(){ local i=0; while :; do printf '\r\033[1;36m %s\033[0m  %s' "${FRAMES:i%4}" "$MSG"; sleep 0.15; i=$((i+1)); done; }
spin(){ MSG="$1"; if [ -t 1 ]; then _spinner & SPIN_PID=$!; fi; return 0; }
spindown(){ if [ -n "$SPIN_PID" ]; then kill "$SPIN_PID" 2>/dev/null; wait "$SPIN_PID" 2>/dev/null; fi; SPIN_PID=""; if [ -t 1 ]; then printf '\r\033[K'; fi; return 0; }

wrapper_for(){ case "$1" in
  bambo|bambo-mc) printf '#!/usr/bin/env bash\nexec "%s/bambo" "$@"\n' "$REPO";;
  bambo-dash)    printf '#!/usr/bin/env bash\nexec python3 "%s/bin/bambo-dash.py" "$@"\n' "$REPO";;
  bambo-nettest) printf '#!/usr/bin/env bash\nexec "%s/bin/bambo-nettest" "$@"\n' "$REPO";;
esac; }

uninstall(){
  REPO="$(locate_repo 2>/dev/null || true)"
  local removed=0
  for c in "${CMDS[@]}"; do f="$BIN/$c"
    if [ -f "$f" ] && { [ -z "$REPO" ] || grep -q "$REPO" "$f" 2>/dev/null; }; then rm -f "$f"; echo "  removed $f"; removed=1; fi
  done
  [ "$removed" = 1 ] || echo "  nothing to remove in $BIN"
}

banner_done(){
  local tok="$REPO/dash.token" t=""
  [ -f "$tok" ] && t="$(cat "$tok")"
  printf '\n\033[1;32m  ✔ bambo-mc is installed\033[0m\n'
  printf '    app       : %s\n' "$REPO"
  printf '    commands  : %s  (in %s)\n' "${CMDS[*]}" "$BIN"
  printf '    game server: NOT started (start when ready: bambo start)\n'
  if [ "$LAUNCH" = 1 ]; then
    if tmux has-session -t bambo-dash 2>/dev/null; then
      printf '    \033[1mdashboard is up\033[0m at  \033[4mhttp://127.0.0.1:%s\033[0m\n' "${BAMBO_DASH_PORT:-8787}"
      printf '    token: %s\n' "${t:-<open the dashboard; it self-generates at $tok>}"
    else
      printf '    \033[33mdashboard did not start\033[0m - retry with: bambo --dash  (log: /tmp/bambo-install-dash.log)\n'
    fi
  fi
  printf '\n'
}

if [ "$UNINSTALL" = 1 ]; then echo "bambo-mc uninstaller"; uninstall; exit 0; fi

REPO="$(locate_repo)"; REPOrc=$?
[ -f "$REPO/bambo" ] || { printf 'bambo install: app folder not found (tried the script dir, ./ and ~/bambo-mc).\nRun install.sh from inside the repo or set BAMBO_REPO=/path/to/bambo-mc.\n' >&2; exit 1; }

# ---------- phase 1: analyse (fast, shown immediately) ----------
printf '\033[1m  bambo-mc installer\033[0m\n'
. /etc/os-release 2>/dev/null; printf '  system    %s %s\n' "${PRETTY_NAME:-Linux}" "$(uname -m)"
JVM="missing"; if command -v java >/dev/null 2>&1; then JV=$(java -version 2>&1 | head -1 | grep -oE '[0-9]+' | head -1); [ "${JV:-0}" -ge 21 ] && JVM="Java $JV" || JVM="Java $JV (need 21+)"; fi
printf '  java %s  tmux %s  python3 %s\n' "$JVM" "$(command -v tmux >/dev/null && echo yes || echo NO)" "$(command -v python3 >/dev/null && echo yes || echo NO)"

if [ "$CHECK" = 1 ]; then
  printf '  (check mode: no changes made - nothing installed, nothing downloaded)\n'
  exit 0
fi

# ---------- phase 2: do the work behind a spinner ----------
T0=$SECONDS
spin "analysing system and preparing"
sleep 0.6; spindown

# ensure the server jar (the one large resource) - download+verify only if absent
if [ ! -f "$REPO/runtime/powernukkitx.jar" ] || [ "$FORCEJAR" = 1 ]; then
  spin "downloading and verifying the server (this can take a while)"
  "$REPO/bambo" --setup >/tmp/bambo-install-jar.log 2>&1; jar_rc=$?
  spindown
  [ $jar_rc -eq 0 ] || printf '  \033[33m!\033[0m jar setup had issues (see /tmp/bambo-install-jar.log)\n'
else
  spin "server already present, skipping download"; sleep 0.4; spindown
fi

# install the global command wrappers
if ! mkdir -p "$BIN" 2>/dev/null; then
  printf '\n  installing to %s needs root. Re-run:  sudo %s --system\n\n' "$BIN" "$0"; exit 1
fi
spin "installing global commands into $BIN"
for c in "${CMDS[@]}"; do wrapper_for "$c" > "$BIN/$c" && chmod +x "$BIN/$c"; done
sleep 0.5; spindown

# PATH hint
if ! printf '%s' ":$PATH:" | grep -q ":$BIN:"; then
  printf '  \033[33mnote\033[0m: add to PATH in ~/.bashrc:  export PATH="%s:$PATH"\n' "$BIN"
fi

# launch ONLY the dashboard (never the game server)
if [ "$LAUNCH" = 1 ] && command -v python3 >/dev/null 2>&1; then
  spin "starting the dashboard"
  "$REPO/bambo" --dash start >/tmp/bambo-install-dash.log 2>&1
  sleep 0.5; spindown
elif [ "$LAUNCH" = 1 ]; then
  printf '  \033[33m!\033[0m python3 missing - dashboard not started\n'
fi

# keep the loader at least ~3s for a smooth reveal, then finish
el=$((SECONDS-T0)); [ $el -lt 3 ] && { spin "almost there"; sleep $((3-el)); spindown; }
banner_done
