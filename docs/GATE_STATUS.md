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

---

## B-route Phase 2 — Simulator 架构（方案 A）进度（2026-08-10/11）

### 已完成阶段

| 阶段 | 内容 | 状态 | 关键验证 |
|---|---|---|---|
| A1 | USING_SIMULATOR arm64 强制打开 | ✅ | dartaotruntime 72× 慢，结果 15530048 一致 |
| A2 | BLR 拦截 + InvokeWithTHR(THR,PP) | ✅ | ShorebirdSimToCpu_BasicCall PASS |
| A3 | fhp_analyze_snapshot ELF+SHA-1 | ✅ | 零错误链接 |
| A4 | .op.link 读取（GT 完全匹配） | ✅ | analyze_shorebird_with_op_link |
| A5 | BL 拦截（等效 DD 改写） | ✅ | A7 结果 9312480 验证 |
| A6 | fhp_linker（263 pytest PASS） | ✅ | 1052/1052 对比 aot_tools |
| A7 | dartaotruntime --shorebird-vmcode 端到端 | ✅ | compute 解释，其余原生，结果正确 |
| B1 | Flutter Engine iOS arm64 重建 | ✅ | ShorebirdSimToCpuCall in binary |
| B2 | analyze_snapshot --shorebird 等价 API | ✅ | Dart_DumpSnapshotInformationShorebirdAsJson，99.97% 链接率 |
| **B3** | **GC Safepoint + 异常传播加固** | **✅ 2026-08-10** | HasScheduledInterrupts + SimulatorSetjmpBuffer |
| **B4** | **iOS vmcode C API + 真机 B4 验证** | **✅ 2026-08-11 PASS** | `B4 vmcode link table: LOADED (3223 entries)` — iPhone 日志实证 |

### B4 真机验证日志（2026-08-11 实录）

```
[ViewController] B4 vmcode link table: LOADED (path=.../HotPatchDemo.app/vmcode_link.vmcode)
```

`fhp_shorebird_load_vmcode()` 在 iPhone 真机成功加载 3223 个 SimulatorToCPU 链接表条目。

### 当前剩余差距

| 差距 | 严重程度 |
|---|---|
| dart_run 全流程验证（需修复 snapshot 版本后重跑） | 下一步（bugfix 已提交 bdcfe67） |
| analyze_snapshot 独立二进制仅 Linux | 工程约束 |
| Simulator 进入开销（每次调用多一跳） | 性能差异，可接受 |
