#!/usr/bin/env bash
# 为一个已构建的 Flutter iOS release app 生成 .vmcode 补丁。
#
#   build_app_patch.sh <app_dir> <patched_lib_dir> <out_dir>
#
# <app_dir>          Flutter 工程根（含 .dart_tool/flutter_build 与 build/ios/iphoneos）
# <patched_lib_dir>  含改动后 lib/ 的目录（通常就是同一工程，改完源码后传它自己）
# <out_dir>          产出目录
#
# 形态说明（实测得出）：
#   base  = app 自带的 Mach-O App.framework/App —— analyze_snapshot 能直接读
#   patch = 必须是 ELF，因为引擎侧 patch_cache.cc 用 Dart_LoadELF 打开 .vmcode
set -euo pipefail

APP_DIR="${1:?usage: $0 <app_dir> <patched_lib_dir> <out_dir>}"
PATCHED_DIR="${2:?usage: $0 <app_dir> <patched_lib_dir> <out_dir>}"
OUT_DIR="${3:?usage: $0 <app_dir> <patched_lib_dir> <out_dir>}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# 工具链：默认 Shorebird 预编译引擎 —— 这是唯一的产品路径。
# 补丁必须与 base 同源，所以基线也必须是同一套工具链构建的。
# FHP_TOOLCHAIN=x1 切到 X1 引擎，仅供研究（Route-A / 同引擎 A/B 对拍）使用。
FHP_TOOLCHAIN="${FHP_TOOLCHAIN:-shorebird}"

if [ "$FHP_TOOLCHAIN" = "x1" ]; then
    E=~/engine_ios/src/out
    GEN_SNAPSHOT=$E/ios_release/gen_snapshot_arm64
    # 必须用引擎构建的那份：它是 macOS host 可执行 + iOS 目标配置。
    # Dart SDK 的 ReleaseARM64 是 macOS 目标，读 iOS 快照会 SIGSEGV。
    ANALYZE=$E/ios_release/analyze_snapshot_arm64
    # Prefer the engine's own arm64 host toolchain: the prebuilt dart-sdk is a
    # different Dart whose kernel binary format is 122 while ~/dart/sdk is 121,
    # so the patch dill would not match the base. Build it with
    # tools/route_a/build_host_engine.sh.
    HOST_SDK=$E/host_release_arm64/dart-sdk
    [ -x "$HOST_SDK/bin/dartaotruntime" ] || \
        HOST_SDK=~/engine_ios/src/flutter/prebuilts/macos-x64/dart-sdk
    DARTAOT=$HOST_SDK/bin/dartaotruntime
    FRONTEND=$HOST_SDK/bin/snapshots/frontend_server_aot.dart.snapshot
    SDK_ROOT=$E/ios_release/flutter_patched_sdk
else
    SB_REV=c15ef6379403a0a55531a058bdb2c8e55bc05c98
    SB=~/.shorebird/bin/cache/flutter/$SB_REV
    SB_ENGINE=$SB/bin/cache/artifacts/engine
    GEN_SNAPSHOT=$SB_ENGINE/ios-release/gen_snapshot_arm64
    ANALYZE=$SB_ENGINE/ios-release/analyze_snapshot_arm64
    DARTAOT=$SB/bin/cache/dart-sdk/bin/dartaotruntime
    FRONTEND=$SB/bin/cache/dart-sdk/bin/snapshots/frontend_server_aot.dart.snapshot
    SDK_ROOT=$SB_ENGINE/common/flutter_patched_sdk_product
fi

for f in "$GEN_SNAPSHOT" "$ANALYZE" "$DARTAOT" "$FRONTEND" "$SDK_ROOT" "$REPO_ROOT/tools/linker.py"; do
    [ -e "$f" ] || { echo "MISSING: $f" >&2; exit 1; }
done

# base 取 release 构建留下的 app.dill，用同一个 gen_snapshot 重新产成 **ELF**。
# 不直接分析 App.framework/App（Mach-O）：我们的 analyze_snapshot 只支持 ELF
# （Dart_LoadELF），而 Shorebird 的 Mach-O 支持在其私有 dart-sdk 里。
# 同一 dill + 同一 gen_snapshot + --deterministic ⇒ 内容一致，仅容器不同。
BASE_DILL="${FHP_BASE_DILL:-$(find "$APP_DIR/.dart_tool/flutter_build" -name "app.dill" 2>/dev/null | head -1)}"
[ -n "$BASE_DILL" ] || { echo "MISSING base app.dill（先跑一次 release 构建）" >&2; exit 1; }

