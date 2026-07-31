# 生产 linker 需求规格（B 计划）

本文把 spike 阶段 `diff_linker.py` 评审（`REVIEW_diff_linker.md`）暴露的硬缺口，转成**正式研发
阶段生产 linker 的设计需求**，并给出**排序与投入估计**。写这份文档的目的：确保这些缺口不是
"以后再说"的黑洞，而是**已排期、有细节的生产需求**。

spike 工具会继续保留其价值——它的**测量 harness + ground-truth 语料**（v6-v8 / p1 / p2 / p3b）
正是用来验证生产 linker 的回归台。

---

## 0. 地基决策（为什么不是在 spike 上补，而是重起）

`diff_linker.py` 事后解析 `objdump`/`readelf` **文本**。评审与全项目结论一致：正确地基是
**在 Kernel / 快照结构层做对齐与比对**（codegen 之前 / 直接读快照对象），而非事后 ELF 文本 diff。
凡涉及"池内容、跨架构、cid/dispatch 元数据"的缺口，在文本 diff 范式里要么做成扔掉的脚手架、
要么根本拿不到数据。故生产 linker **另起**，以本规格为准，spike 只做回归语料源。

## 1. 需求清单（每条对应 REVIEW 的一个/一组缺口）

| # | 需求 | 对应 REVIEW | 说明 |
|---|---|---|---|
| **R1 CanonicalName 对齐** | 从 Kernel `.dill` 取 库URI→类→成员 唯一路径对齐新旧版本函数；**实例级**（含 decl_line/column 区分同名闭包/重载） | S3、命门 | 替代源文件路径代理与无序多重集；混淆/文件移动/版本升级天然免疫（Kernel 名与 ELF 名解耦）。**spike 级探索已证伪一条捷径**（`r2_pool_probe/NOTES.md`）：`gen_snapshot --disassemble` 的函数名仍是 `file:///...` 绝对路径，跟 DWARF 方案同源，不会白给库 URI。**2026-07-31 已跑通并正面验证**（`r1_kernel_dill_probe/NOTES.md`）：`package:kernel` 的 `loadComponentFromBinary`（SDK 自带、现成公开 API，不必自己写二进制格式解析器）读出的 `Library.importUri` 对 `lib/` 下被 `package:` 引用的库文件是真正的 `package:xxx/yyy.dart`，**跨越完全不同的构建目录逐字节稳定**（实测：整个包目录搬到另一绝对路径重新编译，CanonicalName 不变），直接解决 COVERAGE_GAPS #19 part-file-moved 残留问题。诚实边界：入口脚本本身仍是 file:// URI；`fileOffset` 需换算才等价于 decl_line/column；接入 diff_linker 仍是独立的、更大的工程（这轮只验证 CanonicalName 来源） |
| **R2 对象池精确比对** | 解析快照对象池，逐 slot 比对两版同一 canonical slot 的常量内容 | S1 | 修"改 String/double/const 只动池、指令不变"的整类漏判；注意别做成新漏报源。**spike 级探索已验证可行机制**（`r2_pool_probe/NOTES.md`）：非 product `gen_snapshot --disassemble --code_comments` 会吐出独立的 `ObjectPool len:N` 完整列表，含每个 slot 的原始内容（数值常量给 IEEE754 位模式）；实测 `const fee=0.07→0.08` 场景——调用指令逐字节不变（复现 S1 漏判)，但各自 build 自己的池列表在同一 slot 显示 1.07→1.08，解码正确。**不必逆向对象池二进制布局**，复用 VM 自带诊断输出即可 |
| **R3 调用边完备提取** | 边提取包含：目标**身份**（并入条件1）、二级/unchecked 入口按地址区间归属、尾调 jmp、以及**间接/虚调/闭包/tear-off/池介导**调用的显式边界契约 | S2、S4、S5、B1、B2 | 静态侧对每个不可静态解析的转移点，要么建保守边、要么产出"运行时必须重定向此点"的义务清单并逐条核验。**spike 级审计**（`r3_boundary_contract/NOTES.md`，2026-07-31）：diff_linker 故意不为虚调用/闭包调用建传播边，这是**对的**——Gate1 V2 实测虚调用/静态直调都是"单点控制"（改一处、全类/全调用点统一生效），不需要标记调用方。真正缺口不在 diff_linker 静态模型，见下方新增 R3.1 |
| **R3.1 闭包重定向完备性（新识别，2026-07-31）** | 补丁应用引擎须证明"给定一个被改动的函数，能枚举所有引用它的活跃闭包实例"（堆遍历）；做不到完备枚举则该函数一旦被 tear-off 过就必须整体退化到更重的重定向机制 | COVERAGE_GAPS #2 残留备注 | 红线：闭包重定向（Gate1 V2）是**每实例**粒度，不是虚调用那种"改一处全生效"的单点控制——V2 只测了重定向一个已知闭包变量，从未测试"如何找到所有实例"。漏掉的实例**静默保留旧代码**，无任何错误信号，比崩溃更危险。**spike 级已验证核心机制可行**（`r3_closure_enum_probe/NOTES.md`，2026-07-31）：新增 `Internal_countClosuresForFunction` 原生入口，用 `HeapIterationScope`/`ObjectVisitor`（非 `ObjectGraph`——后者被 `DART_ENABLE_HEAP_SNAPSHOT_WRITER` 排除出 `PRODUCT` 构建，生产运行时不存在）遍历堆，实测 5 个不同 receiver 的实例方法 tear-off + 1 个后补的都被完整精确计数。**枚举本身不是无解问题**；剩余是工程细节——边遍历边写入 entry_point（未测）、多 isolate（`HeapIterationScope` 只遍历当前 isolate 堆，未测跨 isolate 场景）、大堆性能（未测） |
| **R4 ICF/去重感知** | 从 Kernel 层做 ICF 感知对齐；被折叠函数不得丢 key；`removed`/折叠导致 key 消失时保守播种其调用方或硬失败 | S6、S7 | 修"被改函数折叠进 removed、从不播种、无告警"红线 |
| **R5 cid/dispatch/vtable 布局稳定化** | 消费 cid/dispatch table/vtable 元数据；类声明集合变化导致 slot 平移时，即便无函数字节变也须检测并处理（SPEC §4.3 cid 稳定化） | 批判#3 | 红线：字节没变但虚调用派发错乱，当前模型完全看不见。**spike 级补测**（`p3c_cid_dispatch/NOTES.md`，2026-07-31）：用 `analyze_snapshot --out` 读快照 Class 对象，对"插入新叶子类"这一具体场景实测 cid 对既有类**保持稳定**；但工具**不暴露 dispatch table 数组本身内容**（只给 cid 分配和 Code 布局），仍是间接证据非直接验证，且只测了一种插入模式——不能外推为"cid 总是稳定"。真正的 slot 内容比对仍需 VM 源码级方法，红线优先级不降 |
| **R6 多架构（IR/快照层，非文本）** | x86-64 + arm64（Android/iOS 真机目标）；在快照/IR 层做，不做 per-arch 文本解析 | A2 | **spike 级已验证 Android arm64**（`ARM64_PORT_NOTES.md`）：`ARCH_CONFIG` 参数化 + `readelf -h` 自动探测架构，P1 大样本(3124函数)在真实 arm64 反汇编上 closure==ground truth、漏判0/误报0，与 x86-64 结果一致。**iOS arm64 未验证**（Mach-O 非 ELF，objdump/readelf 工具链不适用，待 Mac 后独立移植）。生产阶段仍应在快照/IR 层做，此 spike 验证证明"跨架构不是无解问题"，不代表文本解析方案可直接用于生产 |
| **R7 混淆/strip 兼容** | 对齐与比对不依赖 DWARF 文本名；能处理 strip 后的发布产物（从 Kernel + 快照结构，而非符号表） | A1、A3、C2、C3 | release 常 strip+混淆；spike 的 DWARF 真名方案是权宜。**spike 级补测**（`r7_obfuscation_crossbuild/NOTES.md`，2026-07-31）：源码级确认 VM 混淆改名（`Obfuscator::NextName`）是**纯遍历序号计数器，无随机种子**；源码不变时两次独立 `--obfuscate` 构建改名表逐字节相同（探针实测）。结合既有 P1 混淆测试（不同源码、独立构建）closure==ground truth，残留缝隙收窄到"裸名兜底路径"（DWARF 未覆盖的 VM 桩），且失效方向已知安全（过报不漏报）。根治仍需 R1（Kernel 层不依赖 ELF/DWARF 文本名） |
| **R8 绝不静默** | 任何解析退化/格式失配/引擎版本不一致/对齐命中率异常，一律**硬失败或显式告警**，绝不静默输出"好看的 0" | A1、A3、C5、B3 | spike 已加守卫（见下），生产必须制度化 |
| **R9 规模** | 反向边索引 + worklist，线性传播；支撑数万函数真实 app | D4 | spike 的 O(轮×指令) 纯 Python 不可用于真实规模 |

