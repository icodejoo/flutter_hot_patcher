#!/usr/bin/env bash
# 校验 fhpb 的全生命周期语义：init / release 归档 / 补丁自增 / 通道 / 回滚 /
# 服务端应答。不需要设备，也不需要 Shorebird 工具链 —— 用桩件替掉
# analyze_snapshot 与 patch 这两个外部二进制，只测我们自己的逻辑。
#
# 两种模式（环境变量 FHP_TEST_MODE）：
#   local（默认）  本地补丁仓库 + tools/broute/server.py，行为与以前一致
#   server         fhpb 走控制台 API，对着真起的 waitress+sqlite 服务（flutter_code_push/server）跑
#                  FHP_TEST_SERVER_DIR 指服务端代码目录；FHP_TEST_PY 须装好 cryptography/flask/waitress
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PY="${FHP_TEST_PY:-$REPO_ROOT/tools/.venv/bin/python}"
[ -x "$PY" ] || PY="$(command -v python3)"
CLI="$REPO_ROOT/tools/broute/cli.py"
TMP="$(mktemp -d)"; PORT=8793
# Windows(Git Bash)下让 bash 与原生 Python 看到同一个路径写法
command -v cygpath >/dev/null 2>&1 && TMP="$(cygpath -m "$TMP")"
FAILS=0
fail(){ echo "FAIL: $1"; FAILS=$((FAILS+1)); }
pass(){ echo "PASS: $1"; }
cleanup(){ [ -n "${SRV:-}" ] && kill "$SRV" 2>/dev/null; rm -rf "$TMP"; }
trap cleanup EXIT

MODE="${FHP_TEST_MODE:-local}"
SRVDIR="${FHP_TEST_SERVER_DIR:-$REPO_ROOT/../flutter_code_push/server}"
SPORT=8794
# 设备协议请求打到哪个端口：local 是旧 server.py，server 是新服务
CPORT=$PORT
# 一个版本号在两种模式下的差别：server 模式服务端上 release 全局唯一，后面几处要换版本号
SV=1.2.3+7; REJV=1.2.3+7; BADV=1.2.3+7; SVARGS=""; REJARGS=""; BADARGS=""
if [ "$MODE" = server ]; then
  CPORT=$SPORT; SV=2.0.0+1; REJV=3.0.0+1; BADV=9.9.9+1
  SVARGS="--release-version $SV"; REJARGS="--release-version $REJV"; BADARGS="--release-version $BADV --app-id APP1"
  export FHPB_CONFIG="$TMP/console_cfg.json"
else
  export FHPB_MODE=local   # 防止开发机上的 ~/.fhpb/console.json 把本地模式测成 server 模式
fi

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
MODE="no-dwarf_stack_traces_mode"
for a in "\$@"; do case "\$a" in --elf=*) ELF="\${a#--elf=}";; *.dill) DILL="\$a";; --dwarf-stack-traces) MODE="dwarf_stack_traces_mode";; esac; done
VER=\$("$PY" -c "import sys;print(int.from_bytes(open(sys.argv[1],'rb').read(8)[4:8],'big'))" "\$DILL")
if [ "\$VER" != "130" ]; then
  echo "Can't load Kernel binary: Invalid kernel binary format version (expected 130, found \$VER)." >&2
  exit 253
fi
{ head -c 32768 /dev/zero; printf 'product no-code_comments %s dedup_instructions ' "\$MODE"; } > "\$ELF"
SH
chmod +x "$BIN/analyze_snapshot" "$BIN/patch" "$BIN/gen_snapshot"

