#!/usr/bin/env bash
# Inspect a DBC3 patch dill: verify magic + version, list dynamic-module
# entry points, and disassemble the bytecode.
#
# Usage: inspect_patch.sh <patch.dill> [--quiet]
# Exit:  0 = valid DBC3 for the target VM, non-zero = invalid
#
# The accepted format version is whatever the target VM's
# runtime/vm/constants_kbc.h kBytecodeFormatVersion says. For ~/dart/sdk (and
# therefore the X1 engine) that is 1. Override with FHP_KBC_VERSION when
# inspecting patches built for a different VM -- e.g. the prebuilt runtime in
# spikes/m3_ios_realdevice wants 2. See docs/ROUTE_A_RESEARCH.md.
set -euo pipefail

DILL="${1:?Usage: $0 <patch.dill> [--quiet]}"
QUIET="${2:-}"

ENGINE_SRC=~/engine_ios/src
DART_JIT=$ENGINE_SRC/out/host_release/dart
DUMP_BC_SRC=$ENGINE_SRC/flutter/third_party/dart/pkg/dart2bytecode/bin/dump_bytecode.dart

[ -f "$DILL" ] || { echo "ERROR: no such file: $DILL" >&2; exit 1; }

# --- Header check: magic "3CBD" + uint32 LE version == 2 --------------------
EXPECT_VERSION="${FHP_KBC_VERSION:-1}"

python3 - "$DILL" "$EXPECT_VERSION" <<'PY'
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
expected = int(sys.argv[2])
if version != expected:
    print(f"ERROR: bytecode format version {version}, but the target VM only "
          f"accepts version {expected}. Set FHP_KBC_VERSION if you meant a "
          f"different VM.", file=sys.stderr)
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
