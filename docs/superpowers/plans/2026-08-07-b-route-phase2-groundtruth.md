# B-Route Phase 2.0 取证 Spike Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 Shorebird 自己的 fork 二进制在本地离线产出一套 linker ground truth，把 `.vmcode` 布局、LinkTable 编码、subgraph hash 输入、`.link` 中间格式、DD table 语义五项从推断变为字节级实测，并据此产出 A/B 决策报告。

**Architecture:** 纯取证 spike，不写 linker、不改引擎。所有产物落在 `spikes/b_route_phase2_groundtruth/`。核心杠杆是 `aot_tools link --dump-debug-info`——它会落盘 `ct.aot` / `preDdOptimized.aot` / `ddOnly.aot` / `optimized.aot` 四段中间快照，逐段差分即可分离每组 `--base_*_link_data` flag 的单独效果。两个 Python 解析器（`.vmcode`、`.link`）用 aot_tools 自己输出的文本产物（`link_table.txt`、`*.json`）作为独立 oracle 做 TDD。

**Tech Stack:** bash、Python 3（pytest）、Shorebird fork `gen_snapshot_arm64` / `analyze_snapshot_arm64`、`aot-tools.dill`、Shorebird `patch`（bidiff+zstd）

**Spec:** `docs/superpowers/specs/2026-08-07-b-route-phase2-groundtruth-design.md`

---

## 执行期实测修正（2026-08-07，Task 0–2 完成后回写）

以下是执行中实测到的、与本计划初稿不符或初稿未知的事实。**后续任务以这里为准。**

**环境**
- 本机唯一的 bash 是 `/bin/bash` 3.2.57。不可用 bash 4+ 特性（nameref `local -n`、关联数组等）。
- 交互 shell 是 zsh，`env.sh` 用了 bash 数组与 `shopt`，一律经 `bash -c 'source ./env.sh && ...'` 调用。
- pytest 装在 spike 内的隔离 venv：`env.sh` 导出 `PY="$SPIKE_ROOT/.venv/bin/python"`。
  **全文中的 `python3` 一律替换为 `"$PY"`**（计划初稿写的 `pip install --user pytest` 已作废）。

**⚠️ RTK 的 `diff` 在本 repo 内不可信**
- 单行差异的两个文件会被报成 `✅ Files are identical` 且退出码 0；多处改动时统计数字与 hunk 行号也是错的。
- 同样的文件复制到 `/tmp` 下比对则正常，只在 repo 路径触发。
- **任何差异验证一律用 `command diff` / `cmp` / `command git diff --no-index`；git 一律用 `command git`。**

**gen_kernel 必须加 `--target=flutter`**
- 计划初稿 Task 2 Step 1/Step 2 的 `gen_kernel` 命令**缺这个 flag，会直接崩**：
  `Null check operator used on a null value` at `DillLoader.read` / `DillTarget.loadExtraRequiredLibraries`。
- 原因：Shorebird fork 的 `platform_strong.dill` 是按 `--target=flutter` 编的，不是默认 vm target。
- `build_aot.sh` 已内置该 flag 并有行内注释说明。

**已实测确认**
- ELF 路径可用（`--snapshot_kind=app-aot-elf`），五个样本的 `.aot` 均 ~998KB。`SNAPSHOT_KIND=elf` 为默认。
- **gen_snapshot 字节可复现**：同一输入两次构建 `cmp` 完全一致。故 Task 6 差分矩阵里测到的任何字节差异都是真信号，不是构建噪声。

**`analyze_snapshot --shorebird --out=X.json` 的实测 schema**（Task 4/5/8 直接用，不必再探测）

注意：**必须带 `--shorebird`**。不带 `--shorebird` 是另一种格式（顶层为
`metadata` / `objects` / `shorebird` / `snapshot_data`），两者不可混用。

```
顶层: {"shorebird": "true", "snapshot_data": {...}, "functions": [...]}

snapshot_data (全部为字符串):
  dart_version, snapshot_version,
  vm_data_length, vm_data_hash,
  adjusted_vm_instructions_length, adjusted_vm_instructions_hash

functions: list，base 样本实测 1585 条。每条:
  name                 str   例 "[Optimized] Object.runtimeType"
  index_in_entries     int
  offset               int   代码在 instructions 区的偏移
  size                 int
  self_hash            str   40 位十六进制 = SHA-1
  subgraph_hash        str   SHA-1
  op_subgraph_hash     str   SHA-1
  self_pp              list[int]   自身用到的 object pool 槽位下标
  subgraph_pp          list[int]
  self_selectors       list[int]
  subgraph_selectors   list[int]
  self_field_table     list[int]
  subgraph_field_table list[int]
  callees              list[int]   调用图边，值为被调者的 index_in_entries
```

- Task 8 的 `compare_hashes.py` `load_codes()` 直接取顶层 `functions`，按 `name` 建索引即可。
- `callees` 是计划初稿未预料到的字段，它就是 `code_graph.dart` 的输入。

**架构佐证**：`dart_version` 实测为
`3.12.2 (stable) ... on "macos_simarm64"` —— **simarm64**，即 Shorebird 为 iOS 产出的是
SIMARM64 快照。这与设计文档 §1.5 "patch 指令由 VM 内置 Simulator 执行" 的推断一致。

---

## File Structure

全部新建，位于 `spikes/b_route_phase2_groundtruth/`：

| 文件 | 职责 |
|------|------|
| `env.sh` | 唯一的路径真相源。导出所有工具路径，任一缺失即硬失败退出。所有其他脚本 `source` 它。 |
| `.gitignore` | 排除 `out/`（debug bundle 体积大） |
| `samples/base.dart` | 基线样本，含虚调用与 tear-off 以确保触发 DD table |
| `samples/s1_equal_len.dart` | 字符串常量等长改动 |
| `samples/s2_diff_len.dart` | 字符串常量变长改动 |
| `samples/s3_body.dart` | 函数体改动（指令变化） |
| `samples/s4_add.dart` | 新增函数 + 新增类 |
| `build_aot.sh` | 单个 `.dart` → `.dill` → `.aot`。封装 snapshot kind 的选择。 |
| `run_link.sh` | 对一组 (base, patch) 驱动 `aot_tools link --dump-debug-info --reporter=json` |
| `run.sh` | 顶层编排：build base + 四个样本，逐个 link，汇总 |
| `parse_vmcode.py` | `.vmcode` 头部 + LinkTable 二进制解析器（U1/U2） |
| `parse_link_data.py` | `ct.link` / `op.link` / `dt.link` / `ft.link` 解析器（U4） |
| `diff_matrix.py` | 四段中间快照差分矩阵：字节差异 / bidiff 大小 / LinkStats |
| `tests/test_parse_vmcode.py` | 以 `link_table.txt` 为 oracle 校验 `parse_vmcode.py` |
| `tests/test_parse_link_data.py` | 以 `object_pool.json` / `class_table.json` 为 oracle 校验 `parse_link_data.py` |
| `GROUND_TRUTH.md` | U1–U5 实测规格，每条附复现命令 |

决策报告写到 `docs/superpowers/specs/2026-08-07-b-route-phase2-ab-decision.md`。

---

## Task 0: Spike 骨架与环境固化

**Files:**
- Create: `spikes/b_route_phase2_groundtruth/env.sh`
- Create: `spikes/b_route_phase2_groundtruth/.gitignore`

- [ ] **Step 1: 写 `.gitignore`**

创建 `spikes/b_route_phase2_groundtruth/.gitignore`：

```gitignore
out/
__pycache__/
.pytest_cache/
```

- [ ] **Step 2: 写 `env.sh`**

创建 `spikes/b_route_phase2_groundtruth/env.sh`。这是唯一的路径真相源；任何工具缺失必须**硬失败**，
不允许静默继续（沿用 `spikes/gate2_linker/PRODUCTION_LINKER_SPEC.md` R8 纪律）。

```bash
#!/usr/bin/env bash
# Shorebird linker 取证 spike —— 环境定义。所有脚本 source 本文件。
# 纪律：任一工具缺失即硬失败，绝不静默降级。
set -euo pipefail

SB_HOME="${SB_HOME:-$HOME/.shorebird}"

# Shorebird 缓存的 Flutter revision 目录（只应有一个；多于一个时硬失败要求显式指定）
if [ -z "${SB_FLUTTER_REV:-}" ]; then
  _revs=("$SB_HOME"/bin/cache/flutter/*/)
  if [ "${#_revs[@]}" -ne 1 ]; then
    echo "FATAL: expected exactly 1 flutter revision under $SB_HOME/bin/cache/flutter/, found ${#_revs[@]}." >&2
    echo "       Set SB_FLUTTER_REV=<revision> explicitly." >&2
    exit 1
  fi
  SB_FLUTTER_REV="$(basename "${_revs[0]}")"
fi
export SB_FLUTTER_REV

SB_FLUTTER="$SB_HOME/bin/cache/flutter/$SB_FLUTTER_REV"
SB_ENGINE="$SB_FLUTTER/bin/cache/artifacts/engine"

export DART="$SB_FLUTTER/bin/dart"
export DARTAOTRUNTIME="$SB_FLUTTER/bin/cache/dart-sdk/bin/dartaotruntime"
export GEN_KERNEL="$SB_FLUTTER/bin/cache/dart-sdk/bin/snapshots/gen_kernel_aot.dart.snapshot"
export PLATFORM_DILL="$SB_ENGINE/common/flutter_patched_sdk_product/platform_strong.dill"
export GEN_SNAPSHOT="$SB_ENGINE/ios-release/gen_snapshot_arm64"
export ANALYZE_SNAPSHOT="$SB_ENGINE/ios-release/analyze_snapshot_arm64"
export SB_PATCH="$SB_HOME/bin/cache/artifacts/patch/patch"

# aot-tools.dill（目录名是内容 hash，同样要求唯一）
_aots=("$SB_HOME"/bin/cache/artifacts/aot-tools/*/aot-tools.dill)
if [ "${#_aots[@]}" -ne 1 ]; then
  echo "FATAL: expected exactly 1 aot-tools.dill, found ${#_aots[@]}." >&2
  exit 1
fi
export AOT_TOOLS="${_aots[0]}"

export SPIKE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export OUT_DIR="${OUT_DIR:-$SPIKE_ROOT/out}"

sb_require() {
  local var="$1" path="${!1}"
  if [ ! -e "$path" ]; then
    echo "FATAL: $var not found at: $path" >&2
    exit 1
  fi
}

for v in DART DARTAOTRUNTIME GEN_KERNEL PLATFORM_DILL GEN_SNAPSHOT ANALYZE_SNAPSHOT SB_PATCH AOT_TOOLS; do
  sb_require "$v"
done

sb_env_report() {
  echo "SB_FLUTTER_REV   = $SB_FLUTTER_REV"
  echo "DART             = $DART  ($("$DART" --version 2>&1 | head -1))"
  echo "GEN_SNAPSHOT     = $GEN_SNAPSHOT"
  echo "ANALYZE_SNAPSHOT = $ANALYZE_SNAPSHOT"
  echo "AOT_TOOLS        = $AOT_TOOLS  (version $("$DART" run "$AOT_TOOLS" --version 2>&1 | tail -1))"
  echo "PLATFORM_DILL    = $PLATFORM_DILL"
  echo "OUT_DIR          = $OUT_DIR"
}
```

