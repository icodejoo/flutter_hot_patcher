# Gate 1 报告 — 混合执行 ABI（难点 X）

版本 v1.0 · 2026-07-30
状态：**桌面阶段（阶段 A，V1-V5）全部 PASS** · 阶段 B（iOS 真机）未开始

本报告面向两个用途：(1) 提交给 Fable 审核 Gate 1 的结论与证据是否站得住；
(2) 后续迭代/维护时的技术参考。写法上不重复各 `NOTES.md` 的完整反汇编细节，
而是把决策链、证据出处、踩坑和结论串成一条完整的叙事；细节请跳转到对应链接。

---

## 1. 摘要（TL;DR）

- **Gate 1 的命题**（`docs/PRD.md` §8、`docs/SPEC.md` §3"难点 X"）：解释执行的函数与
  AOT 机器码函数能否安全互操作——AOT→解释器调用、异常跨栈正确抛出/捕获、GC 时两种栈帧
  都被正确扫描。这是 Gate 制的第一道、决定生死的验证。
- **结论：PASS。** 在桌面 x64 (WSL2 Ubuntu) 上，用一套"运行时改写调用点机器码（纯用户态）
  + VM 层四个最小新增原生入口"的机制，实测验证了：
  1. 已 AOT 编译的既有静态直调调用点，可在运行时被重定向到解释执行、行为不同的代码（V1）。
  2. 虚调用/接口调用、闭包调用两种间接调用形态，各有比静态直调更优雅的单点重定向方式
     （改 dispatch table 一项 / 改 Closure 对象一个字段）（V2）。
  3. 解释执行代码抛出的异常，能正确穿透被运行时改写过的 AOT 帧（本地 catch + 向外穿透
     两种场景）（V3）。
  4. 解释执行代码内部触发 GC，不会破坏 AOT 调用方帧上存活的对象，GC 后解释器内部分配
     依然正确（V4）。
  5. 高频调用（10 万次）和真实并发竞争（8 isolate、1.6 亿次调用，主 isolate 同时在改写
     共享调用点）下机制保持稳定，零崩溃/损坏（V5）。
  6. **（2026-07-31 追加）多跳纯静态直调链，完全不用 V1，只靠传递闭包+一次 V2 数据
     重定向也能正确生效**（V6）——订正了此前"任何静态直调点都需要V1"的不准确表述，
     见 §5 订正说明与 `cases/v6_multihop_no_v1/NOTES.md`。这次发现直接呼应了 Mac 在
     iOS 阶段 B 上独立得出的同一结论（见下方"下一步"更新）。
- **同时发现的重要约束**（不是失败，是划定了边界，直接影响 PRD/SPEC 的后续设计）：
  - 官方 `package:dynamic_modules` 按设计**不支持替换既有函数**，只支持加法式扩展——
    这不是实现缺口，官方文档明确声明（§4）。我们的机制完全绕开了这套公开 API，靠
    "运行时改写调用点 + VM 最小扩展"自研实现，这正是 SPEC §3 预判的"全场唯一无公开
    先例的部分"。
  - 补丁（字节码模块）能调用的宿主/核心库 API，受**闭世界 AOT 树摇**严格限制——只能引用
    宿主编译产物**自己已经保留下来**的符号（§6）。这直接量化了 SPEC §9"符号绑定无现成
    答案"这个未决问题的严重程度。
  - 增量构建系统有两处依赖追踪失效的坑，会在 `exit code 0` 的情况下悄悄产出没生效的
    二进制（§7）——这是纯工程坑，不影响结论，但会在后续维护中反复踩，已固化进项目内
    skill（`.claude/skills/gate1-vm-spike/SKILL.md`）。
- **下一步（2026-07-31 更新）**：阶段 B（iOS 真机复验）已开始，Mac 反馈 V1（物理改写
  调用指令）在 iOS 上确认不通——这本身完全在预期内（W^X + 代码签名下几乎注定如此，见
  `spikes/gate2_linker/research_machinecode_route.md`）。**关键的是，V6 用例（本报告
  §5 订正）在桌面 x64 上实测证明 V1 从来不是运行时必需的机制**——静态直调链条完全可以
  只靠传递闭包 + 一次 V2 式数据字段重定向正确生效，Mac 在 iOS 上用等价思路独立得出了
  同一结论。这意味着"V1 在 iOS 不通"**没有威胁到混合执行架构的健全性**：真正决定
  iOS 是否可行的，只剩 V2 本身（纯堆数据写）在真机 W^X 约束下是否成立，这个问题本来
  就该由 V2 独立验证，不依赖 V1——阶段 B 剩下要确认的正是这一点。

---

## 2. 背景：为什么要做 Gate 1，命题从哪来

`docs/PRD.md`/`docs/SPEC.md`（2026-07-29）给出了完整背景，这里只摘要 Gate 1 相关部分：

- **产品动机**：iOS Flutter App 的紧急 bug 需要小时级修复能力，不想依赖 Shorebird（闭源、
  不支持私有化部署、ToS 禁止自托管商用）。目标是自研一套"数据自主可控、可私有化部署"
  的热更新方案，覆盖任意 Dart 代码改动（PRD §2/§6）。
- **技术路线**：SPEC §3 把核心自研工作（linker）拆成两个独立难点，X 是 Y 的前置：
  - **难点 X（本报告）**：混合执行 ABI——运行时问题，因为官方 `interpreter.cc` 现成，
    验证成本相对可控，是第一个要冲的 Gate。
  - **难点 Y（Gate 2，未开始）**：逐函数替换而不破坏全局优化——编译期语义 + 内存布局问题，
    需要"全程序 diff + 智能 linker + 基线正常优化"路线（对标 Shorebird，非公开实现）。
