#!/bin/bash
# Build the V2 (call-forms matrix) repro on Android arm64 and push+run via adb.
# 构建 V2(调用形态矩阵)在 Android arm64 上的复现，通过 adb 推送并执行。
#
# Unlike V1/V3/V4/V5, this case needs NO arm64-specific patching code at all —
# redirectDispatchTableEntry / redirectClosureEntryPoint operate entirely
# through the VM natives (class id / Closure object fields), never touching
# raw machine code or instruction encoding. host/main.dart is an unmodified
# copy of the desktop x64 case. This is exactly the portability V2's NOTES.md
# predicted: dispatch-table/closure-entry_point redirects are architecture-
# independent by construction, unlike V1's call-site machine-code rewrite.
#
# 和 V1/V3/V4/V5 不同，这个用例完全不需要任何 arm64 专属的改写代码——
# redirectDispatchTableEntry / redirectClosureEntryPoint 全程通过 VM 原生函数
# (class id / Closure 对象字段)操作，完全不碰原始机器码或指令编码。
# host/main.dart 是桌面 x64 用例的原样拷贝。这正是 V2 的 NOTES.md 预判的可移植性：
# dispatch table/closure entry_point 重定向从设计上就是架构无关的，
# 不像 V1 的调用点机器码改写。
#
# Requires: same as ../v1_replace_existing_function/build_and_push.sh
# （宿主 x64 + Android arm64 双份构建，见该脚本头部注释）。
#
# Usage: DART_SDK_SRC=~/dart/sdk ./build_and_push.sh
set -e

: "${DART_SDK_SRC:?Set DART_SDK_SRC to the dart-lang/sdk source root}"
ADB="${ADB:-adb}"

CASE_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="$(mktemp -d -t gate1b_v2_android_XXXXXX)"
trap 'rm -rf "$BUILD_DIR"' EXIT

HOST_OUT="$DART_SDK_SRC/out/ReleaseX64"
ANDROID_OUT="$DART_SDK_SRC/out/ReleaseAndroidARM64"

GEN_KERNEL_HOST="$HOST_OUT/gen/gen_kernel_aot.dart.snapshot"
AOT_RUNTIME_HOST="$HOST_OUT/dartaotruntime_product"
GEN_SNAPSHOT_ARM64="$ANDROID_OUT/clang_x64/exe.stripped/gen_snapshot_product"
VM_PLATFORM_ARM64="$ANDROID_OUT/vm_platform.dill"
DARTAOTRUNTIME_ARM64="$ANDROID_OUT/dartaotruntime_product"

echo "==> [1/3] AOT-compile host, targeting arm64 platform.dill"
"$AOT_RUNTIME_HOST" "$GEN_KERNEL_HOST" \
  --target vm \
  -Ddart.vm.product=true -Ddynamic.modules.test.mode=aot \
  --aot --no-embed-sources --platform "$VM_PLATFORM_ARM64" \
  --output "$BUILD_DIR/main_aot.dill" \
  "$CASE_DIR/host/main.dart"

echo "==> [2/3] Generate arm64 AOT snapshot"
"$GEN_SNAPSHOT_ARM64" --snapshot-kind=app-aot-elf \
  --elf="$BUILD_DIR/main.snapshot" "$BUILD_DIR/main_aot.dill"

echo "==> [3/3] Push to device and run"
DEVICE_DIR=/data/local/tmp/gate1b/v2
"$ADB" shell "mkdir -p $DEVICE_DIR"
"$ADB" push "$DARTAOTRUNTIME_ARM64" "$DEVICE_DIR/dartaotruntime_product"
"$ADB" push "$BUILD_DIR/main.snapshot" "$DEVICE_DIR/main.snapshot"
"$ADB" shell "chmod 755 $DEVICE_DIR/dartaotruntime_product"
"$ADB" shell "$DEVICE_DIR/dartaotruntime_product $DEVICE_DIR/main.snapshot"
