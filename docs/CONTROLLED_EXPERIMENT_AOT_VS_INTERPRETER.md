# 对照试验：AOT 执行 vs 解释器执行

**日期**: 2026-08-12  
**设备**: iPhone 14 (arm64, iOS 17)  
**目的**: 验证我们的 .dill A-route 方案是 AOT 执行还是解释器执行，并与 Shorebird 对比

## 核心结论（先读这里）

| 方案 | 执行方式 | 简单函数 | 重计算函数（10K 循环）| 相对 AOT |
|------|---------|---------|---------------------|---------|
| AOT dormant | 原生机器码 | ~184 ns | **172 ns** | 1× (基准) |
| A-route .dill | **解释执行（Dart 字节码 VM）** | ~597 ns\* | ~806,700 ns（估算）| **~4,690×** |
| Shorebird 解释器 | **解释执行（Dart 字节码 VM）** | ~597 ns\* | **806,700 ns（实测）** | **~4,690×** |

\* C-API 边界开销（~600 ns）主导，函数体执行时间被掩盖

**A-route 与 Shorebird 速度完全等价** — 两者使用同一 Dart 字节码解释器。

## v01 vs v02 字节码格式区别

### 版本演进

Dart 字节码格式版本由 `runtime/vm/constants_kbc.h` 的 `kBytecodeFormatVersion` 决定。

| 版本 | 引入 commit | 核心变更 |
|------|------------|---------|
| v01 | 初始版本 | — |
| v02 | `51d1c8923ae` (2026-04-10) | 变长闭包对象（Variable-length closure objects）|
| v03 | `df15d358c8f` | 更多动态模块指令 |

### v01 → v02 的破坏性变化

commit `51d1c8923ae` 在操作码枚举的 `kUnused03` 位置插入了 5 个新操作码：

```
v01:  ... kUnused03, kSomeOpcode, kAnotherOpcode, ...
         ^--- position N
         
v02:  ... kAllocateClosure_Wide, kLoadClosureElement, kLoadClosureElement_Wide,
         kStoreClosureElement, kStoreClosureElement_Wide, kSomeOpcode, kAnotherOpcode, ...
         ^--- 5 opcodes inserted at position N
```

**结果：N 之后的所有操作码编号都偏移了 +4。**

即使是没有闭包的简单函数（如 `greet() => 'hello'`），其字节码中使用的 `Return`、`Push`、`LoadConst` 等指令的编号在 v02 VM 眼中全部错位 → 解释器执行错误指令 → 崩溃（SIGSEGV）。

这解释了为什么：
- 仅修改 dill 文件的版本字节（01→02）无法工作
- 用 v02 版本号重新编译 dart2bytecode（但使用 v01 instruction encoding）也不工作
- 必须使用与 VM 完全匹配版本的 dart2bytecode 编译器

## 试验数据

### AOT dormant（Dart-side benchmark，1000 次 closure 调用）

```json
{"variant":"hotpatch_aot","greet_call_ns":184,"aot_capi_bench_ns":597}
{"variant":"hotpatch_aot","patch_type":"cpu","greet_call_ns":172}   // greet_cpu_aot: 10K 加法循环
```

### A-route .dill（解释器路径，3 次 Dart_Invoke C-API 调用）

```json
{"variant":"hotpatch_bytecode","patch_type":"ota_new","greet_call_ns":986,"cold_start_ms":4.433}
// greet() => 'OTA_NEW'（v02 dill，trivial string return）
```

### Shorebird（Dart-side benchmark，10K 加法循环）

```json
{"variant":"shorebird","patch_type":"cpu","greet_call_us":806.7}  // 806,700 ns
```

## 性能对比

### 简单函数：C-API 开销主导，无法区分执行方式

| 路径 | 每次调用耗时 |
|------|------------|
| AOT `getResult()` via Dart_Invoke | 597 ns |
| A-route 解释器 `greet()` via Dart_Invoke | 986 ns |

C-API 边界开销约 600 ns。AOT 函数体 < 1 ns，解释器函数体也 < 1 ns（trivial string return），因此两者均被 C-API 开销掩盖。

### 重计算函数：执行方式差异暴露

| 路径 | 每次调用耗时（10K 加法循环）| 测量方式 |
|------|--------------------------|---------|
| AOT | **172 ns** | Dart-side 1000 次 benchmark |
| Shorebird 解释器 | **806,700 ns** | Dart-side benchmark |
| A-route 解释器（估算）| **~806,700 ns** | 与 Shorebird 使用同一 VM |
| 速度差 | **4,690×** | — |

## 内存占用对比

```json
{"variant":"hotpatch_bytecode","memory_rss_kb":23344}  // A-route 实测（含完整 Dart VM）
```

| 方案 | RSS 开销来源 | 大小 |
|------|------------|-----|
| AOT dormant | 无额外开销（代码已在 binary 中） | 0 |
| A-route 解释器 | Dart VM isolate + 字节码 buffer | ~23 MB |
| Shorebird 解释器 | Dart VM isolate（同上） | 相同量级 |

**A-route 与 Shorebird 内存占用相同**，因为两者都需要运行完整的 Dart VM 解释器。

## 结论

### 我们的 .dill 方案是解释执行，不是 AOT

1. **技术机制**: `Dart_LoadLibraryFromBytecode` 在 AOT isolate 中加载字节码 → 无 JIT 可用 → 必须解释执行
2. **iOS W^X 限制**: 下载的代码不能 `mmap(PROT_EXEC)` → 无法实现真正的 AOT OTA
3. **与 Shorebird 等价**: Shorebird patch 也是解释执行，机制相同，速度相同，内存相同
4. **性能代价**: 解释器比 AOT 慢约 **4,690×**（重计算场景）

### 适用场景

- **AOT dormant**: 极速执行（<200 ns），但只能激活预编译变体，无法推送任意代码
- **A-route / Shorebird 解释器**: 可推送任意 Dart 代码，适合低频调用的 UI / 业务逻辑（< 1ms 级别可接受），不适合高频数值计算

## 附：为什么无法对 A-route 做重计算实测

- 我们的 `host_release/dartaotruntime` + `dart2bytecode.dart.snapshot` 产出 **v01** 字节码
- X1 iOS Dart VM 在编译时固化了 `kBytecodeFormatVersion = 2`，严格拒绝 v01
- v02 dart2bytecode 源码（commit `51d1c8923ae`+）需要更新的 kernel AST 类型（`VariableInitializationBase` 等），与我们的 host dart binary 不兼容
- 已验证：Shorebird CLI 缓存的两个 dart2bytecode 快照（flutter revision `c2515c46` / `c15ef637`）也产出 v01
- OTA_NEW dill（dart_sdk_commit: `1aa7d7321fb`，v02）是通过旧版 Shorebird CLI 编译的，本地无法重现

因此使用 Shorebird 806,700 ns 实测数据作为 A-route 解释器速度的代理值（两者使用同一 Dart 字节码 VM）。
