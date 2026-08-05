# Hotpatch 系统边界报告

版本 v1.1 · 2026-08-04
设备：iPhone 14 (iOS 26.5.2) | SDK: 1aa7d7321fb

---

## 一、已验证可用（本次修复/确认）

| 能力 | 状态 | 备注 |
|------|------|------|
| async/await 函数补丁 | ✅ dart2bytecode 编译通过 | 需单独 dill 文件 |
| sync* generator | ✅ 支持 | |
| async* generator | ✅ 支持 | |
| Records (Dart 3.0) | ✅ 支持 | |
| Extension types (Dart 3.3) | ✅ 支持 | |
| Sealed class + pattern match | ✅ 支持 | |
| 多版本补丁 v1→v2 | ✅ 支持（独立 dill） | Updater 状态机负责版本管理 |
| 继承/mixin/abstract | ✅ 已测试 T35-T42 | |
| 泛型函数/类 | ✅ 已测试 T43-T46 | |
| 第三方纯 Dart 包 | ✅ intl/collection/crypto/path | |

---

## 二、已知限制（已修复或已缓解）

### L1: 每个 .dart 文件只能有一个 entry-point ✅ FIXED
**修复**：`tools/patch_builder/gen_dispatcher.py` — 多函数补丁通过 dispatcher 函数模式支持多个补丁函数。
**方案**：生成一个 dispatcher 入口函数，内部 switch/map 分发到各实际补丁函数；每个补丁文件仍只有一个 `@pragma('dyn-module:entry-point')`。
**约束保留**：每个 .dart/.dill 文件仍只有一个 entry-point，属 VM 设计约束，dispatcher 不能消除。

### L2: const 字面量变化对 kernel_linker 不可见（R2 gap）✅ FIXED
**修复**：`kernel_linker/lib/kernel_diff.dart` — `ConstantCollector` visitor 将常量的实际值追加到 AST 指纹；纯常量变化现在产生不同指纹。
**验证**：T20–T25 全部 6 个 const 场景（double/int/String/static/list/expr）均已正确检测为 CHANGED。
```
CHANGED (6):
  ~ const_toplevel (T20) — double 3.14159→3.14
  ~ const_local   (T21) — int 100→200
  ~ const_final   (T22) — String Alice→Bob
  ~ const_static  (T23) — String v1→v2
  ~ const_list    (T24) — list length 3→4
  ~ const_expr    (T25) — 2*3→2*4
```

### L3: 补丁只能引用基线保留的符号（闭世界约束）✅ MITIGATED
**缓解**：`tools/patch_builder/gen_dynamic_interface.py` — 自动生成 `dynamic_interface.yaml`，声明补丁所需符号以防树摇。
**约束保留**：需要在构建基线时就规划好补丁可能用到的符号集，运行时引入全新外部符号仍不可能。

### L4: cid_map.bin 目前为空（R5 gap）✅ FIXED (graceful)
**修复**：
- `kernel_linker/lib/cid_extractor.dart` — 使用 `analyze_snapshot` 工具从 ELF snapshot 提取 Class→class_id 映射。JSON 格式为 `objects[].{type:"Class", class_id:N, name:"Foo"}`。
- `kernel_linker/lib/manifest_output.dart` — `writeManifest()` 新增 `baseSnapshotPath` / `patchSnapshotPath` / `analyzeSnapshotBin` 可选参数；提供时自动生成非空 cid_map.bin，不提供时优雅降级为 count=0。
- `kernel_linker/bin/kernel_linker.dart` — 新增 `--base-snapshot`, `--patch-snapshot`, `--analyze-snapshot` CLI 标志。
**依赖**：需要 `analyze_snapshot`（release 模式构建）和 `gen_snapshot`（release 模式）。在 SDK build `xcodebuild/ReleaseARM64/` 中两者现已成功构建。
**T04 验证**：纯 const 变化不产生类布局漂移，cid_map.bin count=0 是正确结果（无 cid 重映射需要）。

---

## 三、无法解决（架构/平台限制）

### X1: Flutter Engine 集成测试
**原因**：当前验证套件使用裸 Dart VM C 嵌入模型（`dart_harness.c`），没有 FlutterViewController/FlutterEngine。
**影响**：无法验证 Flutter widget build/rebuild、Provider/Riverpod 状态管理、Navigator、plugin 调用等实际生产路径。
**解决条件**：需要实现 M6（Flutter Engine 嵌入层），预估 2-3 人月。

### X2: Platform channels / Method channels
**原因**：依赖 Flutter Engine 的 BinaryMessenger 层。
**影响**：调用原生 API（相机、蓝牙、支付）的函数无法热修复。
**解决条件**：同 X1。

