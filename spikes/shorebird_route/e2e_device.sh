#!/usr/bin/env bash
# X1 + Shorebird OTA 真机 E2E。
#
#   DEVICE=<identifier> ./e2e_device.sh
#
# 前置：补丁已生成（tools/build_app_patch.sh），app 已用 X1 引擎构建为 baseline。
# 设备路径来自引擎源码 shell/common/shorebird/shorebird.cc:147-162：
#   <app 支持目录>/shorebird/shorebird_updater/<app_id>/
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
V="$HERE/valapp29"
DEVICE="${DEVICE:-}"
BUNDLE_ID="${BUNDLE_ID:-com.hotpatch.valapp29}"
PATCH_DIR="${PATCH_DIR:-/tmp/valpatch}"

if [ -z "$DEVICE" ]; then
    echo "设备列表："
    xcrun devicectl list devices
    echo ""
    echo "用法： DEVICE=<identifier> $0" >&2
    exit 1
fi

step() { echo ""; echo "=== $* ==="; }

step "1. 确认产物齐备"
APP="$V/build/ios/iphoneos/Runner.app"
[ -d "$APP" ] || { echo "缺 Runner.app —— 先用 X1 构建 baseline" >&2; exit 1; }
[ -f "$PATCH_DIR/out.vmcode" ] || { echo "缺 out.vmcode —— 先跑 tools/build_app_patch.sh" >&2; exit 1; }
printf "app:      %s\n" "$APP"
printf "vmcode:   %s bytes\n" "$(wc -c < "$PATCH_DIR/out.vmcode" | tr -d ' ')"
printf "引擎集成: shorebird_* 导出 %s 个\n" \
  "$(dyld_info -exports "$APP/Frameworks/Flutter.framework/Flutter" 2>/dev/null | grep -c shorebird)"

step "2. 签名（构建时用了 --no-codesign）"
IDENTITY="${IDENTITY:-$(security find-identity -v -p codesigning | awk 'NR==1{print $2}')}"
echo "使用身份: $IDENTITY"
codesign --force --sign "$IDENTITY" --timestamp=none \
    "$APP/Frameworks/Flutter.framework" \
    "$APP/Frameworks/App.framework" 2>/dev/null || true
codesign --force --sign "$IDENTITY" --timestamp=none --entitlements /dev/null "$APP"
codesign -dv "$APP" 2>&1 | head -3

step "3. 安装"
xcrun devicectl device install app --device "$DEVICE" "$APP"

step "4. 启动 baseline，应显示 BASELINE_V1"
echo "手动确认屏幕显示 'BASELINE_V1'（橙色底）。"
xcrun devicectl device process launch --device "$DEVICE" --console "$BUNDLE_ID" 2>&1 | head -30 &
LAUNCH=$!
sleep 15
kill "$LAUNCH" 2>/dev/null || true

step "5. 推送补丁"
cat <<'MANUAL'
updater 的补丁目录（来自 shell/common/shorebird/shorebird.cc:147-162）：
  <appDataContainer>/Library/Application Support/shorebird/shorebird_updater/<app_id>/

app_id 取自 shorebird.yaml（本 spike 为 11111111-2222-3333-4444-555555555555）。

推送：
  xcrun devicectl device copy to --device "$DEVICE" \
      --domain-type appDataContainer --domain-identifier "$BUNDLE_ID" \
      --source /tmp/valpatch/out.vmcode \
      --destination "Library/Application Support/shorebird/shorebird_updater/<app_id>/patches/1/dlc.vmcode"

再写 state.json 标记 next_boot_patch（字段名见 framework 二进制里的
PatchState / next_boot_patch / last_booted_patch）。

或走网络：把 shorebird.yaml 的 base_url 指向 tools/patch_server，
让 updater 自行下载（需设备能连到该地址）。
MANUAL

step "6. 冷重启并验证"
cat <<'MANUAL'
  xcrun devicectl device process terminate --device "$DEVICE" --bundle-id "$BUNDLE_ID"
  xcrun devicectl device process launch --device "$DEVICE" --console "$BUNDLE_ID"

PASS = 屏幕显示 'OTA_PATCHED_V2'（绿色底）+ 'PATCH ACTIVE'
FAIL = 仍为 BASELINE_V1
MANUAL
