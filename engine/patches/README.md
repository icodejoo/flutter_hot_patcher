# X1 引擎的 Shorebird 集成改动

> **产品线不需要本目录的任何补丁。**（2026-08-18 定案）
>
> Route-B 是唯一的产品方案，它全程用 Shorebird 的预编译产物：
> `gen_snapshot_arm64` / `analyze_snapshot_arm64` / `patch` / `flutter`，
> 加上纯 Python 的 `tools/linker.py`。产品发布链路（`tools/fhpb`）
> 一次也不碰自建引擎，因此**不需要重建引擎、也不需要打这里的补丁**。
>
> 本目录整体转为**研究档案**，按路线归属如下：
>
> | 补丁 | 归属 | 产品是否需要 |
> |---|---|---|
> | `shorebird_integration.diff` + `shorebird_files/` | X1 引擎集成 Shorebird 引擎层 | 否 |
> | `dartsdk_collect_all_codes.diff` | 自研 analyze_snapshot 的枚举修复 | 否（产品用 Shorebird 的） |
> | `dartsdk_analyze_snapshot_macos.diff` | 同上，macOS 宿主 | 否 |
> | `dartsdk_simulator_ffi.diff` | **Route-A/B 共存**才需要 | 否 |
> | `dartsdk_dynamic_modules_aot.diff` | **Route-A 专用** | 否 |
>
> 最后两项只为「同一个引擎里同时跑 Route-A 和 Route-B」而存在。
> 既然 Route-A 已出局，它们不再有产品意义，仅作研究记录保留。
> 清理前的完整存档：tag `route-a-research-backup-20260818`。


引擎树（`~/engine_ios`）不在本仓库版本控制内，故把改动存于此以便复现。
所有内容遵循 `CLAUDE.md` 的规则 2/3：能拿来用的直接拷，只有闭源缺口才自实现。

## 1. 直接拷用的上游文件（规则 2，勿重写）

从 `~/.shorebird/bin/cache/flutter/<rev>/engine/src/flutter/` 原样拷贝：

```
runtime/shorebird/{patch_cache,patch_mapping}.{h,cc}  runtime/shorebird/BUILD.gn
shell/common/shorebird/{shorebird,updater,snapshots_data_handle}.{h,cc}
shell/common/shorebird/{BUILD.gn,build_rust_updater.gni,build_rust_updater.py,list_rust_files.py}
```

Rust updater 取自 `https://github.com/shorebirdtech/updater.git` @ `1f85c4ab...`
（DEPS 锁定的 revision），置于 `flutter/third_party/updater`。
构建需 `IPHONEOS_DEPLOYMENT_TARGET`，否则报 `___chkstk_darwin` 未定义。

## 2. 我们的改动

`shorebird_integration.diff` —— 对已跟踪文件的改动：

| 文件 | 改动 |
|---|---|
| `runtime/dart_snapshot.cc` | 插入 `ResolveIsolateData/Instructions` 两处钩子 + `ReportLaunchStart()` |
| `runtime/BUILD.gn` | 挂 `shell/common/shorebird:updater` 与（is_ios）`runtime/shorebird:patch_cache` |
| `common/config.gni` | 定义 `SHOREBIRD_PLATFORM_SUPPORTED` / `SHOREBIRD_USE_INTERPRETER` |
| `shell/platform/darwin/ios/BUILD.gn` | framework 挂 `shorebird` 依赖 |
| `.../ios/framework/Source/FlutterDartProject.mm` | 调 `ConfigureShorebird`（移植自上游 iOS 实现） |

`shorebird_files/` —— 需要就地修改的上游文件副本，共三处适配：

**(a) 版本漂移：字段改名。** 上游是 `settings.application_library_paths`（复数），
本引擎为 `application_library_path`（单数，`common/settings.h:140`），类型同为
`std::vector<std::string>`。改动位于 `shorebird.cc`（5 处）。

**(b) 规则 3：三个私有 dart-sdk API 就地实现。** 上游引擎层调用了只存在于
**私有** `shorebirdtech/dart-sdk` 的 C API，我们的 dart-sdk 没有：