- **Gate 制**（PRD §8）：不一次性投入，按风险从高到低分 Gate。Gate 1 是生死判定；
  Gate 1 通过才投入 Gate 2；任一 Gate 否决就回落到备选方案（Android 自研 + iOS 加急审核/
  购买 Shorebird，PRD §9）。

Gate 1 的具体验证项（SPEC §3 难点 X）：

> AOT → 解释器 调用；解释器 → AOT 回调；异常跨两种栈帧正确抛出/捕获；GC 时两种栈帧都被
> 正确扫描（stackmap），无悬垂/误回收。

本报告记录的 V1-V5 五个 spike 用例，就是逐条覆盖这四项 + 高频/并发稳定性。

---

## 3. 方法论

### 3.1 工作约定（硬性，贯穿全程）

> 遇到任何机制/接口/行为不确定，**先查源码与官方文档，基于证据推进，不猜**。

这条约定记在 `cases/v1_replace_existing_function/NOTES.md` 底部，源码范围：
`dart-lang/sdk`（`runtime/vm/*`、`pkg/dynamic_modules`、`pkg/dart2bytecode`、`pkg/vm`、
`runtime/docs/*`）、`flutter/flutter`、pub.dev、GitHub issue/PR/commit。每个关键判断都
在 NOTES 里标注来源（文件:行号 或 URL）。

这条约定不是走过场——V1 早期版本引用过一处源码位置（`object.h:2326`）后来发现指向
`SingleTargetCache` 而非 `Function`/`Code`（§4.2 有记录并订正），这类"先假设、再用源码
核实"的纠错过程本身也留在了 NOTES.md 里，作为方法论的例证。

### 3.2 环境

WSL2 Ubuntu + 从源码构建的 Dart SDK（`--dart-dynamic-modules` 编译开关），流程和坑
详见 `SETUP.md` + `.claude/skills/gate1-vm-spike/SKILL.md`。要点：

- WSL2 网卡 offload 会导致并发网络请求间歇性 TLS 握手失败（拉 SDK 源码时踩过），
  需要 `ethtool -K eth0 tx off gso off tso off rx off gro off lro off sg off`（每次
  WSL 重启失效）。
- 官方构建命令：`./tools/build.py -m release --dart-dynamic-modules runtime
  runtime_precompiled utils/gen_kernel`，产物在 `out/ReleaseX64/`（`dartaotruntime_product`、
  `gen_snapshot_product`、`gen/dart2bytecode.dart.snapshot`、`vm_platform.dill`）。

### 3.3 反汇编方法论（找调用点/重定向点）

不靠猜，靠反汇编逼近真实指令形态：`nm` 找符号静态地址 → `objdump -d` 看实际指令 →
（若要在运行时改写）解析 `/proc/self/maps` 算 load bias → 自检字节序言确认换算无误 →
扫描字节找目标调用指令 → `mprotect` 改权限、写字节、改回权限。完整方法论和代码见
`.claude/skills/gate1-vm-spike/SKILL.md` §5。

**测试用例设计的一个通用教训**（V2 踩过、值得记录）：验证"能不能重定向某种调用形态"
之前，必须先确认测试用例本身没有被 AOT 编译器优化掉这个形态。V2 第一版里
`closureVar` 全程只赋值一次，AOT 闭包特化直接把间接调用去虚化成了普通直调，反汇编出来
的东西根本不是"闭包调用"。让相关变量的取值依赖运行时参数（`args.contains('--xxx')`）
才能防止编译器把它归约成单一目标。

---

## 4. V1 — 替换既有函数（Gate 1 靶心）

用例：`cases/v1_replace_existing_function/`，完整证据见其 `NOTES.md`。

### 4.1 命题

已经 AOT 编译的既有调用点 `g() -> f()`，能否在运行时被重定向到解释执行、行为不同的
`f'`？对比：官方 dynamic modules 的 `loadModuleFromBytes` 只做**新增**（加载新模块、
跑入口、可与 AOT 互操作），不做**替换**（不改既有函数入口）。

### 4.2 排查候选路径——为什么公开 API 走不通

三条独立证据链，全部指向"这是故意的设计限制，不是实现缺口"：

1. **entry_point 字段无效于静态直调**：`Function::EntryPointOf`（`object.h:3227-3238`）/
   `Code::EntryPointOf`（`object.h:7021` 附近）只在虚调用/接口调用/闭包等**间接调用**
   路径上生效。`g()->f()` 是 AOT 编译器生成的**静态直调**（pc-relative 直跳，编码进
   `g` 的机器码里），不经过这两个字段。
   > 早期版本误引用 `object.h:2326`，核实后发现那是 `SingleTargetCache`（内联缓存）的
   > 字段，不是 `Function`/`Code` 的——已在 NOTES.md 订正，留作方法论例证。
2. **`Internal_loadDynamicModule` 无挂载点**（`runtime/lib/object.cc:559`）：该原生实现
   只是 `bytecode::BytecodeLoader::LoadBytecode()` 拿到一个全新独立的 `Function`
   （`is_declared_in_bytecode()`），再用 `DartEntry::InvokeFunction(function, args)`
   一次性直接调用它——全程不挂进任何已有符号表/CanonicalName/dispatch table 条目，
   没有"挂载点"可复用来替换既有函数。
