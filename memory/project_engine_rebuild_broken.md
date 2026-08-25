---
name: project-x1-research-branch
description: X1 引擎现状（2026-08-14 更新）——FFI 阻断的根因已定位，是我们自己的 A1 补丁强开 USING_SIMULATOR
metadata: 
  node_type: memory
  type: project
  originSessionId: cae5863d-feae-468d-8c8b-6c16f076bdaf
---

**X1 已转为研究分支。产品线用 Shorebird 预编译引擎。**

## ⚠ `~/engine_ios` 已于 2026-08-19 删除（34 GB，磁盘告急）

删前它有 **27 个已跟踪文件被修改、0 个本地提交**。其中只有 6 个（`runtime/dart_snapshot.cc`、
`FlutterDartProject.mm`、`common/config.gni` + 三个 `BUILD.gn`）被 `shorebird_integration.diff`
覆盖；**另外 21 个当时没有任何备份**——`display_list/*`、`impeller/geometry/*`、
`lib/ui/floating_point.h`、`saturated_math.h`、`checked_math_impl.h`，
全是 clang 18 + iOS 26.5 的浮点坑（见 `docs/X1_ENGINE_BUILD_NOTES.md`）。

**全部 27 个文件的 diff 已存进版本控制**（route-a-research，commit `c75205c`）：

- `engine/patches/engine_ios_local_all.diff` —— 41 KB / 904 行 / 27 文件，
  `git apply --check --reverse` 验证过与当时工作树一致
- `engine/patches/engine_ios.gclient`、`engine/patches/engine_ios_HEAD.txt`（rev `ae5c3603d0`）

**要重建引擎时**：先 `gclient sync` 到 `ae5c3603d0`，再 `git apply engine_ios_local_all.diff`。
但注意——按 [[project-dart-sdk-fork]] 的主任务要对齐 Dart 3.12.2，
`ae5c3603` 对应的是 Dart 3.7，**届时要 sync 的是另一个 engine revision**，
这份 diff 多半需要重新适配而非直接套用。

删除时已验证：`engine_ios/src/third_party/dart` 只是指向 `~/dart/sdk` 的软链，
`rm -rf` 不跟进，自研 fork 未受影响。

## 已解决

- **可重建性**：`src/third_party/boringssl` 符号链接导致同源码在两个 label 下各编一遍。
  改为「真实目录 + 转发 BUILD.gn + 保留 src 链接」。见 `docs/X1_ENGINE_REBUILD_FIX.md`
- **Shorebird 引擎层已移植**（规则 2，拷贝非重写），见 `engine/patches/README.md`
- **能构建并运行真实 Flutter app**（fvm 3.29.0 匹配 Dart 3.7，`verify_sdk_hash=false`，
  重建 `gen_snapshot_arm64` 与 `Flutter.xcframework`）
- **FFI 阻断的根因已定位（2026-08-14）**，见下

## FFI/platform channel 阻断：根因

不是「Shorebird 私有 dart-sdk 修了什么我们不知道的东西」，是我们自己造成的：

- `runtime/lib/ffi_dynamic_library.cc:32` 把整段 `dart:ffi` 动态库 + `Ffi_GetFfiNativeResolver`
  用 `#if defined(USING_SIMULATOR)` 换成 `SimulatorUnsupported()`
- 我们的 A1 补丁（`runtime/platform/globals.h:369-372`）在 arm64 host==target 时强开 `USING_SIMULATOR`

→ `Native._get_ffi_native_resolver` 抛 `Not supported on simulated architectures.`
→ `RootIsolateToken` → `MethodChannel.setMethodCallHandler` → 全部 platform channel 挂。

同机对拍已证实：A1 生效的 `xcodebuild/ReleaseARM64DM/dartaotruntime_product` 上
`DynamicLibrary.process()` 抛该异常，stock Dart 3.7 正常。

**已修好（2026-08-14，macOS arm64 实测 ALL PASS；iOS 构建未验证）**：
`engine/patches/dartsdk_simulator_ffi.diff`，回归 `tools/tests/test_sim_ffi.sh`。

两步缺一不可：
1. **拆宏**：`globals.h` 新增 `SIMULATOR_HOST_ARCH_MATCH`（arm64 且 HOST_ARCH_ARM64），
   `ffi_dynamic_library.cc` 的门改成按 **ABI 屏障**而非「有没有 Simulator」。
2. **宿主代码逃逸**：只放开门不够——FFI 调用是指向真实 native 地址的 `blr`，
   Simulator 会去解释宿主 C 代码，**第一个就撞 ADRP**（`DecodePCRel` 只实现 ADR）。
   在 `DecodeUnconditionalBranchReg` 的 BLR 分支加逃逸：目标不在任何 Dart 指令段内
   （`Image::contains`，含 isolate + vm-isolate，并排除 `kSimulatorRedirectInstruction` 蹦床）
   时走真实 native 调用。垫片传 x0-x7 + d0-d7 **并把模拟栈顶 256 B 拷到宿主栈**——
   不拷会静默读错值（10 个 int 参数得 5460017187 而非 55）。装 `SimulatorSetjmpBuffer` 传异常。

残留限制：栈参数窗口 256 B；只挂 BLR 不挂 BR。

⚠️ **本节只描述 3.7 的 X1 研究树，别外推到主任务分支。**
在 `shorebird-3.12.2` 上这套**已作废**：上游 `SIMULATOR_FFI` 顶掉了它，
`SIMULATOR_HOST_ARCH_MATCH` 那两块连编译都没进，7 条 FFI 测试全 PASS。
见 [[project-dart-sdk-fork]] 的「FFI 缺口已关闭」。

**意义**：Route-A 与 Route-B 现在**有可能共用一个引擎**——FFI 恢复后 `USING_SIMULATOR`
不再和 Flutter 冲突，`dart_dynamic_modules=true` 也已开着。须在 iOS 构建上重新确认。

## 重建必备（每次）

- `export PATH="$HOME/depot_tools:$PATH"`（gn 要 vpython3）
- 每次 `gn gen` 后重打 `toolchain.ninja` 的 `-F <iPhoneOS.sdk SubFrameworks>` 补丁
- 目标 `ninja -C out/ios_release libFlutter.dylib`；产 app 用的还要 `Flutter.xcframework`
- **不要用 `| tail` 包 ninja** —— 会把退出码掩盖成 tail 的 0
- `src/third_party/dart` 符号链接**必须保留**（它指向 `~/dart/sdk`；引擎源码 include 依赖它）
