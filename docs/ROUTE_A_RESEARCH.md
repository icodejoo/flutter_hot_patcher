# Route-A 研究复盘（2026-08-14）

> 归档记录见 `archive/route_a/README.md`。本文推翻其中两条「关键约束」，
> 并给出第一份跑在**我们自己的 VM**（`~/dart/sdk`）上的 Route-A 端到端验证。
> Route-A 仍按顶级规则 1 停留在研究能力，不进产品线。

## TL;DR

| 归档时的说法 | 复核结论 |
|---|---|
| 约束 3：`loadDynamicModule` 在 `dart:_internal`，Flutter app 无法 import | **错**。CFE 白名单放行名为 `dart_internal` / `dynamic_modules` 的包；stock Flutter 3.29.0 实测通过 |
| 约束 4：X1 跑不了 Flutter app（Simulator 下 FFI 挂） | **根因已定位**：是我们自己的 A1 补丁强开 `USING_SIMULATOR` 触发了 `ffi_dynamic_library.cc` 的整段禁用。Route-A 本就不需要 Simulator，去掉 A1 即可 |
| v02（`bytecodeFormatVersion = 2`）是 iOS VM 的要求 | **对本仓库的 VM 而言是错的**。`~/dart/sdk` 只接受 v01；v02 属于 m3 demo 里那份**外来预编译** VM |
| `tools/build_ios_patch.sh` 产出可用补丁 | 产出的是**看不见 app 任何声明**的孤立模块：缺 `--import-dill` 与 `--validate` |

新增资产：`tools/route_a/`（正确的编译流水线）、`spikes/route_a_v2/`（可跑的最小示例、
Flutter demo app、Flutter 可用的加载 shim、真机对拍脚本）。

**性能结论见 `docs/AB_BENCHMARK_ROUTE_A_VS_B.md`**：真机对拍 Route-A 比 Route-B 快 3.77×，
但 43.0× vs 162.3×（相对原生）都用不上 —— 归档的判断经得起复核。

---

## 1. `loadDynamicModule` 对 Flutter app 是可达的

`pkg/kernel/lib/target/targets.dart:347-351`：

```dart
bool allowPlatformPrivateLibraryAccess(Uri importer, Uri imported) =>
    importer.isScheme("dart") ||
    (importer.isScheme("package") &&
        (importer.path.startsWith("dart_internal/") ||
            importer.path.startsWith("dynamic_modules/")));
```

`FlutterTarget extends VmTarget extends Target`，两级都没有把这条收紧
（`pkg/vm/lib/modular/target/vm.dart:415` 只做了放宽）。
所以**一个名叫 `dart_internal` 的本地 path 依赖包就能 import `dart:_internal`**，包名是关键，不能改。

实测（全部在 stock fvm 3.29.0 / Dart 3.7.0 上，未改动 fvm cache）：

| 检查 | 结果 |
|---|---|
| `dart run`（JIT） | 编译通过，调到 `loadDynamicModule`，只抛 `UnsupportedError: Loading of dynamic modules is not supported`（因为 stock VM 是 `dart_dynamic_modules=false`） |
| `dart compile aot-snapshot` + `dartaotruntime` | 同上 |
| `flutter build bundle`（FlutterTarget frontend_server） | exit 0 |
| stock `frontend_server_aot.dart.snapshot --target=flutter --aot --tfa` | 产出 27,827,528 B dill |

即：**编译侧的 Flutter 集成不需要改引擎、不需要 fork `dart:ui`、不需要插件**。
差的只有运行时——引擎的 Dart VM 必须以 `dart_dynamic_modules=true` 构建（X1 已经是）。

代码在 `spikes/route_a_v2/dart_internal/`。

## 2. `--dynamic-interface` 走得通 Flutter 工具链

AOT 下模块能碰到的东西必须在 dynamic interface 里声明，否则 TFA 会把它们摇掉。
`pkg/frontend_server/lib/frontend_server.dart:195` 有 `addOption('dynamic-interface')`，
Flutter 侧用 `--extra-front-end-options=--dynamic-interface=<path>` 透传。

