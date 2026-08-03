# 给 Mac 那边 kernel_linker 的反馈清单

2026-07-31，Windows/WSL2 这边看过 `kernel_linker v1`（commit c4db08f）代码后的反馈，按优先级排列。

---

## 1.（最高优先级，建议先处理）R3 调用图目前漏了"去虚化"这个红线场景

**现状**：`kernel_diff.dart` 的 `_staticCallees`/`_CalleeCollector` 只追踪 Kernel 层的
`StaticInvocation` 节点——也就是 Dart 源码里语法上就是静态调用的部分（顶层函数、`static`
方法）。

**问题**：AOT 编译器会把"实例方法调用，但 CHA 证明只有唯一可能的目标"（Kernel 层是
`MethodInvocation`，不是 `StaticInvocation`）编译成真正的直接跳转（去虚化）。Kernel IR 这一层
根本不知道这件事——去虚化是 AOT 编译阶段才做的决定。目前的调用图分析看不到这类调用边。

**为什么这是红线，不是精度问题**：旧版 Python `diff_linker.py`（工作在机器码/ELF 层）已经
测过并且 PASS 了这个场景（`spikes/gate2_linker/v6_v7_v8/NOTES.md` "V6 去虚化路由"）——因为在
机器码层面，去虚化后的调用看起来就是普通直调，天然被字节级调用图解析捕获。换到 Kernel IR 层
之后，这个安全网消失了：如果一个只通过实例方法调用（哪怕运行时只有一个实现类）被引用的函数
改了，现在的实现可能完全看不到调用方需要转解释——这正好命中 `docs/SPEC.md` §3 点名的红线：
"去虚化:调用点被硬编码为直接跳转→若目标函数被替换,调用方仍跳旧逻辑"。

**有意思的交叉验证**：Mac 自己在 C 步端到端测试里也独立踩中了同一类陷阱（commit ce38762
提到"AOT CHA优化去虚化,--alt参数防止单目标闭包被特化"）——这跟这边 V6 用例第一版被去虚化吃掉
的坑（`entryVar = stepA` 恒定赋值被特化成直调）是同一个机制的两次独立复现，说明这不是偶然，
是真实存在的风险。

**建议方向**（不是唯一解，供参考）：
- 保守做法：任何通过 `MethodInvocation`/`InstanceInvocation` 引用了被改动函数的调用方，一律
  保守标记为"可能受影响"（哪怕过报，不能漏报）——不需要真的做 CHA 分析，只要"看见调用点提到
  这个符号"就播种。
- 精确做法：在 Kernel 层做一个近似的单态性分析（这个函数在当前可见的类继承体系里是否只有一个
  具体实现），只对确认单态的调用点做传播——这个更接近"复刻 AOT 编译器的去虚化判断"，工作量
  明显更大，且必须和实际 AOT 编译器的 CHA 逻辑保持同步（否则又会退化成新的漏判源）。
- 建议先上保守做法（对齐"完备性优先于精确度"的项目原则），精确做法作为后续优化。

---

## 2. R4（ICF/dedup）：建议 Option A（保守过报），附一条待验证的后续方向

**已用 VM 源码确认**（不是猜测）：ICF 在 VM 里是 `ProgramVisitor::DedupInstructions`
（`runtime/vm/program_visitor.cc`），由 `FLAG_dedup_instructions` 控制（默认 `true`，
"Canonicalize instructions when precompiling"），比对对象是 `Instructions`（实际生成的 AOT
机器码），发生在 `gen_snapshot` 快照生成阶段——**严格晚于 Kernel IR**。这确认了 kernel_linker
在 Kernel 层结构上就看不到 ICF 折叠决定，不是实现疏漏。

**建议**：现在选 **Option A**（fingerprint 相同就保守传播），理由跟第 1 条一样——过报不违反
项目"完备性优先于精确度"的红线，Option B 的"等以后有 AOT 工具"暂缓策略风险更高（相当于在
工具具备能力之前放行这个红线场景）。

**尝试过、暂未验证成功的第三条路（供参考，不建议现在依赖）**：设想是 ICF 折叠后两个函数的
`Function` 对象会指向同一个 `Code`/`Instructions` 对象，`analyze_snapshot`（R5 用过的诊断
工具）的 JSON 输出里 Function→Code 的映射理论上能验证这件事，把"猜"变成"读 ground truth"。
实测：写了两个字节应该完全相同的函数（`=> 42`），用非 product 模式的 `gen_snapshot` +
`analyze_snapshot` 查，**两个函数指向了不同的 Code 对象，没有观察到折叠**。没有查清楚原因
（可能是 product/非 product 模式下 ICF 表现不同——`analyze_snapshot` 只能读非 product 快照；
也可能是这个玩具例子没触发折叠阈值/条件）。**这条路有源码依据、方向对，但没有实测证实**，
不能当作已验证结论——如果以后有时间用更真实的语料（不是两个玩具函数）在 product 快照上
（如果有其他方式读取的话）重新测一次，可能能把 Option A 的启发式换成精确 ground truth。

---

## 3. 好消息：R1/R2/R3(部分)/R9 已经是平台无关的，Android 不需要重新实现

`kernel_linker` 完全基于 `package:kernel` 的 `loadComponentFromBinary` 工作在 Kernel `.dill`
IR 层，从头到尾不碰任何 ELF/Mach-O 二进制结构——这意味着 CanonicalName 对齐、body fingerprint
比对、（去虚化之外的）静态调用图、BFS 规模化传播这几项，天然不知道也不关心目标是 iOS 还是
Android，**不需要为 Android 额外实现**。真正需要按平台/架构适配的，只有"从实际快照文件里读出
结构"这一层（如果以后 R6 或者别的需求需要读 AOT 快照本身的数据，比如 R4 那条待验证的
analyze_snapshot 路线）——这一层 iOS 是 Mach-O、Android 是 ELF，读取方式确实不同，但目前
kernel_linker v1 完全没碰这一层，所以现在还谈不上这个问题。

---

## 4. 项目背景补充（如果 Mac 那边设计 R4-R8 优先级时有用）

- 用户已经明确：Android 的目标形态是"差分+原生重定向"（不是整包 `.so` 替换，那只是过渡/保底
  手段），这跟之前 `docs/SPEC.md` §7.1 写的"长期方向,暂缓"定性不一致，这份文档待修正。这意味着
  kernel_linker 的产出（不管是 R1-R3/R9 已完成的部分，还是 R4-R8 在做的部分）以后会同时服务
  iOS（解释器路线）和 Android（原生重定向路线）——两边共用同一套"哪些函数变了"的判断逻辑，
  区别只在于"变了的函数最终指向解释器 stub 还是新编译的原生代码"。
