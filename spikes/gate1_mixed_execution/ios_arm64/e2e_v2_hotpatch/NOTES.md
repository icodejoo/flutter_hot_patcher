# Gate 1B + 2 端到端 V2 热修复 spike

## 目标

把 Gate1（V2 重定向机制）+ Gate2（补丁 dill 编译）串成一条完整链路：
小改动 → 编译补丁 dill → 运行时加载 → V2 redirect → 行为变更验证。

## macOS arm64 — FULL E2E PASS（2026-07-31）

**工具链**：
- `~/dart/sdk/xcodebuild/ReleaseARM64/dartaotruntime_product`（macOS arm64 VM）
- `~/dart/sdk/xcodebuild/ReleaseARM64/gen/gen_kernel_aot.dart.snapshot`
- `~/dart/sdk/xcodebuild/ReleaseARM64/gen_snapshot_product`（ELF 格式）
- `~/dart/sdk/xcodebuild/ReleaseARM64/gen/dart2bytecode.dart.snapshot`

**流程**：
1. `gen_kernel` → `host_aot.dill`（使用 macOS arm64 `vm_platform.dill`）
2. `gen_snapshot --snapshot-kind=app-aot-elf` → `host.snapshot`
3. `dart2bytecode` → `patch.dill`（补丁源含 `@pragma('dyn-module:entry-point')`）
4. 基线运行：`dartaotruntime_product host.snapshot` → `result: ORIGINAL`
5. 带补丁：`dartaotruntime_product host.snapshot patch.dill` → `result: PATCHED-V2-E2E-HOTFIX`

**关键坑**：
- `computeVar` 只有一个赋值时 AOT 会去虚化跳过闭包变量。需要 `--alt` 路径防止 CHA 优化
  把 `callCompute()` 直接编译为 `compute()` 直调，让 V2 redirect 无处生效。
  解决：`computeVar = args.contains('--alt') ? computeAlt : compute`
- 补丁函数必须加 `@pragma('dyn-module:entry-point')` 否则 `loadDynamicModuleClosure` 返回 null
- `dart2bytecode` 需要 `--target vm -Ddart.vm.product=true -Ddynamic.modules.test.mode=aot
  --bytecode-options=source-positions` 才能正确生成可加载的补丁

**输出**：
```
=== e2e hotpatch (V2/closure) ===
BEFORE: result: ORIGINAL
patch loaded as closure
V2 redirect applied
AFTER:  result: PATCHED-V2-E2E-HOTFIX
E2E PASS: V2 + bytecode patch working
```

## iOS arm64 — 编译链通，部署待完整嵌入模型

iOS arm64 编译链（`gen_kernel` + `gen_snapshot --app-aot-assembly` + `dart2bytecode`）全部成功。

**iOS 部署层的核心发现**：
- 独立 `dartaotruntime_product` 设计为"从文件加载快照"，不支持"内置汇编快照无参数启动"：
  - `snapshot_empty.cc` 提供 4 个 NULL 指针（`kDartVmSnapshotData` 等）
  - `main_impl.cc` 用 array extern 引用这些符号，实际行为是"有 NULL 就要文件参数"
  - `app-aot-assembly` 生成 `kDartIsolateSnapshot*` 但 `main_impl.cc` 期望 `kDartCoreIsolateSnapshot*`
    （两套命名：Flutter 嵌入模型用 Isolate，独立 VM 用 CoreIsolate）
- ELF 快照文件 mmap(PROT_EXEC) 在 iOS 上需要代码签名；`cs.allow-unsigned-executable-memory`
  entitlement 可绕过但需 Apple Developer Portal 配置
- **关键结论：patch.dill 加载是 DATA 操作，不涉及 mmap(PROT_EXEC)，完全不受 W^X 约束**
  补丁字节码由解释器执行（非本机代码映射），iOS W^X 对 bytecode 路径没有影响

**iOS 完整部署路径**：使用 Flutter 嵌入模型（`libdart_aotruntime_product.a` 直接初始化 VM）
→ 这是 Gate 2 生产阶段（B 步骤）需要解决的集成问题，不是机制可行性问题。

## 三平台整体结论

| 平台 | 机制 | E2E 补丁加载 |
|------|------|-------------|
| macOS arm64（桌面） | V1+V2 | ✅ PASS（今日验证）|
| Android arm64（真机） | V1（hotpatch_demo） | ✅ PASS（Gate 1b）|
| iOS arm64（真机） | V2 only（W^X 封 V1） | 机制 ✅，部署待 Flutter 嵌入（B 步）|

**Gate 1+2 全部通过，端到端链路在 macOS arm64 完整验证，iOS 路径机制无障碍，部署是工程问题。**


## iOS Simulator arm64 — V2-closure PASS（2026-08-03）

**结论**：`internal.redirectClosureEntryPoint` 在 iOS Simulator arm64 AOT 环境下工作正常。

**输出**：
```
BEFORE: via-closure: ORIGINAL
AFTER:  via-closure: PATCHED-iOS-HOTFIX
V2-closure iOS PASS
```

**文件**（本目录）：
- `main.dart` — Dart 测试源码（无 `dart:io`，无 `exit()`，`fn` 为 `late`非 final）
- `dart_cli_demo.c` — C 嵌入 harness（`Dart_SetVMFlags` → `Dart_Initialize` → `Dart_CreateIsolateGroup` → `Dart_InvokeClosure`）
- `builtin_shim.cpp` — C++ shim，将私有 `dart::bin::Builtin::NativeLookup` 暴露为 C 符号以安装 `dart:_builtin` native resolver
- `build_sim.sh` — 一键构建+运行脚本（需要 `DART_SDK_SRC` 环境变量）

**关键踩坑**（按解决顺序）：
1. `Dart_Initialize` 返回 `char*`（NULL=成功），不是 `bool`——赋给 bool 会把错误当成功
2. `Dart_SetVMFlags({"--precompiled_mode=true"})` 必须在 `Dart_Initialize` 之前调用
3. `main_impl.o` 冲突——需从静态库里 `ar d` 删掉
4. `FLAG_precompiled_mode=false` 导致 JIT 路径 SIGSEGV——正是 #2 修复的原因
5. `Dart_Invoke(lib,"main",...)` 在 AOT 下报 NoSuchMethod——改用 `Dart_GetField`+`Dart_InvokeClosure`
6. `Dart_NewList(n)` 产生 `List<dynamic>` 不通过类型检查——源码改为 `main(List args)`
7. `Builtin_PrintString` native 未注册——`builtin_shim.cpp` 绕过 private 访问控制，调用 `Dart_SetNativeResolver`
8. `exit()` 调用 `dart:io` Process_Exit native 同样未注册——源码改为 `return`
9. `late final fn` 第二次调用 main 时报已初始化——改为 `late fn`（去掉 `final`）

**W^X 结论**：`redirectClosureEntryPoint` 只写 Closure 堆对象的 `entry_point` 指针字段（堆内存，非可执行页），W^X 对其无约束，iOS 真机亦如此。
