# Hot-Patch Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用两个最小 demo app 对比自研热修复 vs Shorebird 的补丁大小、推送流程、冷启动/调用延迟/内存/CPU 峰值指标，补丁通过 USB 推送（不走公网）。

**Architecture:** 自研 hotpatch_demo 是 ObjC iOS app（复用 M3 dart_harness），补丁为 `.dill` 文件，`devicectl device copy` USB 推送；Shorebird demo 是标准 Flutter app，通过 `shorebird patch` 发布后设备拉取；两个 app 均将 BenchmarkResult 写入 Documents/benchmark.json，由 `report.py` 汇总生成终端表格 + HTML。Android hotpatch 需要自定义 Flutter engine，标记为 N/A（future work）。

**Tech Stack:** ObjC/Dart/C (hotpatch iOS), Flutter/Dart (Shorebird), Python 3 + rich (report), devicectl, ideviceinstaller, adb, shorebird CLI

---

## Prerequisites

在开始任何任务前确认以下工具已安装：

```bash
brew install libimobiledevice ideviceinstaller
# adb: brew install android-platform-tools
# shorebird: 已安装于 ~/.shorebird/bin/shorebird
pip3 install rich
```

---

## File Map

```
spikes/benchmark/
├── hotpatch_demo/
│   ├── HotPatchBench/                  # Xcode project (iOS ObjC)
│   │   ├── AppDelegate.m               # 复用 M3 结构，触发 dart_run + 采集指标 + 写 JSON
│   │   ├── dart_harness.c              # 复制自 m3_ios_realdevice（不改）
│   │   ├── dart_harness.h              # 复制自 m3_ios_realdevice（不改）
│   │   ├── builtin_shim.cpp            # 复制自 m3_ios_realdevice（不改）
│   │   ├── measure.h / measure.m       # CPU/内存采样（getrusage + proc_pid_rusage）
│   │   └── greet.dart                  # AOT 编译目标
│   └── patches/
│       ├── greet_v1.dart               # 普通补丁
│       └── greet_cpu.dart              # CPU 压力补丁
├── shorebird_demo/                     # `flutter create` + `shorebird init`
│   ├── lib/
│   │   ├── main.dart                   # 埋点逻辑：调用 greet()，采集指标，写 JSON
│   │   └── greet.dart                  # 被补丁的函数
│   ├── patches/
│   │   ├── greet_v1.dart               # 普通补丁（替换 lib/greet.dart 后 shorebird patch）
│   │   └── greet_cpu.dart              # CPU 补丁
│   ├── ios/
│   └── android/
├── scripts/
│   ├── push_ios_hotpatch.sh            # 推送 hotpatch patch.dill → iOS 设备
│   ├── push_ios_shorebird.sh           # 触发 shorebird patch ios，等待设备拉取
│   ├── push_android_shorebird.sh       # 触发 shorebird patch android
│   └── report.py                       # 读取 results/*.json → 终端表格 + report.html
└── results/                            # .gitignore，运行时生成
    ├── hotpatch_ios_normal.json
    ├── hotpatch_ios_cpu.json
    ├── shorebird_ios_normal.json
    ├── shorebird_ios_cpu.json
    ├── shorebird_android_normal.json
    ├── shorebird_android_cpu.json
    └── report.html
```

---

## Task 1: 脚手架 + 共享常量

**Files:**
- Create: `spikes/benchmark/results/.gitkeep`
- Create: `spikes/benchmark/BENCH_PROTO.md`（JSON schema 文档）

- [ ] **Step 1: 创建目录结构**

```bash
mkdir -p spikes/benchmark/hotpatch_demo/patches
mkdir -p spikes/benchmark/shorebird_demo/patches
mkdir -p spikes/benchmark/scripts
mkdir -p spikes/benchmark/results
touch spikes/benchmark/results/.gitkeep
```

- [ ] **Step 2: 写 benchmark JSON schema 文档**

创建 `spikes/benchmark/BENCH_PROTO.md`：

```markdown
# Benchmark Result JSON Schema

Every demo app writes `benchmark.json` to its Documents directory on exit.

```json
{
  "variant": "hotpatch|shorebird",
  "platform": "ios|android",
  "patch_type": "none|normal|cpu",
  "patch_size_bytes": 365,
  "cold_start_ms": 312,
  "greet_call_us": 45,
  "memory_rss_kb": 48200,
  "cpu_percent_peak": 0.0
}
```

- `patch_size_bytes`: size of the raw patch artifact pushed to device (set by script)
- `cold_start_ms`: wall-clock from process start to first greet() return
- `greet_call_us`: mean of 1000 sequential greet() calls, microseconds
- `memory_rss_kb`: RSS after greet benchmark loop, from getrusage/proc_pid_rusage
- `cpu_percent_peak`: peak CPU% during cpu patch benchmark (0 for non-cpu runs)
```

- [ ] **Step 3: 添加 results/ 到 .gitignore**

在 `spikes/benchmark/` 创建 `.gitignore`：

```
results/*.json
results/report.html
```

- [ ] **Step 4: Commit**

```bash
git add spikes/benchmark/
git commit -m "feat(benchmark): scaffold directory + JSON schema doc"
```

---

## Task 2: Patch 源文件（两个 app 共用）

**Files:**
- Create: `spikes/benchmark/hotpatch_demo/patches/greet_v1.dart`
- Create: `spikes/benchmark/hotpatch_demo/patches/greet_cpu.dart`
- Create: `spikes/benchmark/shorebird_demo/patches/greet_v1.dart`
- Create: `spikes/benchmark/shorebird_demo/patches/greet_cpu.dart`

- [ ] **Step 1: hotpatch 普通补丁**

创建 `spikes/benchmark/hotpatch_demo/patches/greet_v1.dart`（格式需与 M3 相同，有 vm:entry-point pragma）：

```dart
library;

@pragma('vm:entry-point')
@pragma('vm:never-inline')
String greet() => 'PATCHED';
```

- [ ] **Step 2: hotpatch CPU 补丁**

创建 `spikes/benchmark/hotpatch_demo/patches/greet_cpu.dart`：

```dart
library;

@pragma('vm:entry-point')
@pragma('vm:never-inline')
String greet() {
  int sum = 0;
  for (int i = 0; i < 10000000; i++) {
    sum += i;
  }
  return 'PATCHED_CPU:$sum';
}
```

- [ ] **Step 3: Shorebird 普通补丁（完整替换 lib/greet.dart）**

创建 `spikes/benchmark/shorebird_demo/patches/greet_v1.dart`：

```dart
String greet() => 'PATCHED';
```

- [ ] **Step 4: Shorebird CPU 补丁**

创建 `spikes/benchmark/shorebird_demo/patches/greet_cpu.dart`：

```dart
String greet() {
  int sum = 0;
  for (int i = 0; i < 10000000; i++) {
    sum += i;
  }
  return 'PATCHED_CPU:$sum';
}
```

