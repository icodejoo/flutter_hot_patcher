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

## analyze_snapshot：已跑通，但我们自研的 --shorebird 模式不完整

### 已解决：能在 macOS 上分析 X1 的 iOS 快照

| 步骤 | 解法 |
|---|---|
| 工具必须是 **macOS host 可执行 + iOS 目标配置** | 用引擎的 `lib/snapshot:create_macos_analyze_snapshots`（已从 Shorebird 移植该模板），**不是** Dart SDK 的 `ReleaseARM64`（那是 macOS 目标，读 iOS 快照会 SIGSEGV）|
| `Unsupported platform` | `runtime/bin/analyze_snapshot.cc` 的守卫只允许 android/linux，放宽到 macOS（见 `engine/patches/dartsdk_analyze_snapshot_macos.diff`）|
| `build_analyze_snapshot` 默认 false | args.gn 里置 true |

结果：`analyze_snapshot_arm64 --shorebird` 成功读出 X1 的 iOS 快照，JSON schema 与
Shorebird 完全同构（`name/offset/size/self_hash/subgraph_hash/op_subgraph_hash/...` 齐全）。

**一条歧路的教训**：曾试图在 `app_snapshot.cc` 加 `--ignore_snapshot_feature_mismatch`
绕过 `VerifyFeatures`。结果 SIGSEGV —— 那个校验保护的是真实不兼容（`product ios`
vs `release macos` 的对象布局差异），不可绕过。该改动已撤回。

### 剩余阻碍：`CollectAllCodes` 枚举不完整

`runtime/vm/analyze_snapshot_api_impl.cc` 的 `CollectAllCodes`（我们自研的 B2 commit
`d8ddec71daf`）只遍历 `cls.functions()`：

```cpp
Array& functions = Array::Handle(zone, cls.functions());
if (functions.IsNull()) continue;
for (...) { code = func.CurrentCode(); ... }
```

**AOT 快照里 `cls.functions()` 多被清空**，所以只枚举到 134 个函数（应为数千），
且 app 自身的 `buildLabel` 不在其中；部分 `offset` 为负数（把 VM 区的 Code
按 isolate 基址算偏移）。

正确做法是遍历快照的 code 对象表（`ProgramVisitor` / instructions table），
而非类表。这是一段明确但真实的 VM 内部工作。

**影响**：`tools/linker.py` 靠 `subgraph_hash` 匹配函数；枚举不全则链接无意义。
注意 linker 此前只在 **Shorebird 的** analyze_snapshot 输出上验证过
（`GROUND_TRUTH.md` 与 B-route 实测），从未在我们自研的输出上验证过。

## 后续选项

1. **修 `CollectAllCodes`** —— 改走 code 对象表。这是 X1 路线剩余的唯一阻碍，
   修好即可打通 patch 生成 → 真机 E2E → A/B 性能对比。
2. **产品线改用 Shorebird 预编译引擎**（其 analyze_snapshot 完整可用），
   X1 仅留作 A-route 研究。代价：放弃同引擎 A/B 对比。