证据：给 stock frontend_server 喂一份写错的 yaml，它在
`package:vm/transformations/dynamic_interface_annotator.dart` 里崩了——
说明选项被解析、transform 确实跑了；换成合法 yaml 后正常产出 dill。

## 3. 约束 4 的根因：是我们自己关掉了 FFI

`runtime/lib/ffi_dynamic_library.cc:32`：

```c
#if defined(USING_SIMULATOR) || (defined(DART_PRECOMPILER) && !defined(TESTING))
DART_NORETURN static void SimulatorUnsupported() {
  Exceptions::ThrowUnsupportedError("Not supported on simulated architectures.");
}
...
DEFINE_NATIVE_ENTRY(Ffi_GetFfiNativeResolver, 1, 0) { SimulatorUnsupported(); }
#else
```

而 `runtime/platform/globals.h:369-372` 上的 A1 补丁把 `USING_SIMULATOR`
在 arm64 host==target 时也强行打开（Route-B 需要它跑 Simulator）。
两者相乘 = `Native._get_ffi_native_resolver` 抛异常
→ `RootIsolateToken` → `MethodChannel.setMethodCallHandler` → **全部 platform channel 挂掉**。
这正是 `spikes/shorebird_route/FINDINGS.md` 里那条 trace。

同机直接对拍（同一份源码）：

```
# A1 补丁生效的构建
$ xcodebuild/ReleaseARM64DM/dartaotruntime_product ffi_probe.snapshot
dl_processLibrary threw: Unsupported operation: Not supported on simulated architectures.

# stock Dart 3.7
$ dart ffi_probe.dart
process lib ok: DynamicLibrary: handle=0xfffffffffffffffe
```

**对 Route-A 的结论**：Route-A 用的是 KBC 解释器，跟 ARM64 Simulator 无关。
把 A1 那个 hunk 去掉重建 X1，就同时拿回 `dart:ffi`、platform channel 和
`dart_dynamic_modules=true`（X1 的 `args.gn` 里已经是 true）。
代价是同一份引擎不能再跑 Route-B——两条路要两个引擎变体。

**对「同引擎 A/B 对比」的结论：已解决并在本机验证。**
补丁在 `engine/patches/dartsdk_simulator_ffi.diff`，回归在 `tools/tests/test_sim_ffi.sh`。

分两步，缺一不可：

1. **拆宏**。`USING_SIMULATOR` 同时表达「Simulator 被编进来」和
   「host ABI ≠ target ABI」两件事；host==target 时后者为假，FFI 的禁用前提不成立。
   新增 `SIMULATOR_HOST_ARCH_MATCH`（`globals.h`，arm64 且 `HOST_ARCH_ARM64` 时定义），
   `ffi_dynamic_library.cc` 的门改成
   `(defined(USING_SIMULATOR) && !defined(SIMULATOR_HOST_ARCH_MATCH)) || ...`。

2. **宿主代码逃逸**。只放开门不够：FFI 调用编译成指向真实 native 地址的 `blr`，
   Simulator 会去**解释宿主的 C 代码**。实测第一个撞上的就是 **ADRP**
   （`word=0xf00016e0`；`DecodePCRel` 只实现了 ADR，op==1 直接
   `UnimplementedInstruction`），后面还有 PAC / NEON / LSE 原子指令。
   在 `DecodeUnconditionalBranchReg` 的 BLR 分支里加逃逸：
   目标不在任何 Dart 指令段内（`Image::contains`，含 isolate / vm-isolate 两份，
   并排除 `kSimulatorRedirectInstruction` 蹦床）时，走真实 native 调用。

   调用垫片 `CallHostFunction` 传 x0-x7 + d0-d7，并**把模拟栈顶 256 B 拷到宿主栈**，
   否则超过 8 个整型/浮点参数的调用会**静默读到错值**——这是实测出来的，不是推测：

   | 签名 | 无栈拷贝 | 有栈拷贝 | 期望 |
   |---|---|---|---|
   | 8 int | 36 | 36 | 36 |
   | 10 int | 5460017187 | **55** | 55 |
   | 10 double | 36.0 | **55.0** | 55.0 |

   同时装 `SimulatorSetjmpBuffer`，让宿主代码里抛出的 Dart 异常经
   `JumpToFrame` → longjmp 正常回到 Simulator。

