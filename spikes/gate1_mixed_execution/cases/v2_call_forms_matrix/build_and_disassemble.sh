#!/bin/bash
# Build the V2 host and disassemble callViaInterface / callViaClosure to see
# what instruction shape each call form actually compiles to. This is a
# discovery step, not a pass/fail test — see NOTES.md for what to do with
# the output.
#
# 构建 V2 宿主并反汇编 callViaInterface / callViaClosure，看两种调用形态
# 实际编译成什么指令。这是探查步骤，不是通过/失败测试——看到什么、下一步
# 怎么做见 NOTES.md。
#
# Usage: DART_SDK_SRC=~/dart/sdk ./build_and_disassemble.sh
set -e

: "${DART_SDK_SRC:?Set DART_SDK_SRC to the dart-lang/sdk source root}"

CASE_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="/root/v2_build_persist"
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"

SDK_OUT="$DART_SDK_SRC/out/ReleaseX64"
GEN_KERNEL="$SDK_OUT/gen/gen_kernel_aot.dart.snapshot"
GEN_SNAPSHOT="$SDK_OUT/gen_snapshot_product"
AOT_RUNTIME="$SDK_OUT/dartaotruntime_product"
VM_PLATFORM="$SDK_OUT/vm_platform.dill"

echo "==> [1/3] AOT-compile host"
"$AOT_RUNTIME" "$GEN_KERNEL" \
  --target vm \
  -Ddart.vm.product=true -Ddynamic.modules.test.mode=aot \
  --aot --no-embed-sources --platform "$VM_PLATFORM" \
  --output "$BUILD_DIR/main_aot.dill" \
  "$CASE_DIR/host/main.dart"

echo "==> [2/3] Generate host AOT snapshot"
"$GEN_SNAPSHOT" --snapshot-kind=app-aot-elf \
  --elf="$BUILD_DIR/main.snapshot" "$BUILD_DIR/main_aot.dill"

echo "==> [3/3] Symbols + disassembly"
nm "$BUILD_DIR/main.snapshot" | grep -E '\st\s+(callViaInterface|callViaClosure|closureTarget|OpOriginal\.run|OpOther\.run)$'

echo "--- callViaInterface ---"
START=$(nm "$BUILD_DIR/main.snapshot" | awk '$3=="callViaInterface"{print $1}')
objdump -d --start-address=0x$START --stop-address=0x$(printf '%x' $((0x$START + 0x120))) "$BUILD_DIR/main.snapshot"

echo "--- callViaClosure ---"
START=$(nm "$BUILD_DIR/main.snapshot" | awk '$3=="callViaClosure"{print $1}')
objdump -d --start-address=0x$START --stop-address=0x$(printf '%x' $((0x$START + 0x120))) "$BUILD_DIR/main.snapshot"

echo "==> Build dir kept at $BUILD_DIR"
