# B-Route Phase 2.0：Shorebird linker 取证 spike 设计

> **日期**：2026-08-07
> **状态**：草案，待审阅
> **前置**：B-route Phase 1 已真机 PASS（`spikes/b_route_vmcode/FINDINGS.md`）

---

## 0. 为什么要先做取证，而不是直接开工

`memory/project_b_route_phase2.md` 记录的 Phase 2 目标是"消除对象池重排，把 diff 从 ~300KB 降到几十字节"，
并给了两条路径（二进制层重排 2-4 周 / fork gen_snapshot lite 4-8 周）。

**这个前提是错的。** 本次从开源材料取证后确认：Shorebird 的 linker 不是"缩小 diff 的优化"，
而是一套完全不同的补丁执行架构。对象池对齐只是让它成立的**手段之一**，不是目的。

在弄错架构的前提下选 2-4 周还是 4-8 周，选哪个都不对。所以 Phase 2 拆出一个 **Phase 2.0 取证 spike**，
先把机制实测锁死，再做 A/B 决策。

---

## 1. 已确认的事实（证据链）

以下每一条都有本地可复现的证据，不是推测。

### 1.1 三个开源面

| 材料 | 位置 | 提供了什么 |
|------|------|-----------|
| `shorebird_cli` 全源码 | `~/.shorebird/packages/shorebird_cli/` | linker 的调用方、参数、失败处理、用户告警文案 |
| `aot-tools.dill` | `~/.shorebird/bin/cache/artifacts/aot-tools/<rev>/` | kernel 字符串表可读 → 全部类名/方法名/字段名/字面量 |
| 上游 Dart SDK | `/Users/Cruz/dart/sdk` | 对照基准，判定哪些是 Shorebird 私有扩展 |

`aot-tools.dill` 的字符串表用 `strings -n 100` 即可提取（kernel 的 string table 是一整块连续 UTF-8）。
`dart pkg/kernel/bin/dump.dart` 会因 kernel format version 130 > 121 失败，不必强求。

### 1.2 aot_tools 的文件结构

从 dill 的 source-URI 表直接读出（原始路径为 `.../flutter/engine/src/flutter/third_party/dart/pkg/aot_tools/`）：

```
bin/aot_tools.dart
lib/src/aot_tools.dart, aot_tools_command.dart
lib/src/commands/{compile,dump_blobs,field_table_diff,link,link_diagnostics,
                  link_metadata,link_stats,pretty_json,query_snapshot}_command.dart
lib/src/linker/{linker,link_stats,link_reporter,link_diagnostics,code_graph}.dart
lib/src/linker/debug/{object_pool,class_table,dispatch_table,field_table,bundle}.dart
lib/src/{snapshot_analyzer,snapshot_generator,snapshot_analysis,paths,logger,version}.dart
lib/src/extensions/replace_extension.dart
```

### 1.3 Shorebird 私有的 gen_snapshot flag

在上游 Dart SDK（`runtime/` + `pkg/`）中 grep 这些 flag：**0 命中**。确认为 fork。

```
--base_ct_link_data=   --patch_ct_link_data=      # class table
--base_op_link_data=   --patch_op_link_data=      # object pool
--base_dt_link_data=                              # dispatch table
--base_ft_link_data=                              # field table
--dd_slot_mapping=
--print_class_table_link_info_to=       --print_class_table_link_debug_info_to=
--print_dispatch_table_link_info_to=    --print_dispatch_table_link_debug_info_to=
--print_field_table_link_info_to=       --print_field_table_link_debug_info_to=
--print_dd_function_identity_to=        --print_dd_resolution_to=
--print_shorebird_info
```

二进制里的成对校验错误信息证实了配对约束：

```
Error: --base_ct_link_data must be used with --patch_ct_link_data.
Error: --base_op_link_data must be used with --patch_op_link_data.
```

gen_snapshot 二进制中的源文件路径（与 `memory/project_b_route_phase2.md` 记录一致）：