3. **官方设计文档明确声明"不可替换"**（`pkg/dynamic_modules/README.md`）：
   > "The main semantic restriction: all extensions are additive. Dynamic modules cannot
   > replace an existing declaration in the application, not even if that declaration
   > was delivered through a dynamic module earlier."

   专门有一条 FAQ「Is Dart Dynamic Modules a "code-push" implementation?」，官方回答
   **No**，理由直接点名：dynamic modules 只能新增库、不能更新既有声明；若要让动态模块
   能调用应用里任何东西，就得把整个应用暴露进 dynamic interface，会实质上关掉
   tree-shaking 和全程序优化——官方认为这不适合生产环境。

**这与 PRD §6/SPEC §9 的判断完全对应**：PRD 明确写了"Dart 官方 Dynamic Modules 判定
此路生产不可行"，这次是从源码和官方文档层面拿到了第一手证据支撑这个判断，而不是
转述二手结论。

### 4.3 最终机制（V1 PASS，2026-07-30）

结论：**可以替换。** 机制由两个独立部分拼成，缺一不可：

**(a) 够到调用点——纯用户态运行时改写机器码，零 VM 改动**

`g()` 对 `f()` 的调用反汇编出来是 `call rel32`（x86-64 opcode `E8`，pc-relative
直跳）。用 `dart:ffi` + `mprotect`（全部在 `host/main.dart` 的 `_tryActivatePatch`
里，纯 Dart 代码）：

1. `Process.runSync('nm', [selfPath])` 读自身 ELF 符号表，拿到相关函数的静态地址
   （构建时不能加 `--strip`）。
2. 解析 `/proc/self/maps` 找到自身 ELF 的可执行段映射，算出 load bias
   （`运行时地址 = load_bias + 静态地址`，前提是链接器按 `p_vaddr == p_offset`
   排布 PT_LOAD 段，lld/gold 默认如此）。
3. 自检：按 load_bias 换算出已知函数的运行时地址，读几个字节比对反汇编看到的函数
   序言字节，确认换算无误才继续。
4. 在函数体内扫描字节找 `0xE8` 且目标地址等于已知函数地址的那条指令——不依赖硬编码
   偏移量。
5. `mprotect` 把所在页临时改 RWX，改写 4 字节位移让调用改指向新目标，再 `mprotect`
   改回 RX。

单独验证过：先把调用点指向另一个 AOT 编译的占位函数，能通就说明"运行时改写调用指令"
这个机制本身可行，与后面接解释器完全解耦验证。

**(b) 够到解释器——VM 层最小新增（两个原生入口）**

官方 `loadDynamicModule` 有两个障碍：公开 API 返回 `Future`（底层原生调用其实同步）；
同一份模块字节不能加载两次（报"重复库"错误）。新增两个原生入口，把"加载"和"调用"
拆成两步：

- `Internal_loadDynamicModuleClosure`：像官方实现一样加载字节码，但不直接调用，
  用 `Closure::New(...)` 包成 Closure 对象同步返回——只需加载一次，绕开"重复加载"限制。
- `Internal_invokeDynamicModuleClosure`：接收上面的 Closure，取出内部 `Function`，
  直接调 `DartEntry::InvokeFunction(function, args)`——**不走 Dart 语言层面的闭包调用
  语法**。实测过用语言层 `closure()` 调用会抛
  `NoSuchMethodError: Closure call with mismatched arguments`（字节码声明的入口函数
  签名表示和普通闭包调用的动态派发校验对不上），必须绕开这层校验。

两个新原生入口注册在 `bootstrap_natives.h`，通过 `dart:_internal` 暴露成两个新公开
函数。完整 diff + 应用方式见 `vm_patch/README.md`。

### 4.4 结果

```
BEFORE: g() got: ORIGINAL
AFTER:  g() got: PATCHED
V1 PASS: existing call site g()->f() reached interpreted f'
```

### 4.5 诚实的边界（V1 阶段）

- **W^X + 代码签名下是否成立未知**：桌面 Linux 允许 `mprotect(..., PROT_EXEC)` 把
  任意页标成可执行；iOS 有 W^X 强制和代码签名校验，能不能做等价的运行时改写是阶段 B
  才能回答的问题。
- 只测了零参数、无返回值以外副作用的函数（V3/V4 补上异常/GC）。
- 改写目标固定（编译期已知要重定向到哪个函数），还没做成"运行时任意加载新函数、
  自动发现调用点"的通用机制（这是 Gate 2 linker 的工作范畴）。

---

## 5. V2 — 三种调用形态的可重定向边界矩阵

用例：`cases/v2_call_forms_matrix/`。这是 SPEC §5"传递闭包蔓延边界"设计的关键输入。

### 5.1 命题与方法

V1 只测了最难的静态直调。SPEC §5 提到"虚调用走 dispatch table 天然可重定向"——
这次通过反汇编实测验证，不是从文档推断。

### 5.2 三种形态实测反汇编 + 重定向点

| 形态 | 实际指令 | 重定向点 | 粒度 | 影响范围 |
|---|---|---|---|---|
| 静态直调 | `call rel32` 硬编码进调用方 | 调用点机器码 | 每个调用点 | 只影响被改的那个调用点 |
| 虚调用/接口调用 | `call *(rax+rcx*8)`，按 class id 查 dispatch table | dispatch table 一项 | 每个 class id | 该类所有调用点统一生效 |
| 闭包调用 | `call *rcx`，rcx 读自 Closure 对象自己的 entry_point 字段 | Closure 对象的 entry_point 字段 | 每个闭包实例 | 持有该实例的所有调用点统一生效 |