验证（`tools/tests/test_sim_ffi.sh`，全 PASS）：

```
PASS: @Native resolver reaches host code      # nativeAbs(-9) == 9
PASS: DynamicLibrary.process() call
PASS: register arguments                      # sum8  == 36
PASS: stack integer arguments                 # sum10 == 55
PASS: stack double arguments                  # dsum10 == 55.0
```

`@Native` 那条正是 Flutter 挂掉的入口
（`Native._get_ffi_native_resolver` → `RootIsolateToken` → platform channel）。
上游动态模块 AOT 套件与 `tools/route_a/test.sh` 在改动后均无回归。

**残留限制**：栈参数窗口固定 256 B（32 个 slot）。超出部分不传递。
逃逸只挂在 BLR 上，不挂 BR（native 尾调用未覆盖）。

## 4. v02 是外来 VM 的格式，不是我们的

- `runtime/vm/constants_kbc.h:245` → `kBytecodeFormatVersion = 1`（未改动）
- `runtime/vm/bytecode_reader.cc:737-741` → 版本不等于 1 直接报错

带着 `dbc.dart` 的 v02 手改跑上游 AOT 套件：

```
../../runtime/vm/bytecode_reader.cc: 741: error: Unsupported Dart bytecode format
version 2. This version of Dart VM supports bytecode format version 1.
```

v02 从哪来：`spikes/m3_ios_realdevice/build/libdart_aotruntime_product.a` 导出
`Dart_LoadLibraryFromBytecode` / `Dart_LoadScriptFromBytecode` / `Dart_IsBytecode` / `kBytecodeCid`，
这套 API 在 `~/dart/sdk` 全树不存在。**2026-08-11 的 A-route 真机验证跑的是那份预编译的外来 VM**，
结论不能平移到 X1。

已把 `pkg/dart2bytecode/lib/dbc.dart` 恢复为上游的 `1`。
要复现旧 demo 时用 `archive/route_a/dbc_v02.patch` 临时打回去。

## 5. 旧打包脚本产出的补丁看不见 app

上游 AOT 流水线（`pkg/dynamic_modules/test/runner/aot.dart`）有四步，缺一不可：

1. app kernel **编两遍**：`--aot`（喂 gen_snapshot）+ `--no-aot`（给模块当 import 目标）
2. 两遍都带 `--dynamic-interface=<yaml>`
3. `gen_snapshot --snapshot-kind=app-aot-elf`
4. `dart2bytecode --import-dill <app_no_aot.dill> --validate <yaml>`

`tools/build_ios_patch.sh` 只有 `--platform` 和 `--output`——没有 2 也没有 4，
所以它产出的模块**引用不到 app 里任何声明**，只能写纯自包含代码。
归档文档没有记录这个限制。

正确实现见 `tools/route_a/build.sh`。

## 6. 端到端验证（本机，无需设备）

先建带 dynamic modules 的 host SDK：

```bash
tools/route_a/build_sdk.sh      # → ~/dart/sdk/xcodebuild/ReleaseARM64DM
```

（独立 output 目录，`xcodebuild/ReleaseARM64` 上的 Route-B 工具链不受影响。）

### 上游套件

```bash
cd ~/dart/sdk
DART_CONFIGURATION=ReleaseARM64DM dart --packages=.dart_tool/package_config.json \
  pkg/dynamic_modules/test/runner/main.dart -r aot
```

**12/12 pass。** 其中 `multiple_classes` 需要给它自己的
`dynamic_interface.yaml` 的 `callable:` 补一行 `- library: 'dart:core'`
（上游测试数据的缺口，与本仓库改动无关，已验证补上即过）。

### 我们自己的最小 app

```bash
tools/route_a/test.sh
# PASS route_a_e2e
```

```
before: BASELINE
after: PATCHED_V1
```

574 B 的 KBC v01 模块改掉了一个已 AOT 编译的 app 的行为。
这是 Route-A 第一次在 `~/dart/sdk` 这份 VM 上端到端跑通。

补丁形状（`spikes/route_a_v2/`）：app 侧留一个可写的间接层，模块侧改写它。

