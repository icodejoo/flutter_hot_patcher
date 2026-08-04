# Gate 进度总览

版本 v2.0 · 2026-08-04  
状态：**Gate 1 ✅ PASS · Gate 2 ✅ PASS · M3 ✅ PASS · M4 ✅ PASS · M5 ✅ PASS**

---

## 快速索引

| Gate / 里程碑 | 结论 | 报告 |
|------|------|------|
| Gate 1 桌面（V1-V5） | ✅ PASS | [`GATE1_REPORT.md`](../spikes/gate1_mixed_execution/GATE1_REPORT.md) |
| Gate 1b Android arm64 真机 | ✅ PASS | [`android_arm64/NOTES.md`](../spikes/gate1_mixed_execution/android_arm64/NOTES.md) |
| Gate 1 iOS arm64 机制验证 | ✅ PASS（V2 机制 + Sim + 真机） | [`ios_arm64/e2e_v2_hotpatch/NOTES.md`](../spikes/gate1_mixed_execution/ios_arm64/e2e_v2_hotpatch/NOTES.md) |
| Gate 2 V6-V10 + 精确度 | ✅ PASS | [`gate2_linker/README.md`](../spikes/gate2_linker/README.md) |
| **M3** iOS 真机端到端 demo | ✅ PASS | [`m3_ios_realdevice/RESULTS.md`](../spikes/m3_ios_realdevice/RESULTS.md) |
| **M4** 私有化闭环 | ✅ PASS | 见下文 |
| **M5** 生产灰度 | ✅ PASS | 见下文 |

---

## Gate 1 — 混合执行 ABI（难点 X）

### 验证矩阵

| 用例 | 内容 | 桌面 x64 | Android arm64 | iOS arm64 |
|------|------|:---------:|:-------------:|:---------:|
| V1 | 静态直调替换 | ✅ | ✅ | ⛔ W^X 封堵（用 V2 替代） |
| V2 | 虚调用/闭包调用（dispatch table / entry_point 字段） | ✅ | ✅（零改动） | ✅ Sim + 真机 PASS |
| V3 | 异常跨混合栈正确穿透 | ✅ | ✅ | — |
| V4 | GC 不破坏混合栈帧 | ✅ | ✅ | — |
| V5 | 高频 + 并发竞争（1.6 亿次调用） | ✅ | ✅ | — |

**W^X 结论**：`redirectClosureEntryPoint`（V2）写的是 Dart 堆上 `Closure` 对象的 `entry_point` 字段（**数据页**，非可执行页），W^X 不约束堆写入。iOS 真机实测 PASS。

---

## Gate 2 — 逐函数差分替换（难点 Y）

| 用例 | 内容 | 结论 |
|------|------|------|
| V6 | 去虚化路由 | ✅ |
| V7 | 内联级联 | ✅ |
| V8 | 真实修复场景 | ✅ |
| V9 | 类字段布局变更 | ✅ |
| V10 | 性能：解释比例 0.1%，典型慢 1.7-14x | ✅ |

**差分精确度**：纯 Dart 3125 函数 + Flutter widget 5797 函数，漏判 0，误报 0。

**kernel_linker（R1-R9）**：生产化版本在 `spikes/gate2_linker/tools/kernel_linker/`，输出 PATCH_DELIVERY_SPEC §1 格式 manifest。

---

## M3 — iOS 真机端到端 demo ✅ PASS

**iPhone 14 真机，三场景全部验证通过。**

| 场景 | 条件 | 结果 |
|------|------|------|
| 正常补丁生效 | 首次安装 | `Dart result: PATCHED` ✅ |
| crash-guard 回滚 | patch_status = "loading" | `Dart result: ORIGINAL` ✅ |
| 回滚解除 | 恢复 | `Dart result: PATCHED` ✅ |

**关键踩坑**：`dart:_internal` 被 gen_kernel 拒绝 → `@pragma('vm:external-name')`；bytecode closure 不能普通 dispatch → `Dart_LoadLibraryFromBytecode` + `Dart_Invoke`。

---

## M4 — 私有化闭环 ✅ PASS

| 子里程碑 | 状态 | 位置 |
|---------|------|------|
| 4-A kernel_linker 生产化 | ✅ | `spikes/gate2_linker/tools/kernel_linker/` |
| 4-B 补丁流水线（Ed25519 签名） | ✅ | `tools/patch_builder/` |
| 4-C Updater（Rust，16 tests） | ✅ | `tools/updater/` |
| 4-D 运行时集成（iOS app） | ✅ | `spikes/m3_ios_realdevice/HotPatchDemo/` |
| 4-E 私有服务端 | ✅ | `tools/patch_server/` |

**端到端流：** dart2bytecode → kernel_linker diff → patch_builder 签名 → patch_server 下发 → Updater 验证 → dart_harness 加载 → `Dart result: PATCHED`（iPhone 14 真机）

---

## M5 — 生产灰度 ✅ PASS

| 子里程碑 | 状态 | 位置 |
|---------|------|------|
| 5-A 差分等价测试台 | ✅ 4/4 checks PASS | `tools/patch_server/equivalence_tester.py` |
| 5-B 崩溃率监控 + 熔断撤包 | ✅ | `ViewController.m` + `tools/patch_server/withdraw.sh` |

---

## 参考文档

| 文档 | 说明 |
|------|------|
| [`PRD.md`](PRD.md) | 产品需求 |
| [`SPEC.md`](SPEC.md) | 技术规格与架构 |
| [`PLAN.md`](PLAN.md) | 分阶段计划（Gate 制） |
| [`PATCH_DELIVERY_SPEC.md`](PATCH_DELIVERY_SPEC.md) | 补丁下发全链路规格 |
| [`../spikes/gate2_linker/PRODUCTION_LINKER_SPEC.md`](../spikes/gate2_linker/PRODUCTION_LINKER_SPEC.md) | 生产 linker 需求（R1-R9） |
| [`../spikes/gate2_linker/PRECISION_REPORT.md`](../spikes/gate2_linker/PRECISION_REPORT.md) | 差分精确度量化报告 |
| [`../spikes/m3_ios_realdevice/RESULTS.md`](../spikes/m3_ios_realdevice/RESULTS.md) | M3 iOS 真机验证结果 |
| [`../docs/superpowers/specs/`](superpowers/specs/) | 4-A/4-B/4-C 设计规格 |
| [`../docs/superpowers/plans/`](superpowers/plans/) | 4-A/4-B/4-C 实施计划 |
