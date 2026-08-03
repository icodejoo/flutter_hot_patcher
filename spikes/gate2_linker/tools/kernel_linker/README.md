# kernel_linker

Kernel 层（`.dill` 文件）逐函数差分工具。给定基线和补丁两份 AOT 编译产物的 kernel 文件，输出：
- 直接变化的函数（`CHANGED`）
- 新增/删除函数（`ADDED`/`REMOVED`）
- ICF 去重等价组受影响的函数（`ICF PEERS`）
- 传递受影响的调用方闭包（`TRANSITIVELY AFFECTED`）
- 类层次结构变化（cid/vtable 漂移风险）

## 快速开始

```bash
# 前置：设置 DART_SDK_SRC 指向自编译的 dart-lang/sdk 根目录
export DART_SDK_SRC=~/dart/sdk

# 初始化（拉取 kernel 包镜像，首次运行需要）
./setup.sh

# 运行差分
./run.sh --base base.dill --patch patch.dill

# JSON 输出（供下游工具消费）
./run.sh --base base.dill --patch patch.dill --json

# 详细模式（列出所有受影响函数）
./run.sh --base base.dill --patch patch.dill --verbose
```

## 编译 .dill 文件

```bash
OUT="$DART_SDK_SRC/xcodebuild/ReleaseARM64"   # macOS arm64；Linux 用 out/ReleaseX64

$OUT/dartaotruntime_product \
  $OUT/gen/gen_kernel_aot.dart.snapshot \
  --platform $OUT/vm_platform.dill --aot \
  --output base.dill  base.dart

$OUT/dartaotruntime_product \
  $OUT/gen/gen_kernel_aot.dart.snapshot \
  --platform $OUT/vm_platform.dill --aot \
  --output patch.dill patch.dart
```

两个 `.dill` 文件必须从**同一个文件路径**的不同版本编译（同一 library URI），否则 canonical name 无法对齐，所有函数会显示为 ADDED + REMOVED 而非 CHANGED。

## 输出格式

```
=== kernel_linker ===
Base : 1234 procedures
Patch: 1235 procedures

ADDED (1):
  + file:///path/to/lib.dart::MyClass::newMethod

CHANGED (2):
  ~ file:///path/to/lib.dart::MyClass::fee
  ~ file:///path/to/lib.dart::MyClass::label

ICF PEERS (0) — were identical to a changed function:
  (use --verbose to list)

TRANSITIVELY AFFECTED (3):
  (use --verbose to list)

CLASS HIERARCHY CHANGES (0) — cid/vtable drift risk:
  NOTE: Any class hierarchy change may shift cid values and invalidate virtual dispatch.

Patch set: 6 functions
```

### JSON 输出字段

```json
{
  "base_count": 1234,
  "patch_count": 1235,
  "added": ["..."],
  "removed": ["..."],
  "changed": ["..."],
  "icf_affected": ["..."],
  "transitively_affected": ["..."],
  "class_hierarchy": {
    "added_classes": [],
    "removed_classes": [],
    "hierarchy_changed": [],
    "member_layout_changed": []
  }
}
```

## 命令行参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `--base <path>` | ✅ | 基线 .dill 文件路径 |
| `--patch <path>` | ✅ | 补丁 .dill 文件路径 |
| `--json` | — | 输出 JSON（默认为文本） |
| `--verbose` | — | 列出所有 ICF peers 和传递闭包成员 |
| `--allow-empty` | — | 无变化时不以 exit 3 报错（调试用） |

## Exit codes

| Code | 含义 |
|------|------|
| 0 | 成功，有变化 |
| 1 | 参数错误 |
| 2 | dill 文件不存在 |
| 3 | 未检测到变化（未传 `--allow-empty` 时） |

## 环境变量

| 变量 | 说明 |
|------|------|
| `DART_SDK_SRC` | dart-lang/sdk 源码根目录（`setup.sh` 和 `run.sh` 均使用） |
| `DART_SDK` | 可选；若设置则使用 `$DART_SDK/bin/dart`，否则用 PATH 中的 dart |

## setup.sh — SDK 镜像同步

`setup.sh` 将 `pkg/kernel` 和 `pkg/_fe_analyzer_shared` 从自编译 SDK rsync 到 `.dart_sdk_mirror/`，供 kernel_linker 的 Dart 代码引用。

```bash
# 必须设置 DART_SDK_SRC，否则 setup.sh 会报错
DART_SDK_SRC=~/dart/sdk ./setup.sh
```

**注意**：`.dart_sdk_mirror/` 已加入 `.gitignore`，不会提交到仓库。每次更新 SDK 后需重新运行 `setup.sh`。

## 已验证的覆盖范围（R1-R9）

| 需求 | 状态 | 说明 |
|------|------|------|
| R1 直接变化检测 | ✅ | Kernel AST 全字段指纹（含常量字面量） |
| R2 常量字面量变化 | ✅ | `Printer.writeProcedureInLibrary` 序列化完整 AST，常量变化自动产生不同指纹 |
| R3 新增/删除函数 | ✅ | Canonical name 集合差集 |
| R4 ICF 去重感知 | ✅ | 检测指纹相同函数组（ICF peers），变化函数所在等价组全部纳入补丁集 |
| R5 类层次结构变化 | ✅ | 检测 cid/vtable 漂移风险，输出 CLASS HIERARCHY CHANGES |
| R6 多架构（Mach-O/ELF） | ✅ | 基于 Kernel .dill（与目标 ISA 无关），天然跨架构 |
| R7 混淆兼容 | ✅ | 基于 Kernel canonical name（库 URI + 类 + 成员），不依赖 AOT 符号名，不受混淆影响 |
| R8 无声失败禁止 | ✅ | 无变化时 exit 3（除非 `--allow-empty`）；dill 文件不存在时 exit 2 |
| R9 传递闭包计算 | ✅ | 调用图反向传播：直调 + 去虚化 + 内联调用者递归纳入 |

## 实现文件

| 文件 | 职责 |
|------|------|
| `bin/kernel_linker.dart` | CLI 入口，参数解析，文本/JSON 输出 |
| `lib/kernel_diff.dart` | 核心差分逻辑：指纹计算、变化检测、传递闭包 |
| `lib/canonical_name.dart` | Canonical name 解析（库 URI → 类 → 成员） |
| `lib/class_hierarchy.dart` | 类层次结构变化检测 |
| `lib/icf_groups.dart` | ICF 等价组检测 |
| `lib/instance_edges.dart` | 实例调用边提取（虚调用/接口调用） |