```dart
// app：lib/greeting.dart
String Function() impl = () => 'BASELINE';
String greet() => impl();

// module：modules/patch_v1.dart
@pragma('dyn-module:entry-point')
void patchEntry() { greeting.impl = () => 'PATCHED_V1'; }
```

注意这与归档里「闭包表 `Map<String, Function> patchEntry()`」不同：
有了 `--import-dill`，模块可以直接写 app 的顶层字段，不需要把结果回传给调用方。
单一 entry point 的限制仍然成立。

## 7. X1 引擎重建与 Flutter app 打包（2026-08-14 下午）

带 §3 补丁增量重建 `out/ios_release`（382/382，无错），产出的
`Flutter.xcframework/ios-arm64/Flutter.framework/Flutter` 离线校验：

| 字符串 | 计数 | 含义 |
|---|---|---|
| `Not supported on simulated architectures` | **0** | FFI 禁用分支已整段编译掉 |
| `Loading of dynamic modules is not supported` | **0** | `DART_DYNAMIC_MODULES` 已开 |
| `Unsupported Dart bytecode format version` | 1 | VM 字符串在位，说明提取有效 |

### Flutter iOS release app 已能打出来

`flutter build ios --release --no-codesign --local-engine ios_release`，
app 里 import `dart:_internal`（经 `package:dart_internal`）：

```
✓ Built build/ios/iphoneos/Runner.app (68.2MB)   # 不带 --dynamic-interface
✓ Built build/ios/iphoneos/Runner.app (70.4MB)   # 带 --dynamic-interface（需下面的修复）
```

### 新阻碍：`--dynamic-interface` 撞 AOT 派发表

带 dynamic interface 时 `gen_snapshot` FATAL：

```
Function has no assigned selector ID: package:flutter/src/widgets/shortcuts.dart_KeySet_set_
  (class Library:'package:flutter/src/widgets/shortcuts.dart' Class: KeySet)
```
（函数名是我们给 `dispatch_table_generator.cc:465` 的 FATAL 加了打印才拿到的。）

成因：dynamic interface 的 `_ImplicitUsesAnnotator` 会保活一批实例成员，
其中有些（例如私有字段的隐式 setter）从来不被动态派发，TFA 因此没给它们
分配 table selector。**同一文件的 `SetupSelectorRows` 早就对
`kInvalidSelectorId` 做了跳过**——只有 `NumberSelectors` 里这处 FATAL 没有，
它比 dynamic modules 早，假定唯一成因是构建配错（而那种情况由上面的
`Missing table selector metadata!` 已经拦住）。

修法：把该 FATAL 改成 `continue`。见 `engine/patches/dartsdk_dynamic_modules_aot.diff`。
改后 app 构建通过，且宿主侧全部回归无变化。

### dynamic interface 是必需的，不能绕过

试过不传 `--dynamic-interface` 编译宿主 app、模块也不 `--validate`：
模块能编出来，加载时 VM 报

```
bytecode_reader.cc: 922: error: Unable to find library package:route_a_demo/greeting.dart
```

即模块要引用 app 的库，宿主快照必须带 dynamic interface 元数据。

### 顺带修掉的两个既有构建 bug

| 症状 | 根因 | 修法 |
|---|---|---|
| `out/host_release` 任何 ninja 调用都失败在 gn 重生成 | `create_macos_analyze_snapshot_x64_x64` 依赖 `runtime/bin:analyze_snapshot`，而该 out 目录缺 `build_analyze_snapshot = true` | 加到 `out/host_release/args.gn` |
| 加上后编译失败：`no type named 'SetPendingVmcodeFile' in 'dart::Simulator'` | `Dart_ShorebirdLoadVmcode` 只按 `USING_SIMULATOR` 守卫，但 host_release 是 target-x64（host arm64），`USING_SIMULATOR` 同样成立，而 x64 的 `Simulator` 没这个成员 | 守卫改成 `USING_SIMULATOR && TARGET_ARCH_ARM64` |

## 8. 工具链打通，Flutter 模块已能编出来（2026-08-14 傍晚）

### 卡点根因