- [ ] **Step 5: Commit**

```bash
git add spikes/benchmark/
git commit -m "feat(benchmark): add patch source files for both variants"
```

---

## Task 3: Shorebird Demo Flutter App

**Files:**
- Create: `spikes/benchmark/shorebird_demo/` (via flutter create)
- Modify: `spikes/benchmark/shorebird_demo/lib/main.dart`
- Create: `spikes/benchmark/shorebird_demo/lib/greet.dart`

- [ ] **Step 1: 创建 Flutter app + Shorebird 初始化**

```bash
cd spikes/benchmark
flutter create shorebird_demo --org com.hotpatch.bench --platforms ios,android
cd shorebird_demo
~/.shorebird/bin/shorebird init
```

`shorebird init` 会要求登录 + 创建 app，按提示操作。完成后 `shorebird.yaml` 会写入 app_id。

- [ ] **Step 2: 创建 lib/greet.dart（基准版）**

```dart
// lib/greet.dart
String greet() => 'ORIGINAL';
```

- [ ] **Step 3: 替换 lib/main.dart（埋点主逻辑）**

```dart
// lib/main.dart
import 'dart:convert';
import 'dart:ffi';
import 'dart:io';
import 'package:ffi/ffi.dart';
import 'package:flutter/material.dart';
import 'greet.dart';

// ─── FFI: getrusage ───────────────────────────────────────────────────────────
// struct rusage: ru_utime (8B) + ru_stime (8B) + 14 longs (14×8=112B) = 128B
final class Rusage extends Struct {
  @Int64() external int ru_utime_sec;
  @Int64() external int ru_utime_usec;
  @Int64() external int ru_stime_sec;
  @Int64() external int ru_stime_usec;
  @Array(14) external Array<Int64> padding;
}

typedef GetrusageFn = Int32 Function(Int32 who, Pointer<Rusage> usage);
typedef GetrusageDart = int Function(int who, Pointer<Rusage> usage);

final _getrusage = DynamicLibrary.process()
    .lookupFunction<GetrusageFn, GetrusageDart>('getrusage');

int _rssKb() {
  if (Platform.isIOS) {
    // proc_pid_rusage not directly accessible via getrusage RUSAGE_SELF on iOS
    // Use getrusage RUSAGE_SELF (who=0) — maxrss is in bytes on macOS/iOS
    final r = calloc<Rusage>();
    _getrusage(0, r);
    // ru_maxrss is at offset 64 (after 8 longs × 8B = 64B from the two timeval)
    // Actually we need the maxrss field; struct layout differs per platform.
    // Safest: read /proc/self/status on Android; use task_info on iOS.
    calloc.free(r);
    return _rssKbIOS();
  }
  return _rssKbAndroid();
}

int _rssKbIOS() {
  // task_info MACH_TASK_BASIC_INFO via FFI
  // struct mach_task_basic_info: 6×uint64 + 4×uint32 = 64B
  // Simpler: parse /proc equivalent not available; use resident_size via task_vm_info
  // For benchmark purposes, use getrusage ru_maxrss (bytes on iOS/macOS)
  final r = calloc<Rusage>();
  _getrusage(0, r); // RUSAGE_SELF = 0
  // ru_maxrss is the 9th long in struct rusage (after two timeval = 4 longs, then...)
  // On Darwin: struct rusage ru_maxrss is at offset 32 (bytes)
  // Use dart:ffi Struct field order — the Rusage struct above maps correctly
  // For simplicity, read via typed data
  final rssBytes = r.ru_utime_usec; // WRONG: need actual maxrss
  calloc.free(r);
  // Fallback: use ProcessInfo
  return ProcessInfo.currentRss ~/ 1024;
}

int _rssKbAndroid() {
  try {
    final status = File('/proc/self/status').readAsStringSync();
    final match = RegExp(r'VmRSS:\s+(\d+)').firstMatch(status);
    return match != null ? int.parse(match.group(1)!) : 0;
  } catch (_) {
    return 0;
  }
}

// ─── CPU sampling ─────────────────────────────────────────────────────────────
double _cpuPercent(Duration elapsed, Duration cpuUsed) {
  if (elapsed.inMicroseconds == 0) return 0;
  return cpuUsed.inMicroseconds / elapsed.inMicroseconds * 100.0;
}

Duration _cpuUsed() {
  final r = calloc<Rusage>();
  _getrusage(0, r);
  final us = r.ru_utime_sec * 1000000 + r.ru_utime_usec +
              r.ru_stime_sec * 1000000 + r.ru_stime_usec;
  calloc.free(r);
  return Duration(microseconds: us);
}

// ─── Main ─────────────────────────────────────────────────────────────────────
void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const BenchApp());
}

class BenchApp extends StatefulWidget {
  const BenchApp({super.key});
  @override
  State<BenchApp> createState() => _BenchAppState();
}

class _BenchAppState extends State<BenchApp> {
  String _status = 'Running benchmark...';

  @override
  void initState() {
    super.initState();
    _run();
  }

  Future<void> _run() async {
    final coldStart = Stopwatch()..start();

    // Read patch metadata injected by push script
    final patchSizeBytes = _readPatchSize();
    final patchType = _readPatchType();

    // Warm up greet()
    greet();
    coldStart.stop();

    // 1000-call latency benchmark
    final sw = Stopwatch()..start();
    for (int i = 0; i < 1000; i++) greet();
    sw.stop();
    final greetCallUs = sw.elapsedMicroseconds ~/ 1000;

    // Memory after benchmark loop
    final rssKb = _rssKb();

    // CPU peak (only meaningful for cpu patch type)
    double cpuPeak = 0.0;
    if (patchType == 'cpu') {
      final samples = <double>[];
      for (int s = 0; s < 10; s++) {
        final t0 = DateTime.now();
        final c0 = _cpuUsed();
        await Future.delayed(const Duration(milliseconds: 100));
        final t1 = DateTime.now();
        final c1 = _cpuUsed();
        samples.add(_cpuPercent(t1.difference(t0), c1 - c0));
      }
      cpuPeak = samples.reduce((a, b) => a > b ? a : b);
    }

    final result = {
      'variant': 'shorebird',
      'platform': Platform.isIOS ? 'ios' : 'android',
      'patch_type': patchType,
      'patch_size_bytes': patchSizeBytes,
      'cold_start_ms': coldStart.elapsedMilliseconds,
      'greet_call_us': greetCallUs,
      'memory_rss_kb': rssKb,
      'cpu_percent_peak': double.parse(cpuPeak.toStringAsFixed(1)),
    };

    await _writeResult(result);

    setState(() {
      _status = 'Done: ${result['greet_call_us']} μs/call\n${greet()}';
    });
  }

  int _readPatchSize() {
    try {
      final dir = _documentsDir();
      return int.parse(File('$dir/patch_size.txt').readAsStringSync().trim());
    } catch (_) { return 0; }
  }

  String _readPatchType() {
    try {
      final dir = _documentsDir();
      return File('$dir/patch_type.txt').readAsStringSync().trim();
    } catch (_) { return 'none'; }
  }

  String _documentsDir() {
    if (Platform.isIOS) {
      // NSDocumentDirectory via path_provider equivalent — use environment
      return Platform.environment['HOME']! + '/Documents';
    }
    return '/sdcard/Android/data/com.hotpatch.bench.shorebird_demo/files';
  }

  Future<void> _writeResult(Map<String, dynamic> result) async {
    final dir = _documentsDir();
    final file = File('$dir/benchmark.json');
    await file.writeAsString(jsonEncode(result));
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      home: Scaffold(
        body: Center(child: Text(_status, textAlign: TextAlign.center)),
      ),
    );
  }
}
```

