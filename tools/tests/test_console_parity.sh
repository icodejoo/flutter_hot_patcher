#!/usr/bin/env bash
# 旧补丁仓库 -> 服务端导入器 -> 新旧服务对拍。
# 旧仓库用 fhpb 本地模式亲手造（桩件替掉 analyze_snapshot / patch / gen_snapshot），覆盖：
#   多渠道、已回滚、增量文件缺失、release --force --discard-patches 之后的高水位、不匹配 app_id。
# 然后：fhpb console import 导入 -> 起旧 server.py 与新服务 -> console_parity.py 逐字节对拍 -> 负控制。
#   FHP_TEST_PY          装好 cryptography/flask/waitress 的 Python
#   FHP_TEST_SERVER_DIR  服务端代码目录
#   FHP_PARITY_REPO      给了就对这个真实旧仓库做对拍（不造仓库；须含 app_id）
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PY="${FHP_TEST_PY:-$REPO_ROOT/tools/.venv/bin/python}"
[ -x "$PY" ] || PY="$(command -v python3)"
SRVDIR="${FHP_TEST_SERVER_DIR:-$REPO_ROOT/../flutter_code_push/server}"
CLI="$REPO_ROOT/tools/broute/cli.py"
TMP="$(mktemp -d)"; OLDP=8795; NEWP=8796
command -v cygpath >/dev/null 2>&1 && TMP="$(cygpath -m "$TMP")"
FAILS=0
fail(){ echo "FAIL: $1"; FAILS=$((FAILS+1)); }
pass(){ echo "PASS: $1"; }
PIDS=()
cleanup(){ for p in "${PIDS[@]:-}"; do [ -n "$p" ] && kill "$p" 2>/dev/null; done; rm -rf "$TMP"; }
trap cleanup EXIT
export FHPB_MODE=local PYTHONPATH="$REPO_ROOT/tools/broute"

REPO="${FHP_PARITY_REPO:-$TMP/repo}"
if [ -z "${FHP_PARITY_REPO:-}" ]; then
  APP="$TMP/app"; KEYS="$TMP/keys"; BIN="$TMP/bin"
  mkdir -p "$BIN" "$APP/build/ios/iphoneos/Runner.app/Frameworks/App.framework" "$APP/.dart_tool/flutter_build/x"
  cat > "$BIN/analyze_snapshot" <<'SH'
#!/usr/bin/env bash
for a in "$@"; do case "$a" in --out=*) OUT="${a#--out=}";; esac; done
head -c 65536 /dev/zero > "$OUT"
SH
  cat > "$BIN/patch" <<'SH'
#!/usr/bin/env bash
head -c 1024 /dev/urandom > "$3"
SH
  cat > "$BIN/gen_snapshot" <<'SH'
#!/usr/bin/env bash
for a in "$@"; do case "$a" in --elf=*) ELF="${a#--elf=}";; esac; done
{ head -c 32768 /dev/zero; printf 'product no-code_comments no-dwarf_stack_traces_mode dedup_instructions '; } > "$ELF"
SH
  chmod +x "$BIN"/*
  { head -c 4096 /dev/urandom; printf 'product no-code_comments no-dwarf_stack_traces_mode dedup_instructions '; } \
    > "$APP/build/ios/iphoneos/Runner.app/Frameworks/App.framework/App"
  "$PY" -c "
import sys
open(sys.argv[1],'wb').write(b'\x90\xab\xcd\xef'+(130).to_bytes(4,'big')+b'\x00'*2048)" "$APP/.dart_tool/flutter_build/x/app.dill"
  printf 'name: demo\nflutter:\n  uses-material-design: true\n' > "$APP/pubspec.yaml"
  "$PY" "$CLI" init --app-dir "$APP" --base-url "http://127.0.0.1:$OLDP" --keys "$KEYS" --app-id APP1 >/dev/null 2>&1

  rel(){ "$PY" "$CLI" release --app-dir "$APP" --repo "$REPO" --release-version "$1" \
           --analyze-snapshot "$BIN/analyze_snapshot" --gen-snapshot "$BIN/gen_snapshot" "${@:2}" >/dev/null 2>&1; }
  pub(){ # $1=版本 $2=编号 $3=通道
    "$PY" - "$REPO" "$KEYS" "$BIN/patch" "$1" "$2" "$3" "$OLDP" <<'PY'
import pathlib, sys
import cli
repo, keys, tool, ver, number, channel, port = sys.argv[1:]
vm = pathlib.Path(repo) / ".vm.vmcode"
vm.write_bytes(bytes([int(number)]) * 8192)
cli.publish_vmcode(pathlib.Path(repo), ver, vm, number=int(number), base_url=f"http://127.0.0.1:{port}",
                   channel=channel, private_key=pathlib.Path(keys) / "patch_private.pem",
                   note=f"n{number}", patch_tool=pathlib.Path(tool))
PY
  }
  rb(){ "$PY" "$CLI" rollback --repo "$REPO" --release-version "$1" --patch "$2" >/dev/null 2>&1; }

  # V1：多渠道 + 已回滚(5 先于 2，看回滚次序) + 增量缺失(4)
  rel 1.2.3+7
  pub 1.2.3+7 1 stable; pub 1.2.3+7 2 beta; pub 1.2.3+7 3 stable; pub 1.2.3+7 4 stable; pub 1.2.3+7 5 beta
  rb 1.2.3+7 5; rb 1.2.3+7 2
  rm -f "$REPO/releases/1.2.3+7/patches/4.bin"
  # V2：发过补丁又 --force --discard-patches：没有补丁条目，只剩高水位
  rel 2.0.0+1; pub 2.0.0+1 1 stable; pub 2.0.0+1 2 stable
  rel 2.0.0+1 --force --discard-patches
  # V3：作废之后又发了新号（高水位之上）
  rel 3.0.0+1; pub 3.0.0+1 1 stable
  rel 3.0.0+1 --force --discard-patches; pub 3.0.0+1 2 stable
fi
APPID=$("$PY" -c "import json,glob,sys;print(json.load(open(sorted(glob.glob(sys.argv[1]+'/releases/*/release.json'))[0]))['app_id'])" "$REPO")

