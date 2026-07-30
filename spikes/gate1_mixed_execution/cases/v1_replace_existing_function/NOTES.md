# V1 — 替换既有函数（Gate 1 靶心）

## 命题

已经 AOT 编译的**既有调用点** `g() -> f()`，能否在运行时被重定向到**解释执行、行为不同**的
`f'`？这是全场唯一无公开先例、决定生死的假设。

> 对比：官方 dynamic modules 的 `loadModuleFromBytes` 只做**新增**——加载一个新模块、跑它的
> 入口、可与 AOT 互操作。它**不做替换**（不改既有函数的入口）。所以本用例不能只用公共 API，
> 否则就退化成"互操作"验证，会假阳性通过、证明不了核心命题。

## 可观测判据

`main` 在激活补丁前后各调一次 `g()`：
- BEFORE 期望 `g() got: ORIGINAL`
- AFTER 期望 `g() got: PATCHED`（即既有调用点落进了解释执行的 `fPatched`）

只有 AFTER 变成 PATCHED，才证明"替换"成立。

## 核心待研究机制：入口重定向

`host/main.dart` 的 `_tryActivatePatch` 是占位。真正要探索的是**如何把 `f` 的 Function 入口
切到解释器里的 `fPatched`**。候选路径（Gate 1 要逐一试）：

1. **VM 内部 entry-point 字段（首选切入点）**：已核对源码，**订正上一版引用**——
   `object.h:2326` 的 `DEFINE_NON_POINTER_FIELD_ACCESSORS(uword, entry_point)` 实际属于
   `SingleTargetCache`（内联缓存机制），不是 `Function`/`Code`。真正相关的字段是：
   - `Function::EntryPointOf`（`object.h:3227-3238`，读 `UntaggedFunction::entry_point_`/
     `unchecked_entry_point_`）。
   - `Code::EntryPointOf`（`object.h:7021-7050`附近，读 `UntaggedCode::entry_point_`）。
   - **间接调用**（虚/接口/闭包）经这两个字段跳转；**V1 的静态直调不经过它们**——AOT 编译器
     把 `g()` 对 `f()` 的调用生成为 pc-relative 直跳指令，直接编码进 `g` 的机器码里，
     跳转目标在编译期固化，运行时改 `Function`/`Code` 的 entry_point 字段对它完全无效。
     这条候选路径对 V2（虚调用/接口调用）可能有效，但**救不了 V1**。
   - 解释器调用接口：`Interpreter::Call(const Function&, argdesc, args, thread)`
     （`runtime/vm/interpreter.h`，`#if defined(DART_DYNAMIC_MODULES)` 下）。
   - VM 已有 `is_declared_in_bytecode()` 与一批 `*_bytecode` 已知对象（object.h:540~569），
     说明"函数带字节码、经解释器执行"这条路径 VM 本身支持。
   - **实验手法**：启动期把 `f` 的 `entry_point`（及缓存的 Code）改指向"进入解释器执行 f' 字节码"
     的 stub。**大概率需给 VM 打实验补丁**——这正是 spike 的意义。
2. **dispatch table 重定向**：若 `f` 经虚调用/接口调用进入（V2 专测），改 dispatch table 项即可，
   无需碰机器码。**静态直调（本用例 V1）最难**：`g` 对 `f` 的调用是 pc-relative 硬编码到 `f` 的
   机器码，**不经 entry_point 字段**——所以仅改 entry_point 无法重定向 V1 的直调，必须让 `g` 也转解释
   （传递闭包向上蔓延的第一手证据）。**V1 要实测的正是这一点。**
3. ~~**观察官方 example 的加载路径**：`internal.loadDynamicModule` 内部如何把字节码函数挂进 isolate，
   能否复用同一挂载点，把既有 `CanonicalName` 实体指向新字节码。~~
   **已核实为死路**（`runtime/lib/object.cc:559` `DEFINE_NATIVE_ENTRY(Internal_loadDynamicModule, ...)`）：
   该原生实现只是 `bytecode::BytecodeLoader::LoadBytecode()` 拿到一个全新、独立的 `Function` 对象
   （`is_declared_in_bytecode()`），再用 `DartEntry::InvokeFunction(function, args)` **一次性直接调用**它——
   全程不把这个函数挂进任何已有符号表 / CanonicalName / dispatch table 条目，与既有调用点毫无关联。
   官方机制本质是"独立创建并跑一个新入口"，没有任何"挂载点"可供替换既有函数复用。

## 三种调用形态（V2，产出"传递闭包边界"矩阵）

| 形态 | 调用点性质 | 预期可否重定向 |
|------|-----------|---------------|
| 静态直调（本用例） | pc-relative 硬编码 | 最难；可能须连带调用方一起转解释 |
| 虚调用 / 接口调用 | dispatch table | 应可重定向（改表项） |
| 闭包调用 | 通过 Closure 的 Function | 待测 |

