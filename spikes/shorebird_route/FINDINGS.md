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

## analyze_snapshot：已修复并跑通

### 构建侧（三件事缺一不可）

| 问题 | 解法 |
|---|---|
| 工具必须是 **macOS host 可执行 + iOS 目标配置** | 从**引擎**构建（`lib/snapshot:create_macos_analyze_snapshots`，模板移植自 Shorebird）。**不能**用 Dart SDK 的 `ReleaseARM64` —— 那是 macOS 目标，读 iOS 快照会 SIGSEGV |
| `Unsupported platform` | `runtime/bin/analyze_snapshot.cc` 守卫只允许 android/linux，放宽到 macOS |
| `build_analyze_snapshot` 默认 false | args.gn 置 true |

**歧路教训**：曾在 `app_snapshot.cc` 加 flag 绕过 `VerifyFeatures`，SIGSEGV。
那个校验保护的是真实不兼容（`product ios` vs `release macos` 的对象布局），已撤回。

### 枚举侧：CollectAllCodes 重写

自研的 B2 实现有三个 bug：遍历 `cls.functions()`（AOT 下多被清空）、
闭包循环误置于 cid 循环内（重复 NumCids 遍）、`payload == 0` 永不成立
导致 VM 区 Code 混入产生负偏移。

改为可达对象图遍历（对齐上游 `DumpInterestingObjects`）。
**决定性的一步**是把 `object_store()->instructions_tables()` 加入根集 ——
AOT 的 bare-instructions 模式下绝大多数 Code 不再从类/库可达，
而挂在 `InstructionsTable` 的 `code_objects_` 上。

| | 函数数 | 负偏移 | app 自身代码 |
|---|---|---|---|
| 原实现 | 134 | 有 | ❌ |
| 图遍历后 | 1983 | 0 | ❌ |
| 加 instructions_tables | **7122** | **0** | **✅ buildLabel / ValApp.build** |

（参照：Shorebird 自己的 app 是 7368，量级吻合。）

## 端到端结果（Mac 侧全通）

真实 Flutter app、X1 引擎、我们的 linker：

```
base(ELF):    4,076,952 bytes
patch(ELF):   4,076,952 bytes
out.vmcode:   4,134,296 bytes
link%:        100.00%
bipatch diff: 38,277 bytes
```

`.vmcode` 结构已逐项核对：LinkTable 7122 条、头部补齐到 57344
（= 14 页，与引擎里 `FhpReadLinkHeader` 的算法一致）、内嵌 ELF 逐字节等于
`patch.aot` 且魔数为 `7f454c46`。补丁内容也已核实：
`patch.aot` 只含 `OTA_PATCHED_V2`，`base.aot` 只含 `BASELINE_V1`。

link% 100% 对"仅改字符串常量"是预期结果 —— 与 `GROUND_TRUTH.md` 的发现一致：
等长/变长常量改动够不到代码段，`.text` 与 base 逐字节相同。

## 步骤 1 与 2：已全部脚本化，等设备

两台已配对 iPhone 现为 `unavailable` / `transport: None`，USB 检测不到，无法执行。
Mac 侧能验的都验了。

### 步骤 1：验证补丁在设备上生效 —— `e2e_device.sh`

离线已验证的部分：

| 检查项 | 结果 |
|---|---|
| 引擎 `FhpReadLinkHeader` 算出的 ELF 偏移 vs 实际 | 57344 == 57344 ✅ |
| 该偏移处魔数 | `7f454c46` ✅ |
| 从该偏移读出的内容 == `patch.aot` | ✅ |
| 最终 framework 含 `ConfigureShorebird` 提示串 | ✅ |
| 含 `shorebird_updater` / `dlc.vmcode` / `next_boot_patch` | ✅ |
| 含 `patch_cache` 的加载日志串 | ✅ |
| 含**我写的** `vmcode link header` 错误串 | ✅（证明 `FhpReadLinkHeader` 已编入）|

设备侧注入格式**取自上游源码而非猜测**：

```
<state_root>/patches/<N>/dlc.vmcode
<state_root>/patches/<N>/state.json   {"kind":"Installed","signature":null,"size":N}
<state_root>/pointers.json            {"next_boot_patch":N,...}
```
- 目录常量 `library/src/cache/lifecycle.rs:53-55`
- `state_root` = `<app_storage>/shorebird_updater/<app_id>`（`shorebird.cc:158-159`）
- `PatchState` 为 internally tagged（`lifecycle.rs:59` `#[serde(tag="kind")]`）
- `ReleasePointers` 字段见 `lifecycle.rs:129-141`

### 步骤 2：A/B 性能对比 —— `bench_device.sh`

热函数用**与历史数据同一个** 10K 迭代累加
（`spikes/benchmark/hotpatch_demo/patches/greet_cpu.dart`），以便与
Shorebird 806.7µs / A-route 156.4µs 直接可比。

**一个差点搞砸的设计问题**：最初只改标签函数，但那样 `hotLoop` 的
`subgraph_hash` 不变 → 会被 link 回原生 → 测到的仍是 AOT 速度，
根本测不到解释器。改为让 `hotLoop` 自身变化（迭代数 10000→10001）。

已用工具链实测校验：**7079 个函数中恰好 1 个未匹配，就是 `hotLoop`**
（hash `03be54b8` → `4340c59e`），其余全部 link 回原生 —— 干净的对照实验。
（0.01% 工作量差相对 4000× 量级差可忽略。）

判读标准：

| 结果 | 含义 |
|---|---|
| X1 解释 ≈ 806,700 ns | 我们的 B-route 与 Shorebird 同级；「5.15× 更快」只属于 A-route(KBC)，不属于产品路径 |
| X1 解释 明显优于 806,700 ns | 我们的 SimulatorToCPU 实现有优势 —— 这才构成选 X1 而非 Shorebird 引擎的理由 |

设备接上后：
```bash
DEVICE=<id> ./e2e_device.sh     # 步骤 1
DEVICE=<id> ./bench_device.sh   # 步骤 2
```
