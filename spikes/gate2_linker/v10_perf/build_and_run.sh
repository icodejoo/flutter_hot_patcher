#!/bin/bash
# Build and run the V10 perf spike / 构建并运行 V10 性能 spike.
#
# Measures k: how many times slower interpreted bytecode runs vs AOT native for
# a byte-identical kernel. Reuses the Gate 1 VM patch's loadDynamicModuleClosure
# + invokeDynamicModuleClosure. No call-site rewrite (redirection transparency
# already proven by V1-V5); this isolates raw interpreter cost.
#
# Requires a Dart SDK built from source with dynamic modules + the Gate 1 VM
# patch, and a working dir reachable via a path containing `test-lib`
# (dart:_internal import allowlist).
#
# Usage: DART_SDK_SRC=~/dart/sdk ./build_and_run.sh
set -e

: "${DART_SDK_SRC:?Set DART_SDK_SRC to the dart-lang/sdk source root}"

CASE_DIR="$(cd "$(dirname "$0")" && pwd)"
python3 "$CASE_DIR/gen.py"

BUILD_DIR="$(mktemp -d -t v10_perf_XXXXXX)"
trap 'rm -rf "$BUILD_DIR"' EXIT

SDK_OUT="$DART_SDK_SRC/out/ReleaseX64"
GEN_KERNEL="$SDK_OUT/gen/gen_kernel_aot.dart.snapshot"
GEN_SNAPSHOT="$SDK_OUT/gen_snapshot_product"
DART2BYTECODE="$SDK_OUT/gen/dart2bytecode.dart.snapshot"
AOT_RUNTIME="$SDK_OUT/dartaotruntime_product"
VM_PLATFORM="$SDK_OUT/vm_platform.dill"

# Official dynamic-modules flow so the patch can call dart:core APIs (string
# interpolation, int.parse) — see dynamic_interface.yaml. Without --import-dill
# +--validate against the interface, those calls fail at bytecode LOAD with
# "Unable to find function ... in dart:core" (closed-world tree-shake, skill §6).
# Only dart:core is declared callable, so no --filesystem-scheme is needed.
IFACE="$CASE_DIR/dynamic_interface.yaml"

echo "==> [1/5] AOT-compile host (--dynamic-interface)"
"$AOT_RUNTIME" "$GEN_KERNEL" \
  --target vm \
  -Ddart.vm.product=true -Ddynamic.modules.test.mode=aot \
  --aot --no-embed-sources --platform "$VM_PLATFORM" \
  --dynamic-interface "$IFACE" \
  --output "$BUILD_DIR/main_aot.dill" \
  "$CASE_DIR/host/main.dart"

echo "==> [2/5] Host no-aot kernel (for --import-dill)"
"$AOT_RUNTIME" "$GEN_KERNEL" \
  --target vm \
  -Ddart.vm.product=true -Ddynamic.modules.test.mode=aot \
  --no-aot --no-embed-sources --platform "$VM_PLATFORM" \
  --dynamic-interface "$IFACE" \
  --output "$BUILD_DIR/main_no_aot.dill" \
  "$CASE_DIR/host/main.dart"

echo "==> [3/5] Generate host AOT snapshot"
"$GEN_SNAPSHOT" --snapshot-kind=app-aot-elf \
  --elf="$BUILD_DIR/main.snapshot" "$BUILD_DIR/main_aot.dill"

echo "==> [4/5] Compile each interpreted kernel to bytecode (--import-dill --validate)"
BYTECODE_ARGS=()
while read -r I; do
  [ -z "$I" ] && continue
  "$AOT_RUNTIME" "$DART2BYTECODE" \
    --platform "$VM_PLATFORM" --target vm \
    -Ddart.vm.product=true -Ddynamic.modules.test.mode=aot \
    --bytecode-options=source-positions \
    --import-dill "$BUILD_DIR/main_no_aot.dill" \
    --validate "$IFACE" \
    --output "$BUILD_DIR/c$I.bytecode" \
    "$CASE_DIR/patch/c$I.dart"
  BYTECODE_ARGS+=("$BUILD_DIR/c$I.bytecode")
done < "$CASE_DIR/cases.txt"

echo "==> [5/5] Run benchmark"
"$AOT_RUNTIME" "$BUILD_DIR/main.snapshot" "${BYTECODE_ARGS[@]}"