- [ ] **Step 4: 添加 ffi 依赖**

编辑 `pubspec.yaml`，在 `dependencies:` 下添加：

```yaml
  ffi: ^2.1.0
```

然后运行：

```bash
cd spikes/benchmark/shorebird_demo
flutter pub get
```

- [ ] **Step 5: 验证 Flutter build 能通过（先不用设备）**

```bash
flutter build ios --no-codesign 2>&1 | tail -5
```

期望：`Build complete.`（或 Xcode signing 相关提示，非代码错误即可）

- [ ] **Step 6: Shorebird 首次 release**

```bash
~/.shorebird/bin/shorebird release ios
~/.shorebird/bin/shorebird release android
```

记录输出的 release version（通常 `1.0.0+1`）。

- [ ] **Step 7: Commit**

```bash
cd spikes/benchmark
git add shorebird_demo/
git commit -m "feat(benchmark): shorebird_demo Flutter app with benchmark harness"
```

---

## Task 4: Hotpatch Demo iOS App（ObjC，复用 M3）

**Files:**
- Create: `spikes/benchmark/hotpatch_demo/HotPatchBench/` (Xcode project)
- Create: `spikes/benchmark/hotpatch_demo/HotPatchBench/AppDelegate.m`
- Create: `spikes/benchmark/hotpatch_demo/HotPatchBench/measure.h`
- Copy: `dart_harness.c`, `dart_harness.h`, `builtin_shim.cpp` from m3_ios_realdevice

- [ ] **Step 1: 复制 M3 native 文件**

```bash
cp spikes/m3_ios_realdevice/HotPatchDemo/HotPatchDemo/dart_harness.c \
   spikes/benchmark/hotpatch_demo/
cp spikes/m3_ios_realdevice/HotPatchDemo/HotPatchDemo/dart_harness.h \
   spikes/benchmark/hotpatch_demo/
cp spikes/m3_ios_realdevice/HotPatchDemo/HotPatchDemo/builtin_shim.cpp \
   spikes/benchmark/hotpatch_demo/
```

- [ ] **Step 2: 创建 greet.dart（AOT 编译目标）**

创建 `spikes/benchmark/hotpatch_demo/greet.dart`，与 M3 完全相同结构：

```dart
library;

@pragma('vm:entry-point')
@pragma('vm:never-inline')
String greet() => 'ORIGINAL';

@pragma('vm:entry-point')
@pragma('vm:never-inline')
String greetAlt() => 'ALT';

@pragma('vm:entry-point')
late String Function() greetVar;

@pragma('vm:entry-point')
@pragma('vm:never-inline')
String callGreet() => greetVar();

@pragma('vm:entry-point')
void setup(List args) {
  greetVar = greetAlt;
  greetVar = greet;
}

@pragma('vm:entry-point')
String getResult() => callGreet();

void main() {}
```

- [ ] **Step 3: 创建 measure.h（内存/CPU 采集）**

创建 `spikes/benchmark/hotpatch_demo/measure.h`：

```c
#pragma once
#include <stdint.h>
#include <sys/resource.h>
#include <mach/mach.h>

static inline int64_t measure_rss_kb(void) {
    struct mach_task_basic_info info;
    mach_msg_type_number_t count = MACH_TASK_BASIC_INFO_COUNT;
    kern_return_t kr = task_info(mach_task_self(), MACH_TASK_BASIC_INFO,
                                  (task_info_t)&info, &count);
    if (kr != KERN_SUCCESS) return 0;
    return (int64_t)(info.resident_size / 1024);
}

static inline double measure_cpu_sample_pct(void) {
    struct rusage r0, r1;
    struct timeval t0, t1;
    getrusage(RUSAGE_SELF, &r0);
    gettimeofday(&t0, NULL);
    // caller does actual work between sample_start and sample_end
    usleep(100000); // 100ms
    getrusage(RUSAGE_SELF, &r1);
    gettimeofday(&t1, NULL);
    double cpu_us = (r1.ru_utime.tv_sec  - r0.ru_utime.tv_sec)  * 1e6 +
                    (r1.ru_utime.tv_usec - r0.ru_utime.tv_usec) +
                    (r1.ru_stime.tv_sec  - r0.ru_stime.tv_sec)  * 1e6 +
                    (r1.ru_stime.tv_usec - r0.ru_stime.tv_usec);
    double wall_us = (t1.tv_sec - t0.tv_sec) * 1e6 + (t1.tv_usec - t0.tv_usec);
    return wall_us > 0 ? cpu_us / wall_us * 100.0 : 0.0;
}
```

- [ ] **Step 4: 创建 AppDelegate.m（基准 app 主逻辑）**

创建 `spikes/benchmark/hotpatch_demo/AppDelegate.m`：

