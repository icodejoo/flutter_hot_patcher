#!/usr/bin/env bash
# Compile greet.dart → snapshot.S → snapshot.o (AOT for iOS arm64)
# Run this once before building in Xcode, then add snapshot.o to target.
#
# NOTE: gen_snapshot requires a kernel compiled by the same engine's dart tool.
# Current workaround: reuse snapshot.S from spikes/m3_ios_realdevice (same greet.dart structure).
# To recompile from scratch, use the engine's gen_snapshot with a compatible kernel:
#   gen_snapshot --snapshot_kind=app-aot-assembly --assembly=snapshot.S <kernel.dill>
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
M3_SNAPSHOT="$(cd "$SCRIPT_DIR/../../../spikes/m3_ios_realdevice/HotPatchDemo/HotPatchDemo" && pwd)/snapshot.S"

if [ ! -f "$M3_SNAPSHOT" ]; then
    echo "[build_aot] ERROR: M3 snapshot.S not found at $M3_SNAPSHOT"
    echo "  Run gen_snapshot manually or restore from git."
    exit 1
fi

echo "[build_aot] Reusing M3 snapshot.S (identical greet.dart structure)..."
cp "$M3_SNAPSHOT" "$SCRIPT_DIR/snapshot.S"

echo "[build_aot] Assembling snapshot.S → snapshot.o..."
as -arch arm64 "$SCRIPT_DIR/snapshot.S" -o "$SCRIPT_DIR/snapshot.o"

SIZE=$(stat -f%z "$SCRIPT_DIR/snapshot.o")
echo "[build_aot] Done: snapshot.o (${SIZE}B)"
echo "  Add snapshot.o to HotPatchBench Xcode target 'Compile Sources' to complete the build."
