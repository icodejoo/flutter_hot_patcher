---
name: project-b-route-phase2
description: B-route Phase 2 — 取证 spike 已完成，五个未知量破解四个，A/B 决策为走方案 A（对齐 Shorebird 全架构）
metadata:
  type: project
---

## 决策已定（2026-08-07）：走方案 A

`docs/superpowers/specs/2026-08-07-b-route-phase2-ab-decision.md`

**理由**：能力差距是决定性的。方案 B（data-only + 对象池对齐）永远改不了函数体，
而修 bug 基本都要改函数体。方案 A 改函数体只要 **3.1KB**，与改常量的 2.9KB 同一量级。
方案 B 的原定价值主张（"diff 从 300KB 降到几十字节"）**已被实测推翻** —— 那两个数都没实测过；
Shorebird 自己在 998KB 快照上改等长常量也是 2,881 字节。

**性能风险已降级，A1 可以直接开始。** 补测对称 link_percentage 后：
变长常量 100.00%、函数体改动 **99.84%**、新增类 93.38%（全部落在 Shorebird 的 >90% 生产区间）。
改一个函数体只有那个函数本身走解释执行，占全部代码 0.16% —— 不是"整个 app 变慢"，
而是"被改的那个函数变慢"。残留风险收敛为"若 patch 的恰好是热点函数"，
属可评估可规避的工程权衡，不是否决项。

**Simulator 性能数在本机测不了（真阻断，别再试）**：上游 `USING_SIMULATOR` 只在
`TARGET_ARCH != HOST_ARCH` 时定义；`tools/build.py -a simarm64` 在 arm64 宿主上被解析成
host==target==arm64，产出原生构建；`ARCH_FAMILY` 里没有 `simarm64_arm64` 这个配置项，
要 `simulator_arm64` 只能用 x64 宿主；且 `/Users/Cruz/dart/sdk` 的 checkout 缺
`third_party/protobuf`，gn 直接失败。
**推荐测法**：别搭合成 benchmark，直接 `shorebird release macos` + `shorebird patch macos`
改一个热点循环测前后比值——用 Shorebird 生产引擎端到端测，且 macOS 绕开 iOS 签名/MDM 全套麻烦。
该步会在 Shorebird 服务器上创建真实 release/patch，属对外动作，需用户明确同意后才执行。

**方案 A 唯一没有开源参照的部分**：`runtime/vm/shorebird/wrapper.cc` 的 CPU↔Simulator 双向切换
（`TransitionDartToSimulatorIfNeeded` / `CPUToSimulator` / `SimulatorToCPU` /
`CallSimulatorFromFfiTrampoline`）。其余全部有上游代码或已被 spike 破解。
`simulator_arm64.cc` 本身是上游自带的 3,954 行，只是 `USING_SIMULATOR` 在
`TARGET_ARCH == HOST_ARCH` 时不定义（`runtime/platform/globals.h:369`），真机构建把它编译掉了。

**2026-08-07 重大修正：此前记录的 Phase 2 前提是错的。**

旧前提（已废弃）："Phase 2 = 消除对象池重排，把 diff 从 ~300KB 降到几十字节，Option A 2-4 周 / Option B 4-8 周"。
基于错误的架构理解，工作量估算不可用。

**Shorebird linker 的真实架构（已取证）：**

patch 是一份**完整的新 AOT snapshot**，其 arm64 指令由 VM 内置的 `Simulator` 解释执行 —— 因此不需要
`PROT_EXEC`，天然绕过 iOS W^X。LinkTable 把 subgraph hash 与 base 相同的函数从 simOffset 映射到
cpuOffset，运行时经 `SimulatorToCPU` 跳回原生代码全速执行。`link_percentage` 就是走原生的比例，
低于 90% Shorebird CLI 会告警"应用会变慢"。对象池/类表/字段表对齐只是让 hash 能匹配上的**手段**，不是目的。

关键可行性事实：`simulator_arm64.cc` 是**上游 Dart 本来就有的**（`/Users/Cruz/dart/sdk/runtime/vm/`），
Shorebird 只是把它编进 arm64 真机构建并加了 CPU↔Simulator 转换层。不是从零写解释器。

**取证材料位置（全部可离线复现）：**
- `~/.shorebird/packages/shorebird_cli/` — CLI 全源码，含 `executables/aot_tools.dart`
- `~/.shorebird/bin/cache/artifacts/aot-tools/*/aot-tools.dill` — `strings -n 100` 可读出全部标识符
- `~/.shorebird/bin/cache/flutter/*/bin/cache/artifacts/engine/ios-release/` — fork 的
  `gen_snapshot_arm64` / `analyze_snapshot_arm64` / `Flutter.xcframework`
- `/Users/Cruz/dart/sdk` — 上游对照，用于判定哪些 flag 是 Shorebird 私有

## 已实测破解（2026-08-07 取证 spike，`spikes/b_route_phase2_groundtruth/`）

**`.vmcode` 文件格式（U1/U2，已双向验证）**
```
[uint32 LE 映射数 N]
[N × (uint32 LE sim_offset, uint32 LE cpu_offset)]   # sim=patch 侧偏移, cpu=base 侧偏移
[补零至 16384 字节]
[optimized patch 快照，ELF，与 <sample>.optimized.aot 逐字节相同]
```
- **没有 magic / version 字段**。引擎里的 `WrongMagic`/`WrongVersion` 属于别的结构。
- 二进制解出的 (sim,cpu) 集合与 `link_table.txt` 逐条相等。
- 对齐常量 8192 还是 16384 暂不可区分（样本太小），已排除 4096。

**linker 精度（重要，纠正了一次误判）**
- 逐函数 subgraph hash **精确工作**：改 `kTag` 只让用到它的 `main` 失配，未动过的
  `Greeter.greet` / `makeGreeters` / 分配桩全部链接成功。
- 本 harness 上 link_percentage 只有 ~42%，但 529 个未链接的**全是 Dart SDK 平台函数**，
  平均 363 字节/个（已链接的平均 132 字节/个）—— 函数越大、引用对象池槽位越多越易失配。
  这把"对象池对齐"的价值量化了。
- 注意边界：我们的 base 与 patch 是两个独立从零构建的程序，不等同于 Shorebird 真实
  release→patch 流程，42% 不代表其生产水平。

**工具链踩坑**
- `gen_kernel` 必须加 `--target=flutter`（Shorebird 的 platform dill 是 flutter target），否则崩在
  `DillLoader.loadExtraRequiredLibraries`。
- `.ct.link` / `.ft.link` / `.dt.link` 必须在最初构建 `.aot` 时用
  `--print_{class,field,dispatch}_table_link_info_to=` 一并产出；link 阶段补不出来。
- `analyze_snapshot` 必须带 `--shorebird`，否则是另一种 JSON 格式。
- gen_snapshot 字节可复现，测到的差异都是真信号。

**Why:** 在错误架构前提下选路线，选哪条都不对；先取证再决策。

**How to apply:** 下一步执行 Phase 2.0 取证 spike，完成后才做 A/B 决策。
- 设计：`docs/superpowers/specs/2026-08-07-b-route-phase2-groundtruth-design.md`
- 计划：`docs/superpowers/plans/2026-08-07-b-route-phase2-groundtruth.md`（10 tasks）
- 产出：`spikes/b_route_phase2_groundtruth/GROUND_TRUTH.md` + A/B 决策报告

相关：[[project-m4-m5-progress]]、[[project-shorebird-alignment]]、[[project-x1-engine-build]]