- [ ] **Step 3: 运行环境自检**

Run:
```bash
cd /Users/Cruz/Documents/flutter_hot_patcher/spikes/b_route_phase2_groundtruth
bash -c 'source ./env.sh && sb_env_report'
```

Expected: 打印 8 行路径，无 `FATAL`。`DART` 一行应含 `Dart SDK version: 3.12.x`。
若任何一行报 `FATAL: ... not found`，**停下来**，先解决路径问题再继续——不要改脚本去绕过检查。

- [ ] **Step 4: 确认 pytest 可用**

Run: `python3 -m pytest --version`
Expected: 打印版本号。若 `No module named pytest`，先执行 `python3 -m pip install --user pytest` 再重试。

- [ ] **Step 5: Commit**

```bash
cd /Users/Cruz/Documents/flutter_hot_patcher
git add spikes/b_route_phase2_groundtruth/env.sh spikes/b_route_phase2_groundtruth/.gitignore
git commit -m "spike(b_route_p2): 取证 spike 环境定义与硬失败自检"
```

---

## Task 1: 受控样本源码

**Files:**
- Create: `spikes/b_route_phase2_groundtruth/samples/base.dart`
- Create: `spikes/b_route_phase2_groundtruth/samples/s1_equal_len.dart`
- Create: `spikes/b_route_phase2_groundtruth/samples/s2_diff_len.dart`
- Create: `spikes/b_route_phase2_groundtruth/samples/s3_body.dart`
- Create: `spikes/b_route_phase2_groundtruth/samples/s4_add.dart`

样本必须包含虚调用与 tear-off，否则 DD table 可能为空，U5 无从取证。

- [ ] **Step 1: 写 `samples/base.dart`**

```dart
// 取证基线样本。
// 刻意包含：字符串常量、虚调用（多实现）、tear-off、闭包，
// 以确保 object pool / dispatch table / DD table 三张表都非空。

abstract class Greeter {
  String greet();
}

class EnglishGreeter implements Greeter {
  @override
  String greet() => 'ORIGINAL_EN';
}

class FrenchGreeter implements Greeter {
  @override
  String greet() => 'ORIGINAL_FR';
}

class GermanGreeter implements Greeter {
  @override
  String greet() => 'ORIGINAL_DE';
}

const kTag = 'TAG_AAAA';

int computeChecksum(int seed) {
  var acc = seed;
  for (var i = 0; i < 16; i++) {
    acc = (acc * 31 + i) & 0xFFFFFF;
  }
  return acc;
}

List<Greeter> makeGreeters() => [EnglishGreeter(), FrenchGreeter(), GermanGreeter()];

void main(List<String> args) {
  final greeters = makeGreeters();
  // 虚调用：编译期不可静态解析，进入 dispatch table / DD table
  for (final g in greeters) {
    print('${g.greet()} $kTag');
  }
  // tear-off + 闭包
  final fn = computeChecksum;
  final wrapped = (int x) => fn(x) + 1;
  print(wrapped(args.length));
}
```

- [ ] **Step 2: 写 `samples/s1_equal_len.dart`（字符串常量等长改动）**

复制 `base.dart` 全文，仅把 `const kTag = 'TAG_AAAA';` 改为：

```dart
const kTag = 'TAG_BBBB';
```

其余一字不改。`TAG_AAAA` 与 `TAG_BBBB` 均为 8 字符，长度相同。

- [ ] **Step 3: 写 `samples/s2_diff_len.dart`（字符串常量变长改动）**

复制 `base.dart` 全文，仅把 `const kTag = 'TAG_AAAA';` 改为：

```dart
const kTag = 'TAG_AAAA_EXTENDED_LONGER';
```

其余一字不改。

- [ ] **Step 4: 写 `samples/s3_body.dart`（函数体改动）**

复制 `base.dart` 全文，仅把 `computeChecksum` 的循环常数从 `31` 改为 `37`：

```dart
int computeChecksum(int seed) {
  var acc = seed;
  for (var i = 0; i < 16; i++) {
    acc = (acc * 37 + i) & 0xFFFFFF;
  }
  return acc;
}
```

其余一字不改。这会改变指令字节但不改变任何常量长度。

- [ ] **Step 5: 写 `samples/s4_add.dart`（新增函数 + 新增类）**

复制 `base.dart` 全文，在 `GermanGreeter` 之后插入一个新类，并在 `makeGreeters` 中带上它，
再新增一个顶层函数：

```dart
class SpanishGreeter implements Greeter {
  @override
  String greet() => 'ORIGINAL_ES';
}

int computeSquare(int x) => x * x;
```

同时把 `makeGreeters` 改为：

```dart
List<Greeter> makeGreeters() =>
    [EnglishGreeter(), FrenchGreeter(), GermanGreeter(), SpanishGreeter()];
```

并在 `main` 末尾追加一行，确保 `computeSquare` 不被 TFA 树摇掉：

```dart
  print(computeSquare(args.length));
```

- [ ] **Step 6: 验证五个样本都能被 Dart 分析器接受**

Run:
```bash
cd /Users/Cruz/Documents/flutter_hot_patcher/spikes/b_route_phase2_groundtruth
source ./env.sh
for f in samples/*.dart; do "$DART" analyze --no-fatal-warnings "$f" || echo "ANALYZE FAILED: $f"; done
```

Expected: 每个文件输出 `No issues found!`（或仅 info 级提示），不出现 `ANALYZE FAILED`。

- [ ] **Step 7: Commit**

```bash
cd /Users/Cruz/Documents/flutter_hot_patcher
git add spikes/b_route_phase2_groundtruth/samples
git commit -m "spike(b_route_p2): 四组受控样本（等长/变长常量、函数体、新增类）"
```

---

## Task 2: `.dart` → `.aot` 构建脚本

**Files:**
- Create: `spikes/b_route_phase2_groundtruth/build_aot.sh`

Shorebird 的 `gen_snapshot_arm64` 是 iOS arm64 目标。它同时支持 `app-aot-elf` 与 `app-aot-assembly`。
ELF 单文件对 `analyze_snapshot` 更友好，优先走 ELF；若 ELF 不被支持则退到 assembly + clang。
两条路径下面都写全，不留"视情况处理"。

- [ ] **Step 1: 探测 gen_snapshot 是否接受 ELF 输出**

Run:
```bash
cd /Users/Cruz/Documents/flutter_hot_patcher/spikes/b_route_phase2_groundtruth
source ./env.sh
mkdir -p "$OUT_DIR/probe"
"$DARTAOTRUNTIME" "$GEN_KERNEL" --platform "$PLATFORM_DILL" --aot --tfa \
  -o "$OUT_DIR/probe/base.dill" samples/base.dart
"$GEN_SNAPSHOT" --snapshot_kind=app-aot-elf --elf="$OUT_DIR/probe/base.aot" \
  "$OUT_DIR/probe/base.dill" && echo "ELF_OK" || echo "ELF_FAILED"
ls -la "$OUT_DIR/probe/"
```

Expected: 打印 `ELF_OK`，且 `base.aot` 存在且非空（数 MB）。

记录结果：若打印 `ELF_FAILED`，Step 2 使用 assembly 分支；否则使用 ELF 分支。

- [ ] **Step 2: 写 `build_aot.sh`**

创建 `spikes/b_route_phase2_groundtruth/build_aot.sh`。`SNAPSHOT_KIND` 默认 `elf`，
Step 1 若探测失败则调用时传 `SNAPSHOT_KIND=assembly`。