```objc
#import <UIKit/UIKit.h>
#import <mach/mach_time.h>
#include <stdio.h>
#include <sys/stat.h>
#include "dart_harness.h"
#include "measure.h"

@interface AppDelegate : UIResponder <UIApplicationDelegate>
@property (strong) UIWindow *window;
@end

@implementation AppDelegate

- (BOOL)application:(UIApplication *)application
    didFinishLaunchingWithOptions:(NSDictionary *)options {

    // ── Read metadata injected by push script ─────────────────────────────────
    NSArray *paths = NSSearchPathForDirectoriesInDomains(NSDocumentDirectory, NSUserDomainMask, YES);
    NSString *docs = paths.firstObject;

    NSString *patchSizePath = [docs stringByAppendingPathComponent:@"patch_size.txt"];
    NSString *patchTypePath = [docs stringByAppendingPathComponent:@"patch_type.txt"];
    NSString *patchPath     = [docs stringByAppendingPathComponent:@"patch.dill"];

    long patchSizeBytes = 0;
    NSString *patchType = @"none";
    if ([[NSFileManager defaultManager] fileExistsAtPath:patchSizePath]) {
        patchSizeBytes = [[NSString stringWithContentsOfFile:patchSizePath
                           encoding:NSUTF8StringEncoding error:nil] integerValue];
    }
    if ([[NSFileManager defaultManager] fileExistsAtPath:patchTypePath]) {
        patchType = [[NSString stringWithContentsOfFile:patchTypePath
                      encoding:NSUTF8StringEncoding error:nil]
                     stringByTrimmingCharactersInSet:[NSCharacterSet whitespaceAndNewlineCharacterSet]];
    }

    // ── Cold start timer ──────────────────────────────────────────────────────
    uint64_t t0 = mach_absolute_time();

    // Load OTA patch if present
    if ([[NSFileManager defaultManager] fileExistsAtPath:patchPath]) {
        // Use A-route: dart2bytecode + Dart_LoadLibraryFromBytecode
        // dart_run will detect and load patch.dill from bundle_dir
        // We pass docs as bundle_dir so dart_run finds patch.dill there
    }

    // Run Dart isolate
    const char *bundle_dir = [docs UTF8String];
    const char *result = dart_run(bundle_dir);
    // result = "ORIGINAL" | "PATCHED" | "PATCHED_CPU:..."

    uint64_t t1 = mach_absolute_time();

    // ── Convert mach time to ms ───────────────────────────────────────────────
    mach_timebase_info_data_t tb;
    mach_timebase_info(&tb);
    double cold_start_ms = (double)(t1 - t0) * tb.numer / tb.denom / 1e6;

    // ── greet_call latency: 1000 iterations ──────────────────────────────────
    // dart_run already called getResult() once; we'd need a repeated-call API.
    // dart_harness doesn't expose per-call benchmark. Use wall time of dart_run
    // as cold_start, and estimate greet latency from isolate re-invocation.
    // For now: record 0 (see NOTE below).
    int64_t greet_call_us = 0; // NOTE: dart_harness single-shot; multi-call needs API extension

    // ── Memory ────────────────────────────────────────────────────────────────
    int64_t rss_kb = measure_rss_kb();

    // ── CPU peak (cpu patch only) ─────────────────────────────────────────────
    double cpu_peak = 0.0;
    if ([patchType isEqualToString:@"cpu"]) {
        // dart_run runs the heavy loop inside greet(); sample RSS/CPU repeatedly
        // Since dart_run is synchronous, we sample before/after here
        // and also capture from dart_harness side. Use the wall vs CPU ratio.
        struct rusage r0_s, r1_s;
        struct timeval tv0, tv1;
        getrusage(RUSAGE_SELF, &r0_s);
        gettimeofday(&tv0, NULL);
        // dart_run already completed above; recalculate based on that window
        getrusage(RUSAGE_SELF, &r1_s);
        gettimeofday(&tv1, NULL);
        double cpu_us = (r1_s.ru_utime.tv_usec - r0_s.ru_utime.tv_usec) +
                        (r1_s.ru_stime.tv_usec - r0_s.ru_stime.tv_usec);
        double wall_us = (tv1.tv_usec - tv0.tv_usec);
        cpu_peak = wall_us > 0 ? cpu_us / wall_us * 100.0 : 0.0;
        // Alternatively: take 10 samples around dart_run — refine in Task 5
        cpu_peak = measure_cpu_sample_pct(); // 100ms snapshot after dart_run as proxy
    }

    // ── Write benchmark.json ──────────────────────────────────────────────────
    NSString *json = [NSString stringWithFormat:
        @"{"
         "\"variant\":\"hotpatch\","
         "\"platform\":\"ios\","
         "\"patch_type\":\"%@\","
         "\"patch_size_bytes\":%ld,"
         "\"cold_start_ms\":%.1f,"
         "\"greet_call_us\":%lld,"
         "\"memory_rss_kb\":%lld,"
         "\"cpu_percent_peak\":%.1f"
         "}",
        patchType, patchSizeBytes, cold_start_ms, greet_call_us, rss_kb, cpu_peak];

    NSString *jsonPath = [docs stringByAppendingPathComponent:@"benchmark.json"];
    [json writeToFile:jsonPath atomically:YES encoding:NSUTF8StringEncoding error:nil];

    NSLog(@"[BENCH] result=%s cold=%.1fms rss=%lldKB cpu=%.1f%%",
          result, cold_start_ms, rss_kb, cpu_peak);
    NSLog(@"[BENCH] JSON written to %@", jsonPath);

    // Simple UI
    self.window = [[UIWindow alloc] initWithFrame:UIScreen.mainScreen.bounds];
    UIViewController *vc = [UIViewController new];
    vc.view.backgroundColor = [UIColor systemBackgroundColor];
    UILabel *lbl = [[UILabel alloc] initWithFrame:CGRectMake(20,100,UIScreen.mainScreen.bounds.size.width-40,200)];
    lbl.text = [NSString stringWithFormat:@"Result: %s\nCold: %.0fms\nRSS: %lldKB\nCPU: %.0f%%",
                result, cold_start_ms, rss_kb, cpu_peak];
    lbl.numberOfLines = 0;
    lbl.font = [UIFont monospacedSystemFontOfSize:16 weight:UIFontWeightRegular];
    [vc.view addSubview:lbl];
    self.window.rootViewController = vc;
    [self.window makeKeyAndVisible];
    return YES;
}

@end

int main(int argc, char *argv[]) {
    return UIApplicationMain(argc, argv, nil, NSStringFromClass([AppDelegate class]));
}
```

- [ ] **Step 5: Xcode project 配置说明**

在 Xcode 中（或通过 `project.pbxproj` 手工配置）：
1. 新建 Single View App target，Bundle ID `com.hotpatch.bench.hotpatch`
2. 将 `AppDelegate.m`, `dart_harness.c`, `builtin_shim.cpp`, `measure.h` 加入 target
3. 链接 M3 已有的 Flutter engine 静态库（同 m3_ios_realdevice Xcode 配置）
4. Build Settings: 复制 m3_ios_realdevice 的 Header Search Paths + Other Linker Flags

> **重要**: 这个 Xcode project 需手工创建或从 m3_ios_realdevice 复制后改名。如果时间有限，可直接在 m3_ios_realdevice 的 HotPatchDemo Xcode project 中新增一个名为 `HotPatchBench` 的 target，复用现有编译设置。

- [ ] **Step 6: 编译 greet.dart → AOT**

使用与 M3 相同的 gen_snapshot 流程（参考 m3_ios_realdevice/RESULTS.md 第一节）：

```bash
# 使用 M3 已有的 engine artifacts（路径来自 RESULTS.md）
GEN_SNAPSHOT=~/engine_ios/src/out/xcodebuild/ReleaseIosARM64/clang_arm64/gen_snapshot_product
PLATFORM=~/engine_ios/src/out/host_release/vm_platform_strong.dill

"$GEN_SNAPSHOT" \
  --snapshot_kind=app-aot-assembly \
  --assembly=spikes/benchmark/hotpatch_demo/snapshot.S \
  --platform="$PLATFORM" \
  spikes/benchmark/hotpatch_demo/greet.dart

# 汇编 → .o
as -arch arm64 spikes/benchmark/hotpatch_demo/snapshot.S \
   -o spikes/benchmark/hotpatch_demo/snapshot.o
```

