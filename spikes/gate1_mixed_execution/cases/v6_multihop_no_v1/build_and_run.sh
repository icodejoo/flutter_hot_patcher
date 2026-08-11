#!/bin/bash
# Build and run the V6 spike: does a multi-hop static/direct-call chain
# (stepA -> stepB -> stepC) really need V1's mechanism (physically rewriting
# an existing call instruction), or does closure propagation + a SINGLE
# closure-entry_point redirect (V2, pure data write) fully suffice?
#
# 构建并运行 V6 spike:多跳静态/直调链(stepA->stepB->stepC)是否真的需要
# V1 的机制(物理改写既有调用指令),还是传递闭包+一次闭包 entry_point
# 重定向(V2,纯数据写)就够了?
#
# Usage: DART_SDK_SRC=~/dart/sdk ./build_and_run.sh
set -e

: "${DART_SDK_SRC:?Set DART_SDK_SRC to the dart-lang/sdk source root (built with --dart-dynamic-modules)}"

CASE_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="$(mktemp -d -t v6_no_v1_XXXXXX)"
trap 'rm -rf "$BUILD_DIR"' EXIT

SDK_OUT="$DART_SDK_SRC/out/ReleaseX64"
GEN_KERNEL="$SDK_OUT/gen/gen_kernel_aot.dart.snapshot"
GEN_SNAPSHOT="$SDK_OUT/gen_snapshot_product"
DART2BYTECODE="$SDK_OUT/gen/dart2bytecode.dart.snapshot"
AOT_RUNTIME="$SDK_OUT/dartaotruntime_product"
VM_PLATFORM="$SDK_OUT/vm_platform.dill"

echo "==> [1/4] AOT-compile host (stepA/stepB/stepC + entryVar, untouched by activation)"
"$AOT_RUNTIME" "$GEN_KERNEL" \
  --target vm \
  -Ddart.vm.product=true -Ddynamic.modules.test.mode=aot \
  --aot --no-embed-sources --platform "$VM_PLATFORM" \
  --output "$BUILD_DIR/main_aot.dill" \
  "$CASE_DIR/test-lib/host/main.dart"

echo "==> [2/4] Generate host AOT snapshot"
"$GEN_SNAPSHOT" --snapshot-kind=app-aot-elf \
  --elf="$BUILD_DIR/main.snapshot" "$BUILD_DIR/main_aot.dill"

echo "==> [3/4] Compile the whole interpreted A->B->C replacement chain to bytecode"
"$AOT_RUNTIME" "$DART2BYTECODE" \
  --platform "$VM_PLATFORM" --target vm \
  -Ddart.vm.product=true -Ddynamic.modules.test.mode=aot \
  --bytecode-options=source-positions \
  --output "$BUILD_DIR/module.bytecode" \
  "$CASE_DIR/test-lib/patch/module.dart"

echo "==> [4/4] Run host (no V1 mprotect/instruction-scan code anywhere in this test)"
"$AOT_RUNTIME" "$BUILD_DIR/main.snapshot" "$BUILD_DIR/module.bytecode"
