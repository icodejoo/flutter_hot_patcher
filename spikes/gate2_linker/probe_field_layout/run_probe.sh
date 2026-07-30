#!/bin/bash
# Gate 2 probe P1 driver: AOT-compile both probe variants and disassemble the
# writeB(box.b = v) store so we can compare the encoded field offset.
#
# Usage: DART_SDK_SRC=/root/dart/sdk ./run_probe.sh
set -e
: "${DART_SDK_SRC:?Set DART_SDK_SRC to the dart-lang/sdk source root}"

CASE_DIR="$(cd "$(dirname "$0")" && pwd)"
SDK_OUT="$DART_SDK_SRC/out/ReleaseX64"
GEN_KERNEL="$SDK_OUT/gen/gen_kernel_aot.dart.snapshot"
GEN_SNAPSHOT="$SDK_OUT/gen_snapshot_product"
AOT_RUNTIME="$SDK_OUT/dartaotruntime_product"
VM_PLATFORM="$SDK_OUT/vm_platform.dill"
BUILD=/root/gate2_probe_p1
mkdir -p "$BUILD"

build() {
  local name="$1"
  "$AOT_RUNTIME" "$GEN_KERNEL" --target vm \
    -Ddart.vm.product=true \
    --aot --no-embed-sources --platform "$VM_PLATFORM" \
    --output "$BUILD/${name}_aot.dill" "$CASE_DIR/${name}.dart" >/dev/null 2>&1
  "$GEN_SNAPSHOT" --snapshot-kind=app-aot-elf \
    --elf="$BUILD/${name}.snapshot" "$BUILD/${name}_aot.dill" >/dev/null 2>&1
}

dump_writeB() {
  local name="$1" addr
  addr=$(nm "$BUILD/${name}.snapshot" | awk '$3=="writeB"{print $1}' | head -1)
  echo "  [$name] writeB @ 0x$addr:"
  objdump -d --start-address=0x$addr \
    --stop-address=0x$(printf '%x' $((0x$addr + 0x10))) \
    "$BUILD/${name}.snapshot" | grep -E '^\s+[0-9a-f]+:.*mov'
}

build probe_base
build probe_patched
echo "=== writeB (box.b = v) field-store offset ==="
dump_writeB probe_base
dump_writeB probe_patched
echo "==> base offset should be 0xf (b is 2nd field); patched 0x17 (+8, x pushed b back)"