```
runtime/vm/shorebird/{linker,link_info,object_pool_editor,object_pool_mapper,class_table_mapper}.cc
```

### 1.4 Shorebird 私有的 analyze_snapshot flag

`analyze_snapshot_arm64 --help --verbose` 自带一节 "Shorebird options"：

```
--shorebird                      Produce Shorebird formatted JSON, requires --out.
--no_pp_hash                     Ignore PP offsets when computing subgraph hashes.
--dump_object_pool_link_data     Dump object pool link data as a binary file
--dump_blobs                     Dump the four snapshot regions as a single concatenated blob.
                                 Used by Shorebird's patch tool for avoiding Mach-O/ELF differences.
--dump_object_pool               Dump the object pool as JSON for debugging.
--dump_class_table               Dump the class table as JSON for debugging.
--disassemble                    Include disassembly in the JSON output. Off by default.
```

aot_tools 另外还传了 `--compute_dd_table=`、`--dd_caller_links=`、`--dd_max_bytes=`、
`--dd_table_data=`、`--compute_dd_slot_mapping=`、`--dd_function_identity=`（未出现在 help 中）。

### 1.5 核心机制：CPU / Simulator 双执行

`Linker` 的数据模型是 `Mapping { cpuOffset, simOffset }`，统计字段叫 `simToCpu`，成功日志是：

```
[Linker Success]: Running {N}% of code on CPU.
```

`shorebird_cli` 在 `linkPercentage < 90` 时告警（`patcher.dart`）：

> `shorebird patch` was only able to share X% of Dart code with the released app.
> This is unexpected, and means **the application may execute slower than expected after patching**.

**iOS 真机 arm64 引擎切片**（`Flutter.xcframework/ios-arm64/Flutter.framework/Flutter`，Mach-O arm64）
中包含：

```
../../flutter/third_party/dart/runtime/vm/simulator_arm64.cc     ← arm64 解释器，编进了真机引擎
../../flutter/third_party/dart/runtime/vm/shorebird/wrapper.cc
../../flutter/shell/common/shorebird/{shorebird,snapshots_data_handle}.cc
../../flutter/runtime/shorebird/patch_cache.cc

CPUToSimulator is_resuming: true/false
SimulatorToCPU
TransitionDartToSimulatorIfNeeded
Simulator::Call / Simulator::CallWithCpuState / ResumeOnSimulator
SimulatorCallToRuntime / SimulatorEnterSafepoint / SimulatorExitSafepoint
SimulatorCallNativeThroughSafepoint / SimulatorCallAutoScopeNative
SimulatorCallBootstrapNative / SimulatorCallNoScopeNative
CallSimulatorFromFfiTrampoline / CallClangCodeWithSimulatorArgs
"Has shorebird base instructions table: %s"
".vmcode"  "dlc.vmcode"  "WrongMagic"  "WrongVersion"
```

**结论**：patch 是一份**完整的新 AOT snapshot**，其 arm64 指令由 VM 内置的 `Simulator` 解释执行
——因此不需要 `PROT_EXEC`，天然绕过 iOS W^X。LinkTable 把 subgraph hash 与 base 相同的函数
从 simOffset 映射到 cpuOffset，运行时经 `SimulatorToCPU` 跳回原生代码全速执行。
`link_percentage` 就是走原生的代码比例；未链接上的部分被解释执行，所以慢。

对可行性关键的一点：**`simulator_arm64.cc` 是上游 Dart 本来就有的**
（`/Users/Cruz/dart/sdk/runtime/vm/simulator_arm64.cc`）。Shorebird 的工作量在于把它编进 arm64
真机构建，并加了 CPU↔Simulator 双向转换层与 base instructions table。方案 A 不是从零写解释器。

### 1.6 link 的流水线形状

从 `LinkCommand.run` 的字符串序列还原：

