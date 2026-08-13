#!/usr/bin/env bash
# tools/fhp build must turn a .dart file into a signed, verifiable patch bundle.
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
FAILS=0
fail() { echo "FAIL: $1"; FAILS=$((FAILS+1)); }
pass() { echo "PASS: $1"; }

PB_PY="$REPO_ROOT/tools/patch_builder/.venv/bin/python"
[ -x "$PB_PY" ] || {
  echo "FATAL: patch_builder venv missing. Run:"
  echo "  python3 -m venv tools/patch_builder/.venv"
  echo "  tools/patch_builder/.venv/bin/pip install -r tools/patch_builder/requirements.txt"
  exit 1
}

cat > "$TMP/patch.dart" <<'EOF'
library;

String _greet() => 'FHP_CLI_OK';

@pragma('dyn-module:entry-point')
Map<String, Function> patchEntry() => {'greet': _greet};
EOF

# Generate a throwaway signing keypair. keygen.py takes --out and writes
# private_key.pem / public_key.pem into it.
KEYDIR="$TMP/keys"
mkdir -p "$KEYDIR"
"$PB_PY" "$REPO_ROOT/tools/patch_builder/keygen.py" --out "$KEYDIR" >"$TMP/keygen.out" 2>&1 \
  || { echo "FATAL: keygen failed"; cat "$TMP/keygen.out"; exit 1; }
PRIV="$KEYDIR/private_key.pem"
[ -f "$PRIV" ] || { echo "FATAL: no private_key.pem in $KEYDIR"; ls -la "$KEYDIR"; exit 1; }

if "$REPO_ROOT/tools/fhp" build \
      --source "$TMP/patch.dart" \
      --private-key "$PRIV" \
      --patch-number 7 \
      --app-version "1.0+1" \
      --output-dir "$TMP/bundle" >"$TMP/fhp.out" 2>&1; then
  pass "fhp build exits 0"
else
  fail "fhp build failed"; cat "$TMP/fhp.out"; echo "$FAILS FAILURE(S)"; exit 1
fi

# The bundle must contain a v02 dill.
DILL="$TMP/bundle/bytecode/patch.dill"
if [ -f "$DILL" ]; then
  pass "bundle contains bytecode/patch.dill"
  if "$REPO_ROOT/tools/inspect_patch.sh" "$DILL" --quiet >"$TMP/ins.out" 2>&1; then
    pass "bundled dill is valid v02"
  else
    fail "bundled dill is not valid v02"; cat "$TMP/ins.out"
  fi
else
  fail "bundle is missing bytecode/patch.dill"; find "$TMP/bundle" -type f
fi

# The bundle must be signed and carry a manifest.
if [ -f "$TMP/bundle/manifest.json" ]; then
  pass "bundle contains manifest.json"
else
  fail "bundle is missing manifest.json"
fi
if find "$TMP/bundle" -type f | grep -qiE "\.sig$|signature"; then
  pass "bundle contains a signature"
else
  fail "bundle has no signature file"; find "$TMP/bundle" -type f
fi

# patch_number must round-trip into the manifest.
if [ -f "$TMP/bundle/manifest.json" ]; then
  if python3 -c "
import json,sys
m = json.load(open(sys.argv[1]))
sys.exit(0 if m.get('patch_number') == 7 else 1)
" "$TMP/bundle/manifest.json" 2>/dev/null; then
    pass "manifest patch_number == 7"
  else
    fail "manifest patch_number != 7"
    head -20 "$TMP/bundle/manifest.json"
  fi
fi

# The entry point must be recorded so the runtime knows what to invoke.
if [ -f "$TMP/bundle/manifest.json" ]; then
  if grep -q "patchEntry" "$TMP/bundle/manifest.json"; then
    pass "manifest records the patchEntry entry point"
  else
    fail "manifest does not mention patchEntry"
    head -20 "$TMP/bundle/manifest.json"
  fi
fi

# inspect subcommand must work too.
"$REPO_ROOT/tools/fhp" inspect "$DILL" --quiet >/dev/null 2>&1 \
  && pass "fhp inspect works" || fail "fhp inspect failed"

echo "---"
[ "$FAILS" -eq 0 ] && { echo "ALL PASS"; exit 0; } || { echo "$FAILS FAILURE(S)"; exit 1; }
