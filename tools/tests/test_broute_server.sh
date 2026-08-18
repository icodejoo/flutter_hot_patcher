#!/usr/bin/env bash
# 校验补丁服务端实现的协议与设备更新器一致。
# 字段依据 third_party/updater/library/src/network.rs（PatchCheckRequest/Response）。
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PY="$REPO_ROOT/tools/.venv/bin/python"
TMP="$(mktemp -d)"; PORT=8791
FAILS=0
fail(){ echo "FAIL: $1"; FAILS=$((FAILS+1)); }
pass(){ echo "PASS: $1"; }
cleanup(){ [ -n "${SRV:-}" ] && kill "$SRV" 2>/dev/null; rm -rf "$TMP"; }
trap cleanup EXIT

# 构造一个最小仓库
mkdir -p "$TMP/repo/releases/1.0.0+1/patches"
head -c 4096 /dev/urandom > "$TMP/repo/releases/1.0.0+1/patches/1.bin"
cat > "$TMP/repo/releases/1.0.0+1/index.json" <<JSON
{"patches":[{"number":1,"hash":"abc123","download_url":"http://127.0.0.1:$PORT/patches/1.0.0+1/1.bin","hash_signature":"SIGN"}],"rolled_back":[7]}
JSON

"$PY" "$REPO_ROOT/tools/broute/server.py" --repo "$TMP/repo" --port "$PORT" \
  --bind 127.0.0.1 --app-id APP1 >"$TMP/srv.log" 2>&1 &
SRV=$!
sleep 2

req(){ curl -s -m 5 -X POST "http://127.0.0.1:$PORT/api/v1/patches/check" \
       -H 'Content-Type: application/json' -d "$1"; }

# 1) 匹配的 app_id + 无当前补丁 -> 下发
R1=$(req '{"app_id":"APP1","channel":"stable","release_version":"1.0.0+1","platform":"ios","arch":"aarch64","client_id":"c"}')
echo "$R1" | grep -q '"patch_available": true' && pass "有补丁时下发" || { fail "应下发补丁"; echo "  $R1"; }
echo "$R1" | grep -q '"hash_signature"' && pass "带签名字段" || fail "缺 hash_signature"
echo "$R1" | grep -q '"rolled_back_patch_numbers"' && pass "带回滚列表" || fail "缺 rolled_back_patch_numbers"

# 2) 已是最新 -> 不下发
R2=$(req '{"app_id":"APP1","channel":"stable","release_version":"1.0.0+1","platform":"ios","arch":"aarch64","client_id":"c","current_patch_number":1}')
echo "$R2" | grep -q '"patch_available": false' && pass "已最新则不下发" || { fail "已最新仍下发"; echo "  $R2"; }

# 3) app_id 不匹配 -> 不下发（防止发给别的应用）
R3=$(req '{"app_id":"OTHER","channel":"stable","release_version":"1.0.0+1","platform":"ios","arch":"aarch64","client_id":"c"}')
echo "$R3" | grep -q '"patch_available": false' && pass "app_id 不匹配则不下发" || fail "app_id 不匹配却下发"

# 4) 未知 release -> 不下发
R4=$(req '{"app_id":"APP1","channel":"stable","release_version":"9.9.9+9","platform":"ios","arch":"aarch64","client_id":"c"}')
echo "$R4" | grep -q '"patch_available": false' && pass "未知 release 不下发" || fail "未知 release 却下发"

# 5) 下载端点可用且字节一致
curl -s -m 5 -o "$TMP/got.bin" "http://127.0.0.1:$PORT/patches/1.0.0+1/1.bin"
cmp -s "$TMP/got.bin" "$TMP/repo/releases/1.0.0+1/patches/1.bin" \
  && pass "下载字节一致" || fail "下载内容不一致"

# 6) 事件端点返回 201 并落盘
C=$(curl -s -m 5 -o /dev/null -w '%{http_code}' -X POST "http://127.0.0.1:$PORT/api/v1/patches/events" \
    -H 'Content-Type: application/json' -d '{"event":{"type":"__patch_install__"}}')
[ "$C" = "201" ] && pass "事件端点返回 201" || fail "事件端点返回 $C"
[ -s "$TMP/repo/events.log" ] && pass "事件已落盘" || fail "事件未落盘"

echo "---"
[ "$FAILS" -eq 0 ] && { echo "ALL PASS"; exit 0; } || { echo "$FAILS FAILURE(S)"; exit 1; }
