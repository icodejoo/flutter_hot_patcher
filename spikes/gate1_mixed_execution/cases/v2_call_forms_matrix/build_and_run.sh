#!/bin/bash
# Build and run the V2 call-forms-matrix spike. Pure AOT (no dynamic module
# bytecode/interpreter needed) — the redirect targets (OpPatched, closureTargetPatched)
# are themselves AOT-compiled; the test just proves dispatch-table-entry and
# Closure-entry_point rewrites work as one-shot, single-point redirects.
#
# 构建并运行 V2 调用形态矩阵 spike。纯 AOT(不需要字节码/解释器)——重定向目标
# (OpPatched、closureTargetPatched)本身就是 AOT 编译的；这个测试只验证
# dispatch table 项改写和 Closure entry_point 字段改写这两种"单点重定向"是否生效。
#
# Usage: DART_SDK_SRC=~/dart/sdk ./build_and_run.sh
set -e

: "${DART_SDK_SRC:?Set DART_SDK_SRC to the dart-lang/sdk source root (built with --dart-dynamic-modules)}"

CASE_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="$(mktemp -d -t v2_matrix_XXXXXX)"
trap 'rm -rf "$BUILD_DIR"' EXIT

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

echo "==> [3/3] Run host"
"$AOT_RUNTIME" "$BUILD_DIR/main.snapshot" "$@"