虚调用反汇编（两个实现类防止去虚化）：
```asm
mov  -0x1(%rax),%ecx      ; 从对象头取 class id
shr  $0xc,%ecx
mov  0x68(%r14),%rax      ; 从线程状态(r14=THR)取 dispatch table 基址
call *(%rax,%rcx,8)       ; 按 cid 索引查表、间接调用
```

闭包调用反汇编（`closureVar` 依赖运行时参数防止去虚化）：
```asm
mov  0x7(%rax),%rcx   ; 从 Closure 对象自己的字段(偏移 0x7)取 entry_point
call *%rcx            ; 间接调用，目标是上面读到的 entry_point
```

**对 SPEC §5"传递闭包"的直接推论**：如果一个既有函数只通过虚调用/闭包调用被引用，
重定向代价很低（改一个点，全类/该闭包实例统一生效）；如果它被静态直调引用，这个调用点
本身没有字段可改。

> **订正（2026-07-31，V6 用例，见 `cases/v6_multihop_no_v1/NOTES.md`）**：上一段曾在
> 此处写"只要有任何一个静态直调调用点引用它，就必须额外处理那个调用点（V1 的机制），
> 且做不到'改一处、全局生效'"——这个表述不准确，容易让人误以为 V1 的物理改写机制是
> 静态直调链路运行时必需的。V6 用例实测证伪：一条 A→B→C 的纯静态直调链，只需
> **传递闭包把 A/B/C 整体标记为转解释 + 在链路最外层的虚调用/闭包边界做一次 V2 式
> 数据字段重定向**，完全不碰任何一条调用指令，链路照样正确生效——因为一旦 A 被传递
> 闭包吸收，A 自己的旧机器码（含它对 B 的静态直调指令）根本不再被执行；仍在原生世界
> 运行的调用者，按传递闭包的定义，不可能通过静态直调触达一个"转解释"函数（否则它自己
> 也会被吸收进闭包，矛盾）。**准确的表述应为**：静态直调本身没有可重定向的字段，所以
> 传递闭包必须把整条静态直调链都纳入"转解释"集合，直到遇到虚调用/闭包边界为止——但
> "纳入转解释集合"不等于"运行时需要 V1 物理改写"，V1 在这条链路的运行时激活过程中
> 从未被调用。这正是 SPEC §5"重定向不靠改机器码"的机制级证据，V1 更准确的定位是
> "验证'能否重定向一个既有函数的可观测行为'这件事本身是否可行"的早期探索手段，不是
> 生产架构运行时依赖的机制。

### 5.3 实测验证（VM 新增两个原生入口）

- `Internal_redirectDispatchTableEntry(instance, replacement)`：取
  `instance.GetClassId()`，取 `replacement` 的 `Function.entry_point()`，写进
  `IsolateGroup::dispatch_table()` 对应 cid 的槽位（新加的 `DispatchTable::SetEntryForCid`
  公开方法）。
- `Internal_redirectClosureEntryPoint(target, replacement)`：直接调用 VM 既有的
  `Closure::set_entry_point()`。

```
BEFORE interface: viaInterface: ORIGINAL
BEFORE closure:   viaClosure: ORIGINAL
AFTER interface:  viaInterface: PATCHED-VIA-DISPATCH-TABLE
AFTER closure:    viaClosure: PATCHED-VIA-CLOSURE-ENTRY-POINT
V2 PASS
```

---

## 6. V3/V4 — 异常穿透 + GC 正确性（混合栈 ABI 面）

用例：`cases/v3_exception_passthrough/`、`cases/v4_gc_inside_patch/`。这两项直接对应
SPEC §3 难点 X 里"异常跨两种栈帧正确抛出/捕获"和"GC 时两种栈帧都被正确扫描"两条验证项。

### 6.1 V3 异常穿透——PASS

两种场景都测：本地 catch（`gCatches`）、向外穿透一整个被打过补丁的 AOT 帧
（`gPropagates` → `main`）。

```
AFTER gCatches:     g() caught: Bad state: PATCHED-EXCEPTION
AFTER gPropagates:  propagated to main, caught: Bad state: PATCHED-EXCEPTION
V3 PASS
```

**机制解释**：没加新 VM 代码，沿用 V1 的 `Internal_invokeDynamicModuleClosure`——
`DartEntry::InvokeFunction` 对解释执行异常包成 `Error` 对象同步返回，
`Exceptions::PropagateError` 在原生调用点重新抛出为真正的 Dart 异常，这是 VM 处理
"原生代码调用 Dart 代码"场景的标准机制。一旦异常在原生调用点冒出来，后续传播就是
普通 Dart 异常穿栈，和该栈帧是否被运行时改写过调用指令无关——因为改写只改了 4 字节
位移、没改指令长度，PC 范围不变，AOT 的异常处理/栈展开元数据（按 PC 区间查 handler）
不受影响。

**踩坑**：补丁若声明自定义异常类（`class PatchException implements Exception`），
字节码**加载阶段**报 `Unable to find function Object. in Library:'dart:core' Class:
Object`——这是 §6.3"符号解析闭世界限制"的一个早期实例，当时先用"避免声明新类型"绕过，
后来 V4 才彻底定位到根因。

### 6.2 V4 GC 正确性——PASS

`g()` 持有一个堆上标记数组跨调用存活，`fPatched()`（解释执行）内部分配 30 万个短
生命周期字符串触发真实 scavenger GC。

