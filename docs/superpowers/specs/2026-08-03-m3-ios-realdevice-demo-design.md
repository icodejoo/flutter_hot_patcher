# M3 设计规格：iOS 真机端到端热更新 demo（方案 A）

版本 v1.0 · 2026-08-03

---

## 0. 目标与范围

**目标**：在 iOS 真机上跑通一个最小可验证的热更新 demo——补丁生效、行为可观测、支持回滚。

**范围内**：
- Xcode 工程打包、代码签名、安装到真机
- 基于 `libdart_aotruntime_product.a`（静态库直接初始化 VM）
- V2 closure redirect 机制（Sim 已验证，真机等价）
- bundle 内置 `patch.dill`（demo 阶段不走网络）
- 最小回滚（crash guard via UserDefaults）

**范围外**：
- kernel_linker Mach-O 移植（排在本 milestone 之后）
- 补丁网络下发（M4）
- Flutter framework 集成（使用裸 VM，非 FlutterViewController）
- Android（可与本线解耦独立做）

---

## 1. 构建产物依赖

| 产物 | 来源 | 说明 |
|------|------|------|
| `libdart_aotruntime_product.a` | `~/dart/sdk` iOS arm64 构建 | 静态 VM 库，含解释器（`--dart-dynamic-modules` 开启） |
| `dart2bytecode.dart.snapshot` | 同上 | 用于编译补丁 dill |
| `gen_snapshot_product` | 同上（iOS 交叉编译目标） | 生成 `app-aot-assembly` |
| `gen_kernel_aot.dart.snapshot` | 同上 | Kernel 编译 |
| `vm_platform_strong_product.dill` | 同上 | iOS arm64 VM platform |

构建命令（增量，SDK 已在正确 commit `1aa7d7321fb`）：

```bash
cd ~/dart/sdk
python3 tools/build.py --mode release --os ios --arch arm64 \
  dart2bytecode gen_snapshot gen_kernel_aot_snapshot \
  runtime_kernel_platform_cc dartaotruntime
```

---

## 2. Dart 源码

### 2.1 基线 App 源码（`main.dart`）

```dart
import 'dart:isolate';

late Function() computeVar;

String greet() => 'ORIGINAL';

void main() {
  // late 赋值防止 CHA 去虚化（同 Sim 踩坑 #1）
  computeVar = greet;
  final result = computeVar();
  // 通过 SendPort 把结果传回 C 层
  // 实际实现见 dart_harness.c
}
```

### 2.2 补丁源码（`patch_main.dart`）

```dart
@pragma('dyn-module:entry-point')
String greet() => 'PATCHED';
```

### 2.3 编译步骤

```bash
# 1. Kernel
gen_kernel_aot → app.dill（使用 iOS arm64 vm_platform_strong_product.dill）

# 2. AOT 快照（汇编格式，链接进 Xcode）
gen_snapshot_product --snapshot-kind=app-aot-assembly \
  --assembly=snapshot.S app.dill

# 3. 补丁字节码
dart2bytecode --target vm -Ddart.vm.product=true \
  -Ddynamic.modules.test.mode=aot \
  --bytecode-options=source-positions \
  patch_main.dart → patch.dill
```

---

## 3. Xcode 工程结构

```
HotPatchDemo.xcodeproj/
├── AppDelegate.m
├── ViewController.m          UILabel 展示 greet() 返回值
├── dart_harness.c            VM 初始化 + 补丁加载（改自 Sim dart_cli_demo.c）
├── builtin_shim.cpp          原样复用 Sim 版本
├── snapshot.S                AOT 快照汇编（gen_snapshot 产出）
├── patch.dill                补丁字节码（bundle resource）
└── libdart_aotruntime_product.a  （link phase）
```

### 3.1 dart_harness.c 主要改动（相对 Sim 版本）

- 从 `NSBundle.mainBundle` 读取 `patch.dill` 路径（替代硬编码路径）
- 通过 callback 把 `greet()` 结果传回 ObjC 层（替代 `printf`）
- 去掉 `main_impl.o` 冲突处理（Xcode link 不会引入它）

### 3.2 Xcode 配置要点

- **Architectures**: `arm64`（真机）
- **Signing**: 普通 Personal Team / 开发证书即可
- **Entitlements**: 无需特殊 entitlement（patch.dill 是 DATA 读取，非 mmap exec）
- **Other Linker Flags**: `-ObjC`，链接 `libdart_aotruntime_product.a`
- **Build Phase**: `snapshot.S` 加入 Compile Sources

---

## 4. 运行时流程

```
App 启动
  │
  ├─ 读 UserDefaults["patch_status"]
  │    "bad" → 跳过补丁，走基线（回滚路径）
  │    其他  → 继续
  │
  ├─ 写 UserDefaults["patch_status"] = "loading"（crash guard 开始）
  │
  ├─ dart_harness_init()
  │    Dart_SetVMFlags → Dart_Initialize → Dart_CreateIsolateGroup
  │    检查 bundle 内是否存在 patch.dill
  │      存在 → loadDynamicModule(patch.dill) + redirectClosureEntryPoint
  │      不存在 → 纯基线运行
  │
  ├─ result = dart_invoke_greet()
  │
  ├─ 写 UserDefaults["patch_status"] = "ok"（crash guard 结束）
  │
  └─ ViewController.label.text = result
```

### 回滚触发条件

- 上次启动在 `"loading"` 阶段崩溃 → `patch_status` 停留在 `"loading"` → 本次启动判定为 `"bad"` → 跳过补丁

---

## 5. 验证矩阵

| 场景 | 操作 | 期望结果 |
|------|------|---------|
| 无补丁基线 | 从 bundle 中移除 patch.dill | UILabel: `ORIGINAL` |
| 补丁生效 | bundle 含 patch.dill | UILabel: `PATCHED` |
| 回滚（模拟崩溃） | 手动写 `patch_status = "loading"` 后重启 | UILabel: `ORIGINAL` |
| 回滚解除 | 从 bundle 移除 patch.dill 后重启 | UILabel: `ORIGINAL`，`patch_status` 清除 |

---

## 6. 已知风险与缓解

| 风险 | 可能性 | 缓解 |
|------|--------|------|
| iOS arm64 构建失败（SDK 版本问题） | 低（Sim 同一 SDK 已构建） | 参考 `flutter-engine-rebuild` skill §6 换 commit 流程 |
| `app-aot-assembly` 命名空间与 Flutter Engine 冲突 | 低（不引入 Flutter Engine） | 裸 VM，无冲突 |
| `libdart_aotruntime_product.a` 尺寸导致 IPA 过大 | 中（~40-60MB） | demo 阶段可接受 |
| `dart:io` native 未注册 | 已知（Sim 踩坑 #8） | 源码不用 `exit()`，`dart:io` 不引入 |

---

## 7. 交付标准（M3 PASS 判据）

- iOS 真机上安装 App，UILabel 显示 `PATCHED`
- 模拟回滚场景（设 `patch_status = "loading"` 后重启），显示 `ORIGINAL`
- Xcode build log 无 error，设备不需要特殊 entitlement

---

## 8. 与后续里程碑的接口

- **M4**：dart_harness.c 的补丁路径改为从 `Documents/` 读（Updater 下载落点），bundle 路径退化为 fallback
- **kernel_linker Mach-O 移植**：`patch.dill` 的生成从手工变为 linker 自动输出，harness 层不变
- **M5**：差分等价测试台复用本 demo 的 `greet()` 场景作为最小用例