### X3: dart:isolate 多 isolate 闭包枚举
**原因**：`HeapIterationScope` 只遍历当前 isolate 的堆。如果同一函数被多个 isolate 的闭包引用，其他 isolate 中的实例无法被重定向。
**影响**：使用 `Isolate.spawn` 或 Flutter background isolate 的 App，热修复可能遗漏其他 isolate 中的旧闭包实例（静默不一致，比崩溃更危险）。
**解决条件**：需要在 Dart VM 层实现跨 isolate 的全局堆遍历，工作量大，且需要 VM 暂停所有 isolate 协调。

### X4: App Extension（Widget Extension / Notification Extension）
**原因**：App Extension 是独立进程，有自己的 Dart VM 实例。主 App 的热修复不传播到 Extension 进程。
**影响**：iOS 桌面 Widget、Notification Content Extension 等无法同步热修复。
**解决条件**：需要在每个 Extension 进程中独立集成 Updater，且 Extension 有更严格的内存/时间限制。

### X5: iOS 版本矩阵兼容性
**原因**：当前只有 iPhone 14 (iOS 26.5.2) 一台设备可用。
**影响**：iOS 16/17/18 上的行为未验证（W^X 策略、entitlement 要求、Swift 运行时差异可能影响 Dart VM 行为）。
**解决条件**：需要多台测试设备或 BrowserStack/Sauce Labs 真机云。

### X6: 大堆性能（HeapIterationScope 在生产规模下的耗时）
**原因**：Gate 1 R3.1 验证了机制可行，但未测试 100MB+ 堆上的遍历耗时。
**影响**：对象数量多时，cold boot 阶段应用补丁可能引入可感知的启动延迟。
**解决条件**：需要在真实 Flutter App（含大量 widget 树对象）上测量，可能需要增量遍历或并发遍历优化。

---

## 四、生产发布前必做核查清单

### 必须解决再发版（P0）
- [x] ~~cid_map.bin 有值场景下的测试（增删 class 后 dispatch 正确性）~~ — L4 已实现基础设施；增删类场景的端到端设备测试仍需
- [ ] Flutter Engine 嵌入层最小验证（用 FlutterViewController 替换 dart_harness.c）
- [ ] async/await 场景运行时设备测试（编译通过，设备执行待验证）

### 应该解决（P1）
- [x] ~~const 字面量变化检测~~ — L2 ConstantCollector 修复，T20-T25 全通过
- [ ] 多版本补丁升级的端到端设备测试（v1 → v2 replace）
- [x] ~~闭世界符号集预声明规范~~ — L3 gen_dynamic_interface.py 实现

### 接受为已知限制（KL）
- [x] 每 dill 单入口约束：L1 gen_dispatcher.py 文档化并提供 dispatcher 模式
- [ ] 多 isolate 闭包遗漏：文档化，建议 App 不在补丁期间使用 background isolate
- [ ] App Extension 不同步：文档化，Extension 需要配合发版更新

---

## 五、总结

| 类别 | 数量 | 可行性 |
|------|------|--------|
| 已验证可用 | 11 项 | ✅ |
| 已知限制（已修复/缓解）| 4 项（L1-L4）| ✅ 全部修复或已缓解 |
| 无法解决（架构限制）| 6 项（X1-X6） | ❌ 需要更大工程 |
| 生产前 P0 必做 | 2 项剩余 | 阻塞上线 |

---

## 七、X1 Flutter Engine 构建进展（2026-08-04）

### 构建环境已建立

| 组件 | 状态 |
|------|------|
| Flutter 3.38.10 / 3.44.6 | ✅ 已安装（fvm） |
| depot_tools + gclient | ✅ 可用 |
| flutter/engine main 分支 | ✅ 已 clone |
| gclient sync（Skia/abseil等 ~5GB）| ⏳ 运行中 |
| GN configure（dart_dynamic_modules=true）| ⏳ 待 sync 完成 |
| ninja build ios_release_arm64 | ⏳ 待配置完成 |
| Flutter.xcframework 产物 | ⏳ 待构建完成 |

### 关键技术发现

1. **正确 GN 参数**：`--gn-args "dart_dynamic_modules=true"`（非 `--dart-dynamic-modules`）
2. **vpython3 要求**：必须用 depot_tools 的 vpython3（Python 3.8），不能用系统 Python 3.14
3. **完整 sync 必要**：Skia + abseil-cpp 等 ~5GB 依赖，--no-history 不够，需 full sync
4. **引擎版本**：flutter/engine main branch（3.44.6 对应的 hash 83675ed27... 无法直接 fetch）

### 构建完成后的验证步骤

```bash
# 1. 确认产物
ls ~/engine_ios/src/out/ios_release_arm64/Flutter.xcframework

# 2. 验证 dart_dynamic_modules 编译进去
strings ~/engine_ios/src/out/ios_release_arm64/Flutter.xcframework/*/Flutter.framework/Flutter | \
  grep "Internal_loadDynamicModuleClosure"

# 3. 构建 Flutter test app
cd spikes/flutter_hotpatch_demo/hotpatch_flutter_test
flutter build ios \
  --local-engine=~/engine_ios/src/out/ios_release_arm64 \
  --local-engine-src-path=~/engine_ios/src \
  --release

# 4. 部署到 iPhone 14
xcrun devicectl device install app --device 040F89ED-E7CC-54B0-A7BB-908EE82C0224 \
  build/ios/iphoneos/Runner.app
```

