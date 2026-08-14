#!/usr/bin/env bash
# A patch importing dart:math and dart:convert must compile to a dill whose
# module actually contains the importing functions.
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
FAILS=0
fail() { echo "FAIL: $1"; FAILS=$((FAILS+1)); }
pass() { echo "PASS: $1"; }

SRC="$REPO_ROOT/tools/tests/fixtures/with_imports.dart"
DILL="$TMP/imports.dill"

if "$REPO_ROOT/tools/build_ios_patch.sh" "$SRC" "$DILL" >"$TMP/build.out" 2>&1; then
  pass "source with dart:math + dart:convert compiles"
else
  fail "compile failed"; cat "$TMP/build.out"; echo "$FAILS FAILURE(S)"; exit 1
fi

"$REPO_ROOT/tools/inspect_patch.sh" "$DILL" >"$TMP/inspect.out" 2>&1 \
  || { fail "inspect rejected the dill"; cat "$TMP/inspect.out"; }

grep -q "version: ${FHP_KBC_VERSION:-1}" "$TMP/inspect.out" && pass "format version matches target VM" || fail "format version does not match target VM"

grep -q "entry_point: .*::patchEntry\$" "$TMP/inspect.out" \
  && pass "entry point is patchEntry" || fail "entry point is not patchEntry"

for fn in _greet _encodeState patchEntry; do
  grep -q "^function: $fn\$" "$TMP/inspect.out" \
    && pass "function $fn compiled" || fail "function $fn MISSING"
done

# The imported members must appear in the disassembly, proving the imports were
# resolved rather than dropped. Each is checked separately so a failure names
# the library that did not resolve.
grep -qE "jsonEncode|_JsonStringStringifier|convert" "$TMP/inspect.out" \
  && pass "dart:convert members referenced" || fail "no dart:convert reference"
grep -qE "sqrt|math::|\bmax\b" "$TMP/inspect.out" \
  && pass "dart:math members referenced" || fail "no dart:math reference"

echo "---"
[ "$FAILS" -eq 0 ] && { echo "ALL PASS"; exit 0; } || { echo "$FAILS FAILURE(S)"; exit 1; }
