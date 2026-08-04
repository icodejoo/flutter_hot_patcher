# flutter_hot_patcher

自研 Flutter 逐函数热更新（Code Push）方案，目标覆盖 iOS + Android，核心是一套
**逐函数差分替换 + 编译期约束的 linker**，配合官方 Dart 字节码解释器实现 iOS 端合规热更。

A self-developed Flutter code-push solution targeting iOS + Android. Its core is a
**function-level differential linker with compile-time constraints**, paired with Dart's
official bytecode interpreter to enable App-Store-compliant hot updates on iOS.

## 当前状态 / Current Status

**Gate 1 ✅ PASS · Gate 2 ✅ PASS · M3 ✅ PASS · M4 ✅ PASS · M5 ✅ PASS**

完整私有化 Flutter 热更新系统已交付。完整进度见 [`docs/GATE_STATUS.md`](docs/GATE_STATUS.md)。

## 项目目录 / Layout

```
flutter_hot_patcher/
│
├── docs/                          # 设计文档
│   ├── PRD.md                     # 产品需求
│   ├── SPEC.md                    # 技术规格与架构
│   ├── PLAN.md                    # 分阶段计划（Gate 制）
│   ├── GATE_STATUS.md             # 当前进度总览（从这里开始）
│   ├── PATCH_DELIVERY_SPEC.md     # 补丁下发全链路规格
│   └── superpowers/
│       ├── specs/                 # 4-A/B/C 设计规格
│       └── plans/                 # 4-A/B/C 实施计划
│
├── spikes/
│   ├── gate1_mixed_execution/     # Gate 1：混合执行 ABI 验证（V1-V5 + iOS）
│   ├── gate2_linker/              # Gate 2：kernel_linker + 精确度测试
│   │   └── tools/kernel_linker/  # ★ 4-A 生产级 linker（Dart，R1-R9）
│   └── m3_ios_realdevice/        # ★ M3/M4-D iOS 真机 demo（Xcode App）
│
└── tools/
    ├── patch_builder/            # ★ 4-B 补丁流水线（Python，Ed25519 签名）
    ├── updater/                  # ★ 4-C Updater（Rust，boot-loop watchdog，C FFI）
    └── patch_server/             # ★ 4-E 私有服务端 + 5-A/B 测试台
```

## 快速了解项目 / Where to Start

| 你的目的 | 先看这里 |
|----------|----------|
| 整体进度 / 结论速查 | [`docs/GATE_STATUS.md`](docs/GATE_STATUS.md) |
| 产品需求 | [`docs/PRD.md`](docs/PRD.md) |
| 技术规格与架构 | [`docs/SPEC.md`](docs/SPEC.md) |
| 补丁下发全链路设计 | [`docs/PATCH_DELIVERY_SPEC.md`](docs/PATCH_DELIVERY_SPEC.md) |
| kernel_linker 使用 | [`spikes/gate2_linker/tools/kernel_linker/README.md`](spikes/gate2_linker/tools/kernel_linker/README.md) |
| iOS 真机 demo | [`spikes/m3_ios_realdevice/RESULTS.md`](spikes/m3_ios_realdevice/RESULTS.md) |
| Updater Rust 库 | [`tools/updater/`](tools/updater/) |
| 补丁打包工具 | [`tools/patch_builder/patch_builder.py`](tools/patch_builder/patch_builder.py) |
| 下发服务器 | [`tools/patch_server/patch_server.py`](tools/patch_server/patch_server.py) |
| 等价测试台 | [`tools/patch_server/equivalence_tester.py`](tools/patch_server/equivalence_tester.py) |

## 技术定位 / Positioning

- **不使用任何第三方闭源产物**。全部基于 Dart/Flutter 官方开源代码（BSD）自研，能力定位对齐 Shorebird。
- Dart SDK 锁定版本：`1aa7d7321fb`（2026-05-07），见 [`MAC_HANDOFF.md`](MAC_HANDOFF.md)。
- 核心创新：逐函数差分 linker（kernel_linker，R1-R9）+ 运行时字节码加载（`Dart_LoadLibraryFromBytecode`）。

## 法律边界 / Legal Boundary

全程仅使用 Dart/Flutter 官方 BSD 开源代码自研，能力范围对齐 Shorebird 已开源（MIT/Apache/BSD）的组件；不接触、不使用 Shorebird 闭源二进制或其私有 VM fork。