# --- server 模式：起新服务，建管理员与 API key，登记 APP1 -----------------------
srvq(){ # 用服务端代码读库：srvq '<python 表达式，可用 st=Store>'
  (cd "$SRVDIR" && "$PY" -c "
import sys,json
from app.store import Store
st=Store(sys.argv[1])
$1" "$TMP/srvdata/console.db"); }
if [ "$MODE" = server ]; then
  mkdir -p "$TMP/srvdata"
  (cd "$SRVDIR" && printf 'pw-fhpb-test\n' | "$PY" -m app create-admin --data-dir "$TMP/srvdata" \
     --email t@x.com --password-stdin) >/dev/null 2>&1
  KEYOUT=$(cd "$SRVDIR" && "$PY" -m app create-key --data-dir "$TMP/srvdata" --email t@x.com --name ci 2>&1)
  export FHPB_API_KEY="$(echo "$KEYOUT" | grep -o 'sb_api_[A-Za-z0-9_-]*' | head -1)"
  export FHPB_SERVER="http://127.0.0.1:$SPORT"
  srvq "st.ensure_app('APP1', 'fhpb-test')"
  (cd "$SRVDIR" && exec "$PY" -m app serve --data-dir "$TMP/srvdata" --port $SPORT \
     --base-url "http://127.0.0.1:$SPORT") >"$TMP/srv.log" 2>&1 &
  SRV=$!
  for _ in $(seq 1 30); do curl -s -m 1 "http://127.0.0.1:$SPORT/healthz" >/dev/null 2>&1 && break; sleep 0.5; done
  curl -s -m 2 "http://127.0.0.1:$SPORT/healthz" | grep -q true \
    && pass "新服务已起（waitress + sqlite）" || { fail "新服务没起来"; cat "$TMP/srv.log"; }
fi

# --- 构造一个假的 release 产物 -------------------------------------------------
"$PY" - "$APP" <<'PY'
import plistlib, pathlib, sys
app = pathlib.Path(sys.argv[1])
p = app/"build/ios/iphoneos/Runner.app/Info.plist"
p.write_bytes(plistlib.dumps({"CFBundleShortVersionString":"1.2.3","CFBundleVersion":"7"}))
PY
# 真实 App 的快照特性串里记着构建模式；fhpb release 据此决定基线是否 split。
{ head -c 4096 /dev/urandom; printf 'product no-code_comments no-dwarf_stack_traces_mode dedup_instructions '; } \
  > "$APP/build/ios/iphoneos/Runner.app/Frameworks/App.framework/App"
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

# --- 0) console login / create-key（server 模式）---------------------------------
if [ "$MODE" = server ]; then
  KEY0="$FHPB_API_KEY"
  # login 只认配置文件：环境变量先拿掉
  CFGF="$TMP/login_cfg.json"
  FHPB_CONFIG="$CFGF" FHPB_API_KEY= FHPB_SERVER= "$PY" "$CLI" console login --server "$FHPB_SERVER" \
     --api-key "$KEY0" >"$TMP/login.txt" 2>&1 \
    && pass "console login 验证并保存 key" || { fail "console login 失败"; cat "$TMP/login.txt"; }
  [ "$(stat -c '%a' "$CFGF" 2>/dev/null || stat -f '%Lp' "$CFGF")" = "600" ] \
    && pass "console 配置文件权限 600" || fail "console 配置文件权限不是 600"
  grep -q "$KEY0" "$CFGF" && grep -q "127.0.0.1:$SPORT" "$CFGF" \
    && pass "配置文件记下 server 与 key" || fail "配置文件内容不对"
  FHPB_CONFIG="$TMP/bad_cfg.json" FHPB_API_KEY= FHPB_SERVER= "$PY" "$CLI" console login \
     --server "$FHPB_SERVER" --api-key "sb_api_wrong" >/dev/null 2>&1 \
    && fail "错误的 key 竟然登录成功" || pass "console login 拒绝错误的 key"
  [ ! -e "$TMP/bad_cfg.json" ] && pass "登录失败不落盘" || fail "登录失败却写了配置"
  FHPB_API_KEY= FHPB_SERVER= FHPB_CONFIG="$CFGF" "$PY" "$CLI" console create-key --name second --no-save \
     >"$TMP/ck.txt" 2>&1 && grep -q "sb_api_" "$TMP/ck.txt" \
    && pass "console create-key 经 API 签发新 key" || { fail "create-key 失败"; cat "$TMP/ck.txt"; }
fi

# --- 1) init -------------------------------------------------------------------
OUT=$("$PY" "$CLI" init --app-dir "$APP" --base-url "http://127.0.0.1:$PORT" \
      --keys "$KEYS" --app-id APP1 2>&1)
[ -f "$KEYS/patch_private.pem" ] && pass "init 生成私钥" || fail "init 没生成私钥"
grep -q "^app_id: APP1" "$APP/shorebird.yaml" && pass "init 写入 app_id" || fail "shorebird.yaml 缺 app_id"
grep -q "^patch_public_key: " "$APP/shorebird.yaml" && pass "init 写入公钥" || fail "shorebird.yaml 缺公钥"
grep -q "shorebird.yaml" "$APP/pubspec.yaml" && pass "init 挂进 pubspec assets" || fail "pubspec 未挂 asset"
[ "$(stat -c '%a' "$KEYS/patch_private.pem" 2>/dev/null || stat -f '%Lp' "$KEYS/patch_private.pem")" = "600" ] && pass "私钥权限 600" || fail "私钥权限不是 600"

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
if [ "$MODE" = server ]; then
  # 本地归档不在（换了台机器）时，服务端也要拦住重复 release
  command mv "$REL" "$REL.bak"
  rel_run >"$TMP/dupr.txt" 2>&1 && fail "服务端已有的 release 被重复上传" || pass "服务端已有的 release 被拒绝重复上传"
  grep -q "服务端已有 release" "$TMP/dupr.txt" && pass "拒绝原因是服务端已有" || { fail "拒绝了但原因不对"; cat "$TMP/dupr.txt"; }
  command mv "$REL.bak" "$REL"
  # 五类产物都在服务端（App.baseline / app.dill / base.aot / base.blob / release.json）
  NART=$(srvq "print(len(st.list_release_artifacts(st.ensure_release('APP1','1.2.3+7'))))")
  [ "$NART" = "5" ] && pass "release 产物（基线 + 4 个伴随文件）已上传到服务端" || fail "服务端 release 产物数不对：$NART"
fi

# 一份能用的都没有时必须当场失败，而不是归档一个错的基线
APP2="$TMP/app2"
command cp -R "$APP" "$APP2"
rm -rf "$APP2/.dart_tool/flutter_build/good" "$APP2/shorebird.yaml"
"$PY" "$CLI" release --app-dir "$APP2" --repo "$TMP/repo2" $BADARGS \
      --analyze-snapshot "$BIN/analyze_snapshot" --gen-snapshot "$BIN/gen_snapshot" \
      >"$TMP/rel2.log" 2>&1 \
  && fail "kernel 全不匹配时未被拒绝" || pass "kernel 全不匹配时当场失败"
[ ! -f "$TMP/repo2/releases/$BADV/release.json" ] \
  && pass "失败时不留下半成品 release" || fail "失败却写了 release.json"
if [ "$MODE" = server ]; then
  RELS=$(cd "$SRVDIR" && "$PY" -c "
import sys;from app.store import Store
st=Store(sys.argv[1]);print(sorted(r['version'] for r in st.list_releases('APP1')))" "$TMP/srvdata/console.db")
  echo "$RELS" | grep -q "9.9.9" && fail "失败的 release 在服务端留下了半成品" || pass "失败时服务端也不留半成品 release"
fi

# --- 3) 发布补丁（直接走 publish_vmcode，跳过真实 .vmcode 构建） ----------------
export PYTHONPATH="$REPO_ROOT/tools/broute"
publ(){ # 本地模式：$1=编号 $2=通道
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
pubr(){ # server 模式：$1=强行指定的编号（"" 表示不指定，由服务端分配） $2=通道；分配到的号写进 $TMP/last_number
  "$PY" - "$REPO" "$KEYS" "$BIN/patch" "$1" "$2" "$TMP" <<'PY'
import pathlib, sys
import cli
repo, keys, patch_tool, number, channel, tmp = sys.argv[1:]
repo = pathlib.Path(repo)
con = cli.console_for()
rel = con.find_release("APP1", "1.2.3+7")
vm = repo / ".pub.vmcode"
vm.write_bytes(bytes([len(list(repo.glob('.pubcount*'))) + 1]) * 8192)
(repo / f".pubcount{len(list(repo.glob('.pubcount*')))}").write_text("x")
out = repo / ".pubout"; out.mkdir(exist_ok=True)
e = cli.publish_vmcode_remote(con, "APP1", rel, vm, repo / "releases/1.2.3+7/base.blob", channel=channel,
                              private_key=pathlib.Path(keys) / "patch_private.pem", pub_b64=None,
                              note="n", patch_tool=pathlib.Path(patch_tool), metadata={"t": 1}, out_dir=out,
                              number=int(number) if number else None)
pathlib.Path(tmp, "last_number").write_text(str(e["number"]))
PY
}
pub(){ # $1=编号（server 模式忽略，号由服务端分配） $2=通道
  if [ "$MODE" = server ]; then pubr "" "$2"; else publ "$1" "$2"; fi
}
pubn(){ # 强行指定编号发布：local 是覆盖检查，server 是“服务端才有权分配编号”
  if [ "$MODE" = server ]; then pubr "$1" "$2"; else publ "$1" "$2"; fi
}
lastn(){ cat "$TMP/last_number" 2>/dev/null; }
# 服务端上某 release 的补丁快照：每行 编号:通道:是否回滚
srvpatches(){ (cd "$SRVDIR" && "$PY" -c "
import sys;from app.store import Store
st=Store(sys.argv[1])
rid=st.ensure_release('APP1','1.2.3+7')
for p in st.list_release_patches(rid): print('%d:%s:%d'%(p['number'],p['channel'],p['is_rolled_back']))" "$TMP/srvdata/console.db"); }

pub 1 stable >/dev/null 2>&1; N1=$(lastn)
pub 2 beta   >/dev/null 2>&1; N2=$(lastn)
pub 3 stable >/dev/null 2>&1; N3=$(lastn)
if [ "$MODE" != server ]; then N1=1; N2=2; N3=3; fi
[ "$N1,$N2,$N3" = "1,2,3" ] && pass "三次发布的补丁号依次为 1,2,3" || fail "补丁号不是 1,2,3：$N1,$N2,$N3"

IDX="$REL/index.json"
if [ "$MODE" = server ]; then
  # 每个补丁在服务端都有 ready 的产物，且设备能经 /d/<sha256> 取到；签名随 check 应答下发
  R=$(curl -s -m 5 -X POST "http://127.0.0.1:$CPORT/api/v1/patches/check" -H 'Content-Type: application/json' \
      -d '{"app_id":"APP1","release_version":"1.2.3+7","platform":"ios","arch":"aarch64","client_id":"c","channel":"stable"}')
  echo "$R" | grep -q '"hash_signature"' && pass "补丁已签名（设备 check 应答带 hash_signature）" || fail "补丁未签名：$R"
  DURL=$(echo "$R" | "$PY" -c "import json,sys;print(json.load(sys.stdin)['patch']['download_url'])")
  [ "$(curl -s -m 5 -o /dev/null -w '%{http_code}' "$DURL")" = "200" ] \
    && pass "补丁增量可经 /d/<sha256> 下载" || fail "补丁下载失败：$DURL"
  [ "$(srvpatches | wc -l | tr -d ' ')" = "3" ] && pass "服务端有 3 个补丁行" || fail "服务端补丁行数不对"
else
  [ -f "$REL/patches/1.bin" ] && [ -f "$REL/patches/1.json" ] \
    && pass "补丁产出 .bin 与元数据" || fail "补丁产物不全"
  grep -q '"hash_signature"' "$IDX" && pass "补丁已签名" || fail "补丁未签名"
fi

# 自增编号
if [ "$MODE" = server ]; then
  NEXT=$(( $(srvpatches | cut -d: -f1 | sort -n | tail -1) + 1 ))
else
  NEXT=$("$PY" -c "import json,sys;i=json.load(open('$IDX'));print(max(p['number'] for p in i['patches'])+1)")
fi
[ "$NEXT" = "4" ] && pass "补丁编号自增到 4" || fail "编号自增错误：$NEXT"

# --- 3b) 发布护栏 ---------------------------------------------------------------
# 覆盖已发布的编号会让已装该补丁的设备与新设备分叉
pubn 1 stable >"$TMP/dup.txt" 2>&1 && fail "覆盖已发布的补丁号未被拒绝" \
  || pass "覆盖已发布的补丁号被拒绝"
[ "$MODE" = server ] && { [ "$(srvpatches | wc -l | tr -d ' ')" = "3" ] \
  && pass "被拒绝的指定编号发布没在服务端留下补丁行" || fail "拒绝后服务端多了补丁行"; }

# --force 重发 release 会重算基线，旧增量必然失效，不能默默留着
rel_run --force >"$TMP/f1.txt" 2>&1 && fail "有补丁时 --force 未被拦" \
  || pass "有补丁时 --force 被拦（旧增量会失效）"
grep -q "discard-patches" "$TMP/f1.txt" && pass "提示了 --discard-patches" || fail "未提示补救方式"

# 显式作废后才允许，且必须真的清干净
[ "$MODE" = server ] && IDS0=$(srvq "print(sorted(a['hash'] for a in st.list_release_artifacts(st.ensure_release('APP1','1.2.3+7'))))")
rel_run --force --discard-patches >/dev/null 2>&1
if [ "$MODE" = server ]; then
  [ -z "$(srvpatches | grep ':0$')" ] && pass "--discard-patches 回滚了全部旧补丁（设备不再收到）" \
    || fail "仍有未回滚的旧补丁"
  [ "$(srvpatches | wc -l | tr -d ' ')" = "3" ] && pass "旧补丁行保留（只回滚不删除，编号不会被复用）" \
    || fail "补丁行数变了"
  NART=$(srvq "print(len(st.list_release_artifacts(st.ensure_release('APP1','1.2.3+7'))))")
  IDS1=$(srvq "print(sorted(a['hash'] for a in st.list_release_artifacts(st.ensure_release('APP1','1.2.3+7'))))")
  [ "$NART" = "5" ] && [ "$IDS0" != "$IDS1" ] && pass "基线产物已删除并重传（5 个；release.json 含 created_at，hash 必变。不比 id：sqlite 全删后 id 会从 1 重新分配）"     || fail "重传后产物不对：$NART $IDS0 → $IDS1"
else
  "$PY" -c "
import json,sys
i=json.load(open('$IDX')) if __import__('pathlib').Path('$IDX').exists() else {'patches':[]}
sys.exit(0 if not i['patches'] else 1)" \
    && pass "--discard-patches 清空了失效补丁" || fail "旧补丁仍留在 index.json"
  [ ! -f "$REL/patches/1.bin" ] && pass "失效增量文件已删除" || fail "失效 .bin 仍在"
fi

# 编号不能回绕：装了旧 #3 的设备看到新 #3 会以为自己已是最新，永远收不到补丁
if [ "$MODE" = server ]; then
  HW=$(srvpatches | cut -d: -f1 | sort -n | tail -1)
else
  HW=$("$PY" -c "import json;print(json.load(open('$IDX')).get('high_water',0))")
fi
[ "$HW" = "3" ] && pass "作废后记下高水位 3" || fail "high_water 错误：$HW"
pub 4 stable >/dev/null 2>&1
if [ "$MODE" = server ]; then
  [ "$(lastn)" = "4" ] && pass "作废后新编号从高水位继续（不回绕到 1）" || fail "编号回绕了：$(lastn)"
else
  "$PY" -c "
import sys,pathlib
sys.path.insert(0,'$REPO_ROOT/tools/broute'); import cli, json
i=json.load(open('$IDX'))
sys.exit(0 if cli.next_patch_number(i)==5 else 1)" \
    && pass "作废后新编号从高水位继续（不回绕到 1）" || fail "编号回绕了，设备会收不到补丁"
fi

# 重新铺一遍供后续用例（local：清掉仓库；server：补丁行永不删，把活的全部回滚后再发三个新的）
resetp(){
  if [ "$MODE" = server ]; then
    "$PY" - <<'PY'
import cli
con = cli.console_for(); rel = con.find_release("APP1", "1.2.3+7")
for p in con.patches("APP1", rel["id"]):
    if not p["is_rolled_back"]:
        con.rollback("APP1", rel["id"], p["id"])
PY
  else
    rm -rf "$REL/patches" "$IDX"; mkdir -p "$REL/patches"
  fi
}
resetp
pub 1 stable >/dev/null 2>&1; N1=$(lastn)
pub 2 beta   >/dev/null 2>&1; N2=$(lastn)
pub 3 stable >/dev/null 2>&1; N3=$(lastn)
if [ "$MODE" != server ]; then N1=1; N2=2; N3=3; fi

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
FORCEARGS="--force"; [ "$MODE" = server ] && FORCEARGS="--force --app-id APP1"

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
if [ "$MODE" = server ]; then
  # 服务端 release 归属于 app_id，工程 yaml 与 --app-id 不一致时才是“发错应用”
  patch_run --app-id APP1 >"$TMP/aid2.txt" 2>&1 && fail "--app-id 与工程不一致仍发布" \
    || { grep -q "app_id 不匹配" "$TMP/aid2.txt" && pass "--app-id 与工程 yaml 不一致被拒绝" || { fail "拒绝了但原因不对"; cat "$TMP/aid2.txt"; }; }
fi
patch_run $FORCEARGS >/dev/null 2>&1 && pass "--force 可绕过 app_id 检查" || fail "--force 未生效"
cp "$TMP/yaml.bak" "$APP/shorebird.yaml"

if [ "$MODE" = server ]; then
  # 自验：yaml（端上信任根）里的公钥与签名私钥不配对时，必须在碰服务端之前拒绝
  BEFORE=$(srvpatches | wc -l | tr -d ' ')
  cp "$APP/shorebird.yaml" "$TMP/yaml.bak2"
  "$PY" -c "
import pathlib,sys
sys.path.insert(0,'$REPO_ROOT/tools/broute'); import cli
other=cli.gen_keypair(pathlib.Path('$TMP/selfv_keys'))
p=pathlib.Path('$APP/shorebird.yaml')
t=[l if not l.startswith('patch_public_key:') else 'patch_public_key: '+other for l in p.read_text().splitlines()]
p.write_text(chr(10).join(t)+chr(10))"
  patch_run >"$TMP/selfv.txt" 2>&1 && fail "公钥与私钥不配对仍上传了" \
    || { grep -q "自验未通过" "$TMP/selfv.txt" && pass "上传前自验：公钥与私钥不配对被拒绝" || { fail "拒绝了但不是自验"; cat "$TMP/selfv.txt"; }; }
  [ "$(srvpatches | wc -l | tr -d ' ')" = "$BEFORE" ] && pass "自验失败时服务端没有新补丁行" || fail "自验失败却在服务端建了补丁"
  cp "$TMP/yaml.bak2" "$APP/shorebird.yaml"
  # release 产物按 sha256 缓存在本地
  NC=$(ls "$REPO/.cache" 2>/dev/null | grep -c '^[0-9a-f]\{64\}$')
  [ "$NC" -ge 4 ] && pass "release 产物按 sha256 缓存（$NC 个）" || fail "本地缓存缺失：$NC"
  # 缓存被篡改（或下载半截）后必须重新下载，不能照用
  CF=$(ls "$REPO/.cache" | grep '^[0-9a-f]\{64\}$' | head -1)
  printf 'tampered' >> "$REPO/.cache/$CF"
  patch_run --min-link-pct 1 >/dev/null 2>&1
  [ "$(sha256sum "$REPO/.cache/$CF" | cut -d' ' -f1)" = "$CF" ]     && pass "缓存内容与 sha256 不符时重新下载" || fail "用了被篡改的缓存"
  # --patch-number 在 server 模式不被接受（编号只有服务端能分配）
  patch_run --patch-number 77 >"$TMP/pn.txt" 2>&1 && fail "server 模式接受了 --patch-number" \
    || { grep -q "服务端分配" "$TMP/pn.txt" && pass "--patch-number 被拒绝（号由服务端分配）" || fail "拒绝原因不对"; }
fi

unset FHP_BUILD_SCRIPT
# 上面几发把编号推高了，重置成后续用例期望的状态
resetp
pub 1 stable >/dev/null 2>&1; N1=$(lastn)
pub 2 beta   >/dev/null 2>&1; N2=$(lastn)
pub 3 stable >/dev/null 2>&1; N3=$(lastn)
if [ "$MODE" != server ]; then N1=1; N2=2; N3=3; fi

# --- 4) 回滚 -------------------------------------------------------------------
"$PY" "$CLI" rollback --repo "$REPO" --release-version 1.2.3+7 --patch $N3 >/dev/null 2>&1
if [ "$MODE" = server ]; then
  srvpatches | grep -q "^$N3:stable:1$" && pass "rollback 写入服务端（补丁 #$N3 已回滚）" || fail "rollback 未生效"
  "$PY" "$CLI" rollback --repo "$REPO" --patch $N3 >"$TMP/rb2.txt" 2>&1 \
    && grep -q "已是下线状态" "$TMP/rb2.txt" && pass "重复回滚是幂等的（304 视为已下线）" || fail "重复回滚处理不对"
else
  grep -q '"rolled_back": \[' "$IDX" && "$PY" -c "
import json;i=json.load(open('$IDX'));exit(0 if 3 in i['rolled_back'] else 1)" \
    && pass "rollback 写入 rolled_back" || fail "rollback 未生效"
fi

"$PY" "$CLI" rollback --repo "$REPO" --patch 99 >/dev/null 2>&1 \
  && fail "回滚不存在的补丁未报错" || pass "回滚不存在的补丁被拒绝"

# --- 5) 服务端语义 --------------------------------------------------------------
if [ "$MODE" != server ]; then
  "$PY" "$REPO_ROOT/tools/broute/server.py" --repo "$REPO" --port "$PORT" \
    --bind 127.0.0.1 --app-id APP1 >"$TMP/srv.log" 2>&1 &
  SRV=$!
  sleep 2
fi
req(){ curl -s -m 5 -X POST "http://127.0.0.1:$CPORT/api/v1/patches/check" \
       -H 'Content-Type: application/json' -d "$1"; }
BASE='"app_id":"APP1","release_version":"1.2.3+7","platform":"ios","arch":"aarch64","client_id":"c"'

# 已下线的 #3 不能再下发，stable 应回落到 #1
R=$(req "{$BASE,\"channel\":\"stable\"}")
"$PY" -c "
import json,sys;d=json.loads('''$R''')
sys.exit(0 if d.get('patch_available') and d['patch']['number']==$N1 else 1)" \
  && pass "已下线补丁不下发，回落到 #1" || { fail "回滚后仍下发了 #3"; echo "  $R"; }

# 通道隔离：beta 拿到 #2
R=$(req "{$BASE,\"channel\":\"beta\"}")
"$PY" -c "
import json,sys;d=json.loads('''$R''')
sys.exit(0 if d.get('patch_available') and d['patch']['number']==$N2 else 1)" \
  && pass "beta 通道拿到 #2" || { fail "通道隔离失效"; echo "  $R"; }

# stable 设备不应收到 beta 补丁
R=$(req "{$BASE,\"channel\":\"stable\",\"current_patch_number\":$N1}")
echo "$R" | grep -q '"patch_available": false' \
  && pass "stable 已最新则不下发（不串 beta）" || { fail "stable 收到了 beta 补丁"; echo "  $R"; }

# 恢复 #3 后应重新下发
"$PY" "$CLI" rollback --repo "$REPO" --patch $N3 --undo >/dev/null 2>&1
R=$(req "{$BASE,\"channel\":\"stable\"}")
"$PY" -c "
import json,sys;d=json.loads('''$R''')
sys.exit(0 if d.get('patch_available') and d['patch']['number']==$N3 else 1)" \
  && pass "rollback --undo 后重新下发 #3" || { fail "undo 未生效"; echo "  $R"; }

# --- 5b) 协议兼容与健壮性 --------------------------------------------------------
# 旧客户端发的是 patch_number 而非 current_patch_number（network.rs:252）。
# 只认新字段的话，旧客户端每次启动都会重下一遍已装的补丁。
R=$(req "{$BASE,\"channel\":\"stable\",\"patch_number\":$N3}")
echo "$R" | grep -q '"patch_available": false' \
  && pass "兼容旧客户端的 patch_number 字段" || { fail "旧客户端会被重复下发"; echo "  $R"; }

# 增量文件缺失时不能下发：设备只会 404，还会记一次安装失败
if [ "$MODE" = server ]; then
  R0=$(req "{$BASE,\"channel\":\"stable\"}")
  SHA=$(echo "$R0" | "$PY" -c "import json,sys;print(json.load(sys.stdin)['patch']['download_url'].rsplit('/',1)[1])")
  BLOBF=$(find "$TMP/srvdata/blobs" -type f -name "$SHA" | head -1)
  [ -n "$BLOBF" ] || fail "找不到补丁 blob 文件"
  command mv "$BLOBF" "$TMP/blob.hidden"
else
  command mv "$REL/patches/3.bin" "$TMP/3.bin.hidden"
fi
R=$(req "{$BASE,\"channel\":\"stable\"}")
"$PY" -c "
import json,sys;d=json.loads('''$R''')
sys.exit(0 if (not d.get('patch_available')) or d['patch']['number']!=$N3 else 1)" \
  && pass "增量文件缺失的补丁不下发" || { fail "下发了没有文件的补丁"; echo "  $R"; }
if [ "$MODE" = server ]; then command mv "$TMP/blob.hidden" "$BLOBF"; else command mv "$TMP/3.bin.hidden" "$REL/patches/3.bin"; fi

# index.json 必须原子写，服务端不能读到半截
"$PY" -c "
import sys,pathlib,json
sys.path.insert(0,'$REPO_ROOT/tools/broute'); import cli
p=pathlib.Path('$TMP/atomic.json')
cli.write_json(p, {'a':1})
sys.exit(0 if p.exists() and not list(p.parent.glob('*.tmp')) else 1)" \
  && pass "write_json 原子且不留 .tmp" || fail "原子写有问题"

# --- 6) verify：签名验签 --------------------------------------------------------
VP=1; [ "$MODE" = server ] && VP=$N3   # server 模式只能复核设备此刻会收到的补丁（通道当前最新）
"$PY" "$CLI" verify --repo "$REPO" --patch $VP --app-dir "$APP" >"$TMP/v.txt" 2>&1 \
  && pass "verify 通过（签名 + 大小）" || { fail "verify 失败"; cat "$TMP/v.txt"; }

# 换一把不相干的公钥必须验不过 —— 端上的信任根就靠这一步
OTHER="$TMP/otherkeys"
"$PY" - "$OTHER" <<'PY'
import sys, pathlib
sys.path.insert(0, __import__('os').environ['PYTHONPATH'])
import cli
cli.gen_keypair(pathlib.Path(sys.argv[1]))
PY
"$PY" "$CLI" verify --repo "$REPO" --patch $VP \
      --public-key "$(cat "$OTHER/patch_public_key.b64")" >"$TMP/v2.txt" 2>&1 \
  && { fail "错误公钥竟然验签通过"; cat "$TMP/v2.txt"; } || pass "错误公钥验签被拒绝"
grep -q "公钥与签名私钥不配对" "$TMP/v2.txt" && pass "拒绝原因是验签不过" || fail "拒绝了但不是因为验签"

# --- 7) list 不报错 -------------------------------------------------------------
"$PY" "$CLI" list --repo "$REPO" >"$TMP/list.txt" 2>&1 \
  && grep -q "release 1.2.3+7" "$TMP/list.txt" \
  && pass "list 输出 release" || { fail "list 失败"; cat "$TMP/list.txt"; }

# --- 8) --split-debug-info 基线：模式由 App 的特性串决定，补丁必须同一模式 -------
# 一个 split 构建的 App（特性串 dwarf_stack_traces_mode）。
SAPP="$TMP/sapp"; SREPO="$TMP/srepo"
mkdir -p "$SAPP/build/ios/iphoneos/Runner.app/Frameworks/App.framework" "$SAPP/.dart_tool/flutter_build/good"
cp "$APP/build/ios/iphoneos/Runner.app/Info.plist" "$SAPP/build/ios/iphoneos/Runner.app/Info.plist"
cp "$APP/.dart_tool/flutter_build/good/app.dill" "$SAPP/.dart_tool/flutter_build/good/app.dill"
cp "$APP/shorebird.yaml" "$SAPP/shorebird.yaml"
{ head -c 4096 /dev/urandom; printf 'product no-code_comments dwarf_stack_traces_mode dedup_instructions '; } \
  > "$SAPP/build/ios/iphoneos/Runner.app/Frameworks/App.framework/App"
srel(){ "$PY" "$CLI" release --app-dir "$SAPP" --repo "$SREPO" $SVARGS \
          --analyze-snapshot "$BIN/analyze_snapshot" --gen-snapshot "$BIN/gen_snapshot" "$@"; }
srel >"$TMP/sr.txt" 2>&1 || { fail "split 基线 release 失败"; cat "$TMP/sr.txt"; }
"$PY" -c "import json,sys;sys.exit(0 if json.load(open(sys.argv[1]))['split_debug_info'] is True else 1)" \
  "$SREPO/releases/$SV/release.json" && pass "split 基线被识别并记入 release.json" \
  || fail "release.json 没记下 split_debug_info=true"
# 重新生成的 base.aot 也必须是 dwarf 模式（gen_snapshot 桩件只有收到 --dwarf-stack-traces 才这样写）
grep -q " dwarf_stack_traces_mode " "$SREPO/releases/$SV/base.aot" \
  && pass "split 基线的 base.aot 带 --dwarf-stack-traces 重新生成" \
  || fail "split 基线的 base.aot 没带 dwarf 参数（链接会连错地址）"
grep -q "split_debug_info.: false" "$REPO/releases/1.2.3+7/release.json" \
  && pass "普通基线记为 split_debug_info=false" || fail "普通基线没记 split_debug_info=false"
# 普通 App 却要求 --split-debug-info：拒绝（不能只信命令行）
"$PY" "$CLI" release --app-dir "$APP" --repo "$TMP/srepo2" --split-debug-info $REJARGS \
   --analyze-snapshot "$BIN/analyze_snapshot" --gen-snapshot "$BIN/gen_snapshot" >"$TMP/sr2.txt" 2>&1 \
  && fail "普通 App 加 --split-debug-info 竟然归档了" \
  || { grep -q "no-dwarf_stack_traces_mode" "$TMP/sr2.txt" && pass "普通 App 加 --split-debug-info 被拒绝" \
       || { fail "拒绝了但没说明原因"; cat "$TMP/sr2.txt"; }; }
# 补丁构建：fhpb 必须把模式传给构建脚本，且模式不符的补丁不许发布
cat > "$BIN/build_mode.sh" <<'SH'
#!/usr/bin/env bash
mkdir -p "$3"; head -c 4096 /dev/urandom > "$3/out.vmcode"
M=no-dwarf_stack_traces_mode; [ "${FHP_SPLIT_DEBUG_INFO:-0}" = "1" ] && M=dwarf_stack_traces_mode
[ -n "${FORCE_MODE:-}" ] && M="$FORCE_MODE"
printf 'product %s dedup_instructions ' "$M" > "$3/patch.aot"
echo "seen FHP_SPLIT_DEBUG_INFO=${FHP_SPLIT_DEBUG_INFO:-unset}" > "$3/env.txt"
echo "link%: 100.00%"
SH
chmod +x "$BIN/build_mode.sh"
spatch(){ FHP_BUILD_SCRIPT="$BIN/build_mode.sh" "$PY" "$CLI" patch --app-dir "$SAPP" --repo "$SREPO" $SVARGS \
            --private-key "$KEYS/patch_private.pem" --patch-tool "$BIN/patch" \
            --base-url "http://127.0.0.1:$PORT" --out-dir "$TMP/sout" "$@"; }
spatch >"$TMP/sp.txt" 2>&1 && grep -q "FHP_SPLIT_DEBUG_INFO=1" "$TMP/sout/env.txt" \
  && pass "split 基线的补丁构建收到 FHP_SPLIT_DEBUG_INFO=1" \
  || { fail "split 基线的补丁构建没收到模式"; cat "$TMP/sp.txt"; }
FORCE_MODE=no-dwarf_stack_traces_mode spatch >"$TMP/sp2.txt" 2>&1 \
  && fail "模式不符的补丁竟然发布了" \
  || { grep -q "模式" "$TMP/sp2.txt" && pass "模式与基线不符的补丁被拒绝" \
       || { fail "拒绝了但不是因为模式"; cat "$TMP/sp2.txt"; }; }

echo "---"
[ "$FAILS" -eq 0 ] && { echo "ALL PASS"; exit 0; } || { echo "$FAILS FAILURE(S)"; exit 1; }
