#!/usr/bin/env bash
# Inspect a v02 DBC3 patch dill: verify magic + version, list dynamic-module
# entry points, and disassemble the bytecode.
#
# Usage: inspect_patch.sh <patch.dill> [--quiet]
# Exit:  0 = valid v02 DBC3, non-zero = invalid
set -euo pipefail

DILL="${1:?Usage: $0 <patch.dill> [--quiet]}"
QUIET="${2:-}"

ENGINE_SRC=~/engine_ios/src
DART_JIT=$ENGINE_SRC/out/host_release/dart
DUMP_BC_SRC=$ENGINE_SRC/third_party/dart/pkg/dart2bytecode/bin/dump_bytecode.dart

[ -f "$DILL" ] || { echo "ERROR: no such file: $DILL" >&2; exit 1; }

# --- Header check: magic "3CBD" + uint32 LE version == 2 --------------------
python3 - "$DILL" <<'PY'
import struct, sys
path = sys.argv[1]
with open(path, 'rb') as f:
    head = f.read(8)
if len(head) < 8:
    print(f"ERROR: {path} is too short to be a DBC3 dill ({len(head)} bytes)", file=sys.stderr)
    sys.exit(2)
magic = head[:4]
if magic != b'3CBD':
    print(f"ERROR: bad magic {magic!r} (expected b'3CBD')", file=sys.stderr)
    sys.exit(3)
version = struct.unpack('<I', head[4:8])[0]
print("magic: 3CBD")
print(f"version: {version}")
if version != 2:
    print(f"ERROR: bytecode format version {version}, but the iOS X1 engine "
          f"only accepts version 2. Rebuild with tools/dart2bytecode_v2.",
          file=sys.stderr)
    sys.exit(4)
PY

SIZE=$(wc -c < "$DILL" | tr -d ' ')
echo "size: ${SIZE}"

# --- Disassemble ------------------------------------------------------------
[ -x "$DART_JIT" ] || { echo "ERROR: dart not found at $DART_JIT" >&2; exit 5; }
[ -f "$DUMP_BC_SRC" ] || { echo "ERROR: dump_bytecode.dart not found at $DUMP_BC_SRC" >&2; exit 5; }

DUMP="$(mktemp)"
trap 'rm -f "$DUMP"' EXIT
if ! "$DART_JIT" "$DUMP_BC_SRC" "$DILL" > "$DUMP" 2>&1; then
    echo "ERROR: dump_bytecode failed:" >&2
    cat "$DUMP" >&2
    exit 6
fi

# Entry points are printed as "Dynamic Module Entry Point: <uri>::<name>".
ENTRY_COUNT=0
while IFS= read -r line; do
    echo "entry_point: ${line#Dynamic Module Entry Point: }"
    ENTRY_COUNT=$((ENTRY_COUNT+1))
done < <(grep '^Dynamic Module Entry Point:' "$DUMP" || true)
echo "entry_point_count: ${ENTRY_COUNT}"

if [ "$ENTRY_COUNT" -eq 0 ]; then
    echo "ERROR: no @pragma('dyn-module:entry-point') functions found. The VM" \
         "cannot invoke anything in this patch." >&2
    exit 7
fi

# Every function the disassembler emitted, for multi-function patches.
grep -oE "^Function '[^']+'" "$DUMP" | sed "s/^Function '/function: /; s/'\$//" || true

if [ "$QUIET" != "--quiet" ]; then
    echo "--- disassembly ---"
    cat "$DUMP"
fi