## 2. spike 已就地修复的"诚实批"（不进生产需求，已在 diff_linker.py 落地）

以下为便宜、且保护 spike 工具自身可信度的修复，已改并全语料回归通过（v6-v8/p1/p2/p3b 无回归）：
- **S2**：`sig()` 并入已解析的 call target 身份（同名重定向不再漏）。
- **S4**：call 目标按"最近 low_pc 区间"归属，二级入口 `<sym+0xNN>` 不再断 canonical 条件2边。
- **S5**：call 目标正则改贪婪 + 剥尾 `+0xNN`，`operator+`/`<anonymous closure>` 名不再被截断。
- **守卫（R8 的 spike 版）**：非 GNU objdump 空解析→硬失败；单边 `--*-debug`→硬失败；块数≪DWARF 数
  （疑似 strip）→告警；`removed` 非空→告警（S6）；multiset 清除撞名→告警（S3）。
- **文档/标签**：docstring 同步多重集策略与"归一化文本非逐字节"；`--optimistic` 标注为"下界、不可
  用于生成补丁"；`--list` 的 propagated 口径修正 + 单列 ambiguous-changed 段。

## 2.5 spike 级硬缺口探索（不投入正式研发、仅验证可行性，见 R1/R2 表格）

`r2_pool_probe/NOTES.md`：R2（对象池比对）验证**可行**、找到具体机制（复用 VM 诊断反汇编器，
非 product `gen_snapshot --disassemble --code_comments` 自带的 ObjectPool 文本列表）；R1
（Kernel CanonicalName）证伪了一条设想的捷径（disassemble 输出不会白给库 URI），确认仍需
Kernel `.dill` 解析这块独立工程。均未接入 diff_linker 或投入正式建设——遵循"iOS 门后再建"的
既定顺序，这轮只回答"硬缺口有没有可行路径"。

