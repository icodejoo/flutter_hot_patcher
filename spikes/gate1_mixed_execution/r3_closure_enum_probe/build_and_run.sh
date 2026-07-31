#!/bin/bash
# R3.1 probe: build + run probe.dart against the patched dart-sdk (after
# apply_probe_patch.py has added Internal_countClosuresForFunction and the
# runtime has been rebuilt per the two forced-refresh steps in
# ../vm_patch/README.md). Mirrors v2_call_forms_matrix/build_and_run.sh.
#
# Usage: DART_SDK_SRC=~/dart/sdk ./build_and_run.sh
set -e

: "${DART_SDK_SRC:?Set DART_SDK_SRC to the dart-lang/sdk source root (built with --dart-dynamic-modules)}"

CASE_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="$(mktemp -d -t r3_closure_probe_XXXXXX)"
trap 'rm -rf "$BUILD_DIR"' EXIT

SDK_OUT="$DART_SDK_SRC/out/ReleaseX64"
GEN_KERNEL="$SDK_OUT/gen/gen_kernel_aot.dart.snapshot"
GEN_SNAPSHOT="$SDK_OUT/gen_snapshot_product"
AOT_RUNTIME="$SDK_OUT/dartaotruntime_product"
VM_PLATFORM="$SDK_OUT/vm_platform.dill"

echo "==> [0/3] sanity: native symbol present in dartaotruntime_product?"
nm "$AOT_RUNTIME" | grep -q DN_Internal_countClosuresForFunction \
  && echo "    OK: DN_Internal_countClosuresForFunction found" \
  || { echo "    MISSING -- rebuild per vm_patch/README.md forced-refresh steps first"; exit 1; }

echo "==> [1/3] AOT-compile probe"
"$AOT_RUNTIME" "$GEN_KERNEL" \
  --target vm \
  -Ddart.vm.product=true \
  --aot --no-embed-sources --platform "$VM_PLATFORM" \
  --output "$BUILD_DIR/probe_aot.dill" \
  "$CASE_DIR/test-lib/probe.dart"

echo "==> [2/3] Generate AOT snapshot"
"$GEN_SNAPSHOT" --snapshot-kind=app-aot-elf \
  --elf="$BUILD_DIR/probe.snapshot" "$BUILD_DIR/probe_aot.dill"

echo "==> [3/3] Run"
"$AOT_RUNTIME" "$BUILD_DIR/probe.snapshot" "$@"
