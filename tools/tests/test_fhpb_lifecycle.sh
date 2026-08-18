#!/usr/bin/env bash
# 校验 fhpb 的全生命周期语义：init / release 归档 / 补丁自增 / 通道 / 回滚 /
# 服务端应答。不需要设备，也不需要 Shorebird 工具链 —— 用桩件替掉
# analyze_snapshot 与 patch 这两个外部二进制，只测我们自己的逻辑。
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PY="$REPO_ROOT/tools/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"
CLI="$REPO_ROOT/tools/broute/cli.py"
TMP="$(mktemp -d)"; PORT=8793
FAILS=0
fail(){ echo "FAIL: $1"; FAILS=$((FAILS+1)); }
pass(){ echo "PASS: $1"; }
cleanup(){ [ -n "${SRV:-}" ] && kill "$SRV" 2>/dev/null; rm -rf "$TMP"; }
trap cleanup EXIT

APP="$TMP/app"; REPO="$TMP/repo"; KEYS="$TMP/keys"; BIN="$TMP/bin"
mkdir -p "$BIN" "$APP/build/ios/iphoneos/Runner.app/Frameworks/App.framework" \
         "$APP/.dart_tool/flutter_build/x"

# --- 桩件：analyze_snapshot --dump_blobs 与 patch（bipatch 增量） -------------
cat > "$BIN/analyze_snapshot" <<'SH'
#!/usr/bin/env bash
for a in "$@"; do case "$a" in --out=*) OUT="${a#--out=}";; esac; done
head -c 65536 /dev/zero > "$OUT"
SH
cat > "$BIN/patch" <<'SH'
#!/usr/bin/env bash
# 真 patch 工具签名是 <base> <new> <out>；桩件只产出一个非空文件
head -c 1024 /dev/urandom > "$3"
SH
# gen_snapshot 桩件：只接受 kernel v130 的 dill，模拟真实工具链对版本的挑剔
cat > "$BIN/gen_snapshot" <<SH
#!/usr/bin/env bash
for a in "\$@"; do case "\$a" in --elf=*) ELF="\${a#--elf=}";; *.dill) DILL="\$a";; esac; done
VER=\$("$PY" -c "import sys;print(int.from_bytes(open(sys.argv[1],'rb').read(8)[4:8],'big'))" "\$DILL")
if [ "\$VER" != "130" ]; then
  echo "Can't load Kernel binary: Invalid kernel binary format version (expected 130, found \$VER)." >&2
  exit 253
fi
head -c 32768 /dev/zero > "\$ELF"
SH
chmod +x "$BIN/analyze_snapshot" "$BIN/patch" "$BIN/gen_snapshot"