```
_generateOptimizedPatchSnapshot(base.aot, patch.aot, debugInfoDir)
  ├─ ct.aot              ← 只加 class table link data
  ├─ preDdOptimized.aot  ← 再加 object pool / dispatch table / field table link data
  ├─ ddOnly.aot          ← 只加 DD slot mapping
  └─ optimized.aot       ← 全部
analyze_snapshot --shorebird → base.analyze_snapshot.json / patch.analyze_snapshot.json
  ↓ 若 VM section 不一致则直接失败："base and patch snapshots have differing VM sections"
Linker: baseHashesToCodes × patchHashesToCodes → mappings → LinkTable
validateLinkTable / validatePerfectTable
_writeVmCodeFile: padToAlignment(LinkTable, pageSize) ++ optimizedPatch bytes
  → "LinkTable (padded) size: N bytes" / "wrote vmcode file to ..."
```

`--dump-debug-info` 会把上述四段中间快照 + 各类 dump 全部落盘。**这是整个取证的杠杆点**：
逐段差分四个 `.aot`，就能把每个 `--base_*_link_data` flag 的单独效果分离出来。

### 1.7 数据模型（字段名，来自 dill 字符串表）

```dart
class Code {                    // JSON key
  name, offset, size            //
  selfHash                      // self_hash
  subgraphHash                  // subgraph_hash / op_subgraph_hash
  selfPpIndices                 // self_pp
  subgraphPpIndices             // subgraph_pp
  selfSelectorOffsets           // self_selectors
  subgraphSelectorOffsets       // subgraph_selectors
  selfFieldTableOffsets         // self_field_table
  subgraphFieldTableOffsets     // subgraph_field_table
  disassembly, index_in_entries
}
class Mapping { cpuOffset; simOffset; }
class LinkTable { totalLength; bytesToAdd; }      // ByteWriter.addInt32
class JsonSnapshotData {
  vm_data_length, vm_data_hash,
  adjusted_vm_instructions_length, adjusted_vm_instructions_hash,
  vm_instructions_length, vm_instructions_hash, snapshot_version
}
enum Reason { added, unmatchedSelf, unmatchedChild }   // 未链接原因
class LinkStats {
  classesAdded, fieldsAdded, selectorsAdded, objectsAdded, totalObjects,
  objectsBackfilled, backFillPercentage, missingObjectPoolMappings,
  unlinkedSources, unlinkedCallersBySubgraphHash
}
```

LinkTable 的校验错误信息（说明它按 sim offset 有序遍历）：

```
Mismatched lengths: X vs Y
Mismatched offsets for sim offset N
Unexpected mapping for sim offset N
Missing mapping for sim offset N
```

`code_graph.dart` 中引用了 Floyd–Warshall 与 Tarjan SCC 的维基链接 → subgraph hash 建立在调用图
强连通分量之上。

### 1.8 环境已就绪（可离线复现）

| 组件 | 本地路径 |
|------|---------|
| Shorebird fork gen_snapshot（iOS arm64 目标） | `~/.shorebird/bin/cache/flutter/<rev>/bin/cache/artifacts/engine/ios-release/gen_snapshot_arm64` |
| Shorebird fork analyze_snapshot | 同目录 `analyze_snapshot_arm64` |
| aot_tools | `~/.shorebird/bin/cache/artifacts/aot-tools/<rev>/aot-tools.dill` |
| 可执行 Dart 3.12.2 | `~/.shorebird/bin/cache/flutter/<rev>/bin/dart` |
| shorebird CLI + 已登录凭据 | `~/.shorebird/bin/shorebird`，`~/Library/Application Support/shorebird/credentials.json` |
| 已注册测试 app | `spikes/shorebird_test/shorebird.yaml`（app_id 已有） |

`aot_tools link` 可以**完全离线、脱离 shorebird 账号**直接驱动：它只需要 base.aot、patch.aot、
两个 fork 二进制、patch 的 `.dill`。

---

## 2. Phase 2.0 目标

用 Shorebird 自己的二进制产出一套 ground truth，把 5 个未知量从"字符串表推断"变成"字节级实测"，
并据此给出 A/B 决策。

### 2.1 要锁死的 5 个未知量

