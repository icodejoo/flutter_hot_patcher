# AOT Hot-Patch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 AOT 速度的热修复（零解释开销），对比 M3 bytecode 方案，量化 AOT vs 解释模式的性能差距。

**Architecture:** 两阶段。Phase 1（主线）: 预编译休眠变体——所有 patch 函数随 app 一起 AOT 编译进快照，运行时仅更新 `greetVar` 指针（纯数据段操作，无新可执行代码），100% App Store 合规。Phase 2（扩展）: 运行时加载签名 dylib——开发设备上 dlopen 外部签名 AOT dylib，任意补丁内容均可 AOT 运行，等价于 Shorebird 能力。

**Tech Stack:** ObjC/C（dart_harness 扩展），Dart AOT（gen_snapshot），arm64 assembly，Xcode xcodebuild，devicectl/ideviceinstaller，Python（benchmark report）

---

## Phase 1: 预编译休眠变体（AOT, App Store 合规）

### 工作原理

```
原始快照包含：
  greet()          → return 'ORIGINAL'   (AOT, active)
  greet_patched()  → return 'PATCHED'    (AOT, dormant)
  greet_cpu()      → 10K loop + return   (AOT, dormant)
  applyAOTPatch(n) → greetVar = greet_patched / greet_cpu

"打补丁" = 调用 applyAOTPatch(1) 或 (2)
        = 更新 greetVar 闭包指针
        = 零解释开销，全程 AOT
```

---

### Task 1: 扩展 greet.dart——加入 AOT 休眠变体

**Files:**
- Modify: `spikes/benchmark/hotpatch_demo/greet.dart`

- [ ] **Step 1: 更新 greet.dart**

```dart
library;

@pragma('vm:entry-point')
@pragma('vm:never-inline')
String greet() => 'ORIGINAL';

@pragma('vm:entry-point')
@pragma('vm:never-inline')
String greetAlt() => 'ALT';

// --- AOT Dormant Variants ---

@pragma('vm:entry-point')
@pragma('vm:never-inline')
String greet_patched() => 'PATCHED_AOT';

@pragma('vm:entry-point')
@pragma('vm:never-inline')
String greet_cpu_aot() {
  int sum = 0;
  for (int i = 0; i < 10000; i++) {
    sum += i;
  }
  return sum > 0 ? 'PATCHED_CPU_AOT' : 'PATCHED_CPU_AOT';
}

// --- CHA-defeating indirection (same as M3) ---

@pragma('vm:entry-point')
late String Function() greetVar;

@pragma('vm:entry-point')
@pragma('vm:never-inline')
String callGreet() => greetVar();

@pragma('vm:entry-point')
void setup(List args) {
  greetVar = greetAlt;  // path 1: CHA sees this
  greetVar = greet;     // path 2: always taken
}

// --- AOT Patch Activation ---

@pragma('vm:entry-point')
void applyAOTPatch(List args) {
  final int variant = args.isNotEmpty ? (args[0] as int) : 0;
  greetVar = greetAlt;  // CHA defeat
  if (variant == 1) {
    greetVar = greet_patched;
  } else if (variant == 2) {
    greetVar = greet_cpu_aot;
  }
}

@pragma('vm:entry-point')
String getResult() => callGreet();

// Benchmark: call greetVar N times, return mean microseconds as string
@pragma('vm:entry-point')
String benchmarkGreet(List args) {
  final int n = args.isNotEmpty ? (args[0] as int) : 1000;
  final sw = Stopwatch()..start();
  for (int i = 0; i < n; i++) {
    callGreet();
  }
  sw.stop();
  final us = sw.elapsedMicroseconds / n;
  return us.toStringAsFixed(3);
}

void main() {}
```

- [ ] **Step 2: 重新编译 AOT 快照**

```bash
cd /Users/Cruz/Documents/flutter_hot_patcher/spikes/benchmark/hotpatch_demo
./build_aot.sh
```

但 `build_aot.sh` 复用 M3 的 `snapshot.S`。我们需要从新的 `greet.dart` 重新生成。实际命令：

```bash
GEN_SNAPSHOT=~/engine_ios/src/out/host_release/clang_arm64/gen_snapshot_product
PLATFORM=~/engine_ios/src/out/host_release/vm_platform_strong.dill

"$GEN_SNAPSHOT" \
  --snapshot_kind=app-aot-assembly \
  --assembly=spikes/benchmark/hotpatch_demo/snapshot.S \
  --platform="$PLATFORM" \
  spikes/benchmark/hotpatch_demo/greet.dart

as -arch arm64 spikes/benchmark/hotpatch_demo/snapshot.S \
   -o spikes/benchmark/hotpatch_demo/snapshot.o
```

