# Gate 1 V1 所需的 Dart VM 最小改动

`gate1_vm_patch.diff` 是应用在 `dart-lang/sdk` 源码 checkout（`~/dart/sdk`）上的 diff，
让 [`cases/v1_replace_existing_function`](../cases/v1_replace_existing_function/) 的
`_tryActivatePatch` 能真正调用解释器执行补丁字节码。详见该用例的 `NOTES.md`「V1 PASS」一节
的完整证据链和设计理由，这里只记应用方式。

## 应用方式

```bash
cd ~/dart/sdk   # 已按 SETUP.md 阶段 A2 fetch 好的源码根目录
git apply /path/to/gate1_vm_patch.diff
./tools/build.py -m release --dart-dynamic-modules runtime runtime_precompiled utils/gen_kernel
```

## 改了什么

新增两个原生入口（不改动任何既有官方行为，纯新增）：

- `Internal_loadDynamicModuleClosure`：和官方 `Internal_loadDynamicModule` 一样加载字节码，
  但不立即调用入口点，而是包成 `Closure` 同步返回——绕开官方 API 的 Future 包装（其实底层
  原生调用本身就是同步的）和"同一模块不能加载两次"的限制。
- `Internal_invokeDynamicModuleClosure`：接收上面返回的 Closure，直接调
  `DartEntry::InvokeFunction`，绕开 Dart 语言层闭包调用的动态派发校验（字节码声明的入口点
  用普通 `closure()` 语法调用会抛 `NoSuchMethodError`）。

通过 `dart:_internal`（`internal.dart` + `internal_patch.dart`）暴露成
`loadDynamicModuleClosure` / `invokeDynamicModuleClosure` 两个新公开函数。

## 用法上的限制

- `dart:_internal` 不能被任意代码 import；CFE 的 `allowPlatformPrivateLibraryAccess` 检查
  只放行几类路径，最省事的是让导入方文件路径包含子串 `test-lib`（VM 自己测试用的白名单，
  按路径字符串匹配，不挑用途）。
- 这是 spike 级最小实现，只覆盖"加载一次、可重复调用零参数入口点"，没做参数传递、
  异常穿透、GC 触发等场景（留给 V2/V3/V4）。
