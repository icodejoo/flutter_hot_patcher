# HotPatchBench Xcode Setup

`HotPatchBench.xcodeproj` 已完整创建，包含所有源文件引用和 Build Settings。

## Step 1: 编译 AOT 快照

```bash
cd spikes/benchmark/hotpatch_demo
./build_aot.sh
```

输出 `snapshot.o`（arm64 AOT of greet.dart，约 1.9MB）。

## Step 2: 用 Xcode 打开、签名、部署

```bash
open spikes/benchmark/hotpatch_demo/HotPatchBench.xcodeproj
```

在 Xcode 中：
1. 选择 HotPatchBench target → Signing & Capabilities → 设置你的 Development Team
2. 连接 iOS 设备，选择目标设备，Product → Run

## Step 3: 运行 Push 脚本采集数据

```bash
cd spikes/benchmark
./scripts/push_ios_hotpatch.sh <UDID> normal
./scripts/push_ios_hotpatch.sh <UDID> cpu
```

## 已包含的 Build Settings

| 设置 | 值 |
|------|-----|
| Bundle ID | com.hotpatch.bench.hotpatch |
| ARCHS | arm64 |
| LIBRARY_SEARCH_PATHS | spikes/m3_ios_realdevice/build |
| HEADER_SEARCH_PATHS | /Users/Cruz/dart/sdk/runtime/include |
| OTHER_LDFLAGS | dart_aot_ios, flutter_hotpatch_updater, dart_aotruntime_product, ... |

> 如果 engine 路径变更，在 Xcode Build Settings 里更新 LIBRARY_SEARCH_PATHS。