## 3. 排序与投入（对"上生产"负责的路径）

1. **前置 go/no-go：iOS 真机 W^X 复验（Gate1 阶段B）**——这是全项目**唯一还可能整体推翻方案**的门；
   机器码路线调研也确认 iOS W^X 是成败所在。生产 linker 是 1–2 人月级投入（对齐/稳定化是 Shorebird
   做了多年仍在迭代的最硬核心），**在 iOS 墙验证之前不应投入这笔工程**——否则墙不成立即打水漂。
2. **iOS 门通过后**：按本规格 R1–R9 在 Kernel 层正式开建生产 linker。
3. **验证**：以 spike 的 REVIEW 复现场景 + COVERAGE_GAPS 用例 + ground-truth 语料（v6-v8/p1/p2/p3b）
   作为生产 linker 的回归台；每个红线缺口配一个必过的回归用例。

## 4. 仍需补的 spike 级覆盖（喂给生产验证，见 COVERAGE_GAPS）

Stream/生成器、捕获局部变量的闭包、FFI Struct 布局变更、签名变更、增删符号、模式匹配、
part/part-of 多文件同库、cid/dispatch 布局漂移（批判#3，红线，最优先补一个复现用例）。

---

**一句话**：硬缺口不是"留到以后"，是**已作为 R1–R9 排进生产 linker 需求**；只是**做的地方**是 Kernel 层
新工程、**做的时机**排在 iOS W^X go/no-go 之后——这样每分工程都花在不会被扔、不会被 iOS 墙推翻的地方。
