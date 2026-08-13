#!/usr/bin/env bash
set -euo pipefail

PATCH_TYPE="${1:-normal}"
REPO_ROOT="$(cd "$(dirname "$0")/../../../" && pwd)"
OUT_DIR="$REPO_ROOT/spikes/benchmark/results"
mkdir -p "$OUT_DIR"

D2B_V2="$REPO_ROOT/tools/dart2bytecode_v2"
PLATFORM=~/engine_ios/src/out/host_release/vm_platform_strong.dill

if [ ! -x "$D2B_V2" ]; then
    echo "[build_patch] ERROR: dart2bytecode_v2 not found at $D2B_V2" >&2
    exit 1
fi

case "$PATCH_TYPE" in
  normal) SRC="$REPO_ROOT/spikes/benchmark/hotpatch_demo/patches/greet_v1.dart" ;;
  cpu)    SRC="$REPO_ROOT/spikes/benchmark/hotpatch_demo/patches/greet_cpu.dart" ;;
  heavy)  SRC="$REPO_ROOT/spikes/benchmark/hotpatch_demo/patches/greet_heavy.dart" ;;
  *) echo "Usage: $0 normal|cpu|heavy"; exit 1 ;;
esac

echo "[build_patch] Compiling $PATCH_TYPE patch (v02) from $SRC"
"$D2B_V2" \
  --platform "$PLATFORM" \
  --output "$OUT_DIR/hotpatch_patch.dill" \
  "$SRC"

SIZE=$(stat -f%z "$OUT_DIR/hotpatch_patch.dill")
echo "[build_patch] Done: patch_type=$PATCH_TYPE size=${SIZE}B → $OUT_DIR/hotpatch_patch.dill"
echo "$SIZE" > "$OUT_DIR/hotpatch_patch_size.txt"
echo "$PATCH_TYPE" > "$OUT_DIR/hotpatch_patch_type.txt"
