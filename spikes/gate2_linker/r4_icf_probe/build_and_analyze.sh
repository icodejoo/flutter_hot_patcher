#!/bin/bash
: "${DART_SDK_SRC:?Set DART_SDK_SRC}"
HERE="$(cd "$(dirname "$0")" && pwd)"
SDK_OUT="$DART_SDK_SRC/out/ReleaseX64"
GEN_KERNEL="$SDK_OUT/gen/gen_kernel_aot.dart.snapshot"
GEN_SNAPSHOT="$SDK_OUT/gen_snapshot"
AOT_RUNTIME="$SDK_OUT/dartaotruntime_product"
VM_PLATFORM="$SDK_OUT/vm_platform.dill"
ANALYZE="$SDK_OUT/analyze_snapshot"
B="$HERE/_build"
rm -rf "$B"; mkdir -p "$B"

"$AOT_RUNTIME" "$GEN_KERNEL" --target vm -Ddart.vm.product=true \
  --aot --no-embed-sources --platform "$VM_PLATFORM" \
  --output "$B/probe_aot.dill" "$HERE/test-lib/probe.dart"
echo "gen_kernel exit=$?"

"$GEN_SNAPSHOT" --snapshot-kind=app-aot-elf \
  --elf="$B/probe.snapshot" --save-debugging-info="$B/probe.debug" \
  "$B/probe_aot.dill"
echo "gen_snapshot exit=$?"

"$ANALYZE" --out="$B/probe.json" "$B/probe.snapshot"
echo "analyze exit=$?"
echo "done -> $B/probe.json"
