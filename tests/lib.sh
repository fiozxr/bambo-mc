#!/usr/bin/env bash
# tests/lib.sh - shared helpers for the bambo-mc test suite.
set -uo pipefail

ROOT="${ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

PASS=0
FAIL=0
CURRENT_TEST=""

t() { CURRENT_TEST="$1"; }
ok() { PASS=$((PASS+1)); echo "  PASS  $CURRENT_TEST: $1"; }
fail() { FAIL=$((FAIL+1)); echo "  FAIL  $CURRENT_TEST: $1"; }
check() { if [ "$1" = "$2" ]; then ok "$3"; else fail "$3 (want [$2] got [$1])"; fi; }
check_contains() { case "$1" in *"$2"*) ok "$3";; *) fail "$3 (missing [$2] in [$1])";; esac; }
check_empty() { [ -z "$1" ] && ok "$2" || fail "$2 (non-empty: $1)"; }

summary() {
  echo
  echo "== $CURRENT_TEST: $PASS passed, $FAIL failed =="
  [ "$FAIL" = 0 ]
}

# build a throwaway repo fixture rooted at a temp dir
make_fixture() {
  local base
  base="$(mktemp -d /tmp/bambo-test.XXXXXX)"
  mkdir -p "$base/runtime/backups" "$base/server" "$base/runtime/worlds/world/db"
  cp "$ROOT/server/pnx.yml" "$base/server/pnx.yml"
  cp "$ROOT/server/pnx.yml" "$base/runtime/pnx.yml"
  cp "$ROOT/install.sh" "$base/install.sh"
  cp "$ROOT/config.example" "$base/config.example"
  printf 'MANIFEST-000000\n' > "$base/runtime/worlds/world/db/CURRENT"
  : > "$base/runtime/worlds/world/db/MANIFEST-000000"
  echo "$base"
}
