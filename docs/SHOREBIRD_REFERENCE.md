# Shorebird 参照基线：开源/闭源清单与集成架构

> 核准日期：2026-08-13
> 全部结论均由本机实测得出，每条附可复现命令。标注 **[实测]** 的有命令输出支撑。

本文是 `CLAUDE.md` 三条顶级规则的事实依据。规则要能执行，前提是"哪些开源、哪些闭源"必须准确 ——
判错方向会导致重复实现开源代码（违反规则 2），或凭空发挥去写闭源部分（违反规则 3）。

---

## 0. 结论速查

| 组件 | 开源？ | 依据 | 规则归属 |
|---|---|---|---|
| `shorebirdtech/flutter`（引擎 fork） | **✅ 开源** | 公开可 clone，源码已在本机 | 规则 2：直接用 |
| `shorebirdtech/updater`（Rust） | **✅ 开源** | 公开可 clone | 规则 2：直接用 |
| `shorebird_cli` | **✅ 开源** | 本机有源码 | 规则 2：直接用 |
| `shorebirdtech/dart-sdk`（VM/Simulator） | **❌ 私有** | `Repository not found`；DEPS 走 SSH | 规则 3：自实现 |
| `aot_tools`（linker） | **❌ 闭源** | 只有 `aot-tools.dill` | 规则 3：自实现 |
| 服务端 / check-update 协议 | **❌ 闭源** | 无源码 | 规则 3：自实现 |

---

## 1. 开源部分（规则 2 适用：直接拿来用）

### 1.1 `shorebirdtech/flutter` —— 引擎 fork

**[实测]** 公开可访问，且完整源码已在本机：

```bash
git ls-remote https://github.com/shorebirdtech/flutter.git HEAD
# → c2515c46c7fca511e39735a615f0f12f3dca6230

SBF=~/.shorebird/bin/cache/flutter/c15ef6379403a0a55531a058bdb2c8e55bc05c98
git -C "$SBF" remote -v          # → https://github.com/shorebirdtech/flutter.git
ls "$SBF/engine/src/flutter"     # 完整引擎源码
```

补丁加载相关的**全部**文件（照抄，不要重写）：

```
flutter/runtime/dart_snapshot.cc                      # 钩子，约 12 行（见 §3.1）
flutter/runtime/shorebird/patch_cache.{h,cc}          # Dart_LoadELF 载入 .vmcode + 弱引用缓存
flutter/runtime/shorebird/patch_mapping.{h,cc}        # 适配成 fml::Mapping
flutter/runtime/shorebird/BUILD.gn
flutter/shell/common/shorebird/shorebird.{h,cc}       # ConfigureShorebird
flutter/shell/common/shorebird/updater.{h,cc}         # Rust updater 的 C++ 封装
flutter/shell/common/shorebird/snapshots_data_handle.{h,cc}
flutter/shell/common/shorebird/build_rust_updater.{gni,py}
flutter/shell/common/shorebird/*_unittests.cc         # 连测试一起
flutter/shell/platform/darwin/.../FlutterEngine.mm    # 调 ConfigureShorebird（:683）
flutter/shell/platform/android/flutter_main.cc        # 同上（:167）
flutter/shell/platform/linux/fl_shorebird.cc          # 同上（:53）
```

编译开关：`SHOREBIRD_USE_INTERPRETER`（补丁加载全部在这个宏内）。

### 1.2 `shorebirdtech/updater` —— Rust updater

**[实测]** 公开，且 HEAD 与 DEPS 锁定的 revision 完全一致：

```bash
git ls-remote https://github.com/shorebirdtech/updater.git HEAD
# → 1f85c4ab1ee5b540269b9859c75e1bffbb9050c7
grep -A1 updater_git "$SBF/DEPS"
#   "updater_git": "https://github.com/shorebirdtech/updater.git",
#   "updater_rev": "1f85c4ab1ee5b540269b9859c75e1bffbb9050c7",
```

DEPS 把它挂在 `engine/src/flutter/third_party/updater`。

职责（从 framework 二进制 `strings` 可见）：补丁下载、Ed25519 签名校验、staging、
状态机（`PatchState::Downloading/Downloaded/Installed/Bad`）、boot 崩溃看门狗
（`BootCrash`/`InvalidPatchBytes`/`InstallHashMismatch`）、磁盘缓存、网络钩子。

导出的 C ABI 共 10 个 —— **注意里面没有任何"加载补丁"的函数**：

```
shorebird_init
shorebird_next_boot_patch_number / shorebird_next_boot_patch_path
shorebird_current_boot_patch_number
shorebird_check_for_downloadable_update
shorebird_report_launch_start / _success / _failure
shorebird_free_string / shorebird_free_update_result
```