`flutter_tools/artifacts.dart:1466 _getDartSdkPath()` 先找
`<host_engine_out>/dart-sdk/bin`，找不到就回落
`engine_src/flutter/prebuilts/macos-arm64/dart-sdk`。
`out/host_release` 既是 `target_cpu = "x64"`（`dartaotruntime` / `gen_snapshot`
都是 Mach-O x86_64，在 M2 上走 Rosetta），又没有 `dart-sdk/` 树，
于是 app 的 kernel 一直是那份预编译 Dart 产的 **v122**，而 `~/dart/sdk` 是 **v121**：

```
Unexpected Kernel Format Version 122 (expected 121)
```

`target_cpu` 不是探测出来的，是当初 `gn gen` 传进去的；换什么 Mac 都不会自动变。

### 修法

新建 `out/host_release_arm64`：`target_cpu = "arm64"` + `full_dart_sdk = true`
（`tools/route_a/build_host_engine.sh`）。2800/2800 构建通过，产出
`dart-sdk/bin/{dart,dartaotruntime,snapshots/frontend_server_aot.dart.snapshot}`
与 `gen/dart2bytecode.dart.snapshot`，全部 arm64、全部 kernel 121。

app 构建加 `--local-engine-host host_release_arm64` 后：

```
✓ Built build/ios/iphoneos/Runner.app (69.7MB)
app.dill: magic 90abcdef  version 121      ← 与 X1 一致
```

### Flutter app 的 KBC 模块已产出

`tools/route_a/build_flutter_module.sh`：

```
[route_a] app kernel (no_aot)
[route_a] module bytecode
[route_a] module.bytecode: KBC v1, 510 bytes
```

模块 `import 'package:fapp/patchable.dart'` 并改写它的顶层字段，
经 `--validate` 校验通过。**Route-A 的编译链到此在 Flutter 上完整了**，只差上机。

### Route-B 的 `.vmcode` 也已按新引擎重做

`valapp29` 用新引擎重建（68.2 MB），`tools/build_app_patch.sh` 改为优先用
`host_release_arm64/dart-sdk`（否则补丁 dill 是 v122、base 是 v121）：

```
base(ELF):   4,077,088    patch(ELF):  4,077,088
out.vmcode:  4,142,624    link%: 100.00%
link table:  7123 条      内嵌 ELF 偏移 65536（16384 对齐）逐字节 == patch.aot
base.aot 只含 BASELINE_V1 / patch.aot 只含 OTA_PATCHED_V2
```

按 ELF 分节比对，差异全部落在 `.rodata`（+96 B，就是那个字符串）与
符号表/build-id 的零星几字节；**`.text` 1,597,072 字节逐字节相同**，
与 link% 100%、与 `GROUND_TRUTH.md`「改常量够不着代码段」一致。
（先前按整文件位移比出的「1,076,847 字节差异」是位移伪影，不是真实改动量。）

## 9. 真机验证（2026-08-14，iPhone 14 / iOS 26.6）

设备 `QA-iPhone-YPVYHY2D90` = `00008110-000E583836F3601E`。判定一律读
`idevicesyslog`，不看屏幕。

### Route-A：Flutter app 里加载 KBC 模块 —— PASS

`spikes/route_a_v2/flutter_app`（`com.hotpatch.bench.hotpatch`），模块推到
`Documents/module.bytecode`，冷启：

```
flutter: FHP_A=before=BASELINE
flutter: FHP_A=module=586B
flutter: FHP_A=status=loaded
flutter: FHP_A=after=PATCHED_V1
```

**归档文档里「Flutter app 无法 import `dart:_internal`、Route-A 上不了 Flutter」到此被真机推翻。**

### FFI 修复的 iOS 运行时验证 —— PASS（顺带拿到）

这个 app 用 `path_provider` 取 Documents 目录、再用 `dart:io` 读文件，两者都成功。
`path_provider` 走的就是 MethodChannel —— 修复前它会在 binding 初始化阶段
连同所有 platform channel 一起抛
`Not supported on simulated architectures`。整轮日志里该字符串 **0 次**。

### Route-B：`.vmcode` 真机生效 —— PASS

`valapp29`（`com.hotpatch.bench.shorebirdDemo`）：

