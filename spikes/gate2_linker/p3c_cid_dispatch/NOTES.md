# cid/dispatch 布局漂移探测（评审批判#3）—— 有界探测的诚实结果

**目标**：评审的完备性批判 #3 指出 diff_linker 对**类 cid 分配 / dispatch table 布局**零建模，
理论上补丁可能"字节没变但虚调用派发行为变"——试图复现这个红线盲区。

跑：`patch.dart` 在已有三个 `Shape` 实现类（`Sq`/`Tri`/`Circ`，通过 `List<Shape>` megamorphic
调用、非去虚化）**之前**插入一个新实现类 `Extra`（保留但不在执行路径上），源码上 Sq/Tri/Circ/
`useShapes` 逐字节不变。

## 确证的部分：虚调用点本身是"位置/cid 无关"的

反汇编 `useShapes` 里的虚调用点：

```
mov  -0x1(%rdi),%ecx      ; 从对象头取 cid（运行时读取，非编译期立即数）
shr  $0xc,%ecx
mov  0x68(%r14),%rax      ; dispatch table 基址，从 THR 固定偏移取
call *(%rax,%rcx,8)       ; 间接调用，cid 全程运行时计算
```

cid **在运行时从对象头读取**、dispatch table 指针**从 THR 固定偏移取**——调用点指令本身
**不编码任何 cid/布局信息**。实测（diff_linker 自身的 `sig()`）：加入 `Extra` 后，
`useShapes`/`Sq.area`/`Tri.area`/`Circ.area` 归一化后**逐字节相同**。→ 对**这一种**虚调用
形态（megamorphic、经 dispatch table），调用点字节确实与 cid 布局无关，批判担心的"字节不变
但派发变"**在调用点这一侧不成立**。

## 未确证、诚实标注为悬而未决的部分

批判真正的担忧是 **dispatch table 的数据内容**（不是调用它的代码）——即 `DispatchTable[cid]`
这个 slot 存的目标地址，是否会因新增/重排类而对**既有类**指向不同内容。这是一个**二进制数据
结构问题**（快照的只读数据段，非 `.text`，`objdump -d` 不显示），要验证需要定位 VM 内部
dispatch table 的确切内存布局并逐 slot 比对两版内容——这超出了本轮的合理时间盒，**未完成**，
如实标注为待正式研发用 VM 源码级方法验证的悬念，而非编造一个通过/不通过的结论。

## 意外收获：揪出并修复了一个 S4 修复自身的回归

探测过程中发现 `useShapes` 一度被误报 byte-changed（闭包滚到 55%→64%）。根因**不是 cid/dispatch
问题，是我们自己刚做的 S4 修复的一个缺陷**：`resolve()` 对调用目标地址做"就近取最大 low_pc"时
**没有上界**——如果目标地址落在**没有 DWARF 子程序覆盖的运行时 stub 区**（如
`new ConcurrentModificationError` 这类抛错桩），会被错误归属给"地址上恰好在它前面的某个无关
Dart 函数"，且这个错误归属**随代码布局漂移**（加 Extra 后 stub 区位置一变，归属跟着变）→
制造出跨版本的假 byte-changed，级联放大。

**已修复**：`dwarf_canonical_map` 现在同时记录每个函数的 `[low_pc, high_pc)` 区间（`high_pc`
在本机 GNU readelf 渲染下是绝对地址，已实测确认）；`resolve()` 只在目标**严格落在某函数自己的
区间内**时才归属为该函数的次入口，否则回退裸名（S4 修复前的行为），不再做无界"就近"猜测。
全语料回归（v6-v8/p1/p2/p3b）确认修复后无回归。

## 附带发现：新增类/接口触发 SDK 全局类型检查桩churn（新噪音源，方向 sound）

即使排除上述回归，加入 `Extra` 后仍能观察到大量 `assert type is X` 类型检查桩函数的
byte-changed（如 `assert type is Iterable<X0>`、`assert type is Completer<void>` 等）。这些是
泛型实例化产生的自动类型检查辅助符号，为整个 SDK 共享、随程序里类型集合变化而**批量重新生成/
编号**——不同于 V9 已归一化的"对象池 slot 漂移"，这是**没有被 normalize() 处理的新噪音类别**。
方向上是 **sound 的过报**（不会漏判，只会让闭包偏大），但说明"改动引入新的类型/接口"这类补丁
在当前 spike 工具下会产生比"改函数体常量"大得多的噪音闭包——这与 V9/V10 的核心发现一致
（对齐/稳定化精度决定闭包大小），只是又指认了一个具体噪音源。**未归一化，留作已知局限。**

## 结论（诚实、有界）

- ✅ 确证：megamorphic 虚调用**调用点**字节与 cid/布局无关（对这一形态，批判担心的机制不成立）。
- ⚠️ 未确证：dispatch table **数据内容**本身是否漂移——需 VM 源码级探测，本轮未做，如实留白，
  已记入 `PRODUCTION_LINKER_SPEC.md` R5（cid/dispatch 稳定化）作为生产 linker 必须处理的项，
  **不因本次探测未完全证实而降低其在生产需求里的优先级**（批判的理论依据——SPEC §4.3——独立
  于本探测成立）。
- ✅ 收获：修复了 S4 自身的一个真实回归（次入口解析需要 high_pc 上界，不能无界就近猜测）。
- ✅ 收获：发现新增类型/接口触发的类型检查桩批量 churn，是一个未归一化的新噪音源（sound 但影响
  闭包大小），已记入本 NOTES 供后续参考。
