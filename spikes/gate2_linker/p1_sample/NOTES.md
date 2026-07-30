# P1 大样本全类型覆盖 —— 差分精确度实测

**目标**（用户）：把测试工程扩成全类型全场景大样本，每种构造都改到，测 ①功能覆盖率
②差分算法精确度。本目录是纯 Dart 那一半（Flutter widget 见 `../p2_widget/`）。

跑：`DART_SDK_SRC=/root/dart/sdk ./run_sample.sh`（`gen_sample.py` 生成 base/patch 树 +
manifest.json；建 AOT+DWARF 快照；`diff_linker` CanonicalName 保守模式；`measure.py`
对比闭包 vs manifest ground truth）。

## 样本设计（3125 函数，8 模块，跨模块同名压测）

- **8 个模块**（mod0..mod7），每个都含**同一套构造、同一套元素名**——`fnInt`/`MethodC.method`/
  `Pair.combine`/… 在每个模块重复。裸符号名下这制造 **294 处撞名**，正是 CanonicalName
  对齐的压测（裸名会把它们全部误判、误伤）。
- **全类型/全场景覆盖**（每种都改到一个实例）：基本类型 int/double/bool/String；引用类型
  List/Map/Set/record；类成员 method/getter/operator/static；mixin、enum、泛型 Pair<A,B>、
  闭包（改动落在匿名闭包体）、直接调用链（cascade）、多态虚调用边界（不应传播）。
- **补丁只改每种的一个实例**（各在不同模块，18 处改动），其余同名实例不变——精确度就看
  linker 会不会误伤那些同名未改的兄弟。
- `manifest.json` 记录元素 / **直接**调用边（虚调用边故意不记）/ 改动集；`measure.py` 从改动集
  沿直接边算不动点得期望闭包，与实测对比。

## 结果：PASS —— 闭包 == ground truth，完备且精确

| 指标 | 值 |
|---|---|
| 总函数 | 3125 |
| 跨模块撞名 key | 294（9.4%）——**全部因多重集相同判等价，0 被播种** |
| byte-changed（条件1） | **18 = 全部 18 种改动构造，逐个直接检出** |
| 闭包（must reinterpret） | **29 = ground truth**（18 改动 + 链 cascade + 各模块 moduleChecksum + main） |
| MISSES（漏判，须 0） | **0**（完备/sound：每处改动都进闭包） |
| FALSE POSITIVES（误报） | **0**（精确：同名未改兄弟无一误伤） |
| SDK/库函数被误标 | **0** |

- **功能覆盖率**：18 种构造改动**全部被检出**（含匿名闭包体改动、enum/mixin/泛型/operator/
  getter；虚调用边界正确**不**把 `callVirt` 拖进闭包——多态调用间接、无直接边）。
- **精确度**：对比裸名对齐（294 撞名会滚成大闭包），CanonicalName + 多重集精化把闭包收敛到
  **恰好 ground truth**，误报/漏判均为 0。这量化坐实了"命门是对齐精度"：对齐做对，精确度 100%。

## 关键工程发现：AOT 相同代码折叠（ICF）

搭样本时踩到并解决的真问题（写下来供正式研发）：Dart AOT 把**整数常量放对象池**，因此
仅差常量的同构函数（`int f(int x)=>x+K`）**指令字节完全相同**，被 **identical-code folding
(ICF)** 合并成一个代码块；且 **DWARF 不为被合并函数列出子程序名**（实测 base 里 0 个
`MethodC.method` 子程序）。后果：后验 DWARF keying 无法把一个共享块拆回多个 canonical key
→ 被合并函数丢 key → 表现为改动函数变"added"、真改动被漏。

- **规避（本 spike）**：让每个 (模块,构造) 的 body 有**结构性**差异（`W()` 变长嵌套运算链真正
  作用于 x；fnList 用**随模块变化的列表长度**），使指令序列唯一、ICF 不合并。纯常量 salt
  无效（进池后指令仍相同）。
- **对正式 linker 的意义**：真 linker 应在 **Kernel/CanonicalName 层**（codegen 之前）对齐，
  那里每个函数天然独立、无 ICF 歧义——这正是 SPEC §4.1 把 CanonicalName 对齐列为命门的原因，
  也说明"后验 ELF/DWARF 差分"是 spike 权宜、非最终形态。ICF 本身真 linker 也须显式处理
  （一个代码块 ↔ 多个函数）。

## spike 边界

- 静态精确度测量（objdump + DWARF + 不动点），未运行时实跑闭包；行为等价性由"patch 快照=
  完整重编译参照 + 非闭包函数逐字节等价"论证（同 V6-V9）。base=7531 / patch=7629 输出不同，
  确认改动可观测。
- 沿用 `diff_linker` 的 normalize() 对象池 slot 通配近似（tools/NOTES）：若某改动**只**体现为
  池常量值变化，会被通配漏掉。本样本用 W() 让改动同时改变非池指令而规避；真 linker 需精确
  slot→常量映射。
- async 构造未纳入（其状态机降级会拆成多符号，留作单独用例）。
