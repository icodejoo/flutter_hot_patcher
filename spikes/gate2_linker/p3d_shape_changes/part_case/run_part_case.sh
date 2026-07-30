#!/bin/bash
# part/part-of case: base/ and patch/ are each a small source TREE (app.dart +
# helpers.dart), not single files — build from app.dart as entry, with
# --save-debugging-info + --*-src-root (root-relative canonical keys).
set -e
: "${DART_SDK_SRC:?Set DART_SDK_SRC to the dart-lang/sdk source root}"
HERE="$(cd "$(dirname "$0")" && pwd)"
TOOLS="$HERE/../../tools"
SDK_OUT="$DART_SDK_SRC/out/ReleaseX64"
GEN_KERNEL="$SDK_OUT/gen/gen_kernel_aot.dart.snapshot"
GEN_SNAPSHOT="$SDK_OUT/gen_snapshot_product"
AOT_RUNTIME="$SDK_OUT/dartaotruntime_product"
VM_PLATFORM="$SDK_OUT/vm_platform.dill"
B="$(mktemp -d -t part_case_XXXXXX)"
trap 'rm -rf "$B"' EXIT

build() {
  local tree="$1"
  "$AOT_RUNTIME" "$GEN_KERNEL" --target vm -Ddart.vm.product=true \
    --aot --no-embed-sources --platform "$VM_PLATFORM" \
    --output "$B/${tree}_aot.dill" "$HERE/$tree/app.dart" >/dev/null 2>&1
  "$GEN_SNAPSHOT" --snapshot-kind=app-aot-elf \
    --elf="$B/${tree}.snapshot" --save-debugging-info="$B/${tree}.debug" \
    "$B/${tree}_aot.dill" >/dev/null 2>&1
}
echo "== building base + patch =="
build base
build patch
echo "== base output =="; "$AOT_RUNTIME" "$B/base.snapshot"
echo "== patch output (== full-recompile reference) =="; "$AOT_RUNTIME" "$B/patch.snapshot"

echo "== diff-linker (CanonicalName) =="
python3 "$TOOLS/diff_linker.py" "$B/base.snapshot" "$B/patch.snapshot" \
  --base-debug "$B/base.debug" --patch-debug "$B/patch.debug" \
  --base-src-root "$HERE/base" --patch-src-root "$HERE/patch" --list \
  | grep -vE '^CLOSURE'