- [ ] **Step 3: 验证 snapshot.o 包含新符号**

```bash
nm spikes/benchmark/hotpatch_demo/snapshot.o | grep -i "snap\|instr" | head -5
ls -lh spikes/benchmark/hotpatch_demo/snapshot.o
```

期望：snapshot.o 存在，大小约 2MB+

- [ ] **Step 4: Commit**

```bash
git add spikes/benchmark/hotpatch_demo/greet.dart spikes/benchmark/hotpatch_demo/snapshot.S
git commit -m "feat(aot): add AOT dormant variants + benchmarkGreet() to greet.dart"
```

---

### Task 2: 扩展 dart_harness——支持 AOT 补丁激活 + 性能测量

**Files:**
- Modify: `spikes/benchmark/hotpatch_demo/dart_harness.c`
- Modify: `spikes/benchmark/hotpatch_demo/dart_harness.h`

- [ ] **Step 1: 在 dart_harness.h 新增 API**

在 `dart_harness.h` 的 `extern "C"` 块里添加：

```c
/**
 * Apply an AOT patch variant (no bytecode loading required).
 * variant=1: greet_patched (returns 'PATCHED_AOT')
 * variant=2: greet_cpu_aot (10K loop)
 * Returns: result of getResult() after patch applied.
 */
const char* dart_apply_aot_patch(int variant);

/**
 * Benchmark greetVar() for n calls, return mean microseconds as string.
 * Calls benchmarkGreet([n]) in Dart.
 */
const char* dart_benchmark_greet(int n);
```

- [ ] **Step 2: 在 dart_harness.c 实现 dart_apply_aot_patch()**

在 dart_harness.c 末尾添加（在最后一个 `}` 之前）：

```c
const char* dart_apply_aot_patch(int variant) {
    Dart_Handle lib = Dart_RootLibrary();
    if (Dart_IsError(lib)) {
        return "ERROR: no root library";
    }

    // Build args: [variant]
    Dart_Handle args[1];
    args[0] = Dart_NewIntegerFromInt64(variant);

    Dart_Handle list = Dart_NewList(1);
    Dart_ListSetAt(list, 0, args[0]);

    Dart_Handle dart_args[1];
    dart_args[0] = list;

    Dart_Handle result = Dart_Invoke(lib,
        Dart_NewStringFromCString("applyAOTPatch"), 1, dart_args);
    if (Dart_IsError(result)) {
        return Dart_GetError(result);
    }

    // Return getResult() to confirm patch applied
    Dart_Handle get_result = Dart_Invoke(lib,
        Dart_NewStringFromCString("getResult"), 0, NULL);
    if (Dart_IsError(get_result)) {
        return Dart_GetError(get_result);
    }

    const char* cstr = NULL;
    Dart_StringToCString(get_result, &cstr);
    return cstr;
}

const char* dart_benchmark_greet(int n) {
    Dart_Handle lib = Dart_RootLibrary();
    if (Dart_IsError(lib)) return "0.0";

    Dart_Handle list = Dart_NewList(1);
    Dart_ListSetAt(list, 0, Dart_NewIntegerFromInt64(n));
    Dart_Handle dart_args[1];
    dart_args[0] = list;

    Dart_Handle result = Dart_Invoke(lib,
        Dart_NewStringFromCString("benchmarkGreet"), 1, dart_args);
    if (Dart_IsError(result)) return "0.0";

    const char* cstr = NULL;
    Dart_StringToCString(result, &cstr);
    return cstr;
}
```

- [ ] **Step 3: Commit**

```bash
git add spikes/benchmark/hotpatch_demo/dart_harness.c \
        spikes/benchmark/hotpatch_demo/dart_harness.h
git commit -m "feat(aot): dart_harness API for AOT patch activation + benchmark"
```

---

### Task 3: 更新 AppDelegate.m——支持 AOT 模式测量

**Files:**
- Modify: `spikes/benchmark/hotpatch_demo/AppDelegate.m`

- [ ] **Step 1: 新增 AOT benchmark 逻辑**

修改 AppDelegate.m，在读取 `patch_type.txt` 后增加分支：

