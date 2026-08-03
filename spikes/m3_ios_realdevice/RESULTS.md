# M3 iOS 真机 Demo 结果

## 设备
- iPhone 14 (iPhone14,7), UDID: 040F89ED-E7CC-54B0-A7BB-908EE82C0224
- iOS 26.5 (SDK iPhoneOS26.5)

## 结论
**V2 redirect 机制在 iOS 真机 AOT 环境下工作正常。**
- `redirectClosureEntryPoint`（通过 `@pragma vm:external-name Internal_redirectClosureEntryPoint`）
  在 iOS 真机 arm64 AOT 下成功将 closure 的 entry_point 字段重定向到补丁实现。
- W^X 对 closure entry_point 字段写入（堆内存，非可执行页）无约束，iOS 真机实测确认。

## 场景验证

### 场景 1: 正常补丁生效
**条件**: patch_status = nil (首次安装)
**Console 输出**: `[M3] Dart result: PATCHED`
**结果**: PASS

### 场景 2: crash-guard 触发回滚
**条件**: patch_status = "loading"（模拟上次崩溃）
**Console 输出**: `[M3] Dart result: ORIGINAL`
**结果**: PASS

### 场景 3: 回滚解除
**条件**: 移除强制回滚代码，patch_status = nil
**Console 输出**: `[M3] Dart result: PATCHED`
**结果**: PASS

## 技术要点（关键踩坑）

1. **gen_snapshot 目标平台**: 需用 iOS 目标的 gen_snapshot（`xcodebuild/ReleaseIosARM64/clang_arm64/gen_snapshot_product`），
   不能用 host macOS gen_snapshot（会生成 macOS 段语义的汇编）。

2. **dart:_internal 访问限制**: gen_kernel 不允许用户代码 `import 'dart:_internal'`。
   解法：`@pragma('vm:external-name', 'Internal_redirectClosureEntryPoint')` 直调 native。

3. **BootstrapNatives resolver**: `builtin_shim.cpp` 需要暴露 `BootstrapNatives::Lookup`（非 `Builtin::NativeLookup`），
   使 VM 对 `DN_*` bootstrap natives 使用正确的 `BootstrapNativeCallWrapper` ABI。

4. **AOT CHA 去虚化**: `greetVar` 只赋一个值时 AOT 会直接内联/去虚化调用，导致 redirect 无处生效。
   解法：添加 `greetAlt` 第二条赋值路径，让 CHA 无法确定唯一目标。

5. **静态库拆分**: 998MB 单体库 `-all_load` 会引入大量 duplicate symbol（JIT + precompiler 与 AOT 冲突）。
   解法：只链接 AOT product 相关 `.o` 文件（`dartaotruntime_product_set.*` + 对应依赖库）。

6. **cfprefsd 缓存**: 通过 `devicectl device copy` 直接写入 NSUserDefaults plist 不会绕过 cfprefsd 内存缓存。
   场景 2/3 测试需要 uninstall + reinstall 以清除 cfprefsd 缓存，再写入目标 plist 后启动。

## M3 判定
**PASS** — 正式研发前置条件全部满足，可进入 M4（私有化闭环）。