| # | 未知量 | 为什么必须实测 | 取证手段 |
|---|-------|--------------|---------|
| **U1** | `.vmcode` 文件布局：magic、version、LinkTable 编码、pageSize 对齐 | 引擎里有 `WrongMagic`/`WrongVersion`，说明有头部；我们自己的 updater 要么复用要么自定义，先得知道对方长什么样 | 解析实产 `out.vmcode` 头部，与 `link_table.txt` 对照 |
| **U2** | LinkTable 条目编码，simOffset / cpuOffset 的基准点（section 起始？instructions blob 起始？） | 这是运行时跳转正确性的根 | `writeLinkTableDiagnostics` 输出 + 二进制对照 |
| **U3** | `self_hash` / `subgraph_hash` 的输入构成（`--no_pp_hash` 说明 PP offset 默认参与） | 决定"改一个字符串常量会不会导致大面积 unlink" | 三组受控改动，观察 hash 变化面 |
| **U4** | `ct.link` / `op.link` / `dt.link` / `ft.link` 的二进制格式 | 这是 fork gen_snapshot 的**输入契约**；方案 A 与 B 都要自己生成它 | `--dump_object_pool_link_data` + `--print_*_link_info_to` 直接 dump |
| **U5** | DD table 的语义与在 link 中的作用 | 二进制里有 `DD VERIFY FAIL … would SIGSEGV at PC 0 on the first indirect call`，说明它直接关系到补丁能否不崩 | `--print_dd_resolution_to` TSV + `preDdOptimized.aot` vs `ddOnly.aot` 差分 |

关于 U5 的已知线索（gen_snapshot 二进制字符串）：

```
DD table: %ld slots, %ld retained, %ld rewritten, %ld unrewritten-null filled with sentinel,
          %ld rewritten-null missing
DD resolution: %ld resolved, %ld preserved (%ld would-have-flipped), %ld carried
               (%ld refreshed, %ld dropped-stale), %ld dropped (empty_tally=... )
DD VERIFY FAIL: rewritten slot %ld >= table_size %ld
DD VERIFY FAIL: rewritten slot %ld is NULL
DD VERIFY: ... The rewriter emitted LDR+BLR through these slots but the resolver populated
           no target; shipping this snapshot would SIGSEGV at PC 0 on the first indirect call
```

初判：DD 是一张间接调用跳转表（rewriter 把直调改写为经 DD slot 的 `LDR+BLR`），linker 需要在
base/patch 之间保持 slot 身份稳定。取证时须验证这个初判。

### 2.2 差分矩阵

四段中间快照两两差分，把每组 flag 的效果分离出来：

| 差分对 | 分离出的效果 |
|--------|-------------|
| `patch.aot` → `ct.aot` | class table 对齐（cid 稳定化）单独的效果 |
| `ct.aot` → `preDdOptimized.aot` | object pool + dispatch table + field table 对齐的效果 |
| `preDdOptimized.aot` → `ddOnly.aot` | DD slot mapping 的效果 |
| `ddOnly.aot` → `optimized.aot` | 剩余合并步骤 |

每一档都记录：字节差异量、bidiff+zstd 后大小、link_percentage、LinkStats 各计数。

### 2.3 受控样本

同一个最小 Dart 程序的三组改动，覆盖 Phase 1 已知的痛点与未知面：

| 样本 | 改动 | 关注点 |
|------|------|--------|
| S1 | 改一个字符串常量的**内容且等长** | 纯对象池内容变化，指令不变 |
| S2 | 改一个字符串常量的**长度** | Phase 1 观测到 228K 字节重排的原始场景 |
| S3 | 改一个函数体（指令变化） | Phase 1 明确不支持的场景；观察 Shorebird 如何处理 |
| S4 | 新增一个函数 + 一个类 | `classesAdded` / `objectsAdded` / `Reason.added` 路径 |

S1/S2 用于对照 Phase 1 的实测数据；S3/S4 用于验证 1.5 节的架构推断。

