---
name: project-v02-toolchain
description: KBC 补丁工具链现状（2026-08-14 重写）——v02 是外来 VM 的格式，我们的 VM 只吃 v01；正确流水线在 tools/route_a/
metadata:
  type: project
---

**2026-08-14 重写。此前记录的 v02 前提是错的。**

## 版本：我们的 VM 只接受 v01

`~/dart/sdk/runtime/vm/constants_kbc.h:245` → `kBytecodeFormatVersion = 1`；
`runtime/vm/bytecode_reader.cc:737-741` 拒绝其它版本。
带 v02 手改跑上游套件直接报
`Unsupported Dart bytecode format version 2`。

v02 属于 `spikes/m3_ios_realdevice/build/libdart_aotruntime_product.a` —— 一份**外来预编译 VM**，
导出 `Dart_LoadLibraryFromBytecode` / `Dart_LoadScriptFromBytecode` / `Dart_IsBytecode` / `kBytecodeCid`，
这些在 `~/dart/sdk` 全树不存在。
`pkg/dart2bytecode/lib/dbc.dart` 已恢复上游值 1；旧改动存 `archive/route_a/dbc_v02.patch`。

## 用哪套工具

- **新（正确）**：`tools/route_a/` —— 形状取自上游 `pkg/dynamic_modules/test/runner/aot.dart`。
  见 [[project-route-a-archived]] 与 `docs/ROUTE_A_RESEARCH.md`。
- **旧（有缺陷，勿再用于新工作）**：`tools/build_ios_patch.sh` / `tools/dart2bytecode_v2` / `tools/fhp`
  —— 只传 `--platform` 和 `--output`，缺 `--import-dill` 与 `--validate`，
  产出的模块**引用不到 app 里任何声明**。它们和四个测试套件留在 CI 门里只为防腐坏。

## 仍然成立的约束

`bytecode_generator.dart:657-668`：每个 module 只允许一个
`@pragma('dyn-module:entry-point')`，且必须 static、无类型参数、无参数。
但闭包表写法（`Map<String, Function> patchEntry()`）不再是必需——
有 `--import-dill` 后模块可以直接写 app 的顶层字段：

```dart
@pragma('dyn-module:entry-point')
void patchEntry() { greeting.impl = () => 'PATCHED_V1'; }
```

**How to apply**: 新补丁一律走 `tools/route_a/build.sh`，并给 app 配 `dynamic_interface.yaml`。