```objc
// 读取 patch_mode: "bytecode" | "aot" (新增)
NSString *patchModePath = [docs stringByAppendingPathComponent:@"patch_mode.txt"];
NSString *patchMode = @"bytecode";
if ([[NSFileManager defaultManager] fileExistsAtPath:patchModePath]) {
    patchMode = [[NSString stringWithContentsOfFile:patchModePath
                  encoding:NSUTF8StringEncoding error:nil]
                 stringByTrimmingCharactersInSet:[NSCharacterSet whitespaceAndNewlineCharacterSet]];
}

// Cold start timer: covers dart_run() initialization
uint64_t t0 = mach_absolute_time();
const char *bundle_dir = [docs UTF8String];
const char *result;

if ([patchMode isEqualToString:@"aot"]) {
    // AOT mode: dart_run initializes VM, then apply AOT patch (no bytecode loading)
    result = dart_run(bundle_dir);  // baseline: greet() = 'ORIGINAL'
    // Apply AOT patch variant
    int aot_variant = [patchType isEqualToString:@"normal"] ? 1 :
                      [patchType isEqualToString:@"cpu"]    ? 2 : 0;
    if (aot_variant > 0) {
        result = dart_apply_aot_patch(aot_variant);
    }
} else {
    // Bytecode mode (existing M3 path)
    result = dart_run(bundle_dir);
}

uint64_t t1 = mach_absolute_time();
mach_timebase_info_data_t tb;
mach_timebase_info(&tb);
double cold_start_ms = (double)(t1 - t0) * tb.numer / tb.denom / 1e6;

// greet() call latency via benchmarkGreet(1000)
int64_t greet_call_ns = 0;
if ([patchMode isEqualToString:@"aot"]) {
    const char* bench_result = dart_benchmark_greet(1000);
    // bench_result is mean microseconds as string
    double us = atof(bench_result);
    greet_call_ns = (int64_t)(us * 1000.0);  // convert to ns
}
```

更新 JSON 输出：
```objc
NSString *json = [NSString stringWithFormat:
    @"{"
     "\"variant\":\"hotpatch_%@\","    // hotpatch_aot or hotpatch_bytecode
     "\"platform\":\"ios\","
     "\"patch_type\":\"%@\","
     "\"patch_mode\":\"%@\","
     "\"patch_size_bytes\":%ld,"
     "\"cold_start_ms\":%.3f,"
     "\"greet_call_ns\":%lld,"         // nanoseconds for high-res AOT measurement
     "\"memory_rss_kb\":%lld,"
     "\"cpu_percent_peak\":%.1f"
     "}",
    patchMode, patchType, patchMode, patchSizeBytes,
    cold_start_ms, greet_call_ns, rss_kb, cpu_peak];
```

- [ ] **Step 2: Commit**

```bash
git add spikes/benchmark/hotpatch_demo/AppDelegate.m
git commit -m "feat(aot): AppDelegate supports aot/bytecode mode switch"
```

---

### Task 4: Xcode 重新构建 + 安装

**Files:**
- No new files (rebuild existing HotPatchBench.xcodeproj)

- [ ] **Step 1: Archive + Export IPA**

```bash
cd /Users/Cruz/Documents/flutter_hot_patcher/spikes/benchmark/hotpatch_demo

xcodebuild \
  -project HotPatchBench.xcodeproj \
  -scheme HotPatchBench \
  -configuration Release \
  -destination "generic/platform=iOS" \
  CODE_SIGN_STYLE=Automatic \
  DEVELOPMENT_TEAM=7VP87G446C \
  -allowProvisioningUpdates \
  -archivePath /tmp/HotPatchBench_aot.xcarchive \
  archive 2>&1 | grep -E "SUCCEEDED|FAILED|error:" | head -5

xcodebuild -exportArchive \
  -archivePath /tmp/HotPatchBench_aot.xcarchive \
  -exportPath /tmp/HotPatchBench_aot_export \
  -exportOptionsPlist /tmp/ExportOptions.plist \
  2>&1 | grep -E "SUCCEEDED|FAILED" | head -3
```

期望：`ARCHIVE SUCCEEDED` + `EXPORT SUCCEEDED`

- [ ] **Step 2: 安装到设备**

```bash
ideviceinstaller uninstall com.hotpatch.bench.hotpatch 2>&1 | tail -2
ideviceinstaller install /tmp/HotPatchBench_aot_export/HotPatchBench.ipa 2>&1 | tail -3
```

期望：`Install: Complete`

---

### Task 5: 采集 AOT 对比数据

**Files:**
- Create: `spikes/benchmark/scripts/push_ios_hotpatch_aot.sh`

- [ ] **Step 1: 创建 AOT push 脚本**

创建 `spikes/benchmark/scripts/push_ios_hotpatch_aot.sh`：

