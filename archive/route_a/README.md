# Route-A（KBC 字节码 / dart_dynamic_modules）—— 已归档

> 归档于 2026-08-14。产品线走 Route-B，见 `docs/PRODUCTION_RELEASE.md`。

## 为什么归档

按 `CLAUDE.md` 规则 1（完整功能以 Shorebird 为参照），Shorebird 不提供此能力，
故默认不进产品。真机复测也表明它的性能优势用不上（见下）。

## 它是什么

用 `Dart_LoadLibraryFromBytecode` / `loadDynamicModule` 加载 v02 DBC3 字节码模块，
由 KBC 解释器执行。与 Route-B（换整个 AOT 快照 + Simulator 解释）机制不同。

## 保留的资产

| 资产 | 位置 |
|---|---|
| v02 编译工具链 | `tools/dart2bytecode_v2`、`tools/build_ios_patch.sh`、`tools/inspect_patch.sh` |
| 一键打包 | `tools/fhp build`（源码 → 签名 bundle） |
| 回归测试 | `tools/tests/test_{inspect_patch,multi_function_patch,import_patch,fhp_cli}.sh` |
| 独立 embedder 验证 | `spikes/m3_ios_realdevice/` |

这些测试仍在 CI 门里跑，保证工具链不腐坏。

## 关键约束（若将来恢复）

1. **每个模块只能有一个入口点**，且必须 static、无类型参数、无参数
   （`bytecode_generator.dart:657-668`）。多函数补丁写成闭包表：
   ```dart
   @pragma('dyn-module:entry-point')
   Map<String, Function> patchEntry() => {'greet': _greet, 'add': _add};
   ```
2. **v02 依赖本地手改**：`~/dart/sdk/pkg/dart2bytecode/lib/dbc.dart` 的
   `bytecodeFormatVersion` 被从 1 改为 2（未提交）。上游是 1。
3. **`loadDynamicModule` 在 `dart:_internal`**（平台私有库），Flutter app 无法 import。
   独立 Dart 程序（`--target vm`）可以。
4. **X1 引擎当前跑不了 Flutter app**：Simulator 下 `dart:ffi` 的 `@Native` 解析不支持，
   platform channel 全挂。见 `spikes/shorebird_route/FINDINGS.md`。

## 性能（真机实测，换算成每迭代）

| | ns/迭代 |
|---|---|
| 原生 AOT | 0.45 |
| **Route-A KBC** | **15.64** |
| Route-B（Simulator） | 62.30 |

KBC 确实快 4.0×，但落在无用区间：补 UI/业务逻辑时两者都远快于需求；
补热路径时两者都不可接受（35× 与 138×）。

## 恢复条件

1. Shorebird 引擎不可用（停更 / 授权 / 版本跟不上）
2. 需要「加载任意新模块」这一 Route-B 不具备的能力（插件体系等）
3. 出现能用上那 4× 的真实场景，且在 Flutter app 上重测确认
