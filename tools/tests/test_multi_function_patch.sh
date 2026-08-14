#!/usr/bin/env bash
# A multi-function patch must compile to ONE dill with exactly one
# dyn-module entry point (a no-arg map factory) plus every patched function.
#
# dart2bytecode rejects a second @pragma('dyn-module:entry-point') outright
# ("Duplicate Dynamic Module Entry Points") and rejects any entry point that
# takes arguments, so the map-of-closures shape is the only way to ship several
# functions in one patch. Both rejections are asserted here so a future
# toolchain change that relaxes them is noticed rather than silently assumed.
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
FAILS=0
fail() { echo "FAIL: $1"; FAILS=$((FAILS+1)); }
pass() { echo "PASS: $1"; }

SRC="$REPO_ROOT/tools/tests/fixtures/multi_function.dart"
DILL="$TMP/multi.dill"

if "$REPO_ROOT/tools/build_ios_patch.sh" "$SRC" "$DILL" >"$TMP/build.out" 2>&1; then
  pass "multi-function source compiles"
else
  fail "compile failed"; cat "$TMP/build.out"; echo "$FAILS FAILURE(S)"; exit 1
fi

"$REPO_ROOT/tools/inspect_patch.sh" "$DILL" --quiet >"$TMP/inspect.out" 2>&1 \
  || { fail "inspect rejected the dill"; cat "$TMP/inspect.out"; }

grep -q "version: ${FHP_KBC_VERSION:-1}" "$TMP/inspect.out" && pass "format version matches target VM" || fail "format version does not match target VM"

# Exactly one entry point, and it is the map factory.
COUNT=$(grep '^entry_point_count:' "$TMP/inspect.out" | awk '{print $2}')
if [ "$COUNT" = "1" ]; then
  pass "entry_point_count == 1"
else
  fail "entry_point_count == $COUNT, expected 1"
fi
grep -q "entry_point: .*::patchEntry\$" "$TMP/inspect.out" \
  && pass "entry point is patchEntry" || fail "entry point is not patchEntry"

# Every patched function must be present in the compiled module.
for fn in _greet _addNumbers _describe patchEntry; do
  grep -q "^function: $fn\$" "$TMP/inspect.out" \
    && pass "function $fn compiled" || fail "function $fn MISSING"
done

# --- Guard the two toolchain constraints this design exists to work around ---

# A second entry point must be rejected.
cat > "$TMP/dup.dart" <<'EOF'
library;

@pragma('dyn-module:entry-point')
String a() => 'a';

@pragma('dyn-module:entry-point')
String b() => 'b';
EOF
if "$REPO_ROOT/tools/build_ios_patch.sh" "$TMP/dup.dart" "$TMP/dup.dill" >"$TMP/dup.out" 2>&1; then
  fail "two entry points should be rejected but compiled"
else
  if grep -q "Duplicate Dynamic Module Entry Points" "$TMP/dup.out"; then
    pass "two entry points rejected with the expected message"
  else
    fail "two entry points rejected, but not for the expected reason"
    head -3 "$TMP/dup.out"
  fi
fi

# An entry point taking arguments must be rejected.
cat > "$TMP/args.dart" <<'EOF'
library;

@pragma('dyn-module:entry-point')
int addNumbers(int a, int b) => a + b;
EOF
if "$REPO_ROOT/tools/build_ios_patch.sh" "$TMP/args.dart" "$TMP/args.dill" >"$TMP/args.out" 2>&1; then
  fail "an entry point with arguments should be rejected but compiled"
else
  if grep -q "should be a static no-argument method" "$TMP/args.out"; then
    pass "entry point with arguments rejected with the expected message"
  else
    fail "entry point with arguments rejected, but not for the expected reason"
    head -3 "$TMP/args.out"
  fi
fi

echo "---"
[ "$FAILS" -eq 0 ] && { echo "ALL PASS"; exit 0; } || { echo "$FAILS FAILURE(S)"; exit 1; }