```bash
#!/usr/bin/env bash
# Push AOT patch mode benchmark to iOS device
# Usage: ./push_ios_hotpatch_aot.sh [UDID] [none|normal|cpu]
set -euo pipefail

UDID="${1:-040F89ED-E7CC-54B0-A7BB-908EE82C0224}"
PATCH_TYPE="${2:-normal}"
BUNDLE_ID="com.hotpatch.bench.hotpatch"
RESULTS="/Users/Cruz/Documents/flutter_hot_patcher/spikes/benchmark/results"

echo "=== HotPatch iOS AOT Mode: $PATCH_TYPE ==="

printf '0'         > /tmp/patch_size.txt   # AOT patch has no file to push
printf "$PATCH_TYPE" > /tmp/patch_type.txt
printf 'aot'       > /tmp/patch_mode.txt
printf ''          > /tmp/empty.txt

for f in patch_size.txt patch_type.txt patch_mode.txt; do
  xcrun devicectl device copy to --device "$UDID" \
    --domain-type appDataContainer --domain-identifier "$BUNDLE_ID" \
    --source "/tmp/$f" --destination "Documents/$f" 2>/dev/null | grep "File on Device" || true
done
xcrun devicectl device copy to --device "$UDID" \
  --domain-type appDataContainer --domain-identifier "$BUNDLE_ID" \
  --source /tmp/empty.txt --destination "Documents/benchmark.json" 2>/dev/null || true

xcrun devicectl device process launch \
  --device "$UDID" --terminate-existing "$BUNDLE_ID" 2>/dev/null
echo "  Waiting 20s..."
sleep 20

xcrun devicectl device copy from --device "$UDID" \
  --domain-type appDataContainer --domain-identifier "$BUNDLE_ID" \
  --source "Documents/benchmark.json" \
  --destination "$RESULTS/hotpatch_aot_ios_${PATCH_TYPE}.json" 2>/dev/null

python3 -c "
import json, os
p = '$RESULTS/hotpatch_aot_ios_${PATCH_TYPE}.json'
if os.path.getsize(p) > 0: print('  Result:', json.dumps(json.load(open(p)), indent=2))
else: print('  EMPTY')
" 2>/dev/null
```

```bash
chmod +x spikes/benchmark/scripts/push_ios_hotpatch_aot.sh
```

- [ ] **Step 2: 采集 AOT none (baseline)**

```bash
./spikes/benchmark/scripts/push_ios_hotpatch_aot.sh 040F89ED-E7CC-54B0-A7BB-908EE82C0224 none
```

期望：`benchmark.json` 包含 `"variant":"hotpatch_aot"`, `"patch_mode":"aot"`, `greet_call_ns > 0`

- [ ] **Step 3: 采集 AOT normal patch**

```bash
./spikes/benchmark/scripts/push_ios_hotpatch_aot.sh 040F89ED-E7CC-54B0-A7BB-908EE82C0224 normal
```

- [ ] **Step 4: 采集 AOT cpu patch**

```bash
./spikes/benchmark/scripts/push_ios_hotpatch_aot.sh 040F89ED-E7CC-54B0-A7BB-908EE82C0224 cpu
```

---

### Task 6: 更新 report.py + 对比报告

**Files:**
- Modify: `spikes/benchmark/scripts/report.py`

- [ ] **Step 1: 在 EXPECTED 中添加 hotpatch_aot**

在 report.py 的 `EXPECTED` 列表中添加：

```python
EXPECTED = [
    ("hotpatch",      "ios", "normal"),   # bytecode (existing)
    ("hotpatch",      "ios", "cpu"),      # bytecode (existing)
    ("hotpatch_aot",  "ios", "none"),     # AOT baseline
    ("hotpatch_aot",  "ios", "normal"),   # AOT patch
    ("hotpatch_aot",  "ios", "cpu"),      # AOT cpu patch
    ("shorebird",     "ios", "none"),
    ("shorebird",     "ios", "normal"),
    ("shorebird",     "ios", "cpu"),
    ...
]
```

result file 名: `hotpatch_aot_ios_normal.json` 等。

- [ ] **Step 2: 添加 greet_call_ns 到 METRICS**

```python
METRICS = [
    ("patch_size_bytes", "Patch Size",    lambda v: f"{v:,} B"),
    ("cold_start_ms",    "Cold Start",    lambda v: f"{v:.3f} ms"),
    ("greet_call_us",    "greet() μs",    lambda v: f"{v:.2f} μs" if v else "N/A"),
    ("greet_call_ns",    "greet() ns",    lambda v: f"{v} ns" if v else "N/A"),  # new
    ("memory_rss_kb",    "RSS",           lambda v: f"{v:,} KB"),
    ("cpu_percent_peak", "CPU Peak",      lambda v: f"{v:.1f}%"),
]
```

