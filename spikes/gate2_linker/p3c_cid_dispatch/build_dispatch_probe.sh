#!/bin/bash
# R5 spike probe: does DispatchTable slot content drift for existing classes
# when a new class is inserted, even though no function bytes change?
# Uses analyze_snapshot's --out JSON dump (non-product gen_snapshot not needed;
# analyze_snapshot is a separate diagnostic tool that ships in ReleaseX64 out/).
set -e
export DART_SDK_SRC=/root/dart/sdk
SDK_OUT="$DART_SDK_SRC/out/ReleaseX64"
GEN_KERNEL="$SDK_OUT/gen/gen_kernel_aot.dart.snapshot"
GEN_SNAPSHOT="$SDK_OUT/gen_snapshot"
AOT_RUNTIME="$SDK_OUT/dartaotruntime_product"
VM_PLATFORM="$SDK_OUT/vm_platform.dill"
ANALYZE="$SDK_OUT/analyze_snapshot"
HERE="$(cd "$(dirname "$0")" && pwd)"
B="$HERE/_build"
rm -rf "$B"
mkdir -p "$B"

build() {
  local tree="$1"
  "$AOT_RUNTIME" "$GEN_KERNEL" --target vm -Ddart.vm.product=true \
    --aot --no-embed-sources --platform "$VM_PLATFORM" \
    --output "$B/${tree}_aot.dill" "$HERE/${tree}.dart"
  "$GEN_SNAPSHOT" --snapshot-kind=app-aot-elf \
    --elf="$B/${tree}.snapshot" --save-debugging-info="$B/${tree}.debug" \
    "$B/${tree}_aot.dill"
}
echo "== building base + patch =="
build base
build patch

echo "== analyze_snapshot on base =="
"$ANALYZE" --out="$B/base.json" "$B/base.snapshot"
echo "== analyze_snapshot on patch =="
"$ANALYZE" --out="$B/patch.json" "$B/patch.snapshot"

echo "== done =="
ls -la "$B"/*.json
echo "== top-level keys (base) =="
python3 -c "import json; d=json.load(open('$B/base.json')); print(list(d.keys()))"
