# Gate 1 Spike — 混合执行 ABI 验证

Mixed-mode execution ABI validation spike.

验证目标（对应 PLAN.md 的 Gate 1）：**已经 AOT 编译的既有调用点，能否在运行时被重定向到
解释执行、行为不同的新函数**（"替换"），同时验证混合栈的异常/GC（ABI）。这是整条 iOS
自研路线的生死判定点。

> **靶心更正**：不是验证"互操作"（新增字节码函数 ↔ AOT 互调）——官方 dynamic modules 本就支持，
> 验证它会假阳性通过。真正无先例的是**替换既有函数**。详见 `cases/v1_replace_existing_function/NOTES.md`。

## 验证用例

| ID | 名称 | 验证内容 |
|----|------|---------|
| V1 | **替换既有函数** | `g()->f()` 既有调用点被重定向到解释执行的 `f'`，行为变化可观测（最硬，先做） |
| V2 | 三种调用形态 | 静态直调/虚调用/闭包，产出"可重定向 vs 必须连带失效"边界矩阵 |
| V3 | 异常穿透 | 异常跨两种栈帧抛出/捕获，finally/rethrow 正确 |
| V4 | GC 正确性 | 混合栈存活期间触发 GC，两种帧引用都被扫描 |
| V5 | 稳定性 | 高频循环压测，无泄漏/偶发崩溃 |

## 环境前提

本机为 **Windows_x64**（Dart SDK 3.12.2 stable）。但：

- 难点 X 的**最终目标平台是 iOS(arm64)**，其 W^X + 无 JIT 限制是 iOS 特有的，必须在
  **macOS 上交叉编译 + iOS 真机**验证才算数。Windows/桌面平台验证只能作为**机制预验证**
  （证明解释器与 AOT 能互操作），不能替代 iOS 真机结论。
- 官方解释器 `interpreter.cc` 需从 **dart-lang/sdk 源码用 `--dart-dynamic-modules` 构建**，
  stable SDK 不含。本机缺 `ninja`/`python3` 等构建依赖（见下）。

## 环境搭建步骤（M0）

> 目标：先在**任意可用平台**跑通官方 `pkg/dynamic_modules/example`，确认解释器 +
> `dart2bytecode` 工具链可用；再迁移到 macOS/iOS 做真机验证。

1. **准备构建依赖**（本机当前缺失，需安装）：
   - `depot_tools`（含 `gclient`、`ninja`、`gn`）
   - `python3`（构建脚本依赖；本机仅有 `python` 3.14）
   - macOS 侧还需 Xcode（iOS 交叉编译与真机部署）

2. **拉取 Dart SDK 源码**：
   ```
   mkdir dart-sdk && cd dart-sdk
   fetch dart          # depot_tools 提供
   ```

3. **构建带解释器的运行时**（关键：`--dart-dynamic-modules` 开关）：
   ```
   ./tools/build.py --mode release --arch x64 create_sdk
   # iOS: ./tools/build.py --os ios --arch arm64 ...（需 macOS + Xcode）
   # 具体 flag 名以官方 pkg/dynamic_modules/example/run.sh 为准
   ```

4. **跑通官方样例**，确认工具链可用：
   ```
   # 参考 dart-lang/sdk 的 pkg/dynamic_modules/example/run.sh
   # 它演示了 --dart-dynamic-modules 构建 + 用 dart2bytecode 编译动态模块 + 加载运行
   ```

## 目录

```
gate1_mixed_execution/
├── README.md              # 本文件
├── cases/
│   └── v1_replace_existing_function/   # V1: 替换既有函数（含 NOTES.md 机制探索）
├── vendor/                # dart-lang/sdk 等外部源码（git-ignored，本地拉取）
└── results/               # 各用例实测结论
```

## 当前状态

- [x] 骨架建立（V1 替换用例 + 机制探索 NOTES）
- [ ] M0：安装构建依赖（depot_tools / python3；iOS 复验需 macOS + Xcode）
- [ ] M0：拉取 dart-lang/sdk 并用 `--dart-dynamic-modules` 构建
- [ ] M0：桌面 arm64 跑通官方 `pkg/dynamic_modules/example`（工具链 + 互操作基线）
- [ ] V1：探索入口重定向机制 → 替换可观测生效（桌面 → iOS 真机）
- [ ] V2–V5