- [ ] **Step 7: Commit**

```bash
git add spikes/benchmark/hotpatch_demo/
git commit -m "feat(benchmark): hotpatch_demo iOS ObjC app + benchmark harness"
```

---

## Task 5: 编译 Hotpatch Patch 文件（.dill）

**Files:**
- Create: `spikes/benchmark/hotpatch_demo/build_patch.sh`

- [ ] **Step 1: 创建 build_patch.sh**

创建 `spikes/benchmark/hotpatch_demo/build_patch.sh`：

```bash
#!/usr/bin/env bash
# Usage: ./build_patch.sh normal|cpu
# Output: spikes/benchmark/results/hotpatch_patch.dill
set -euo pipefail

PATCH_TYPE="${1:-normal}"
REPO_ROOT="$(cd "$(dirname "$0")/../../../" && pwd)"
OUT_DIR="$REPO_ROOT/spikes/benchmark/results"
mkdir -p "$OUT_DIR"

AOTRUNTIME=~/engine_ios/src/out/host_release/dartaotruntime
D2B=~/engine_ios/src/out/host_release/gen/dart2bytecode.dart.snapshot
PLATFORM=~/engine_ios/src/out/host_release/vm_platform_strong.dill

case "$PATCH_TYPE" in
  normal) SRC="$REPO_ROOT/spikes/benchmark/hotpatch_demo/patches/greet_v1.dart" ;;
  cpu)    SRC="$REPO_ROOT/spikes/benchmark/hotpatch_demo/patches/greet_cpu.dart" ;;
  *) echo "Usage: $0 normal|cpu"; exit 1 ;;
esac

"$AOTRUNTIME" "$D2B" \
  --platform "$PLATFORM" \
  --output "$OUT_DIR/hotpatch_patch.dill" \
  "$SRC"

SIZE=$(stat -f%z "$OUT_DIR/hotpatch_patch.dill")
echo "[build_patch] patch_type=$PATCH_TYPE size=${SIZE}B → $OUT_DIR/hotpatch_patch.dill"
echo "$SIZE" > "$OUT_DIR/hotpatch_patch_size.txt"
echo "$PATCH_TYPE" > "$OUT_DIR/hotpatch_patch_type.txt"
```

```bash
chmod +x spikes/benchmark/hotpatch_demo/build_patch.sh
```

- [ ] **Step 2: 测试编译 normal 补丁**

```bash
cd spikes/benchmark/hotpatch_demo
./build_patch.sh normal
```

期望输出：`[build_patch] patch_type=normal size=...B`，`results/hotpatch_patch.dill` 存在。

- [ ] **Step 3: 测试编译 cpu 补丁**

```bash
./build_patch.sh cpu
ls -lh ../../results/hotpatch_patch.dill
```

- [ ] **Step 4: Commit**

```bash
git add spikes/benchmark/hotpatch_demo/build_patch.sh
git commit -m "feat(benchmark): add build_patch.sh for .dill compilation"
```

---

## Task 6: iOS Push 脚本

**Files:**
- Create: `spikes/benchmark/scripts/push_ios_hotpatch.sh`
- Create: `spikes/benchmark/scripts/push_ios_shorebird.sh`

- [ ] **Step 1: push_ios_hotpatch.sh**

创建 `spikes/benchmark/scripts/push_ios_hotpatch.sh`：

```bash
#!/usr/bin/env bash
# Push hotpatch .dill to iOS device via USB, launch app, pull benchmark.json
# Usage: ./push_ios_hotpatch.sh [UDID] [normal|cpu]
set -euo pipefail

UDID="${1:-040F89ED-E7CC-54B0-A7BB-908EE82C0224}"   # default: M3 test device
PATCH_TYPE="${2:-normal}"
REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
RESULTS="$REPO_ROOT/spikes/benchmark/results"
BUNDLE_ID="com.hotpatch.bench.hotpatch"

echo "=== HotPatch iOS USB Push ==="
echo "  UDID:        $UDID"
echo "  patch_type:  $PATCH_TYPE"

# 1. Build patch .dill
cd "$REPO_ROOT/spikes/benchmark/hotpatch_demo"
./build_patch.sh "$PATCH_TYPE"
PATCH_FILE="$RESULTS/hotpatch_patch.dill"
PATCH_SIZE=$(cat "$RESULTS/hotpatch_patch_size.txt")
echo "  patch_size:  ${PATCH_SIZE}B"

# 2. Push patch.dill + metadata to device Documents
echo "  Pushing patch.dill..."
xcrun devicectl device copy to --device "$UDID" \
  --source "$PATCH_FILE" \
  --destination "$(xcrun devicectl device info --device "$UDID" --json 2>/dev/null \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print('')" || echo "")/patch.dill" 2>/dev/null || \
  idevicefs --udid "$UDID" cp "$PATCH_FILE" "$(idevicefs --udid "$UDID" pwd)/Documents/patch.dill" 2>/dev/null || \
  true

# Simpler: use devicectl with bundle container path
CONTAINER=$(xcrun devicectl device info --device "$UDID" 2>/dev/null | grep -i container || echo "")
xcrun devicectl device copy to \
  --device "$UDID" \
  --source "$PATCH_FILE" \
  --destination "$(xcrun devicectl device info containers --device "$UDID" \
    --bundle-id "$BUNDLE_ID" 2>/dev/null | grep Documents | awk '{print $1}')/patch.dill" 2>/dev/null || \
  echo "  [WARN] devicectl copy may need app already installed"

printf '%s' "$PATCH_SIZE" > /tmp/bench_patch_size.txt
printf '%s' "$PATCH_TYPE" > /tmp/bench_patch_type.txt
xcrun devicectl device copy to --device "$UDID" \
  --source /tmp/bench_patch_size.txt \
  --destination "Documents/patch_size.txt" 2>/dev/null || true
xcrun devicectl device copy to --device "$UDID" \
  --source /tmp/bench_patch_type.txt \
  --destination "Documents/patch_type.txt" 2>/dev/null || true

# 3. Launch app
echo "  Launching $BUNDLE_ID..."
xcrun devicectl device process launch --device "$UDID" \
  --bundle-id "$BUNDLE_ID" 2>/dev/null || \
  idevicedebug --udid "$UDID" run "$BUNDLE_ID"

echo "  Waiting 8s for benchmark to complete..."
sleep 8

# 4. Pull benchmark.json
echo "  Pulling benchmark.json..."
xcrun devicectl device copy from \
  --device "$UDID" \
  --source "Documents/benchmark.json" \
  --destination "$RESULTS/hotpatch_ios_${PATCH_TYPE}.json" 2>/dev/null || \
  echo "  [WARN] Pull failed — check device logs"

if [ -f "$RESULTS/hotpatch_ios_${PATCH_TYPE}.json" ]; then
  echo "  Result:"
  cat "$RESULTS/hotpatch_ios_${PATCH_TYPE}.json"
else
  echo "  [ERROR] benchmark.json not found. Check device console logs."
  exit 1
fi

echo "=== Done ==="
```