```
AFTER: g() got: PATCHED-AFTER-ALLOC-last=garbage-299999; markerIntact=true
V4 PASS
```

标记数组内容原样不变，GC 后解释器内部分配依然正确。

### 6.3 关键发现（比 V4 本身更重要）：字节码模块符号解析受闭世界 AOT 树摇严格限制

这是本报告里**除"官方机制不支持替换"外最重要的架构级发现**，直接量化了
SPEC §9"符号绑定无现成答案"这个未决问题。

调试过程（三次踩同一类坑，逐步定位机制）：

1. 补丁调用 `VMInternalsForTesting.collectAllGarbage()`（`dart:_internal`）强制 GC——
   字节码**加载阶段**报错 `Unable to find class VMInternalsForTesting in
   Library:'dart:_internal'`。让宿主也引用这个类以排除"纯树摇未保留"——**依然失败**。
2. 改用 `List<int>.filled(...)`（`dart:core`）——**同样**加载阶段失败：
   `Unable to find function _List@....filled in Library:'dart:core' Class: _List`。
   排除了"只是 dart:_internal 特殊"这个假设。
3. 改用字符串插值（宿主代码本来就在用）——能过；但对插值结果调一个普通 getter
   `.isNotEmpty`——**又失败**：`Unable to find function get:isNotEmpty in
   Library:'dart:core' Class: String`。

**真正的机制**：不是"这个符号属于哪个库"，是**闭世界 AOT 树摇**——字节码读取器
（`BytecodeReaderHelper::ReadConstantPool`/`ReadObjectContents`）只能把补丁常量池里的
符号引用，链接到宿主编译产物**自己已经保留下来**的声明。宿主代码没用过的东西（哪怕是
`dart:core` 里再普通不过的 getter），AOT 树摇时就被删了，补丁引用必然找不到。字符串
插值之所以每次都能用，纯粹是因为宿主代码自己也在用它构造返回值。

**对 SPEC/PRD 的直接影响**：

- 这正是 `pkg/dynamic_modules/README.md`"默认什么都不暴露，除非显式声明"设计原则的
  另一个体现（§4.2 第 3 条已经从"能不能替换"的角度确认过一次，这次是从"补丁调用普通
  API 也受限"的角度再次确认）。
- 真实生产场景下，**补丁能调用的 API 面，取决于宿主愿意在 `dynamic_interface.yaml`
  里声明多大的 `callable` 范围**——范围越大，AOT 编译器需要保留的东西越多，越接近
  关闭 tree-shaking，和官方 FAQ"暴露太多会实质性关掉全程序优化"的权衡完全对应。
- 这直接呼应 PRD §7"符号绑定无现成答案"和 SPEC §4.5"符号绑定（linker 的另一半，
  官方无现成答案）"——本报告把这个"无现成答案"的问题从"抽象未决项"变成了
  "有具体报错信息、可复现、机制已定位清楚"的工程问题，为 Gate 2 设计 linker 的符号
  绑定策略提供了直接输入：**linker 必须能计算"补丁字节码引用的每个符号，宿主基线
  是否已经保留"，未保留的要么报错拒绝、要么想办法强制保留（类似我们这里"让宿主也
  引用一次"的手法，但那对 V3/V4 都不管用，说明这条路对生产级方案不可靠）**。

### 6.4 关于 dynamic_interface.yaml 的定位（本次 spike 故意留白）

所有 V1-V5 用例都没有配置 `dynamic_interface.yaml`（`--dynamic-interface`/`--validate`
编译参数）。这不是遗漏，是有意的范围控制——本轮 spike 的目标是验证"运行时重定向 +
VM 层最小扩展"这条自研路径本身是否可行，而不是评估官方 `dynamic_interface.yaml`
机制能覆盖多大的 API 面。§6.3 的发现已经把"要不要接这个机制"变成一个明确的后续
问题，留给 Gate 2（linker 设计）或专门的后续 spike 处理。

---

## 7. V5 — 压测（高频 + 并发）

用例：`cases/v5_stress/`。

### 7.1 结果

```
V5b concurrent isolates: 1437655 ORIGINAL (before the race caught up),
  158562345 saw the shared call site flip (no local closure),
  0 unexpected/corrupted (out of 160000000 total)
V5a high-frequency: 100000/100000 calls observed PATCHED
V5 PASS
```

- **V5a 高频**：激活后连续调用 10 万次，100% 一致，零偶发失败。
- **V5b 并发**：8 个 isolate 各跑 2000 万次紧循环调用（共 1.6 亿次），从 spawn 起就
  开始跑，主 isolate 随后才对共享调用点做 `mprotect` + 改字节。真实测到了竞争窗口——
  143 万多次调用捕捉到补丁落地**前**的状态，1.58 亿多次捕捉到落地**后**的状态，
  全程 **0 次**崩溃/损坏。

### 7.2 方法论教训：第一次"通过"是假阳性

第一次跑（8 isolate × 5 万次）结果全部是"补丁前"状态、0 次翻转——worker 在主
isolate 完成 `mprotect` 改写之前就跑完退出了，根本没测到竞争，但 `0 unexpected`
这个数字当时确实是真的。**光看"没出错"不够，必须从数据里确认竞争窗口真的被覆盖到**
（这里是"ORIGINAL 计数 > 0 且翻转计数 > 0"这个条件）。把迭代次数从 5 万提到 2000 万
才测到真实重叠。这条教训已经写进 `NOTES.md` 和项目 skill，避免以后设计并发测试时
重犯。

