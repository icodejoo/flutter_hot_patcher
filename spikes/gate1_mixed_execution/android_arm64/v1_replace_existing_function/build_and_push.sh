#!/bin/bash
# Build the Gate 1b Android arm64 repro and push it to a connected device via adb.
# 构建 Gate 1b Android arm64 复现用例，通过 adb 推到已连接的设备上。
#
# Requires:
#   - A Dart SDK checkout built for BOTH host x64 (out/ReleaseX64, with the
#     Gate 1 VM patch applied — see ../vm_patch/) AND Android arm64
#     (out/ReleaseAndroidARM64, same patch, same source tree — see below).
#   - adb on PATH (or set ADB=/path/to/adb), device connected + authorized.
#   - Working directory reachable via a path containing `test-lib` (dart:_internal
#     import allowlist — same trick as the desktop cases).
#
# To build the Android arm64 SDK target (one-time, alongside the existing host build):
#   cd ~/dart/sdk
#   ./tools/build.py --os android --arch arm64 -m release --dart-dynamic-modules \
#       runtime runtime_precompiled utils/gen_kernel
#   # Then force-build the specific artifacts this script needs (GN's default
#   # target names don't cover everything; see NOTES.md for why):
#   cd out/ReleaseAndroidARM64
#   ../../buildtools/ninja/ninja exe.stripped/dartaotruntime \
#       clang_x64/exe.stripped/gen_snapshot_product \
#       gen/gen_kernel_aot.dart.snapshot gen/dart2bytecode.dart.snapshot vm_platform.dill
#   ../../buildtools/ninja/ninja 'runtime/bin:dartaotruntime_product'
#
# Usage: DART_SDK_SRC=~/dart/sdk ./build_and_push.sh
set -e

: "${DART_SDK_SRC:?Set DART_SDK_SRC to the dart-lang/sdk source root}"
ADB="${ADB:-adb}"

CASE_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="$(mktemp -d -t gate1b_android_XXXXXX)"
trap 'rm -rf "$BUILD_DIR"' EXIT

HOST_OUT="$DART_SDK_SRC/out/ReleaseX64"
ANDROID_OUT="$DART_SDK_SRC/out/ReleaseAndroidARM64"

GEN_KERNEL_HOST="$HOST_OUT/gen/gen_kernel_aot.dart.snapshot"
AOT_RUNTIME_HOST="$HOST_OUT/dartaotruntime_product"
DART2BYTECODE_HOST="$HOST_OUT/gen/dart2bytecode.dart.snapshot"
GEN_SNAPSHOT_ARM64="$ANDROID_OUT/clang_x64/exe.stripped/gen_snapshot_product"
VM_PLATFORM_ARM64="$ANDROID_OUT/vm_platform.dill"
DARTAOTRUNTIME_ARM64="$ANDROID_OUT/dartaotruntime_product"  # unstripped — nm needs symbols

echo "==> [1/5] AOT-compile host (with existing f/g), targeting arm64 platform.dill"
"$AOT_RUNTIME_HOST" "$GEN_KERNEL_HOST" \
  --target vm \
  -Ddart.vm.product=true -Ddynamic.modules.test.mode=aot \
  --aot --no-embed-sources --platform "$VM_PLATFORM_ARM64" \
  --output "$BUILD_DIR/main_aot.dill" \
  "$CASE_DIR/host/main.dart"

echo "==> [2/5] Generate arm64 AOT snapshot (host gen_snapshot, target arm64)"
"$GEN_SNAPSHOT_ARM64" --snapshot-kind=app-aot-elf \
  --elf="$BUILD_DIR/main.snapshot" "$BUILD_DIR/main_aot.dill"

echo "==> [3/5] Compile replacement f' to bytecode (target arm64 platform.dill)"
"$AOT_RUNTIME_HOST" "$DART2BYTECODE_HOST" \
  --platform "$VM_PLATFORM_ARM64" --target vm \
  -Ddart.vm.product=true -Ddynamic.modules.test.mode=aot \
  --bytecode-options=source-positions \
  --output "$BUILD_DIR/f_patch.bytecode" \
  "$CASE_DIR/patch/f_patch.dart"

echo "==> [4/5] Resolve g/f/fAlt static addresses at BUILD time (device has no nm)"
G_ADDR=$(nm "$BUILD_DIR/main.snapshot" | awk '$3=="g"{print $1}' | head -1)
F_ADDR=$(nm "$BUILD_DIR/main.snapshot" | awk '$3=="f"{print $1}' | head -1)
FALT_ADDR=$(nm "$BUILD_DIR/main.snapshot" | awk '$3=="fAlt"{print $1}' | head -1)
echo "    g=0x$G_ADDR f=0x$F_ADDR fAlt=0x$FALT_ADDR"

echo "==> [5/5] Push to device and run"
DEVICE_DIR=/data/local/tmp/gate1b/v1
"$ADB" shell "mkdir -p $DEVICE_DIR"
"$ADB" push "$DARTAOTRUNTIME_ARM64" "$DEVICE_DIR/dartaotruntime_product"
"$ADB" push "$BUILD_DIR/main.snapshot" "$DEVICE_DIR/main.snapshot"
"$ADB" push "$BUILD_DIR/f_patch.bytecode" "$DEVICE_DIR/f_patch.bytecode"
"$ADB" shell "chmod 755 $DEVICE_DIR/dartaotruntime_product"
"$ADB" shell "$DEVICE_DIR/dartaotruntime_product $DEVICE_DIR/main.snapshot $DEVICE_DIR/f_patch.bytecode $DEVICE_DIR/main.snapshot $G_ADDR $F_ADDR $FALT_ADDR"