---

## 3. 交付物

1. **`spikes/b_route_phase2_groundtruth/`**
   - `run.sh`：一条命令从零跑完全部样本，输出到 `out/`
   - `parse_vmcode.py`：`.vmcode` 头部 + LinkTable 解析器（U1/U2 的可执行形式）
   - `parse_link_data.py`：`ct.link` / `op.link` 等格式解析器（U4）
   - `out/`：全部 debug bundle 与中间快照（**不入 git**，`.gitignore` 排除）
2. **`spikes/b_route_phase2_groundtruth/GROUND_TRUTH.md`**：U1–U5 的实测规格，每条附复现命令
3. **`docs/superpowers/specs/2026-08-07-b-route-phase2-ab-decision.md`**：A/B 决策报告

决策报告必须回答：

- 方案 A（对齐全架构）要改我们的 X1 引擎哪些地方、工作量分解到周
- 方案 B（只做对象池对齐、保留 data-only 约束）的能力上限，用 S1–S4 的实测数据说明它覆盖/不覆盖什么
- 在**不**拿到 Shorebird 那份 `shorebird/wrapper.cc` 的前提下，A 是否可行；如可行，缺口清单
- 推荐项与理由

---

## 4. 非目标

明确**不做**，以免 spike 膨胀：

- 不实现 linker（A 或 B 的任何一方）
- 不修改我们的 Flutter engine / X1 引擎
- 不修改 `tools/updater/`、`tools/patch_builder/`、`tools/patch_server/`
- 不追求与 Shorebird 的 `.vmcode` 格式二进制兼容（我们是私有部署，格式可以自定；取证是为了理解，不是为了兼容）
- 不做真机运行验证（Phase 2.0 全部在 Mac 上完成）

---

## 5. 风险与应对

| 风险 | 应对 |
|------|------|
| `aot_tools compile` 需要 `vm_platform.dill` / `gen_kernel`，路径不明 | 先跑 `aot_tools compile --help` 实探；退路是直接用 `gen_kernel_aot.dart.snapshot` 手工产 `.dill`，再用 fork gen_snapshot 出 `.aot` |
| fork gen_snapshot 是 iOS arm64 目标，宿主为 x86_64 universal | 已确认是 universal binary（x86_64 + arm64），Rosetta 或原生均可跑；`--target-os ios` 明确指定 |
| 最小 Dart 样本可能触发不了 DD table（需要足够的间接调用） | S4 显式构造虚调用 / tear-off；若仍不触发，退到 `shorebird_test` 的 Flutter 样本 |
| `--dump-debug-info` 的产物体积大 | 输出目录进 `.gitignore`，只把解析后的规格写进 `GROUND_TRUTH.md` |
| Shorebird 二进制版本与我们的 X1 引擎 Dart 版本不同，结论不可直接外推 | 在 `GROUND_TRUTH.md` 中记录 `snapshot_version` 与两侧 Dart 版本；凡是版本相关的结论显式标注 |

---

## 6. 验收标准

Phase 2.0 完成的判定：

1. `run.sh` 能在干净环境一次跑通，产出 S1–S4 四组完整 debug bundle
2. `parse_vmcode.py` 能解析出实产 `out.vmcode` 的头部字段与全部 LinkTable 条目，
   条目数与 `link_table.txt` 一致，且 sim offset 单调递增校验通过
3. U1–U5 每一项在 `GROUND_TRUTH.md` 中有实测结论 + 复现命令；**推测必须显式标注为推测**
4. 四段中间快照的差分矩阵有完整数据（字节差异 / bidiff 大小 / link_percentage / LinkStats）
5. A/B 决策报告给出明确推荐，且推荐建立在实测数据而非推断之上

第 3 条的"绝不静默"要求沿用 `spikes/gate2_linker/PRODUCTION_LINKER_SPEC.md` R8 的既定纪律：
解析失败、格式失配、样本没触发目标代码路径，一律硬失败或显式告警，不允许输出"好看的 0"。
