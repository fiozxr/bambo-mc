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
import hmac
import html
import io
import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOOL_VERSION = "2.5.3"
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
LOG_DIR = os.path.join(ROOT, "logs")
REQ_LOG = os.path.join(LOG_DIR, "dash.log")
AUDIT_LOG = os.path.join(LOG_DIR, "dash-audit.log")

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
ADMIN = {"players", "op", "whitelist", "world", "user", "plugins", "broadcast", "tps", "cmd", "motd", "config"}


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
def sh(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=120, cwd=ROOT)
    except Exception as e:
        return subprocess.CompletedProcess(cmd, 1, "", str(e))


def running():
    return subprocess.run(["tmux", "has-session", "-t", SESSION],
                          capture_output=True).returncode == 0


def port_bound():
    return any((":%d" % PORT) in line
               for line in sh(["ss", "-lun"]).stdout.splitlines())


def join_line():
    out = sh([BAMBO, "join"]).stdout
    for l in out.splitlines():
        if "address" in l:
            return l.split("address", 1)[1].strip()
    return "(run bambo join manually)"


def log_tail(n=200):
    if not os.path.exists(SERVER_LOG):
        return "(no log yet)"
    with io.open(SERVER_LOG, "r", errors="replace") as f:
        lines = f.readlines()[-n:]
    return "".join(lines).translate({ord(c): None for c in "§eabrc6"})


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


def status():
    return {
        "running": running(),
        "port_bound": port_bound(),
        "join": join_line(),
        "backups": backups(),
        "others": other_servers(),
        "players": None,   # not polled; see console
    }
