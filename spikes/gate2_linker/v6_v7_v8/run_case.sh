#!/bin/bash
# Generic diff-linker case runner for V6/V7/V8: builds base+patch AOT snapshots
# from <case>/base.dart and <case>/patch.dart and runs the diff-linker, listing
# the transitive "must reinterpret" closure. Reuses the P2/tools mechanism.
#
# Usage: DART_SDK_SRC=/root/dart/sdk ./run_case.sh <case-subdir>
#   e.g. DART_SDK_SRC=/root/dart/sdk ./run_case.sh v7_inline
set -e
: "${DART_SDK_SRC:?Set DART_SDK_SRC to the dart-lang/sdk source root}"
CASE="${1:?Usage: run_case.sh <case-subdir>}"

HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$HERE/$CASE"
TOOLS="$HERE/../tools"
SDK_OUT="$DART_SDK_SRC/out/ReleaseX64"
GEN_KERNEL="$SDK_OUT/gen/gen_kernel_aot.dart.snapshot"
GEN_SNAPSHOT="$SDK_OUT/gen_snapshot_product"
AOT_RUNTIME="$SDK_OUT/dartaotruntime_product"
VM_PLATFORM="$SDK_OUT/vm_platform.dill"
B="$(mktemp -d -t gate2_${CASE}_XXXXXX)"
trap 'rm -rf "$B"' EXIT

build() {
  local src="$1" out="$2"
  "$AOT_RUNTIME" "$GEN_KERNEL" --target vm -Ddart.vm.product=true \
    --aot --no-embed-sources --platform "$VM_PLATFORM" \
    --output "$B/${out}_aot.dill" "$SRC/${src}.dart" >/dev/null 2>&1
  "$GEN_SNAPSHOT" --snapshot-kind=app-aot-elf \
    --elf="$B/${out}.snapshot" "$B/${out}_aot.dill" >/dev/null 2>&1
}

echo "== building $CASE base + patch =="
build base base
build patch patch

# Also run both to show behavior (base vs patch = the full-recompile reference).
echo "== base output =="; "$AOT_RUNTIME" "$B/base.snapshot"
echo "== patch output (== full-recompile reference behavior) =="; "$AOT_RUNTIME" "$B/patch.snapshot"

echo "== diff-linker closure (optimistic = ideal CanonicalName aligner) =="
python3 "$TOOLS/diff_linker.py" "$B/base.snapshot" "$B/patch.snapshot" --list --optimistic
