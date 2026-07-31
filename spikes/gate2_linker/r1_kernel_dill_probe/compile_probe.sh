#!/bin/bash
set -e
: "${DART_SDK_SRC:?Set DART_SDK_SRC}"
HERE="$(cd "$(dirname "$0")" && pwd)"
SDK_OUT="$DART_SDK_SRC/out/ReleaseX64"
GEN_KERNEL="$SDK_OUT/gen/gen_kernel_aot.dart.snapshot"
AOT_RUNTIME="$SDK_OUT/dartaotruntime_product"
VM_PLATFORM="$SDK_OUT/vm_platform.dill"
PKG="$HERE/probe_pkg"

"$AOT_RUNTIME" "$GEN_KERNEL" --target vm -Ddart.vm.product=true \
  --aot --no-embed-sources --platform "$VM_PLATFORM" \
  --packages "$PKG/.dart_tool/package_config.json" \
  --output "$HERE/probe.dill" \
  "$PKG/bin/main.dart"

echo "compiled -> $HERE/probe.dill"