```bash
#!/usr/bin/env bash
# 用法: build_aot.sh <input.dart> <output_dir> <name>
# 产出: <output_dir>/<name>.dill 与 <output_dir>/<name>.aot
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/env.sh"

INPUT="$1"; OUTDIR="$2"; NAME="$3"
SNAPSHOT_KIND="${SNAPSHOT_KIND:-elf}"
mkdir -p "$OUTDIR"

DILL="$OUTDIR/$NAME.dill"
AOT="$OUTDIR/$NAME.aot"

echo "[build_aot] gen_kernel -> $DILL"
"$DARTAOTRUNTIME" "$GEN_KERNEL" \
  --platform "$PLATFORM_DILL" \
  --aot --tfa \
  -Ddart.vm.product=true \
  -o "$DILL" \
  "$INPUT"

[ -s "$DILL" ] || { echo "FATAL: gen_kernel produced empty $DILL" >&2; exit 1; }

echo "[build_aot] gen_snapshot ($SNAPSHOT_KIND) -> $AOT"
case "$SNAPSHOT_KIND" in
  elf)
    "$GEN_SNAPSHOT" --snapshot_kind=app-aot-elf --elf="$AOT" "$DILL"
    ;;
  assembly)
    ASM="$OUTDIR/$NAME.S"
    "$GEN_SNAPSHOT" --snapshot_kind=app-aot-assembly --assembly="$ASM" "$DILL"
    [ -s "$ASM" ] || { echo "FATAL: gen_snapshot produced empty $ASM" >&2; exit 1; }
    xcrun --sdk iphoneos clang -arch arm64 -dynamiclib \
      -Wl,-U,_kDartVmSnapshotData -Wl,-U,_kDartVmSnapshotInstructions \
      -Wl,-U,_kDartIsolateSnapshotData -Wl,-U,_kDartIsolateSnapshotInstructions \
      -o "$AOT" "$ASM"
    ;;
  *)
    echo "FATAL: unknown SNAPSHOT_KIND=$SNAPSHOT_KIND (expected elf|assembly)" >&2
    exit 1
    ;;
esac

[ -s "$AOT" ] || { echo "FATAL: gen_snapshot produced empty $AOT" >&2; exit 1; }
echo "[build_aot] ok: $(ls -la "$AOT")"
```

- [ ] **Step 3: 构建全部五个 `.aot`**

Run:
```bash
cd /Users/Cruz/Documents/flutter_hot_patcher/spikes/b_route_phase2_groundtruth
chmod +x build_aot.sh
source ./env.sh
for s in base s1_equal_len s2_diff_len s3_body s4_add; do
  ./build_aot.sh "samples/$s.dart" "$OUT_DIR/aot" "$s"
done
ls -la "$OUT_DIR/aot/"
```

Expected: 五个 `.aot` 与五个 `.dill`，每个 `.aot` 非空。

- [ ] **Step 4: 确认 analyze_snapshot 能读这些 `.aot`**

Run:
```bash
cd /Users/Cruz/Documents/flutter_hot_patcher/spikes/b_route_phase2_groundtruth
source ./env.sh
"$ANALYZE_SNAPSHOT" --shorebird --out="$OUT_DIR/probe/base.analyze.json" "$OUT_DIR/aot/base.aot"
python3 -c "
import json,sys
d=json.load(open('$OUT_DIR/probe/base.analyze.json'))
print('top-level keys:', sorted(d.keys())[:20])
"
```

Expected: 生成 JSON 且能被 `json.load` 解析，打印出顶层 key 列表。
把这份 key 列表记下来——Task 4/5 会用到。若 analyze_snapshot 报错，**停下来**排查 `.aot` 格式，
不要继续往下走。

- [ ] **Step 5: Commit**

```bash
cd /Users/Cruz/Documents/flutter_hot_patcher
git add spikes/b_route_phase2_groundtruth/build_aot.sh
git commit -m "spike(b_route_p2): .dart -> .dill -> .aot 构建脚本（elf/assembly 双路径）"
```

---

## Task 3: 驱动 `aot_tools link`

**Files:**
- Create: `spikes/b_route_phase2_groundtruth/run_link.sh`
- Create: `spikes/b_route_phase2_groundtruth/run.sh`

- [ ] **Step 1: 写 `run_link.sh`**

创建 `spikes/b_route_phase2_groundtruth/run_link.sh`：

```bash
#!/usr/bin/env bash
# 用法: run_link.sh <sample_name>
# 前提: $OUT_DIR/aot/base.aot 与 $OUT_DIR/aot/<sample_name>.aot 已存在
# 产出: $OUT_DIR/link/<sample_name>/ 下的 out.vmcode / link.jsonl / debug/
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/env.sh"

NAME="$1"
BASE_AOT="$OUT_DIR/aot/base.aot"
PATCH_AOT="$OUT_DIR/aot/$NAME.aot"
PATCH_DILL="$OUT_DIR/aot/$NAME.dill"
WORK="$OUT_DIR/link/$NAME"

for f in "$BASE_AOT" "$PATCH_AOT" "$PATCH_DILL"; do
  [ -s "$f" ] || { echo "FATAL: missing input $f" >&2; exit 1; }
done

rm -rf "$WORK"
mkdir -p "$WORK/debug"

echo "[link] $NAME"
set +e
"$DART" run "$AOT_TOOLS" link \
  --base="$BASE_AOT" \
  --patch="$PATCH_AOT" \
  --analyze-snapshot="$ANALYZE_SNAPSHOT" \
  --gen-snapshot="$GEN_SNAPSHOT" \
  --kernel="$PATCH_DILL" \
  --output="$WORK/out.vmcode" \
  --dump-debug-info="$WORK/debug" \
  --reporter=json \
  --redirect-to="$WORK/link.jsonl" \
  --disassemble \
  --verbose > "$WORK/stdout.txt" 2> "$WORK/stderr.txt"
RC=$?
set -e

echo "[link] exit=$RC"
if [ -s "$WORK/link.jsonl" ]; then
  echo "[link] jsonl events:"
  python3 -c "
import json,sys
for line in open('$WORK/link.jsonl'):
    line=line.strip()
    if not line: continue
    e=json.loads(line)
    print('  ', e.get('type'), {k:v for k,v in e.items() if k!='type'})
"
fi

if [ $RC -ne 0 ]; then
  echo "[link] FAILED — stderr tail:" >&2
  tail -30 "$WORK/stderr.txt" >&2
  exit $RC
fi

[ -s "$WORK/out.vmcode" ] || { echo "FATAL: no out.vmcode produced" >&2; exit 1; }
echo "[link] ok: $(ls -la "$WORK/out.vmcode")"
echo "[link] debug dir contents:"
find "$WORK/debug" -type f | sed 's|^|    |'
```

- [ ] **Step 2: 对 s1 单跑一次，看 debug 目录真实结构**

Run:
```bash
cd /Users/Cruz/Documents/flutter_hot_patcher/spikes/b_route_phase2_groundtruth
chmod +x run_link.sh
./run_link.sh s1_equal_len
```

Expected: `[link] exit=0`，jsonl 里出现 `link_success` 事件并带 `link_percentage`，
`debug` 目录下列出文件清单。预期能看到（依据设计文档 §1.6）：
`ct.aot`、`preDdOptimized.aot`、`ddOnly.aot`、`optimized.aot`、`link_table.txt`、
`manifest.json`、`*.analyze_snapshot.json`、`class_table.json`、`dispatch_table.json`、
`field_table.json`、`object_pool.json`、`object_pool.txt`、`*.link`。

**把实际清单原样记录下来。** 如果实际文件名与预期不符，以实际为准，并在
Task 9 的 `GROUND_TRUTH.md` 中记下差异——不要修改脚本去"凑"预期。

若 `link` 失败并报 `base and patch snapshots have differing VM sections`，
说明 base 与 patch 的编译参数不一致；核对两次 `build_aot.sh` 调用的参数完全相同后重试。

- [ ] **Step 3: 写 `run.sh` 顶层编排**

创建 `spikes/b_route_phase2_groundtruth/run.sh`：

```bash
#!/usr/bin/env bash
# 顶层编排：构建 base + 四组样本，逐个 link。
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
source ./env.sh

SAMPLES=(s1_equal_len s2_diff_len s3_body s4_add)

echo "=== 1/3 build aot ==="
./build_aot.sh samples/base.dart "$OUT_DIR/aot" base
for s in "${SAMPLES[@]}"; do
  ./build_aot.sh "samples/$s.dart" "$OUT_DIR/aot" "$s"
done

echo "=== 2/3 link ==="
FAILED=()
for s in "${SAMPLES[@]}"; do
  ./run_link.sh "$s" || FAILED+=("$s")
done

echo "=== 3/3 summary ==="
for s in "${SAMPLES[@]}"; do
  jsonl="$OUT_DIR/link/$s/link.jsonl"
  if [ -s "$jsonl" ]; then
    python3 -c "
import json
pct=None
for line in open('$jsonl'):
    line=line.strip()
    if not line: continue
    e=json.loads(line)
    if e.get('type')=='link_success': pct=e.get('link_percentage')
print(f'  $s: link_percentage={pct}')
"
  else
    echo "  $s: NO JSONL"
  fi
done

if [ "${#FAILED[@]}" -gt 0 ]; then
  echo "FAILED SAMPLES: ${FAILED[*]}" >&2
  exit 1
fi
echo "ALL OK"
```

- [ ] **Step 4: 全量跑通**

Run:
```bash
cd /Users/Cruz/Documents/flutter_hot_patcher/spikes/b_route_phase2_groundtruth
chmod +x run.sh
./run.sh
```

Expected: 末尾打印 `ALL OK`，四个样本各有一个 `link_percentage` 数值。

**预期结论对照**（设计文档 §1.5 的架构推断）：`s1` / `s2` 应接近 100%（只动常量），
`s3` 应因 `computeChecksum` 及其调用者 unlink 而略低于 100%，`s4` 应出现 `Reason.added`。
若 `s3` 仍是 100%，说明 subgraph hash 的输入与推断不符——这是重要发现，记录下来，不要忽略。

若某个样本 link 失败，**不要跳过它**。记录失败原因，它本身就是取证结论的一部分。

- [ ] **Step 5: Commit**

```bash
cd /Users/Cruz/Documents/flutter_hot_patcher
git add spikes/b_route_phase2_groundtruth/run_link.sh spikes/b_route_phase2_groundtruth/run.sh
git commit -m "spike(b_route_p2): aot_tools link 驱动脚本与顶层编排"
```

---

## Task 4: `.vmcode` 解析器（U1 + U2）

