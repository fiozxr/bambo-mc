#!/usr/bin/env python3
"""bambo-dash - local admin dashboard for the bambo-mc server.

Production hardening (v2):
  * stdlib only; reuses the tested ./bambo CLI for all control; never runs an
    arbitrary command directly.
  * Token: auto-generated atomically (mode 0600) in dash.token, or overridden by
    the BAMBO_DASH_TOKEN environment variable. Rotation via `bambo dash token-new`.
  * Auth: constant-time HMAC compare; per-IP brute-force rate limiting.
  * Audit: every action is appended to logs/dash-audit.log (JSON lines).
  * Requests: logs/dash.log (JSON lines); oversized bodies rejected; security
    headers on every response; graceful shutdown on SIGTERM/SIGINT.
"""
import argparse
import collections
import hmac
import html
import io
import json
import os
import re
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

TOOL_VERSION = "2.8.2"
MAX_BODY = 64 * 1024          # request body cap (bytes)
MAX_ARGS = 8                  # max args in one admin action
MAX_ARG_LEN = 256             # max length of a single arg
FAIL_WINDOW = 60.0            # seconds
FAIL_LIMIT = 10               # failed auth attempts per IP per window
PORT = 19132


def _find_root(start):
    """Locate the repo root (the dir holding ./bambo and runtime/) by walking up."""
    d = os.path.abspath(start)
    while d != os.path.dirname(d):
        if os.path.isdir(os.path.join(d, "runtime")) and os.path.exists(os.path.join(d, "bambo")):
            return d
        d = os.path.dirname(d)
    return os.path.dirname(os.path.abspath(start))


ROOT = _find_root(os.path.dirname(os.path.abspath(__file__)))
BAMBO = os.path.join(ROOT, "bambo")
SESSION = "bambo-mc"
SERVER_LOG = os.path.join(ROOT, "runtime", "logs", "server.log")
BACKUP_DIR = os.path.join(ROOT, "runtime", "backups")
TOKEN_FILE = os.path.join(ROOT, "dash.token")
PNX_YML = os.path.join(ROOT, "runtime", "pnx.yml")
STATE_FILE = os.path.join(ROOT, "runtime", "bambo.state.json")
LOG_DIR = os.path.join(ROOT, "logs")
REQ_LOG = os.path.join(LOG_DIR, "dash.log")
AUDIT_LOG = os.path.join(LOG_DIR, "dash-audit.log")
LISTEN_HOST = "127.0.0.1"   # set from --host in main(); used for the exposure alert

# Fixed power actions (no user args).
ACTIONS = {
    "start":   [BAMBO, "start"],
    "stop":    [BAMBO, "stop"],
    "restart": [BAMBO, "restart"],
    "backup":  [BAMBO, "backup", "--force"],
}

# Admin actions run as: bambo <name> <args...>. The dashboard passes argv (never a shell
# string); bambo itself validates the subcommand and refuses bad input. 'cmd' is the raw
# operator pass-through - that is why every POST here is token-gated.
ADMIN = {"players", "op", "whitelist", "world", "user", "plugins", "broadcast", "tps", "cmd",
         "motd", "config", "restore", "rollback", "update", "maintenance", "setup"}

# These stop the server, tar the worlds or restart the engine; the ~40s restart plus
# a large world copy must not be killed by the read-only 120s timeout mid-transfer.
SLOW = ACTIONS.keys() | {"motd", "world", "config", "restore", "rollback", "update", "setup"}
SLOW_TIMEOUT = 600


# ---------------- token ----------------
def _load_token():
    env = os.environ.get("BAMBO_DASH_TOKEN", "").strip()
    if env:
        return env
    if not os.path.exists(TOKEN_FILE):
        tmp = TOKEN_FILE + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(secrets.token_hex(32) + "\n")
        os.replace(tmp, TOKEN_FILE)
    with io.open(TOKEN_FILE, "r", encoding="utf-8") as f:
        return f.read().strip()


TOKEN = _load_token()
# ---------------- logging ----------------
def _log_line(path, obj):
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with io.open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(obj) + "\n")
    except Exception:
        pass


def log_request(ip, method, path, code, ms):
    _log_line(REQ_LOG, {"ts": time.time(), "ip": ip, "method": method,
                         "path": path, "code": code, "ms": round(ms, 1)})


def log_audit(ip, action, ok, code, detail=""):
    _log_line(AUDIT_LOG, {"ts": time.time(), "ip": ip, "action": action,
                           "ok": ok, "code": code, "detail": detail[:500]})


# ---------------- rate limiting ----------------
_rl_lock = threading.Lock()
_rl_fail = {}  # ip -> list of failure timestamps


def rate_limited(ip):
    now = time.time()
    with _rl_lock:
        stamps = [t for t in _rl_fail.get(ip, []) if now - t < FAIL_WINDOW]
        _rl_fail[ip] = stamps
        if len(stamps) >= FAIL_LIMIT:
            return True
        stamps.append(now)
        _rl_fail[ip] = stamps
        return False


# ---------------- backend helpers ----------------
_cache = {}
_cache_lock = threading.Lock()


def cached(key, ttl, fn):
    """Memoize fn for ttl seconds. The browser polls /api/status every 3s and
    these fields shell out (join/others) or walk the filesystem."""
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
    val = fn()
    with _cache_lock:
        _cache[key] = (now, val)
    return val


def sh(cmd, timeout=120):
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout, cwd=ROOT)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(
            cmd, 124, "", "timed out after %ds (the command was killed mid-run - "
                           "check 'bambo status' and the logs)" % timeout)
    except Exception as e:
        return subprocess.CompletedProcess(cmd, 1, "", str(e))


def running():
    try:
        return subprocess.run(["tmux", "has-session", "-t", SESSION],
                              capture_output=True).returncode == 0
    except OSError:
        return False   # tmux not installed - report stopped instead of failing the whole status


def port_bound():
    return any((":%d" % PORT) in line
               for line in sh(["ss", "-lun"]).stdout.splitlines())


def join_line():
    out = sh([BAMBO, "join"]).stdout
    for l in out.splitlines():
        if "address" in l:
            return l.split("address", 1)[1].strip()
    return "(run bambo join manually)"


MC_COLOR = re.compile(r"§[0-9a-fk-orA-FK-OR]")
ANSI_CSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def log_tail(n=200, max_bytes=256 * 1024):
    """Last n lines of the server log, with colour codes removed.

    Reads backwards from the end: the log grows all day, so slurping the whole
    file on every 3s poll would read megabytes to display two hundred lines.
    """
    if not os.path.exists(SERVER_LOG):
        return "(no log yet)"
    try:
        size = os.path.getsize(SERVER_LOG)
        with open(SERVER_LOG, "rb") as f:
            if size > max_bytes:
                f.seek(size - max_bytes)
                f.readline()          # drop the partial line the seek landed in
            data = f.read(max_bytes)
    except OSError as e:
        return "(cannot read log: %s)" % e
    lines = data.decode("utf-8", "replace").splitlines(True)[-n:]
    # A colour code is § plus its ONE following code character - deleting the
    # letters themselves would eat every e/a/b/r/c in the text.
    return ANSI_CSI.sub("", MC_COLOR.sub("", "".join(lines)))


def backups():
    if not os.path.isdir(BACKUP_DIR):
        return []
    d = sorted(x for x in os.listdir(BACKUP_DIR) if x[:1].isdigit())
    return d[-12:]


def is_server_dir(d):
    """A directory looks like a server if it holds a server binary/jar."""
    if not os.path.isdir(d):
        return False
    try:
        names = os.listdir(d)
    except OSError:
        return False
    return ("bedrock_server" in names or "bedrock_server.exe" in names
            or any(n.endswith(".jar") for n in names))


def other_servers():
    """Read-only discovery of sibling server dirs. Listed, NOT controlled here."""
    found = []
    if os.path.isdir(os.path.join(ROOT, "empty-serve")):
        found.append("~/bambo-mc/empty-serve (dev, source only)")
    root = os.path.expanduser("~/minecraftbe")
    if os.path.isdir(root):
        for name in sorted(os.listdir(root)):
            child = os.path.join(root, name)
            if is_server_dir(child):
                found.append(child.replace(os.path.expanduser("~"), "~"))
    return found


# ---------------- derived server facts (file reads only: no extra subprocess) ----
LOG_LINE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+\[[^\]]*\]\s+([A-Z]+)\s*-\s?(.*)$")
BOOT_DONE = re.compile(r"^Done \((\d+(?:\.\d+)?)s\)")
JOIN = re.compile(r"^(.+?) joined the game$")
LEAVE = re.compile(r"^(.+?) (?:left the game|lost connection)$")
LIST_COUNT = re.compile(r"There are (\d+)/(\d+) players online")

def parse_log(text):
    """Turn the cleaned log tail into entries the page can filter and badge.

    Levels are also returned as a single letter: colour alone is not a status
    signal (SECURITY.md / WCAG), and the letter survives greyscale and CVD.
    """
    out = []
    for line in text.splitlines():
        line = line.rstrip()
        if not line.strip():
            continue
        m = LOG_LINE.match(line.strip())
        if m:
            ts, level, msg = m.group(1), m.group(2), m.group(3)
            out.append({"ts": ts, "level": level, "tag": level[:1], "msg": msg})
        elif out:
            out[-1]["msg"] += " " + line.strip()   # a wrapped line continues the entry
        else:
            out.append({"ts": "", "level": "", "tag": "?", "msg": line.strip()})
    return out


def _epoch(ts):
    try:
        return time.mktime(time.strptime(ts, "%Y-%m-%d %H:%M:%S"))
    except (ValueError, OverflowError):
        return None


