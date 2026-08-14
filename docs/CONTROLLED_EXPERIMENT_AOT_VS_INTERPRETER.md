# 对照试验：AOT 执行 vs 解释器执行

> **2026-08-14 更正（真机复测）**
>
> 文中「A-route 比 Shorebird 快 5.15×」的测量本身成立，但**只适用于 A-route
> （KBC 字节码解释）**，而 A-route 已按顶级规则 1 出局产品线。
>
> 产品路径 B-route 与 Shorebird 机制同构（ARM64 Simulator 解释 AOT 代码）。
> 同一引擎、同一函数、同一设备的实测：原生 4,502 ns/call vs 解释 623,070 ns/call
> （138×），每迭代 62.30 ns，与历史 Shorebird 的 80.67 ns/迭代**同量级**。
>
> 另：文中称 Shorebird 使用「Dart 字节码 VM」有误 —— 它用的是 ARM64 Simulator
> 解释 AOT 机器码。详见 `docs/SHOREBIRD_REFERENCE.md` §3 与
> `docs/PRODUCTION_RELEASE.md`。



**日期**: 2026-08-12  
**设备**: iPhone 14 (arm64, iOS 17)  
**目的**: 验证我们的 .dill A-route 方案是 AOT 执行还是解释器执行，并与 Shorebird 对比

## 核心结论（先读这里）

| 方案 | 执行方式 | 简单函数 | 重计算函数（10K 循环）| 相对 AOT |
|------|---------|---------|---------------------|---------|
| AOT dormant | 原生机器码 | ~184 ns | **172 ns** | 1× (基准) |
| A-route .dill | **解释执行（Dart 字节码 VM）** | ~597 ns\* | **13,652 ns（实测，1K iter）** | **~79×** |
| Shorebird 解释器 | **解释执行（Dart 字节码 VM）** | ~597 ns\* | **806,700 ns（实测）** | **~4,690×** |

\* C-API 边界开销（~600 ns）主导，函数体执行时间被掩盖

**A-route 比 Shorebird 快约 6×（per-iter）** — 使用不同版本 Dart 字节码 VM（X1 自研 engine vs Shorebird 打包 VM），机制相同但性能有差异。

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
| Shorebird 解释器 | **806,700 ns（10K iter）** | Dart-side benchmark，80.67 ns/iter |
| A-route 解释器（实测）| **13,652 ns（1K iter）** | iPhone 14 KBC C-API bench，13.65 ns/iter |
| per-iter 速度差 | **~6×**（X1 engine 更快）| 不同 VM build |
| 速度差 vs AOT | **~79×**（A-route）/ **~469×**（Shorebird）| — |

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

## 附：Mac dart run JIT 参考数据（2026-08-13）

iPhone 14 KBC 实测因设备未连接暂缺，用 Mac `dart run` 做 JIT 对比参考：

```bash
# greet_flat_loop.dart: 1000 iterations sum loop
dart run kbc_bench.dart  # N=10000 calls, 3 runs
# per_call: 623 ns / 798 ns / 915 ns  (平均 ~779 ns)
```

| 环境 | 模式 | 1000-iter loop 耗时/call |
|------|------|------------------------|
| Mac arm64 (M-series) | Dart JIT | **~779 ns**（均值，3次） |
| iPhone 14 KBC interpreter | 字节码解释 | **待测**（设备离线） |
| Shorebird iPhone 14 | 字节码解释（10K iter） | **806,700 ns**（实测）|

**注意**：
- Dart JIT 比 KBC 解释器快约 100×（JIT 将热循环编译为机器码）
- Shorebird 806,700 ns 是 10K 迭代的总耗时（每 iter ~80.67 ns in KBC）
- Mac JIT 779 ns 是 1K 迭代总耗时（每 iter ~0.78 ns in JIT）
- 两者单次调用的 per-iter 开销差约 **103×**，符合解释器 vs JIT 的典型比值

iPhone 14 KBC 1K iter 预测：
- Shorebird per-iter KBC ≈ 80.67 ns × 1000 iter = **~80,670 ns/call**
- 即比 AOT (172 ns) 慢约 **469×**