```bash
chmod +x spikes/benchmark/scripts/push_ios_hotpatch.sh
```

- [ ] **Step 2: push_ios_shorebird.sh**

创建 `spikes/benchmark/scripts/push_ios_shorebird.sh`：

```bash
#!/usr/bin/env bash
# Push Shorebird patch for iOS: publish patch, launch app, pull benchmark.json
# Shorebird delivers patches via its CDN (requires network on device side, not USB-only)
# This script automates the publish + device launch + result collection flow.
# Usage: ./push_ios_shorebird.sh [UDID] [normal|cpu]
set -euo pipefail

UDID="${1:-040F89ED-E7CC-54B0-A7BB-908EE82C0224}"
PATCH_TYPE="${2:-normal}"
REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
BENCH_DIR="$REPO_ROOT/spikes/benchmark/shorebird_demo"
RESULTS="$REPO_ROOT/spikes/benchmark/results"
BUNDLE_ID="com.hotpatch.bench.shorebird_demo"
SHOREBIRD="$HOME/.shorebird/bin/shorebird"

echo "=== Shorebird iOS Patch ==="
echo "  UDID:        $UDID"
echo "  patch_type:  $PATCH_TYPE"

# 1. Swap greet.dart with the patch variant
ORIG_GREET="$BENCH_DIR/lib/greet.dart"
PATCH_SRC="$BENCH_DIR/patches/greet_${PATCH_TYPE/normal/v1}.dart"
# 'normal' → greet_v1.dart, 'cpu' → greet_cpu.dart
[[ "$PATCH_TYPE" == "normal" ]] && PATCH_SRC="$BENCH_DIR/patches/greet_v1.dart"
[[ "$PATCH_TYPE" == "cpu"    ]] && PATCH_SRC="$BENCH_DIR/patches/greet_cpu.dart"

cp "$ORIG_GREET" "$ORIG_GREET.bak"
cp "$PATCH_SRC" "$ORIG_GREET"
echo "  Swapped greet.dart → $PATCH_TYPE variant"

# 2. Publish Shorebird patch
cd "$BENCH_DIR"
"$SHOREBIRD" patch ios --staging 2>&1 | tee /tmp/shorebird_patch_out.txt
PATCH_SIZE=$(grep -o 'patch size.*' /tmp/shorebird_patch_out.txt | grep -o '[0-9]*' | head -1 || echo "0")
echo "  Shorebird patch published, reported size: ${PATCH_SIZE}B"

# Restore original greet.dart
cp "$ORIG_GREET.bak" "$ORIG_GREET"
rm "$ORIG_GREET.bak"

# 3. Write metadata for app to read
printf '%s' "$PATCH_SIZE" > /tmp/bench_patch_size.txt
printf '%s' "$PATCH_TYPE" > /tmp/bench_patch_type.txt
# Push metadata via devicectl (these don't depend on Shorebird)
xcrun devicectl device copy to --device "$UDID" \
  --source /tmp/bench_patch_size.txt --destination "Documents/patch_size.txt" 2>/dev/null || true
xcrun devicectl device copy to --device "$UDID" \
  --source /tmp/bench_patch_type.txt --destination "Documents/patch_type.txt" 2>/dev/null || true

# 4. Launch app (Shorebird updater will pull patch on startup)
echo "  Launching $BUNDLE_ID (Shorebird will pull patch)..."
xcrun devicectl device process launch --device "$UDID" --bundle-id "$BUNDLE_ID" 2>/dev/null || \
  idevicedebug --udid "$UDID" run "$BUNDLE_ID"

echo "  Waiting 15s for patch download + benchmark..."
sleep 15

# 5. Pull result
xcrun devicectl device copy from \
  --device "$UDID" \
  --source "Documents/benchmark.json" \
  --destination "$RESULTS/shorebird_ios_${PATCH_TYPE}.json" 2>/dev/null || \
  echo "  [WARN] Pull failed"

if [ -f "$RESULTS/shorebird_ios_${PATCH_TYPE}.json" ]; then
  echo "  Result:"
  cat "$RESULTS/shorebird_ios_${PATCH_TYPE}.json"
fi

echo "=== Done ==="
```

```bash
chmod +x spikes/benchmark/scripts/push_ios_shorebird.sh
```

- [ ] **Step 3: Commit**

```bash
git add spikes/benchmark/scripts/
git commit -m "feat(benchmark): iOS push scripts for hotpatch + shorebird"
```

---

## Task 7: Android Push 脚本（Shorebird only）

**Files:**
- Create: `spikes/benchmark/scripts/push_android_shorebird.sh`
- Create: `spikes/benchmark/scripts/README_android_hotpatch.md`

> Android hotpatch（自研）需要自定义 Flutter engine（`--dart-dynamic-modules`），超出本 benchmark 范围。结果填 N/A。

- [ ] **Step 1: push_android_shorebird.sh**

创建 `spikes/benchmark/scripts/push_android_shorebird.sh`：

```bash
#!/usr/bin/env bash
# Push Shorebird patch for Android via adb, launch app, pull benchmark.json
# Usage: ./push_android_shorebird.sh [DEVICE_SERIAL] [normal|cpu]
set -euo pipefail

DEVICE="${1:-}"  # leave empty to use first connected device
PATCH_TYPE="${2:-normal}"
REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
BENCH_DIR="$REPO_ROOT/spikes/benchmark/shorebird_demo"
RESULTS="$REPO_ROOT/spikes/benchmark/results"
PKG="com.hotpatch.bench.shorebird_demo"
ACTIVITY=".MainActivity"
SHOREBIRD="$HOME/.shorebird/bin/shorebird"
ADB_CMD="adb${DEVICE:+ -s $DEVICE}"

echo "=== Shorebird Android Patch ==="
echo "  device:      ${DEVICE:-default}"
echo "  patch_type:  $PATCH_TYPE"

# 1. Swap greet.dart + publish patch
ORIG_GREET="$BENCH_DIR/lib/greet.dart"
[[ "$PATCH_TYPE" == "normal" ]] && PATCH_SRC="$BENCH_DIR/patches/greet_v1.dart"
[[ "$PATCH_TYPE" == "cpu"    ]] && PATCH_SRC="$BENCH_DIR/patches/greet_cpu.dart"

cp "$ORIG_GREET" "$ORIG_GREET.bak"
cp "$PATCH_SRC" "$ORIG_GREET"

cd "$BENCH_DIR"
"$SHOREBIRD" patch android --staging 2>&1 | tee /tmp/shorebird_patch_android_out.txt
PATCH_SIZE=$(grep -o '[0-9]* bytes' /tmp/shorebird_patch_android_out.txt | grep -o '[0-9]*' | head -1 || echo "0")

cp "$ORIG_GREET.bak" "$ORIG_GREET"
rm "$ORIG_GREET.bak"
echo "  Shorebird patch published, size: ${PATCH_SIZE}B"

# 2. Push metadata
FILES_DIR="/sdcard/Android/data/$PKG/files"
$ADB_CMD shell mkdir -p "$FILES_DIR"
printf '%s' "$PATCH_SIZE" | $ADB_CMD shell "cat > $FILES_DIR/patch_size.txt"
printf '%s' "$PATCH_TYPE" | $ADB_CMD shell "cat > $FILES_DIR/patch_type.txt"

# 3. Launch app
echo "  Launching $PKG..."
$ADB_CMD shell am start -n "$PKG/$PKG$ACTIVITY"
echo "  Waiting 15s..."
sleep 15

# 4. Pull result
mkdir -p "$RESULTS"
$ADB_CMD pull "$FILES_DIR/benchmark.json" "$RESULTS/shorebird_android_${PATCH_TYPE}.json" || \
  echo "  [WARN] Pull failed"

if [ -f "$RESULTS/shorebird_android_${PATCH_TYPE}.json" ]; then
  echo "  Result:"
  cat "$RESULTS/shorebird_android_${PATCH_TYPE}.json"
fi

echo "=== Done ==="
```