### 7.3 一个附带发现：isolate 的堆隔离性

Dart isolate 之间不共享堆/全局变量，只有**编译产物（代码）**在同一个 isolate group
内共享。第一版让 worker isolate 直接调用持有解释执行闭包的 `fAlt()` 崩溃了
（`Null check operator used on a null value`）——因为 `_cachedPatch` 是主 isolate
设置的顶层变量，worker isolate 里读到的是它自己那份、从未被赋值过的 `null`。

**没有**尝试"让每个 worker 各自加载同一份模块字节"，因为很可能撞上"重复库"检查
（`bytecode::BytecodeLoader` 的锁是 `thread->isolate_group()->program_lock()`，
这个检查很可能是整个 isolate group 共享的，多个 isolate 各自加载同一份字节大概率
在第二个上报错）——这是一个**独立、这次故意没测**的问题，为了不污染"并发改写调用点
安全不安全"这一个变量。

**对生产设计的启示**：真实部署中，如果补丁需要在多个 isolate 里生效，"调用点重定向"
和"解释执行闭包状态"需要分开处理——前者靠共享代码天然生效，后者需要每个 isolate
独立加载（或者设计一套跨 isolate 共享该状态的机制，这本身也是 Gate 2 需要考虑的
一个设计点）。

### 7.4 诚实的边界

- 只测了"多个 isolate 同时**读**一条正在被改写的指令"是否安全，没测"多个地方同时
  **写**同一个调用点"（写-写竞争）——当前设计里只有一处（main）做改写。
- 8 个 isolate、单机单进程 ≠ iOS 真机多核硬件 + 真实系统调度器，阶段 B 需要重新验证。
- 没有测长时间运行下反复激活/回滚补丁的稳定性，也没有测多个不同函数同时被打补丁。

---

## 8. VM 改动完整清单

diff 文件：`vm_patch/gate1_vm_patch.diff`，应用方式和构建坑详见 `vm_patch/README.md`。

新增四个原生入口（**不改动任何既有官方行为，纯新增**）：

| 原生入口 | 文件 | 作用 |
|---|---|---|
| `Internal_loadDynamicModuleClosure` | `runtime/lib/object.cc` | 加载字节码但不立即调用，包成 Closure 同步返回，绕开官方 API 的 Future 包装和"重复加载"限制 |
| `Internal_invokeDynamicModuleClosure` | `runtime/lib/object.cc` | 直接调 `DartEntry::InvokeFunction`，绕开 Dart 语言层闭包调用的签名校验 |
| `Internal_redirectDispatchTableEntry` | `runtime/lib/object.cc` | 改写虚调用/接口调用的 dispatch table 里对应 class id 的那一项 |
| `Internal_redirectClosureEntryPoint` | `runtime/lib/object.cc` | 调用既有的 `Closure::set_entry_point`，改写闭包实例的 entry_point 字段 |

配套新增：`DispatchTable::SetEntryForCid`（`runtime/vm/dispatch_table.h`，公开写入方法）。

通过 `dart:_internal`（`internal.dart` + `internal_patch.dart`）暴露成四个新公开函数。

**构建系统两个致命坑**（增量构建下 `exit code 0` 但改动未生效，详见
`vm_patch/README.md` 和 skill）：

1. `vm_platform.dill`（CFE 解析 `dart:_internal` 等核心库声明的缓存）不在
   `runtime`/`runtime_precompiled`/`utils/gen_kernel` 的依赖图里，需显式
   `ninja vm_platform.dill ...` 强制刷新。
2. `bootstrap_natives.cc` 对 `bootstrap_natives.h` 的 `#include` 依赖没被 ninja
   depfile 正确追踪，需 `touch` 后显式 `ninja dartaotruntime_product
   gen_snapshot_product` 强制刷新。
3. **唯一可靠的验证方法**：`nm out/ReleaseX64/dartaotruntime_product | grep
   DN_Internal_你的函数名`，不要只看 exit code。

---

## 9. 其他工程性发现

- **`dart:_internal` 的 import 限制**：CFE 有 `allowPlatformPrivateLibraryAccess`
  检查（`pkg/kernel/lib/target/targets.dart` + `pkg/vm/lib/modular/target/vm.dart`），
  默认只放行 `dart:*` 库自己、`package:dynamic_modules/*`，以及几个按**导入方文件
  路径子串**匹配的 VM 测试目录（`importer.path.contains('test-lib')` 最好用）。
  这只影响 spike 用例本身怎么合法 import，不影响生产代码（生产补丁走
  `dynamic_interface.yaml` 机制，不需要这个技巧）。
- **闭包调用会被 AOT 去虚化**（V2 踩过）：如果闭包变量全程只被赋值一次，编译器会把
  间接调用优化成直调。这个现象本身对 Gate 2 linker 的"传递闭包"分析可能有意义——
  意味着"闭包调用"在实际编译产物里不一定真的是间接调用，需要 linker 按实际编译结果
  判断，不能假设"声明为闭包类型 = 间接调用"。

---

## 10. 结论与建议

1. **Gate 1（难点 X）桌面阶段验证通过**：混合执行 ABI 的四个核心问题（AOT→解释器调用、
   异常穿透、GC 正确性、高频/并发稳定性）在桌面 x64 上全部有实测证据支持，机制成立。
2. **官方公开 API 这条路走不通，但自研路径可行**：这验证了 PRD/SPEC 的预判——不能靠
   `package:dynamic_modules` 的公开 API 完成，需要"运行时改写调用点 + VM 最小扩展"
   这条自研路线；本报告给出了这条路线的具体实现和证据。
