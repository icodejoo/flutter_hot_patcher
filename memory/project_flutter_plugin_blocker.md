---
name: project-flutter-plugin-blocker
description: Flutter 集成结论（2026-08-13 已定案）——不要 fork dart:ui；挂载点是引擎内部快照解析
metadata:
  type: project
---

**已定案（2026-08-13）。结论：不要 fork `dart:ui`。**

完整证据见 `docs/SHOREBIRD_REFERENCE.md` §3。以下只记结论与被证伪的死路。

## 三条已证伪的路（不要再走）

1. **`Dart_LoadLibraryFromBytecode` 在本工具链不存在。** 只在 demo 目录的 vendored
   `dart_api.h` 和预编译 `libdart_aotruntime_product.a` 里。`~/dart/sdk` 全树 0 命中，
   shipped `Flutter.framework` `nm` 也是 0。那个 demo 是独立 Dart embedder，不是 Flutter app。

2. **`dart_lib_export_symbols = true` 不可用。** `DART_EXPORT` 在 `DART_SHARED_LIB` 下多加
   `__attribute((used))`，破坏 LTO dead-strip，连带复活 Dart 自带 BoringSSL → 链接失败。已实测回滚。

3. **fork `dart:ui` 转出 `loadDynamicModule`** —— 方案本身可行（`dart:ui` 是平台库，
   已 import `dart:nativewrappers`），但 **Shorebird 证明不必要**：它对 `dart:ui` 零改动、
   Dart 侧零 API、`Dart_*` 导出为 0。而且 Dart 层加载必然在启动之后，补不了启动路径上的函数。

## 正确挂载点

引擎内部的快照解析，非任何 Dart 可见接口：`flutter/runtime/dart_snapshot.cc` 的
`ResolveIsolateData()` / `ResolveIsolateInstructions()`，各约 6 行。
`dart:_internal` 平台私有这个障碍在正确架构下根本不出现。

**关键性质**：补丁在第一行 Dart 执行前生效，所以启动路径上的函数也能补。

## How to apply

按规则 2，这套钩子已开源，直接采用，不要自研。见 [[project-landing-plan]] P0-2。
