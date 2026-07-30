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
| **R1 CanonicalName 对齐** | 从 Kernel `.dill` 取 库URI→类→成员 唯一路径对齐新旧版本函数；**实例级**（含 decl_line/column 区分同名闭包/重载） | S3、命门 | 替代源文件路径代理与无序多重集；混淆/文件移动/版本升级天然免疫（Kernel 名与 ELF 名解耦） |
| **R2 对象池精确比对** | 解析快照对象池，逐 slot 比对两版同一 canonical slot 的常量内容 | S1 | 修"改 String/double/const 只动池、指令不变"的整类漏判；注意别做成新漏报源 |
| **R3 调用边完备提取** | 边提取包含：目标**身份**（并入条件1）、二级/unchecked 入口按地址区间归属、尾调 jmp、以及**间接/虚调/闭包/tear-off/池介导**调用的显式边界契约 | S2、S4、S5、B1、B2 | 静态侧对每个不可静态解析的转移点，要么建保守边、要么产出"运行时必须重定向此点"的义务清单并逐条核验 |
| **R4 ICF/去重感知** | 从 Kernel 层做 ICF 感知对齐；被折叠函数不得丢 key；`removed`/折叠导致 key 消失时保守播种其调用方或硬失败 | S6、S7 | 修"被改函数折叠进 removed、从不播种、无告警"红线 |
| **R5 cid/dispatch/vtable 布局稳定化** | 消费 cid/dispatch table/vtable 元数据；类声明集合变化导致 slot 平移时，即便无函数字节变也须检测并处理（SPEC §4.3 cid 稳定化） | 批判#3 | 红线：字节没变但虚调用派发错乱，当前模型完全看不见 |
| **R6 多架构（IR/快照层，非文本）** | x86-64 + arm64（Android/iOS 真机目标）；在快照/IR 层做，不做 per-arch 文本解析 | A2 | arm64 是真实部署目标之一，spike 的所有 soundness 证据只在 x86-64 取得 |
| **R7 混淆/strip 兼容** | 对齐与比对不依赖 DWARF 文本名；能处理 strip 后的发布产物（从 Kernel + 快照结构，而非符号表） | A1、A3、C2、C3 | release 常 strip+混淆；spike 的 DWARF 真名方案是权宜 |
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
