# flutter_hot_patcher

自研 Flutter 逐函数热更新（Code Push）方案，目标覆盖 iOS + Android，核心是一套
**逐函数差分替换 + 编译期约束的 linker**，配合官方 Dart 字节码解释器实现 iOS 端合规热更。

A self-developed Flutter code-push solution targeting iOS + Android. Its core is a
**function-level differential linker with compile-time constraints**, paired with Dart's
official bytecode interpreter to enable App-Store-compliant hot updates on iOS.

## 为什么做这个 / Why

- Shorebird 是目前唯一成熟的 Flutter iOS 热更方案，但**闭源、不支持私有化部署，其 ToS 明确禁止自托管商用**。
- 市面无成熟的可私有化部署替代品；开源方案仅支持 Android 整包 `.so` 替换，无差分、无 iOS。
- 我们需要**数据自主可控、可私有化部署**的热更能力。

## 技术定位 / Positioning

- **不使用任何第三方闭源产物**。全部基于 Dart/Flutter 官方开源代码（BSD）自研，能力定位对齐 Shorebird。
- 终局形态：维护一对魔改的 **Dart VM fork + Flutter Engine fork**，供自有 App 使用。
- 关键复用：Dart 官方 `runtime/vm/interpreter.cc`（`--dart-dynamic-modules` 开关）+ `dart2bytecode` 编译器，均为 BSD，解释器无需自研。
- 真正自研部分（唯一无公开先例的黑盒）：**逐函数替换 + 编译期约束的 linker**。

## 当前状态 / Current Status

**Gate 1 ✅ PASS（桌面 x64 + Android arm64 真机 + iOS Simulator arm64）**  
**Gate 2 ✅ PASS（kernel_linker V1 R1-R9 全部满足，精确度 0% 漏判/误报）**  
**→ 正式研发前置条件全部满足，下一步：M3 端到端 demo**

详细进度见 [`docs/GATE_STATUS.md`](docs/GATE_STATUS.md)。

## 快速了解项目 / Where to Start

| 你的目的 | 先看这里 |
|----------|----------|
| 整体进度 / 结论速查 | [`docs/GATE_STATUS.md`](docs/GATE_STATUS.md) |
| 产品需求 | [`docs/PRD.md`](docs/PRD.md) |
| 技术规格与架构 | [`docs/SPEC.md`](docs/SPEC.md) |
| 分阶段计划（Gate 制） | [`docs/PLAN.md`](docs/PLAN.md) |
| 补丁下发全链路设计 | [`docs/PATCH_DELIVERY_SPEC.md`](docs/PATCH_DELIVERY_SPEC.md) |
| Gate 1 完整证据链 | [`spikes/gate1_mixed_execution/GATE1_REPORT.md`](spikes/gate1_mixed_execution/GATE1_REPORT.md) |
| iOS Sim V2-closure demo（可复现） | [`spikes/gate1_mixed_execution/ios_arm64/e2e_v2_hotpatch/README.md`](spikes/gate1_mixed_execution/ios_arm64/e2e_v2_hotpatch/README.md) |
| kernel_linker 使用文档 | [`spikes/gate2_linker/tools/kernel_linker/README.md`](spikes/gate2_linker/tools/kernel_linker/README.md) |
| Gate 2 差分精确度量化 | [`spikes/gate2_linker/PRECISION_REPORT.md`](spikes/gate2_linker/PRECISION_REPORT.md) |
| Mac 接手清单 | [`MAC_HANDOFF.md`](MAC_HANDOFF.md) |

## 目录 / Layout

```
flutter_hot_patcher/
├── docs/                          # PRD / SPEC / PLAN / GATE_STATUS / PATCH_DELIVERY_SPEC
├── spikes/
│   ├── gate1_mixed_execution/     # Gate 1：混合执行 ABI 验证（V1-V5 + iOS Sim）
│   │   ├── GATE1_REPORT.md        # Gate 1 完整证据链
│   │   ├── cases/                 # V1-V5 桌面用例
│   │   ├── android_arm64/         # Gate 1b：Android 真机复验
│   │   ├── ios_arm64/             # iOS arm64：机制验证 + Simulator demo
│   │   └── vm_patch/              # Dart VM 补丁（gate1_vm_patch.diff）
│   └── gate2_linker/              # Gate 2：kernel_linker + 精确度测试
│       ├── tools/kernel_linker/   # 生产 linker 原型（R1-R9）
│       ├── PRECISION_REPORT.md    # 精确度量化报告
│       └── PRODUCTION_LINKER_SPEC.md  # 生产需求规格
└── README.md
```

## 法律边界 / Legal Boundary

全程仅使用 Dart/Flutter 官方 BSD 开源代码自研，能力范围对齐 Shorebird 已开源（MIT/Apache/BSD）的组件；不接触、不使用 Shorebird 闭源二进制或其私有 VM fork。立项前建议法务对整体路线做一次确认。
