#!/bin/bash
# Build the V6 (multi-hop static-call chain, no V1) repro on Android arm64
# and push+run via adb.
#
# Like V2, this case needs NO arm64-specific patching code at all --
# loadDynamicModuleClosure / redirectClosureEntryPoint operate entirely
# through the VM natives (Closure object fields, bytecode module loading),
# never touching raw machine code or instruction encoding. host/main.dart
# is an unmodified copy of the desktop x64 case. This IS the point of V6:
# if the desktop x64 result cross-validates cleanly on a second, unrelated
# architecture with zero changes, that's strong evidence the mechanism is
# architecture-independent by construction (same reasoning V2's Android
# script already documented).
#
# 跟 V2 一样，这个用例完全不需要任何 arm64 专属的改写代码——
# loadDynamicModuleClosure / redirectClosureEntryPoint 全程通过 VM 原生函数
# (Closure 对象字段、字节码模块加载)操作，完全不碰原始机器码或指令编码。
# host/main.dart 是桌面 x64 用例的原样拷贝。这正是 V6 要验证的：如果桌面 x64
# 的结果能在第二个、不相关的架构上零改动干净复现，就是"这套机制天生架构无关"
# 的有力证据(跟 V2 的 Android 脚本记录的推理一致)。
#
# Requires: Android arm64 dart-sdk build (same as ../v1_replace_existing_function,
# see that script's header for the one-time build.py invocation). Bytecode
# compilation (dart2bytecode) and kernel compilation (gen_kernel) run on the
# HOST x64 toolchain regardless of target arch -- bytecode/kernel IR are
# architecture-independent; only gen_snapshot (AOT codegen) and vm_platform.dill
# are arch-specific (see ../vm_patch/README.md "Android arm64 交叉编译" section).
#
# Usage: DART_SDK_SRC=~/dart/sdk ./build_and_push.sh
set -e

: "${DART_SDK_SRC:?Set DART_SDK_SRC to the dart-lang/sdk source root}"
ADB="${ADB:-adb}"

CASE_DIR="$(cd "$(dirname "$0")" && pwd)"
DESKTOP_CASE_DIR="$CASE_DIR/../../cases/v6_multihop_no_v1"
# adb.exe is a WINDOWS binary (invoked via WSL interop) -- it cannot see paths
# inside the WSL2 VM's own Linux filesystem (/root/..., /tmp/...). BUILD_DIR
# must live under a DrvFs-mounted path (/mnt/c/...) that both WSL and Windows
# can resolve, or every `adb push` of a WSL-only path silently fails
# ("cannot stat ... No such file or directory") from adb's point of view.
#
# adb.exe 是 Windows 二进制(经 WSL interop 调用)——看不到 WSL2 虚拟机自己的
# Linux 文件系统里的路径(/root/...、/tmp/...)。BUILD_DIR 必须放在 DrvFs 挂载
# 路径(/mnt/c/...)下，WSL 和 Windows 才能都解析到，否则每次 `adb push` 一个
# 只存在于 WSL 内部的路径都会从 adb 的视角"悄悄"失败(报 cannot stat)。
BUILD_DIR="$(mktemp -d -p /mnt/c/workspace/flutter_hot_patcher/.build_tmp -t gate1b_v6_android_XXXXXX 2>/dev/null || { mkdir -p /mnt/c/workspace/flutter_hot_patcher/.build_tmp && mktemp -d -p /mnt/c/workspace/flutter_hot_patcher/.build_tmp -t gate1b_v6_android_XXXXXX; })"
trap 'rm -rf "$BUILD_DIR"' EXIT

HOST_OUT="$DART_SDK_SRC/out/ReleaseX64"
ANDROID_OUT="$DART_SDK_SRC/out/ReleaseAndroidARM64"

