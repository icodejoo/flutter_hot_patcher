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

## 后续补测（2026-07-31）：用 analyze_snapshot 直接查 cid 本身是否漂移

上面的探测只确证了"调用点指令"与 cid 无关；批判真正担心的是 **cid 分配/dispatch table 内容**
本身是否因新增类而漂移。这轮用 Dart SDK 自带的 `analyze_snapshot --out=xxx.json` 诊断工具
（`runtime/vm/analyze_snapshot_api_impl.cc`，release 模式 `gen_snapshot`/`analyze_snapshot`
配对能跑，product 模式不兼容会硬报错版本不匹配）直接读快照的 Class/Function/Code 对象结构。

**诚实边界先行**：`analyze_snapshot` 的 JSON 输出**不包含** DispatchTable 数组本身的内容
（`metadata.offsets.thread.dispatch_table_array` 只是 Thread 结构体里这个字段的**内存偏移量**，
不是数组内容）；`snapshot_data` 顶层也只有 4 个不透明地址，无解析。所以这条探测**验证的是 cid
分配是否稳定，不是 dispatch table 数组内容本身**——这是当前可获得证据的上限，如实标注。

**探测数据**（同一组 base/patch，Extra 插入在 Sq/Tri/Circ **之前**）：

| 类 | base cid | patch cid | 是否相同 |
|---|---|---|---|
| Sq | 307 | 307 | ✅ |
| Tri | 306 | 306 | ✅ |
| Circ | 305 | 305 | ✅ |
| Shape | 308 | 309 | ❌（抽象基类，新增 Extra 插入其后重编号） |
| Extra | — | 308 | 新增，占了 Shape 原来的号 |

**结论**：对这个具体场景（三个已有的具体实现类 Sq/Tri/Circ，新增一个同接口的 Extra），**cid 分配
对既有三个具体类保持稳定**，只有抽象基类 Shape 的编号被新类"挤"了一位。同时 `Sq.area`/`Tri.area`/
`Circ.area` 的 Code 对象**size 逐字节不变、offset 整体平移**（因为 Extra 的代码插进了同一个
`.text` 段前面，是布局位移，非内容变化）——这与 diff_linker 早先"这三个函数字节不变"的结论一致，
是同一个事实的两个视角互相印证。

**未确证、仍需留白的部分**：
- 只测了一种插入模式（新增同接口叶子类，插在既有实现类之前）。cid 分配算法的具体规则未知
  （不是源码声明顺序——Extra 插在最前但没抢到最小 cid），**更复杂的场景（改接口继承链、
  改抽象基类插入位置、增删接口）是否会牵动既有类的 cid 仍未验证**，不能从这一个正例外推为
  "cid 总是稳定"的通用结论。
- 即使 cid 稳定，dispatch table 数组本身**每个 slot 存的目标地址**——这是本探测始终拿不到的
  数据（工具没暴露）——严格说仍是**未直接验证**，只是"cid 不变 + 该 cid 对应函数代码不变"这
  两件已确证的事实叠加后，间接支持"这个具体场景下 dispatch table 该 slot 的效果不变"，不是
  对 dispatch table 数组内容的直接读取比对。
- 若要拿到 dispatch table 数组本身的内容做逐 slot 比对，`analyze_snapshot` 这条路走不通，需要
  VM 源码级另辟蹊径（例如给 `analyze_snapshot` 加一个补丁导出 dispatch table 数组，或直接
  解析快照二进制里 `DispatchTable::Deserialize` 读取的原始字节段）——这是比本轮 spike 大得多
  的工程，仍按"iOS 门后再建"的既定顺序，留给 R1-R9 正式研发。

## 结论（诚实、有界）

- ✅ 确证：megamorphic 虚调用**调用点**字节与 cid/布局无关（对这一形态，批判担心的机制不成立）。
- ⚠️ 未确证：dispatch table **数据内容**本身是否漂移——需 VM 源码级探测，本轮未做，如实留白，
  已记入 `PRODUCTION_LINKER_SPEC.md` R5（cid/dispatch 稳定化）作为生产 linker 必须处理的项，
  **不因本次探测未完全证实而降低其在生产需求里的优先级**（批判的理论依据——SPEC §4.3——独立
  于本探测成立）。
- ✅ 收获：修复了 S4 自身的一个真实回归（次入口解析需要 high_pc 上界，不能无界就近猜测）。
- ✅ 收获：发现新增类型/接口触发的类型检查桩批量 churn，是一个未归一化的新噪音源（sound 但影响
  闭包大小），已记入本 NOTES 供后续参考。
