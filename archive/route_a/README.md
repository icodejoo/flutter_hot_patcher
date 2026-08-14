# Route-A（KBC 字节码 / dart_dynamic_modules）—— 已归档

> 归档于 2026-08-14。产品线走 Route-B，见 `docs/PRODUCTION_RELEASE.md`。
>
> **2026-08-14 复核**：下面「关键约束」的第 2、3、4 条已被推翻或重新定性，
> 且 Route-A 已在 `~/dart/sdk` 上端到端跑通。详见 **`docs/ROUTE_A_RESEARCH.md`**。
> 仍按规则 1 停留在研究能力，不进产品线。

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
| 独立 embedder 验证（**外来 VM**，见复核） | `spikes/m3_ios_realdevice/` |
| **可跑的最小示例（本机 AOT 已 PASS）** | `spikes/route_a_v2/`、`tools/route_a/` |

这些测试仍在 CI 门里跑，保证工具链不腐坏。

## 关键约束（若将来恢复）

> 第 2、3、4 条已过时，保留原文以便对照；更正见 `docs/ROUTE_A_RESEARCH.md`。
> - 2：v02 只属于 m3 demo 里那份外来预编译 VM；`~/dart/sdk` 只接受 v01。
>   手改已恢复上游值，原改动存为 `dbc_v02.patch`。
> - 3：CFE 白名单放行名为 `dart_internal` / `dynamic_modules` 的包，
>   Flutter app 可以 import `dart:_internal`（stock Flutter 3.29.0 实测通过）。
> - 4：根因是我们自己的 A1 补丁强开 `USING_SIMULATOR`，触发
>   `runtime/lib/ffi_dynamic_library.cc` 整段禁用 FFI。Route-A 不需要 Simulator。

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

## 性能

下表是归档时的数据，测自**独立 Dart embedder**（`spikes/m3_ios_realdevice`），
而那份跑的是外来预编译 VM。

| | ns/迭代 |
|---|---|
| 原生 AOT | 0.45 |
| **Route-A KBC** | **15.64** |
| Route-B（Simulator） | 62.30 |

**2026-08-14 已在真实 Flutter app + 真机上重测**，见
`docs/AB_BENCHMARK_ROUTE_A_VS_B.md`：0.448 / 19.274 / 72.729 ns/迭代，
KBC 快 **3.77×**。倍率量级与上表一致。

两次测量都指向同一个判断：这 3.8–4× 落在无用区间 —— 补 UI/业务逻辑时两者都远快于需求；
补热路径时两者都不可接受（43× 与 162×）。

## 恢复条件

1. Shorebird 引擎不可用（停更 / 授权 / 版本跟不上）
2. 需要「加载任意新模块」这一 Route-B 不具备的能力（插件体系等）
3. 出现能用上那 4× 的真实场景，且在 Flutter app 上重测确认