**Files:**
- Create: `spikes/b_route_phase2_groundtruth/parse_vmcode.py`
- Create: `spikes/b_route_phase2_groundtruth/tests/test_parse_vmcode.py`

`out.vmcode` = `padToAlignment(LinkTable, pageSize) ++ optimizedPatch bytes`（设计文档 §1.6）。
`link_table.txt` 是 aot_tools 自己写的文本版链接表，作为二进制解析的**独立 oracle**。

- [ ] **Step 1: 人工勘察头部与 oracle 格式**

Run:
```bash
cd /Users/Cruz/Documents/flutter_hot_patcher/spikes/b_route_phase2_groundtruth
source ./env.sh
W="$OUT_DIR/link/s1_equal_len"
echo "--- vmcode size ---"; ls -la "$W/out.vmcode"
echo "--- first 128 bytes ---"; xxd -l 128 "$W/out.vmcode"
echo "--- optimized.aot size ---"; ls -la "$W/debug/optimized.aot" 2>/dev/null || find "$W/debug" -name "optimized*"
echo "--- link_table.txt head ---"; head -20 "$W/debug/link_table.txt" 2>/dev/null || find "$W/debug" -name "link_table*"
echo "--- link_table.txt lines ---"; wc -l "$W/debug/link_table.txt" 2>/dev/null
```

Expected: 看到 vmcode 前 128 字节的十六进制。记录：
1. 是否有可识别的 magic（引擎里有 `WrongMagic`/`WrongVersion` 字符串，说明存在头部）
2. `len(out.vmcode) - len(optimized.aot)` = LinkTable 区（含 padding）的字节数
3. `link_table.txt` 的行格式与行数

**把这三项原样写进笔记**，Step 2 的测试要用到。

- [ ] **Step 2: 写失败的测试**

创建 `spikes/b_route_phase2_groundtruth/tests/test_parse_vmcode.py`。
oracle 是 `link_table.txt`：解析器抽出的 mapping 数必须与文本版一致，且 sim offset 必须单调递增
（设计文档 §1.7 的 `Missing/Unexpected mapping for sim offset` 校验暗示了这一性质）。

```python
import os
import re
import subprocess
import sys

import pytest

SPIKE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SPIKE)

from parse_vmcode import parse_vmcode  # noqa: E402

OUT = os.environ.get("OUT_DIR", os.path.join(SPIKE, "out"))
SAMPLE = "s1_equal_len"
WORK = os.path.join(OUT, "link", SAMPLE)
VMCODE = os.path.join(WORK, "out.vmcode")
LINK_TABLE_TXT = os.path.join(WORK, "debug", "link_table.txt")
OPTIMIZED_AOT = os.path.join(WORK, "debug", "optimized.aot")


def _require(path):
    if not os.path.exists(path):
        pytest.fail(
            f"missing fixture {path}. Run ./run.sh first. "
            "Do NOT skip this test — a missing fixture is a hard failure."
        )


def oracle_mapping_count():
    """从 aot_tools 自己写的 link_table.txt 数出 mapping 条数。"""
    _require(LINK_TABLE_TXT)
    with open(LINK_TABLE_TXT) as f:
        text = f.read()
    # link_table.txt 每条 mapping 一行，形如 "<index>: sim=<n> cpu=<n>" 之类。
    # 精确正则在 Step 1 勘察后填入；这里按"含两个十进制数的行"计数。
    lines = [l for l in text.splitlines() if re.search(r"\d+.*\d+", l)]
    return len(lines)


def test_vmcode_splits_into_link_table_and_snapshot():
    _require(VMCODE)
    _require(OPTIMIZED_AOT)
    result = parse_vmcode(VMCODE)
    snapshot_size = os.path.getsize(OPTIMIZED_AOT)
    assert result.snapshot_size == snapshot_size, (
        f"parsed snapshot region is {result.snapshot_size} bytes but "
        f"optimized.aot is {snapshot_size} bytes"
    )


def test_mapping_count_matches_link_table_txt():
    _require(VMCODE)
    result = parse_vmcode(VMCODE)
    assert len(result.mappings) == oracle_mapping_count()


def test_sim_offsets_are_strictly_increasing():
    _require(VMCODE)
    result = parse_vmcode(VMCODE)
    sims = [m.sim_offset for m in result.mappings]
    assert sims == sorted(sims), "sim offsets are not sorted"
    assert len(set(sims)) == len(sims), "duplicate sim offsets"


def test_cli_prints_summary():
    _require(VMCODE)
    out = subprocess.run(
        [sys.executable, os.path.join(SPIKE, "parse_vmcode.py"), VMCODE],
        capture_output=True, text=True, check=True,
    ).stdout
    assert "mappings=" in out
    assert "snapshot_size=" in out
```

- [ ] **Step 3: 运行测试，确认失败**

Run:
```bash
cd /Users/Cruz/Documents/flutter_hot_patcher/spikes/b_route_phase2_groundtruth
python3 -m pytest tests/test_parse_vmcode.py -v
```

Expected: FAIL，报 `ModuleNotFoundError: No module named 'parse_vmcode'`。

- [ ] **Step 4: 写 `parse_vmcode.py`**

创建 `spikes/b_route_phase2_groundtruth/parse_vmcode.py`。
下面是骨架，**头部字段的偏移与宽度必须按 Step 1 勘察到的实际字节填入**——
`HEADER_SPEC` 里的候选解释若与实际不符，以实际为准并更新常量。
纪律：解析不出来就 `raise`，不许返回空表。

```python
#!/usr/bin/env python3
"""Shorebird .vmcode 解析器。

文件结构（来自 aot_tools LinkCommand._writeVmCodeFile 的字符串证据）:
    [ LinkTable, padToAlignment(pageSize) ][ optimized patch snapshot bytes ]

LinkTable 由 ByteWriter.addInt32 写出，条目为 (cpuOffset, simOffset) 对。
本模块用实测数据反推确切布局；任何不一致一律抛异常，绝不静默。
"""
from __future__ import annotations

import struct
import sys
from dataclasses import dataclass

PAGE_SIZE = 4096  # aot_tools 用 pageSize 对齐；若实测不符，改这里并在 GROUND_TRUTH.md 记录


@dataclass(frozen=True)
class Mapping:
    cpu_offset: int
    sim_offset: int


@dataclass
class VmCode:
    header: dict
    mappings: list[Mapping]
    link_table_region_size: int  # 含 padding
    snapshot_offset: int
    snapshot_size: int


def _u32(buf: bytes, off: int) -> int:
    return struct.unpack_from("<I", buf, off)[0]


def parse_vmcode(path: str) -> VmCode:
    with open(path, "rb") as f:
        data = f.read()

    if len(data) < PAGE_SIZE:
        raise ValueError(f"{path}: too small ({len(data)} bytes) to contain a LinkTable page")

    # --- 头部 ---
    # 引擎二进制含 "WrongMagic"/"WrongVersion"，故假定前两个 u32 为 magic 与 version。
    # Step 1 勘察若显示不同布局，改这里。
    magic = _u32(data, 0)
    version = _u32(data, 4)
    count = _u32(data, 8)
    header = {"magic": hex(magic), "version": version, "count": count}

    # --- LinkTable 条目 ---
    entry_size = 8  # 两个 int32
    table_start = 12
    table_end = table_start + count * entry_size
    if table_end > len(data):
        raise ValueError(
            f"{path}: declared count={count} needs {table_end} bytes but file is {len(data)}. "
            "Header layout assumption is wrong — re-inspect with `xxd -l 128`."
        )

    mappings = []
    for i in range(count):
        off = table_start + i * entry_size
        mappings.append(Mapping(cpu_offset=_u32(data, off), sim_offset=_u32(data, off + 4)))

    # --- 分界 ---
    region = ((table_end + PAGE_SIZE - 1) // PAGE_SIZE) * PAGE_SIZE
    snapshot_size = len(data) - region
    if snapshot_size <= 0:
        raise ValueError(
            f"{path}: LinkTable region {region} >= file size {len(data)}; layout assumption wrong."
        )

    return VmCode(
        header=header,
        mappings=mappings,
        link_table_region_size=region,
        snapshot_offset=region,
        snapshot_size=snapshot_size,
    )


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {argv[0]} <out.vmcode>", file=sys.stderr)
        return 2
    vc = parse_vmcode(argv[1])
    print(f"header={vc.header}")
    print(f"mappings={len(vc.mappings)}")
    print(f"link_table_region_size={vc.link_table_region_size}")
    print(f"snapshot_offset={vc.snapshot_offset}")
    print(f"snapshot_size={vc.snapshot_size}")
    for m in vc.mappings[:10]:
        print(f"  sim=0x{m.sim_offset:x} -> cpu=0x{m.cpu_offset:x}")
    if len(vc.mappings) > 10:
        print(f"  ... {len(vc.mappings) - 10} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
```

- [ ] **Step 5: 迭代到测试通过**

Run:
```bash
cd /Users/Cruz/Documents/flutter_hot_patcher/spikes/b_route_phase2_groundtruth
python3 -m pytest tests/test_parse_vmcode.py -v
```

Expected: 4 passed。

若失败，用真实字节调整假设（头部宽度、字段顺序、entry 是 `(cpu,sim)` 还是 `(sim,cpu)`、
`PAGE_SIZE` 是否 4096 还是 16384）。每次调整都必须由 `xxd` 观察到的实际字节支撑，
不允许为了让测试变绿而放宽断言。

`test_mapping_count_matches_link_table_txt` 中的 oracle 正则在 Step 1 看到
`link_table.txt` 真实格式后收紧为精确匹配。

- [ ] **Step 6: 对全部四个样本跑一遍解析器**

