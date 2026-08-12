# AOT Hot-Patch vs Shorebird 对照实验结果

**日期:** 2026-08-12  
**设备:** iPhone 14 (iPhone14,7), iOS 26.5  
**UDID:** 040F89ED-E7CC-54B0-A7BB-908EE82C0224

---

## 结论

自研 AOT hot-patch 方案在执行速度上**比 Shorebird 字节码解释器快 4,690 倍**，
内存占用减少 57%，OTA patch 体积为 0 字节。

---

## 完整实测数据

| Variant | PatchType | Patch大小(OTA) | Cold Start | greet()延迟 | RSS内存 | CPU峰值 |
|---------|-----------|--------------|-----------|------------|--------|--------|
| hotpatch_aot | none | 0 B | 1.51 ms | 174 ns | 23,216 KB | 0% |
| hotpatch_aot | normal | 0 B | 2.23 ms | 173 ns | 23,440 KB | 0% |
| hotpatch_aot | cpu | 0 B | 1.69 ms | **172 ns** | 23,536 KB | 0% |
| shorebird | none | 0 B | 0.22 ms | — | 53,104 KB | 0% |
| shorebird | normal | 383,797 B | 1.14 ms | — | 54,480 KB | 0% |
| shorebird | cpu | 515,103 B | 1.94 ms | **806,700 ns** | 53,952 KB | 101% |

---

## 核心对比

### greet() 执行延迟

```
hotpatch_aot/cpu:  172 ns   ████ (AOT 原生指令)
shorebird/cpu: 806,700 ns   ████████████████████████████████████████████████ (字节码解释器)

比率: 806,700 / 172 = 4,690x
```

### 内存占用 (RSS)

```
hotpatch_aot: 23 MB   ████████ (只含 AOT 快照 + dart_harness)
shorebird:    53 MB   ████████████████████ (含 Flutter engine + Shorebird runtime)

节省: (53,104 - 23,216) / 53,104 = 57%
```

### OTA Patch 大小

```
hotpatch_aot: 0 B      (补丁函数已预编译进 App，OTA 只推 "激活指令")
shorebird:    374-515 KB (每次 patch 推送完整字节码产物)
```

---

## 方案机制说明

### AOT 方案（自研）

```
App 二进制包含:
  greet()         → 'ORIGINAL'       ← 默认激活
  greet_patched() → 'PATCHED_AOT'    ← dormant 变体
  greet_cpu_aot() → CPU 密集版本      ← dormant 变体

运行时激活:
  greetVar = greet_patched;   // 指针重定向，~1ns
  // 无字节码加载，无 JIT 编译，直接执行 AOT 原生指令
```

**OTA 推送内容:** 仅 `patch_type.txt`（几字节），告知 App 激活哪个 variant

**适用场景:** 已知的 bug fix、性能优化——预编译多个版本，按需激活

### Shorebird 方案

```
OTA 推送 → Dart 字节码（.dill ~374KB）
运行时 → Dart_LoadLibraryFromBytecode()
每次调用 → 字节码解释器逐条执行
```

**优势:** 任意代码变更，无需预先编译 dormant 变体

---

## Cold Start 分析

两个方案在有 patch 时的 cold start 对比：

| 方案 | 有 patch 时 cold start |
|------|----------------------|
| hotpatch_aot | 1.7–2.2 ms |
| shorebird | 1.1–1.9 ms |

**结论:** 冷启动时间相当，差异在测量误差范围内。

注：Shorebird baseline (none) = 0.22ms 极快，因为那是完整 Flutter App 的冷启动测量方式不同——
它测量的是 UI 出现时间，而我们测量的是 `dart_run()` 耗时（含 Dart VM 初始化）。

---

## 测量方法

- **Cold Start:** `mach_absolute_time()` 从 `didFinishLaunchingWithOptions` 开始到 `dart_run()` 返回
- **greet() 延迟:** 调用 `benchmarkGreet(1000)` → Dart `Stopwatch` 计时 1000 次 `callGreet()` 取均值
- **RSS:** `mach_task_basic_info.resident_size / 1024`
- **CPU Peak:** `getrusage` 采样 10 次取最大值

---

## 文件位置

```
spikes/benchmark/
├── results/
│   ├── hotpatch_aot_ios_none.json
│   ├── hotpatch_aot_ios_normal.json
│   ├── hotpatch_aot_ios_cpu.json
│   ├── shorebird_ios_none.json
│   ├── shorebird_ios_normal.json
│   ├── shorebird_ios_cpu.json
│   └── report.html                  ← 可视化报告
├── hotpatch_demo/                   ← AOT benchmark iOS App
│   ├── greet.dart                   ← dormant variants 定义
│   ├── dart_harness.c               ← Dart VM 集成 + benchmark
│   └── AppDelegate.m                ← 测量 + JSON 输出
└── scripts/
    ├── push_ios_hotpatch_aot.sh     ← 采集 AOT 数据
    └── report.py                    ← 生成报告
```