| 缺失 API | 我们的实现 | 依据 |
|---|---|---|
| `Dart_SnapshotDataSize` | `FhpSnapshotDataSize`（`patch_mapping.cc`） | Dart 快照头是公开布局（`runtime/vm/snapshot.h:36-40`）：offset 0 magic `0xdcdcf5f5`、offset 4 `int64 length` |
| `Dart_SnapshotInstrSize` | `FhpSnapshotInstrSize` → 返回 0 | instructions 段无长度头；引擎在 `DART_SNAPSHOT_STATIC_LINK` 路径上对这两段一律传 size=0，VM 自行确定范围，沿用同一约定 |
| `Shorebird_ReadLinkHeader` | `FhpReadLinkHeader`（`patch_cache.cc`） | 解析的是**我们自己 linker 定义**的 `.vmcode` 容器头，格式见 `spikes/b_route_phase2_groundtruth/GROUND_TRUTH.md` §1，与 `tools/linker.py` 的 `_header_size()` 对齐 |

**(c) `Dart_LoadELF` 签名差异。** 上游多传一个 `dart::bin::kReadOnly` mode 参数；
本引擎的 `Dart_LoadELF`（`runtime/bin/elf_loader.h:41`）只有 7 个形参，故去掉该实参。

## 3. 复现步骤

```bash
export PATH="$HOME/depot_tools:$PATH"          # gn 需要 vpython3
# 1) 拷上游文件（见 §1）+ 置入 Rust updater
# 2) 应用本目录的 diff 与 shorebird_files/ 覆盖
# 3) gn gen 并重打 toolchain 补丁（见 docs/X1_ENGINE_REBUILD_FIX.md）
cd ~/engine_ios/src && ./flutter/third_party/gn/gn gen out/ios_release
#    重打 -F <iPhoneOS.sdk SubFrameworks> 补丁
ninja -C out/ios_release libFlutter.dylib     # 不要用 | tail 包住
```

前置条件：`docs/X1_ENGINE_REBUILD_FIX.md` 的 BoringSSL 双 label 修复必须已应用，
否则链接期 20 个重复符号。

## `dartsdk_simulator_ffi.diff`（2026-08-14）

让 `dart:ffi` 在 ARM64 Simulator 下可用，从而 Flutter 的 platform channel
不再在 binding 初始化阶段全挂。三个文件：

- `runtime/platform/globals.h` — A1 的强开 hunk，外加新的 `SIMULATOR_HOST_ARCH_MATCH`
  （host arch == target arch，即 ABI 屏障不存在）。**patch 自带 A1**，可直接打到干净 SDK 上。
- `runtime/lib/ffi_dynamic_library.cc` — 禁用条件改为按 ABI 屏障而非「有没有 Simulator」
- `runtime/vm/simulator_arm64.cc` — BLR 目标落在 Dart 指令段之外时逃逸为真实 native 调用
  （x0-x7 + d0-d7 + 256 B 栈参数窗口，窗口按 `stack_base()` 裁剪）
- `runtime/vm/dart_api_impl.cc` — `Dart_ShorebirdLoadVmcode` 的守卫补上 `TARGET_ARCH_ARM64`；
  只按 `USING_SIMULATOR` 守卫会让 target-x64 的 host 构建编不过

背景与实测数据见 `docs/ROUTE_A_RESEARCH.md` §3；回归 `tools/tests/test_sim_ffi.sh`。
仅在 macOS arm64 上验证过，iOS 构建未验证。

## `dartsdk_dynamic_modules_aot.diff`（2026-08-14）

`dispatch_table_generator.cc` 的 `NumberSelectors` 里，把
`Function has no assigned selector ID` 的 FATAL 改成跳过。

带 `--dynamic-interface` 编 Flutter app 时，annotator 会保活一些从不被动态派发的
成员（实测 `package:flutter/src/widgets/shortcuts.dart` 的 `KeySet._set_`），
TFA 不会给它们分配 table selector。同文件的 `SetupSelectorRows` 本来就跳过
`kInvalidSelectorId`，只有这处 FATAL 没有。

不打这个补丁，`flutter build ios --release` 带 dynamic interface 必失败。
详见 `docs/ROUTE_A_RESEARCH.md` §7。