mkdir -p "$OUT_DIR"

# FHP_BASE_AOT：release 归档时已经产过并验过的 base ELF。直接复用可省一次
# gen_snapshot，也保证补丁对的就是当初归档的那份基线（fhpb release 会传它）。
if [ -n "${FHP_BASE_AOT:-}" ]; then
    echo "[0/5] 复用已归档的 base ELF: $FHP_BASE_AOT"
    BASE_APP="$FHP_BASE_AOT"
else
    echo "[0/5] base kernel -> base ELF"
    "$GEN_SNAPSHOT" --deterministic \
        --snapshot_kind=app-aot-elf \
        --elf="$OUT_DIR/base.aot" \
        "$BASE_DILL"
    BASE_APP="$OUT_DIR/base.aot"
fi

# 复现 flutter 自己那串前端参数是不可靠的：它还会传 --no-link-platform、
# --delete-tostring-package-uri、插件注册入口等，漏一个 link% 就会崩到个位数
# （实测：一个带插件的 app 漏掉后是 2.62%）。带插件或带 dynamic interface 的
# 工程请改让 flutter 自己编补丁 kernel，再用 FHP_PATCH_DILL 传进来：
#   改源码 → flutter build ios ... → 取 .dart_tool/flutter_build/**/app.dill → 还原源码
if [ -n "${FHP_PATCH_DILL:-}" ]; then
    echo "[1/5] 用调用方提供的 patch dill: $FHP_PATCH_DILL"
    cp "$FHP_PATCH_DILL" "$OUT_DIR/patch.dill"
else

echo "[1/5] 编译改动后的 kernel dill（用 frontend_server，与 flutter build 同一路径）"
PKG_NAME=$(python3 -c "
import re,sys
for l in open('$PATCHED_DIR/pubspec.yaml'):
    m=re.match(r'^name:\s*(\S+)', l)
    if m: print(m.group(1)); break
")
# 若 base app 是带 dynamic interface 编的，补丁也必须带同一份，
# 否则两边 kernel 差异远超预期改动，link% 会失真。
DI_ARGS=()
if [ -n "${FHP_DYNAMIC_INTERFACE:-}" ]; then
    DI_ARGS=(--dynamic-interface "$FHP_DYNAMIC_INTERFACE")
fi

"$DARTAOT" "$FRONTEND" \
    --sdk-root "$SDK_ROOT/" \
    --target=flutter \
    ${DI_ARGS[@]+"${DI_ARGS[@]}"} \
    --no-print-incremental-dependencies \
    -Ddart.vm.profile=false -Ddart.vm.product=true \
    --delete-tostring-package-uri=dart:ui \
    --delete-tostring-package-uri=package:flutter \
    --aot --tfa --target-os ios \
    --packages "$PATCHED_DIR/.dart_tool/package_config.json" \
    --output-dill "$OUT_DIR/patch.dill" \
    --verbosity=error \
    "package:$PKG_NAME/main.dart"

fi

echo "[2/5] gen_snapshot -> patch ELF（.vmcode 内嵌必须是 ELF）"
"$GEN_SNAPSHOT" --deterministic \
    --snapshot_kind=app-aot-elf \
    --elf="$OUT_DIR/patch.aot" \
    "$OUT_DIR/patch.dill"

echo "[3/5] analyze_snapshot base（ELF）"
"$ANALYZE" --shorebird --out="$OUT_DIR/base.json" "$BASE_APP"

echo "[4/5] analyze_snapshot patch（ELF）"
"$ANALYZE" --shorebird --out="$OUT_DIR/patch.json" "$OUT_DIR/patch.aot"

echo "[5/5] link -> out.vmcode"
LINK_PCT=$(python3 "$REPO_ROOT/tools/linker.py" \
    --base="$BASE_APP" \
    --patch="$OUT_DIR/patch.aot" \
    --output="$OUT_DIR/out.vmcode" \
    --base-json="$OUT_DIR/base.json" \
    --patch-json="$OUT_DIR/patch.json" \
    --verbose)

echo ""
echo "=== 结果 ==="
echo "base(ELF):    $(wc -c < "$BASE_APP" | tr -d ' ') bytes"
echo "patch(ELF):   $(wc -c < "$OUT_DIR/patch.aot" | tr -d ' ') bytes"
echo "out.vmcode:   $(wc -c < "$OUT_DIR/out.vmcode" | tr -d ' ') bytes"
echo "link%:        ${LINK_PCT}%"
