---
name: project-aot-benchmark-final
description: AOT方案 vs Shorebird 完整对照实验结果（2026-08-12，iPhone 14 实测）
metadata:
  type: project
---

**AOT方案对照实验完成（2026-08-12）**

**Why:** 证明自研 AOT hot-patch 方案在执行速度和内存占用上远优于 Shorebird 字节码解释方案。

**How to apply:** 引用此数据时使用下方表格；greet() 延迟对比是最核心指标（4690x）。

## 实测数据（iPhone 14, iOS 26.5）

| Variant | PatchType | Patch大小 | Cold Start | greet()延迟 | RSS内存 |
|---------|-----------|----------|-----------|------------|--------|
| hotpatch_aot | none | 0 B | 1.51 ms | 174 ns | 23,216 KB |
| hotpatch_aot | normal | 0 B | 2.23 ms | 173 ns | 23,440 KB |
| hotpatch_aot | cpu | 0 B | 1.69 ms | 172 ns | 23,536 KB |
| shorebird | none | 0 B | 0.22 ms | — | 53,104 KB |
| shorebird | normal | 383,797 B | 1.14 ms | — | 54,480 KB |
| shorebird | cpu | 515,103 B | 1.94 ms | 806,700 ns | 53,952 KB |

## 关键对比

| 指标 | hotpatch_aot | Shorebird | 倍率 |
|------|-------------|-----------|------|
| greet() 延迟 | **172 ns** | 806,700 ns | **4,690x 快** |
| RSS 内存 | **23 MB** | 53 MB | **57% 更少** |
| Patch 大小 (OTA) | **0 B** | 374-515 KB | 函数预编译进 App |
| Cold Start (with patch) | 1.7-2.2 ms | 1.1-1.9 ms | 相当 |

## 方案机制

AOT方案 = 将补丁函数（greet_patched()、greet_cpu_aot()）预编译进 App 二进制，
运行时通过 greetVar 指针重定向激活，无需 OTA 推送可执行代码。

OTA 内容：仅推送 "激活指令"（哪个 variant），而非完整编译产物。

**数据文件位置:** `spikes/benchmark/results/hotpatch_aot_ios_*.json`
**报告:** `spikes/benchmark/results/report.html`
