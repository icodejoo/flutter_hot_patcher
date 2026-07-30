#!/bin/bash
# P1 precision run: generate the large sample, build base/patch AOT snapshots
# (with DWARF debug for CanonicalName alignment), run the diff-linker, and
# compare its closure to the manifest ground truth via measure.py.
#
# Usage: DART_SDK_SRC=/root/dart/sdk ./run_sample.sh
set -e
: "${DART_SDK_SRC:?Set DART_SDK_SRC to the dart-lang/sdk source root}"

HERE="$(cd "$(dirname "$0")" && pwd)"
TOOLS="$HERE/../tools"
python3 "$HERE/gen_sample.py"

SDK_OUT="$DART_SDK_SRC/out/ReleaseX64"
GEN_KERNEL="$SDK_OUT/gen/gen_kernel_aot.dart.snapshot"
GEN_SNAPSHOT="$SDK_OUT/gen_snapshot_product"
AOT_RUNTIME="$SDK_OUT/dartaotruntime_product"
VM_PLATFORM="$SDK_OUT/vm_platform.dill"
B="$(mktemp -d -t p1_sample_XXXXXX)"
trap 'rm -rf "$B"' EXIT

build() {
  local tree="$1"
  "$AOT_RUNTIME" "$GEN_KERNEL" --target vm -Ddart.vm.product=true \
    --aot --no-embed-sources --platform "$VM_PLATFORM" \
    --output "$B/${tree}_aot.dill" "$HERE/${tree}/app.dart" >/dev/null 2>&1
  "$GEN_SNAPSHOT" --snapshot-kind=app-aot-elf \
    --elf="$B/${tree}.snapshot" --save-debugging-info="$B/${tree}.debug" \
    "$B/${tree}_aot.dill" >/dev/null 2>&1
}
echo "== building base + patch AOT snapshots =="
build base
build patch
echo "== base output =="; "$AOT_RUNTIME" "$B/base.snapshot"
echo "== patch output (full-recompile reference) =="; "$AOT_RUNTIME" "$B/patch.snapshot"

echo "== diff-linker (CanonicalName, conservative) =="
python3 "$TOOLS/diff_linker.py" "$B/base.snapshot" "$B/patch.snapshot" \
  --base-debug "$B/base.debug" --patch-debug "$B/patch.debug" \
  --base-src-root "$HERE/base" --patch-src-root "$HERE/patch" \
  --emit-closure | tee "$B/out.txt" | grep -v '^CLOSURE'
grep '^CLOSURE' "$B/out.txt" > "$B/closure.txt" || true

echo "== precision vs manifest ground truth =="
python3 "$HERE/measure.py" "$HERE/manifest.json" "$B/closure.txt"