Run:
```bash
cd /Users/Cruz/Documents/flutter_hot_patcher/spikes/b_route_phase2_groundtruth
source ./env.sh
for s in s1_equal_len s2_diff_len s3_body s4_add; do
  echo "=== $s ==="
  python3 parse_vmcode.py "$OUT_DIR/link/$s/out.vmcode"
done
```

Expected: 四个样本都解析成功，mapping 数随样本变化（s3/s4 应少于 s1/s2）。

- [ ] **Step 7: Commit**

```bash
cd /Users/Cruz/Documents/flutter_hot_patcher
git add spikes/b_route_phase2_groundtruth/parse_vmcode.py spikes/b_route_phase2_groundtruth/tests/test_parse_vmcode.py
git commit -m "spike(b_route_p2): .vmcode 头部与 LinkTable 解析器（U1/U2）"
```

---

## Task 5: `.link` 中间格式解析器（U4）

**Files:**
- Create: `spikes/b_route_phase2_groundtruth/parse_link_data.py`
- Create: `spikes/b_route_phase2_groundtruth/tests/test_parse_link_data.py`

`ct.link` / `op.link` / `dt.link` / `ft.link` 是 fork gen_snapshot 的**输入契约**，A 与 B 两个方案都得自己生成它。
oracle 用 aot_tools 同时输出的 `class_table.json` / `object_pool.json`（同一份数据的 JSON 视图）。

- [ ] **Step 1: 勘察 `.link` 文件与对应 JSON**

Run:
```bash
cd /Users/Cruz/Documents/flutter_hot_patcher/spikes/b_route_phase2_groundtruth
source ./env.sh
W="$OUT_DIR/link/s1_equal_len/debug"
find "$W" -name "*.link" -exec ls -la {} \;
for f in $(find "$W" -name "*.link"); do echo "=== $f ==="; xxd -l 64 "$f"; done
echo "=== class_table.json head ==="
python3 -c "
import json,glob
for p in glob.glob('$W/**/class_table.json', recursive=True):
    d=json.load(open(p)); print(p, type(d), list(d)[:10] if isinstance(d,dict) else d[:3]); break
"
echo "=== object_pool.json head ==="
python3 -c "
import json,glob
for p in glob.glob('$W/**/object_pool.json', recursive=True):
    d=json.load(open(p)); print(p, type(d), list(d)[:10] if isinstance(d,dict) else d[:3]); break
"
```

Expected: 列出所有 `.link` 文件与各自前 64 字节，以及两个 JSON 的顶层结构。
**记录每个 `.link` 的字节大小与 JSON 里对应实体的数量** —— 两者的比值直接给出 entry 宽度。

- [ ] **Step 2: 写失败的测试**

创建 `spikes/b_route_phase2_groundtruth/tests/test_parse_link_data.py`：

```python
import glob
import json
import os
import sys

import pytest

SPIKE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SPIKE)

from parse_link_data import parse_link_file, LinkFileKind  # noqa: E402

OUT = os.environ.get("OUT_DIR", os.path.join(SPIKE, "out"))
DEBUG = os.path.join(OUT, "link", "s1_equal_len", "debug")


def _find(pattern):
    hits = glob.glob(os.path.join(DEBUG, "**", pattern), recursive=True)
    if not hits:
        pytest.fail(
            f"no {pattern} under {DEBUG}. Run ./run.sh first. "
            "A missing artifact is a hard failure, not a skip."
        )
    return hits[0]


def test_every_link_file_parses():
    link_files = glob.glob(os.path.join(DEBUG, "**", "*.link"), recursive=True)
    assert link_files, f"no .link files under {DEBUG}"
    for path in link_files:
        parsed = parse_link_file(path)
        assert parsed.kind is not LinkFileKind.UNKNOWN, f"unrecognised kind for {path}"
        assert parsed.entries, f"{path} parsed to zero entries"


def test_no_trailing_bytes():
    """entry 宽度若猜错，尾部必然剩下不足一条的字节。"""
    for path in glob.glob(os.path.join(DEBUG, "**", "*.link"), recursive=True):
        parsed = parse_link_file(path)
        assert parsed.trailing_bytes == 0, (
            f"{path}: {parsed.trailing_bytes} trailing bytes — entry width assumption is wrong"
        )


def test_class_table_link_entry_count_matches_json():
    ct = _find("ct.link")
    js = _find("class_table.json")
    parsed = parse_link_file(ct)
    data = json.load(open(js))
    entities = data["classes"] if isinstance(data, dict) and "classes" in data else data
    assert len(parsed.entries) == len(entities)
```

- [ ] **Step 3: 运行测试，确认失败**

Run: `python3 -m pytest tests/test_parse_link_data.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'parse_link_data'`。

- [ ] **Step 4: 写 `parse_link_data.py`**

创建 `spikes/b_route_phase2_groundtruth/parse_link_data.py`：

```python
#!/usr/bin/env python3
"""Shorebird linker 中间文件（ct/op/dt/ft .link）解析器。

这些文件是 fork gen_snapshot 的输入契约:
    --base_ct_link_data=  --patch_ct_link_data=
    --base_op_link_data=  --patch_op_link_data=
    --base_dt_link_data=  --base_ft_link_data=

格式未公开。本模块按实测反推；entry 宽度猜错时 trailing_bytes != 0 会暴露出来。
"""
from __future__ import annotations

import os
import struct
import sys
from dataclasses import dataclass, field
from enum import Enum


class LinkFileKind(Enum):
    CLASS_TABLE = "ct"
    OBJECT_POOL = "op"
    DISPATCH_TABLE = "dt"
    FIELD_TABLE = "ft"
    DD = "dd"
    UNKNOWN = "unknown"


# entry 宽度（字节）。Step 1 勘察后按 文件大小 / JSON 实体数 校正。
ENTRY_WIDTH = {
    LinkFileKind.CLASS_TABLE: 8,
    LinkFileKind.OBJECT_POOL: 8,
    LinkFileKind.DISPATCH_TABLE: 8,
    LinkFileKind.FIELD_TABLE: 8,
    LinkFileKind.DD: 8,
}


@dataclass
class ParsedLinkFile:
    path: str
    kind: LinkFileKind
    header: dict = field(default_factory=dict)
    entries: list[tuple[int, ...]] = field(default_factory=list)
    trailing_bytes: int = 0


def classify(path: str) -> LinkFileKind:
    name = os.path.basename(path)
    for kind in LinkFileKind:
        if kind is LinkFileKind.UNKNOWN:
            continue
        if name.startswith(kind.value + ".") or name.startswith(kind.value + "_"):
            return kind
    return LinkFileKind.UNKNOWN


def parse_link_file(path: str) -> ParsedLinkFile:
    kind = classify(path)
    if kind is LinkFileKind.UNKNOWN:
        raise ValueError(f"cannot classify link file: {path}")

    with open(path, "rb") as f:
        data = f.read()
    if not data:
        raise ValueError(f"{path} is empty")

    width = ENTRY_WIDTH[kind]
    # 头部宽度：Step 1 勘察确定。若无头部则设为 0。
    header_size = 0
    body = data[header_size:]

    count = len(body) // width
    trailing = len(body) - count * width

    fmt = "<" + "I" * (width // 4)
    entries = [struct.unpack_from(fmt, body, i * width) for i in range(count)]

    return ParsedLinkFile(
        path=path, kind=kind,
        header={"file_size": len(data), "header_size": header_size},
        entries=entries, trailing_bytes=trailing,
    )


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(f"usage: {argv[0]} <file.link> [...]", file=sys.stderr)
        return 2
    for path in argv[1:]:
        p = parse_link_file(path)
        print(f"{path}: kind={p.kind.value} entries={len(p.entries)} "
              f"trailing={p.trailing_bytes} header={p.header}")
        for e in p.entries[:5]:
            print("   ", tuple(hex(x) for x in e))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
```

- [ ] **Step 5: 迭代到测试通过**

Run: `python3 -m pytest tests/test_parse_link_data.py -v`
Expected: 3 passed。

调整 `ENTRY_WIDTH` 与 `header_size` 直到 `trailing_bytes == 0` 且条目数与 JSON 一致。
每次调整都要有实测依据。若某类 `.link` 怎么调都对不上，**如实记录为"格式未破解"**，
在 `GROUND_TRUTH.md` 中标注，不要伪造一个能通过的宽度。此时把对应测试改为
`pytest.xfail(reason=...)` 并写明原因，而不是删掉它。

- [ ] **Step 6: Commit**

```bash
cd /Users/Cruz/Documents/flutter_hot_patcher
git add spikes/b_route_phase2_groundtruth/parse_link_data.py spikes/b_route_phase2_groundtruth/tests/test_parse_link_data.py
git commit -m "spike(b_route_p2): ct/op/dt/ft .link 中间格式解析器（U4）"
```

---

## Task 6: 四段中间快照差分矩阵

**Files:**
- Create: `spikes/b_route_phase2_groundtruth/diff_matrix.py`

设计文档 §2.2：把 `patch.aot → ct.aot → preDdOptimized.aot → ddOnly.aot → optimized.aot`
逐段差分，分离每组 flag 的单独效果。

- [ ] **Step 1: 确认 Shorebird `patch` 二进制的调用方式**

Run:
```bash
cd /Users/Cruz/Documents/flutter_hot_patcher/spikes/b_route_phase2_groundtruth
source ./env.sh
"$SB_PATCH" --help 2>&1 | head -20 || "$SB_PATCH" 2>&1 | head -20
```

Expected: 打印用法。记录参数顺序（Phase 1 已用过该工具，见 `spikes/b_route_vmcode/FINDINGS.md`；
若 `--help` 无输出，参照该文档中的既有调用方式）。

- [ ] **Step 2: 写 `diff_matrix.py`**

创建 `spikes/b_route_phase2_groundtruth/diff_matrix.py`。
`SB_PATCH_ARGV` 按 Step 1 的实际用法填写。