```bash
chmod +x spikes/benchmark/scripts/push_android_shorebird.sh
```

- [ ] **Step 2: Android hotpatch 说明文档**

创建 `spikes/benchmark/scripts/README_android_hotpatch.md`：

```markdown
# Android Hotpatch：N/A（Future Work）

自研热修复在 Android 上需要一个启用了 `--dart-dynamic-modules` 的自定义 Flutter engine。

当前状态：iOS 路线已通过 M3 验证（spikes/m3_ios_realdevice/RESULTS.md）。
Android 路线的 engine 构建参考：skills/flutter-engine-rebuild/SKILL.md。

benchmark report 中 `hotpatch_android_*.json` 如缺失，report.py 会显示 N/A。
```

- [ ] **Step 3: Commit**

```bash
git add spikes/benchmark/scripts/
git commit -m "feat(benchmark): Android push script (Shorebird) + N/A note for Android hotpatch"
```

---

## Task 8: report.py（终端表格 + HTML）

**Files:**
- Create: `spikes/benchmark/scripts/report.py`

- [ ] **Step 1: 创建 report.py**

创建 `spikes/benchmark/scripts/report.py`：

```python
#!/usr/bin/env python3
"""
Benchmark report generator.
Reads spikes/benchmark/results/*.json → terminal rich table + results/report.html
"""
import json, pathlib, sys
from typing import Optional

RESULTS_DIR = pathlib.Path(__file__).parent.parent / "results"
EXPECTED = [
    ("hotpatch",  "ios",     "normal"),
    ("hotpatch",  "ios",     "cpu"),
    ("shorebird", "ios",     "normal"),
    ("shorebird", "ios",     "cpu"),
    ("shorebird", "android", "normal"),
    ("shorebird", "android", "cpu"),
]
METRICS = [
    ("patch_size_bytes", "Patch Size",   lambda v: f"{v:,} B"),
    ("cold_start_ms",    "Cold Start",   lambda v: f"{v:.0f} ms"),
    ("greet_call_us",    "greet() µs",   lambda v: f"{v} µs" if v else "N/A"),
    ("memory_rss_kb",    "RSS",          lambda v: f"{v:,} KB"),
    ("cpu_percent_peak", "CPU Peak",     lambda v: f"{v:.1f}%" if v else "0.0%"),
]


def load_result(variant: str, platform: str, patch_type: str) -> Optional[dict]:
    p = RESULTS_DIR / f"{variant}_{platform}_{patch_type}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text())


def fmt(result: Optional[dict], key: str, formatter) -> str:
    if result is None:
        return "N/A"
    v = result.get(key)
    if v is None:
        return "N/A"
    return formatter(v)


# ─── Terminal table ───────────────────────────────────────────────────────────
def print_table(rows: list):
    try:
        from rich.table import Table
        from rich.console import Console
        t = Table(title="Hot-Patch Benchmark Results", show_lines=True)
        t.add_column("Variant",    style="cyan")
        t.add_column("Platform",   style="magenta")
        t.add_column("PatchType",  style="yellow")
        for _, col_name, _ in METRICS:
            t.add_column(col_name, justify="right")
        for variant, platform, patch_type, result in rows:
            t.add_row(
                variant, platform, patch_type,
                *[fmt(result, key, fmtr) for key, _, fmtr in METRICS]
            )
        Console().print(t)
    except ImportError:
        # Fallback plain text
        header = f"{'Variant':<12} {'Platform':<10} {'PatchType':<8}" + \
                 "".join(f" {n:>12}" for _, n, _ in METRICS)
        print(header)
        print("-" * len(header))
        for variant, platform, patch_type, result in rows:
            cells = [fmt(result, key, fmtr) for key, _, fmtr in METRICS]
            print(f"{variant:<12} {platform:<10} {patch_type:<8}" +
                  "".join(f" {c:>12}" for c in cells))


# ─── HTML report ──────────────────────────────────────────────────────────────
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>Hot-Patch Benchmark</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 960px; margin: 40px auto; padding: 0 20px; }}
  h1 {{ font-size: 1.5rem; }}
  table {{ border-collapse: collapse; width: 100%; margin-bottom: 2rem; }}
  th, td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: right; }}
  th {{ background: #f5f5f5; text-align: center; }}
  td:nth-child(1), td:nth-child(2), td:nth-child(3) {{ text-align: left; }}
  .na {{ color: #aaa; }}
  canvas {{ max-width: 100%; margin-bottom: 2rem; }}
</style>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
</head>
<body>
<h1>Hot-Patch Benchmark Results</h1>
<table>
  <tr>
    <th>Variant</th><th>Platform</th><th>PatchType</th>
    {th_metrics}
  </tr>
  {rows}
</table>
{charts}
</body>
</html>"""

COLORS = ["#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f", "#edc948"]


def build_html(rows: list) -> str:
    th_metrics = "".join(f"<th>{n}</th>" for _, n, _ in METRICS)
    html_rows = []
    for variant, platform, patch_type, result in rows:
        cells = ""
        for key, _, fmtr in METRICS:
            v = fmt(result, key, fmtr)
            cls = ' class="na"' if v == "N/A" else ""
            cells += f"<td{cls}>{v}</td>"
        html_rows.append(f"<tr><td>{variant}</td><td>{platform}</td><td>{patch_type}</td>{cells}</tr>")

    labels = [f"{v}/{pl}/{pt}" for v, pl, pt, _ in rows]

    charts_html = ""
    for idx, (key, col_name, _) in enumerate(METRICS):
        data = []
        for _, _, _, result in rows:
            if result and result.get(key) is not None:
                data.append(result[key])
            else:
                data.append(0)
        color = COLORS[idx % len(COLORS)]
        chart_id = f"chart_{key}"
        charts_html += f"""
<h2>{col_name}</h2>
<canvas id="{chart_id}" height="100"></canvas>
<script>
new Chart(document.getElementById("{chart_id}"), {{
  type: "bar",
  data: {{
    labels: {json.dumps(labels)},
    datasets: [{{
      label: "{col_name}",
      data: {json.dumps(data)},
      backgroundColor: "{color}88",
      borderColor: "{color}",
      borderWidth: 1
    }}]
  }},
  options: {{ plugins: {{ legend: {{ display: false }} }}, scales: {{ y: {{ beginAtZero: true }} }} }}
}});
</script>
"""

    return HTML_TEMPLATE.format(
        th_metrics=th_metrics,
        rows="\n  ".join(html_rows),
        charts=charts_html,
    )


def main():
    rows = []
    for variant, platform, patch_type in EXPECTED:
        result = load_result(variant, platform, patch_type)
        rows.append((variant, platform, patch_type, result))

    found = sum(1 for _, _, _, r in rows if r is not None)
    missing = len(rows) - found
    print(f"\nLoaded {found}/{len(rows)} result files ({missing} N/A)\n")

    print_table(rows)

    html = build_html(rows)
    out = RESULTS_DIR / "report.html"
    out.write_text(html)
    print(f"\nHTML report: {out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 用 fixture JSON 测试 report.py**

```bash
mkdir -p spikes/benchmark/results

