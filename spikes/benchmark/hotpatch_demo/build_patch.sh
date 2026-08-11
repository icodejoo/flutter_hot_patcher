#!/usr/bin/env bash
# Usage: ./build_patch.sh normal|cpu
# Compiles a patch .dill from patches/greet_v1.dart or patches/greet_cpu.dart
# Output: spikes/benchmark/results/hotpatch_patch.dill
set -euo pipefail

PATCH_TYPE="${1:-normal}"
REPO_ROOT="$(cd "$(dirname "$0")/../../../" && pwd)"
OUT_DIR="$REPO_ROOT/spikes/benchmark/results"
mkdir -p "$OUT_DIR"

AOTRUNTIME=~/engine_ios/src/out/host_release/dartaotruntime
D2B=~/engine_ios/src/out/host_release/gen/dart2bytecode.dart.snapshot
PLATFORM=~/engine_ios/src/out/host_release/vm_platform_strong.dill

if [ ! -f "$AOTRUNTIME" ]; then
    echo "[build_patch] ERROR: dartaotruntime not found at $AOTRUNTIME"
    echo "  Build the custom engine first. See skills/flutter-engine-rebuild/SKILL.md"
    exit 1
fi

case "$PATCH_TYPE" in
  normal) SRC="$REPO_ROOT/spikes/benchmark/hotpatch_demo/patches/greet_v1.dart" ;;
  cpu)    SRC="$REPO_ROOT/spikes/benchmark/hotpatch_demo/patches/greet_cpu.dart" ;;
  *) echo "Usage: $0 normal|cpu"; exit 1 ;;
esac

echo "[build_patch] Compiling $PATCH_TYPE patch from $SRC"
"$AOTRUNTIME" "$D2B" \
  --platform "$PLATFORM" \
  --output "$OUT_DIR/hotpatch_patch.dill" \
  "$SRC"

SIZE=$(stat -f%z "$OUT_DIR/hotpatch_patch.dill")
echo "[build_patch] Done: patch_type=$PATCH_TYPE size=${SIZE}B → $OUT_DIR/hotpatch_patch.dill"
echo "$SIZE" > "$OUT_DIR/hotpatch_patch_size.txt"
echo "$PATCH_TYPE" > "$OUT_DIR/hotpatch_patch_type.txt"
