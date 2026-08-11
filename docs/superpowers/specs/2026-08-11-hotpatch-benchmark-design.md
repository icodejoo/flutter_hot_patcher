# 热修复对比 Benchmark 设计文档

**日期**: 2026-08-11  
**范围**: 自研热修复 vs Shorebird，iOS + Android，USB 推送，全指标对比

---

## 目标

用两个最小 demo app，通过 USB 数据线推送补丁（不走公网），全面对比：
1. 补丁文件大小
2. 修复流程复杂度
3. 修复后执行性能（冷启动、调用延迟、内存、CPU 峰值）

---

## 目录结构

```
spikes/benchmark/
├── shorebird_demo/            # Flutter app，集成 Shorebird SDK
│   ├── lib/main.dart          # 埋点主逻辑
│   ├── lib/greet.dart         # 原始：return "ORIGINAL"
│   ├── patches/
│   │   ├── greet_v1.dart      # 普通补丁：return "PATCHED"
│   │   └── greet_cpu.dart     # CPU 补丁：10M 循环
│   ├── ios/
│   └── android/
├── hotpatch_demo/             # 自研热修复 Flutter app
│   ├── lib/main.dart
│   ├── lib/greet.dart
│   ├── patches/
│   │   ├── greet_v1.dart
│   │   └── greet_cpu.dart
│   ├── ios/                   # 复用 M3 dart_harness + builtin_shim
│   └── android/               # JNI 桥接 dart_harness
├── scripts/
│   ├── push_ios_shorebird.sh
│   ├── push_ios_hotpatch.sh
│   ├── push_android_shorebird.sh
│   ├── push_android_hotpatch.sh
│   └── report.py
└── results/                   # 运行时生成，gitignore
    ├── shorebird_ios.json
    ├── shorebird_android.json
    ├── hotpatch_ios.json
    ├── hotpatch_android.json
    └── report.html
```

---

## 两个 Demo App

### 共同约定

- Flutter 3.x，target: iOS arm64 release + Android arm64 release
- 同一个 `greet()` 函数作为被补丁目标
- App 启动后自动执行测量流程，写结果 JSON 到 Documents 目录后退出

### Shorebird Demo

- `shorebird init` + `shorebird release`
- 补丁文件通过 `shorebird patch --staging` 生成后，用文件服务绕过公网：
  在 Mac 上起 `python3 -m http.server 8080`，设备端通过 USB tunnel（`iproxy` iOS / `adb forward` Android）访问 `127.0.0.1:8080`，等价"不走公网"
- Shorebird updater 在 app 启动时拉取 patch（localhost），完成热修复

### 自研 Hotpatch Demo

- iOS：复用 M3 的 `dart_harness.c` + `builtin_shim.cpp`，patch 为 `.dill` 文件，通过 `devicectl device copy` 推到 Documents，app 启动时加载
- Android：JNI 桥接 `dart_harness`，patch 同样为 `.dill`，`adb push` 到 app files 目录

---

## 埋点协议

每次运行写入 `benchmark.json`：

```json
{
  "variant": "shorebird|hotpatch",
  "platform": "ios|android",
  "patch_type": "normal|cpu",
  "patch_size_bytes": 0,
  "cold_start_ms": 0,
  "greet_call_us": 0,
  "memory_rss_kb": 0,
  "cpu_percent_peak": 0.0
}
```

| 字段 | 采集方式 |
|------|---------|
| `patch_size_bytes` | 脚本 `stat` 补丁文件，通过环境变量或文件旁注入 app |
| `cold_start_ms` | `main()` 入口 `Stopwatch` 到首次 `greet()` 返回 |
| `greet_call_us` | 1000 次 `greet()` 调用均值（微秒） |
| `memory_rss_kb` | FFI 调用 `getrusage`（Android）/ `proc_pid_rusage`（iOS）|
| `cpu_percent_peak` | `Timer.periodic(100ms)` 采样 10 次，FFI 读 `getrusage.ru_utime` diff，取峰值 |

---

## CPU 补丁

```dart
// patches/greet_cpu.dart
String greet() {
  int sum = 0;
  for (int i = 0; i < 10000000; i++) { sum += i; }
  return "PATCHED_CPU:$sum";
}
```

CPU 采样在 `greet_cpu` 测量轮次使用，普通补丁轮次 `cpu_percent_peak` 填 0。

---

## 推送脚本

### iOS

**push_ios_shorebird.sh**
1. `flutter build ipa --release`（shorebird_demo）
2. `ideviceinstaller -i` 安装 IPA
3. 启动本地 http-server + `iproxy 8080 8080 <udid>`
4. `devicectl device process launch` 启动 app
5. 等待 8s（updater 下载 + 测量）
6. `devicectl device copy from` 取回 `benchmark.json`
7. 关闭 iproxy + http-server

**push_ios_hotpatch.sh**
1. `flutter build ipa --release`（hotpatch_demo）
2. `ideviceinstaller -i` 安装 IPA
3. `PATCH_SIZE=$(stat -f%z patch.dill)`
4. `devicectl device copy to` 推送 `patch.dill` + `patch_size.txt`
5. `devicectl device process launch`，等待 5s
6. `devicectl device copy from` 取回 `benchmark.json`

### Android

**push_android_shorebird.sh**
1. `flutter build apk --release`
2. `adb install -r`
3. 启动本地 http-server + `adb reverse tcp:8080 tcp:8080`
4. `adb shell am start`，等待 8s
5. `adb pull` 取回 `benchmark.json`

**push_android_hotpatch.sh**
1. `flutter build apk --release`
2. `adb install -r`
3. `adb push patch.dill /sdcard/Android/data/<pkg>/files/`
4. `adb push patch_size.txt`（旁注大小）
5. `adb shell am start`，等待 5s
6. `adb pull` 取回 `benchmark.json`

---

## 报告生成

`report.py`（依赖 `rich`，标准库 json/pathlib）：

1. 读取 `results/*.json`（允许部分缺失，缺失格显示 `N/A`）
2. 终端：`rich.table.Table`，行=方案×平台，列=五个指标
3. HTML：内联 Chart.js，四张柱状图（每指标一张，四条柱），写入 `results/report.html`

---

## 成功标准

- [ ] 四个组合（shorebird-ios / shorebird-android / hotpatch-ios / hotpatch-android）均能产出非零 JSON
- [ ] 普通补丁 + CPU 补丁各跑一遍（共 8 个 JSON）
- [ ] `report.html` 本地浏览器可打开，数据正确显示
- [ ] 补丁推送全程不依赖公网（localhost tunnel 或直接文件推送）

---

## 已知约束

- Shorebird 的 `--local-patch` 或 staging channel 需要 Shorebird 账号（免费 tier 够用）
- iOS 推送需要 `ideviceinstaller`（`brew install ideviceinstaller`）+ 设备已信任 Mac
- Android 需要 `adb`（Android SDK platform-tools）
- `rich` 需要 `pip install rich`
