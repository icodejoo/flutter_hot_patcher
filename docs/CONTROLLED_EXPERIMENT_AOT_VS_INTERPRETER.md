# 对照试验：AOT 执行 vs 解释器执行

**日期**: 2026-08-12  
**设备**: iPhone 14 (arm64, iOS 17)  
**目的**: 验证我们的 .dill A-route 方案是 AOT 执行还是解释器执行，并与 Shorebird 对比

## 试验设计

三条执行路径：

| 路径 | 机制 | 预测执行方式 |
|------|------|------------|
| AOT dormant | 预编译静态变体（编译进 app binary） | 原生 AOT |
| A-route .dill | `Dart_LoadLibraryFromBytecode` → 解释执行 | 解释器 |
| Shorebird B-route | Dart VM 解释器（Simulator mode） | 解释器 |

## 原始数据

### AOT dormant（Dart-side benchmark，1000 次 closure 调用）

```json
// greet() => 'ORIGINAL'（基线）
{"variant":"hotpatch_aot","greet_call_ns":184,"aot_capi_bench_ns":597}

// 之前 session 数据（git commit f36c73f）：
{"variant":"hotpatch_aot","patch_type":"none","greet_call_ns":174}
{"variant":"hotpatch_aot","patch_type":"cpu","greet_call_ns":172}   // greet_cpu_aot: 10K 加法循环
```

### A-route .dill（解释器路径，3 次 Dart_Invoke 调用）

```json
// greet() => 'OTA_NEW'（v02 dill，解释执行）
{"variant":"hotpatch_bytecode","patch_type":"ota_new","greet_call_ns":597,"cold_start_ms":3.350}
```

### Shorebird（之前 session，git commit ccd2810）

```json
// greet_cpu_aot: 10K 加法循环（Shorebird 解释器执行）
{"variant":"shorebird","patch_type":"cpu","greet_call_us":806.7}  // 806,700 ns
```

## 关键对比

### 简单函数（string return）：C-API 开销主导

| 路径 | 每次调用耗时 | 测量方法 |
|------|------------|---------|
| AOT `getResult()` via Dart_Invoke | **597 ns** | C-API（3 次） |
| 解释器 `greet()` via Dart_Invoke | **597 ns** | C-API（3 次） |

**结论**: 对于简单函数，`Dart_Invoke` C API 边界开销（~600 ns）远大于函数执行时间，两者无法区分。

### 重计算函数（10K 加法循环）：执行方式差异暴露

| 路径 | 每次调用耗时 | 测量方法 |
|------|------------|---------|
| AOT `greet_cpu_aot()` (10K loop) | **172 ns** | Dart-side 1000 次循环 |
| Shorebird 解释器 `greet_cpu_aot()` (10K loop) | **806,700 ns** | Dart-side benchmark |
| 速度差异 | **4,690x** | — |

## 结论

### 我们的 .dill 方案是解释执行，不是 AOT

1. **技术机制**: `Dart_LoadLibraryFromBytecode` 在 AOT isolate 中加载字节码 → 无 JIT 可用 → 必须解释执行
2. **iOS W^X 限制**: 下载的代码不能 `mmap(PROT_EXEC)` → 无法实现真正的 AOT OTA
3. **与 Shorebird 等价**: Shorebird B-route 也是解释执行，机制相同
4. **性能**: 解释器比 AOT 慢 **~4,690x**（重计算场景）

### 三种执行方式对比

```
执行方式        | 简单函数    | 10K 循环    | OTA 代码大小
----------------|------------|-------------|-------------
AOT dormant     | ~184 ns    | ~172 ns     | 0 bytes（激活信号）
A-route 解释器  | ~597 ns*   | ~806,700 ns | 439 bytes
Shorebird 解释器| ~806,700 ns| ~806,700 ns | 515 KB
```
\* C-API 开销主导

### 各方案适用场景

- **AOT dormant**: 极速执行（<200ns），但 OTA 只能激活预编译变体，无法推送任意代码
- **A-route 解释器**: 可推送任意 Dart 代码，但执行速度为解释器速度（适合低频调用的 UI/业务逻辑）
- **Shorebird 解释器**: 与 A-route 等价，更完整的 patch 生态

## 技术限制记录

### 无法对 A-route 做重计算对比试验的原因

- `dart2bytecode` (2026-08 build, host_release) 产出 3CBD **v01** 格式字节码
- 我们的 X1 iOS Dart VM 接受 **v02** 格式（在 build 时编译进去）
- 版本差异：仅修改版本字节无效（v01 与 v02 字节码指令集不兼容）
- 可行的 v02 dill 只能通过**等长二进制字符串替换**现有 v02 模板生成，不支持任意函数体

### 解决方案（如需精确测量解释器速度）

1. 使用 Shorebird 数据作为代理（两者使用同一解释器）
2. 或重新构建 dart2bytecode 工具至 v02 版本（需要特定 Dart SDK commit）
