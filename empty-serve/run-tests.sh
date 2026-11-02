#!/usr/bin/env bash
# empty-serve build + test runner.
#
# Builds every layer, runs each class's built-in self-test main(), then starts the
# servers on scratch UDP ports and runs the python structural probes against them.
# Pure local: no network, no third-party deps. Exit 0 = all green.
set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1
SRC=src/esnet
OUT=out

echo "== build =="
rm -rf "$OUT"
mkdir -p "$OUT"
javac -d "$OUT" "$SRC"/*.java || { echo "BUILD FAILED"; exit 1; }
echo "  compiled $(ls "$SRC"/*.java | wc -l) classes"

fail=0
run() {
  echo "== $1 =="
  java -cp "$OUT" "$2" || { echo "  $1: FAILED"; fail=1; }
}

run "framing self-test"      esnet.Framing
run "crypto self-test"       esnet.Crypto
run "handshake JWT self-test" esnet.Handshake

# -- live probes (scratch ports; avoid 19132/19133 in case PNX runs) --
PING_PORT=19533
ES_PORT=19535
echo "== ping/pong probe =="
java -cp "$OUT" esnet.PingServer $PING_PORT >/tmp/es-ping.log 2>&1 &
P1=$!
sleep 1
python3 probe.py $PING_PORT || { echo "  ping probe FAILED"; fail=1; }
kill $P1 2>/dev/null; wait $P1 2>/dev/null

echo "== handshake probe =="
java -cp "$OUT" esnet.EsServer $ES_PORT >/tmp/es-handshake.log 2>&1 &
P2=$!
sleep 1
python3 handshake_probe.py $ES_PORT || { echo "  handshake probe FAILED"; fail=1; }
kill $P2 2>/dev/null; wait $P2 2>/dev/null

echo
if [ "$fail" = 0 ]; then
  echo "RESULT: ALL LAYERS OK"
  exit 0
else
  echo "RESULT: FAILURES PRESENT (see above)"
  exit 1
fi
