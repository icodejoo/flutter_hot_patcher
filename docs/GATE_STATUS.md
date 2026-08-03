# Gate 进度总览

版本 v1.1 · 2026-08-03  
状态：**Gate 1 ✅ PASS（含 iOS 真机） · Gate 2 ✅ PASS · M3 ✅ PASS · 正式研发前置条件全部满足**

---

## 快速索引

| Gate | 结论 | 报告 |
|------|------|------|
| Gate 1 桌面（V1-V5） | ✅ PASS | [`GATE1_REPORT.md`](../spikes/gate1_mixed_execution/GATE1_REPORT.md) |
| Gate 1b Android arm64 真机 | ✅ PASS | [`android_arm64/NOTES.md`](../spikes/gate1_mixed_execution/android_arm64/NOTES.md) |
| Gate 1 iOS arm64 机制验证 + 真机部署 | ✅ PASS（V2 机制 + iPhone 14 真机，M3 完成） | [`ios_arm64/e2e_v2_hotpatch/NOTES.md`](../spikes/gate1_mixed_execution/ios_arm64/e2e_v2_hotpatch/NOTES.md) |
| Gate 1 iOS Simulator arm64 | ✅ PASS | [`ios_arm64/e2e_v2_hotpatch/README.md`](../spikes/gate1_mixed_execution/ios_arm64/e2e_v2_hotpatch/README.md) |
| Gate 2 V6-V10 + 精确度 | ✅ PASS | [`gate2_linker/README.md`](../spikes/gate2_linker/README.md) |

---

## Gate 1 — 混合执行 ABI（难点 X）

### 命题

让基线里已 AOT 编译的**既有**调用点，运行时走到字节码版本的新函数，且 ABI（异常/GC/并发）正确。

### 验证矩阵

| 用例 | 内容 | 桌面 x64 | Android arm64 | iOS arm64 |
|------|------|:---------:|:-------------:|:---------:|
| V1 | 静态直调替换（运行时改写调用指令） | ✅ | ✅ | ⛔ W^X 封堵（用 V2 替代） |
| V2 | 虚调用/闭包调用（dispatch table / entry_point 字段） | ✅ | ✅（零改动） | ✅ 真机 iPhone 14 PASS |
| V3 | 异常跨混合栈正确穿透 | ✅ | ✅ | — |
| V4 | GC 不破坏混合栈帧 | ✅ | ✅ | — |
| V5 | 高频 + 并发竞争（1.6 亿次调用） | ✅ | ✅ | — |

### W^X 结论

`redirectClosureEntryPoint`（V2）写的是 Dart 堆上 `Closure` 对象的 `entry_point` 字段（**数据页**，非可执行页），W^X 不约束堆写入。iPhone 14 真机 arm64 实测 PASS，含 crash-guard 回滚全流程验证。

### 重要约束（划定边界，不是失败）

- 官方 `package:dynamic_modules` **按设计不支持替换既有函数**（additive only），我们的机制完全绕开它。
- 补丁字节码只能引用宿主 AOT 编译产物已保留的符号（闭世界树摇）——调用任意宿主 API 需通过 `dynamic_interface.yaml` 的 `callable` 声明。

---

## Gate 2 — 逐函数差分替换（难点 Y）

### 命题

基线全优化 AOT 编译下，linker 能否正确识别"受影响传递闭包"并转解释执行，使补丁行为与完整重编译版一致，且性能下降可接受。

### 验证结果

| 用例 | 内容 | 结论 |
|------|------|------|
| V6 | 去虚化路由：替换被去虚化直调的函数 | ✅ |
| V7 | 内联级联：替换被多处内联的函数，所有调用者转解释 | ✅ |
| V8 | 真实修复场景：行为与完整重编译版一致 | ✅ |
| V9 | 类字段布局变更：双层 PASS（linker + runtime） | ✅ |
| V10 | 性能：解释比例 0.1%，典型慢 1.7-14x，产品可接受 | ✅ |

### 差分精确度（大样本）

| 场景 | 函数数 | 漏判 | 误报 |
|------|--------|------|------|
| 纯 Dart 全类型（3125 函数，294 撞名） | — | 0 | 0 |
| Flutter widget + 完整框架（5797 函数） | widget 改动收敛 3 函数（0.1%） | 0 | 0 |

**关键发现**：闭包规模本身有界（个位数函数）；解释比例是**对齐精确度**的函数，不是闭包天然爆炸——CanonicalName 对齐（Kernel URI→类→成员）是命门，不是优化项。

### kernel_linker（R1-R9 全部满足）

`spikes/gate2_linker/tools/kernel_linker/` 实现了生产 linker 所需的全部 9 项功能需求。使用方法见 [`tools/kernel_linker/README.md`](../spikes/gate2_linker/tools/kernel_linker/README.md)。

---

## M3 — iOS 真机端到端 demo ✅ PASS

**iPhone 14 真机，三场景全部验证通过。**

| 场景 | 条件 | 结果 |
|------|------|------|
| 场景 1: 正常补丁生效 | patch_status = nil | `[M3] Dart result: PATCHED` ✅ |
| 场景 2: crash-guard 触发回滚 | patch_status = "loading" | `[M3] Dart result: ORIGINAL` ✅ |
| 场景 3: 回滚解除 | patch_status = nil（恢复） | `[M3] Dart result: PATCHED` ✅ |

详见 [`spikes/m3_ios_realdevice/RESULTS.md`](../spikes/m3_ios_realdevice/RESULTS.md)。

---

## 下一里程碑：M4（私有化闭环）

M3 已完成，可进入 M4：

| 里程碑 | 目标 | 状态 |
|--------|------|------|
| **M3** | 端到端 demo：一个真实 Bug，端上补丁生效、可回滚 | ✅ PASS |
| M4 | 私有化闭环：生成/签名/下发/回滚全私有部署 | 待启动 |
| M5 | 生产灰度：差分等价测试台 100% + 崩溃率达标 | 待启动 |

---

## 参考文档

- [`PRD.md`](PRD.md) — 产品需求
- [`SPEC.md`](SPEC.md) — 技术规格
- [`PLAN.md`](PLAN.md) — 分阶段计划（Gate 制）
- [`PATCH_DELIVERY_SPEC.md`](PATCH_DELIVERY_SPEC.md) — 补丁下发全链路设计
- [`../spikes/gate2_linker/PRODUCTION_LINKER_SPEC.md`](../spikes/gate2_linker/PRODUCTION_LINKER_SPEC.md) — 生产 linker 需求（R1-R9）
- [`../spikes/gate2_linker/PRECISION_REPORT.md`](../spikes/gate2_linker/PRECISION_REPORT.md) — 差分精确度量化报告
