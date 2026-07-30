# Gate 1 V1/V2 所需的 Dart VM 最小改动

`gate1_vm_patch.diff` 是应用在 `dart-lang/sdk` 源码 checkout（`~/dart/sdk`）上的 diff，
支撑三个用例：
- [`cases/v1_replace_existing_function`](../cases/v1_replace_existing_function/) 的
  `_tryActivatePatch` 真正调用解释器执行补丁字节码。
- [`cases/v2_call_forms_matrix`](../cases/v2_call_forms_matrix/) 的虚调用/闭包调用重定向。
- [`android_arm64/`](../android_arm64/) V1 在 Android arm64 真机上的复现。

详见各用例的 `NOTES.md` 完整证据链和设计理由，这里只记应用方式和构建坑。

## 应用方式

```bash
cd ~/dart/sdk   # 已按 SETUP.md 阶段 A2 fetch 好的源码根目录
git apply /path/to/gate1_vm_patch.diff
./tools/build.py -m release --dart-dynamic-modules runtime runtime_precompiled utils/gen_kernel
```

**⚠️ 构建系统坑（2026-07-30 实测，务必看）**：上面这条 `build.py` 命令对这份 diff
**不可靠**——增量构建下有两处依赖追踪失效，静默产出旧的二进制（`exit code 0`，但改动没生效）：

1. `vm_platform.dill`（CFE 编译宿主代码时用来解析 `dart:_internal` 等核心库声明的缓存产物）
   不在 `runtime`/`runtime_precompiled`/`utils/gen_kernel` 这几个目标名的依赖图里，
   改了 `sdk/lib/internal/internal.dart` 之类的核心库源码后**不会自动重建**。
   **强制刷新**：
   ```bash
   cd out/ReleaseX64 && ../../buildtools/ninja/ninja vm_platform.dill \
     dart-sdk/lib/_internal/vm_platform.dill dart-sdk/lib/_internal/vm_platform_strong.dill
   ```
2. `runtime/vm/bootstrap_natives.cc`（维护原生函数注册表的 `.cc` 文件）对
   `runtime/vm/bootstrap_natives.h` 的 `#include` 依赖没有被 ninja 的 depfile 正确追踪——
   改了 `.h` 里的 `BOOTSTRAP_NATIVE_LIST` 宏（加新原生函数）后，`.cc` 不会自动重新编译，
   新函数编译进了 `object.cc` 的 `.o` 但**没有被注册表引用**，链接产物里直接找不到符号，
   运行时报 `Failed to resolve native function 'XXX'`。
   **强制刷新**：
   ```bash
   touch runtime/vm/bootstrap_natives.cc
   cd out/ReleaseX64 && ../../buildtools/ninja/ninja dartaotruntime_product gen_snapshot_product
   ```

**每次改这份 diff 或往上加新原生函数后，按顺序做**：改源码 → 跑一次
`./tools/build.py ...`（正常构建其余部分）→ 上面两条强制刷新命令 → 用 `nm` 验证
（`nm out/ReleaseX64/dartaotruntime_product | grep DN_Internal_你的函数名`，能搜到才算数，
不要只看 `exit code 0` 就信了）。

## 改了什么

新增四个原生入口（不改动任何既有官方行为，纯新增）：

- `Internal_loadDynamicModuleClosure`：和官方 `Internal_loadDynamicModule` 一样加载字节码，
  但不立即调用入口点，而是包成 `Closure` 同步返回——绕开官方 API 的 Future 包装（其实底层
  原生调用本身就是同步的）和"同一模块不能加载两次"的限制。
- `Internal_invokeDynamicModuleClosure`：接收上面返回的 Closure，直接调
  `DartEntry::InvokeFunction`，绕开 Dart 语言层闭包调用的动态派发校验（字节码声明的入口点
  用普通 `closure()` 语法调用会抛 `NoSuchMethodError`）。