PAGE_CSS_HTML = """<!doctype html><meta charset=utf-8><title>bambo-mc admin</title>
<style>
 :root{--glass:rgba(255,255,255,.06);--stroke:rgba(255,255,255,.14);--txt:#e9edf5;--mut:#9aa4b8;
   --accent:#6ea8fe;--ok:#57e6b0;--bad:#ff8f8f}
 *{box-sizing:border-box}
 html,body{margin:0;min-height:100%}
 body{font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,system-ui,sans-serif;color:var(--txt);
   background:#0c0f16;-webkit-font-smoothing:antialiased;
   background-image:radial-gradient(900px 520px at 10% -10%,rgba(80,120,255,.30),transparent),
     radial-gradient(720px 520px at 98% -4%,rgba(140,90,255,.22),transparent),
     radial-gradient(680px 620px at 50% 122%,rgba(40,180,160,.18),transparent);
   background-attachment:fixed}
 header.bar{display:flex;align-items:center;justify-content:space-between;gap:12px;
   padding:18px 22px;position:sticky;top:0;z-index:5;
   background:rgba(12,15,22,.55);backdrop-filter:blur(20px) saturate(160%);-webkit-backdrop-filter:blur(20px) saturate(160%);
   border-bottom:1px solid var(--stroke)}
 .brand{display:flex;align-items:center;gap:12px}
 .logo{width:40px;height:40px;border-radius:12px;background:linear-gradient(135deg,#6ea8fe,#8b5cff);
   box-shadow:0 8px 22px rgba(95,110,255,.4);display:grid;place-items:center;font-weight:800;color:#fff}
 .brand h1{font-size:19px;margin:0;font-weight:650;letter-spacing:.2px}
 .brand p{margin:0;color:var(--mut);font-size:12.5px}
 main{max-width:1000px;margin:0 auto;padding:22px 20px 70px}
 .card{background:var(--glass);backdrop-filter:blur(18px) saturate(165%);-webkit-backdrop-filter:blur(18px) saturate(165%);
   border:1px solid var(--stroke);border-radius:16px;padding:16px 18px;margin:14px 0;
   box-shadow:0 10px 34px rgba(0,0,0,.30)}
 .card>b{display:block;font-size:12px;text-transform:uppercase;letter-spacing:.7px;color:var(--mut);margin-bottom:11px}
 .row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
 .pill{padding:3px 12px;border-radius:999px;font-weight:700;font-size:12px;border:1px solid var(--stroke)}
 .up{background:rgba(55,211,153,.16);color:var(--ok);border-color:rgba(55,211,153,.4)}
 .down{background:rgba(255,107,107,.14);color:var(--bad);border-color:rgba(255,107,107,.36)}
 input,button{font:inherit;color:var(--txt);background:rgba(255,255,255,.05);border:1px solid var(--stroke);
   border-radius:10px;padding:8px 12px}
 button{cursor:pointer;background:linear-gradient(135deg,rgba(110,168,254,.25),rgba(139,92,255,.18))}
 button:hover{border-color:var(--accent)}
 pre{background:rgba(0,0,0,.35);border:1px solid var(--stroke);border-radius:12px;padding:12px;
   font:12.5px/1.55 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;overflow:auto;margin:10px 0 0}
 small{color:var(--mut)}
 #tok{width:100%;max-width:360px;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:13px}
</style>
<header class=bar><div class=brand><div class=logo>>_</div><div><h1>bambo-mc</h1>
 <p>admin &middot; v__VERSION__ &middot; local</p></div></div>
 <div class=row><input id=tok type=password placeholder="token (saved in this browser)" autocomplete=off>
 <button id=savetok>save</button><button id=reload>refresh</button></div></header>
<main>
 <div class=card><b>State</b><div id=state class=row>…</div></div>
 <div class=card><b>Power</b><div class=row>
   <button data-a=start>start</button><button data-a=stop>stop</button>
   <button data-a=restart>restart</button><button data-a=backup>backup (force)</button></div>
   <pre id=out style="display:none"></pre></div>
 <div class=card><b>Players</b><button data-run="players|list">list</button><pre id=pplayers style="display:none"></pre></div>
 <div class=card><b>Operators</b><div class=row>
   <input id=opname placeholder="gamertag">
   <button data-op=add>add</button><button data-op=del>remove</button>
   <button data-run="op|list">list</button></div>
   <pre id=pops style="display:none"></pre></div>
 <div class=card><b>Whitelist</b><div class=row>
   <input id=wlname placeholder="gamertag">
   <button data-wl=add>add</button><button data-wl=remove>remove</button>
   <button data-run="whitelist|list">list</button>
   <button data-wl=on>on</button><button data-wl=off>off</button></div>
   <pre id=pwhl style="display:none"></pre></div>
 <div class=card><b>Worlds</b><div class=row>
   <button data-run="world|list">list</button>
   <button data-run="world|save">save-all</button></div>
   <div class=row style="margin-top:8px">
     <input id=world_new placeholder="new world name">
     <button id=world_create>create</button>
     <input id=world_old placeholder="old name"><input id=world_ren placeholder="new name">
     <button id=world_rename>rename</button></div>
   <div class=row>
     <input id=world_def placeholder="set as default world">
     <button id=world_default>make default</button>
     <input id=world_del placeholder="delete world">
     <label><input type=checkbox id=world_del_force> <small>force</small></label>
     <button id=world_delete>move to trash</button></div>
   <small>world changes require the server to be stopped; delete moves to runtime/.trash (reversible)</small>
   <pre id=pworld style="display:none"></pre></div>
 <div class=card><b>Users</b><div class=row>
   <button data-run="user|list">online list</button>
   <button data-run="op|list">ops</button></div>
   <div class=row style="margin-top:8px">
     <input id=user_ban_name placeholder="player to ban">
     <button id=user_ban>ban</button>
     <input id=user_unban_name placeholder="player to unban">
     <button id=user_unban>unban</button></div>
   <div class=row>
     <input id=user_kick_name placeholder="player to kick">
     <button id=user_kick>kick</button>
     <select id=user_gm_mode><option value=0>survival</option><option value=1>creative</option><option value=2>adventure</option><option value=3>spectator</option></select>
     <input id=user_gm_player placeholder="player (blank=all)">
     <button id=user_gm>gamemode</button></div>
   <small>ban / unban / kick / gamemode act on the live server</small>
   <pre id=pusers style="display:none"></pre></div>
 <div class=card><b>Server utilities</b><div class=row>
   <button id=plugins>plugins</button>
   <button id=tps>tps</button>
   <input id=bc_msg placeholder="message to everyone" style="flex:1">
   <button id=broadcast>broadcast</button></div>
   <pre id=pplugins style="display:none"></pre></div>
 <div class=card><b>Console command</b><div class=row>
   <input id=cmdline placeholder="/gamemode creative Steve" style="flex:1">
   <button id=run_cmd>Run</button></div>
   <small>raw operator pass-through to the server console &mdash; powerful, token required</small>
   <pre id=pcmd style="display:none"></pre></div>
 <div class=card><b>Server name (MOTD)</b><div class=row>
   <input id=motd1 placeholder="bambo-mc">
   <input id=motd2 placeholder="sub-line (optional)">
   <button id=save_motd>Save &amp; restart</button></div>
   <small>this is the name shown in the client server list &mdash; saves config and <b>restarts the server</b> (~40s)</small>
   <pre id=pmotd style="display:none"></pre></div>
 <div class=card><b>Backups <small id=bc></small></b><pre id=bk>loading&hellip;</pre></div>
 <div class=card><b>Other servers <small>detected, not managed here</small></b><pre id=other></pre></div>
 <div class=card><b>Log tail</b><pre id=log></pre></div>
</main>"""

