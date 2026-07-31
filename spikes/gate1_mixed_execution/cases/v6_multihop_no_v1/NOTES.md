# V6 — 多跳静态直调链，完全不用 V1，只靠传递闭包 + 单次 V2 数据重定向

## 命题

`GATE1_REPORT.md` §5（V2 那节）有一句话："只要有任何一个静态直调调用点引用它，就必须
额外处理那个调用点（V1 的机制），且做不到'改一处、全局生效'。" —— 这句话字面上暗示：
静态直调链条上的每一跳都躲不开 V1（物理改写调用指令）。

但 `SPEC.md` §5 的"关键更正"说的是另一件事："**重定向不靠改机器码**：靠新程序自身的
入口表与调度结构……直调链失效向上蔓延，形成有界的传递闭包……改一个函数→直调它的、
内联它的调用者的机器码不再字节等价→它们也转解释→继续向上，直到遇到可重定向的边界
（虚调用点）为止。"

这两处表述在"V1 是否是运行时真正必需的机制"这一点上有张力，本文档之前（评审这次会话）
没有把它们调和清楚。这个用例就是专门设计出来，用实测而不是推演，回答这个问题：

**一条纯静态直调的多跳链（A 直调 B、B 直调 C，中间没有任何虚调用/闭包边界），改动 C，
能不能只靠"把 A/B/C 整体标记为转解释 + 在链路最外层做一次数据字段重定向"就正确生效，
完全不碰任何一条既有调用指令？**

（背景：这个问题最初是从"Mac 反馈 Gate1 V1 在 iOS 上走不通"这次对话延伸出来的——如果
V1 真的是每条静态直调链都躲不开的必需机制，"V1 在 iOS 不通"就意味着整个混合执行架构
在 iOS 上可能有严重的健全性缺口；如果 V1 从来不是必需的，"V1 不通"就只是印证了一个从
设计上就该绕开的错误路径。这个用例在桌面 x64 上独立验证这件事，不需要等 iOS。Mac 那边
用同样的思路（多跳直调链、只用 V2 + 传递闭包）在 iOS 上也已经得出"V1 非必需"的结论——
本用例是这个结论的独立交叉验证。）

## 设计

```
callViaClosure() --闭包调用--> entryVar() --静态直调--> stepA() --静态直调--> stepB() --静态直调--> stepC()
```

只有 `entryVar` 这一个闭包字段会被改写（V2 机制）。`stepA`/`stepB`/`stepC`/
`callViaClosure` 四个函数的编译字节，从构建到运行结束，**一次都不会被读写**。

激活补丁：
1. 用 `loadDynamicModuleClosure` 加载一份新编译的字节码模块（`patch/module.dart`），
   里面重新实现了**整条链**（`stepA_new`→`stepB_new`→`stepC_new`，不只是改 C）——
   这正是传递闭包的字面含义：C 变了，直调它的 B、直调 B 的 A 也要跟着转解释。
2. 用 `redirectClosureEntryPoint(entryVar, patchTrampoline)` 把 `entryVar` 自己的
   `entry_point` 字段指向一个 AOT 蹦床函数 `patchTrampoline`（内部调
   `invokeDynamicModuleClosure` 进解释器）——**一次堆数据写，不做 mprotect，不扫描
   任何指令字节**。

## 踩坑：第一版测试用例被 AOT 特化吃掉了，V2 的 NOTES.md 早就警告过这个坑

第一版里 `entryVar = stepA;` 是**恒定赋值**——编译器能证明 `entryVar` 只可能持有
`stepA`，于是把 `callViaClosure()` 里的 `entryVar()` 直接**去虚化成普通直调**，完全
绕过了闭包对象的 `entry_point` 字段。实测现象：`redirectClosureEntryPoint` 调用本身
不报错，但 `AFTER` 跟 `BEFORE` 完全一样——重定向确实写对了一个 Closure 对象的字段，
但已经没有任何调用点还经过它了（写了个没人用的字段）。

