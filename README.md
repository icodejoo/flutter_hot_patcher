# flutter_hot_patcher

自研 Flutter 逐函数热更新（Code Push）方案，目标覆盖 iOS + Android，核心是一套
**逐函数差分替换 + 编译期约束的 linker**，配合官方 Dart 字节码解释器实现 iOS 端合规热更。

A self-developed Flutter code-push solution targeting iOS + Android. Its core is a
**function-level differential linker with compile-time constraints**, paired with Dart's
official bytecode interpreter to enable App-Store-compliant hot updates on iOS.

## 为什么做这个 / Why

- Shorebird 是目前唯一成熟的 Flutter iOS 热更方案，但**闭源、不支持私有化部署，其 ToS 明确禁止自托管商用**。
- 市面无成熟的可私有化部署替代品；开源方案（如 flutter_patcher）仅支持 Android 整包 .so 替换，无差分、无 iOS。
- 我们需要**数据自主可控、可私有部署**的热更能力。

## 技术定位 / Positioning

- **不使用任何第三方闭源产物**。全部基于 Dart/Flutter 官方开源代码（BSD）自研，能力定位对齐 Shorebird。
- 终局形态：维护一对魔改的 **Dart VM fork + Flutter Engine fork**，供自有 App 使用。
- 关键复用：Dart 官方 `runtime/vm/interpreter.cc`（`--dart-dynamic-modules` 开关）+ `dart2bytecode` 编译器，均为 BSD，解释器无需自研。
- 真正自研部分（唯一无公开先例的黑盒）：**逐函数替换 + 编译期约束的 linker**。

## 当前阶段 / Current Phase

**Gate 1 桌面 x64 + Android arm64 真机（V1-V5）已全部 PASS**，Gate 2 linker 可行性 spike 级
验证（大样本精确度、多 agent 评审、生产需求排期）已完成。**唯一剩下的、还可能整体推翻方案的
验证点是 Gate 1 阶段 B：iOS 真机 W^X 复验**——需要 Mac，是当前的头号任务。

**刚接手项目（尤其是从 Windows/WSL2 移交到 Mac）先读 [MAC_HANDOFF.md](MAC_HANDOFF.md)**，
里面有锁定的 dart-sdk/Flutter Engine commit、`.gclient` 配置技巧等不在 git 历史里、只存在于
上一台机器文件系统里的关键信息。

## 文档 / Docs

- [MAC_HANDOFF.md](MAC_HANDOFF.md) — **Mac 交接清单，接手项目先看这个**
- [docs/PRD.md](docs/PRD.md) — 产品需求文档
- [docs/SPEC.md](docs/SPEC.md) — 技术规格与架构
- [docs/PLAN.md](docs/PLAN.md) — 分阶段实施计划（Gate 制）
- [spikes/gate1_mixed_execution/GATE1_REPORT.md](spikes/gate1_mixed_execution/GATE1_REPORT.md) — Gate1 完整证据链
- [spikes/gate2_linker/REVIEW_diff_linker.md](spikes/gate2_linker/REVIEW_diff_linker.md) — Gate2 diff_linker 多 agent 评审
- [spikes/gate2_linker/PRODUCTION_LINKER_SPEC.md](spikes/gate2_linker/PRODUCTION_LINKER_SPEC.md) — 生产 linker 需求（R1-R9）

## 目录 / Layout

```
flutter_hot_patcher/
├── docs/           # PRD / SPEC / PLAN
├── spikes/         # 验证性实验代码（Gate 1 从这里开始）
└── README.md
```

## 法律边界 / Legal Boundary

全程仅使用 Dart/Flutter 官方 BSD 开源代码自研，能力范围对齐 Shorebird 已开源
（MIT/Apache/BSD）的组件；不接触、不使用 Shorebird 闭源二进制或其私有 VM fork。
立项前建议法务对整体路线做一次确认。