```python
#!/usr/bin/env python3
"""四段中间快照差分矩阵。

对每个样本，沿 patch.aot -> ct.aot -> preDdOptimized.aot -> ddOnly.aot -> optimized.aot
逐段计算:
  - 相对 base.aot 的字节差异数
  - bidiff+zstd（Shorebird patch 工具）后的 diff 大小
并汇总 link.jsonl 中的 LinkStats。输出 Markdown 表格。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

STAGES = ["patch", "ct", "preDdOptimized", "ddOnly", "optimized"]
SAMPLES = ["s1_equal_len", "s2_diff_len", "s3_body", "s4_add"]

SB_PATCH = os.environ["SB_PATCH"]
OUT_DIR = os.environ["OUT_DIR"]


def byte_diff_count(a: str, b: str) -> int:
    """逐字节比较；长度不同的尾部全部计入差异。"""
    with open(a, "rb") as fa, open(b, "rb") as fb:
        da, db = fa.read(), fb.read()
    n = min(len(da), len(db))
    return sum(1 for i in range(n) if da[i] != db[i]) + abs(len(da) - len(db))


def bidiff_size(base: str, new: str) -> int | None:
    """用 Shorebird patch 工具产 diff，返回字节数；失败返回 None（不静默成 0）。"""
    with tempfile.NamedTemporaryFile(suffix=".patch", delete=False) as tmp:
        out = tmp.name
    try:
        # SB_PATCH_ARGV: 依 Step 1 实测的参数顺序
        r = subprocess.run([SB_PATCH, base, new, out], capture_output=True, text=True)
        if r.returncode != 0:
            print(f"  WARN: patch failed ({base} -> {new}): {r.stderr.strip()}", file=sys.stderr)
            return None
        return os.path.getsize(out)
    finally:
        if os.path.exists(out):
            os.unlink(out)


def stage_path(sample: str, stage: str) -> str | None:
    if stage == "patch":
        p = os.path.join(OUT_DIR, "aot", f"{sample}.aot")
    else:
        p = os.path.join(OUT_DIR, "link", sample, "debug", f"{stage}.aot")
    return p if os.path.exists(p) else None


def link_stats(sample: str) -> dict:
    path = os.path.join(OUT_DIR, "link", sample, "link.jsonl")
    if not os.path.exists(path):
        return {}
    for line in open(path):
        line = line.strip()
        if not line:
            continue
        e = json.loads(line)
        if e.get("type") == "link_success":
            return e
    return {}


def main() -> int:
    base_aot = os.path.join(OUT_DIR, "aot", "base.aot")
    if not os.path.exists(base_aot):
        print(f"FATAL: {base_aot} missing. Run ./run.sh first.", file=sys.stderr)
        return 1

    print("# 差分矩阵\n")
    print(f"base.aot = {os.path.getsize(base_aot)} bytes\n")
    print("| sample | stage | size | byte_diff_vs_base | bidiff_size |")
    print("|---|---|---|---|---|")
    missing = []
    for s in SAMPLES:
        for st in STAGES:
            p = stage_path(s, st)
            if p is None:
                missing.append(f"{s}/{st}")
                print(f"| {s} | {st} | MISSING | — | — |")
                continue
            bd = byte_diff_count(base_aot, p)
            bs = bidiff_size(base_aot, p)
            print(f"| {s} | {st} | {os.path.getsize(p)} | {bd} | "
                  f"{bs if bs is not None else 'FAILED'} |")

    print("\n# LinkStats\n")
    print("| sample | link_percentage | base_codes | patch_codes | linked_code_size |")
    print("|---|---|---|---|---|")
    for s in SAMPLES:
        st = link_stats(s)
        print(f"| {s} | {st.get('link_percentage')} | {st.get('base_codes_length')} | "
              f"{st.get('patch_codes_length')} | {st.get('linked_code_size')} |")

    if missing:
        print(f"\n**MISSING ARTIFACTS:** {', '.join(missing)}", file=sys.stderr)
        print(f"\n> ⚠️ 缺失产物: {', '.join(missing)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: 生成矩阵**

Run:
```bash
cd /Users/Cruz/Documents/flutter_hot_patcher/spikes/b_route_phase2_groundtruth
source ./env.sh
python3 diff_matrix.py | tee "$OUT_DIR/diff_matrix.md"
```

Expected: 两张 Markdown 表。**逐行看，别只看跑通了。** 关键读法：
- `patch → ct` 行之间 `byte_diff_vs_base` 的下降 = class table 对齐的贡献
- `ct → preDdOptimized` 的下降 = object pool + dispatch/field table 对齐的贡献
- `preDdOptimized → ddOnly` 的变化 = DD slot mapping 的贡献
- `s2_diff_len` 的 `optimized` 行如果仍是大数字，说明对象池对齐没能吃掉变长字符串的重排——
  这直接推翻方案 B 的价值假设，是决策报告的核心输入

若某一列全是 `MISSING`，说明 `--dump-debug-info` 没落盘那一段，回到 Task 3 Step 2 核对实际文件名。

- [ ] **Step 4: Commit**

```bash
cd /Users/Cruz/Documents/flutter_hot_patcher
git add spikes/b_route_phase2_groundtruth/diff_matrix.py
git commit -m "spike(b_route_p2): 四段中间快照差分矩阵"
```

---

## Task 7: DD table 取证（U5）

**Files:**
- Create: `spikes/b_route_phase2_groundtruth/probe_dd.sh`

已知线索（设计文档 §2.1）：`DD VERIFY FAIL: ... would SIGSEGV at PC 0 on the first indirect call`，
初判 DD 是间接调用跳转表，rewriter 把直调改写成经 DD slot 的 `LDR+BLR`。**须验证这个初判。**

- [ ] **Step 1: 写 `probe_dd.sh`**

创建 `spikes/b_route_phase2_groundtruth/probe_dd.sh`：

```bash
#!/usr/bin/env bash
# DD table 取证: 收集 dd 相关产物并对 preDdOptimized 与 ddOnly 反汇编差分。
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
source ./env.sh

SAMPLE="${1:-s3_body}"
W="$OUT_DIR/link/$SAMPLE"
D="$W/debug"
P="$OUT_DIR/dd/$SAMPLE"
mkdir -p "$P"

echo "=== 1. dd 相关产物清单 ==="
find "$D" -iname "*dd*" -exec ls -la {} \; || echo "(none found)"

echo "=== 2. dd_resolution TSV（每 slot 结局: resolved / sentinel-filled / null）==="
TSV="$(find "$D" -iname "*dd_resolution*" | head -1)"
if [ -n "$TSV" ]; then
  head -1 "$TSV"
  echo "--- 各结局计数 ---"
  tail -n +2 "$TSV" | awk -F'\t' '{c[$NF]++} END {for (k in c) print k, c[k]}'
  echo "--- 总行数 ---"; wc -l < "$TSV"
else
  echo "NOT FOUND — aot_tools 未透传 --print_dd_resolution_to；见 Step 3"
fi

echo "=== 3. stderr 中的 DD 统计行 ==="
grep -E "^DD (table|resolution|VERIFY)" "$W/stderr.txt" "$W/stdout.txt" 2>/dev/null || echo "(none)"

echo "=== 4. preDdOptimized vs ddOnly 反汇编差分 ==="
for st in preDdOptimized ddOnly; do
  f="$D/$st.aot"
  if [ -f "$f" ]; then
    objdump -d "$f" > "$P/$st.disasm" 2>/dev/null \
      || xcrun llvm-objdump -d "$f" > "$P/$st.disasm"
    echo "  $st: $(wc -l < "$P/$st.disasm") lines"
  else
    echo "  $st: MISSING"
  fi
done
if [ -f "$P/preDdOptimized.disasm" ] && [ -f "$P/ddOnly.disasm" ]; then
  diff -u "$P/preDdOptimized.disasm" "$P/ddOnly.disasm" > "$P/dd.diff" || true
  echo "  diff lines: $(wc -l < "$P/dd.diff")"
  echo "--- diff 中 ldr/blr 出现次数（验证 LDR+BLR 改写假设）---"
  grep -cE "^\+.*\bldr\b" "$P/dd.diff" || true
  grep -cE "^\+.*\bblr\b" "$P/dd.diff" || true
  echo "--- diff 前 60 行 ---"
  head -60 "$P/dd.diff"
fi
```

- [ ] **Step 2: 跑 DD 取证**

Run:
```bash
cd /Users/Cruz/Documents/flutter_hot_patcher/spikes/b_route_phase2_groundtruth
chmod +x probe_dd.sh
./probe_dd.sh s3_body 2>&1 | tee "$OUT_DIR/dd_probe_s3.txt"
./probe_dd.sh s4_add  2>&1 | tee "$OUT_DIR/dd_probe_s4.txt"
```

Expected: 至少拿到第 3 节的 `DD table: N slots, ...` 统计行。
第 4 节的 diff 中若 `+` 侧大量出现 `ldr` 紧跟 `blr`，则 LDR+BLR 改写假设成立。

**判定纪律**：假设成立就写"已验证"，不成立就写"证伪"，两者都没看出来就写"未能取证"。
三种结论都是合格产出；编一个说得通的解释不是。

- [ ] **Step 3: 若 `dd_resolution` TSV 缺失，直接调 gen_snapshot 补取**

aot_tools 未必把 `--print_dd_resolution_to` 透传出来。缺失时直接手工调用 fork gen_snapshot：

Run:
```bash
cd /Users/Cruz/Documents/flutter_hot_patcher/spikes/b_route_phase2_groundtruth
source ./env.sh
S=s3_body
D="$OUT_DIR/link/$S/debug"
mkdir -p "$OUT_DIR/dd/$S"
"$GEN_SNAPSHOT" \
  --snapshot_kind=app-aot-elf --elf="$OUT_DIR/dd/$S/manual.aot" \
  --print_shorebird_info \
  --print_dd_resolution_to="$OUT_DIR/dd/$S/dd_resolution.tsv" \
  --print_dd_function_identity_to="$OUT_DIR/dd/$S/dd_identity.txt" \
  --print_class_table_link_info_to="$OUT_DIR/dd/$S/ct_info.txt" \
  --print_dispatch_table_link_info_to="$OUT_DIR/dd/$S/dt_info.txt" \
  --print_field_table_link_info_to="$OUT_DIR/dd/$S/ft_info.txt" \
  "$OUT_DIR/aot/$S.dill" 2>&1 | tee "$OUT_DIR/dd/$S/gen_snapshot.log"
