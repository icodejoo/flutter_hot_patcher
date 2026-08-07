---
name: project-ios-verification
description: iOS 真机验证现状与阻塞原因 — 2026-08-06
metadata:
  type: project
---

## iOS 真机验证进度

**目标：** 在 iPhone 14（device ID: 00008110-000E583836F3601E，QA-iPhone-YPVYHY2D90）上验证 dart_dynamic_modules 能力。

**X1 Mac 端验证：✅ 完成**
```
loadModuleFromBytes SUCCESS! Result: Closure: () => void
dart_dynamic_modules IS FULLY WORKING (host_release dart)
```
工具链：`~/engine_ios/src/out/host_release/dartaotruntime` + `dart2bytecode.dart.snapshot`

**iOS 真机验证：⛔ 被 mprotect 阻断**

错误：
```
mprotect failed: 13 (Permission denied)
dart::StubCode::Init()
```

根因：dart_dynamic_modules=true 启用了 JIT stub 生成基础设施，iOS 不允许 mprotect(PROT_EXEC) 无 JIT entitlement。

**转向：** Shorebird 路线（AOT + pointer-swap，数据页写入，W^X 合规）。

**已验证的 Shorebird 机制：**
- 内嵌 Rust updater（shorebirdtech/updater MIT）
- AOT snapshot binary diff → pointer table 更新
- 不需要 JIT，写 Dart 堆数据页

**iOS Flutter 版本兼容问题（仅针对 dart_dynamic_modules 路线）：**
- 引擎 dart revision: 37bbc285d8（Dart 3.7.0-260.0.dev, Dec 17, 2024）
- Flutter 3.38.10 用 Dart 3.10.9 → snapshot 版本不匹配
- Flutter 3.29.0 用 Dart 3.7.0 stable → dart:ui 缺 SemanticsRole
- flutter/engine.git 已迁移 monorepo，无法直接 git pull 到新版本

**How to apply:** 不再追求 dart_dynamic_modules iOS 验证；iOS 热修复通过 Shorebird 路线实现（已有 M3-M5 PASS 的 V2 机制）。
