# iOS Simulator V2-closure 热修复 Demo

**验证内容**：`internal.redirectClosureEntryPoint` 在 iOS Simulator arm64 AOT 环境下将闭包重定向到补丁实现。

**结论**：✅ PASS — 输出 `V2-closure iOS PASS`，W^X 无影响（见下文）。

## 文件说明

| 文件 | 用途 |
|------|------|
| `main.dart` | Dart 测试源码（无 `dart:io`，无 `exit()`，`fn` 为 `late` 非 final） |
| `dart_cli_demo.c` | C 嵌入 harness：初始化 VM → 调用 `main([])` → 调用 `main(['--patch'])` |
| `builtin_shim.cpp` | C++ shim：将私有 `dart::bin::Builtin::NativeLookup` 暴露为 C 符号，安装 `dart:_builtin` native resolver |
| `build_sim.sh` | 一键构建 + 运行脚本（8 步） |

## 前置条件

1. macOS + Xcode（含 iOS Simulator SDK）
2. 自编译的 dart-lang/sdk，含以下产物：
   - `xcodebuild/ReleaseARM64/` — 宿主工具链（`dartaotruntime_product`、`gen_kernel_aot.dart.snapshot`）
   - `xcodebuild/ReleaseIosSimARM64/` — iOS Simulator 目标（`gen_snapshot_product`、`libdart_aotruntime_product.a`）
3. 一个运行中的 iPhone Simulator（arm64，iOS 14+）

## 快速运行

```bash
# 1. 确认 Simulator 已启动（记下 UDID）
xcrun simctl list devices | grep Booted

# 2. 构建并运行
DART_SDK_SRC=~/dart/sdk ./build_sim.sh [simulator-udid]
```

默认 UDID：`33F3D819-6B24-4276-88FD-9BAE91D83CAD`（iPhone 17 Pro 26.4.1）。

## 预期输出

```
=== 1. kernel ===
=== 2. snapshot (via simctl spawn) ===
=== 3. assemble ===
=== 4. compile C++ shim ===
=== 5. compile C embedding ===
=== 6. build static lib from Dart runtime objects ===
=== 7. link ===
=== 8. run ===
BEFORE: via-closure: ORIGINAL
AFTER:  via-closure: PATCHED-iOS-HOTFIX
V2-closure iOS PASS
```

## 构建步骤详解

| 步骤 | 工具 | 说明 |
|------|------|------|
| 1. kernel | `dartaotruntime_product gen_kernel_aot.dart.snapshot` | 将 `main.dart` 编译为 `app.dill` |
| 2. snapshot | `xcrun simctl spawn ... gen_snapshot_product` | 生成汇编快照（iOS Simulator 二进制，必须通过 simctl spawn 运行） |
| 3. assemble | `xcrun --sdk iphonesimulator as` | 将 `.S` 汇编为 `.o` |
| 4. shim | `xcrun clang++ -std=c++17` | 编译 `builtin_shim.cpp` |
| 5. harness | `xcrun clang` | 编译 `dart_cli_demo.c` |
| 6. static lib | `ar rcs` + `ar d` | 从运行时 `.o` 集合构建静态库，删除冲突的 `main_impl.o`/`main.o`/`snapshot_empty.o` |
| 7. link | `xcrun clang++` | 链接所有目标 + `-framework Foundation -framework Security` |
| 8. run | `xcrun simctl spawn` | 在 Simulator 内执行 demo |

## 关键设计点

### `builtin_shim.cpp` — 绕过私有访问控制

`dart::bin::Builtin::NativeLookup` 在 `builtin.h` 中为 `private`，无法直接使用头文件。
Shim 重新声明该类（不引入 `builtin.h`），以 `public` 可见性声明同名成员，通过 C linkage 暴露：

```cpp
namespace dart { namespace bin {
class Builtin {
public:
    static Dart_NativeFunction NativeLookup(Dart_Handle, int, bool*);
    static const uint8_t* NativeSymbol(Dart_NativeFunction);
};
}}
extern "C" {
    Dart_NativeFunction builtin_native_lookup_shim(...) { return dart::bin::Builtin::NativeLookup(...); }
    const uint8_t* builtin_native_symbol_shim(...)      { return dart::bin::Builtin::NativeSymbol(...); }
}
```

### `dart_cli_demo.c` — 双次调用验证热修复

1. `Dart_SetVMFlags({"--precompiled_mode=true"})` — 必须在 `Dart_Initialize` 之前
2. `setup_print()` — 通过 shim 调用 `Dart_SetNativeResolver` 注册 `dart:_builtin` resolver
3. `Dart_InvokeClosure(main_closure, [])` — 基线调用，输出 `ORIGINAL`
4. `Dart_InvokeClosure(main_closure, ['--patch'])` — 触发 `redirectClosureEntryPoint`，输出 `PATCHED-iOS-HOTFIX`

## W^X 为何不影响此机制

`redirectClosureEntryPoint` 写的是 Dart 堆上 `Closure` 对象的 `entry_point` 字段（堆内存，数据页），**不是可执行内存页**。iOS W^X 限制的是"同一页同时可写可执行"，堆写入完全不在其约束范围内。Simulator arm64 = 真机 arm64 ISA，故此结论直接适用于 iOS 真机。

## 踩坑速查

| 错误现象 | 根因 | 修法 |
|----------|------|------|
| `Builtin_PrintString` native 未注册 → ABORT | `dart:_builtin` 无 native resolver | `builtin_shim.cpp` + `Dart_SetNativeResolver` |
| `NativeLookup` 是 private member | `builtin.h` 声明为 private | 不引入头文件，直接重声明类 |
| `globals.h` `std::bit_cast` 编译报错 | 引入了 `builtin.h` → `globals.h` 需 C++20 | 改为不引入头文件 |
| `Process_Exit` native 未注册 → ABORT | `exit()` 调用 `dart:io` resolver | 源码去掉 `dart:io`，`exit()` 改 `return` |
| `LateInitializationError: Field 'fn' already initialized` | `fn` 声明为 `late final`，第二次调用 main 试图赋值 | 改为 `late`（去掉 `final`） |
| Kernel format 130 vs 125 mismatch | `.dart_sdk_mirror` 来自旧 pub release | `rsync` 从自编译 SDK 同步（见 `setup.sh` `DART_SDK_SRC`） |