记录每种"可重定向 / 必须连带失效"，直接得到传递闭包的边界——这是 Gate 2 linker 的关键输入。

## 与 ABI（异常/GC）的关系

V1 打通"替换可观测生效"后，V3（异常穿透 f'→g）、V4（f' 内触发 GC）在**同一套 f'/g 混合栈**上加测，
一并覆盖难点 X 的 ABI 面。

## 构建

沿用官方 `run.sh` 的工具链（`--dart-dynamic-modules` 构建的 gen_snapshot / dartaotruntime /
dart2bytecode）。宿主 AOT 编译（含 `f`/`g`），补丁 `f_patch.dart` 经 dart2bytecode 生成字节码。
激活步骤依赖上面待研究的入口重定向机制——**这一步能不能实现，就是 Gate 1 的答案**。

## 关键发现（2026-07-29）：官方机制在设计上明确不支持"替换"

三条证据链均指向同一结论——**这不是实现缺口，是故意的设计限制**：

1. **entry_point 字段无效于 V1**：`Function::EntryPointOf`（`object.h:3227-3238`）/
   `Code::EntryPointOf`（`object.h:7021` 附近）只在虚调用/接口调用/闭包等**间接调用**路径上生效。
   V1 的 `g()->f()` 是 AOT 编译器生成的**静态直调**（pc-relative 直跳，编码进 `g` 的机器码里），
   不经过这两个字段，运行时改它们对 V1 完全无效。
2. **`Internal_loadDynamicModule` 无挂载点**（`runtime/lib/object.cc:559`）：该原生实现只是
   `bytecode::BytecodeLoader::LoadBytecode()` 拿到一个全新独立的 `Function`（`is_declared_in_bytecode()`），
   再用 `DartEntry::InvokeFunction(function, args)` 一次性直接调用它——全程不挂进任何已有符号表 /
   CanonicalName / dispatch table 条目，和既有调用点毫无关联，没有"挂载点"可复用。
3. **官方设计文档明确声明"不可替换"**（`pkg/dynamic_modules/README.md`）：
   > "The main semantic restriction: all extensions are additive. Dynamic modules cannot replace
   > an existing declaration in the application, not even if that declaration was delivered
   > through a dynamic module earlier."

   专门有一条 FAQ「Is Dart Dynamic Modules a "code-push" implementation?」，官方回答 **No**，理由直接点名：
   dynamic modules 只能新增库、不能更新既有声明；若要让动态模块能调用应用里任何东西，就得把整个
   应用暴露进 dynamic interface，那会实质上关掉 tree-shaking 和全程序优化——官方认为这不适合生产环境。

**结论**：Dart 官方 Dynamic Modules 特性，按当前公开设计，从架构上就不是为"替换既有函数"设计的，
只支持"预先声明好的可插拔扩展点"这种加法式扩展。要在此基础上实现 V1 的"入口重定向"，
必须绕开这套公开机制、深入 VM 内部（比如直接改写 `g` 编译产物里的调用指令、或引入全新的
反优化/重编译触发路径），这已经超出"使用现有特性"的范畴，是要在 VM 上做实验性的二次开发。
是否继续投入这个方向、以及投入到什么程度，是 Gate 1 spike 本身要不要继续的关键决策点。

## V1 PASS（2026-07-30）：最终机制与证据

**结论：可以。** 已实测跑通，`g()->f()` 这个既有静态直调调用点，在运行时被重定向到了
解释执行的 `fPatched()`，`AFTER: g() got: PATCHED`，退出码 0（`V1 PASS`）。

机制由两个独立部分拼成，缺一不可（呼应上面"关键发现"里官方机制单独用不够的结论）：

### (a) 够到调用点——纯用户态运行时改写机器码，零 VM 改动

`g()` 对 `f()` 的调用是编译器生成的 `call rel32`（x86-64 opcode `E8`，pc-relative 直跳）。
用 `dart:ffi` + `mprotect`（全部在 `host/main.dart` 的 `_tryActivatePatch` 里，纯 Dart 代码，
不碰 VM 源码）：
1. `Process.runSync('nm', [selfPath])` 读自身 ELF 符号表，拿到 `g`/`f`/重定向目标函数的静态地址。
2. 解析 `/proc/self/maps` 找到自身 ELF 的可执行段映射，算出 load bias（`运行时地址 = load_bias + 静态地址`）。
3. 自检：按 load_bias 换算出 `g()` 的运行时地址，读 4 字节校验函数序言字节，确认换算无误才继续。
4. 在 `g()` 函数体内扫描字节，找到目标恰好等于 `f` 静态地址的 `call rel32` 指令——不依赖硬编码偏移。
5. `mprotect` 把所在页临时改 RWX，改写 4 字节位移让调用改指向新目标，再 `mprotect` 改回 RX。