3. **符号绑定问题比预期更具体、更严格**：闭世界树摇对补丁能调用的 API 有硬约束，
   Gate 2 设计 linker 时，符号绑定策略必须正面处理"补丁引用的符号，宿主基线是否
   已保留"这个问题，不能假设"反正是同一个 SDK 版本就能互相调用"。
4. **下一步决策点**：是否投入阶段 B（iOS 真机复验）。SETUP.md 已给出前提条件
   （获取 Mac 的三种方式）。阶段 B 要回答的问题：W^X + 代码签名下，运行时改写调用点
   这条核心机制是否被系统拦截；解释执行的真机性能；App Store 审核是否放行动态字节码
   （这条理论上应该没问题，因为补丁走的是解释型字节码，符合 Guideline 3.3.1b，
   但"运行时改写已签名代码段的调用指令"这个动作本身在 iOS 上物理上可能不被允许——
   这正是阶段 B 存在的意义）。
5. **（2026-07-31 追加）V1 确认在 iOS 上不通，但 V6 证明这不是问题**：阶段 B 已开始，
   Mac 反馈 V1 的物理改写机制在 iOS 上确实被拦截——完全在预期内。同一时间，V6 用例
   （§5 订正，`cases/v6_multihop_no_v1/`）在桌面 x64 上实测证明：多跳静态直调链完全
   可以只靠传递闭包+一次 V2 数据重定向正确生效，V1 从未被调用。Mac 在 iOS 上用等价
   思路独立得出同一结论。**这意味着 V1 从来不是生产架构运行时依赖的机制**——iOS 上
   "V1 不通"不威胁混合执行架构的健全性，阶段 B 真正要确认的是 V2（纯数据写）本身在
   iOS 真机 W^X 约束下是否成立。

---

## 11. 参考资料索引

### 项目内文档
- `docs/PRD.md`、`docs/SPEC.md`、`docs/PLAN.md` — 产品需求、技术规格、Gate 制划分
- `spikes/gate1_mixed_execution/SETUP.md` — 环境搭建、阶段划分
- `.claude/skills/gate1-vm-spike/SKILL.md` — 完整操作流程、构建坑、反汇编方法论
- `spikes/gate1_mixed_execution/cases/v{1..6}_*/NOTES.md` — 各用例完整证据链
  （V6 是 2026-07-31 追加，验证"V1 是否运行时必需"）
- `spikes/gate1_mixed_execution/vm_patch/{README.md,gate1_vm_patch.diff}` — VM 改动

### 外部源码/文档引用
- `pkg/dynamic_modules/README.md`（dart-lang/sdk）— 官方设计文档，"additive only"声明
- `runtime/vm/object.h`（`Function::EntryPointOf` ~3227 行、`Code::EntryPointOf` ~7021
  行、`Closure::entry_point()`/`set_entry_point()` ~12674 行）
- `runtime/lib/object.cc:559`（`Internal_loadDynamicModule` 原始实现）
- `runtime/vm/dispatch_table.h`（`DispatchTable` 类）
- `runtime/vm/bytecode_reader.cc`（字节码常量池解析、跨库符号解析报错来源）
- `pkg/kernel/lib/target/targets.dart` + `pkg/vm/lib/modular/target/vm.dart`
  （`allowPlatformPrivateLibraryAccess` 检查）

---

## 12. 追加（2026-07-30）：Gate 1b — Android arm64 真机复现

用户手头暂时没有 iPhone，但有 Android arm64 真机可用。V1-V5 全部在 x86-64 桌面验证，
从未测过 arm64——这正是 iOS 最终也要用的同一个 CPU 架构族。在获取 Mac/iPhone 之前，
先用 Android arm64 复现 V1-V5 全部核心机制，是一次**低成本、有实际增量价值**的
预检查：用例见 `android_arm64/`，完整证据见 `android_arm64/NOTES.md`。

**结果：V1-V5 全部 PASS。** 不只是 V1（静态直调替换）——三种调用形态矩阵（V2）、
异常穿透（V3）、GC 正确性（V4）、高频/并发压测（V5）在真实 arm64 硬件上全部复现成立：

```
GATE1B-ANDROID-ARM64 PASS          (V1)
V2 PASS                            (原样跑通，零改动)
GATE1B-V3-ANDROID-ARM64 PASS       (V3)
GATE1B-V4-ANDROID-ARM64 PASS       (V4)
GATE1B-V5-ANDROID-ARM64 PASS       (V5，1.6 亿次调用，0 次损坏)
```

**一条格外有分量的附加证据**：V2（虚调用改 dispatch table 一项、闭包调用改
Closure 对象的 entry_point 字段）在 arm64 上是**原样拷贝、零改动**跑通的——
这实测验证了 V2 桌面阶段矩阵的可移植性推论：重定向点如果是"改一个 VM 管理的
数据结构字段"而不是"改原始机器码"，这套机制天然跨架构。V1/V3/V4/V5 都需要
针对 arm64 重写调用点改写逻辑，唯独 V2 不需要——这条差异本身就是对"传递闭包
边界"设计（SPEC §5.4）的一次交叉验证。

**这次验证解决了什么、没解决什么**，边界必须讲清楚：