```
[shorebird] SetBaseSnapshot mappings: ... total=505529
[shorebird] No public key configured; skipping signature verification
Shorebird updater: active path: .../shorebird_updater/patches/1/dlc.vmcode
flutter: FHP_RESULT=OTA_PATCHED_V2          （baseline 那轮是 BASELINE_V1）
```

### 修正：state root 没有 `<app_id>` 这一层

`e2e_device.sh` 原本按 `shorebird.cc:158-159` 推成
`<app_storage>/shorebird_updater/<app_id>`。真机上按那个路径推，updater 完全不看，
日志停在 `Shorebird updater: no active patch`。

真实布局（从设备上 updater 自建的目录反推）：

```
Library/Application Support/shorebird/shorebird_updater/pointers.json
Library/Application Support/shorebird/shorebird_updater/patches/<N>/dlc.vmcode
Library/Application Support/shorebird/shorebird_updater/patches/<N>/state.json
```

`pointers.json` 还多一个字段：
`{"next_boot_patch":N,"last_booted_patch":null,"currently_booting_patch":null,"boot_started_at":null}`。
脚本已按实测改正。

### 设备侧约束

该 team 是**免费开发者账号**，同一设备最多 3 个 app：

```
This device has reached the maximum number of installed apps using a free
developer profile: { 7VP87G446C.com.hotpatch.bench.shorebirdDemo,
                     G5A33T9UT8.com.digiplus.arenasocial.arenaSocial.dev,
                     7VP87G446C.org.hotpatch.m3demo }
```

装第 4 个必须先卸一个。本轮为装 Route-A 的 app 卸掉了自己刚装的 valapp29
（Route-B 结果已先行取得）。另外 `flutter build ios` 不加 `--no-codesign`
才会嵌 `embedded.mobileprovision`，否则 `devicectl install` 直接失败；
`e2e_device.sh` 的重签步骤已改为「已正确签过就跳过」——
它原本用 `find-identity` 第一条，那是另一个 team 的证书，重签会让描述文件对不上。

## 10. 状态汇总

| 项 | 状态 |
|---|---|
| `loadDynamicModule` 对 Flutter app 可达 | **成立**（§1，stock Flutter 3.29.0 实测） |
| `--dynamic-interface` 走得通 Flutter 工具链 | **成立**（§2、§7） |
| Simulator 与 FFI 共存 | **已实现**（§3）；macOS arm64 实测 + iOS 真机运行时 PASS（§9） |
| v01/v02 版本前提更正 | **已确认**（§4） |
| 宿主 AOT 端到端 | **PASS**（§6，上游套件 12/12 + 自建 demo） |
| X1 引擎重建 | **已完成**（§7） |
| Flutter iOS app 打包（含 dynamic interface） | **已完成**（§7） |
| 给 Flutter app 编模块 | **已完成**（§8，510 B KBC v1） |
| Route-B `.vmcode` 按新引擎重做 | **已完成**（§8，link% 100%） |
| Flutter app 真机加载 KBC 模块 | **PASS**（§9） |
| iOS 上 FFI 修复的运行时验证 | **PASS**（§9，path_provider + dart:io 都通） |
| Route-B `.vmcode` 真机生效 | **PASS**（§9） |
| Route-A 与 Route-B 性能对拍 | **已完成** → `docs/AB_BENCHMARK_ROUTE_A_VS_B.md` |

## 11. 最终结论

技术上，Route-A 在 Flutter + iOS 真机上**完全可行**，归档时列的四项约束里三项被推翻。

但 `docs/AB_BENCHMARK_ROUTE_A_VS_B.md` 的真机对拍显示它比 Route-B 只快 **3.77×**
（43.0× vs 162.3× 相对原生），这个差距落在无用区间：补 UI/业务逻辑时两者都远快于需求，
补热路径时两者都不可接受。

**所以 Route-A 的定位不变**：按顶级规则 1，Shorebird 不提供此能力 → 不进产品线，
留作研究能力。恢复条件见 `archive/route_a/README.md`，其中第 3 条
（「出现能用上那 4× 的真实场景，且须在 Flutter app 上重测确认」）现在已经重测过了 ——
量出来是 3.77×，且两条路都离热路径需求差两个数量级。