复现：
```bash
FW="$SBF/bin/cache/artifacts/engine/ios-release/Flutter.xcframework/ios-arm64/Flutter.framework/Flutter"
dyld_info -exports "$FW" | grep -oE "_shorebird[A-Za-z_]*" | sort -u
```

### 1.3 `shorebird_cli`

**[实测]** 源码在 `~/.shorebird/packages/shorebird_cli`，
含 `lib/src/executables/aot_tools.dart`（调用 linker 的编排层，注意 linker 本体是闭源的）。

---

## 2. 闭源部分（规则 3 适用：自实现 + 从接口形状反推）

### 2.1 `shorebirdtech/dart-sdk` —— **私有**

**[实测]** 仓库不公开，本机缓存里也没有它的源码，只有编译产物：

```bash
git ls-remote https://github.com/shorebirdtech/dart-sdk.git HEAD
# → remote: Repository not found.

grep dart_sdk_git "$SBF/DEPS"
# → "dart_sdk_git": "git@github.com:shorebirdtech/dart-sdk.git",   ← SSH，需授权

ls "$SBF/engine/src/flutter/third_party/dart"    # → No such file or directory
```

可用的只有二进制：`gen_snapshot_arm64`、带 `--shorebird` 的 `analyze_snapshot_arm64`、
以及内含 `ShorebirdSimToCpuCall` 的 `Flutter.framework`。

**这一条决定了本项目最难的那部分工作是合规的**：我们在 `~/dart/sdk` 上的 8 条自研 commit
（SimulatorToCPU、BLR/BL intercept、link table 钩子、`Dart_ShorebirdLoadVmcode`、
`Dart_DumpSnapshotInformationShorebirdAsJson`）对应的正是这个私有仓库 → 属于规则 3。
而且命名直接对齐 Shorebird 的接口形状，这正是规则 3 要求的做法。

### 2.2 `aot_tools link` —— linker

**[实测]** 只有编译产物，无源码：

```bash
ls ~/.shorebird/bin/cache/artifacts/aot-tools/*/
# → aot-tools.dill  aot-tools.dill.stamp
```

我们的对应实现：`tools/linker.py`。

**这是规则 3 的标杆范例**：`.vmcode` 容器布局、LinkTable 编码、
`subgraph_hash` 作为链接门槛等等，全部由 `spikes/b_route_phase2_groundtruth/GROUND_TRUTH.md`
用 Shorebird 自己的二进制离线实测反推，并以它自己的 `link_table.txt` 和
`analyze_snapshot` JSON 作为独立 oracle 交叉验证。

### 2.3 服务端 / check-update 协议

无源码。我们的对应实现：`tools/patch_server/`。
协议形状可从 framework 二进制里的 `PatchCheckRequest` / `PatchCheckResponse` 字段名反推。

---

## 3. Shorebird 的集成架构（源码级）

### 3.1 唯一的引擎钩子

`flutter/runtime/dart_snapshot.cc` 的 `ResolveIsolateData()`：

```cpp
shorebird::Updater::Instance().ReportLaunchStart();
#if SHOREBIRD_USE_INTERPRETER
  if (auto mapping = TryLoadFromPatch(settings.application_library_paths,
                                      DartSnapshot::kIsolateDataSymbol)) {
    return mapping;
  }
#endif
  return SearchMapping(...);   // 没补丁 → 回落基线，正常启动
```

`ResolveIsolateInstructions()` 是对称的一段。两处合计约 12 行。

### 3.2 补丁如何被发现与载入

```cpp
// runtime/shorebird/patch_cache.cc:124  TryLoadFromPatch
const auto& patch_path = native_library_paths.front();
bool is_patch = patch_path.find(".vmcode") != std::string::npos;
if (!is_patch) return nullptr;
// 补丁只含 isolate data/instructions，不含 VM 的 → 其他 symbol 一律回落
auto cache_entry = PatchCache::Instance().GetOrLoad(patch_path);
```

`PatchCacheEntry` 用 `Dart_LoadELF`（`third_party/dart/runtime/bin/elf_loader.h`）
把 `.vmcode` 当 ELF 载入，取出 `isolate_data` 与 `isolate_instructions` 两个指针。

### 3.3 完整启动链路

1. 各平台引擎启动时调 `ConfigureShorebird(settings, ...)`
   （darwin `FlutterEngine.mm:683` / android `flutter_main.cc:167` / linux `fl_shorebird.cc:53`）
2. 它向 Rust updater 询问 `Updater::Instance().NextBootPatchPath()`
3. 有补丁 → 把 `.vmcode` 路径插到 `settings.application_library_paths` **最前面**（`shorebird.cc:273`）
4. `ResolveIsolateData/Instructions` 认出 `.vmcode` → `Dart_LoadELF` 载入
5. 失败或无补丁 → `SearchMapping` 回落基线
6. 改动过的函数由 Simulator 解释执行，未改动的经 `ShorebirdSimToCpuCall` 桥回原生

