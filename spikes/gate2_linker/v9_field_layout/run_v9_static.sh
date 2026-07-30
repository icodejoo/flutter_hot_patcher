#!/bin/bash
# V9 layer 1 (static completeness): build base/patch and run the diff linker in
# optimistic mode (ignore runtime name-collision noise, focus on our uniquely-
# named functions). Verify every Point accessor lands in the closure and
# `unrelated` stays equivalent.
#
# Usage: DART_SDK_SRC=/root/dart/sdk ./run_v9_static.sh
set -e
: "${DART_SDK_SRC:?Set DART_SDK_SRC to the dart-lang/sdk source root}"

CASE_DIR="$(cd "$(dirname "$0")" && pwd)"
TOOLS="$CASE_DIR/../tools"
SDK_OUT="$DART_SDK_SRC/out/ReleaseX64"
GEN_KERNEL="$SDK_OUT/gen/gen_kernel_aot.dart.snapshot"
GEN_SNAPSHOT="$SDK_OUT/gen_snapshot_product"
AOT_RUNTIME="$SDK_OUT/dartaotruntime_product"
VM_PLATFORM="$SDK_OUT/vm_platform.dill"
B=/root/gate2_v9
mkdir -p "$B"

build() {
  local src="$1" out="$2"
  "$AOT_RUNTIME" "$GEN_KERNEL" --target vm -Ddart.vm.product=true \
    --aot --no-embed-sources --platform "$VM_PLATFORM" \
    --output "$B/${out}_aot.dill" "$CASE_DIR/${src}.dart" >/dev/null 2>&1
  "$GEN_SNAPSHOT" --snapshot-kind=app-aot-elf \
    --elf="$B/${out}.snapshot" "$B/${out}_aot.dill" >/dev/null 2>&1
}

build v9_base base
build v9_patch patch
python3 "$TOOLS/diff_linker.py" "$B/base.snapshot" "$B/patch.snapshot" --optimistic --list
