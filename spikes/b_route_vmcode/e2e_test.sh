#!/usr/bin/env bash
# B-route 端对端测试脚本
# 用法: ./e2e_test.sh <base_App_path> <patch_App_path>
set -euo pipefail

BASE_APP="${1:?usage: e2e_test.sh <base_App> <patch_App>}"
PATCH_APP="${2:?usage: e2e_test.sh <base_App> <patch_App>}"

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
PB="$REPO/tools/patch_builder"
PS="$REPO/tools/patch_server"
PATCHES_DIR="$PS/patches"
RELEASE="1.0+1"
PATCH_NUM=1
OUT_DIR="$PATCHES_DIR/$RELEASE/vmcode-v$PATCH_NUM"

echo "=== B-route 端对端测试 ==="
echo "base:  $BASE_APP"
echo "patch: $PATCH_APP"
echo "output: $OUT_DIR"
echo ""

echo "--- 步骤1: 生成 vmcode patch ---"
python3 "$PB/vmcode_patch_builder.py" \
    --base-app "$BASE_APP" \
    --patch-app "$PATCH_APP" \
    --patch-number $PATCH_NUM \
    --release-version "$RELEASE" \
    --output-dir "$OUT_DIR"

echo ""
echo "--- 步骤2: 验证输出文件 ---"
ls -lh "$OUT_DIR/"
echo ""
echo "manifest.json:"
cat "$OUT_DIR/manifest.json"

echo ""
echo "--- 步骤3: 启动 patch server ---"
echo "运行: cd $PS && python3 patch_server.py --patches-dir $PATCHES_DIR --port 8765"
echo "然后用 curl 验证:"
echo "  curl -s -X POST http://localhost:8765/api/v1/patches/check \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d '{\"release_version\":\"$RELEASE\",\"platform\":\"ios\",\"channel\":\"stable\",\"current_patch_number\":0}'"