**关键性质：补丁在第一行 Dart 代码执行之前就已生效**，因此启动路径上的函数也能被补。
任何"Dart 层加载"的方案都做不到这一点。

### 3.4 [实测] 它对 Dart 侧零暴露

| 指标 | Shorebird（arm64 device） | 我们的 X1 引擎 |
|---|---|---|
| 导出符号总数 | 9,671 | 102 |
| `Dart_*` C API 导出 | **0** | 0 |
| Dart 可见的加载 API | **无** | 无 |
| `shorebird_*` 导出 | 10 | 0 |
| `dart:ui` 改动 | **无** | 无 |

**推论：不要 fork `dart:ui`。** 正确的挂载点是引擎内部的快照解析，不是任何 Dart 可见接口。
`dart:_internal` 是平台私有库这个障碍，在正确的架构下根本不出现。

---

## 4. 我们的源项目 vs Shorebird 的

**[实测]** 我们 fork 的是**上游**，不是 Shorebird：

| | 我们的 | Shorebird 的 |
|---|---|---|
| 引擎 | `flutter/engine.git` @ `ae5c3603`（上游）+ 22 处未提交改动 | `shorebirdtech/flutter` @ `c15ef637` |
| Dart SDK | `dart.googlesource.com/sdk.git` @ `37bbc285d8d`（上游）+ 8 条自研 commit + 35 处未提交改动 | `shorebirdtech/dart-sdk` @ `db98bdaa`（私有）|

复现：
```bash
git -C ~/engine_ios/src/flutter remote -v     # → flutter/engine.git
git -C ~/dart/sdk remote -v                   # → dart.googlesource.com/sdk.git
git -C ~/dart/sdk log --oneline -9            # 8 条自研 commit 在 37bbc285d8d 之上
```

我们那 8 条 Dart SDK commit：

```
3237f7d7bf7 feat(B2+B4): Dart_DumpSnapshotInformationShorebirdAsJson + Dart_ShorebirdLoadVmcode
d8ddec71daf feat(B2): Dart_DumpSnapshotInformationShorebirdAsJson -- --shorebird analyze_snapshot mode
b4e19db7571 fix(A2+A5): guard InvokeWithTHR with __aarch64__ for cross-compilation
4744cad6bf0 feat(A5): BL intercept + configurable SimToCpu threshold
a412c7cd577 fix(A7): SimulatorToCPU icount threshold (50M) skips startup phase
804e216019e feat(A2+A7): SimulatorToCPU with THR+PP via inline asm; vmcode loader
2be0d4cb2cb fix(A2): SimulatorToCPU BLR intercept now working — 2 bugs fixed
8c0b4fc0b05 feat(A2): SimulatorToCPU prototype — BLR link table hook + assembly shim
```

### 4.1 规则判定

| 我们的实现 | 对应 Shorebird 组件 | 该组件是否开源 | 判定 |
|---|---|---|---|
| `~/dart/sdk` 的 8 条 commit（Simulator/vmcode loader） | `shorebirdtech/dart-sdk` | ❌ 私有 | **✅ 规则 3 合规**，且已按接口形状对齐 |
| `tools/linker.py` | `aot_tools link` | ❌ 闭源 | **✅ 规则 3 合规**，有 oracle 交叉验证 |
| `tools/patch_server/` | 服务端协议 | ❌ 闭源 | **✅ 规则 3 合规** |
| `tools/updater/`（自研 Rust） | `shorebirdtech/updater` | **✅ 开源** | **❌ 违反规则 2** —— 应改用上游 |
| 引擎集成层（尚未实现） | `runtime/shorebird/` + `shell/common/shorebird/` + `dart_snapshot.cc` 钩子 | **✅ 开源** | **规则 2：必须直接采用，不要自己写** |

### 4.2 待偿还的技术债

1. **`tools/updater/` 重复实现了开源的 `shorebirdtech/updater`** —— 应替换为上游。
2. **引擎侧集成尚缺，且必须采用 Shorebird 的公开实现**，不能自研。
   前置阻碍：`~/engine_ios` 目前无法重建（`src/third_party/boringssl` 是指向
   `src/flutter/third_party/boringssl` 的符号链接，gn 因此把同一份源码在两个 label 下
   各编译一遍，链接时 20 个 BoringSSL 重复符号）。
3. **A-route（KBC）按规则 1 不进产品** —— Shorebird 无此能力。它另有两个悬案：
   `dbc.dart` 的 `bytecodeFormatVersion` 是本地手改，且 `loadDynamicModule` 位于
   平台私有库 `dart:_internal`。
