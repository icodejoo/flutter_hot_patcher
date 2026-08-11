---
name: project-benchmark
description: 自研热修复 vs Shorebird 对比 benchmark 项目现状——spikes/benchmark/ 已搭建，待真机采集数据
metadata:
  type: project
---

`spikes/benchmark/` 已完成代码搭建（2026-08-11）。

**Why:** 量化对比自研热修复与 Shorebird 的补丁大小、推送流程、冷启动/延迟/内存/CPU 峰值。

**How to apply:** 当继续这个 benchmark 任务时参考此文件，了解已完成部分和待完成步骤。

## 已完成

- `shorebird_demo/`：Flutter app，ffi 埋点，iOS build PASS（13.4MB IPA），写 benchmark.json 到 Documents
- `hotpatch_demo/`：ObjC iOS app，复用 M3 dart_harness，mach_absolute_time 冷启动，mach_task_basic_info RSS
- `hotpatch_demo/build_patch.sh`：dart2bytecode 编译 .dill 补丁（依赖 ~/engine_ios）
- `hotpatch_demo/patches/`：greet_v1.dart（普通）+ greet_cpu.dart（10M 循环）
- `scripts/push_ios_hotpatch.sh`：devicectl USB 推 .dill，launch，pull benchmark.json
- `scripts/push_ios_shorebird.sh`：shorebird patch + CDN 分发，pull result
- `scripts/push_android_shorebird.sh`：adb push metadata + shorebird patch
- `scripts/report.py`：rich 终端表格 + Chart.js HTML，N/A 容错

## iOS 实测结果（2026-08-11，iPhone 14 iOS 26.5）

| 指标 | hotpatch normal | hotpatch cpu | shorebird normal | shorebird cpu |
|------|----------------|--------------|-----------------|---------------|
| 补丁大小 | 447 B | 514 B | 384 KB | 515 KB |
| 冷启动 | 8.6 ms | 7 ms | 1.1 ms | 1.9 ms |
| greet() 延迟 | N/A | N/A | 0 μs | 807 μs（解释模式！）|
| 内存 RSS | 28 MB | 28 MB | 54 MB | 54 MB |
| CPU 峰值 | 0% | 100% | 0% | 101% |

关键发现：
- Shorebird patch 比 hotpatch 大 860×（AOT diff vs 原始 .dill bytecode）
- Shorebird RSS 约 2× （Flutter+Shorebird vs 裸 Dart VM）
- Shorebird cpu patch 以解释模式运行（807μs/call），hotpatch 为 AOT
- cpu loop 须限制 ≤10K 次（Shorebird 解释模式无法处理 1M 次）

## 待完成（手动操作）

1. `shorebird init` + `shorebird release ios/android`（需 Shorebird 账号登录）
2. 按 `hotpatch_demo/XCODE_SETUP.md` 创建 Xcode project，安装 IPA 到设备
3. 执行 push 脚本采集数据（各组合各跑 normal + cpu 两种补丁）
4. `python3 scripts/report.py` 生成对比报告

## 关键约束

- Android hotpatch = N/A（需自定义 engine，参考 flutter-engine-rebuild skill）
- `greet_call_us` 在 hotpatch 侧 = 0（dart_harness 单次运行，无重复调用接口）
- Shorebird patch_size_bytes 从 CLI 输出 grep，精度依赖 shorebird 输出格式
- devicectl container path 格式因 iOS 版本而异，需实测调整
- shorebird_demo 的 iOS Documents 路径用 HOME env var（无 path_provider）
