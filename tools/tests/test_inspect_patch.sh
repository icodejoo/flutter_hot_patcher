#!/usr/bin/env bash
# Test tools/inspect_patch.sh against known-good and known-bad dills.
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
INSPECT="$REPO_ROOT/tools/inspect_patch.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
FAILS=0

fail() { echo "FAIL: $1"; FAILS=$((FAILS+1)); }
pass() { echo "PASS: $1"; }

# Fixture: a valid single-function v02 patch.
cat > "$TMP/ok.dart" <<'EOF'
library;

@pragma('dyn-module:entry-point')
String greet() => 'INSPECT_OK';
EOF
"$REPO_ROOT/tools/build_ios_patch.sh" "$TMP/ok.dart" "$TMP/ok.dill" >/dev/null 2>&1 \
  || { echo "FATAL: fixture build failed"; exit 1; }

# 1. Valid v02 dill exits 0.
if "$INSPECT" "$TMP/ok.dill" >"$TMP/ok.out" 2>&1; then
  pass "valid v02 dill exits 0"
else
  fail "valid v02 dill should exit 0; got $?"; cat "$TMP/ok.out"
fi

# 2. Reports version 2.
grep -q "version: 2" "$TMP/ok.out" || fail "should report 'version: 2'"
grep -q "version: 2" "$TMP/ok.out" && pass "reports version 2"

# 3. Lists the entry point.
grep -q "entry_point: .*greet" "$TMP/ok.out" || fail "should list greet as entry_point"
grep -q "entry_point: .*greet" "$TMP/ok.out" && pass "lists greet entry point"

# 4. A v01 dill (version byte forced back to 1) must be rejected non-zero.
cp "$TMP/ok.dill" "$TMP/bad.dill"
python3 -c "
import sys
p = sys.argv[1]
d = bytearray(open(p,'rb').read())
d[4] = 1
open(p,'wb').write(d)
" "$TMP/bad.dill"
if "$INSPECT" "$TMP/bad.dill" >"$TMP/bad.out" 2>&1; then
  fail "v01 dill should exit non-zero"
else
  pass "v01 dill rejected"
fi

# 5. A non-dill file must be rejected non-zero.
echo "not a dill" > "$TMP/junk.bin"
if "$INSPECT" "$TMP/junk.bin" >/dev/null 2>&1; then
  fail "junk file should exit non-zero"
else
  pass "junk file rejected"
fi

echo "---"
[ "$FAILS" -eq 0 ] && { echo "ALL PASS"; exit 0; } || { echo "$FAILS FAILURE(S)"; exit 1; }
