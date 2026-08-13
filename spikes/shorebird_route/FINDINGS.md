# X1 引擎 + Shorebird 集成：验证结论

> 2026-08-13。目标是让**标准 Flutter app** 在 X1 引擎上具备 Shorebird 等价的 OTA 能力，
> 从而之后能在同一引擎上公平对比 A-route（KBC）与 B-route（Simulator）性能。

## 已达成

### 1. X1 引擎可重建（此前从未成功）

`libFlutter.dylib` 在 `out/ios_release` 里从未链接成功过。根因与修复见
`docs/X1_ENGINE_REBUILD_FIX.md`（`src/third_party/boringssl` 符号链接导致 gn 绕过
Flutter 自带转发覆盖、把同一份源码在两个 label 下各编一遍）。

### 2. Shorebird 公开引擎层已移植进 X1 并生效

按规则 2 原样拷用，未重写。移植与三处适配见 `engine/patches/README.md`。

app 内嵌 framework 实测：

| 指标 | 移植前 | 移植后 |
|---|---|---|
| `shorebird_*` 导出 | 0 | **15** |
| `Failed to find shorebird.yaml`（我们接的 ConfigureShorebird） | 0 | **1** |
| `loadDynamicModule`（A-route 能力） | 4 | **4**（保留） |
| `ShorebirdSimToCpuCall` | 4 | **4**（保留） |

### 3. 真实 Flutter app 已能在 X1 上构建

`✓ Built build/ios/iphoneos/Runner.app (62.6MB)`。过程解决了四个连锁阻碍：

| 阻碍 | 解法 |
|---|---|
| Shorebird 的 Flutter 3.44 要求 Dart 3.10，X1 只有 3.7 | 改用 fvm `3.29.0`（`sdk: ^3.7.0`，与 X1 匹配） |
| `Invalid SDK hash` | `verify_sdk_hash = false`，且必须重建**正确的目标名** `gen_snapshot_arm64`（不是 `gen_snapshot`） |
| 缺 `const_finder.dart.snapshot` | `--no-tree-shake-icons` |
| app 嵌到的是 8/5 的**过时 `Flutter.xcframework`** | 重建 `Flutter.xcframework`（toolchain 的 SubFrameworks 补丁已能让 `copy_and_verify_framework_module` 通过） |

### 4. 上游 Rust updater 已接入

`shorebirdtech/updater` @ `1f85c4ab`（DEPS 锁定版），置于 `flutter/third_party/updater`，
iOS arm64 编译通过（`libupdater.a`）。构建需 `IPHONEOS_DEPLOYMENT_TARGET`，
否则 `___chkstk_darwin` 未定义。**这同时偿还了 `tools/updater/` 的规则 2 债。**

### 5. 补丁构建脚本

`tools/build_app_patch.sh`，可用 `FHP_TOOLCHAIN=x1|shorebird` 切换工具链
（补丁必须与 base 同源）。形态：base 是 app 的 Mach-O `App`，patch 必须是 **ELF**
（引擎侧 `patch_cache.cc` 用 `Dart_LoadELF` 打开 `.vmcode`）。

## 当前阻碍：X1 缺可用的 analyze_snapshot

`tools/linker.py` 依赖 `analyze_snapshot --shorebird` 读取 base/patch 快照。

| 候选 | 结果 |
|---|---|
| Shorebird 预编译的 `analyze_snapshot_arm64` | ❌ `Wrong full snapshot version`（它是 Dart 3.10，X1 是 3.7） |
| 从 Flutter 引擎构建（已移植其 BUILD.gn 目标 + `build_analyze_snapshot = true`） | ❌ 二进制产出了，但运行报 `Unsupported platform. Requires DART_PRECOMPILED_RUNTIME` —— host 工具链下未定义 |
| `~/dart/sdk/xcodebuild/ReleaseARM64` 既有产物（8/4） | ❌ 早于自研 `--shorebird` commit：`Unrecognized flags: shorebird` |
| 重建 `ReleaseARM64`（已设 `build_analyze_snapshot = true`） | ❌ 同样 `Requires DART_PRECOMPILED_RUNTIME`（该目录 `dart_runtime_mode = "develop"`） |
| 重建 `ReleaseIosARM64`（AOT 配置） | ❌ 撞 libcxx cmath 问题（`X1_ENGINE_BUILD_NOTES.md` 附錄 A 的补丁只打在引擎的 libcxx，未打在 Dart SDK 自己的 third_party/libcxx） |

**结论**：需要一个 `DART_PRECOMPILED_RUNTIME` 生效的 Dart SDK 构建，
且其 libcxx 已打 cmath 补丁。这是一段独立的构建系统工作，未在本轮完成。

## 后续三个选项

1. **补完 X1 的 analyze_snapshot** —— 给 `~/dart/sdk/third_party/libcxx` 打 cmath 补丁，
   并用 AOT/product 模式构建。工作量中等但明确。
2. **让 linker 不依赖 analyze_snapshot** —— 自行解析快照的 function/hash 信息。
   工作量大（等于重做 `analyze_snapshot --shorebird`）。
3. **产品线改用 Shorebird 预编译引擎**（其 analyze_snapshot 可用），
   X1 仅保留作 A-route 性能研究。代价：放弃在同一引擎上做 A/B 对比。

## 复现

```bash
# 引擎（前置：docs/X1_ENGINE_REBUILD_FIX.md 的 BoringSSL 修复）
export PATH="$HOME/depot_tools:$PATH"
cd ~/engine_ios/src && ./flutter/third_party/gn/gn gen out/ios_release
#   重打 toolchain 的 -F SubFrameworks 补丁
ninja -C out/ios_release Flutter.xcframework gen_snapshot_arm64

# app
~/fvm/versions/3.29.0/bin/flutter build ios --release --no-codesign \
  --no-tree-shake-icons \
  --local-engine-src-path="$HOME/engine_ios/src" \
  --local-engine=ios_release --local-engine-host=host_release
```

`lib/main_patched_v2.dart` 是补丁版源码（`buildLabel()` 返回 `OTA_PATCHED_V2`），
`lib/main.dart` 保持 baseline（`BASELINE_V1`）。