GEN_KERNEL_HOST="$HOST_OUT/gen/gen_kernel_aot.dart.snapshot"
AOT_RUNTIME_HOST="$HOST_OUT/dartaotruntime_product"
DART2BYTECODE_HOST="$HOST_OUT/gen/dart2bytecode.dart.snapshot"
GEN_SNAPSHOT_ARM64="$ANDROID_OUT/clang_x64/exe.stripped/gen_snapshot_product"
VM_PLATFORM_ARM64="$ANDROID_OUT/vm_platform.dill"
# stripped variant is fine here -- unlike V1, this test never scans symbols
# (`nm`) on the runtime binary, no code addresses are ever resolved.
DARTAOTRUNTIME_ARM64="$ANDROID_OUT/exe.stripped/dartaotruntime_product"

echo "==> [1/5] AOT-compile host (stepA/stepB/stepC + entryVar), targeting arm64 platform.dill"
"$AOT_RUNTIME_HOST" "$GEN_KERNEL_HOST" \
  --target vm \
  -Ddart.vm.product=true -Ddynamic.modules.test.mode=aot \
  --aot --no-embed-sources --platform "$VM_PLATFORM_ARM64" \
  --output "$BUILD_DIR/main_aot.dill" \
  "$DESKTOP_CASE_DIR/test-lib/host/main.dart"

echo "==> [2/5] Generate arm64 AOT snapshot (host gen_snapshot, target arm64)"
"$GEN_SNAPSHOT_ARM64" --snapshot-kind=app-aot-elf \
  --elf="$BUILD_DIR/main.snapshot" "$BUILD_DIR/main_aot.dill"

echo "==> [3/5] Compile the interpreted A->B->C replacement chain to bytecode (target arm64 platform.dill)"
"$AOT_RUNTIME_HOST" "$DART2BYTECODE_HOST" \
  --platform "$VM_PLATFORM_ARM64" --target vm \
  -Ddart.vm.product=true -Ddynamic.modules.test.mode=aot \
  --bytecode-options=source-positions \
  --output "$BUILD_DIR/module.bytecode" \
  "$DESKTOP_CASE_DIR/test-lib/patch/module.dart"

echo "==> [4/5] Push to device"
# Copy the runtime binary into the DrvFs-visible BUILD_DIR too -- same
# adb.exe/WSL-interop path-visibility constraint as above. adb.exe (a native
# Windows binary reached via WSL interop) does not translate POSIX-style
# /mnt/c/... arguments on its own -- each local path handed to `adb push`
# must be converted to a Windows-style path first (`wslpath -w`), or adb
# reports "cannot stat ''" / "No such file or directory" even though the
# file genuinely exists and `ls` can see it from WSL.
#
# 把运行时二进制也拷进 DrvFs 可见的 BUILD_DIR——跟上面同样的
# adb.exe/WSL-interop 路径可见性限制。adb.exe(经 WSL interop 调用的原生
# Windows 二进制)不会自动转换 POSIX 风格的 /mnt/c/... 参数——每个传给
# `adb push` 的本地路径都得先转成 Windows 风格路径(`wslpath -w`)，
# 否则即使文件真实存在、WSL 的 `ls` 也能看到，adb 依然会报
# "cannot stat ''"/"No such file or directory"。
cp "$DARTAOTRUNTIME_ARM64" "$BUILD_DIR/dartaotruntime_product"
DEVICE_DIR=/data/local/tmp/gate1b/v6
"$ADB" shell "mkdir -p $DEVICE_DIR"
"$ADB" push "$(wslpath -w "$BUILD_DIR/dartaotruntime_product")" "$DEVICE_DIR/dartaotruntime_product"
"$ADB" push "$(wslpath -w "$BUILD_DIR/main.snapshot")" "$DEVICE_DIR/main.snapshot"
"$ADB" push "$(wslpath -w "$BUILD_DIR/module.bytecode")" "$DEVICE_DIR/module.bytecode"
"$ADB" shell "chmod 755 $DEVICE_DIR/dartaotruntime_product"

echo "==> [5/5] Run on device"
"$ADB" shell "$DEVICE_DIR/dartaotruntime_product $DEVICE_DIR/main.snapshot $DEVICE_DIR/module.bytecode"