# --- 导入（走 fhpb console import，即服务端 app.importer 的同一逻辑） ----------------
DATA="$TMP/data"; mkdir -p "$DATA"
"$PY" "$CLI" console import --repo "$REPO" --data-dir "$DATA" --server-dir "$SRVDIR" --python "$PY" >"$TMP/imp.txt" 2>&1
RC=$?
cat "$TMP/imp.txt"
[ $RC -eq 0 ] && pass "fhpb console import 成功（导入器自证答复一致）" || fail "导入失败 rc=$RC"
grep -q "答复不一致 0 项" "$TMP/imp.txt" && pass "导入器自带自证：不一致 0 项" || fail "导入器自证不是 0 项"
"$PY" "$CLI" console import --repo "$REPO" --data-dir "$DATA" --server-dir "$SRVDIR" --python "$PY" >/dev/null 2>&1 \
  && pass "重复导入安全（幂等）" || fail "重复导入失败"

# --- 起两个服务 -------------------------------------------------------------------
"$PY" "$REPO_ROOT/tools/broute/server.py" --repo "$REPO" --port $OLDP --bind 127.0.0.1 --app-id "$APPID" >"$TMP/old.log" 2>&1 &
PIDS+=($!)
(cd "$SRVDIR" && exec "$PY" -m app serve --data-dir "$DATA" --port $NEWP --base-url "http://127.0.0.1:$OLDP") >"$TMP/new.log" 2>&1 &
PIDS+=($!)
for _ in $(seq 1 30); do
  curl -s -m 1 "http://127.0.0.1:$NEWP/healthz" >/dev/null 2>&1 && curl -s -m 1 -o /dev/null "http://127.0.0.1:$OLDP/x" 2>/dev/null && break
  sleep 0.5
done

par(){ "$PY" "$REPO_ROOT/tools/tests/console_parity.py" --old "http://127.0.0.1:$OLDP" --new "http://127.0.0.1:$NEWP" \
         --repo "$REPO" --app-id "$APPID"; }

echo "=== 对拍（正向）"
par >"$TMP/par1.txt" 2>&1; R1=$?
cat "$TMP/par1.txt"
[ $R1 -eq 0 ] && pass "core 组逐字节相同" || fail "core 组有差异"

# --- 负控制 1：新服务把一个已回滚的补丁改回未回滚 -> 对拍必须红 ------------------------
echo "=== 负控制 1：改新库（补丁 #2 取消回滚）"
SQ="import sqlite3,sys;c=sqlite3.connect(sys.argv[1]);c.execute(sys.argv[2]);c.commit()"
"$PY" -c "$SQ" "$DATA/console.db" "UPDATE patches SET is_rolled_back=0 WHERE number=2 AND release_id=(SELECT id FROM releases WHERE version='1.2.3+7')"
par >"$TMP/nc1.txt" 2>&1; N1=$?
grep -E "^\[core\]|DIFF|RESULT" "$TMP/nc1.txt" | head -12
[ $N1 -ne 0 ] && pass "负控制 1：改坏新库后对拍变红" || fail "负控制 1 没红"
"$PY" -c "$SQ" "$DATA/console.db" "UPDATE patches SET is_rolled_back=1 WHERE number=2 AND release_id=(SELECT id FROM releases WHERE version='1.2.3+7')"
par >/dev/null 2>&1 && pass "负控制 1 还原后恢复全绿" || fail "还原后仍红"

# --- 负控制 2：旧仓库里抹掉一个补丁的签名 -> 对拍必须红 ----------------------------------
echo "=== 负控制 2：改旧仓库（抹掉 V1 补丁 #3 的 hash_signature；#3 是 stable 最新，设备会收到它）"
IDXF="$REPO/releases/1.2.3+7/index.json"; cp "$IDXF" "$TMP/index.bak"
"$PY" -c "
import json,sys;p=sys.argv[1];i=json.load(open(p))
[x for x in i['patches'] if x['number']==3][0].pop('hash_signature');json.dump(i,open(p,'w'),indent=2)" "$IDXF"
par >"$TMP/nc2.txt" 2>&1; N2=$?
grep -E "^\[core\]|RESULT" "$TMP/nc2.txt"; grep -m2 DIFF -A2 "$TMP/nc2.txt"
[ $N2 -ne 0 ] && pass "负控制 2：改坏旧仓库后对拍变红" || fail "负控制 2 没红"
cp "$TMP/index.bak" "$IDXF"
par >/dev/null 2>&1 && pass "负控制 2 还原后恢复全绿" || fail "还原后仍红"

echo "---"
[ "$FAILS" -eq 0 ] && { echo "ALL PASS"; exit 0; } || { echo "$FAILS FAILURE(S)"; exit 1; }