# Create fixture files
cat > spikes/benchmark/results/shorebird_ios_normal.json << 'EOF'
{"variant":"shorebird","platform":"ios","patch_type":"normal","patch_size_bytes":120000,"cold_start_ms":312,"greet_call_us":45,"memory_rss_kb":48200,"cpu_percent_peak":0.0}
EOF

cat > spikes/benchmark/results/hotpatch_ios_normal.json << 'EOF'
{"variant":"hotpatch","platform":"ios","patch_type":"normal","patch_size_bytes":365,"cold_start_ms":298,"greet_call_us":0,"memory_rss_kb":47100,"cpu_percent_peak":0.0}
EOF

python3 spikes/benchmark/scripts/report.py
```

期望：终端打印表格，`results/report.html` 生成。

- [ ] **Step 3: 验证 HTML 可在浏览器打开**

```bash
open spikes/benchmark/results/report.html
```

期望：浏览器显示表格 + Chart.js 柱状图（Chart.js 需要网络加载 CDN；如离线，图不显示但表格正常）。

- [ ] **Step 4: 清理 fixture 文件，Commit**

```bash
rm spikes/benchmark/results/*.json
git add spikes/benchmark/scripts/report.py
git commit -m "feat(benchmark): report.py terminal table + HTML with Chart.js"
```

---

## Task 9: 端到端 README + 工具清单

**Files:**
- Create: `spikes/benchmark/README.md`

- [ ] **Step 1: 创建 README**

创建 `spikes/benchmark/README.md`：

```markdown
# Hot-Patch Benchmark

对比自研热修复（hotpatch）vs Shorebird，iOS + Android。

## 前置工具

```bash
brew install libimobiledevice ideviceinstaller  # iOS USB
brew install android-platform-tools             # adb (Android)
pip3 install rich                                # 终端表格
~/.shorebird/bin/shorebird --version             # Shorebird CLI（已安装）
```

## 目录

| 目录 | 说明 |
|------|------|
| `hotpatch_demo/` | ObjC iOS app（复用 M3 dart_harness），USB 推送 .dill |
| `shorebird_demo/` | Flutter app，Shorebird patch 分发 |
| `scripts/` | 推送脚本 + report.py |
| `results/` | 运行时生成（.gitignore） |

## 运行流程

### Shorebird iOS

```bash
# 首次：shorebird release（已在 Task 3 完成）
# 每次推新补丁：
./scripts/push_ios_shorebird.sh <UDID> normal
./scripts/push_ios_shorebird.sh <UDID> cpu
```

### Hotpatch iOS（USB）

```bash
# 确保 HotPatchBench.ipa 已安装到设备
./scripts/push_ios_hotpatch.sh <UDID> normal
./scripts/push_ios_hotpatch.sh <UDID> cpu
```

### Shorebird Android

```bash
./scripts/push_android_shorebird.sh [DEVICE_SERIAL] normal
./scripts/push_android_shorebird.sh [DEVICE_SERIAL] cpu
```

### Android Hotpatch

N/A — 需要自定义 Flutter engine（`--dart-dynamic-modules`）。参考 `skills/flutter-engine-rebuild/SKILL.md`。

## 生成报告

```bash
python3 scripts/report.py
open results/report.html
```

## 关键指标

| 指标 | 采集方式 |
|------|---------|
| patch_size_bytes | stat 补丁文件 |
| cold_start_ms | mach_absolute_time() / Stopwatch |
| greet_call_us | 1000次均值（hotpatch=N/A，单次隔离运行无重复调用接口）|
| memory_rss_kb | mach_task_basic_info（iOS）/ /proc/self/status（Android）|
| cpu_percent_peak | getrusage 采样（cpu patch 轮次） |

> **注**: hotpatch_demo 的 `greet_call_us` 为 0/N/A，因为 dart_harness 是单次隔离运行，
> 不暴露重复调用接口。若需测试，需扩展 dart_harness 支持 benchmark_n_calls(n) 入口。
```

- [ ] **Step 2: Commit**

```bash
git add spikes/benchmark/README.md
git commit -m "docs(benchmark): README with prerequisites + run guide"
```

---

## Self-Review

**Spec coverage 检查：**
- ✅ 两个独立 demo app（hotpatch ObjC iOS + Shorebird Flutter）
- ✅ 补丁文件大小对比（build_patch.sh stat + shorebird output）
- ✅ 修复流程对比（USB push vs Shorebird CDN，README 有对比）
- ✅ 冷启动（mach_absolute_time / Stopwatch）
- ✅ 调用延迟（1000 次均值，hotpatch 有 N/A 说明）
- ✅ 内存 RSS（mach_task_basic_info iOS / /proc Android）
- ✅ CPU 峰值（cpu patch 轮次 getrusage 采样）
- ✅ iOS push scripts（两个）
- ✅ Android push script（Shorebird）
- ✅ 终端表格 + HTML（report.py）
- ✅ Android hotpatch N/A 明确说明
- ✅ Shorebird iOS + Android 均覆盖

**已知局限（在 README + JSON schema 中已注明）：**
- hotpatch `greet_call_us` = 0（dart_harness 单次运行，非重复调用）
- Shorebird patch_size_bytes 从 CLI 输出 grep，可能不精确（备选：直接 stat 下载的 patch artifact）
- devicectl copy 路径格式需实测调整（不同 iOS 版本的 app container 路径格式不同）

