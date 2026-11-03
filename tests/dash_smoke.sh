#!/usr/bin/env bash
# tests/dash_smoke.sh - start the dashboard on a scratch port and exercise the API.
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=tests/lib.sh
. "$DIR/lib.sh"

t "dashboard smoke"
PORT=8791
TOK="test-token-for-smoke"
export BAMBO_DASH_TOKEN="$TOK"

python3 "$ROOT/bin/bambo-dash.py" --host 127.0.0.1 --port $PORT >/tmp/bambo-dash-smoke.log 2>&1 &
DPID=$!
# Poll for readiness: a fixed sleep made this suite race the interpreter's startup
# and report 10 phantom failures whenever the machine was busy.
ready=0
for i in $(seq 1 100); do
  if curl -s -m 1 -o /dev/null "http://127.0.0.1:$PORT/api/health" 2>/dev/null; then ready=1; break; fi
  kill -0 "$DPID" 2>/dev/null || break
  sleep 0.1
done
if [ "$ready" != 1 ]; then
  fail "dashboard never answered /api/health (log: $(tail -3 /tmp/bambo-dash-smoke.log 2>/dev/null))"
  kill -TERM "$DPID" 2>/dev/null
  summary
fi

# page + headers
hdr="$(curl -s -D - -o /dev/null http://127.0.0.1:$PORT/)"
check_contains "$hdr" "200 OK" "GET / returns 200"
check_contains "$hdr" "Content-Security-Policy" "CSP header present"
check_contains "$hdr" "X-Content-Type-Options: nosniff" "nosniff header present"
check_contains "$hdr" "X-Frame-Options: DENY" "frame deny header present"

# health
out="$(curl -s http://127.0.0.1:$PORT/api/health)"
check_contains "$out" '"ok": true' "health endpoint"

# status
out="$(curl -s http://127.0.0.1:$PORT/api/status)"
echo "$out" | python3 -m json.tool >/dev/null 2>&1 && ok "status is valid JSON" || fail "status invalid"
check_contains "$out" '"running"' "status has running key"

# The log tail must strip §-codes without deleting the letters they are named
# after: the old translate() ate every e/a/b/r/c/6 and turned the log into noise.
python3 - "$ROOT/bin/bambo-dash.py" <<'PY'
import importlib.util, os, sys, tempfile
spec = importlib.util.spec_from_file_location("dash", sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
fd, path = tempfile.mkstemp(suffix=".log"); os.close(fd)
with open(path, "w") as f:
    f.write("§aLoading pnx.yml\n§eSelected English (eng) as the base language\n\x1b[0m§bDone (50.5s)!\n")
m.SERVER_LOG = path
out = m.log_tail()
os.unlink(path)
missing = [w for w in ("Loading", "Selected", "English", "base", "language", "Done", "50.5") if w not in out]
if missing:
    print("mangled, lost words: %s" % ",".join(missing)); sys.exit(1)
if "§" in out or "\x1b" in out:
    print("colour/ANSI codes left in output"); sys.exit(1)
PY
[ $? = 0 ] && ok "log tail strips colour codes without eating letters" \
           || fail "log tail mangles the server log"

# bad token -> 401
code="$(curl -s -o /dev/null -w '%{http_code}' -X POST http://127.0.0.1:$PORT/api/action \
  -H 'content-type: application/json' -d '{"token":"wrong","action":"start"}')"
check "$code" "401" "bad token rejected"

# unknown action with good token -> 400
code="$(curl -s -o /dev/null -w '%{http_code}' -X POST http://127.0.0.1:$PORT/api/action \
  -H 'content-type: application/json' -d "{\"token\":\"$TOK\",\"action\":\"nope\"}")"
check "$code" "400" "unknown action rejected"

# good action (config get motd runs against the real repo; server may be stopped)
out="$(curl -s -X POST http://127.0.0.1:$PORT/api/action \
  -H 'content-type: application/json' -d "{\"token\":\"$TOK\",\"action\":\"config\",\"args\":[\"get\",\"motd\"]}")"
echo "$out" | python3 -c 'import json,sys; sys.exit(0 if json.load(sys.stdin).get("ok") else 1)' \
  && ok "config get action succeeds" || fail "config get action failed: $out"

out="$(curl -s -X POST http://127.0.0.1:$PORT/api/action \
  -H 'content-type: application/json' -d "{\"token\":\"$TOK\",\"action\":\"world\",\"args\":[\"list\"]}")"
echo "$out" | python3 -c 'import json,sys; sys.exit(0 if json.load(sys.stdin).get("ok") else 1)' \
  && ok "world list action succeeds" || fail "world list action failed: $out"

# oversized body -> 413
python3 - "$PORT" <<'PY'
import json, sys, urllib.request
port = sys.argv[1]
req = urllib.request.Request(
    "http://127.0.0.1:%s/api/action" % port,
    data=b"x" * 70000,
    headers={"content-type": "application/json"},
    method="POST",
)
try:
    urllib.request.urlopen(req, timeout=5)
    raise SystemExit("should have failed")
except urllib.error.HTTPError as e:
    sys.exit(0 if e.code == 413 else 1)
PY
[ $? = 0 ] && ok "oversized body -> 413" || fail "oversized body not rejected"

# rate limiting: 15 bad tokens -> eventually 429
last=""
for i in $(seq 1 15); do
  last="$(curl -s -o /dev/null -w '%{http_code}' -X POST http://127.0.0.1:$PORT/api/action \
    -H 'content-type: application/json' -d '{"token":"x","action":"start"}')"
done
check "$last" "429" "brute force rate-limited"

# graceful shutdown
kill -TERM $DPID
wait $DPID
rc=$?
check "$rc" "0" "graceful shutdown on SIGTERM"

[ -s "$ROOT/logs/dash.log" ] && ok "request log written" || fail "request log missing"
[ -s "$ROOT/logs/dash-audit.log" ] && ok "audit log written" || fail "audit log missing"

summary
