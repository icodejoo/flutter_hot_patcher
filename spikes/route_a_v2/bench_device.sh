#!/usr/bin/env bash
# A/B/C 性能对拍：同一个 app、同一个引擎，三种执行方式跑同一个热循环。
#
#   DEVICE=<udid> ./bench_device.sh [rounds]
#
#   native  hotLoopNative 走原生 AOT
#   kbc     Route-A：KBC 模块重绑 hotLoop，循环体由 KBC 解释器执行
#   sim     Route-B：.vmcode 把 hotLoopNative 换掉，subgraph_hash 不匹配 →
#           不 link 回原生 → 由 ARM64 Simulator 解释执行
#
# 三种配置轮换跑（native,kbc,sim,native,kbc,sim,…）而不是每种连跑 N 次：
# 单机热节流会系统性地偏袒先跑的那一组。
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
DEVICE="${DEVICE:?usage: DEVICE=<udid> $0 [rounds]}"
ROUNDS="${1:-3}"
B="${BUNDLE_ID:-com.hotpatch.bench.hotpatch}"
MODULE="${MODULE:-/tmp/bmod/module.bytecode}"
VMCODE="${VMCODE:-/tmp/benchpatch/out.vmcode}"
OUT="${OUT:-/tmp/bench_results}"
SB="Library/Application Support/shorebird/shorebird_updater"

for f in "$MODULE" "$VMCODE"; do
  [ -e "$f" ] || { echo "missing: $f"; exit 1; }
done
rm -rf "$OUT"; mkdir -p "$OUT"
W=$(mktemp -d); trap 'rm -rf "$W"' EXIT

push() { xcrun devicectl device copy to --device "$DEVICE" \
    --domain-type appDataContainer --domain-identifier "$B" \
    --source "$1" --destination "$2" >/dev/null 2>&1; }

# 实测修正：patch 被成功 boot 一次后 updater 会消费掉 next_boot_patch，
# 并且校验失败时会把 patches/N/state.json 改写成 {"kind":"Bad",...} 并删掉
# dlc.vmcode。所以每一轮都要重新 stage 整个 patch，不能只切指针。
mkdir -p "$W/patches/1"
cp "$VMCODE" "$W/patches/1/dlc.vmcode"
SIZE=$(wc -c < "$VMCODE" | tr -d ' ')
python3 -c "
import json,sys
open('$W/patches/1/state.json','w').write(json.dumps({'kind':'Installed','signature':None,'size':$SIZE}))"
push "$MODULE" "Documents/module.bytecode"

stage_patch() { push "$W/patches" "$SB/patches"; }

pointers() { python3 -c "
import json,sys
n = None if '$1'=='null' else int('$1')
open('$W/pointers.json','w').write(json.dumps(
  {'next_boot_patch':n,'last_booted_patch':None,
   'currently_booting_patch':None,'boot_started_at':None}))"
  push "$W/pointers.json" "$SB/pointers.json"; }

mode() { printf '%s' "$1" > "$W/mode.txt"; push "$W/mode.txt" "Documents/mode.txt"; }

run_one() {  # $1=label $2=mode $3=next_boot_patch
  mode "$2"
  if [ "$3" != "null" ]; then stage_patch; fi
  pointers "$3"
  pkill -f idevicesyslog 2>/dev/null || true
  local log="$OUT/$1.log"
  : > "$log"
  idevicesyslog -u "$DEVICE" > "$log" 2>&1 &
  local sp=$!
  xcrun devicectl device process launch --device "$DEVICE" --terminate-existing "$B" >/dev/null 2>&1
  # 等 BENCH 行出现；Route-B 解释执行启动很慢，给足时间
  local i=0
  while [ $i -lt 120 ] && ! grep -aq "FHP_A=BENCH" "$log"; do i=$((i+1)); /bin/sleep 1; done
  kill $sp 2>/dev/null || true
  grep -a "FHP_A=" "$log" | sed 's/.*FHP_A=/  /'
}

# native 基线不在这里测：X1 的 A1 补丁让 arm64 上 USING_SIMULATOR 无条件生效，
# 所有 Dart 都跑在 Simulator 里，这个引擎产不出原生数字。原生要用 stock 引擎
# 重建同一个 app（不带 --local-engine，也不带 --dynamic-interface）后单独测，
# 见 docs/AB_BENCHMARK_ROUTE_A_VS_B.md「必须说清的三条限制」。
for r in $(seq 1 "$ROUNDS"); do
  echo ""; echo "########## round $r"
  echo "--- kbc (Route-A)"; run_one "kbc_$r" kbc 1
  echo "--- sim (Route-B)"; run_one "sim_$r" native 1
done

echo ""; echo "########## summary"
python3 - "$OUT" <<'PY'
import re, sys, pathlib, statistics
out = pathlib.Path(sys.argv[1])
res = {}
for f in sorted(out.glob('*.log')):
    cfg = f.stem.rsplit('_', 1)[0]
    for line in f.read_text(errors='ignore').splitlines():
        m = re.search(r'FHP_A=BENCH mode=(\S+) calls=(\d+) elapsed_us=(\d+) ns_per_call=([\d.]+) ns_per_iter=([\d.]+)', line)
        if m:
            res.setdefault(cfg, []).append(float(m.group(5)))
print(f"{'config':10} {'runs':>5} {'ns/iter median':>16} {'min':>10} {'max':>10}")
med = {}
for k in ('kbc', 'sim'):
    v = res.get(k, [])
    if not v:
        print(f"{k:10} {'0':>5}  (no data)"); continue
    med[k] = statistics.median(v)
    print(f"{k:10} {len(v):>5} {med[k]:>16.3f} {min(v):>10.3f} {max(v):>10.3f}")
if 'kbc' in med and 'sim' in med:
    print()
    print(f"sim / kbc = {med['sim']/med['kbc']:.2f}x")
    print("native 基线请用 stock 引擎单独测，见 docs/AB_BENCHMARK_ROUTE_A_VS_B.md")
PY