- **解决了**：arm64 指令编码层面的机制可行性。arm64 的直调指令是 `bl`
  （反汇编实测确认，编码和 x86-64 的 `call rel32` 完全不同），且 arm64 对
  自修改代码有 x86-64 没有的硬性要求——写完新指令字节后必须显式做指令缓存
  失效（`dc cvau`+`ic ivau`+相应屏障指令），否则 CPU 可能执行到缓存里的旧
  指令。这一整层在 x86-64 桌面验证里完全没有出现过，这次证明了它可以正确
  处理（bionic 没有现成的 `__clear_cache`/`cacheflush` API，靠自己汇编一段
  验证过的机器码、`mmap` 出可执行页来调用）。
- **没有解决**：iOS 那个最核心的悬念——W^X 强制 + 代码签名下，
  `mprotect(PROT_EXEC)` 会不会被系统拦截。**Android 不强制 W^X**，这正是
  Android 上热更新普遍比 iOS 容易的根本原因；这次在 Android 上跑通，
  不能反推 iOS 上也能跑通。阶段 B（iOS 真机复验）依然是唯一能回答这个问题
  的地方，无法被跳过或替代。

**附带发现（符号解析的一个坑）**：`@pragma('vm:entry-point')` 标注的函数
（`fAlt`，为了防止 AOT 树摇而加的保活标注）在 arm64 的符号表里出现了**两个不同
地址**（大概率是 checked/unchecked 两个入口变体，没有逐一反汇编确认）。构建脚本
一开始没处理这种情况，`nm` 匹配出两行地址拼进 shell 变量后嵌入了换行符，把后续
的 `adb shell` 命令字符串拆成两条，第二条（一串裸地址）被设备的 shell 当命令名
执行报错——这个错误在 V1 第一次跑通时就出现过，当时因为"侥幸"选中了两个地址里
排序在前的那个而被忽略，直到 V3 上再次复现才顺藤摸瓜查到根因。修复：所有取地址
的地方都加 `| head -1`，不依赖排序侥幸。**没有验证过两个地址具体对应什么**，
这次的验证目的不需要深究，但以后若要在生产级 linker 里做类似的符号解析，这是一个
需要提前弄清楚的点。

**附带发现（真实的可移植性 bug）**：交叉编译到 Android arm64 时，V2 新增的
`Internal_redirectClosureEntryPoint` 因为 `#if defined(DART_PRECOMPILED_RUNTIME)`
分支边界写得不对（提取参数的语句放在了分支外面），在 `gen_snapshot` 的
`precompiler_product` 构建变体下触发 `-Werror -Wunused-variable` 编译失败——
桌面 x64 的构建变体恰好都定义了这个宏，从未暴露过这个问题。这说明**只在
desktop x64 上迭代，测不出这类"只在跨架构交叉编译时才触发"的坑**，已修复
并更新进 `vm_patch/gate1_vm_patch.diff`。

**结论**：这次验证没有推翻 Gate 1 的任何结论，反而增加了一条正面证据——
核心机制的思路（找调用点 + 改写 + 接解释器）具备跨架构可移植性，每种架构
有各自的指令编码/内存一致性细节要单独处理，但至今没有发现从根本上推翻方案
的新问题。iOS 真机复验（阶段 B）仍是下一个、也是唯一悬而未决的关键节点。

---

## 13. 追加（2026-07-30）：端到端热修复流程演示（真机全流程 PASS）

前面所有验证（V1-V5、Gate 1b）都是 spike 骨架——靠命令行参数手动传字节码路径/
快照路径/十六进制地址，适合单独验证"机制通不通"，不像真实部署会长什么样。
`android_arm64/hotpatch_demo/`（完整证据见其 `NOTES.md`）把同一套已验证机制
重新组织成目标形态并在真机上完整跑通：

1. **安装**（一次性）：编译 app + 生成地址清单 + 推到设备一个稳定目录 + 跑一次
   看基线——`BEFORE: g() got: ORIGINAL`。
2. **推送补丁**：只编译推送一个小字节码文件到独立的补丁目录，已安装的 app
   二进制不再被碰。
3. **重启**：重新调用同一个已安装的二进制（不重新编译、不重装）。它在启动时
   自己检测补丁文件是否存在，存在则加载激活——`AFTER: g() got: PATCHED-V1-HOTFIX`。
4. **二次独立发布**：再推一个不同的补丁、再重启，验证"装一次、之后独立发布
   多次"——`AFTER: g() got: PATCHED-V2-FOLLOWUP-FIX`，全程未重装 app。

这直接对应 SPEC.md §5"运行时模型"里描述的启动流程（引擎/app 启动时决定加载
基线还是解释器 stub，补丁是独立于基线之外可下发的数据），以及 PRD.md §7
"补丁需重启（冷启动）生效"——这次演示的正是这条设计在真机上的最小可行形态。

**诚实边界**：这不是真的 Flutter APK / Engine 集成（那是 Gate 2 的范畴，
工作量完全是另一个量级）；"app"是一个普通的 Dart AOT 可执行文件，"重启"是
重新调用这个可执行文件，不是真的杀掉/拉起一个 Android Activity。核心机制
（调用点改写 + 解释器接入）和 V1-V5、Gate 1b 完全一样，这次新增的只是"围绕
机制的部署流程长什么样"，不是机制本身又多测了一遍。

---

*本报告基于 2026-07-29～2026-07-30 的实测结果。若后续 SDK 版本更新，VM 内部字段
偏移/函数签名可能变化，复现前建议按 `.claude/skills/gate1-vm-spike/SKILL.md` 的
方法重新反汇编确认，不要假设本报告的具体地址/偏移量在新版本上依然成立。*
