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
#   ./install.sh --auto         automatic setup: ensure deps (apt/dnf/zypper/pacman),
#                               jar, token, nightly backup cron, wrappers, dashboard
#   ./install.sh --auto --start   also start the game server after installing
#   ./install.sh --auto --dry-run preview everything --auto would do (changes nothing)
#   ./install.sh --auto --ask (default when interactive; --no-ask to disable)
#   ./install.sh --auto --ask  prompt: match installed client version, or install latest
set -uo pipefail

# shellcheck disable=SC1003,SC2016
# - SC1003: the spinner frame string contains a backslash intentionally.
# - SC2016: the PATH hint is printed literally for the user (single quotes intentional).

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-}")" 2>/dev/null && pwd || echo "")"
REPO=""; PREFIX=""; SYSTEM=0; UNINSTALL=0; LAUNCH=1; FORCEJAR=0; CHECK=0; AUTO=0; START=0; DRYRUN=0; ASK=0; ASKOFF=0

# ---- locate the app folder (works run-from-repo AND via 'curl | bash') ----
locate_repo() {
  [ -n "${BAMBO_REPO:-}" ] && { echo "$BAMBO_REPO"; return 0; }
  [ -n "$SELF_DIR" ] && [ -x "$SELF_DIR/bambo" ] && { echo "$SELF_DIR"; return 0; }
  [ -x "./bambo" ] && { [ -d "./runtime" ] || [ -f "./config.example" ]; } && { (cd . && pwd); return 0; }
  for c in "$HOME/bambo-mc" "$PWD/bambo-mc" /opt/bambo-mc; do
    [ -x "$c/bambo" ] && { echo "$c"; return 0; }; done
  return 1
}

usage(){ sed -n '2,20p' "$0" 2>/dev/null | sed 's/^# \{0,1\}//'; }

# ---- --auto helpers: make the machine ready end-to-end ----
ensure_deps() {
  local missing="" tool
  for tool in java tmux python3 curl ip; do
    command -v "$tool" >/dev/null 2>&1 || missing="$missing $tool"
  done
  if [ -z "$missing" ]; then
    printf '  deps: all required tools present\n'
    return 0
  fi
  printf '  deps: missing:%s\n' "$missing"
  if [ "$DRYRUN" = 1 ]; then
    printf '    (dry-run) would install them via the system package manager\n'
    return 0
  fi
  local pm=""
  command -v apt-get >/dev/null 2>&1 && pm=apt
  command -v dnf >/dev/null 2>&1 && pm=dnf
  command -v zypper >/dev/null 2>&1 && pm=zypper
  command -v pacman >/dev/null 2>&1 && pm=pacman
  if [ -z "$pm" ]; then
    printf '  deps: no supported package manager found; install manually:%s\n' "$missing" >&2
    return 1
  fi
  local sudoer=""
  if [ "$(id -u)" != 0 ]; then
    if command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
      sudoer="sudo -n"
    else
      printf '  deps: need root to install packages - re-run with sudo or as root\n' >&2
      return 1
    fi
  fi
  case "$pm" in
    apt)     $sudoer apt-get update -qq || true
             $sudoer apt-get install -y --no-install-recommends \
               openjdk-21-jre-headless tmux python3 curl iproute2 ;;
    dnf)    $sudoer dnf install -y java-21-openjdk-headless tmux python3 curl iproute ;;
    zypper) $sudoer zypper install -y java-21-openjdk-headless tmux python3 curl iproute2 ;;
    pacman) $sudoer pacman -S --noconfirm jre21-openjdk-headless tmux python3 curl iproute2 ;;
  esac
  local bad=""
  for tool in java tmux python3 curl ip; do
    command -v "$tool" >/dev/null 2>&1 || bad="$bad $tool"
  done
  if [ -n "$bad" ]; then
    printf '  deps: still missing after install:%s\n' "$bad" >&2
    return 1
  fi
  printf '  deps: installed OK\n'
}

ensure_cron() {
  command -v crontab >/dev/null 2>&1 || { printf '  cron: crontab unavailable - skipping nightly backup job\n'; return 0; }
  local line="30 3 * * * cd \"$REPO\" && ./bambo stop && ./bambo backup && ./bambo start >> \"$REPO/logs/cron-backup.log\" 2>&1"
  if crontab -l 2>/dev/null | grep -qF "bambo backup"; then
    printf '  cron: nightly backup job already installed\n'
    return 0
  fi
  printf '  cron: adding nightly backup job\n'
  if [ "$DRYRUN" = 1 ]; then
    printf '    (dry-run) would append: %s\n' "$line"
    return 0
  fi
  mkdir -p "$REPO/backups" "$REPO/logs"
  local stamp; stamp="$(date +%Y%m%d-%H%M%S)"
  crontab -l 2>/dev/null > "$REPO/backups/crontab.backup.$stamp" || true
  { crontab -l 2>/dev/null; echo "$line"; } | crontab -
  printf '    previous crontab saved to backups/crontab.backup.%s\n' "$stamp"
}

ensure_token() {
  if [ -f "$REPO/dash.token" ]; then
    printf '  token: present (perms %s)\n' "$(stat -c %a "$REPO/dash.token")"
    return 0
  fi
  printf '  token: generating\n'
  if [ "$DRYRUN" = 1 ]; then
    printf '    (dry-run) would generate dash.token\n'
    return 0
  fi
  (cd "$REPO" && env -u BAMBO_ROOT ./bambo dash token-new) >/dev/null 2>&1 \
    && printf '    dash.token created\n' \
    || printf '    (token generation deferred to dashboard first run)\n'
}

for a in "$@"; do
  case "$a" in
    --check)    CHECK=1 ;;
    --auto)     AUTO=1 ;;
    --start)    START=1 ;;
    --dry-run)  DRYRUN=1 ;;
--ask)      ASK=1 ;;
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

REPO="$(locate_repo)"
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

# --auto: make the machine ready end-to-end (deps, cron, token)
if [ "$AUTO" = 1 ]; then
  ensure_deps || exit 2
  ensure_cron
  ensure_token
  # make sure a user configuration exists (created from config.example if missing)
  if [ ! -f "$REPO/bambo.conf" ]; then
    cp "$REPO/config.example" "$REPO/bambo.conf" 2>/dev/null && chmod 600 "$REPO/bambo.conf" || true
    [ -f "$REPO/bambo.conf" ] && printf '  config: created bambo.conf (edit it, then: bambo config apply)\n'
  fi
fi

# --dry-run: stop before anything mutates the system
if [ "$DRYRUN" = 1 ]; then
  printf '\n  (dry-run) stopping before any changes - nothing was installed or modified\n'
  exit 0
fi

# ensure the server jar (the one large resource) - download+verify only if absent
EASK=""
if [ "${ASK:-0}" = 1 ] || { [ "${ASKOFF:-0}" != 1 ] && [ -t 1 ]; }; then
  EASK=1
else
  EASK=0
fi
if [ ! -f "$REPO/runtime/powernukkitx.jar" ] || [ "$FORCEJAR" = 1 ]; then
  spin "downloading and verifying the server (this can take a while)"
  "$REPO/bambo" --setup${EASK:+ --ask} >/tmp/bambo-install-jar.log 2>&1; jar_rc=$?
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
if [ "$AUTO" = 1 ] && [ "$EASK" = 1 ]; then
  printf '\n  Setting up configuration (press Enter to accept defaults)...\n'
  (cd "$REPO" && ./bambo config wizard --apply) || true
fi

if [ "$START" = 1 ]; then
  echo "  starting services (server + dashboard)..."
  (cd "$REPO" && ./bambo up)
fi