- `Internal_redirectDispatchTableEntry`（V2）：改写虚调用/接口调用的 dispatch table 里
  对应 class id 的那一项，让所有按该 cid 分发的调用统一重定向。
- `Internal_redirectClosureEntryPoint`（V2）：直接调用 VM 既有的 `Closure::set_entry_point`，
  改写某个闭包实例自己的 entry_point 字段。

通过 `dart:_internal`（`internal.dart` + `internal_patch.dart`）暴露成
`loadDynamicModuleClosure` / `invokeDynamicModuleClosure` /
`redirectDispatchTableEntry` / `redirectClosureEntryPoint` 四个新公开函数。

## 用法上的限制

- `dart:_internal` 不能被任意代码 import；CFE 的 `allowPlatformPrivateLibraryAccess` 检查
  只放行几类路径，最省事的是让导入方文件路径包含子串 `test-lib`（VM 自己测试用的白名单，
  按路径字符串匹配，不挑用途）。
- V1 部分是 spike 级最小实现，只覆盖"加载一次、可重复调用零参数入口点"，没做参数传递、
  异常穿透、GC 触发等场景（留给 V3/V4）。
- V2 的 dispatch table 重定向只测过两个具体实现类的场景，没测过大规模 cid 空间/并发场景。

## 跨平台移植踩坑（交叉编译到 Android arm64 时暴露，务必看）

`Internal_redirectClosureEntryPoint` 里，`GET_NON_NULL_NATIVE_ARGUMENT` 提取的两个变量
一开始放在 `#if defined(DART_PRECOMPILED_RUNTIME)` **外面**——这在桌面 x64 的
`dartaotruntime_product`/`gen_snapshot_product` 构建变体下没问题（这两个变体都定义了
`DART_PRECOMPILED_RUNTIME`），但交叉编译到 Android/iOS 等目标架构时，会触发 `gen_snapshot`
的 `precompiler_product` 变体——这个变体**不**定义 `DART_PRECOMPILED_RUNTIME`，走
`#else` 分支，两个变量完全没用上，在 `-Werror -Wunused-variable` 下编译直接报错。
diff 里已经修好（把 `GET_NON_NULL_NATIVE_ARGUMENT` 挪进 `#if` 分支里面）。**结论**：
以后凡是 `#if defined(DART_PRECOMPILED_RUNTIME)` 里才用到的变量，提取语句也要放进
同一个 `#if` 分支，不要放在外面——这条只在交叉编译到桌面 x64 以外的架构时才会暴露，
纯 x64 desktop 迭代永远测不出来。

## Android arm64 交叉编译（Gate 1b，验证过程见 `android_arm64/NOTES.md`）

除了应用这份 diff、正常构建桌面 x64（`out/ReleaseX64`），还需要额外交叉编译一份 Android
arm64 目标：

```bash
# .gclient 加 custom_vars: {"download_android_deps": True} 和 target_os = ["android"]
cd ~/dart && gclient sync -D

cd ~/dart/sdk
./tools/build.py --os android --arch arm64 -m release --dart-dynamic-modules \
    runtime runtime_precompiled utils/gen_kernel

# 默认目标名不包含需要的具体产物（同样的坑，见 skill）：
cd out/ReleaseAndroidARM64
../../buildtools/ninja/ninja exe.stripped/dartaotruntime \
    clang_x64/exe.stripped/gen_snapshot_product \
    gen/gen_kernel_aot.dart.snapshot gen/dart2bytecode.dart.snapshot vm_platform.dill
../../buildtools/ninja/ninja 'runtime/bin:dartaotruntime_product'
```

**编译 Dart 源码的工具（`gen_kernel`/`dart2bytecode`）继续用桌面 x64 那份**（跟目标 CPU
无关），只有 `gen_snapshot`（生成 AOT 机器码快照）和 `vm_platform.dill` 需要
Android arm64 版本——完整说明见 `android_arm64/NOTES.md`「环境搭建」一节。
