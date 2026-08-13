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

# 工具链：默认用 X1 引擎（补丁必须与 base 同源 —— base 是 X1 的 gen_snapshot 产出的）。
# 设 FHP_TOOLCHAIN=shorebird 可切到 Shorebird 预编译引擎。
FHP_TOOLCHAIN="${FHP_TOOLCHAIN:-x1}"

if [ "$FHP_TOOLCHAIN" = "x1" ]; then
    E=~/engine_ios/src/out
    GEN_SNAPSHOT=$E/ios_release/gen_snapshot_arm64
    ANALYZE=$E/ios_release/analyze_snapshot_arm64
    DARTAOT=~/engine_ios/src/flutter/prebuilts/macos-x64/dart-sdk/bin/dartaotruntime
    FRONTEND=~/engine_ios/src/flutter/prebuilts/macos-x64/dart-sdk/bin/snapshots/frontend_server_aot.dart.snapshot
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

BASE_APP="$APP_DIR/build/ios/iphoneos/Runner.app/Frameworks/App.framework/App"
[ -f "$BASE_APP" ] || { echo "MISSING base app: $BASE_APP（先跑一次 release 构建）" >&2; exit 1; }

mkdir -p "$OUT_DIR"

echo "[1/5] 编译改动后的 kernel dill（用 frontend_server，与 flutter build 同一路径）"
PKG_NAME=$(python3 -c "
import re,sys
for l in open('$PATCHED_DIR/pubspec.yaml'):
    m=re.match(r'^name:\s*(\S+)', l)
    if m: print(m.group(1)); break
")
"$DARTAOT" "$FRONTEND" \
    --sdk-root "$SDK_ROOT/" \
    --target=flutter \
    --no-print-incremental-dependencies \
    -Ddart.vm.profile=false -Ddart.vm.product=true \
    --delete-tostring-package-uri=dart:ui \
    --delete-tostring-package-uri=package:flutter \
    --aot --tfa --target-os ios \
    --packages "$PATCHED_DIR/.dart_tool/package_config.json" \
    --output-dill "$OUT_DIR/patch.dill" \
    --verbosity=error \
    "package:$PKG_NAME/main.dart"

echo "[2/5] gen_snapshot -> patch ELF（.vmcode 内嵌必须是 ELF）"
"$GEN_SNAPSHOT" --deterministic \
    --snapshot_kind=app-aot-elf \
    --elf="$OUT_DIR/patch.aot" \
    "$OUT_DIR/patch.dill"

echo "[3/5] analyze_snapshot base（Mach-O）"
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
echo "base(Mach-O): $(wc -c < "$BASE_APP" | tr -d ' ') bytes"
echo "patch(ELF):   $(wc -c < "$OUT_DIR/patch.aot" | tr -d ' ') bytes"
echo "out.vmcode:   $(wc -c < "$OUT_DIR/out.vmcode" | tr -d ' ') bytes"
echo "link%:        ${LINK_PCT}%"
