#!/bin/bash
# V9 layer-2 (runtime): compile host (with --dynamic-interface) + patch bytecode
# (--import-dill --validate) via the official dynamic-modules pipeline, then run.
# The patch defines Box with new fields (w,h); success = area()==12, proving the
# interpreter allocates/accesses the new layout correctly across the virtual-call
# boundary to the host AOT.
#
# Usage: DART_SDK_SRC=/root/dart/sdk ./run_v9_runtime.sh
set -e
: "${DART_SDK_SRC:?Set DART_SDK_SRC to the dart-lang/sdk source root}"

CASE_DIR="$(cd "$(dirname "$0")" && pwd)"   # the runtime/ folder = filesystem-root
OUT="$DART_SDK_SRC/out/ReleaseX64"
AOT_RUNTIME="$OUT/dartaotruntime_product"
GEN_KERNEL="$OUT/gen/gen_kernel_aot.dart.snapshot"
GEN_SNAPSHOT="$OUT/gen_snapshot_product"
DART2BYTECODE="$OUT/gen/dart2bytecode.dart.snapshot"
VM_PLATFORM="$OUT/vm_platform.dill"
PKGCFG="$DART_SDK_SRC/.dart_tool/package_config.json"
SCHEME=dev-dart-app
WORK=/root/gate2_v9_rt/v9run
rm -rf "$WORK"; mkdir -p "$WORK/modules"
cd "$WORK"

echo "== [1/4] host AOT kernel =="
"$AOT_RUNTIME" "$GEN_KERNEL" --target vm --packages "$PKGCFG" \
  -Ddart.vm.product=true --aot --no-embed-sources --platform "$VM_PLATFORM" \
  --output main_aot.dill \
  --filesystem-root "$CASE_DIR" --filesystem-scheme "$SCHEME" \
  --dynamic-interface "$SCHEME:/dynamic_interface.yaml" \
  "$SCHEME:/main.dart"

echo "== [2/4] host no-aot kernel (for --import-dill) =="
"$AOT_RUNTIME" "$GEN_KERNEL" --target vm --packages "$PKGCFG" \
  -Ddart.vm.product=true --no-aot --no-embed-sources --platform "$VM_PLATFORM" \
  --output main_no_aot.dill \
  --filesystem-root "$CASE_DIR" --filesystem-scheme "$SCHEME" \
  --dynamic-interface "$SCHEME:/dynamic_interface.yaml" \
  "$SCHEME:/main.dart"

echo "== [3/4] AOT snapshot + patch bytecode (entry1 {w,h} and entry2 {w,pad,h}) =="
"$GEN_SNAPSHOT" --snapshot-kind=app-aot-elf --elf=main.snapshot main_aot.dill
compile_patch() {
  local entry="$1"
  "$AOT_RUNTIME" "$DART2BYTECODE" --platform "$VM_PLATFORM" --target vm \
    --packages "$PKGCFG" -Ddart.vm.product=true \
    --import-dill main_no_aot.dill \
    --validate "$SCHEME:/dynamic_interface.yaml" \
    --filesystem-root "$CASE_DIR" --filesystem-scheme "$SCHEME" \
    --output "modules/$entry.bytecode" --prefix-library-uris import/prefix \
    "$SCHEME:/modules/$entry"
}
compile_patch entry1.dart
compile_patch entry2.dart

echo "== [4/4] execute both layouts =="
echo "-- entry1 (Box{w,h}) --"
"$AOT_RUNTIME" main.snapshot modules/entry1.dart.bytecode
echo "-- entry2 (Box{w,pad,h} — h offset shifted) --"
"$AOT_RUNTIME" main.snapshot modules/entry2.dart.bytecode
echo "EXIT=$?"
