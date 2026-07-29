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

- **不反编译、不使用 Shorebird 任何闭源产物**。全部基于 Dart/Flutter 官方开源代码（BSD）自研。
- 终局形态：维护一对魔改的 **Dart VM fork + Flutter Engine fork**，供自有 App 使用。
- 关键复用：Dart 官方 `runtime/vm/interpreter.cc`（`--dart-dynamic-modules` 开关）+ `dart2bytecode` 编译器，均为 BSD，解释器无需自研。
- 真正自研部分（唯一无公开先例的黑盒）：**逐函数替换 + 编译期约束的 linker**。

## 当前阶段 / Current Phase

**Gate 1 — 验证难点 X（混合执行 ABI 层）**：验证解释执行的函数与 AOT 机器码函数能否
在真机 iOS 上安全互操作（互相调用、异常穿透、GC 扫描）。这是整条路线的生死判定点。

## 文档 / Docs

- [docs/PRD.md](docs/PRD.md) — 产品需求文档
- [docs/SPEC.md](docs/SPEC.md) — 技术规格与架构
- [docs/PLAN.md](docs/PLAN.md) — 分阶段实施计划（Gate 制）

## 目录 / Layout

```
flutter_hot_patcher/
├── docs/           # PRD / SPEC / PLAN
├── spikes/         # 验证性实验代码（Gate 1 从这里开始）
└── README.md
```

## 法律边界 / Legal Boundary

全程仅使用 Dart/Flutter 官方 BSD 开源代码与 Shorebird 主动开源（MIT/Apache/BSD）仓库
**的设计思路参考**。不反编译 `aot-tools`、不接触 Shorebird 闭源二进制或其私有 VM fork。
思路相似不构成侵权（思想不受版权保护），但立项前建议法务对整体路线做一次确认。
