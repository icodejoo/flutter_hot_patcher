#!/bin/bash
# STEP 1 (run ONCE): build the demo "app" and install it to the device.
# 第一步(只跑一次)：构建演示用的"app"，安装到设备上。
#
# After this, the app lives at /data/local/tmp/hotpatch_demo/app/ on the
# device. Nothing in that directory is touched again by push_patch.sh —
# patches go into a SEPARATE directory. This mirrors "install the app once;
# ship patches independently afterward."
#
# 跑完之后，app 就在设备的 /data/local/tmp/hotpatch_demo/app/ 里了。之后
# push_patch.sh 不会再碰这个目录——补丁进的是**另一个**独立目录。这就是
# "app 装一次；之后独立发补丁"这个流程的模拟。
#
# Requires: same host x64 + Android arm64 Dart SDK build as
# ../v1_replace_existing_function/build_and_push.sh (see that file's header
# and ../../vm_patch/README.md for the one-time SDK setup).
#
# Usage: DART_SDK_SRC=~/dart/sdk ./install.sh
set -e

: "${DART_SDK_SRC:?Set DART_SDK_SRC to the dart-lang/sdk source root}"
ADB="${ADB:-adb}"

CASE_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="$(mktemp -d -t hotpatch_install_XXXXXX)"
trap 'rm -rf "$BUILD_DIR"' EXIT

HOST_OUT="$DART_SDK_SRC/out/ReleaseX64"
ANDROID_OUT="$DART_SDK_SRC/out/ReleaseAndroidARM64"
GEN_KERNEL_HOST="$HOST_OUT/gen/gen_kernel_aot.dart.snapshot"
AOT_RUNTIME_HOST="$HOST_OUT/dartaotruntime_product"
GEN_SNAPSHOT_ARM64="$ANDROID_OUT/clang_x64/exe.stripped/gen_snapshot_product"
VM_PLATFORM_ARM64="$ANDROID_OUT/vm_platform.dill"
DARTAOTRUNTIME_ARM64="$ANDROID_OUT/dartaotruntime_product"

echo "==> [1/4] AOT-compile the app"
"$AOT_RUNTIME_HOST" "$GEN_KERNEL_HOST" \
  --target vm \
  -Ddart.vm.product=true -Ddynamic.modules.test.mode=aot \
  --aot --no-embed-sources --platform "$VM_PLATFORM_ARM64" \
  --output "$BUILD_DIR/app_aot.dill" \
  "$CASE_DIR/host/main.dart"

echo "==> [2/4] Generate arm64 AOT snapshot (app.snapshot — name matters, main.dart checks for it)"
"$GEN_SNAPSHOT_ARM64" --snapshot-kind=app-aot-elf \
  --elf="$BUILD_DIR/app.snapshot" "$BUILD_DIR/app_aot.dill"

echo "==> [3/4] Write manifest.txt (function addresses, resolved once via nm)"
G_ADDR=$(nm "$BUILD_DIR/app.snapshot" | awk '$3=="g"{print $1}' | head -1)
F_ADDR=$(nm "$BUILD_DIR/app.snapshot" | awk '$3=="f"{print $1}' | head -1)
FALT_ADDR=$(nm "$BUILD_DIR/app.snapshot" | awk '$3=="fAlt"{print $1}' | head -1)
cat > "$BUILD_DIR/manifest.txt" <<EOF
g=$G_ADDR
f=$F_ADDR
fAlt=$FALT_ADDR
EOF
echo "    $(cat "$BUILD_DIR/manifest.txt" | tr '\n' ' ')"

echo "==> [4/4] Install to device (app dir), run once to show baseline"
APP_DIR=/data/local/tmp/hotpatch_demo/app
PATCH_DIR=/data/local/tmp/hotpatch_demo/patches
"$ADB" shell "mkdir -p $APP_DIR $PATCH_DIR"
"$ADB" shell "rm -f $PATCH_DIR/current.bytecode"   # fresh install: no patch yet
"$ADB" push "$DARTAOTRUNTIME_ARM64" "$APP_DIR/dartaotruntime_product"
"$ADB" push "$BUILD_DIR/app.snapshot" "$APP_DIR/app.snapshot"
"$ADB" push "$BUILD_DIR/manifest.txt" "$APP_DIR/manifest.txt"
"$ADB" shell "chmod 755 $APP_DIR/dartaotruntime_product"

echo ""
echo "==> Installed. Running once to show baseline behavior:"
"$ADB" shell "$APP_DIR/dartaotruntime_product $APP_DIR/app.snapshot"
