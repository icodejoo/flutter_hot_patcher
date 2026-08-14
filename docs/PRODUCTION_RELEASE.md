# 生产落地结论

> 2026-08-14 真机验证完成（iPhone 14 / iOS 26.6，UDID `00008110-000E583836F3601E`）

## 决定：产品线采用 Shorebird 预编译引擎，X1 转为研究分支

**依据不是偏好，是实测**：本轮凡按规则 2 直接采用 Shorebird 的组件（Rust updater、
`patch_cache`、boot 看门狗、`ConfigureShorebird`）**一次跑通**；凡自研的部分
**三处全出问题**（`.vmcode` 对齐常量、`CollectAllCodes` 枚举、Simulator 下的 FFI）。

X1 唯一的独有价值 A-route（KBC）已按规则 1 出局；其 Simulator 从未证明快于 Shorebird。

## 真机验证结果（全部 PASS）

### 步骤 1：OTA 补丁生效

| 阶段 | `FHP_RESULT` |
|---|---|
| baseline | `BASELINE_V1` |
| 注入补丁 + 冷重启 | **`OTA_PATCHED_V2`** |

`Failed to load patch` = 0，updater 日志 `active path: .../patches/20`。
补丁由**我们自研的 `tools/linker.py`** 产出，被 Shorebird 引擎正确加载。

### 步骤 2：A/B 性能（同一引擎、同一函数、同一设备）

热函数：10K 迭代累加，与历史基准同一函数。

| | ns/call | ns/迭代 |
|---|---|---|
| 原生 AOT | 4,502 | 0.45 |
| 解释执行（补丁） | 623,070 | 62.30 |
| **倍数** | **138×** | |

对照历史 Shorebird 实测 806,700 ns/call（80.67 ns/迭代）—— 本次 62.30 ns/迭代，
**同量级**。

**结论：B-route 的性能与 Shorebird 同级。** 此前记录的「快 5.15×」只属于
A-route（KBC 字节码），不属于产品路径 —— 该结论已在 `RESULTS.md` 与
`CONTROLLED_EXPERIMENT_AOT_VS_INTERPRETER.md` 中更正。

### 实验有效性校验

补丁未匹配集合 = `hotLoop` 及其调用者（3/7369 个函数），其余全部 link 回原生 ——
确认只有被测函数走解释器，是干净的对照实验。

## 交付的产品链路

```
源码改动
  ↓  tools/build_app_patch.sh（FHP_TOOLCHAIN=shorebird）
  ↓    ├ frontend_server  → patch.dill
  ↓    ├ gen_snapshot     → patch.aot（ELF）
  ↓    ├ analyze_snapshot → base/patch JSON
  ↓    └ tools/linker.py  → out.vmcode（LinkTable + 内嵌 ELF）
  ↓  tools/patch_builder  → Ed25519 签名 bundle
  ↓  tools/patch_server   → 分发（shorebird.yaml 的 base_url 指向它）
设备：Shorebird 引擎在 dart_snapshot.cc 的 ResolveIsolateData 处换入补丁快照
```

自研的只有闭源那三块（linker / patch_builder / patch_server），符合规则 3。

## 本轮修复的两个真实缺陷

**1. `.vmcode` 头部对齐必须是 16384，不是 4096**

设备报 `File offset must be page-aligned.`。7122 条算出 57344（4096 的倍数但非
16384 的倍数），而 iOS arm64 是 16KB 页。已在生产端（`tools/linker.py`）与
消费端（引擎 `FhpReadLinkHeader`）同时修正。

这解决了 `GROUND_TRUTH.md` 的两条悬案：对齐常量是 **16384**；aot_tools 日志里
的 `65536` 正是 56980 字节头部按 16KB 对齐的结果。

**2. `CollectAllCodes` 枚举不全**

自研的 `--shorebird` 分析器只遍历 `cls.functions()`（AOT 下多被清空），
只得 134 个函数且含负偏移。改为可达对象图遍历，并把
`object_store()->instructions_tables()` 加入根集（AOT bare-instructions 模式下
Code 挂在那里）：**134 → 1983 → 7122**，负偏移归零，app 自身代码正确出现。

## X1 研究分支的现状与遗留

X1 引擎已可重建、已集成 Shorebird 公开引擎层、能构建并运行真实 Flutter app，
但**存在一个阻断产品化的缺陷**：

Dart 跑在 Simulator 下时 `dart:ffi` 的 `@Native` 解析不支持 →
`RootIsolateToken` 失败 → **Flutter 全部 platform channel 在 binding 初始化阶段抛异常**。

```
Native._get_ffi_native_resolver (dart:ffi-patch/ffi_patch.dart:1557)
→ RootIsolateToken.__getRootIsolateToken
→ MethodChannel.setMethodCallHandler → RestorationManager.initChannels
```

同一 app 在 Shorebird 引擎上该异常为 **0 条**，证明是 X1 特有。
Shorebird 的私有 dart-sdk 显然修了这一点。

若将来要恢复「同引擎 A/B 对比」或启用 A-route，这是唯一待解的阻碍。
所有 X1 工作已保留：`engine/patches/`、`docs/X1_ENGINE_REBUILD_FIX.md`、
`spikes/shorebird_route/FINDINGS.md`。

## 验证门（全部可复现）

| 门 | 命令 | 状态 |
|---|---|---|
| v02 工具链 | `bash tools/tests/test_inspect_patch.sh` | PASS |
| 多函数补丁 | `bash tools/tests/test_multi_function_patch.sh` | PASS |
| 跨库 import | `bash tools/tests/test_import_patch.sh` | PASS |
| `fhp` CLI | `bash tools/tests/test_fhp_cli.sh` | PASS |
| patch_builder | `tools/patch_builder/.venv/bin/python -m pytest tools/patch_builder/test_patch_builder.py` | 10 passed |
| 真机 OTA | 见上，`BASELINE_V1 → OTA_PATCHED_V2` | PASS |
| A/B 性能 | 见上，138× | PASS |

## 已知限制

- iOS only；Android 未实现
- 补丁冷启动生效（与 Shorebird 相同）
- 依赖 Shorebird 预编译引擎产物（其 dart-sdk 私有，无法自建）
- 企业防火墙曾阻断网络分发；本次验证用 `devicectl` 直接注入
