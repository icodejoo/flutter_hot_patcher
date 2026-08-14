#!/usr/bin/env bash
# X1 + Shorebird OTA 真机 E2E（步骤 1：验证补丁在设备上真的生效）
#
#   DEVICE=<identifier> ./e2e_device.sh
#
# 补丁布局与状态格式全部取自上游 updater 源码，非猜测：
#   目录常量  library/src/cache/lifecycle.rs:53-55
#     PATCHES_DIR="patches"  PATCH_STATE_FILE="state.json"  POINTERS_FILE="pointers.json"
#   state_root  shell/common/shorebird/shorebird.cc:158-159
#     <app_storage>/shorebird_updater/<app_id>
#   PatchState  lifecycle.rs:59 #[serde(tag="kind")] → {"kind":"Installed",...}
#   ReleasePointers lifecycle.rs:129-141
#
# 最终布局：
#   <state_root>/patches/<N>/dlc.vmcode
#   <state_root>/patches/<N>/state.json
#   <state_root>/pointers.json
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
V="$HERE/valapp29"
DEVICE="${DEVICE:-}"
BUNDLE_ID="${BUNDLE_ID:-com.hotpatch.valapp29}"
PATCH_DIR="${PATCH_DIR:-/tmp/valpatch}"
PATCH_N="${PATCH_N:-1}"
APP_ID="${APP_ID:-11111111-2222-3333-4444-555555555555}"

if [ -z "$DEVICE" ]; then
    echo "设备列表："; xcrun devicectl list devices
    echo ""; echo "用法： DEVICE=<identifier> $0" >&2; exit 1
fi

step() { echo ""; echo "=== $* ==="; }

step "1. 产物检查"
APP="$V/build/ios/iphoneos/Runner.app"
VMCODE="$PATCH_DIR/out.vmcode"
[ -d "$APP" ]     || { echo "缺 Runner.app（先用 X1 构建 baseline）" >&2; exit 1; }
[ -f "$VMCODE" ]  || { echo "缺 out.vmcode（先跑 tools/build_app_patch.sh）" >&2; exit 1; }
SIZE=$(wc -c < "$VMCODE" | tr -d ' ')
printf "vmcode: %s bytes | 引擎 shorebird_* 导出: %s\n" "$SIZE" \
  "$(dyld_info -exports "$APP/Frameworks/Flutter.framework/Flutter" 2>/dev/null | grep -c shorebird)"

step "2. 签名"
# 如果 flutter build 已经带描述文件正确签过（没传 --no-codesign），就别再签一遍：
# 用 find-identity 的第一条很可能是别的 team 的证书，重签会让描述文件对不上，
# devicectl install 直接失败。
if codesign --verify --deep --strict "$APP" >/dev/null 2>&1 && \
   [ -e "$APP/embedded.mobileprovision" ]; then
    echo "已带描述文件签好，跳过重签"
else
    IDENTITY="${IDENTITY:-$(security find-identity -v -p codesigning | awk 'NR==1{print $2}')}"
    echo "身份: $IDENTITY"
    for f in "$APP/Frameworks/Flutter.framework" "$APP/Frameworks/App.framework"; do
        [ -e "$f" ] && codesign --force --sign "$IDENTITY" --timestamp=none "$f"
    done
    codesign --force --sign "$IDENTITY" --timestamp=none "$APP"
fi
codesign -dv "$APP" 2>&1 | head -2

step "3. 安装并跑 baseline"
xcrun devicectl device install app --device "$DEVICE" "$APP"
echo "启动 15s，屏幕应显示 BASELINE_V1（橙色底）"
( xcrun devicectl device process launch --device "$DEVICE" --console "$BUNDLE_ID" 2>&1 | head -40 ) &
LP=$!; sleep 15; kill "$LP" 2>/dev/null || true

step "4. 构造 updater 状态（格式取自上游源码）"
STAGE=$(mktemp -d)
mkdir -p "$STAGE/patches/$PATCH_N"
cp "$VMCODE" "$STAGE/patches/$PATCH_N/dlc.vmcode"
python3 - "$STAGE" "$PATCH_N" "$SIZE" <<'PY'
import json, sys, pathlib
stage, n, size = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
root = pathlib.Path(stage)
# PatchState 是 internally tagged（lifecycle.rs:59 #[serde(tag="kind")]）
(root/'patches'/str(n)/'state.json').write_text(json.dumps(
    {"kind": "Installed", "signature": None, "size": size}))
(root/'pointers.json').write_text(json.dumps(
    {"next_boot_patch": n, "last_booted_patch": None,
     "currently_booting_patch": None, "boot_started_at": None}))
print("state.json:", (root/'patches'/str(n)/'state.json').read_text())
print("pointers.json:", (root/'pointers.json').read_text())
PY

step "5. 推送到设备"
# 实测修正（2026-08-14 真机）：state root **没有** <app_id> 这一层。
# 带 app_id 的目录 updater 完全不看，日志停在 "no active patch"。
# 正确路径由设备上 updater 自己建的目录反推得到。
DEST="Library/Application Support/shorebird/shorebird_updater"
echo "目标: $DEST"
xcrun devicectl device copy to --device "$DEVICE" \
    --domain-type appDataContainer --domain-identifier "$BUNDLE_ID" \
    --source "$STAGE/patches" --destination "$DEST/patches"
xcrun devicectl device copy to --device "$DEVICE" \
    --domain-type appDataContainer --domain-identifier "$BUNDLE_ID" \
    --source "$STAGE/pointers.json" --destination "$DEST/pointers.json"
rm -rf "$STAGE"

step "6. 冷重启并验证"
xcrun devicectl device process terminate --device "$DEVICE" --bundle-id "$BUNDLE_ID" 2>/dev/null || true
sleep 2
echo "启动 20s。PASS = 显示 OTA_PATCHED_V2（绿色底）+ PATCH ACTIVE"
echo "                FAIL = 仍显示 BASELINE_V1"
( xcrun devicectl device process launch --device "$DEVICE" --console "$BUNDLE_ID" 2>&1 | head -60 ) &
LP=$!; sleep 20; kill "$LP" 2>/dev/null || true

echo ""
echo "如未生效，看设备日志里的 [shorebird] 行："
echo "  log stream --device --predicate 'eventMessage CONTAINS \"shorebird\"'"
