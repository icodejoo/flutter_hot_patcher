#!/bin/bash
# Build and run the V3 EXCEPTION PASSTHROUGH spike / 构建并运行 V3 异常穿透 spike.
#
# Requires a Dart SDK built from source with dynamic modules support AND the
# Gate 1 VM patch applied (see ../../vm_patch/README.md):
#   ./tools/build.py -m release --dart-dynamic-modules runtime runtime_precompiled utils/gen_kernel
#
# Requires the working directory to be reachable via a path containing the
# substring `test-lib` (dart:_internal import allowlist — see
# ../../vm_patch/README.md and .claude/skills/gate1-vm-spike/SKILL.md §4).
#
# Usage: DART_SDK_SRC=~/dart/sdk ./build_and_run.sh
set -e

: "${DART_SDK_SRC:?Set DART_SDK_SRC to the dart-lang/sdk source root (built with --dart-dynamic-modules + Gate 1 VM patch)}"

CASE_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="$(mktemp -d -t v3_except_XXXXXX)"
trap 'rm -rf "$BUILD_DIR"' EXIT

SDK_OUT="$DART_SDK_SRC/out/ReleaseX64"
GEN_KERNEL="$SDK_OUT/gen/gen_kernel_aot.dart.snapshot"
GEN_SNAPSHOT="$SDK_OUT/gen_snapshot_product"
DART2BYTECODE="$SDK_OUT/gen/dart2bytecode.dart.snapshot"
AOT_RUNTIME="$SDK_OUT/dartaotruntime_product"
VM_PLATFORM="$SDK_OUT/vm_platform.dill"

echo "==> [1/4] AOT-compile host (with existing f/gCatches/gPropagates)"
"$AOT_RUNTIME" "$GEN_KERNEL" \
  --target vm \
  -Ddart.vm.product=true -Ddynamic.modules.test.mode=aot \
  --aot --no-embed-sources --platform "$VM_PLATFORM" \
  --output "$BUILD_DIR/main_aot.dill" \
  "$CASE_DIR/host/main.dart"

echo "==> [2/4] Generate host AOT snapshot"
"$GEN_SNAPSHOT" --snapshot-kind=app-aot-elf \
  --elf="$BUILD_DIR/main.snapshot" "$BUILD_DIR/main_aot.dill"

echo "==> [3/4] Compile throwing replacement f' to bytecode"
"$AOT_RUNTIME" "$DART2BYTECODE" \
  --platform "$VM_PLATFORM" --target vm \
  -Ddart.vm.product=true -Ddynamic.modules.test.mode=aot \
  --bytecode-options=source-positions \
  --output "$BUILD_DIR/f_patch.bytecode" \
  "$CASE_DIR/patch/f_patch.dart"

echo "==> [4/4] Run host"
"$AOT_RUNTIME" "$BUILD_DIR/main.snapshot" "$BUILD_DIR/f_patch.bytecode" "$BUILD_DIR/main.snapshot"
