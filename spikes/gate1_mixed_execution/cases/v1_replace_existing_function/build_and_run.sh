#!/bin/bash
# Build and run the V1 REPLACEMENT spike / 构建并运行 V1 替换 spike.
#
# Requires a Dart SDK built from source with dynamic modules support:
#   ./tools/build.py -m release --dart-dynamic-modules runtime runtime_precompiled utils/gen_kernel
# 需要从源码、开 --dart-dynamic-modules 构建的 Dart SDK（见 ../../SETUP.md 阶段 A3）。
#
# Usage: DART_SDK_SRC=~/dart/sdk ./build_and_run.sh
#
# 重要 / IMPORTANT:
#   本脚本负责 (1) AOT 编译宿主（含既有 f/g）(2) 把补丁 f' 编成字节码 (3) 启动宿主。
#   但"把 f 的入口切到解释器 f'"这一核心步骤在 host/main.dart 的 _tryActivatePatch 里，
#   目前是占位——它是 Gate 1 要探索实现的机制（见 NOTES.md）。在机制接入前，运行会输出
#   "V1 INCONCLUSIVE"，这是预期的：脚本先把可复现的构建/运行链路搭好，机制探索在其上迭代。
set -e

: "${DART_SDK_SRC:?Set DART_SDK_SRC to the dart-lang/sdk source root (built with --dart-dynamic-modules)}"

CASE_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="$(mktemp -d -t v1_repl_XXXXXX)"
trap 'rm -rf "$BUILD_DIR"' EXIT

SDK_OUT="$DART_SDK_SRC/out/ReleaseX64"   # 按宿主架构调整 / adjust per host arch
GEN_KERNEL="$SDK_OUT/gen/gen_kernel_aot.dart.snapshot"
GEN_SNAPSHOT="$SDK_OUT/gen_snapshot_product"
DART2BYTECODE="$SDK_OUT/gen/dart2bytecode.dart.snapshot"
AOT_RUNTIME="$SDK_OUT/dartaotruntime_product"
VM_PLATFORM="$SDK_OUT/vm_platform.dill"

echo "==> [1/4] AOT-compile host (with existing f/g)"
"$AOT_RUNTIME" "$GEN_KERNEL" \
  --target vm \
  -Ddart.vm.product=true -Ddynamic.modules.test.mode=aot \
  --aot --no-embed-sources --platform "$VM_PLATFORM" \
  --output "$BUILD_DIR/main_aot.dill" \
  "$CASE_DIR/host/main.dart"

echo "==> [2/4] Generate host AOT snapshot"
"$GEN_SNAPSHOT" --snapshot-kind=app-aot-elf \
  --elf="$BUILD_DIR/main.snapshot" "$BUILD_DIR/main_aot.dill"

echo "==> [3/4] Compile replacement f' to bytecode"
"$AOT_RUNTIME" "$DART2BYTECODE" \
  --platform "$VM_PLATFORM" --target vm \
  -Ddart.vm.product=true -Ddynamic.modules.test.mode=aot \
  --bytecode-options=source-positions \
  --output "$BUILD_DIR/f_patch.bytecode" \
  "$CASE_DIR/patch/f_patch.dart"

echo "==> [4/4] Run host (expects V1 INCONCLUSIVE until _tryActivatePatch is wired)"
"$AOT_RUNTIME" "$BUILD_DIR/main.snapshot" "$BUILD_DIR/f_patch.bytecode"