- [ ] **Step 3: 生成对比报告并验证**

```bash
python3 spikes/benchmark/scripts/report.py
open spikes/benchmark/results/report.html
```

期望：表格显示 hotpatch_aot 的 `greet_call_ns` 明显小于 shorebird 的 `greet_call_us`（如 ~50ns vs ~807μs = 约 16,000× 差距）

- [ ] **Step 4: Commit**

```bash
git add spikes/benchmark/scripts/push_ios_hotpatch_aot.sh \
        spikes/benchmark/scripts/report.py \
        spikes/benchmark/results/
git commit -m "feat(aot): AOT benchmark scripts + updated report with aot vs bytecode comparison"
```

---

## Phase 2: 运行时加载签名 AOT Dylib（Development Device）

> 仅在 Phase 1 完成后执行。需要开发设备，不适用 App Store。

### Task 7: 编译 patch 为 arm64 dylib

- [ ] **Step 1: 从 greet_patched.dart 生成 AOT assembly**

```bash
GEN_SNAPSHOT=~/engine_ios/src/out/host_release/clang_arm64/gen_snapshot_product
PLATFORM=~/engine_ios/src/out/host_release/vm_platform_strong.dill

# Create minimal Dart program for the patch function only
cat > /tmp/patch_for_dylib.dart << 'DART'
library patch_lib;

@pragma('vm:entry-point')
@pragma('vm:never-inline')
String greet_patch_impl() => 'PATCHED_DYLIB_AOT';

void main() {}
DART

"$GEN_SNAPSHOT" \
  --snapshot_kind=app-aot-assembly \
  --assembly=/tmp/patch_dylib.S \
  --platform="$PLATFORM" \
  /tmp/patch_for_dylib.dart
```

- [ ] **Step 2: 编译为 dylib**

```bash
as -arch arm64 /tmp/patch_dylib.S -o /tmp/patch_dylib.o

clang -arch arm64 -dynamiclib \
  -target arm64-apple-ios16.0 \
  -isysroot $(xcrun --sdk iphoneos --show-sdk-path) \
  /tmp/patch_dylib.o \
  -install_name @rpath/patch.dylib \
  -o /tmp/patch_aot.dylib
```

- [ ] **Step 3: 签名 dylib（使用开发 team cert）**

```bash
codesign -s "Apple Development" \
  --entitlements spikes/benchmark/hotpatch_demo/entitlements.plist \
  /tmp/patch_aot.dylib
```

（entitlements.plist 使用同 app 的 entitlements）

- [ ] **Step 4: Push dylib 到设备并测试**

```bash
xcrun devicectl device copy to \
  --device 040F89ED-E7CC-54B0-A7BB-908EE82C0224 \
  --domain-type appDataContainer \
  --domain-identifier com.hotpatch.bench.hotpatch \
  --source /tmp/patch_aot.dylib \
  --destination "Documents/patch_aot.dylib"
```

- [ ] **Step 5: dart_harness 添加 dlopen 加载路径**

在 dart_harness.c 添加 `dart_load_aot_dylib(path)` 函数：

```c
const char* dart_load_aot_dylib(const char* dylib_path) {
    void* handle = dlopen(dylib_path, RTLD_NOW | RTLD_LOCAL);
    if (!handle) {
        return dlerror();
    }
    // Find greet function symbol
    typedef const char* (*GreetFn)(void);
    // The AOT symbol for greet_patch_impl — find via nm
    // ...
    return "DYLIB_LOADED";
}
```

Note: AOT dylib symbol resolution is complex — the function is in the isolate snapshot, not exported as a C symbol. This step may require additional engine support.

---

## Self-Review

**Phase 1 spec coverage:**
- ✅ AOT dormant variants in snapshot (greet_patched, greet_cpu_aot)
- ✅ applyAOTPatch() for data-only patch activation
- ✅ benchmarkGreet(n) for 1000-call latency measurement
- ✅ dart_apply_aot_patch() C API
- ✅ dart_benchmark_greet() C API
- ✅ AppDelegate.m aot/bytecode mode switch
- ✅ push_ios_hotpatch_aot.sh script
- ✅ report.py updated with hotpatch_aot rows + greet_call_ns metric
- ✅ Comparison experiment: AOT ns vs bytecode μs vs shorebird μs

**Phase 2:** Dylib approach requires validation of symbol resolution — marked as spike.

**Known constraint:** Phase 1 AOT patches are pre-compiled and shipped with the app. "New" patches require a new app release. Phase 2 removes this constraint but requires development cert.
