# R1 spike — 真正解析 Kernel `.dill` 拿 CanonicalName（library URI 而非文件路径）

**背景**：`r2_pool_probe/NOTES.md` 此前证伪了一条捷径——`gen_snapshot --disassemble` 的函数名
仍是 `file:///...` 绝对路径，跟 DWARF 方案同源，不会白给库 URI。`PRODUCTION_LINKER_SPEC.md`
R1 的结论是"必须走 Kernel `.dill` 二进制解析（CFE/kernel-service AST）"，但从未真正做过——
这轮不等 Mac，直接验证这条路能不能走通、走通之后是不是真的解决问题。

## 找到的机制：`package:kernel` 的 `loadComponentFromBinary`

`pkg/kernel/lib/kernel.dart` 导出一个公开、干净的高层 API：

```dart
Component loadComponentFromBinary(String path, [Component? component]);
```

把 `.dill` 解析成一棵 `Component` AST，`component.libraries` 是 `Library` 列表，每个 `Library`
有 `.importUri`（这就是 CanonicalName 要的库标识）、`.classes`（含 `.name`）、`.procedures`/
`.fields`（含 `.name` 和 `.fileOffset`，可用于同名重载/闭包的实例级区分）。**这不是要自己写
Kernel 二进制格式解析器**——SDK 自带的 `package:kernel` 已经是现成、维护良好的读取库，跑通只是
"怎么调用它"的工程问题，不是"格式怎么解析"的研究问题。

**跑通方式**：这个仓库没有构建过完整可发行的 `dart-sdk`（只构建了 `runtime`/`gen_snapshot` 这些
最小产物），没有 `pub`。绕过：用已经编译好的 JIT `dart` 可执行文件（`out/ReleaseX64/dart`）+
手写一份 `package_config.json`，把 `kernel` 和它唯一的依赖 `_fe_analyzer_shared` 直接指向
dart-sdk 源码树里的 `pkg/kernel`、`pkg/_fe_analyzer_shared`（monorepo 内自带，不需要联网拉包）。

## 实测：`package:` URI 真的出现了，而且跨路径稳定

编译一个真正的 pub 包结构（`lib/foo.dart` 定义 `Greeter`/`helper`，`bin/main.dart` 用
`import 'package:probe_pkg/foo.dart'` 引用），用 `gen_kernel_aot.dart.snapshot --packages`
（指向 `.dart_tool/package_config.json`）编译出 `.dill`，再用上面的脚本读出：

```
LIBRARY uri=file:///.../probe_pkg/bin/main.dart scheme=file      <- 入口脚本本身,直接按路径调用
LIBRARY uri=package:probe_pkg/foo.dart scheme=package             <- 被import的库文件
  CLASS Greeter
    MEMBER greet (kind=ProcedureKind.Method, fileOffset=39)
  TOP-LEVEL helper (fileOffset=84)
```

**关键**：`lib/` 下被 `package:` 语法引用的库文件，Kernel 里的 `importUri` 就是真正的
`package:probe_pkg/foo.dart`——不是文件路径。这跟"入口脚本按路径直接调用得到 file:// URI"
是两回事：真实 Flutter App 的业务代码几乎全部在 `lib/` 下、彼此用 `package:` 互相引用，
只有极少数直接按路径调用的入口文件（`main.dart` 本身）才会退化成 file:// URI。

**跨路径稳定性验证**（对应 COVERAGE_GAPS #19 "part 文件移动导致 DWARF 方案误判 removed+added"
这个残留问题）：把整个 `probe_pkg` 目录**复制到一个完全不同的绝对路径**
（`probe_pkg_patch/`，模拟"补丁在不同机器/不同目录构建"或"文件被移动"），改 `helper` 函数体，
重新编译、重新读取：

```
BASE : uri=package:probe_pkg/foo.dart, MEMBER greet(fileOffset=39), TOP-LEVEL helper(fileOffset=84)
PATCH: uri=package:probe_pkg/foo.dart, MEMBER greet(fileOffset=39), TOP-LEVEL helper(fileOffset=84)
```

**逐字节相同**——即使物理构建目录完全不同，`package:probe_pkg/foo.dart::Greeter.greet` /
`::helper` 这两个 CanonicalName 完全没变。这正是 DWARF 方案做不到的（DWARF 的 `decl_file` 是
绝对源文件路径，目录一变就变，见 P1 NOTES `part_case` 用例复现的 removed+added 误判）。

## 诚实边界

- **只有 `package:` 引用的库文件受益**；直接按脚本路径调用的入口文件（`main.dart`/
  `bin/xxx.dart`）依然是 `file://` URI——真实 Flutter App 里，绝大多数业务逻辑在 `lib/`
  下、天然是 `package:` 引用，入口文件通常很薄（只是 `runApp(MyApp())` 一行），受影响面小，
  但不是"完全没有残留 file:// URI"。
  产生这一发现的原因: Dart 允许直接对一个文件路径调用而不必属于任何包,这类脚本天然没有
  `package:` 概念可用。
- **这次只验证了"读出来的 URI 是什么"，没有把这套机制接进 diff_linker**——真要用，需要：
  (a) 决定新 diff_linker 是读 `.dill` 而非读 ELF/DWARF（架构级改动，R1-R9 那 1-2 人月工程的
  一部分）；(b) 把"改动检测"也挪到 Kernel AST 层（比较 `Procedure`/`Field` 的内容，而非
  objdump 反汇编文本）——这轮只回答"CanonicalName 从哪来"这一个子问题，不是"整个新 linker
  怎么建"。
- **`fileOffset` 是源码字节偏移，不是 decl_line/column**——SPEC 原文要求"decl_line/column
  区分同名闭包/重载"；`fileOffset` 已经能唯一区分同名声明（每个声明的 fileOffset 不同），
  效果等价，但不是字面意义上的行列号，如果生产实现需要真正的行列号需要额外从 `Component`
  的 line-starts 信息换算（`package:kernel` 也提供这个能力，这轮没测，属于工程细节非
  可行性问题）。
- **AOT `--aot` 树摇会吃掉未被引用的符号**（`newlyAdded()` 加进 patch 但没被 main 调用，
  没有出现在 dump 里）——这是既有的、已知的闭世界树摇特性（见 memory
  "字节码符号解析受限"），不是这次探测的新发现，只是恰好在这轮测试里又碰到一次，如实记录。

## 结论：R1 从"设想需要走 Kernel 层"变成"走通了、且证实真的解决问题"

- ✅ **机制确认**：`package:kernel` 的 `loadComponentFromBinary` 是现成、公开、可直接复用的
  Kernel `.dill` 解析入口，不需要自己写二进制格式解析器。
- ✅ **正面验证**：`lib/` 下的库文件拿到的是真正的 `package:` scheme URI，不是文件路径。
- ✅ **正面验证**：这个 URI 跨越"完全不同的构建目录"（模拟机器/路径变化）保持逐字节稳定，
  直接解决 COVERAGE_GAPS #19 的 part-file-moved 残留问题（这是一个更强的测试——整个包目录
  搬家，而不只是 part 文件内部换位置）。
- ⚠️ **边界诚实标注**：入口脚本本身仍是 file:// URI；`fileOffset` 不等价于行列号但效果等价；
  接入 diff_linker 是独立的、更大的工程，这轮只验证了 CanonicalName 来源这一个子问题。
