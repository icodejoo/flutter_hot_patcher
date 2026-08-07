---
name: project-b-route-phase2
description: B-route Phase 2 — Shorebird linker 真实架构已取证确认，Phase 2.0 取证 spike 的 spec+plan 已就绪
metadata:
  type: project
---

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

**Why:** 在错误架构前提下选路线，选哪条都不对；先取证再决策。

**How to apply:** 下一步执行 Phase 2.0 取证 spike，完成后才做 A/B 决策。
- 设计：`docs/superpowers/specs/2026-08-07-b-route-phase2-groundtruth-design.md`
- 计划：`docs/superpowers/plans/2026-08-07-b-route-phase2-groundtruth.md`（10 tasks）
- 产出：`spikes/b_route_phase2_groundtruth/GROUND_TRUTH.md` + A/B 决策报告

相关：[[project-m4-m5-progress]]、[[project-shorebird-alignment]]、[[project-x1-engine-build]]