PAGE_JS = """<script>
const $=s=>document.querySelector(s);
function esc(s){const d=document.createElement('div');d.textContent=s==null?'':String(s);return d.innerHTML}
function tok(){return $('#tok').value.trim()}
$('#savetok').onclick=()=>{localStorage.setItem('es_tok',tok());};
window.addEventListener('load',()=>{const t=localStorage.getItem('es_tok'); if(t) $('#tok').value=t;});
async function j(u,o){const r=await fetch(u,o);return r.json()}
async function refresh(){
  try{
    const s=await j('/api/status');
    const up=s.running?'up':'down';
    $('#state').innerHTML=
      `<span class="pill ${up}">${s.running?'RUNNING':'STOPPED'}</span>
       <span>UDP :19132 ${s.port_bound?'bound':'not bound'}</span>
       <span>join ${esc(s.join)}</span>`;
    $('#bc').textContent=`(${s.backups.length} kept)`;
    $('#bk').textContent=s.backups.join('\n')||'(none)';
    $('#other').textContent=s.others.join('\n')||'(none detected)';
    $('#log').textContent=s.log||'(empty)';
  }catch(e){$('#state').innerHTML='<span class="pill down">dashboard offline</span>'}
}
async function post(body){
  body.token=tok();
  const r=await fetch('/api/action',{method:'POST',
    headers:{'content-type':'application/json'},body:JSON.stringify(body)});
  return r.json();
}
async function power(a){
  const el=$('#out'); el.style.display='block'; el.textContent='running: '+a;
  const d=await post({action:a});
  el.textContent=(d.ok?'OK\n':'ERROR\n')+(d.output||JSON.stringify(d)); refresh();
}
async function run(action,args,sel){
  const el=$(sel); el.style.display='block'; el.textContent='…';
  const d=await post({action,args});
  el.textContent=(d.ok?'':'ERROR\n')+(d.output||JSON.stringify(d));
}
document.querySelectorAll('button[data-a]').forEach(b=>b.onclick=()=>power(b.dataset.a));
document.querySelectorAll('button[data-run]').forEach(b=>b.onclick=()=>{
  const [a,...rest]=b.dataset.run.split('|');
  const sel={players:'#pplayers',op:'#pops',whitelist:'#pwhl',world:'#pworld'}[a];
  run(a,rest,sel);
});
document.querySelectorAll('button[data-op]').forEach(b=>b.onclick=()=>{
  const n=$('#opname').value.trim(); if(!n){$('#pops').textContent='enter a name';return;}
  run('op',[b.dataset.op,n],'#pops');
});
document.querySelectorAll('button[data-wl]').forEach(b=>b.onclick=()=>{
  const s=b.dataset.wl, n=$('#wlname').value.trim();
  if((s==='add'||s==='remove')&&!n){$('#pwhl').textContent='enter a name';return;}
  run('whitelist',[s,...(n?[n]:[])],'#pwhl');
});
$('#run_cmd').onclick=()=>{
  const c=$('#cmdline').value.trim(); if(!c){$('#pcmd').textContent='type a command';return;}
  run('cmd',[c],'#pcmd');
};
$('#save_motd').onclick=()=>{
  const a=$('#motd1').value.trim(); if(!a){$('#pmotd').textContent='enter a name';return;}
  const b=$('#motd2').value.trim();
  const el=$('#pmotd'); el.style.display='block';
  el.textContent='saving + restarting the server (~40s)...';
  run('motd',[a,b],'#pmotd');
};
$('#world_create').onclick=()=>{const n=$('#world_new').value.trim(); if(!n){$('#pworld').textContent='enter a name';return;} run('world',['create',n],'#pworld');};
$('#world_rename').onclick=()=>{const a=$('#world_old').value.trim(), b=$('#world_ren').value.trim(); if(!a||!b){$('#pworld').textContent='enter old and new names';return;} run('world',['rename',a,b],'#pworld');};
$('#world_delete').onclick=()=>{const n=$('#world_del').value.trim(); if(!n){$('#pworld').textContent='enter a name';return;} const f=$('#world_del_force').checked?'--force':''; run('world',['delete',n,...(f?[f]:[])],'#pworld');};
$('#world_default').onclick=()=>{const n=$('#world_def').value.trim(); if(!n){$('#pworld').textContent='enter a name';return;} run('world',['default',n],'#pworld');};
$('#user_ban').onclick=()=>{const n=$('#user_ban_name').value.trim(); if(!n){$('#pusers').textContent='enter a name';return;} run('user',['ban',n],'#pusers');};
$('#user_unban').onclick=()=>{const n=$('#user_unban_name').value.trim(); if(!n){$('#pusers').textContent='enter a name';return;} run('user',['unban',n],'#pusers');};
$('#user_kick').onclick=()=>{const n=$('#user_kick_name').value.trim(); if(!n){$('#pusers').textContent='enter a name';return;} run('user',['kick',n],'#pusers');};
$('#user_gm').onclick=()=>{const m=$('#user_gm_mode').value, n=$('#user_gm_player').value.trim(); run('user',['gamemode',m,...(n?[n]:[])],'#pusers');};
$('#plugins').onclick=()=>run('plugins',[],'#pplugins');
$('#tps').onclick=()=>run('tps',[],'#pplugins');
$('#broadcast').onclick=()=>{const m=$('#bc_msg').value.trim(); if(!m){$('#pplugins').textContent='enter a message';return;} run('broadcast',[m],'#pplugins');};
refresh();setInterval(refresh,3000);
</script>"""

PAGE = (PAGE_CSS_HTML + PAGE_JS).replace("__VERSION__", TOOL_VERSION)
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
        """Read a request body, enforcing a size cap."""
        try:
            n = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            n = 0
        if n > MAX_BODY:
            return None
        if n <= 0:
            return b"{}"
        return self.rfile.read(n) or b"{}"

    # -- GET --
    def do_GET(self):
        t0 = time.time()
        code = 200
        try:
            if self.path == "/" or self.path.startswith("/index"):
                self._send(200, PAGE)
            elif self.path == "/api/health":
                self._json(200, {"ok": True})
            elif self.path.startswith("/api/status"):
                s = status()
                s["log"] = log_tail()
                self._json(200, s)
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
            # token check (constant-time)
            provided = str(req.get("token", ""))
            if not hmac.compare_digest(provided, TOKEN):
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
            r = sh(argv)
            out = (r.stdout or "") + (r.stderr or "")
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
