#!/bin/bash
# Build the V3 (exception passthrough) repro on Android arm64 and push+run via adb.
# 构建 V3(异常穿透)在 Android arm64 上的复现，通过 adb 推送并执行。
#
# Requires: same as ../v1_replace_existing_function/build_and_push.sh.
# Usage: DART_SDK_SRC=~/dart/sdk ./build_and_push.sh
set -e

: "${DART_SDK_SRC:?Set DART_SDK_SRC to the dart-lang/sdk source root}"
ADB="${ADB:-adb}"

CASE_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="$(mktemp -d -t gate1b_v3_android_XXXXXX)"
trap 'rm -rf "$BUILD_DIR"' EXIT

HOST_OUT="$DART_SDK_SRC/out/ReleaseX64"
ANDROID_OUT="$DART_SDK_SRC/out/ReleaseAndroidARM64"

GEN_KERNEL_HOST="$HOST_OUT/gen/gen_kernel_aot.dart.snapshot"
AOT_RUNTIME_HOST="$HOST_OUT/dartaotruntime_product"
DART2BYTECODE_HOST="$HOST_OUT/gen/dart2bytecode.dart.snapshot"
GEN_SNAPSHOT_ARM64="$ANDROID_OUT/clang_x64/exe.stripped/gen_snapshot_product"
VM_PLATFORM_ARM64="$ANDROID_OUT/vm_platform.dill"
DARTAOTRUNTIME_ARM64="$ANDROID_OUT/dartaotruntime_product"

echo "==> [1/4] AOT-compile host, targeting arm64 platform.dill"
"$AOT_RUNTIME_HOST" "$GEN_KERNEL_HOST" \
  --target vm \
  -Ddart.vm.product=true -Ddynamic.modules.test.mode=aot \
  --aot --no-embed-sources --platform "$VM_PLATFORM_ARM64" \
  --output "$BUILD_DIR/main_aot.dill" \
  "$CASE_DIR/host/main.dart"

echo "==> [2/4] Generate arm64 AOT snapshot"
"$GEN_SNAPSHOT_ARM64" --snapshot-kind=app-aot-elf \
  --elf="$BUILD_DIR/main.snapshot" "$BUILD_DIR/main_aot.dill"

echo "==> [3/4] Compile replacement (throwing) f' to bytecode"
"$AOT_RUNTIME_HOST" "$DART2BYTECODE_HOST" \
  --platform "$VM_PLATFORM_ARM64" --target vm \
  -Ddart.vm.product=true -Ddynamic.modules.test.mode=aot \
  --bytecode-options=source-positions \
  --output "$BUILD_DIR/f_patch.bytecode" \
  "$CASE_DIR/patch/f_patch.dart"

echo "==> [4/4] Resolve addresses at BUILD time, push, run"
F_ADDR=$(nm "$BUILD_DIR/main.snapshot" | awk '$3=="f"{print $1}' | head -1)
FALT_ADDR=$(nm "$BUILD_DIR/main.snapshot" | awk '$3=="fAlt"{print $1}' | head -1)
GCATCHES_ADDR=$(nm "$BUILD_DIR/main.snapshot" | awk '$3=="gCatches"{print $1}' | head -1)
GPROP_ADDR=$(nm "$BUILD_DIR/main.snapshot" | awk '$3=="gPropagates"{print $1}' | head -1)
echo "    f=0x$F_ADDR fAlt=0x$FALT_ADDR gCatches=0x$GCATCHES_ADDR gPropagates=0x$GPROP_ADDR"

DEVICE_DIR=/data/local/tmp/gate1b/v3
"$ADB" shell "mkdir -p $DEVICE_DIR"
"$ADB" push "$DARTAOTRUNTIME_ARM64" "$DEVICE_DIR/dartaotruntime_product"
"$ADB" push "$BUILD_DIR/main.snapshot" "$DEVICE_DIR/main.snapshot"
"$ADB" push "$BUILD_DIR/f_patch.bytecode" "$DEVICE_DIR/f_patch.bytecode"
"$ADB" shell "chmod 755 $DEVICE_DIR/dartaotruntime_product"
"$ADB" shell "$DEVICE_DIR/dartaotruntime_product $DEVICE_DIR/main.snapshot $DEVICE_DIR/f_patch.bytecode $DEVICE_DIR/main.snapshot $F_ADDR $FALT_ADDR $GCATCHES_ADDR $GPROP_ADDR"