这正是 `v2_call_forms_matrix/NOTES.md` 里"测试用例设计的一个通用教训"点过的坑：
"验证'能不能重定向某种调用形态'之前，必须先确认测试用例本身没有被 AOT 编译器优化掉
这个形态本身。" 修法跟 V2 一样——加一个从未真正使用、只是让取值变成"运行时才能确定"
的候选值（`stepAAlt`），赋值改成 `args.contains('--alt') ? stepAAlt : stepA`，编译器
就没法把 `entryVar` 常量折叠掉了。

## 结果（PASS）

```
BEFORE: viaClosure: A(B(ORIGINAL-C))
  loaded interpreted patch chain as a closure
  redirected entryVar entry_point to patchTrampoline (data write only, no mprotect, no instruction bytes touched)
AFTER: viaClosure: A-new(B-new(PATCHED-C))
V6 PASS: multi-hop static-call chain (stepA->stepB->stepC) reached the patched C
via ONLY a closure entry_point redirect (V2 mechanism) -- zero code-page writes,
V1 never invoked
```

`AFTER` 显示整条链（A-new/B-new/PATCHED-C）全部换成了字节码版本，而这个过程里**唯一的
运行时改写操作是一次 Closure 字段写**——没有 `mprotect`，没有扫描/改写任何函数的调用
指令字节，`stepA`/`stepB`/`stepC` 自己的 AOT 编译产物从头到尾原封不动（只是不再被
任何活跃调用点引用而已）。

## 结论

- **V1 的物理改写机制，对这条多跳静态直调链而言，从头到尾都没有被用到，链路也正确
  生效**——这直接支持 `SPEC.md` §5"关键更正"的表述（"重定向不靠改机器码"），
  `GATE1_REPORT.md` §5 那句"任何静态直调调用点都需要V1的机制"的表述需要订正/澄清
  （不准确，或者至少容易引起误解）。
- 机制解释：一旦 A 被传递闭包纳入"转解释"集合，A 自己的旧机器码（包括它对 B 的静态
  直调指令）根本不会再被执行——因为够到 A 的唯一活跃路径只剩这一个闭包字段（其余
  仍是原生、未被闭包吸收的调用者，按定义不可能靠静态直调触达一个"转解释"函数，
  否则它自己也会被传递闭包吸收，矛盾）。一旦控制权进了解释器，解释器内部的调用
  （A_new→B_new→C_new）全部走解释器自己的符号化调用机制，不是硬编码的机器指令，
  天然不需要任何代码页写入。
- **跟 Mac 在 iOS 上独立得出的"V1 非必需"结论互相印证**——这次是在桌面 x64 上、
  用等价的测试设计复现的，两边使用不同环境得到一致结论，置信度更高。
- 这意味着：iOS 上"V1 不通"这个此前的最大悬念，**没有威胁到混合执行架构的健全性**——
  真正决定 iOS 是否可行的，只剩 V2 本身（dispatch table / closure entry_point 写、
  纯堆数据操作）在真机上是否真的不受 W^X 影响，这件事本来就该由 V2 自己的 iOS 复验
  来确认，不依赖 V1。

## 诚实边界

- 只测了"闭包边界"这一种虚调用形态（跟 V2 的 `closureVar` 一样）。虚调用/接口调用
  边界（dispatch table）理论上应该同理，但这个用例没有专门覆盖多跳链条 + 接口调用
  边界的组合，留作后续如果需要更多交叉验证再补。
- 只在桌面 x64 上验证；Android arm64 真机复现原计划要做，但当前环境 `adb` 不可用
  （设备未连接/工具未装），留待设备就绪后补一遍——预期结果应该跟 V2 在 Android arm64
  上"零改动直接复现"一样（这次机制全程是纯数据操作，不涉及任何架构相关的指令编码）。
- 链条只有 3 跳（A→B→C）。更长的链条（比如 10+ 跳纯直调）原则上同一套论证应该仍然
  成立（传递闭包会继续往上吸收，直到虚调用边界），但没有专门测过更长的链条。
