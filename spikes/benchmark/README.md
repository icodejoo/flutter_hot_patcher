# Hot-Patch Benchmark

全面对比自研热修复（hotpatch）vs Shorebird 的补丁大小、推送流程、执行性能。

## 前置工具

```bash
brew install libimobiledevice ideviceinstaller  # iOS USB
brew install android-platform-tools             # adb
pip3 install rich                                # 终端彩色表格（可选）
# shorebird: 已安装于 ~/.shorebird/bin/shorebird
```

## 目录结构

| 路径 | 说明 |
|------|------|
| `hotpatch_demo/` | ObjC iOS app，复用 M3 dart_harness，USB 推送 .dill |
| `shorebird_demo/` | Flutter app，Shorebird patch 分发（CDN） |
| `scripts/` | 推送脚本 + report.py |
| `results/` | 运行时生成（已 .gitignore JSON + HTML） |
| `BENCH_PROTO.md` | benchmark.json 字段说明 |

## 运行流程

### 1. 首次准备（仅需一次）

**hotpatch_demo iOS**：按 `hotpatch_demo/XCODE_SETUP.md` 创建 Xcode project，安装 IPA 到设备。

**shorebird_demo**：
```bash
cd spikes/benchmark/shorebird_demo
~/.shorebird/bin/shorebird init   # 登录并关联 app
~/.shorebird/bin/shorebird release ios
~/.shorebird/bin/shorebird release android
```

### 2. 推送补丁并采集结果

**Hotpatch iOS（USB 直推）**：
```bash
./scripts/push_ios_hotpatch.sh <UDID> normal
./scripts/push_ios_hotpatch.sh <UDID> cpu
```

**Shorebird iOS（CDN 分发）**：
```bash
./scripts/push_ios_shorebird.sh <UDID> normal
./scripts/push_ios_shorebird.sh <UDID> cpu
```

**Shorebird Android**：
```bash
./scripts/push_android_shorebird.sh [DEVICE_SERIAL] normal
./scripts/push_android_shorebird.sh [DEVICE_SERIAL] cpu
```

**Android Hotpatch**：N/A（需自定义 Flutter engine，参考 `scripts/README_android_hotpatch.md`）

### 3. 生成报告

```bash
python3 scripts/report.py
open results/report.html
```

## 指标说明

| 指标 | 采集方式 | 备注 |
|------|---------|------|
| `patch_size_bytes` | `stat` 补丁文件 | hotpatch=.dill 裸大小，shorebird=CLI 输出 |
| `cold_start_ms` | mach_absolute_time / Dart Stopwatch | 从进程启动到首次 greet() 返回 |
| `greet_call_us` | 1000 次调用均值（μs） | hotpatch=0（dart_harness 单次运行，无重复调用接口） |
| `memory_rss_kb` | mach_task_basic_info（iOS）/ /proc/self/status（Android） | |
| `cpu_percent_peak` | getrusage 采样 10 次取峰值 | 仅 cpu patch 轮次有效 |

## 设备信息

- iOS 测试设备：iPhone 14 (040F89ED-E7CC-54B0-A7BB-908EE82C0224)，iOS 26.5