ls -la "$OUT_DIR/dd/$S/"
head -20 "$OUT_DIR/dd/$S/dd_resolution.tsv" 2>/dev/null
```

Expected: 生成 `dd_resolution.tsv` 与几个 `*_info.txt`。这些 `*_link_info_to` 的输出正是
U4 的人类可读对照版，能反过来校验 Task 5 的二进制解析。

- [ ] **Step 4: Commit**

```bash
cd /Users/Cruz/Documents/flutter_hot_patcher
git add spikes/b_route_phase2_groundtruth/probe_dd.sh
git commit -m "spike(b_route_p2): DD table 取证脚本（U5）"
```

---

## Task 8: subgraph hash 输入取证（U3）

**Files:**
- Create: `spikes/b_route_phase2_groundtruth/probe_hash.sh`

要回答的问题：`self_hash` / `subgraph_hash` 的输入包含什么？`--no_pp_hash` 关掉 PP offset 后
哪些函数从 unlink 变回 link？这直接决定"改一个字符串常量会不会引发大面积 unlink"。

- [ ] **Step 1: 写 `probe_hash.sh`**

创建 `spikes/b_route_phase2_groundtruth/probe_hash.sh`：

```bash
#!/usr/bin/env bash
# subgraph hash 取证: 对每个样本 dump analyze_snapshot JSON，
# 与 base 比对 self_hash / subgraph_hash 的变化面；再用 --no_pp_hash 复跑对照。
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
source ./env.sh

P="$OUT_DIR/hash"
mkdir -p "$P"

dump() {  # dump <aot> <outjson> [extra flags...]
  local aot="$1" out="$2"; shift 2
  "$ANALYZE_SNAPSHOT" --shorebird --out="$out" "$@" "$aot"
  [ -s "$out" ] || { echo "FATAL: analyze_snapshot produced no $out" >&2; exit 1; }
}

echo "=== dump with PP hash (default) ==="
dump "$OUT_DIR/aot/base.aot" "$P/base.json"
for s in s1_equal_len s2_diff_len s3_body s4_add; do
  dump "$OUT_DIR/aot/$s.aot" "$P/$s.json"
done

echo "=== dump with --no_pp_hash ==="
dump "$OUT_DIR/aot/base.aot" "$P/base.nopp.json" --no_pp_hash
for s in s1_equal_len s2_diff_len s3_body s4_add; do
  dump "$OUT_DIR/aot/$s.aot" "$P/$s.nopp.json" --no_pp_hash
done

echo "=== hash 变化面分析 ==="
python3 compare_hashes.py "$P"
```

- [ ] **Step 2: 写 `compare_hashes.py`**

创建 `spikes/b_route_phase2_groundtruth/compare_hashes.py`：

```python
#!/usr/bin/env python3
"""比较 base 与各样本的 self_hash / subgraph_hash 变化面。

回答: 改一处源码，有多少函数的 self_hash 变了？多少 subgraph_hash 变了？
      --no_pp_hash 能把变化面收窄多少？
"""
from __future__ import annotations

import json
import os
import sys

SAMPLES = ["s1_equal_len", "s2_diff_len", "s3_body", "s4_add"]


def load_codes(path: str) -> dict[str, dict]:
    """返回 name -> code 记录。JSON 结构未公开，逐层探测并在失败时报错。"""
    data = json.load(open(path))
    codes = None
    if isinstance(data, dict):
        for key in ("codes", "functions", "snapshot_data"):
            if key in data:
                codes = data[key]
                break
        if isinstance(codes, dict):
            for key in ("codes", "functions"):
                if key in codes:
                    codes = codes[key]
                    break
    if not isinstance(codes, list):
        raise ValueError(
            f"{path}: cannot locate the code list. "
            f"top-level keys = {sorted(data)[:20] if isinstance(data, dict) else type(data)}. "
            "Inspect the JSON and update load_codes()."
        )
    out = {}
    for c in codes:
        name = c.get("name")
        if name is None:
            raise ValueError(f"{path}: code record without 'name': {list(c)[:10]}")
        out[name] = c
    return out