def session_facts(entries, running_now):
    """Boot time, uptime, who is online and the last thing the server said.

    Players are replayed from join/leave events after the most recent boot. If the
    log window does not reach back to a boot line the count is unknown (None) - the
    page shows a dash rather than inventing zero.
    """
    last_boot = None
    for i, e in enumerate(entries):
        if BOOT_DONE.match(e["msg"]) or e["msg"].startswith("Opening server on"):
            last_boot = i
    online = None
    boot_ts = None
    if last_boot is not None:
        boot_ts = entries[last_boot]["ts"] or None
        names = set()
        for e in entries[last_boot:]:
            j, l = JOIN.match(e["msg"]), LEAVE.match(e["msg"])
            if j:
                names.add(j.group(1).strip())
            elif l:
                names.discard(l.group(1).strip())
        online = len(names)
        for e in reversed(entries[last_boot:]):   # an explicit `list` is authoritative
            m = LIST_COUNT.search(e["msg"])
            if m:
                online = int(m.group(1))
                break
    if not running_now:
        online = 0 if boot_ts else None
    uptime = None
    if running_now and boot_ts:
        ep = _epoch(boot_ts)
        if ep:
            uptime = max(0, int(time.time() - ep))
    last_msg = entries[-1] if entries else None
    return {
        "boot_ts": boot_ts,
        "uptime_s": uptime,
        "players_online": online,
        "last_ts": last_msg["ts"] if last_msg else None,
        "last_msg": last_msg["msg"] if last_msg else None,
        "errors": sum(1 for e in entries if e["level"] in ("ERROR", "SEVERE", "FATAL")),
        "warns": sum(1 for e in entries if e["level"] == "WARN"),
    }