这一步单独验证过：先把调用点指向另一个 AOT 编译的占位函数 `fAlt`，能通就说明"运行时改写调用指令"
这个机制本身可行（见下方历史记录），与后面接解释器完全解耦验证。

### (b) 够到解释器——VM 层最小新增（两个原生入口，改 C++ 源码 + 重编译）

官方 `loadDynamicModule` 有两个障碍：公开 API 返回 `Future`（虽然底层原生调用其实是同步的），
且同一份模块字节不能加载两次（报"重复库"错误）。绕开方式是新增两个原生入口，
"加载"和"调用"拆成两步：

- `Internal_loadDynamicModuleClosure`（`runtime/lib/object.cc`）：和官方 `Internal_loadDynamicModule`
  几乎一样地加载字节码，但**不直接调用**，而是用 `Closure::New(...)` 包成一个 Closure 对象同步返回——
  只需加载一次，绕开"重复加载"限制。
- `Internal_invokeDynamicModuleClosure`（`runtime/lib/object.cc`）：接收上面的 Closure，取出内部
  `Function`，直接调 `DartEntry::InvokeFunction(function, args)`——**不走 Dart 语言层面的闭包调用
  语法** `closure()`。实测过用语言层 `closure()` 调用会抛
  `NoSuchMethodError: Closure call with mismatched arguments`（字节码声明的入口函数签名表示
  和普通闭包调用的动态派发检查对不上），所以必须像官方原生实现一样，直接从原生层调用
  `DartEntry::InvokeFunction`，绕开这层校验。

两个新原生入口都注册在 `bootstrap_natives.h`，通过 `dart:_internal`（`internal.dart` +
`internal_patch.dart`）暴露成两个新的公开函数：`loadDynamicModuleClosure` / `invokeDynamicModuleClosure`。

### 其他踩坑记录

- **`dart:_internal` 不能随便 import**：CFE 有 `allowPlatformPrivateLibraryAccess` 检查
  （`pkg/kernel/lib/target/targets.dart` + `pkg/vm/lib/modular/target/vm.dart`），默认只放行
  `dart:*` 库自己、`package:dynamic_modules/*`，以及几个按**文件路径子串**匹配的 VM 测试目录，
  其中 `importer.path.contains('test-lib')` 最好用——把用例工作目录路径里塞进 `test-lib` 子串
  （比如 `/root/test-lib-gate1/...`）就能合法导入，不用改编译器源码。

### 诚实的边界（现在能说的、不能说的）

这是桌面 x64 spike 级 PoC，证明的是**机制本身可行**，还没证明的：
- **W^X + 代码签名下是否成立**：桌面 Linux 允许 `mprotect(..., PROT_EXEC)` 把任意页标成可执行；
  iOS 有 W^X 强制和代码签名校验，能不能做等价的运行时改写是阶段 B 才能回答的问题（这正是
  SETUP.md 阶段 B 存在的原因）。
- **并发安全**：改写调用指令时没有做其他线程正在执行到这条指令中途的互斥处理，多线程环境下
  这么直接改字节可能不安全。
- **只测了零参数、无返回值以外副作用的函数**：`f()`/`fPatched()` 都是无参数纯函数，没有测参数
  传递、异常穿透、GC 触发（V2/V3/V4 待办）。
- **改写目标固定**：当前是"编译期已知要重定向到哪个函数"，还没做成"运行时任意加载新函数、
  自动发现调用点"的通用机制。

## 状态

- [x] 用例骨架（host / patch / 判据）
- [x] 环境：`--dart-dynamic-modules` 构建 + 桌面 x64 跑通官方 example（2026-07-29）
- [x] V1 基线构建链路跑通（`build_and_run.sh`，INCONCLUSIVE 符合预期）
- [x] 排查候选路径 1/3（entry_point 字段、loadDynamicModule 挂载点）——均确认对 V1 无效，且官方文档明确
      "不可替换"是设计限制而非实现缺口
- [x] 探索入口重定向机制——**已实现**：运行时机器码改写（纯用户态）+ VM 层最小新增两个原生入口
- [x] V1 静态直调替换可观测生效——**PASS**（2026-07-30，`AFTER: g() got: PATCHED`，exit 0）
- [ ] V2 三形态矩阵 / V3 异常 / V4 GC / V5 压测
- [ ] iOS(arm64) 真机复验——**这是下一个关键节点**：桌面证明的机制在 W^X + 代码签名下能不能成立

## 工作约定（硬性）

遇到任何机制/接口/行为不确定，**先查源码与官方文档，基于证据推进，不猜**：
- dart-lang/sdk（`runtime/vm/*`、`pkg/dynamic_modules`、`pkg/dart2bytecode`、`pkg/vm`、`runtime/docs/*`）
- flutter/flutter（engine 集成、`shell/*`）
- pub.dev（包 API 与文档）
- GitHub issue/PR/commit（设计意图、变更历史）

每个关键判断在 NOTES/结论里标注来源（文件:行 或 URL），便于复核。