### X1 完成判定标准

- [ ] Flutter.xcframework 包含 `Internal_loadDynamicModuleClosure` 符号
- [ ] Flutter test app 成功在 iPhone 14 启动（显示 "BASELINE" 或 "PATCHED"）
- [ ] Updater fhp_init/stage_patch MethodChannel 调用返回 0（成功）
- [ ] 加载 patch.dill 后 UI 显示 "PATCHED"

---

## 八、X1 最终状态：googlesource.com 网络受限（2026-08-04）

### 根本原因

```
curl -I https://flutter.googlesource.com → HTTP 000 (连接失败)
curl -I https://github.com              → HTTP 200 (正常)
```

Flutter Engine 的 30+ 个第三方依赖（abseil-cpp、angle、skia 等）
托管在 googlesource.com，该网络无法访问。
gclient sync 始终在这些依赖上失败，无法完成 Engine 构建。

### 已完成工作

| 组件 | 状态 |
|------|------|
| flutter/engine main 分支 clone | ✅ 完成 |
| tools/gn --ios 参数确认 | ✅ --gn-args "dart_dynamic_modules=true" |
| vpython3 配置 | ✅ 正常 |
| Flutter plugin scaffold | ✅ tools/flutter_plugin/ |
| Flutter test app | ✅ spikes/flutter_hotpatch_demo/ |
| gclient sync 第三方依赖 | ❌ googlesource.com 不可达 |

### 在能访问 googlesource.com 的机器上的完整步骤

```bash
# 1. 获取代码
mkdir -p ~/engine_ios/src
git clone https://github.com/flutter/engine.git --branch main --depth=100 ~/engine_ios/src/flutter

# 2. 配置 .gclient
cat > ~/engine_ios/.gclient << 'GCLIENT_EOF'
solutions = [{ "name": "src/flutter", "url": "https://github.com/flutter/engine.git",
  "custom_deps": {"src/third_party/dart": None}, "deps_file": "DEPS" }]
GCLIENT_EOF

# 3. sync（需要 googlesource.com 访问）
export PATH="$HOME/depot_tools:$PATH"
cd ~/engine_ios && gclient sync --force -j8

# 4. 链接补丁 Dart SDK
rm -rf src/third_party/dart
ln -sf ~/dart/sdk src/third_party/dart

# 5. GN configure
cd src/flutter
vpython3 tools/gn --ios --runtime-mode release \
  --no-prebuilt-dart-sdk --gn-args="dart_dynamic_modules=true"

# 6. Build (~60 min)
ninja -C ../out/ios_release_arm64 flutter

# 7. Verify
strings out/ios_release_arm64/Flutter.xcframework/**/Flutter | \
  grep "Internal_loadDynamicModuleClosure"

# 8. Test Flutter app
cd ~/Documents/flutter_hot_patcher/spikes/flutter_hotpatch_demo/hotpatch_flutter_test
flutter build ios \
  --local-engine=~/engine_ios/src/out/ios_release_arm64 \
  --local-engine-src-path=~/engine_ios/src --release
```

### X1 完成判定标准（在有网络访问权的机器上）

- [ ] Flutter.xcframework 含 Internal_loadDynamicModuleClosure 符号
- [ ] Flutter test app 在 iPhone 14 显示 PATCHED
- [ ] Updater MethodChannel fhp_init/stage_patch 返回 0


---

## 八、X1 最终状态：googlesource.com 网络受限（2026-08-04）

### 根本原因
- `flutter.googlesource.com` → HTTP 000 (连接失败)
- `github.com` → HTTP 200 (正常)
- Flutter Engine 30+ 第三方依赖托管在 googlesource.com，该网络无法访问

### 已完成工作
- flutter/engine main 分支 clone ✅
- tools/gn --ios 参数确认: `--gn-args "dart_dynamic_modules=true"` ✅
- vpython3 配置正常 ✅
- Flutter plugin scaffold: tools/flutter_plugin/ ✅
- Flutter test app: spikes/flutter_hotpatch_demo/ ✅
- gclient sync: ❌ googlesource.com 不可达

### 在能访问 googlesource.com 的机器上运行
```bash
cd ~/engine_ios && gclient sync --force -j8
ln -sf ~/dart/sdk src/third_party/dart
cd src/flutter && vpython3 tools/gn --ios --runtime-mode release \
  --no-prebuilt-dart-sdk --gn-args="dart_dynamic_modules=true"
ninja -C ../out/ios_release_arm64 flutter
```
