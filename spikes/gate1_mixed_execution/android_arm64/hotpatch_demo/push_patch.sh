#!/bin/bash
# STEP 2 (run per patch): compile ONE patch source file to bytecode and push
# it into the device's patches directory. Does NOT touch the installed app
# (dartaotruntime_product / app.snapshot / manifest.txt) at all.
# 第二步(每发一个补丁跑一次)：把一个补丁源文件编译成字节码，推到设备的补丁
# 目录。完全不碰已安装的 app(dartaotruntime_product / app.snapshot /
# manifest.txt)。
#
# Usage: DART_SDK_SRC=~/dart/sdk ./push_patch.sh patch_v1/f_patch.dart
#    or: DART_SDK_SRC=~/dart/sdk ./push_patch.sh patch_v2/f_patch.dart
set -e

: "${DART_SDK_SRC:?Set DART_SDK_SRC to the dart-lang/sdk source root}"
ADB="${ADB:-adb}"
PATCH_SRC="${1:?Usage: ./push_patch.sh <path-to-patch.dart>, e.g. patch_v1/f_patch.dart}"

CASE_DIR="$(cd "$(dirname "$0")" && pwd)"
PATCH_SRC_ABS="$(cd "$(dirname "$PATCH_SRC")" && pwd)/$(basename "$PATCH_SRC")"
BUILD_DIR="$(mktemp -d -t hotpatch_push_XXXXXX)"
trap 'rm -rf "$BUILD_DIR"' EXIT

HOST_OUT="$DART_SDK_SRC/out/ReleaseX64"
ANDROID_OUT="$DART_SDK_SRC/out/ReleaseAndroidARM64"
AOT_RUNTIME_HOST="$HOST_OUT/dartaotruntime_product"
DART2BYTECODE_HOST="$HOST_OUT/gen/dart2bytecode.dart.snapshot"
VM_PLATFORM_ARM64="$ANDROID_OUT/vm_platform.dill"

echo "==> [1/2] Compile $PATCH_SRC to bytecode (target arm64 platform.dill)"
"$AOT_RUNTIME_HOST" "$DART2BYTECODE_HOST" \
  --platform "$VM_PLATFORM_ARM64" --target vm \
  -Ddart.vm.product=true -Ddynamic.modules.test.mode=aot \
  --bytecode-options=source-positions \
  --output "$BUILD_DIR/current.bytecode" \
  "$PATCH_SRC_ABS"

echo "==> [2/2] Push to device patches directory"
PATCH_DIR=/data/local/tmp/hotpatch_demo/patches
"$ADB" shell "mkdir -p $PATCH_DIR"
"$ADB" push "$BUILD_DIR/current.bytecode" "$PATCH_DIR/current.bytecode"
echo "==> Patch pushed. Run ./restart.sh to see it take effect."