# --- 构造一个假的 release 产物 -------------------------------------------------
"$PY" - "$APP" <<'PY'
import plistlib, pathlib, sys
app = pathlib.Path(sys.argv[1])
p = app/"build/ios/iphoneos/Runner.app/Info.plist"
p.write_bytes(plistlib.dumps({"CFBundleShortVersionString":"1.2.3","CFBundleVersion":"7"}))
PY
head -c 4096 /dev/urandom > "$APP/build/ios/iphoneos/Runner.app/Frameworks/App.framework/App"
# 两份 app.dill：新的那份是别的工具链留下的 v121，正确的是 v130。
# release 必须选 v130 那份，而不是 mtime 最新的那份。
mkdir -p "$APP/.dart_tool/flutter_build/good" "$APP/.dart_tool/flutter_build/stale"
mkdill(){ "$PY" -c "
import sys
open(sys.argv[1],'wb').write(b'\x90\xab\xcd\xef'+int(sys.argv[2]).to_bytes(4,'big')+b'\x00'*2048)" "$1" "$2"; }
mkdill "$APP/.dart_tool/flutter_build/good/app.dill" 130
sleep 1
mkdill "$APP/.dart_tool/flutter_build/stale/app.dill" 121
cat > "$APP/pubspec.yaml" <<'YAML'
name: demo
flutter:
  uses-material-design: true
YAML

# --- 1) init -------------------------------------------------------------------
OUT=$("$PY" "$CLI" init --app-dir "$APP" --base-url "http://127.0.0.1:$PORT" \
      --keys "$KEYS" --app-id APP1 2>&1)
[ -f "$KEYS/patch_private.pem" ] && pass "init 生成私钥" || fail "init 没生成私钥"
grep -q "^app_id: APP1" "$APP/shorebird.yaml" && pass "init 写入 app_id" || fail "shorebird.yaml 缺 app_id"
grep -q "^patch_public_key: " "$APP/shorebird.yaml" && pass "init 写入公钥" || fail "shorebird.yaml 缺公钥"
grep -q "shorebird.yaml" "$APP/pubspec.yaml" && pass "init 挂进 pubspec assets" || fail "pubspec 未挂 asset"
[ "$(stat -f '%Lp' "$KEYS/patch_private.pem")" = "600" ] && pass "私钥权限 600" || fail "私钥权限不是 600"

# init 幂等：重跑不应换掉 app_id（否则线上设备全部失联）
"$PY" "$CLI" init --app-dir "$APP" --base-url "http://127.0.0.1:$PORT" --keys "$KEYS" >/dev/null 2>&1
grep -q "^app_id: APP1" "$APP/shorebird.yaml" && pass "init 幂等，app_id 不变" || fail "重跑 init 换掉了 app_id"

# --- 1b) 换钥 -------------------------------------------------------------------
# init 是幂等的，换不了钥 —— 这是刻意的，换钥后果太重（必须重新发版）
export PYTHONPATH="$REPO_ROOT/tools/broute"
FP_BEFORE=$("$PY" -c "
import hashlib,sys;print(hashlib.sha256(open('$KEYS/patch_private.pem','rb').read()).hexdigest())")
"$PY" "$CLI" init --app-dir "$APP" --base-url "http://127.0.0.1:$PORT" --keys "$KEYS" --force >/dev/null 2>&1
FP_AFTER=$("$PY" -c "
import hashlib,sys;print(hashlib.sha256(open('$KEYS/patch_private.pem','rb').read()).hexdigest())")
[ "$FP_BEFORE" = "$FP_AFTER" ] && pass "init --force 不动私钥（换钥要用 rotate-key）" \
  || fail "init 意外换了私钥"
# --force 只覆盖 yaml，绝不能顺带换掉 app_id
grep -q "^app_id: APP1" "$APP/shorebird.yaml" \
  && pass "init --force 保住 app_id（换掉=设备全失联）" || fail "--force 换掉了 app_id"

# rotate-key 才真的换，且必须保住 app_id、同步 yaml 公钥、归档旧钥
PK_BEFORE=$(grep "^patch_public_key:" "$APP/shorebird.yaml")
"$PY" "$CLI" rotate-key --app-dir "$APP" --keys "$KEYS" >/dev/null 2>&1
FP_ROT=$("$PY" -c "
import hashlib;print(hashlib.sha256(open('$KEYS/patch_private.pem','rb').read()).hexdigest())")
PK_AFTER=$(grep "^patch_public_key:" "$APP/shorebird.yaml")
[ "$FP_AFTER" != "$FP_ROT" ] && pass "rotate-key 换了私钥" || fail "rotate-key 没换私钥"
[ "$PK_BEFORE" != "$PK_AFTER" ] && pass "rotate-key 同步更新 yaml 公钥" || fail "yaml 公钥未更新"
grep -q "^app_id: APP1" "$APP/shorebird.yaml" && pass "rotate-key 保住 app_id" || fail "换钥改了 app_id"
[ -f "$KEYS/retired"/*/patch_private.pem ] 2>/dev/null \
  && pass "旧钥已归档（老版本仍需它签补丁）" || fail "旧钥被丢弃了"

# 换钥后旧签名必须验不过 —— 这正是换钥的意义
"$PY" - "$KEYS" <<'PY'
import base64, pathlib, sys
sys.path.insert(0, __import__('os').environ['PYTHONPATH'])
import cli
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.exceptions import InvalidSignature
keys = pathlib.Path(sys.argv[1])
old = sorted((keys / "retired").iterdir())[-1] / "patch_private.pem"
sig = cli.sign_hash("deadbeef", old)                      # 用旧钥签
new_pub = base64.b64decode((keys / "patch_public_key.b64").read_text().strip())
k = serialization.load_der_public_key(new_pub)
try:
    k.verify(base64.b64decode(sig), b"deadbeef", padding.PKCS1v15(), hashes.SHA256())
    sys.exit(1)   # 新公钥竟然验过了旧签名
except InvalidSignature:
    sys.exit(0)
PY
[ $? -eq 0 ] && pass "旧钥签名在新公钥下验不过" || fail "换钥后旧签名仍有效"

# 恢复给后续用例：app_id 必须仍是 APP1
grep -q "^app_id: APP1" "$APP/shorebird.yaml" || fail "换钥流程污染了 app_id"

# --- 2) release ----------------------------------------------------------------
rel_run(){ "$PY" "$CLI" release --app-dir "$APP" --repo "$REPO" \
           --analyze-snapshot "$BIN/analyze_snapshot" --gen-snapshot "$BIN/gen_snapshot" "$@"; }
rel_run >/dev/null 2>&1
REL="$REPO/releases/1.2.3+7"
[ -f "$REL/release.json" ] && pass "release 从 Info.plist 推出 1.2.3+7" || fail "release_version 推断错误"
[ -f "$REL/App.baseline" ] && pass "release 归档 App 二进制" || fail "缺 App.baseline"
[ -f "$REL/app.dill" ]     && pass "release 归档 app.dill" || fail "缺 app.dill（补丁将无法同源编译）"
[ -f "$REL/base.blob" ]    && pass "release 生成 base.blob" || fail "缺 base.blob"
[ -f "$REL/base.aot" ]     && pass "release 归档已校验的 base.aot" || fail "缺 base.aot"

# 关键：必须选中 v130 那份，而不是 mtime 更新的 v121
KV=$("$PY" -c "import json;print(json.load(open('$REL/release.json'))['app_dill_kernel_version'])")
[ "$KV" = "130" ] && pass "release 跳过 mtime 更新但版本不符的 app.dill" \
  || fail "release 选错了 app.dill（kernel v$KV）"

# 重复 release 必须拒绝：覆盖基线会让已下发补丁全部错位
rel_run >/dev/null 2>&1 && fail "重复 release 未被拒绝" || pass "重复 release 被拒绝"

# 一份能用的都没有时必须当场失败，而不是归档一个错的基线
APP2="$TMP/app2"
command cp -R "$APP" "$APP2"
rm -rf "$APP2/.dart_tool/flutter_build/good" "$APP2/shorebird.yaml"
"$PY" "$CLI" release --app-dir "$APP2" --repo "$TMP/repo2" \
      --analyze-snapshot "$BIN/analyze_snapshot" --gen-snapshot "$BIN/gen_snapshot" \
      >"$TMP/rel2.log" 2>&1 \
  && fail "kernel 全不匹配时未被拒绝" || pass "kernel 全不匹配时当场失败"
[ ! -f "$TMP/repo2/releases/1.2.3+7/release.json" ] \
  && pass "失败时不留下半成品 release" || fail "失败却写了 release.json"

# --- 3) 发布补丁（直接走 publish_vmcode，跳过真实 .vmcode 构建） ----------------
export PYTHONPATH="$REPO_ROOT/tools/broute"
pub(){ # $1=编号 $2=通道
  "$PY" - "$REPO" "$KEYS" "$BIN/patch" "$1" "$2" "$PORT" <<'PY'
import pathlib, sys
import cli
repo, keys, patch_tool, number, channel, port = sys.argv[1:]
vm = pathlib.Path(repo) / f".vm{number}.vmcode"
vm.write_bytes(bytes([int(number)]) * 8192)
cli.publish_vmcode(pathlib.Path(repo), "1.2.3+7", vm, number=int(number),
                   base_url=f"http://127.0.0.1:{port}", channel=channel,
                   private_key=pathlib.Path(keys) / "patch_private.pem",
                   note=f"n{number}", patch_tool=pathlib.Path(patch_tool))
PY
}

pub 1 stable >/dev/null 2>&1
pub 2 beta   >/dev/null 2>&1
pub 3 stable >/dev/null 2>&1

IDX="$REL/index.json"
[ -f "$REL/patches/1.bin" ] && [ -f "$REL/patches/1.json" ] \
  && pass "补丁产出 .bin 与元数据" || fail "补丁产物不全"
grep -q '"hash_signature"' "$IDX" && pass "补丁已签名" || fail "补丁未签名"

# 自增编号
NEXT=$("$PY" -c "import json,sys;i=json.load(open('$IDX'));print(max(p['number'] for p in i['patches'])+1)")
[ "$NEXT" = "4" ] && pass "补丁编号自增到 4" || fail "编号自增错误：$NEXT"

# --- 3b) 发布护栏 ---------------------------------------------------------------
# 覆盖已发布的编号会让已装该补丁的设备与新设备分叉
pub 1 stable >"$TMP/dup.txt" 2>&1 && fail "覆盖已发布的补丁号未被拒绝" \
  || pass "覆盖已发布的补丁号被拒绝"

# --force 重发 release 会重算基线，旧增量必然失效，不能默默留着
rel_run --force >"$TMP/f1.txt" 2>&1 && fail "有补丁时 --force 未被拦" \
  || pass "有补丁时 --force 被拦（旧增量会失效）"
grep -q "discard-patches" "$TMP/f1.txt" && pass "提示了 --discard-patches" || fail "未提示补救方式"

# 显式作废后才允许，且必须真的清干净
rel_run --force --discard-patches >/dev/null 2>&1
"$PY" -c "
import json,sys
i=json.load(open('$IDX')) if __import__('pathlib').Path('$IDX').exists() else {'patches':[]}
sys.exit(0 if not i['patches'] else 1)" \
  && pass "--discard-patches 清空了失效补丁" || fail "旧补丁仍留在 index.json"
[ ! -f "$REL/patches/1.bin" ] && pass "失效增量文件已删除" || fail "失效 .bin 仍在"

# 编号不能回绕：装了旧 #3 的设备看到新 #3 会以为自己已是最新，永远收不到补丁
HW=$("$PY" -c "import json;print(json.load(open('$IDX')).get('high_water',0))")
[ "$HW" = "3" ] && pass "作废后记下高水位 3" || fail "high_water 错误：$HW"
pub 4 stable >/dev/null 2>&1
"$PY" -c "
import sys,pathlib
sys.path.insert(0,'$REPO_ROOT/tools/broute'); import cli, json
i=json.load(open('$IDX'))
sys.exit(0 if cli.next_patch_number(i)==5 else 1)" \
  && pass "作废后新编号从高水位继续（不回绕到 1）" || fail "编号回绕了，设备会收不到补丁"

# 重新铺一遍供后续用例
rm -rf "$REL/patches" "$IDX"; mkdir -p "$REL/patches"
pub 1 stable >/dev/null 2>&1
pub 2 beta   >/dev/null 2>&1
pub 3 stable >/dev/null 2>&1

# --- 3c) cmd_patch 的护栏（用桩件替掉真实构建） ---------------------------------
# 桩件：产出一个假的 out.vmcode，link% 由 FAKE_LINK 指定
cat > "$BIN/build_stub.sh" <<'SH'
#!/usr/bin/env bash
mkdir -p "$3"; head -c 4096 /dev/urandom > "$3/out.vmcode"
# 格式必须与 build_app_patch.sh 一致：数值带尾随 % 号
echo "link%:        ${FAKE_LINK:-100.00}%"
SH
chmod +x "$BIN/build_stub.sh"
export FHP_BUILD_SCRIPT="$BIN/build_stub.sh"

patch_run(){ "$PY" "$CLI" patch --app-dir "$APP" --repo "$REPO" \
             --private-key "$KEYS/patch_private.pem" --patch-tool "$BIN/patch" \
             --base-url "http://127.0.0.1:$PORT" "$@"; }

# link% 塌方 = 补丁与基线不同源，这是已知失败信号，必须拦
FAKE_LINK=2.62 patch_run >"$TMP/lp.txt" 2>&1 && fail "link% 2.62% 仍被发布" \
  || pass "link% 低于门限被拒绝"
grep -q "min-link-pct" "$TMP/lp.txt" && pass "提示了 --min-link-pct" || fail "未提示放宽方式"

# 显式放低门限则允许（留给确实预期低 link% 的场景）
FAKE_LINK=2.62 patch_run --min-link-pct 1 >/dev/null 2>&1 \
  && pass "显式放低门限后可发布" || fail "放低门限仍失败"

# 解析不到 link% 时必须拒绝，而不是当作通过
cat > "$BIN/build_nolink.sh" <<'SH'
#!/usr/bin/env bash
mkdir -p "$3"; head -c 4096 /dev/urandom > "$3/out.vmcode"; echo "done"
SH
chmod +x "$BIN/build_nolink.sh"
FHP_BUILD_SCRIPT="$BIN/build_nolink.sh" patch_run >/dev/null 2>&1 \
  && fail "解析不到 link% 却放行" || pass "解析不到 link% 时拒绝发布"

# app_id 不匹配：补丁会被发给错误的应用
cp "$APP/shorebird.yaml" "$TMP/yaml.bak"
"$PY" -c "
import pathlib
p=pathlib.Path('$APP/shorebird.yaml')
p.write_text(p.read_text().replace('app_id: APP1','app_id: SOMEONE-ELSE'))"
patch_run >"$TMP/aid.txt" 2>&1 && fail "app_id 不匹配仍发布" || pass "app_id 不匹配被拒绝"
patch_run --force >/dev/null 2>&1 && pass "--force 可绕过 app_id 检查" || fail "--force 未生效"
cp "$TMP/yaml.bak" "$APP/shorebird.yaml"

unset FHP_BUILD_SCRIPT
# 上面几发把编号推高了，重置成后续用例期望的 1/2/3
rm -rf "$REL/patches" "$IDX"
mkdir -p "$REL/patches"
pub 1 stable >/dev/null 2>&1
pub 2 beta   >/dev/null 2>&1
pub 3 stable >/dev/null 2>&1

# --- 4) 回滚 -------------------------------------------------------------------
"$PY" "$CLI" rollback --repo "$REPO" --release-version 1.2.3+7 --patch 3 >/dev/null 2>&1
grep -q '"rolled_back": \[' "$IDX" && "$PY" -c "
import json;i=json.load(open('$IDX'));exit(0 if 3 in i['rolled_back'] else 1)" \
  && pass "rollback 写入 rolled_back" || fail "rollback 未生效"

"$PY" "$CLI" rollback --repo "$REPO" --patch 99 >/dev/null 2>&1 \
  && fail "回滚不存在的补丁未报错" || pass "回滚不存在的补丁被拒绝"

# --- 5) 服务端语义 --------------------------------------------------------------
"$PY" "$REPO_ROOT/tools/broute/server.py" --repo "$REPO" --port "$PORT" \
  --bind 127.0.0.1 --app-id APP1 >"$TMP/srv.log" 2>&1 &
SRV=$!
sleep 2
req(){ curl -s -m 5 -X POST "http://127.0.0.1:$PORT/api/v1/patches/check" \
       -H 'Content-Type: application/json' -d "$1"; }
BASE='"app_id":"APP1","release_version":"1.2.3+7","platform":"ios","arch":"aarch64","client_id":"c"'

# 已下线的 #3 不能再下发，stable 应回落到 #1
R=$(req "{$BASE,\"channel\":\"stable\"}")
"$PY" -c "
import json,sys;d=json.loads('''$R''')
sys.exit(0 if d.get('patch_available') and d['patch']['number']==1 else 1)" \
  && pass "已下线补丁不下发，回落到 #1" || { fail "回滚后仍下发了 #3"; echo "  $R"; }

# 通道隔离：beta 拿到 #2
R=$(req "{$BASE,\"channel\":\"beta\"}")
"$PY" -c "
import json,sys;d=json.loads('''$R''')
sys.exit(0 if d.get('patch_available') and d['patch']['number']==2 else 1)" \
  && pass "beta 通道拿到 #2" || { fail "通道隔离失效"; echo "  $R"; }

# stable 设备不应收到 beta 补丁
R=$(req "{$BASE,\"channel\":\"stable\",\"current_patch_number\":1}")
echo "$R" | grep -q '"patch_available": false' \
  && pass "stable 已最新则不下发（不串 beta）" || { fail "stable 收到了 beta 补丁"; echo "  $R"; }

# 恢复 #3 后应重新下发
"$PY" "$CLI" rollback --repo "$REPO" --patch 3 --undo >/dev/null 2>&1
R=$(req "{$BASE,\"channel\":\"stable\"}")
"$PY" -c "
import json,sys;d=json.loads('''$R''')
sys.exit(0 if d.get('patch_available') and d['patch']['number']==3 else 1)" \
  && pass "rollback --undo 后重新下发 #3" || { fail "undo 未生效"; echo "  $R"; }

# --- 5b) 协议兼容与健壮性 --------------------------------------------------------
# 旧客户端发的是 patch_number 而非 current_patch_number（network.rs:252）。
# 只认新字段的话，旧客户端每次启动都会重下一遍已装的补丁。
R=$(req "{$BASE,\"channel\":\"stable\",\"patch_number\":3}")
echo "$R" | grep -q '"patch_available": false' \
  && pass "兼容旧客户端的 patch_number 字段" || { fail "旧客户端会被重复下发"; echo "  $R"; }

# 增量文件缺失时不能下发：设备只会 404，还会记一次安装失败
command mv "$REL/patches/3.bin" "$TMP/3.bin.hidden"
R=$(req "{$BASE,\"channel\":\"stable\"}")
"$PY" -c "
import json,sys;d=json.loads('''$R''')
sys.exit(0 if (not d.get('patch_available')) or d['patch']['number']!=3 else 1)" \
  && pass "增量文件缺失的补丁不下发" || { fail "下发了没有文件的补丁"; echo "  $R"; }
command mv "$TMP/3.bin.hidden" "$REL/patches/3.bin"

# index.json 必须原子写，服务端不能读到半截
"$PY" -c "
import sys,pathlib,json
sys.path.insert(0,'$REPO_ROOT/tools/broute'); import cli
p=pathlib.Path('$TMP/atomic.json')
cli.write_json(p, {'a':1})
sys.exit(0 if p.exists() and not list(p.parent.glob('*.tmp')) else 1)" \
  && pass "write_json 原子且不留 .tmp" || fail "原子写有问题"

# --- 6) verify：签名验签 --------------------------------------------------------
"$PY" "$CLI" verify --repo "$REPO" --patch 1 --app-dir "$APP" >"$TMP/v.txt" 2>&1 \
  && pass "verify 通过（签名 + 大小）" || { fail "verify 失败"; cat "$TMP/v.txt"; }

# 换一把不相干的公钥必须验不过 —— 端上的信任根就靠这一步
OTHER="$TMP/otherkeys"
"$PY" - "$OTHER" <<'PY'
import sys, pathlib
sys.path.insert(0, __import__('os').environ['PYTHONPATH'])
import cli
cli.gen_keypair(pathlib.Path(sys.argv[1]))
PY
"$PY" "$CLI" verify --repo "$REPO" --patch 1 \
      --public-key "$(cat "$OTHER/patch_public_key.b64")" >"$TMP/v2.txt" 2>&1 \
  && { fail "错误公钥竟然验签通过"; cat "$TMP/v2.txt"; } || pass "错误公钥验签被拒绝"

# --- 7) list 不报错 -------------------------------------------------------------
"$PY" "$CLI" list --repo "$REPO" >"$TMP/list.txt" 2>&1 \
  && grep -q "release 1.2.3+7" "$TMP/list.txt" \
  && pass "list 输出 release" || { fail "list 失败"; cat "$TMP/list.txt"; }

echo "---"
[ "$FAILS" -eq 0 ] && { echo "ALL PASS"; exit 0; } || { echo "$FAILS FAILURE(S)"; exit 1; }