def server_config():
    """The handful of live pnx.yml settings an operator checks, by flat key."""
    want = {"motd": "name", "sub-motd": "subtitle", "maxPlayers": "max_players",
            "xboxAuth": "xbox_auth", "allowList": "allowlist", "port": "port",
            "defaultLevelName": "default_world", "gamemode": "gamemode",
            "difficulty": "difficulty", "pvp": "pvp"}
    flat = {}
    try:
        with io.open(PNX_YML, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
                    continue
                k, _, v = line.lstrip().partition(":")
                k = k.strip()
                v = v.split("#")[0].strip()
                if k in want and v and k not in flat:
                    flat[k] = v
    except OSError:
        return {}
    out = {}
    for k, name in want.items():
        out[name] = flat.get(k)
    return out


def state_facts():
    try:
        with io.open(STATE_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        return {}
    return {k: d.get(k) for k in ("tag", "protocol", "client_version", "installed_at",
                                  "prev_tag", "prev_client_version")}


# Releases this project knows how to install, with the Bedrock protocol each one
# serves. Mirrors pnx_facts() in the ./bambo CLI - tests/cli_basics.sh asserts the two
# tables list identical tag/protocol/client triples, so they cannot drift apart.
RELEASES = [
    ("3.0.6", "2225", "1.26.60"),
    ("3.0.5", "2193", "1.26.50"),
    ("3.0.4", "2169", "1.26.45"),
    ("3.0.3", "2168", "1.26.44"),
    ("3.0.2", "2168", None),
    ("3.0.1", "1001", None),
    ("3.0.0", "1001", None),
]

def releases(current, prev):
    """The version picker's data: what can be installed, and where each one sits."""
    out = []
    for tag, protocol, client in RELEASES:
        out.append({"tag": tag, "protocol": protocol, "client_version": client,
                    "current": tag == current, "is_previous": tag == prev,
                    "needs_download": tag != current})
    return out


def alerts(health, cfg, st, running, bound, host, backup_list, port):
    """What is wrong, in the order an operator should read it."""
    out = []
    if running and not bound:
        out.append({"level": "critical", "title": "Up, but unreachable",
                    "detail": "The server process is running but nothing is listening on UDP %d, "
                              "so clients cannot connect." % port})
    if st.get("tag") in (None, ""):
        out.append({"level": "critical", "title": "Version not recorded",
                    "detail": "runtime/bambo.state.json has no tag, so join info and "
                              "rollback are unreliable. Re-run bambo setup."})
    if backup_list:
        try:
            newest = time.mktime(time.strptime(backup_list[-1], "%Y%m%d-%H%M%S"))
            age_h = int((time.time() - newest) / 3600)
            if age_h >= 36:
                out.append({"level": "warn", "title": "Backups are stale",
                            "detail": "The newest snapshot is %dh old; the nightly 03:30 job "
                                      "may not be installed or failed." % age_h})
        except (ValueError, OverflowError):
            pass
    else:
        out.append({"level": "warn", "title": "No backups yet",
                    "detail": "Nothing in runtime/backups. Take one before the next world change."})
    if health["errors"]:
        out.append({"level": "warn", "title": "%d errors in the log window" % health["errors"],
                    "detail": "Open the log and filter to E to read them."})
    if host != "127.0.0.1" and cfg.get("xbox_auth") == "false":
        out.append({"level": "warn", "title": "Open auth on an exposed port",
                    "detail": "The dashboard is reachable from the network and Xbox authentication "
                              "is off, so anyone on this LAN can join without an account."})
    if not out:
        out.append({"level": "ok", "title": "Nothing needs attention",
                    "detail": "Port listening, backups recent, no errors in the log window."})
    return out


_hist = collections.deque(maxlen=240)
_hist_lock = threading.Lock()
HIST_STEP = 5.0    # seconds between samples, so the heartbeat axis is time, not polls


def sample_history(online, running_now):
    """Keep the recent shape of the server: up/down and player count.

    In-memory only - it is empty again after a dashboard restart, which the page
    states instead of drawing a misleading flat line.
    """
    now = time.time()
    with _hist_lock:
        if _hist and now - _hist[-1][0] < HIST_STEP:
            return
        _hist.append([int(now), online, 1 if running_now else 0])


def history():
    with _hist_lock:
        return list(_hist)


def status():
    running_now = running()
    bound = port_bound()
    cfg = cached("config", 30.0, server_config)
    st = cached("state", 60.0, state_facts)
    # Not memoized: it is a cheap listdir, and the backup list is exactly what has
    # changed when someone looks at it - a CLI-side `bambo backup` used to stay
    # invisible here for up to 30s, leaving "No backups yet" on screen after a
    # snapshot had already succeeded.
    backups_list = backups()
    health = session_facts(parse_log(log_tail(400)), running_now)
    port = int(cfg.get("port") or PORT)
    sample_history(health["players_online"], running_now)
    return {
        "running": running_now,
        "port_bound": bound,
        "port": port,
        "join": cached("join", 15.0, join_line),
        "join_ip": (cached("join", 15.0, join_line).split() or [""])[0],
        "backups": backups_list,
        "others": cached("others", 60.0, other_servers),
        "config": cfg,
        "version": st,
        "health": health,
        "players": health["players_online"],
        "exposed": LISTEN_HOST if LISTEN_HOST != "127.0.0.1" else None,
        "history": history(),
        "releases": releases(st.get("tag"), st.get("prev_tag")),
        "alerts": alerts(health, cfg, st, running_now, bound, LISTEN_HOST, backups_list, port),
    }


PAGE_CSS_HTML = """<!doctype html>
<html lang=en>
<head>
<meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1">
<meta name=referrer content=no-referrer>
<title>bambo-mc &middot; server room</title>
<style>
/* ============================================================
   bambo-dash "server room" - a NOC console for one Bedrock box.
   Three elevation greys carry depth (no gradient washes); colour is
   reserved for status, and every status also has a letter or word so it
   survives greyscale and colour-vision deficiency. Machine data is
   monospaced with tabular figures so live values cannot jitter.
   ============================================================ */
:root{
  --bg:#0e1116; --panel:#151a21; --raise:#1c222b; --rule:#262e39; --rule2:#333d4a;
  --txt:#d9e1eb; --dim:#8592a3; --faint:#64717f;
  --accent:#46c1d6; --accent-ink:#04121a;
  --ok:#62c98d; --warn:#e0a83f; --crit:#e8635f;
  --sans:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,Ubuntu,Cantarell,"Noto Sans",sans-serif;
  --mono:ui-monospace,"SF Mono","Cascadia Mono","JetBrains Mono",Menlo,Consolas,"DejaVu Sans Mono",monospace;
  --g:14px; --r:6px;
  color-scheme:dark
}
:root[data-theme=light]{
  --bg:#f2f5f7; --panel:#fff; --raise:#eaeef3; --rule:#d8dfe6; --rule2:#c3ccd7;
  --txt:#131a21; --dim:#55616f; --faint:#77838f;
  --accent:#0c7c92; --accent-ink:#ffffff;
  --ok:#1a7a44; --warn:#8a5a00; --crit:#a8291f;
  color-scheme:light
}
*{box-sizing:border-box}
html,body{margin:0;background:var(--bg);color:var(--txt)}
body{font:400 13.5px/1.5 var(--sans);-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}
h1,h2,h3{margin:0;font-weight:600;letter-spacing:-.01em}
a{color:var(--accent)}
button,input,select,textarea{font:inherit;color:var(--txt);background:var(--raise);border:1px solid var(--rule2);
  border-radius:var(--r);padding:6px 10px}
input,select{min-width:0}
button{cursor:pointer;background:var(--panel);border-color:var(--rule2)}
button:hover:not(:disabled){border-color:var(--accent);background:var(--raise)}
button:focus-visible,a:focus-visible,input:focus-visible,select:focus-visible,summary:focus-visible{
  outline:2px solid var(--accent);outline-offset:1px}
button:disabled{opacity:.45;cursor:not-allowed}
button.go{background:var(--accent);color:var(--accent-ink);border-color:transparent;font-weight:600}
button.danger{color:var(--crit)}
.mono{font-family:var(--mono);font-variant-numeric:tabular-nums}
.num{font-family:var(--mono);font-variant-numeric:tabular-nums;letter-spacing:-.02em}
.dim{color:var(--dim)}.faint{color:var(--faint)}
.hidden{display:none!important}

/* ---- shell: left rail + column ---- */
.shell{display:grid;grid-template-columns:186px minmax(0,1fr);min-height:100vh}
.rail{border-right:1px solid var(--rule);padding:16px 14px;display:flex;flex-direction:column;gap:18px;
  position:sticky;top:0;height:100vh}
.mark{display:flex;align-items:center;gap:9px}
.mark .cube{width:22px;height:22px;border:1px solid var(--rule2);border-radius:4px;position:relative;flex:none}
.mark .cube i{position:absolute;inset:4px 4px auto 4px;height:5px;background:var(--accent);border-radius:1px}
.mark b{font-size:14px;letter-spacing:-.015em}
.mark small{display:block;color:var(--faint);font-size:11px;font-family:var(--mono)}
nav{display:flex;flex-direction:column;gap:1px}
nav a{color:var(--dim);text-decoration:none;padding:6px 8px;border-radius:var(--r);font-size:13px;
  border-left:2px solid transparent}
nav a:hover{color:var(--txt);background:var(--panel)}
nav a[aria-current=true]{color:var(--txt);border-left-color:var(--accent);background:var(--panel)}
.railfoot{margin-top:auto;display:flex;flex-direction:column;gap:10px;font-size:12px;color:var(--faint)}
.live{display:flex;align-items:center;gap:7px}
.live .pip{width:7px;height:7px;border-radius:50%;background:var(--ok);flex:none}
.live.stale .pip{background:var(--warn)}
.live.down .pip{background:var(--crit)}
@keyframes breathe{0%,100%{opacity:1}50%{opacity:.35}}
.live .pip.beat{animation:breathe 2.4s ease-in-out infinite}
.col{padding:18px 22px 64px;max-width:1180px}
section{scroll-margin-top:14px;margin-bottom:var(--g)}
section>h2{font-size:13px;color:var(--dim);font-weight:600;margin:0 0 10px;display:flex;align-items:baseline;gap:10px}
section>h2 .n{font-family:var(--mono);font-size:11px;color:var(--faint)}
.panel{background:var(--panel);border:1px solid var(--rule);border-radius:var(--r)}
.pad{padding:12px 14px}
.split{display:grid;grid-template-columns:minmax(0,1.45fr) minmax(0,1fr);gap:var(--g);align-items:start}

/* ---- status strip: the five-second read ---- */
.strip{display:grid;grid-template-columns:minmax(230px,1fr) auto;gap:var(--g);align-items:stretch}
.state{padding:14px 16px;display:flex;flex-direction:column;gap:12px}
.staword{display:flex;align-items:center;gap:11px}
.staword .dot{width:11px;height:11px;border-radius:50%;flex:none;background:var(--faint)}
.staword[data-s=up] .dot{background:var(--ok)}
.staword[data-s=down] .dot{background:var(--crit)}
.staword h1{font-size:26px;font-weight:700;letter-spacing:-.03em;line-height:1}
.staword .why{font-size:12.5px;color:var(--dim);font-weight:400;letter-spacing:0}
.facts{display:flex;flex-wrap:wrap;gap:0 26px;margin:0;padding:0;list-style:none}
.facts li{display:flex;flex-direction:column}
.facts .k{font-size:11px;color:var(--faint)}
.facts .v{font-family:var(--mono);font-variant-numeric:tabular-nums;font-size:15px}
.facts .v.big{font-size:21px;font-weight:600}
.join{border-left:1px solid var(--rule);padding:14px 16px;min-width:250px;display:flex;flex-direction:column;
  gap:9px;justify-content:center;background:var(--raise);border-radius:0 var(--r) var(--r) 0}
.join .addr{font-family:var(--mono);font-size:19px;letter-spacing:-.02em;font-variant-numeric:tabular-nums;
  word-break:break-all;line-height:1.2}
.join .row{display:flex;gap:8px;align-items:center;justify-content:space-between}
.acts{display:flex;gap:8px;flex-wrap:wrap}
/* ---- heartbeat: the one memorable element ---- */
.heart{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:var(--g);align-items:center;padding:10px 14px}
.heart svg{display:block;width:100%;height:46px}
.heart .axis{font-family:var(--mono);font-size:11px;color:var(--faint);white-space:nowrap}
/* ---- alerts ---- */
.alerts{display:flex;flex-direction:column;gap:1px}
.alert{display:grid;grid-template-columns:22px minmax(0,1fr);gap:10px;padding:9px 12px;align-items:start;
  border-top:1px solid var(--rule)}
.alert:first-child{border-top:0}
.alert .b{font-family:var(--mono);font-size:11px;font-weight:700;width:20px;height:20px;border-radius:4px;
  display:grid;place-items:center;background:var(--raise);color:var(--dim)}
.alert.critical .b{color:var(--crit);border:1px solid var(--crit)}
.alert.warn .b{color:var(--warn);border:1px solid var(--warn)}
.alert.ok .b{color:var(--ok);border:1px solid var(--rule2)}
.alert t{display:block;font-size:13px}
.alert d{display:block;font-size:12.5px;color:var(--dim);margin-top:1px}

/* ---- log console ---- */
.logbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:9px 12px;border-bottom:1px solid var(--rule)}
.chips{display:flex;gap:4px}
.chip{font-family:var(--mono);font-size:11px;padding:3px 8px;border-radius:999px;border:1px solid var(--rule2);
  background:transparent;color:var(--dim);cursor:pointer}
.chip[aria-pressed=true]{border-color:var(--accent);color:var(--txt);background:var(--raise)}
.logbody{height:min(52vh,460px);overflow:auto;background:var(--raise);border-radius:0 0 var(--r) var(--r);
  padding:8px 0;font-family:var(--mono);font-size:12px;line-height:1.62}
.lb-pause{position:sticky;bottom:8px;left:8px;width:max-content;margin:0 auto;display:block}
.lrow{display:grid;grid-template-columns:78px 16px 14px minmax(0,1fr);gap:8px;padding:0 12px;white-space:pre-wrap;
  word-break:break-word}
.lrow:hover{background:var(--panel)}
.lrow .t{color:var(--faint)}
.lrow .g{color:var(--faint)}
.lrow .l{font-weight:700}
.lrow.ERROR .l,.lrow.FATAL .l{color:var(--crit)}
.lrow.WARN .l{color:var(--warn)}
.lrow.DEBUG .l,.lrow.TRACE .l{color:var(--faint)}
.lrow .m{color:var(--txt)}

/* ---- tables ---- */
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:7px 10px;border-top:1px solid var(--rule);vertical-align:middle}
th{font-size:11px;color:var(--faint);font-weight:600;border-top:0}
tbody tr:first-child td{border-top:0}
td.n,th.n{font-family:var(--mono);font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}
td.act{text-align:right;white-space:nowrap}
.empty{padding:16px 14px;color:var(--dim);font-size:13px}
.empty b{display:block;color:var(--txt);font-weight:600;margin-bottom:2px}
.rows{display:flex;flex-direction:column}
.row{display:flex;gap:10px;align-items:center;padding:8px 12px;border-top:1px solid var(--rule);flex-wrap:wrap}
.row:first-child{border-top:0}
.row label{font-size:12px;color:var(--dim);min-width:74px}
.row .grow{flex:1 1 180px;min-width:0}

/* ---- progressive disclosure ---- */
details{border-top:1px solid var(--rule)}
details:first-of-type{border-top:0}
summary{cursor:pointer;padding:10px 12px;font-size:13px;color:var(--dim);list-style:none;display:flex;
  align-items:center;gap:9px}
summary::-webkit-details-marker{display:none}
summary:hover{color:var(--txt)}
summary .c{font-family:var(--mono);font-size:10px;color:var(--faint);transition:transform .15s}
details[open] summary .c{transform:rotate(90deg)}
details[open] summary{color:var(--txt)}
.dbo{padding:2px 12px 12px}

/* ---- results & toasts ---- */
.res{font-family:var(--mono);font-size:12px;white-space:pre-wrap;word-break:break-word;background:var(--raise);
  border:1px solid var(--rule);border-left:2px solid var(--rule2);border-radius:var(--r);padding:9px 11px;margin:10px 0 0}
.res.err{border-left-color:var(--crit)}
.res.ok{border-left-color:var(--ok)}
#toasts{position:fixed;right:14px;bottom:14px;display:flex;flex-direction:column;gap:8px;z-index:40;max-width:min(420px,92vw)}
.toast{background:var(--panel);border:1px solid var(--rule2);border-left:2px solid var(--accent);
  border-radius:var(--r);padding:9px 12px;font-size:13px;box-shadow:0 10px 30px rgba(0,0,0,.42)}
.toast.err{border-left-color:var(--crit)}
.toast.ok{border-left-color:var(--ok)}
.toast b{display:block;font-weight:600}
.toast span{color:var(--dim);font-size:12px}
.busy{display:inline-block;width:11px;height:11px;border:2px solid var(--rule2);border-top-color:var(--accent);
  border-radius:50%;animation:spin .7s linear infinite;vertical-align:-2px;margin-right:7px}
@keyframes spin{to{transform:rotate(360deg)}}
.confirm{border-color:var(--crit)!important;color:var(--crit)}
.kv{display:grid;grid-template-columns:auto minmax(0,1fr);gap:4px 14px;font-size:13px;margin:0}
.kv dt{color:var(--faint)}
.kv dd{margin:0;font-family:var(--mono);font-variant-numeric:tabular-nums;word-break:break-word}
.sev{font-family:var(--mono);font-size:11px;padding:1px 6px;border-radius:999px;border:1px solid var(--rule2);color:var(--dim)}
.sev.on{color:var(--ok);border-color:var(--ok)}
.sev.off{color:var(--dim)}
@media (max-width:1000px){
  .shell{grid-template-columns:1fr}
  .rail{position:static;height:auto;flex-direction:row;align-items:center;gap:14px;border-right:0;
    border-bottom:1px solid var(--rule);overflow-x:auto}
  nav{flex-direction:row;flex-wrap:wrap}
  nav a{border-left:0;border-bottom:2px solid transparent}
  nav a[aria-current=true]{border-bottom-color:var(--accent)}
  .railfoot{margin:0 0 0 auto;flex-direction:row;align-items:center}
  .split{grid-template-columns:1fr}
  .strip{grid-template-columns:1fr}
  .join{border-left:0;border-top:1px solid var(--rule);border-radius:0 var(--r) var(--r) 0}
  .col{padding:14px 14px 60px}
}
@media (prefers-reduced-motion:reduce){*,*::before,*::after{animation-duration:.01ms!important;
  animation-iteration-count:1!important;transition-duration:.01ms!important}}
</style>
</head>
<body>
<div class=shell>
  <aside class=rail>
    <div class=mark><div class=cube><i></i></div><div><b>bambo-mc</b><small>v__VERSION__</small></div></div>
    <nav aria-label=Sections>
      <a href=#status>Status</a><a href=#logs>Log</a><a href=#players>Players</a>
      <a href=#worlds>Worlds</a><a href=#backups>Backups</a><a href=#maintenance>Maintenance</a>
      <a href=#access>Access</a><a href=#console>Console</a>
    </nav>
    <div class=railfoot>
      <div class=live id=live><span class=pip></span><span id=liveTxt>connecting</span></div>
      <button id=themeBtn type=button>Theme</button>
    </div>
  </aside>

  <main class=col>
    <section id=status>
      <div class="panel strip">
        <div class=state>
          <div class=staword id=staword data-s=down>
            <span class=dot></span><h1 id=stateWord>Checking</h1><span class=why id=stateWhy></span>
          </div>
          <ul class=facts>
            <li><span class=k>Players</span><span class="v big" id=fPlayers>-</span></li>
            <li><span class=k>Uptime</span><span class=v id=fUptime>-</span></li>
            <li><span class=k>Last activity</span><span class=v id=fActivity>-</span></li>
            <li><span class=k>Engine</span><span class=v id=fEngine>-</span></li>
          </ul>
          <div class=acts>
            <button class=go data-act=start type=button>Start</button>
            <button data-act=stop data-confirm="Stop the server? Anyone playing is disconnected, and worlds save first (~40s)." type=button>Stop</button>
            <button data-act=restart data-confirm="Restart the server? Players are disconnected for about a minute." type=button>Restart</button>
            <button data-act=backup data-confirm="Take a snapshot of worlds, players and config now?" type=button>Back up now</button>
            <button id=refreshBtn type=button>Refresh</button>
          </div>
        </div>
        <div class=join>
          <div class="row"><span class=k>Join address</span><span class=faint id=joinNet></span></div>
          <div class=addr id=joinAddr>-</div>
          <div class="row"><span class=faint id=joinPort>port -</span>
            <span><button id=copyBtn type=button>Copy</button></span></div>
        </div>
      </div>
      <div class="panel heart">
        <svg id=heart viewBox="0 0 600 46" preserveAspectRatio=none role=img aria-label="Players online and running state over the last few minutes"></svg>
        <span class=axis id=heartAxis></span>
      </div>
      <div class="panel alerts" id=alerts aria-live=polite aria-label="Things needing attention"></div>
    </section>

    <section id=logs>
      <div class=panel>
        <div class=logbar>
          <b style=font-size:13px>Server log</b>
          <div class=chips role=group aria-label="Filter level">
            <button class=chip data-lvl=INFO aria-pressed=true type=button>info</button>
            <button class=chip data-lvl=WARN aria-pressed=true type=button>warn</button>
            <button class=chip data-lvl=ERROR aria-pressed=true type=button>error</button>
            <button class=chip data-lvl=DEBUG aria-pressed=false type=button>debug</button>
          </div>
          <input id=logSearch class=grow placeholder="Filter text" aria-label="Filter log text" style=flex:1>
          <select id=logLines aria-label="Lines to read">
            <option value=200>200 lines</option><option value=400 selected>400 lines</option>
            <option value=800>800 lines</option>
          </select>
          <button class=chip id=autoBtn aria-pressed=true type=button>Follow</button>
        </div>
        <div class=logbody id=logBody tabindex=0></div>
        <button class="chip lb-pause hidden" id=newBtn type=button></button>
      </div>
    </section>

    <div class=split>
      <div>
        <section id=players>
          <h2>Players <span class=n id=playersSub></span></h2>
          <div class=panel>
            <div class=rows id=playersBody></div>
            <details>
              <summary><span class=c>&#9656;</span>Move a player, or change their mode</summary>
              <div class=dbo>
                <div class=row><label for=uName>Player</label>
                  <input id=uName class=grow placeholder="gamertag"></div>
                <div class=row><label>Action</label>
                  <select id=uVerb><option value=gamemode>Game mode</option><option value=kick>Kick</option>
                    <option value=ban>Ban</option><option value=unban>Unban</option>
                    <option value=op>Make operator</option><option value=deop>Remove operator</option></select>
                  <select id=uMode><option value=0>survival</option><option value=1>creative</option>
                    <option value=2>adventure</option><option value=3>spectator</option></select>
                  <button id=uGo class=go type=button>Apply</button></div>
                <div class="res hidden" id=uRes></div>
              </div>
            </details>
            <details>
              <summary><span class=c>&#9656;</span>Announce something in game</summary>
              <div class=dbo><div class=row><label>Message</label>
                <input id=bcMsg class=grow placeholder="Dinner on the server in 10">
                <button id=bcGo type=button>Broadcast</button></div>
                <div class="res hidden" id=bcRes></div></div>
            </details>
          </div>
        </section>

        <section id=console>
          <h2>Console command</h2>
          <div class=panel>
            <div class="pad row" style=padding-top:0>
              <input id=cmdLine class=grow placeholder="save-all" aria-label="Server console command">
              <button id=cmdGo class=go type=button>Run</button>
            </div>
            <div class="dbo faint" style=font-size:12px>
              Sent straight to the server console, without the leading slash. This is the
              unfiltered operator door - the reason this page needs its token.
            </div>
            <div class="res hidden" id=cmdRes style=margin:0 12px 12px></div>
          </div>
        </section>

        <section id=worlds>
          <h2>Worlds <button id=worldRefresh class=chip type=button>Reload</button></h2>
          <div class=panel>
            <div id=worldsBody></div>
            <details>
              <summary><span class=c>&#9656;</span>Create, rename or clear a world</summary>
              <div class=dbo>
                <div class="row faint" style=font-size:12px>
                  The server must be stopped first - those buttons tell you if it is running.</div>
                <div class=row><label for=wNew>New from template</label>
                  <input id=wNew class=grow placeholder="world name"><button data-w="create" type=button>Create</button></div>
                <div class=row><label for=wOld>Rename</label>
                  <input id=wOld class=grow placeholder="current name">
                  <input id=wRen class=grow placeholder="new name"><button data-w="rename" type=button>Rename</button></div>
                <div class=row><label for=wDel>Move to trash</label>
                  <input id=wDel class=grow placeholder="world name">
                  <button data-w="delete" class=danger
                    data-confirm="Move this world to runtime/.trash? Players respawn in the default world. It stays recoverable until you purge it." type=button>Move to trash</button></div>
                <div class="res hidden" id=wRes></div>
              </div>
            </details>
          </div>
        </section>

        <section id=access>
          <h2>Access</h2>
          <div class=panel>
            <div class="pad rows">
              <div class=row><label>Server name</label>
                <input id=motd1 class=grow placeholder="name shown in the server list">
                <input id=motd2 class=grow placeholder="second line (optional)">
                <button id=motdGo type=button data-confirm="Saving the name restarts the server (~40s) and disconnects players.">Save</button></div>
              <div class=row><label>Allow list</label>
                <select id=wlMode><option value=add>Add player</option><option value=remove>Remove player</option>
                  <option value=on>Switch on</option><option value=off>Switch off</option><option value=list>Show list</option></select>
                <input id=wlName class=grow placeholder="gamertag">
                <button id=wlGo type=button>Apply</button></div>
              <div class=row><label>Operators</label>
                <input id=opName class=grow placeholder="gamertag">
                <button data-op=add type=button>Grant</button>
                <button data-op=del class=danger type=button>Revoke</button>
                <button id=opList type=button>Show list</button></div>
              <div class="res hidden" id=aRes></div>
            </div>
            <details>
              <summary><span class=c>&#9656;</span>Server settings in use</summary>
              <div class=dbo><dl class=kv id=cfgKv></dl></div>
            </details>
            <details>
              <summary><span class=c>&#9656;</span>Daily restart at 04:00</summary>
              <div class=dbo><div class=row>
                <button data-maint=status type=button>Check</button>
                <button data-maint=on type=button>Turn on</button>
                <button data-maint=off type=button>Turn off</button></div>
                <div class="res hidden" id=maintRes></div></div>
            </details>
          </div>
        </section>
      </div>

      <div>
        <section id=backups>
          <h2>Backups <span class=n id=backupSub></span></h2>
          <div class=panel><div id=backupBody></div></div>
        </section>

        <section id=maintenance>
          <h2>Software</h2>
          <div class=panel>
            <div class=pad><dl class=kv id=verKv></dl></div>
            <div class="row" style=padding:0 12px 12px>
              <button id=updateCheck type=button>Check for updates</button>
              <button id=prevBtn type=button data-confirm="Swap back to the previously installed engine? The server stops for a moment.">Back to previous build</button>
            </div>
            <div class="row" style=padding:0 12px 12px>
              <label for=verPick style=font-size:12px;color:var(--dim)>Switch engine</label>
              <select id=verPick class=grow aria-label="Server version to switch to"></select>
              <button id=verGo class=danger type=button
                data-confirm="Install this engine build? Takes a backup, stops the server, downloads the jar, then restarts if it was running. Clients must match the Bedrock version it speaks.">Switch</button>
            </div>
            <div class="row" style=padding:0 12px 12px>
              <label for=verCustom style=font-size:12px;color:var(--dim)>Or install</label>
              <input id=verCustom class=grow placeholder="any release tag, e.g. 3.0.4" aria-label="Release tag to install">
              <button id=verInstall type=button data-confirm="Download that release and make it the live server? Restart the server afterwards to run it.">Install</button>
            </div>
            <div class="dbo faint" style=font-size:12px id=verHint></div>
            <div class="res hidden" id=verRes></div>
          </div>
        </section>

        <section id=token>
          <h2>Admin token</h2>
          <div class=panel>
            <div class="pad rows">
              <div class=row>
                <input id=tok type=password placeholder="paste the token from dash.token"
                  autocomplete=off autocapitalize=off spellcheck=false class=grow aria-label="Admin token">
                <button id=tokSave class=go type=button>Save</button>
              </div>
              <div class=row style=font-size:12px;color:var(--dim);display:block>
                Every control here sends <span class=mono>bambo</span> a command, so every one needs the token.
                It is kept in this browser only. <span class=mono id=tokState></span>
              </div>
            </div>
          </div>
        </section>

        <section id=other>
          <h2>Other servers on this machine</h2>
          <div class=panel><div id=otherBody></div></div>
        </section>
      </div>
    </div>
  </main>
</div>
<div id=toasts aria-live=polite aria-atomic=false></div>
</body>
</html>"""

PAGE_JS = """<script>
"use strict";
/* ============================================================
   All data reaches the screen through textContent / createElement.
   Server text is never interpolated into HTML, so a crafted player
   name or log line cannot become markup (see SECURITY.md).
   ============================================================ */
const $=(s)=>document.querySelector(s);
const el=(t,c,txt)=>{const e=document.createElement(t);if(c)e.className=c;if(txt!==undefined)e.textContent=txt;return e;};
const S={st:null,log:[],lvl:new Set(["INFO","WARN","ERROR"]),q:"",follow:true,fail:0,timer:null,logTimer:null,busy:new Set()};

/* ---------- small format helpers (tabular-safe, never colour alone) ---------- */
function ago(sec){
  if(sec===null||sec===undefined||isNaN(sec))return "-";
  sec=Math.max(0,Math.round(sec));
  if(sec<60)return sec+"s";
  const m=Math.floor(sec/60); if(m<60)return m+"m";
  const h=Math.floor(m/60); if(h<24)return h+"h"+String(m%60).padStart(2,"0");
  return Math.floor(h/24)+"d"+String(h%24).padStart(2,"0");
}
function dur(sec){
  if(sec===null||sec===undefined||isNaN(sec))return "-";
  const d=Math.floor(sec/86400),h=Math.floor(sec%86400/3600),m=Math.floor(sec%3600/60);
  if(d)return d+"d "+String(h).padStart(2,"0")+"h";
  if(h)return h+"h "+String(m).padStart(2,"0")+"m";
  return m+"m";
}
function epochTo(ts){const e=new Date(ts.replace(" ","T"));const n=e.getTime();return isNaN(n)?null:Math.round((Date.now()-n)/1000);}
function tsClock(ts){return ts?ts.slice(11,19):"";}
function backupAge(name){
  const m=name.match(/^(\\d{4})(\\d{2})(\\d{2})-(\\d{2})(\\d{2})(\\d{2})$/);
  if(!m)return null;
  const d=new Date(+m[1],+m[2]-1,+m[3],+m[4],+m[5],+m[6]);
  return isNaN(d.getTime())?null:Math.round((Date.now()-d.getTime())/1000);
}

/* ---------- toasts: action feedback that does not block the page ---------- */
function toast(title,detail,kind){
  const t=el("div","toast"+(kind?" "+kind:""));
  t.appendChild(el("b",null,title));
  if(detail)t.appendChild(el("span",null,detail));
  $("#toasts").appendChild(t);
  setTimeout(()=>{t.remove();},kind==="err"?9000:5200);
}
function result(node,resp,label){
  if(!node)return;
  node.classList.remove("hidden");
  node.classList.remove("ok","err");
  node.classList.add(resp&&resp.ok?"ok":"err");
  const head=(resp&&resp.ok?"\\u2713 ":"\\u2717 ")+(label||"")+"\\n";
  node.textContent=head+((resp&&resp.output)||JSON.stringify(resp));
  node.scrollTop=0;
}

/* ---------- transport ---------- */
async function get(url){
  const r=await fetch(url,{headers:{accept:"application/json"}});
  if(!r.ok)throw new Error("HTTP "+r.status);
  return r.json();
}
async function post(action,args){
  const t=($("#tok").value||localStorage.getItem("bambo.tok")||"").trim();
  const r=await fetch("/api/action",{method:"POST",headers:{"content-type":"application/json"},
    body:JSON.stringify({token:t,action:action,args:args||[]})});
  const d=await r.json().catch(()=>({ok:false,output:"no response body (HTTP "+r.status+")"}));
  if(r.status===401){toast("Admin token missing or wrong","Open the token panel, paste the value from dash.token, then Save.","err");}
  if(r.status===429){toast("Too many failed attempts","Wait about a minute before trying the token again.","err");}
  return d;
}
async function run(btn,action,args,label,resNode){
  // Keyed on the control, not the action name: two different "world" buttons
  // (create and delete) must not swallow each other, and a busy control says so
  // instead of quietly doing nothing.
  const key=action+"|"+JSON.stringify(args||[])+(btn?"|"+((btn.dataset.act||btn.dataset.w||btn.dataset.op||btn.dataset.maint||btn.dataset.restore||btn.id)||"btn"):"");
  if(S.busy.has(key)){toast("Already working","That command is still running - check the panel below it.","");return;}
  S.busy.add(key);
  const html=btn?btn.textContent:"";
  if(btn){btn.disabled=true;btn.innerHTML="";btn.prepend(el("span","busy"));btn.append(html);}
  try{
    const d=await post(action,args);
    if(resNode)result(resNode,d,label||action);
    toast((d.ok?label||action:("Failed: "+(label||action))),
      d.ok?(((d.output||"").trim().split("\\n").pop()||"done").slice(0,160)):"see the panel for the reason",d.ok?"ok":"err");
    if(d.ok)await tick(true);
    return d;
  }catch(e){
    if(resNode)result(resNode,{ok:false,output:String(e)});
    toast("Could not reach the dashboard",String(e),"err");
  }finally{
    S.busy.delete(key);
    if(btn){btn.disabled=false;btn.textContent=html;}
  }
}

/* ---------- two-step confirmation ---------- */
// armed() serves buttons with their own click listener; arm/disarm run from the
// delegated handler, so a single press can never both arm and act.
function armed(btn){return !btn.dataset.confirm||btn.dataset.arm==="1";}
function armButton(btn){
  if(btn.dataset.label0===undefined)btn.dataset.label0=btn.textContent;
  btn.dataset.arm="1";
  btn.classList.add("confirm");
  btn.textContent="Tap again to confirm";
  toast("Confirm: "+(btn.dataset.label0||"this"),btn.dataset.confirm,"");
  setTimeout(()=>{if(btn.dataset.arm==="1")disarmButton(btn);},8000);
}
function disarmButton(btn){
  btn.dataset.arm="0";
  btn.classList.remove("confirm");
  if(btn.dataset.label0!==undefined)btn.textContent=btn.dataset.label0;
}

/* ---------- status render ---------- */
function renderStatus(s){
  S.st=s;
  const up=!!s.running;
  const word=up?(s.port_bound?"Running":"Not reachable"):"Stopped";
  const sw=$("#staword");
  sw.dataset.s=up?(s.port_bound?"up":"warn"):"down";
  sw.querySelector("h1").textContent=word;
  $("#stateWhy").textContent=up
    ?(s.port_bound?"":(s.health&&s.health.errors?s.health.errors+" errors in view":""))
    :"";
  const h=s.health||{};
  const max=(s.config&&+s.config.max_players)||0;
  $("#fPlayers").textContent=(h.players_online===null||h.players_online===undefined)
    ?"-":(max?h.players_online+"/"+max:String(h.players_online));
  $("#fUptime").textContent=up?dur(h.uptime_s):"-";
  $("#fActivity").textContent=h.last_ts?ago(epochTo(h.last_ts)):"-";
  const v=s.version||{};
  $("#fEngine").textContent=v.tag?("PNX "+v.tag):"-";
  $("#joinAddr").textContent=s.join_ip||(s.join||"-").split(" ")[0];
  $("#joinPort").textContent="port "+(s.port||19132)+(s.port_bound?" \\u00b7 listening":" \\u00b7 not listening");
  $("#joinNet").textContent=s.exposed?"exposed on "+s.exposed:"localhost only";
  const pb=$("#playersSub");
  if(pb)pb.textContent=h.players_online?"someone is in":"nobody connected";

  const cfg=s.config||{};
  const kv=$("#cfgKv");
  if(kv){kv.innerHTML="";
    [["Name",cfg.name],["Second line",cfg.subtitle],["Max players",cfg.max_players],
     ["Default world",cfg.default_world],["Game mode",cfg.gamemode],["Difficulty",cfg.difficulty],
     ["Player versus",cfg.pvp],["Xbox authentication",cfg.xbox_auth],["Allow list",cfg.allowlist],
     ["Port",cfg.port]].forEach(([k,val])=>{
      if(val===undefined)return;
      kv.appendChild(el("dt",null,k));
      const dd=el("dd",null,val);
      if(k==="Xbox authentication"||k==="Allow list"){
        dd.textContent="";
        dd.appendChild(el("span","sev "+(val==="true"?"on":"off"),val==="true"?"on":"off"));
        if(k==="Xbox authentication"&&val==="false"){
          dd.append(el("span","faint","  trusted LAN only - anyone on the network can join"));
        }
      }
      kv.appendChild(dd);
    });}

  const alerts=$("#alerts");
  alerts.innerHTML="";
  const order={critical:0,warn:1,ok:2};
  (s.alerts||[]).slice().sort((a,b)=>(order[a.level]||9)-(order[b.level]||9)).forEach(a=>{
    const row=el("div","alert "+a.level);
    const badge={critical:"!",warn:"~",ok:"ok"}[a.level]||"i";
    row.appendChild(el("b",null,badge));
    const body=el("div");
    body.appendChild(el("t",null,a.title+(a.level==="critical"?" - critical":a.level==="warn"?" - check this":"")));
    body.appendChild(el("d",null,a.detail));
    row.appendChild(body);
    alerts.appendChild(row);
  });

  const ob=$("#otherBody");
  ob.innerHTML="";
  const others=s.others||[];
  if(!others.length)ob.appendChild(el("div","empty",["Nothing else found under ~/minecraftbe.","This dashboard only controls bambo-mc."]));
  else{const b=el("div","pad");others.forEach(o=>b.appendChild(el("div","mono dim",o)));ob.appendChild(b);}

  const bb=$("#backupBody");
  bb.innerHTML="";
  const list=(s.backups||[]).slice().reverse();
  $("#backupSub").textContent=list.length?list.length+" kept, newest first":"none yet";
  if(!list.length){
    bb.appendChild(el("div","empty",[el("b",null,"No snapshots yet"),
      "Back up now, or wait for the nightly job at 03:30."]));
  }else{
    const tbl=el("table");
    const head=el("tr");["Snapshot","Age",""].forEach((t,i)=>head.appendChild(el(i?"th":"th",i===2?"act n":"n",t)));
    const thead=el("thead",null);thead.appendChild(head);tbl.appendChild(thead);
    const tb=el("tbody");
    list.forEach((n,i)=>{
      const tr=el("tr");
      tr.appendChild(el("td","mono",n));
      const age=backupAge(n);
      tr.appendChild(el("td","n",age===null?"-":ago(age)));
      const td=el("td","act");
      if(i===0)td.appendChild(el("span","sev on","newest"));
      else{
        const b=el("button",null,"Restore");
        b.dataset.restore=n;
        b.dataset.confirm="Restore "+n+"? Current worlds are kept as worlds.pre-restore-<time>, so this is reversible. The server must be stopped.";
        if(!up)b.disabled=false;else b.disabled=true,b.title="Stop the server first";
        td.appendChild(b);
      }
      tr.appendChild(td);tb.appendChild(tr);
    });
    tbl.appendChild(tb);bb.appendChild(tbl);
  }
  renderVersion(s);
  renderHeart(s);
}

/* ---------- the heartbeat: players over time, drawn without a chart lib ---------- */
function renderHeart(s){
  const svg=$("#heart");
  const hist=s.history||[];
  const axis=$("#heartAxis");
  svg.innerHTML="";
  if(hist.length<2){
    axis.textContent="collecting";
    const t=el("text",null,"needs a few minutes of samples");
    t.setAttribute("x","8");t.setAttribute("y","28");
    t.setAttribute("fill","currentColor");t.setAttribute("opacity",".45");
    t.setAttribute("font-size","12");t.setAttribute("font-family","var(--mono)");
    svg.appendChild(t);
    return;
  }
  const W=600,H=46,pad=4;
  const t0=hist[0][0],t1=hist[hist.length-1][0];
  const span=Math.max(1,t1-t0);
  const counts=hist.map(h=>typeof h[1]==="number"?h[1]:0);
  const maxP=Math.max(1,...counts);
  const x=(t)=>pad+(t-t0)/span*(W-pad*2);
  const y=(p)=>H-pad-(p/maxP)*(H-pad*2-10);
  // running-state band: dim strip where the server was down, so gaps read as downtime
  let runStart=null;
  hist.forEach((h,i)=>{
    const down=!h[2];
    if(down&&runStart===null)runStart=i;
    if((!down||i===hist.length-1)&&runStart!==null){
      const a=hist[runStart][0],b=down?h[0]:hist[i][0];
      const r=el("rect");
      r.setAttribute("x",x(a));r.setAttribute("y",2);
      r.setAttribute("width",Math.max(1.5,x(b)-x(a)));r.setAttribute("height",H-4);
      r.setAttribute("fill","var(--crit)");r.setAttribute("opacity",".14");
      svg.appendChild(r);runStart=null;
    }
  });
  let dPath="";
  hist.forEach((h,i)=>{dPath+=(i?"L":"M")+x(h[0]).toFixed(1)+" "+y(counts[i]).toFixed(1)+" ";});
  const line=el("path");
  line.setAttribute("d",dPath.trim());
  line.setAttribute("fill","none");line.setAttribute("stroke","var(--accent)");
  line.setAttribute("stroke-width","1.75");line.setAttribute("stroke-linejoin","round");
  svg.appendChild(line);
  const last=hist[hist.length-1];
  const dot=el("circle");
  dot.setAttribute("cx",x(last[0]));dot.setAttribute("cy",y(counts[counts.length-1]));
  dot.setAttribute("r","2.6");dot.setAttribute("fill","var(--accent)");
  svg.appendChild(dot);
  axis.textContent=maxP+" max \\u00b7 "+Math.round(span/60)+"m window";
}

/* ---------- log ---------- */
function logRow(e){
  const tr=el("div","lrow "+(e.level||""));
  tr.appendChild(el("span","t",tsClock(e.ts)));
  tr.appendChild(el("span","g","|"));
  tr.appendChild(el("span","l",e.tag||"?"));
  tr.appendChild(el("span","m",e.msg));
  if(e.level==="ERROR"||e.level==="FATAL")tr.style.fontWeight="600";
  return tr;
}
function renderLog(){
  const box=$("#logBody");
  const atBottom=box.scrollHeight-box.scrollTop-box.clientHeight<24;
  const q=S.q.toLowerCase();
  const shown=S.log.filter(e=>S.lvl.has(e.level)&&(!q||e.msg.toLowerCase().includes(q)));
  box.innerHTML="";
  const frag=document.createDocumentFragment();
  shown.forEach(e=>frag.appendChild(logRow(e)));
  box.appendChild(frag);
  if(S.follow&&atBottom)box.scrollTop=box.scrollHeight;
  if(!shown.length)box.appendChild(el("div","empty","Nothing matches those filters in the window that was read."));
}
async function tickLog(){
  const lim=+($("#logLines").value||400);
  try{
    const d=await get("/api/log?limit="+lim);
    const before=S.log.length?S.log[S.log.length-1]:null;
    S.log=d.entries||[];
    const after=S.log.length?S.log[S.log.length-1]:null;
    renderLog();
    if(!S.follow&&before&&after&&before.ts!==after.ts){
      const nb=$("#newBtn");
      nb.textContent="Jump to newest ("+S.log.length+" lines)";
      nb.classList.remove("hidden");
    }
  }catch(e){/* status poll already reports the connection state */}
}

/* ---------- poll loop, hidden-tab aware ---------- */
async function tick(force){
  const live=$("#live"),txt=$("#liveTxt");
  try{
    const s=await get("/api/status");
    renderStatus(s);
    S.fail=0;
    live.classList.remove("stale","down");
    live.querySelector(".pip").classList.add("beat");
    txt.textContent="live \\u00b7 "+new Date().toTimeString().slice(0,8);
    if(force)tickLog();
  }catch(e){
    S.fail++;
    live.classList.add("down");live.querySelector(".pip").classList.remove("beat");
    txt.textContent="offline \\u00b7 retrying";
    toastOnce("Dashboard stopped answering",String(e)+" - is the server process still running?","err");
  }
  schedule();
}
let toastSeen=new Set();
function toastOnce(title,detail,kind){
  if(toastSeen.has(title))return;
  toastSeen.add(title);toast(title,detail,kind);
}
function schedule(){
  clearTimeout(S.timer);clearTimeout(S.logTimer);
  if(document.hidden)return;                       // a laptop on a hotspot does not need polling in a background tab
  const backoff=Math.min(20000,3000*Math.pow(2,S.fail));
  S.timer=setTimeout(tick,backoff);
  S.logTimer=setTimeout(tickLog,S.fail?backoff:5000);
}
document.addEventListener("visibilitychange",()=>{if(!document.hidden){S.fail=0;tick(true);}});

/* ---------- players panel: live count plus the console list on demand ---------- */
async function refreshPlayers(){
  const body=$("#playersBody");
  body.innerHTML="";
  const s=S.st||{};
  const h=s.health||{};
  const n=h.players_online;
  if(!s.running){
    body.appendChild(el("div","empty",[el("b",null,"The server is stopped"),
      "Nobody can join until it runs. Start it from the panel above."]));
    return;
  }
  if(n===0){
    body.appendChild(el("div","empty",[el("b",null,"Nobody is connected"),
      "Send them the join address above - name shows as "+((s.config&&s.config.name)||"bambo-mc")+"."]));
    return;
  }
  const d=await post("players",["list"]);
  // The console answers with "There are N/M players online:" then one name per line.
  const lines=(d.output||"").split("\\n")
    .map(x=>x.replace(/^.*?\\]\\s*[A-Z]+\\s*-\\s*/,"").replace(/^>\\s*/,"").trim())
    .filter(x=>x&&!/^>\\s*$/.test(x));
  const at=lines.findIndex(x=>/players online/i.test(x));
  const names=(at>=0?lines.slice(at+1):[]);
  const tbl=el("table"),tr=el("tr");
  ["Player","Last seen"].forEach(t=>tr.appendChild(el("th",null,t)));
  const th=el("thead");th.appendChild(tr);tbl.appendChild(th);
  const tb=el("tbody");
  (names.length?names:["(see the log for who is in)"]).forEach(nm=>{
    const r=el("tr");
    r.appendChild(el("td","mono",nm));
    r.appendChild(el("td","n",h.last_ts?tsClock(h.last_ts):"now"));
    tb.appendChild(r);
  });
  tbl.appendChild(tb);body.appendChild(tbl);
}

/* ---------- worlds ---------- */
async function refreshWorlds(){
  const box=$("#worldsBody");
  box.innerHTML="";
  const d=await post("world",["list"]);
  const lines=(d.output||"").split("\\n").map(x=>x.replace(/^\\s+/,"")).filter(x=>x&&!/^---/.test(x));
  if(!d.ok||!lines.length){
    box.appendChild(el("div","empty",[el("b",null,"Could not read the worlds"),(d.output||"No worlds found.").trim().slice(0,300)]));
    return;
  }
  const tbl=el("table"),hd=el("tr");
  ["World","Size",""].forEach(t=>hd.appendChild(el("th",null,t)));
  const th=el("thead");th.appendChild(hd);tbl.appendChild(th);
  const tb=el("tbody");
  lines.forEach(l=>{
    const m=l.match(/^(\\S+)\\s+([0-9.]+[KMGT]?)\\s*(\\(default\\))?/);
    const r=el("tr");
    r.appendChild(el("td","mono",m?m[1]:l));
    r.appendChild(el("td","n",m?m[2]:""));
    const td=el("td","act");
    if(m&&m[3])td.appendChild(el("span","sev on","default"));
    else{
      const b=el("button",null,"Make default");
      b.dataset.w="default";b.dataset.name=m?m[1]:l;
      b.dataset.confirm="Set this as the world players spawn in? The server must be stopped, and it restarts to take effect.";
      td.appendChild(b);
    }
    r.appendChild(td);tb.appendChild(r);
  });
  tbl.appendChild(tb);box.appendChild(tbl);
}

/* ---------- wiring ---------- */
function wireActions(){
  document.addEventListener("click",(ev)=>{
    const b=ev.target.closest("button");
    if(!b)return;
    // Confirm lives here, not on a per-button listener: a document-level handler
    // always runs after the button's own listeners, so one click cannot both arm
    // and act. Buttons with their own listener check armed() and bail on tap one.
    if(b.dataset.confirm){
      if(b.dataset.arm!=="1"){armButton(b);return;}
      disarmButton(b);
    }
    // power actions
    if(b.dataset.act){
      if(b.dataset.act==="start")return run(b,"start",[],"Starting the server");
      return run(b,b.dataset.act,[],b.textContent.trim());
    }
    if(b.dataset.w){
      const w=b.dataset.w;
      let args=null,label="";
      if(w==="create"){const n=$("#wNew").value.trim();if(!n){toast("Type a world name first","","");return;}args=["create",n];label="Create world "+n;}
      if(w==="rename"){const o=$("#wOld").value.trim(),r=$("#wRen").value.trim();
        if(!o||!r){toast("Both names are needed","","");return;}args=["rename",o,r];label="Rename world";}
      if(w==="delete"){const n=$("#wDel").value.trim();if(!n){toast("Type the world name","","");return;}args=["delete",n,"--force"];label="Move world to trash";}
      if(w==="default"){const n=b.dataset.name||"";args=["default",n];label="Set "+n+" as default";}
      if(w==="save"){args=["save"];label="Save worlds";}
      if(args)return run(b,"world",args,label,$("#wRes")).then(refreshWorlds);
    }
    if(b.dataset.op){
      const n=$("#opName").value.trim();
      if(!n){toast("Type the gamertag","","");return;}
      return run(b,"op",[b.dataset.op,n],(b.dataset.op==="add"?"Grant operator to ":"Revoke operator from ")+n,$("#aRes"));
    }
    if(b.dataset.maint){
      return run(b,"maintenance",[b.dataset.maint],"Daily restart: "+b.dataset.maint,$("#maintRes"));
    }
    if(b.dataset.restore){
      return run(b,"restore",[b.dataset.restore],"Restore "+b.dataset.restore).then(()=>toast("Restore finished","Start the server and check the worlds.","ok"));
    }
  });
  $("#refreshBtn").addEventListener("click",()=>tick(true));
  $("#copyBtn").addEventListener("click",async()=>{
    const a=($("#joinAddr").textContent||"").trim();
    try{await navigator.clipboard.writeText(a);toast("Join address copied",a,"ok");}
    catch(e){
      const r=document.createRange();r.selectNodeContents($("#joinAddr"));
      const sel=window.getSelection();sel.removeAllRanges();sel.addRange(r);
      toast("Select and copy manually",a,"");
    }
  });
  $("#themeBtn").addEventListener("click",()=>{
    const cur=document.documentElement.dataset.theme;
    const next=cur==="light"?"dark":(cur==="dark"?"auto":"light");
    document.documentElement.dataset.theme=next==="auto"?"":next;
    localStorage.setItem("bambo.theme",next);
    $("#themeBtn").textContent=next==="auto"?"Theme: auto":("Theme: "+next);
  });
  $("#tok").value=localStorage.getItem("bambo.tok")||"";
  $("#tokSave").addEventListener("click",()=>{
    const t=$("#tok").value.trim();
    if(!t){toast("Nothing to save","Paste the token from dash.token first.","err");return;}
    localStorage.setItem("bambo.tok",t);
    $("#tokState").textContent="saved in this browser";
    toast("Token saved","Try a control now.","ok");
  });
  $("#autoBtn").addEventListener("click",(e)=>{
    S.follow=!S.follow;
    e.currentTarget.setAttribute("aria-pressed",String(S.follow));
    e.currentTarget.textContent=S.follow?"Following":"Paused";
    if(S.follow){$("#newBtn").classList.add("hidden");renderLog();}
  });
  $("#newBtn").addEventListener("click",()=>{
    const box=$("#logBody");box.scrollTop=box.scrollHeight;
    S.follow=true;$("#autoBtn").setAttribute("aria-pressed","true");$("#autoBtn").textContent="Following";
    $("#newBtn").classList.add("hidden");
  });
  document.querySelectorAll(".chip[data-lvl]").forEach(c=>c.addEventListener("click",()=>{
    const l=c.dataset.lvl;
    const on=c.getAttribute("aria-pressed")==="true";
    c.setAttribute("aria-pressed",String(!on));
    if(on)S.lvl.delete(l);else S.lvl.add(l);
    renderLog();
  }));
  $("#logSearch").addEventListener("input",(e)=>{S.q=e.target.value.trim();renderLog();});
  $("#logLines").addEventListener("change",()=>tickLog());
  $("#cmdGo").addEventListener("click",()=>{
    const c=$("#cmdLine").value.trim();
    if(!c){toast("Type a command first","Example: save-all","","");return;}
    run($("#cmdGo"),"cmd",[c.replace(/^\\//,"")],"Run on console",$("#cmdRes"));
  });
  $("#cmdLine").addEventListener("keydown",(e)=>{if(e.key==="Enter")$("#cmdGo").click();});
  $("#uGo").addEventListener("click",()=>{
    const n=$("#uName").value.trim(),verb=$("#uVerb").value,mode=$("#uMode").value;
    if(!n){toast("Type the gamertag","","");return;}
    const args=verb==="gamemode"?["gamemode",mode,n]:(verb==="op"?null:[verb,n]);
    if(verb==="op")return run($("#uGo"),"op",["add",n],"Grant operator to "+n,$("#uRes"));
    if(verb==="deop")return run($("#uGo"),"op",["del",n],"Revoke operator from "+n,$("#uRes"));
    return run($("#uGo"),"user",args,verb+" "+n,$("#uRes"));
  });
  $("#bcGo").addEventListener("click",()=>{
    const m=$("#bcMsg").value.trim();
    if(!m){toast("Nothing to announce","","");return;}
    run($("#bcGo"),"broadcast",[m],"Broadcast sent",$("#bcRes"));
  });
  $("#motdGo").addEventListener("click",(e)=>{
    if(!armed(e.currentTarget))return;         // saving the name restarts the server
    const a=$("#motd1").value.trim(),b=$("#motd2").value.trim();
    if(!a){toast("Give the server a name first","","");return;}
    run($("#motdGo"),"motd",b?[a,b]:[a],"Saved the name and restarted",$("#aRes"));
  });
  $("#wlGo").addEventListener("click",()=>{
    const mode=$("#wlMode").value,n=$("#wlName").value.trim();
    if(["add","remove","on","off","list","reload"].indexOf(mode)<0){toast("Choose what to do with the allow list first","","err");return;}
    if((mode==="add"||mode==="remove")&&!n){toast("Type the gamertag","","");return;}
    run($("#wlGo"),"whitelist",n&&mode!=="on"&&mode!=="off"?[mode,n]:[mode],"Allow list: "+mode,$("#aRes"));
  });
  $("#opList").addEventListener("click",()=>run($("#opList"),"op",["list"],"Operators",$("#aRes")));
  $("#worldRefresh").addEventListener("click",refreshWorlds);
  $("#updateCheck").addEventListener("click",()=>run($("#updateCheck"),"update",["check"],"Update check",$("#verRes")));
  // Any button with its own listener must check armed() too: the document-level
  // arming runs after this handler, so without the guard one tap would act.
  $("#verGo").addEventListener("click",(e)=>{
    if(!armed(e.currentTarget))return;         // switching engines stops the server and downloads a build
    const sel=$("#verPick"), tag=(sel&&sel.value)||"";
    if(!tag){toast("Choose a version first","","err");return;}
    run(e.currentTarget,"rollback",[tag],"Switched the engine to PNX "+tag,$("#verRes")).then(()=>tick(true));
  });
  $("#verInstall").addEventListener("click",(e)=>{
    if(!armed(e.currentTarget))return;         // installs a build and makes it live
    const v=$("#verCustom").value.trim();
    if(!v){toast("Type a release tag first","For example: 3.0.4","","err");return;}
    run(e.currentTarget,"setup",[v],"Installed PNX "+v,$("#verRes")).then(()=>tick(true));
  });
  $("#prevBtn").addEventListener("click",(e)=>{
    const b=e.currentTarget;
    if(!armed(b))return;                       // swapping the engine stops the server
    run(b,"rollback",["--prev"],"Rolled back to the previous build",$("#verRes")).then(()=>tick(true));
  });
  // nav highlight + players auto-refresh on state change
  document.querySelectorAll("nav a").forEach(a=>a.addEventListener("click",()=>{
    document.querySelectorAll("nav a").forEach(x=>x.removeAttribute("aria-current"));
    a.setAttribute("aria-current","true");
  }));
  const io=new IntersectionObserver((es)=>{
    es.forEach(e=>{if(e.isIntersecting){
      const id=e.target.id;
      document.querySelectorAll("nav a").forEach(x=>
        x.setAttribute("aria-current",String(x.getAttribute("href")==="#"+id)));
      if(id==="players")refreshPlayers();
      if(id==="worlds")refreshWorlds();
    }});
  },{rootMargin:"-40% 0px -50% 0px"});
  document.querySelectorAll("main section").forEach(s=>io.observe(s));
}

/* ---------- version card ---------- */
function prevLabel(v){
  if(!v.prev_tag)return "none kept on disk";
  let out="PNX "+v.prev_tag;
  if(v.prev_client_version)out+=" (client "+v.prev_client_version+")";
  return out;
}
function renderVersion(s){
  const v=(s&&s.version)||{};
  const kv=$("#verKv");
  if(!kv)return;
  kv.innerHTML="";
  [["Engine","PowerNukkitX "+(v.tag||"-")],
   ["Bedrock protocol",v.protocol||"-"],
   ["Client version served",v.client_version||"-"],
   ["Installed",(v.installed_at||"-").replace("T"," ").replace("Z"," UTC")],
   ["Previous build",prevLabel(v)]]
  .forEach(([k,val])=>{kv.appendChild(el("dt",null,k));kv.appendChild(el("dd",null,val));});
  const p=$("#prevBtn");
  if(p)p.disabled=!v.prev_tag;

  const sel=$("#verPick");
  if(sel && s.releases){
    const have=sel.value;
    sel.innerHTML="";
    s.releases.forEach(r=>{
      const o=document.createElement("option");
      o.value=r.tag;
      o.textContent="PNX "+r.tag+"  \u00b7  serves Bedrock "+(r.client_version||"unknown")
        +"  \u00b7  protocol "+r.protocol
        +(r.current?"  \u2190 installed":(r.is_previous?"  \u2190 previous build":""));
      o.disabled=r.current;
      sel.appendChild(o);
    });
    if(have && s.releases.some(r=>r.tag===have && !r.current))sel.value=have;
    const hint=$("#verHint");
    if(hint){
      const cur=s.releases.filter(r=>r.current)[0];
      hint.textContent=cur
        ?("Currently PNX "+cur.tag+", serving Bedrock "+(cur.client_version||"an unknown version")+
          ". Pick from the list, or install any other release by tag - clients on a different Bedrock release cannot join.")
        :"This build is not one of the pinned releases; use the field below to install one.";
    }
  }
}

/* ---------- boot ---------- */
(function boot(){
  const saved=localStorage.getItem("bambo.theme");
  if(saved==="light"||saved==="dark")document.documentElement.dataset.theme=saved;
  const wantLight=window.matchMedia&&window.matchMedia("(prefers-color-scheme: light)").matches;
  if(!document.documentElement.dataset.theme&&wantLight)document.documentElement.dataset.theme="light";
  $("#themeBtn").textContent="Theme: "+(document.documentElement.dataset.theme||"auto");
  wireActions();
  tick(true);
  tickLog();
})();
</script>"""

PAGE = PAGE_CSS_HTML + PAGE_JS
PAGE = PAGE.replace("__VERSION__", TOOL_VERSION)

CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
        "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


class H(BaseHTTPRequestHandler):
    server_version = "bambo-dash/" + TOOL_VERSION
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass  # we do our own structured request logging

    # -- helpers --
    def _client_ip(self):
        try:
            return self.client_address[0]
        except Exception:
            return "unknown"

    def _send(self, code, body, ctype="text/html"):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", CSP)
        if self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(b)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, code, obj):
        self._send(code, json.dumps(obj), "application/json")

    def _read_body(self):
        """Read a request body, enforcing a size cap.

        Either the body is consumed or the connection is closed: leaving bytes in
        the socket would be parsed as the next request on a keep-alive connection.
        """
        if self.headers.get("Transfer-Encoding", "").lower().strip() == "chunked":
            self.close_connection = True    # chunked has no declared length to cap
            return b"{}"
        try:
            n = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            n = 0
        if n > MAX_BODY:
            self.close_connection = True
            return None
        if n <= 0:
            return b"{}"
        return self.rfile.read(n) or b"{}"

    # -- GET --
    def do_GET(self):
        t0 = time.time()
        code = 200
        try:
            parts = urlparse(self.path)
            path, qs = parts.path, parse_qs(parts.query)
            if path == "/" or path.startswith("/index"):
                self._send(200, PAGE)
            elif path == "/api/health":
                self._json(200, {"ok": True})
            elif path == "/api/log":
                # The log rides its own endpoint: it is the biggest payload on the
                # page, so it must not ride in the 3s status poll.
                try:
                    lim = int((qs.get("limit") or ["400"])[0])
                except ValueError:
                    lim = 400
                lim = max(20, min(lim, 800))
                self._json(200, {"entries": parse_log(log_tail(lim)), "limit": lim})
            elif path == "/api/status":
                self._json(200, status())
            else:
                code = 404
                self._json(404, {"ok": False, "error": "not found"})
        except Exception as e:
            code = 500
            self._json(500, {"ok": False, "error": "internal error"})
            _log_line(REQ_LOG, {"ts": time.time(), "ip": self._client_ip(),
                                 "event": "get_exception", "exception": str(e)})
        log_request(self._client_ip(), "GET", self.path, code, (time.time() - t0) * 1000)

    # -- POST --
    def do_POST(self):
        t0 = time.time()
        code = 200
        ip = self._client_ip()
        try:
            if not self.path.startswith("/api/action"):
                code = 404
                self.close_connection = True   # a POST here carries a body we must not strand
                self._json(404, {"ok": False, "error": "not found"})
                return
            raw = self._read_body()
            if raw is None:
                code = 413
                self._json(413, {"ok": False, "error": "body too large"})
                return
            try:
                req = json.loads(raw)
            except Exception:
                code = 400
                self._json(400, {"ok": False, "error": "bad json"})
                return
            # token check (constant-time; bytes, because compare_digest raises
            # TypeError on non-ASCII str - that turned a wrong token into a 500
            # that skipped the rate limiter entirely)
            provided = str(req.get("token", "")).encode("utf-8", "replace")
            if not hmac.compare_digest(provided, TOKEN.encode("utf-8", "replace")):
                code = 401
                if rate_limited(ip):
                    code = 429
                    self._json(429, {"ok": False, "error": "too many attempts",
                                      "retry_after": int(FAIL_WINDOW)})
                else:
                    self._json(401, {"ok": False, "error": "bad token"})
                log_audit(ip, "auth", False, code)
                return
            action = req.get("action", "")
            if action in ACTIONS:
                argv = ACTIONS[action]
            elif action in ADMIN:
                args = req.get("args") or []
                if not isinstance(args, list) or len(args) > MAX_ARGS:
                    code = 400
                    self._json(400, {"ok": False, "error": "bad args"})
                    return
                sargs = []
                for a in args:
                    a = str(a)
                    if len(a) > MAX_ARG_LEN or "\n" in a or "\r" in a:
                        code = 400
                        self._json(400, {"ok": False, "error": "bad arg"})
                        return
                    sargs.append(a)
                argv = [BAMBO, action] + sargs
            else:
                code = 400
                self._json(400, {"ok": False, "error": "unknown action"})
                return
            r = sh(argv, timeout=SLOW_TIMEOUT if action in SLOW else 120)
            out = (r.stdout or "") + (r.stderr or "")
            with _cache_lock:
                _cache.clear()   # an action may have changed backups/join/state the page shows
            code = 200
            self._json(200, {"ok": r.returncode == 0, "code": r.returncode,
                             "output": out[-4000:]})
            log_audit(ip, action, r.returncode == 0, r.returncode, out[-200:])
        except Exception as e:
            code = 500
            self._json(500, {"ok": False, "error": "internal error"})
            _log_line(REQ_LOG, {"ts": time.time(), "ip": ip, "event": "post_exception",
                                 "exception": str(e)})
        finally:
            log_request(ip, "POST", self.path, code, (time.time() - t0) * 1000)


def main():
    ap = argparse.ArgumentParser(prog="bambo-dash")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8787)
    a = ap.parse_args()
    global LISTEN_HOST
    LISTEN_HOST = a.host
    if a.host != "127.0.0.1":
        print("WARNING: exposing on %s. Anyone on that network can control the server "
              "with the token. Token: %s" % (a.host, TOKEN))
    else:
        print("Token (localhost only, safer): %s" % TOKEN)
    print("bambo-dash v%s on http://%s:%d  (Ctrl-C to stop)" % (TOOL_VERSION, a.host, a.port))

    httpd = ThreadingHTTPServer((a.host, a.port), H)
    httpd.daemon_threads = True

    def _shutdown(signum, frame):
        print("\nbambo-dash: shutting down (signal %s)" % signum)
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
