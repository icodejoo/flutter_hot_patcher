#!/usr/bin/env bash
# 步骤 2：A/B 性能对比（X1 引擎上，原生 vs 解释）
#
#   DEVICE=<identifier> ./bench_device.sh
#
# 实验设计（已用工具链实测校验）：
#   热函数 hotLoop = 10K 迭代累加，与历史数据同函数
#   （spikes/benchmark/hotpatch_demo/patches/greet_cpu.dart），
#   以便与 Shorebird 806.7µs / A-route KBC 156.4µs 直接可比。
#
#   补丁版把迭代数改为 10001，**目的是让 subgraph_hash 变化**——
#   否则 hotLoop 会被 link 回原生，测到的仍是 AOT 速度而非解释器。
#   已验证：7079 个函数中恰好 1 个未匹配，就是 hotLoop。
#   （0.01% 的工作量差异相对 4000× 的量级差可忽略。）
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
V="$HERE/valapp29"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
DEVICE="${DEVICE:-}"
BUNDLE_ID="${BUNDLE_ID:-com.hotpatch.valapp29}"
APP_ID="${APP_ID:-11111111-2222-3333-4444-555555555555}"
F29=~/fvm/versions/3.29.0/bin/flutter

[ -n "$DEVICE" ] || { xcrun devicectl list devices; echo ""; echo "用法： DEVICE=<id> $0" >&2; exit 1; }
step() { echo ""; echo "=== $* ==="; }

step "A. 构建 baseline（hotLoop 走原生 AOT）"
cp "$V/lib/main_bench_baseline.dart" "$V/lib/main.dart"
( cd "$V" && rm -rf build .dart_tool/flutter_build && "$F29" build ios --release \
    --no-codesign --no-tree-shake-icons \
    --local-engine-src-path="$HOME/engine_ios/src" --local-engine=ios_release \
    --local-engine-host=host_release ) > /tmp/bench_a.log 2>&1
echo "构建完成"

step "B. 生成 benchmark 补丁（hotLoop 走解释器）"
cp "$V/lib/main_bench_patched.dart" "$V/lib/main.dart"
rm -rf /tmp/benchpatch
bash "$REPO_ROOT/tools/build_app_patch.sh" "$V" "$V" /tmp/benchpatch 2>&1 | tail -5
cp "$V/lib/main_bench_baseline.dart" "$V/lib/main.dart"

echo "确认只有 hotLoop 未匹配："
python3 -c "
import json
b={f['subgraph_hash'] for f in json.load(open('/tmp/benchpatch/base.json'))['functions']}
u=[f['name'] for f in json.load(open('/tmp/benchpatch/patch.json'))['functions'] if f['subgraph_hash'] not in b]
print('  未匹配:', u)
assert u==['hotLoop'], '实验无效：未匹配集合应恰为 [hotLoop]'
"

step "C. 测 baseline（原生）"
PATCH_DIR=/tmp/benchpatch DEVICE="$DEVICE" BUNDLE_ID="$BUNDLE_ID" APP_ID="$APP_ID" \
  bash -c 'true'   # 安装与启动沿用 e2e_device.sh 的步骤 2-3
echo "运行 e2e_device.sh 的签名/安装/启动部分，记录屏幕上的 ns/call"
echo "或看日志： log stream --device --predicate 'eventMessage CONTAINS \"BENCH\"'"

step "D. 装补丁后测（解释）"
echo "用 e2e_device.sh 注入 /tmp/benchpatch/out.vmcode，冷重启，记录 ns/call"

step "E. 结论"
cat <<'MANUAL'
填入下表（与历史数据对照）：

  X1 原生 AOT（baseline）      : ____ ns/call
  X1 解释（B-route/Simulator）  : ____ ns/call
  ── 历史参照 ──
  Shorebird Simulator          : 806,700 ns/call（实测）
  A-route KBC 字节码            : 156,363 ns/call（实测）
  AOT                          :     172 ns/call（实测）

判读：
  若 X1 解释 ≈ 806,700 → 我们的 B-route 与 Shorebird 同级，
    「5.15× 更快」只属于 A-route(KBC)，不属于产品路径。
  若 X1 解释 明显优于 806,700 → 我们的 SimulatorToCPU 实现有优势，
    这才是选 X1 而非 Shorebird 引擎的理由。
MANUAL
