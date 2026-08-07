#!/usr/bin/env bash
# Task 8 (U3) - subgraph hash forensics.
#
# Runs analyze_snapshot --shorebird over base.aot and all four sample .aot's,
# twice: once with default flags and once adding --no_pp_hash, which
# analyze_snapshot --help documents as:
#
#     --no_pp_hash   Ignore PP offsets when computing subgraph hashes.
#
# Results land in out/hash/<name>.json and out/hash/<name>.nopp.json, then
# compare_hashes.py is invoked over them.
#
# Usage:  bash -c 'source ./env.sh && ./probe_hash.sh'
#     or: ./probe_hash.sh          (sources env.sh itself)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -z "${ANALYZE_SNAPSHOT:-}" ]; then
  # shellcheck source=/dev/null
  source "$SCRIPT_DIR/env.sh"
fi

: "${OUT_DIR:=$SCRIPT_DIR/out}"
AOT_DIR="$OUT_DIR/aot"
HASH_DIR="$OUT_DIR/hash"
mkdir -p "$HASH_DIR"

NAMES="base s1_equal_len s2_diff_len s3_body s4_add"

FORCE="${FORCE:-0}"
MISSING=""

run_one() {
  # $1 = name, $2 = output suffix, $3.. = extra flags
  local name="$1" suffix="$2"
  shift 2
  local src="$AOT_DIR/$name.aot"
  local dst="$HASH_DIR/$name$suffix.json"

  if [ ! -f "$src" ]; then
    echo "MISSING input snapshot: $src" >&2
    MISSING="$MISSING $src"
    return 0
  fi

  if [ -s "$dst" ] && [ "$FORCE" != "1" ]; then
    echo "  reuse  $dst ($(stat -f%z "$dst") bytes)  [FORCE=1 to regenerate]"
    return 0
  fi

  echo "  run    analyze_snapshot --shorebird $* --out=$dst  $src"
  if ! "$ANALYZE_SNAPSHOT" --shorebird "$@" --out="$dst" "$src" >"$dst.log" 2>&1; then
    echo "FAILED: analyze_snapshot exited non-zero for $src $*; see $dst.log" >&2
    cat "$dst.log" >&2
    if grep -q "Unrecognized flags" "$dst.log" 2>/dev/null; then
      echo "  NOTE: the flag is listed under 'Shorebird options' in --help but is" >&2
      echo "        rejected by the VM flag parser of this product-mode binary," >&2
      echo "        i.e. documented-but-not-compiled-in. Not a driver error." >&2
    fi
    MISSING="$MISSING $dst"
    rm -f "$dst"
    return 0
  fi
  if [ ! -s "$dst" ]; then
    echo "FAILED: analyze_snapshot produced no/empty output at $dst" >&2
    MISSING="$MISSING $dst"
    return 0
  fi
  echo "         -> $(stat -f%z "$dst") bytes"
}

echo "== analyze_snapshot --shorebird (default flags) =="
for n in $NAMES; do
  run_one "$n" ""
done

echo
echo "== analyze_snapshot --shorebird --no_pp_hash =="
for n in $NAMES; do
  run_one "$n" ".nopp" --no_pp_hash
done

echo
if [ -n "$MISSING" ]; then
  echo "!!! MISSING / FAILED artifacts:" >&2
  for m in $MISSING; do echo "  - $m" >&2; done
  echo "!!! compare_hashes.py will report these cells as MISSING." >&2
fi

echo
echo "== compare_hashes.py =="
exec "$PY" "$SCRIPT_DIR/compare_hashes.py" "$HASH_DIR"