def report(base_path: str, sample_path: str, label: str) -> None:
    base, patch = load_codes(base_path), load_codes(sample_path)
    common = set(base) & set(patch)
    added = set(patch) - set(base)
    removed = set(base) - set(patch)

    self_changed = [n for n in common if base[n].get("self_hash") != patch[n].get("self_hash")]
    sub_changed = [n for n in common
                   if base[n].get("subgraph_hash") != patch[n].get("subgraph_hash")]

    print(f"  {label}:")
    print(f"    total={len(patch)} common={len(common)} added={len(added)} removed={len(removed)}")
    print(f"    self_hash changed     = {len(self_changed)}"
          f" ({100*len(self_changed)/max(len(common),1):.2f}%)")
    print(f"    subgraph_hash changed = {len(sub_changed)}"
          f" ({100*len(sub_changed)/max(len(common),1):.2f}%)")
    for n in sorted(self_changed)[:10]:
        print(f"      self:     {n}")
    for n in sorted(sub_changed)[:10]:
        print(f"      subgraph: {n}")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {argv[0]} <hash_dir>", file=sys.stderr)
        return 2
    d = argv[1]
    for suffix, title in ((".json", "WITH pp hash"), (".nopp.json", "NO pp hash")):
        print(f"\n=== {title} ===")
        base = os.path.join(d, "base" + suffix)
        for s in SAMPLES:
            p = os.path.join(d, s + suffix)
            if not os.path.exists(p):
                print(f"  {s}: MISSING {p}")
                continue
            report(base, p, s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
```

- [ ] **Step 3: 跑 hash 取证**

Run:
```bash
cd /Users/Cruz/Documents/flutter_hot_patcher/spikes/b_route_phase2_groundtruth
chmod +x probe_hash.sh
./probe_hash.sh 2>&1 | tee "$OUT_DIR/hash_probe.txt"
```

Expected: 两节输出（有 / 无 PP hash），每个样本给出 self_hash 与 subgraph_hash 的变化函数数与百分比。

首次运行 `compare_hashes.py` 很可能因 JSON 结构不符而抛 `ValueError` 并打印顶层 key ——
这是设计好的行为。照它打印的 key 修 `load_codes()`，不要用 `try/except: return {}` 吞掉。

**关键读法**：
- `s1_equal_len`（等长常量）若 subgraph_hash 变化面很小 → 对象池内容变化被 hash 容忍
- `s2_diff_len`（变长常量）若变化面显著大于 s1 → PP offset 参与 hash 得到证实
- `--no_pp_hash` 若把 s2 的变化面压到接近 s1 → `--no_pp_hash` 的作用得到证实

- [ ] **Step 4: Commit**

```bash
cd /Users/Cruz/Documents/flutter_hot_patcher
git add spikes/b_route_phase2_groundtruth/probe_hash.sh spikes/b_route_phase2_groundtruth/compare_hashes.py
git commit -m "spike(b_route_p2): subgraph hash 输入取证（U3）"
```

---

## Task 9: 汇总 GROUND_TRUTH.md

**Files:**
- Create: `spikes/b_route_phase2_groundtruth/GROUND_TRUTH.md`
- Create: `spikes/b_route_phase2_groundtruth/README.md`

- [ ] **Step 1: 写 `README.md`**

创建 `spikes/b_route_phase2_groundtruth/README.md`：

```markdown
# B-Route Phase 2.0 取证 Spike

用 Shorebird 自己的 fork 二进制离线复现 `aot_tools link`，把 linker 的五项未知量实测锁死。

**设计**：`docs/superpowers/specs/2026-08-07-b-route-phase2-groundtruth-design.md`
**结论**：`GROUND_TRUTH.md`
**决策**：`docs/superpowers/specs/2026-08-07-b-route-phase2-ab-decision.md`

## 跑一遍

```bash
source ./env.sh && sb_env_report   # 环境自检
./run.sh                           # 构建 + link 四组样本
python3 -m pytest tests/ -v        # 解析器回归
python3 diff_matrix.py             # 差分矩阵
./probe_dd.sh s3_body              # DD 取证
./probe_hash.sh                    # hash 取证
```

产物全部落在 `out/`（已 gitignore）。

## 纪律

解析失败、格式失配、样本没触发目标代码路径 —— 一律硬失败或显式告警，
不允许输出"好看的 0"。沿用 `spikes/gate2_linker/PRODUCTION_LINKER_SPEC.md` R8。
```

- [ ] **Step 2: 写 `GROUND_TRUTH.md`**

创建 `spikes/b_route_phase2_groundtruth/GROUND_TRUTH.md`，用 Task 2–8 的实测数据填写。
结构如下，**每一节都必须给出复现命令，且实测与推测分开标注**：

```markdown
# Shorebird linker Ground Truth

> 实测日期：<填写>
> 工具版本：aot_tools <version> / Dart <version> / Flutter revision <rev>
> 样本：spikes/b_route_phase2_groundtruth/samples/

标注约定：**[实测]** = 有命令输出支撑；**[推测]** = 从字符串表或代码结构推断，未经实测；
**[未破解]** = 尝试过但没拿到结论。

---

## U1 .vmcode 文件布局  [实测/推测/未破解]

<头部字段表：offset / width / 字段名 / 实测值>
<LinkTable 区大小与 padding 规则>
<复现命令>

## U2 LinkTable 条目编码  [...]

<entry 宽度、字段顺序、simOffset/cpuOffset 的基准点>
<sim offset 单调性验证结果>
<复现命令>

## U3 subgraph hash 输入  [...]

<四个样本 × 有无 --no_pp_hash 的变化面表格>
<结论：PP offset 是否参与、哪些改动会导致大面积 unlink>
<复现命令>

## U4 .link 中间格式  [...]

<每类 .link 的 entry 宽度、头部、条目语义>
<与 --print_*_link_info_to 文本输出的交叉验证结果>
<未破解的部分如实列出>
<复现命令>

## U5 DD table 语义  [...]

<DD table 统计行原文>
<dd_resolution.tsv 各结局计数>
<LDR+BLR 改写假设：已验证 / 证伪 / 未能取证>
<复现命令>

---

## 差分矩阵

<粘贴 diff_matrix.py 的两张表>

## 与 Phase 1 实测数据的对照

| 场景 | Phase 1（无 linker） | Phase 2.0（Shorebird linker） |
|---|---|---|
| 等长字符串改动 | 198,818 字节差异 / 2.6KB diff | <填写> |
| 变长字符串改动 | 228,642 字节差异 / 2.4KB diff | <填写> |
| 函数体改动 | Phase 1 不支持 | <填写> |
| 新增类/函数 | Phase 1 不支持 | <填写> |

## 与设计文档推断的差异

<逐条列出：设计文档 §1.x 推断了 A，实测是 B>
<无差异时明确写"无差异">
```

- [ ] **Step 3: 核对"绝不静默"**

Run:
```bash
cd /Users/Cruz/Documents/flutter_hot_patcher/spikes/b_route_phase2_groundtruth
grep -n "\[推测\]\|\[未破解\]" GROUND_TRUTH.md
grep -n "TBD\|TODO\|<填写>" GROUND_TRUTH.md
```

Expected: 第一条命令列出所有未经实测的结论（正常，只要标注了就行）。
第二条命令**必须无输出** —— 有 `<填写>` 残留说明文档没写完。

- [ ] **Step 4: 回归全套测试**

Run:
```bash
cd /Users/Cruz/Documents/flutter_hot_patcher/spikes/b_route_phase2_groundtruth
python3 -m pytest tests/ -v
```

Expected: 全部 passed（或明确标注了 reason 的 xfail）。

- [ ] **Step 5: Commit**

```bash
cd /Users/Cruz/Documents/flutter_hot_patcher
git add spikes/b_route_phase2_groundtruth/README.md spikes/b_route_phase2_groundtruth/GROUND_TRUTH.md
git commit -m "spike(b_route_p2): GROUND_TRUTH 实测规格（U1-U5）"
```

---

## Task 10: A/B 决策报告

**Files:**
- Create: `docs/superpowers/specs/2026-08-07-b-route-phase2-ab-decision.md`
- Modify: `spikes/b_route_vmcode/FINDINGS.md`（追加 Phase 2.0 小节）
- Modify: `/Users/Cruz/.claude/projects/-Users-Cruz-Documents-flutter-hot-patcher/memory/project_b_route_phase2.md`

- [ ] **Step 1: 盘点方案 A 对我们 X1 引擎的改动面**

Run:
```bash
cd /Users/Cruz/dart/sdk
ls -la runtime/vm/simulator_arm64.cc runtime/vm/simulator_arm64.h
grep -c "" runtime/vm/simulator_arm64.cc
grep -n "DART_INCLUDE_SIMULATOR\|defined(USING_SIMULATOR)" runtime/vm/globals.h runtime/vm/simulator_arm64.h | head -20
```

Expected: 确认上游 `simulator_arm64.cc` 存在及其行数，以及它被哪个宏门控。
这是方案 A 工作量估算的基础事实（设计文档 §1.5：Shorebird 没有从零写解释器，
而是把上游 simulator 编进了 arm64 真机构建）。

记录：文件行数、门控宏名、`USING_SIMULATOR` 在 arm64 host 上默认是否为假。

- [ ] **Step 2: 写决策报告**

创建 `docs/superpowers/specs/2026-08-07-b-route-phase2-ab-decision.md`：

```markdown
# B-Route Phase 2 A/B 决策报告

> 日期：<填写>
> 依据：spikes/b_route_phase2_groundtruth/GROUND_TRUTH.md（全部实测）

## 1. 一句话结论

<推荐 A 还是 B，一句话说清>

## 2. 实测事实摘要

<从 GROUND_TRUTH.md 摘 5-8 条直接影响决策的实测数据，每条附出处小节号>

## 3. 方案 A：对齐 Shorebird 全架构

### 能力
<能覆盖哪些改动类型，依据 s1-s4 的实测>

### 需要改的地方
| 组件 | 改动 | 依据 |
|---|---|---|
| X1 Flutter Engine | 开启 arm64 simulator 编译 + CPU↔Sim 转换层 | 上游 simulator_arm64.cc <行数> 行，门控宏 <宏名> |
| gen_snapshot | 实现 --base_*_link_data 系列 | GROUND_TRUTH U4 |
| analyze_snapshot | 实现 --shorebird JSON + subgraph hash | GROUND_TRUTH U3 |
| linker（新建） | Code 图 + hash 匹配 + LinkTable 生成 | GROUND_TRUTH U1/U2 |
| updater | .vmcode 加载路径 | GROUND_TRUTH U1 |

### 工作量分解
<按周分解，每项标注依据>

### 未解风险
<GROUND_TRUTH 中标 [未破解] 的项，及其对 A 的阻塞程度>

## 4. 方案 B：只做对象池对齐，保留 data-only 约束

### 能力上限
<用 s1/s2 的实测 diff 数据说明能压到多小>
<用 s3/s4 说明覆盖不了什么>

### 工作量
<按周分解>

### 致命问题（若有）
<例如：若实测显示对象池对齐吃不掉变长字符串的重排，B 的价值假设不成立>

## 5. 在拿不到 shorebird/wrapper.cc 的前提下，A 是否可行

<逐项列缺口：哪些能从上游 Dart 直接拿、哪些必须自研、哪些没有已知路径>

## 6. 推荐与理由

<明确推荐，理由必须引用第 2 节的实测数据，不引用推断>

## 7. 若推荐 A，下一步

<Phase 2.1 的范围界定，不展开成计划>
```

- [ ] **Step 3: 更新 `spikes/b_route_vmcode/FINDINGS.md`**

在文件末尾"历史记录"之前插入一节：

```markdown
## Phase 2.0：Shorebird linker 取证（2026-08-XX）

**推翻了本文档 §"Phase 2：自研 aot_tools link"的前提。**

Shorebird linker 不是"缩小 diff 的优化"，而是另一套执行架构：patch 为完整新 AOT snapshot，
指令由 VM 内置 arm64 Simulator 解释执行（绕开 iOS W^X），LinkTable 把 subgraph hash 与 base
相同的函数从 simOffset 映射回 cpuOffset 走原生代码。link_percentage 即走原生的比例。

实测规格见 `spikes/b_route_phase2_groundtruth/GROUND_TRUTH.md`，
A/B 决策见 `docs/superpowers/specs/2026-08-07-b-route-phase2-ab-decision.md`。
```

- [ ] **Step 4: 更新 memory**

覆写 `/Users/Cruz/.claude/projects/-Users-Cruz-Documents-flutter-hot-patcher/memory/project_b_route_phase2.md`，
保留 frontmatter 的 `name` 与 `type`，把正文换成实测后的结论：Shorebird 的真实架构、
GROUND_TRUTH 的位置、A/B 决策结果、下一步。旧的"Option A 2-4 周 / Option B 4-8 周"表述必须删掉——
那是基于错误前提的估算，留着会误导下次会话。

同时更新 `memory/project_m4_m5_progress.md` 中"B-route Phase 2（待开始）"一节的描述，
以及 `memory/MEMORY.md` 里对应那行的 hook 文字。

- [ ] **Step 5: 核对无残留占位符**

Run:
```bash
cd /Users/Cruz/Documents/flutter_hot_patcher
grep -rn "<填写>\|TBD\|TODO" docs/superpowers/specs/2026-08-07-b-route-phase2-ab-decision.md spikes/b_route_phase2_groundtruth/GROUND_TRUTH.md
```

Expected: 无输出。

- [ ] **Step 6: Commit**

```bash
cd /Users/Cruz/Documents/flutter_hot_patcher
git add docs/superpowers/specs/2026-08-07-b-route-phase2-ab-decision.md \
        spikes/b_route_vmcode/FINDINGS.md memory/
git commit -m "docs(b_route): Phase 2.0 A/B 决策报告 + 修正 Phase 2 前提"
```

---

## 验收（对应设计文档 §6）

全部任务完成后逐条核对：

- [ ] `./run.sh` 在干净环境一次跑通，四组样本各有完整 debug bundle
- [ ] `parse_vmcode.py` 解析出实产 `out.vmcode` 的头部与全部 LinkTable 条目，条目数与 `link_table.txt` 一致，sim offset 单调递增校验通过
- [ ] U1–U5 在 `GROUND_TRUTH.md` 中各有结论 + 复现命令，推测显式标注
- [ ] 差分矩阵四段数据完整（字节差异 / bidiff 大小 / link_percentage / LinkStats）
- [ ] A/B 决策报告给出明确推荐，推荐理由引用实测数据
- [ ] `python3 -m pytest tests/ -v` 全绿（xfail 须带 reason）
- [ ] `out/` 未被提交进 git（`git status --short spikes/b_route_phase2_groundtruth/` 不出现 `out/`）
