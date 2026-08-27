# 🤖 SDK 复刻自动化状态机

> **⚠️ 核心协议**：当你（Claude）清空上下文并重新读取此文件时，你必须保持 /loop 状态。
> 不要为了确认「下一步做什么」而停下——那答案在【当前核心任务】里。直接读它，
> 立即执行【开发->验证->文档->提交】闭环。
> **唯一例外见下面第 5 条：`git push` 与其他外向、不可逆的操作必须停下来问。**

---

## 🔒 每轮不可违反的约束

> **权威副本在 `docs/LOOP_CONTRACT.md`** —— 运行契约正文 + 全部实测依据都在那里。
> **每轮开始读那一份**，不要依赖本文件里的任何摘要。
> 两份并存必然漂移，这个坑在 `CLAUDE.md` 规则 0 上已经栽过一次
> （v1 树与 route-a-research 树各一份，后者整个规则 0 章节都不存在）。

一句话版，**不能替代读契约**：

> **你是调度器，不是执行者。** 每轮只做「读 memo.md → 派 subagent 干活 →
> 记录结论 → 结束本轮」四步，绝不在主循环里直接跑构建/测试/大范围搜索或读大文件。
> 崩溃的真因是主上下文线性累积（实测每 500 条消息涨 15–18 万 token，
> 峰值 973,940 撑爆），**把工作丢进子上下文是唯一能改变增长斜率的办法**。

---

## 📋 当前核心任务

> 任务 1-6 已全部完成（见下方任务卡）。以下是 **2026-08-25 重新符号实测**后的新清单。

- [x] 任务 7：`field_hasher.cc` ✅ `ecd1e5b5b20`。**最后一个「一侧为 0」的私有子系统已关闭**
- [x] 任务 8：改写路径的生产覆盖 ✅ `041fe7f24a3` + spike `c958c6f`。
      **第一次跑就是 bus error**（代码页写保护）→ 真实 bug 已修；
      常设检查 `op_rewrite_check.sh` 已进 `verify_all`（现 8 项）
- [~] 任务 9：`GetBestMapping` 的不可破平票 —— **已测出分歧，转入挂起池**
      `ead5f153d8d` + spike `3277b35`。他们 `14/8/0/120`、我们 `14/13/0/115`
- [x] 任务 10：`IndirectStaticCall` 68 vs 64 → **不是缺口，已结案**（本轮实测）
      去重方法名集合 diff：他们 19、我们 20，**「只在他们那边」为空**。
      多出的 `IndirectStaticCallInstr::FromCall` 是我们的外联工厂，被 DD IL pass 真实调用
      （`aot_call_specializer.cc:1222`）；他们没有该符号是因为**他们那个 IL pass 完全内联**。
      且 `FromCall` 是**上游本家族的惯用法**（`StaticCallInstr`/`PolymorphicInstanceCallInstr`/
      `DispatchTableCallInstr` 都有同名工厂）→ 不是发明。**原始 `nm` 行数差 = strip 差异，已确认。**
- [~] 任务 11：**中断** —— 造 fixture 时撞上一个我自己引入的回归（见下），优先修它
- [x] 任务 12：修 `dd_runtime_check` 的假绿 + 回退补齐 ✅ `0dfe634b44e` + spike `115249c`
- [x] 任务 13：**让补齐能与反向定长解析共存** ✅ `d99ff81f8e7` + spike `d21d04d`
      **修法就在猜的地方**：`SkipBackOverObjectPoolLoadPadding` 加在三个解码入口，
      **八个调用点一个都不用动**。`op_rewrite_check` 不再 BLOCKED，编辑器重新活了。
      详见下方任务卡。
- [x] 任务 14：**造一对真正不同的 base/patch，让映射不再是恒等** ✅ spike `e9223a4`
      `g_insert.dart` + `op_real_mapping_check.sh`（`verify_all` 现 **9 项**）。
      2321 个池访问、分布距离 592、四个阶段计数与他们逐行相同（backfill **19** 不是 16）。
      ⚠️ **但它不取代 `op_aggregator_check`**，这是实测出来的，详见下方任务卡。
- [x] 任务 15：**给被改写的站点一个逐字节判据** ✅ `8c9ae52a50d` + spike `a505c58`
      改写后用解码器把新字节读回来，要求读出的索引 == 瞄准的索引。
      🔴 **实测证明这个缺口是真的**：把发射器瞄偏一格，
      **原有两个判据全绿**（阶段计数仍与他们逐行相同、分布距离仍非零），
      655 个站点全错而无人发现。详见下方任务卡。
- [x] 任务 16：**语义判据已找到，且比预想的强** ✅ spike `463ba49`
      装载路线与「直接比两侧池内容」都被**快照版本 hash 墙**挡死（双向实测），
      但映射可以**从代码里反推出来**：`op_real_mapping_check` 现在有第三个判据——
      **我们实际应用的映射与他们的逐条相同（1123 条，零分歧）**。详见下方任务卡。
- [~] 任务 17：**`analyze_snapshot` 的 flag 面** —— 能做的那部分做完了，其余**依赖缺失**
      ✅ `fbcefad7224` + spike `f989967`：`--shorebird` 补进 help（与他们逐字节相同），
      新增 `analyze_snapshot_help_check.sh`（`verify_all` 现 **10 项**），
      把「还差几个 flag」变成**每轮实测的数字**：7 documented / 14 lines withheld。
      ⚠️ **另外六个不是懒得做，是缺子系统**（本轮查证）：
      `--dump_object_pool_link_data` / `--no_pp_hash` 需要 **`op_subgraph_hash`**
      （私有子系统，我们没有；`ObjectPoolLinkInfo::WriteToStream` **已实现且逐字节验证过**
      → **缺的是生产方不是格式**）；`--dump_blobs` 需要四个 region 的**长度**，
      而 `Dart_SnapshotAnalyzerInformation` 结构里根本没带。
- [~] 任务 18：**`SubgraphHasher` 侦察 + `--no_pp_hash` 关闭** ✅ `7ca20d214ea` + spike `63a658c`
      🔴 **符号表那条「两边都 0 = 口径陷阱」是错的，已订正**：`SubgraphHasher` 在
      **`analyze_snapshot`** 里（`dart::snapshot_analyzer::`），我们只量过 `gen_snapshot`。
      换个二进制量：**他们有、我们 0**，是真实缺口。
      ✅ **顺手关掉一个 flag**：`--no_pp_hash` 是**他们自己也不接受的死 flag**
      （help 里有，parser 不收，落到 VM 被拒）→ 忠实复刻 = **写进 help 且不注册**。
      我们的行为**本来就和他们逐字节相同**，只差两行 help。缺口 6/14 → **5/12**。
- [~] 任务 19：**`SubgraphHasher` 侦察** —— 等价关系解出来了，**框架没有** ✅ spike `1a3ee52`
      `SUBGRAPH_HASHER_RECON.md` + `probe_subgraph_hash.py`（**本轮无代码改动，是纯侦察**）。
      **已确立**（对他们 1380 个函数逐个实测）：
      ① ~~`self_hash` **只取决于指令字节**（1378 个不同 blob，无一 blob 对应两个 hash）
      → 名字/索引/位置都不参与；~~
      🔴 **2026-08-26 任务 58 推翻了这一条**：序数表是 `SubgraphHasher` 的**成员**
      （`+0x100` 池、`+0x198` 字段表），**每一层 walk 都要查** ⇒ `self_hash` 可证**不是**
      「某个函数字节的函数」。原来的观测（1378 blob 无冲突）没错，**结论错了**——
      在他们那一次运行里序数恰好与字节共变，所以外部观测分辨不出来。
      **这正是「外部黑箱观测能立性质、不能立机制」的实例。**
      ② 它是**多对一**（1378 → 1170）所以做了归一化；
      ③ **被忽略的是「PP 相对加载的位移」和「跳转/调用目标」**
      （拿同 hash 不同字节的函数对直接读出来的，也正是 `--no_pp_hash` 描述所说）；
      ④ 只屏蔽这两样：1378 → **1185**，目标 1170，**还差 15 类**；
      再加 ldp/stp、`add xN,x27,#imm`、`b.cond`、`cbz`、`tbz`、`adr` **一类都没少**
      → 残差是**另一种机制**，最可能是寄存器偏移型池加载（偏移在 movz/movk 立即数里）；
      ⑤ 🔴 **摘要不是对字节缓冲区的平铺 SHA-1**：`sha1(raw)` 与 `sha1(归一化)`
      对 1380 个**全部为 0**（连归一化等于恒等的那些也不中）→ **字节外面还有框架**
      （长度/分块/种子），它在 `Hasher::Entry` + `Hasher::Hash()` 里。
      ✅ **方法上值得留的一条：比「划分」，不要比「摘要」。**
      框架未知 ⇒ 任何候选都算不出摘要；但「这两个函数 hash 相同」与框架无关，
      照样可观测。①-④ 全靠这个才够得到。
- [x] 任务 20：**SHA-1 的框架已解出** ✅ spike `848c903`（反汇编 `Hasher::Hash()`）
      ```
      self_hash = SHA1( 对每个 Entry: le32(e.first) ‖ le32(e.second) )
      ```
      **不是对指令字节做哈希**——这就是上一轮 `sha1(bytes)` 全 0 的原因。
      证据全来自反汇编：`vector<Entry>` 在 `this+0x18`，
      `count=(end-begin)>>3` → **`sizeof(Entry)==8`**；
      `ldp w25,w24,[x21,#-0x4]` 一次读两个 int32；
      每个字段**逐字节小端**喂入（`strb` / `lsr #8` / `#16` / `#24`）；
      每字节 index 加一，等于 `0x40` 就调 `sha1_transform` 并把位计数加 `0x200`。
      **标准 SHA-1、无自定义种子**：`0x100266a50` 处 32 字节 = 标准 IV + K0..K2，
      K3(`0xca62c1d6`) 由函数头的 `mov/movk` 给出（读常量时**做了对照**：
      先确认已知指令地址在同一 file-offset 映射下解码正确）。
      ⚠️ **ABI 陷阱复发并已记录**：`Hash()` 返回 `std::string` → **sret，`x1` 才是 `this`**，
      把 `x0` 当 `this` 会让整个函数的偏移全错。
      🔑 **它同时改写了上一轮的说法**：所谓「归一化」**从来不是字节掩码**——
      PP 位移与跳转目标不进摘要，是因为**没人把它们放进 `Entry`**，不是被掩掉了。
- [~] 任务 21：**entry 的 kind 名字全拿到了；编号没拿到（刻意不猜）** ✅ spike `5a1585f`
      他们自己的字符串表（`0x1002c9c14` 起连续）：
      `CodeName` / `RawInstructionBits` / `OffsetFromPayloadStart` /
      `ObjectPoolLoadIndex` / `DispatchTableCall` / `IndirectStaticCall` /
      `FieldTableLoadIndex` / `ExternalBranchTargetIndex` / `LocalBranch` / `Unknown`。
      → **摘要 = 每条指令一个「分类过的」entry**，第二个字段装的是
      **有意义的那部分（池索引 / 字段表索引 / 跳转目标），不是编码出来的位移** ——
      这正是前两轮从外部量到的「归一化」的机制。
      ✅ **`CodeName` 不进 `self_hash`（已证，不是假定）**：全库恰好只有两组
      「同字节不同名」的函数，两组都是 `self_hash` 相同、
      `subgraph_hash`/`op_subgraph_hash` 不同 → 名字在 subgraph 那两个里。
      ⚠️ **kind 编号刻意留空**：push 点上看到的常量是 1/2/4/6/7/8，
      但**「字符串表顺序 = 枚举顺序」被 `Hash()` 的 switch 证伪**
      （它的 `==7` 臂走的是 `Disassembler::Disassemble`，不是取名字）。
      **把看起来合理的表写进实现就是编造**，所以留空。
- [~] 任务 22：**kind 编号已解出（①完成）；entry 流未解（②未完）** ✅ spike `a360547`
      跟着 `Hash()` 在 `0x1001960ac` 的 switch 逐臂追到它加载的字符串：
      | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
      |---|---|---|---|---|---|---|---|---|
      | `CodeName` | `OffsetFromPayloadStart` | `ObjectPoolLoadIndex` | `DispatchTableCall` | `ExternalBranchTargetIndex` | `LocalBranch` | `FieldTableLoadIndex` | `RawInstructionBits` | `IndirectStaticCall` |
      🔴 **果然不是字符串表顺序** —— 上一轮如果按「看起来合理」的表写下去，**九个里错五个**。
      kind 7 是唯一不直接取名字的臂（先 `Disassembler::Disassemble` 再取名），已**直接查证**非靠排除法。
      ⚠️ **entry 流两个模型都实测 0/1380**：「每指令一个 `RawInstructionBits`」、
      以及「PP 加载换成 `ObjectPoolLoadIndex`」→ **流不是「每字一个 entry」**。
- [~] 任务 23：**entry 流已解到 253/1380** ✅ spike `2e4e01e`
      `AccumulateRecursive` 开头 `sub x27, x24, x0`（= `pc - payload_start`）
      再 `orr x24, x8, x27, lsl #32` → **Entry 就是一个 64 位寄存器：低半是 kind、高半是 value**，
      这**独立印证了 kind 编号**（kind 1 确实是 `OffsetFromPayloadStart`）。
      它把 entry push 进**三个** vector（`+0x40`/`+0x78`/`+0xb0`，间距 0x38 → 三个 `Hasher`），
      其中 **`+0xb0` 被 `depth==0` 门控** → 这就是 `self_hash` 只算函数自身、
      另两个累积整个 walk 的原因。
      **三条规则（每条都是「取当前模型最小的错例 → 暴力搜出唯一修法 → 全量复测」）**：
      | 模型 | 命中 |
      |---|---:|
      | 开头 `(1,0)` + 每指令 `(7, word)` | 77 |
      | + 跳转：本地 `(5, target)`、外部 `(4, 序号)` | 190 |
      | + PP 加载 `(2, 序号)`，并吃掉它的补齐 NOP | **253** |
      🔑 **value 是「函数内的序号」不是真实索引** —— 暴力搜 `_printClosure` 得到 `(2,0)`
      而它的池索引是 319。**这正是三轮前量到的跨快照稳定性的成因**
      （两个闭包加载不同池槽却同 `self_hash`，因为都是各自的第 0 个）。
      🔑 **PP 加载独占整个补齐 footprint** —— 没有任何单槽替换能修好 `_printClosure`，
      加载 + 两个 NOP 塌成**一个** entry。
      模型已存进 `probe_subgraph_hash.py`（不是写在文档里），下轮从 253 起步。
- [~] 任务 24：**entry 流 253 → 277/1380** ✅ spike `eb80c18`
      同一个循环：取最小错例 → 暴力搜修法 → 全量复测。
      | 新增规则 | 命中 |
      |---|---:|
      | 字段表：`ldr xN,[THR,#off]` + 经 `xN` 的访问 → `(6, 序号)`，**两条指令塌成一个 entry** | 258 |
      | 条件跳转也算跳转，且 `LocalBranch` 装的是**相对下一条指令的 delta** | **277** |
      🔑 **`LocalBranch` 的值是 `delta-1`**（暴力搜 `[Stub] Type Test Type: Object`
      对一个目标在字节 12 的 `b.eq` 返回 `(5,1)`）；绝对偏移和原始位移都只得 258。
      🔴 **上一轮模型里那条「绝对偏移」从来没被执行过** —— 在把条件跳转纳入之前，
      语料里几乎所有本地跳转都掉进 `RawInstructionBits`，所以那条规则**对错都是同一个分数**。
      ✅ **可复用教训：模型的总分在涨，不代表它每一条规则都被检验过。**
- [~] 任务 25：**entry 流 277 → 1070/1380**（本轮最大一跳）✅ spike `057b97f`
      🔑 **`LocalBranch` 的值是常数 1** —— 不是目标、不是位移、也不是序号。
      在 25 个「恰好一个本地跳转」的函数上分别解，**每一个答案都是 1**
      （包括一个 delta = -7 的向后跳转）。
      🔴 **这是这个模型里第二条「因为赢过对手所以看起来对」的错规则**：
      先是绝对偏移，然后是 `delta-1`（277 vs 两个对手各 258）。
      `delta-1` 只在 `delta==2` 时正确 —— 而那恰好是最常见的形状（跳过一条指令）。
      ✅ **教训不是「要测规则」（上一轮已加），而是：
      一个候选可以是所有已试候选里最好的，同时仍然是错的 ——
      候选之间互相打分永远发现不了这件事。**
      找到它的方法是：**在很多函数上分别解出那个值，然后看答案的分布**，
      而不是提出公式再打分。
      ✅ 随后按同法复核了三个序号规则（没有想当然）：
      pool / ext / field 都赢过各自的常数 0 与常数 1
      （1070 vs 777/614、535/254、1063/1012）→ 它们确实是序号。
      ✅ 五条规则也都做过扰动负控制：delta 分别 -277/-68/-141/-19/-5，**无死条款**。
- [~] 任务 26：**entry 流 1070 → 1082/1380** ✅ spike `ce5adbb`
      字段表还有**三指令形态**：`ldr xN,[THR,#off]` ; `add xM,xN,#imm` ; `ldar xD,[xM]`
      （位移在 `add` 里，且 `ldar`/`stlr` 也算访问）。
      🔴 **它第一次跑出「毫无变化」，我差点当成假设被证伪。**
      规则是对的，错的是我的 `add` 匹配掩码用了 `0x7f800000` —— **把 bit 31 掩掉了，
      于是永远匹配不上**。
      ✅ **与 CLAUDE.md 里 `ldr [xN,#0x48]` 那次假红同型：
      一个「不可能命中的判据」和一个「命中了但没发现东西的判据」，报告的字面结果一模一样。
      假设产出「恰好零变化」时，先确认匹配器真的能匹配，再去信这个结果。**
      ⚠️ 另测得：**剩下 310 个错例没有一个能靠「替换单个 entry」修好** → 剩下的全是多指令塌缩。
- [~] 任务 27：**entry 流 1082 → 1185/1380** ✅ spike `673bf7e`
      | 新增规则 | 命中 |
      |---|---:|
      | `DispatchTableCall`：三指令塌缩 `<算 cid>` ; `ldr xN,[x21,xM,lsl#3]` ; `blr xN`，值为**常数 1** | 1183 |
      | 大位移池访问（`add xN,PP,#imm{,lsl 12}` [; `add`] ; `ldr`/`ldp`）+ 直接 `ldp/stp` off PP | **1185** |
      ✅ **常数 1 是解出来的不是猜的**：在 20 个函数上分别解，20 个全给「塌 3 条、值 1」。
      （因为两轮前 `LocalBranch` 是常数、而别处的序号又都是真序号，所以这条必须单独验。）
      ✅ **大位移那条只值 +2，也去确认了它真的在触发**：全语料只有 **3 个**函数含
      `add xN,PP,#imm` → +2 就是它的全部。**「小收益」和「匹配器从不命中」从分数上看是一样的。**
      📊 **规则覆盖已量化**（发现死条款的最便宜手段）：
      `OffsetFromPayloadStart 1380 / ObjectPool 2294 / ExternalBranch 4997 /
      LocalBranch 9000 / DispatchTableCall 332 / FieldTable 245 / Raw 49402`
      🔴 **`IndirectStaticCall`(8) 至今一次都没被发出过** —— 它是最后一个没有规则的 kind。
- [~] 任务 28：**两个否定结果，分数没动**（1185/1380 不变）✅ spike `2d8be05`
      ① 🔴 **任务卡的前提是错的**：`IndirectStaticCall` 零发射**是正确的，不是缺规则**。
      它该有的形态（`ldr x16,[THR,#0x978]` → 索引加载 → `blr`）**在本语料里根本不存在**——
      实测被当作后续加载基址的 THR 偏移只有 `0x70`（203 次，字段表）
      和 `0x690/0x6b0/0x6b8/0x6c0`（共 8 次）。`base.so` 是**不带 DD pass** 构建的。
      **查证只花了一次查询。**
      ② 🔴 **`ObjectPoolLoadIndex` 的「序号」规则在一般情况下是错的。**
      在 14 个「恰好一处明确池引用」的函数上分别解——**每一个都是该函数的第一处池引用**，
      所以序号模型全预测 0，而真值是 `49,8,45,18,4,2,67,1,16,2,4,4,16,4`。
      **排除掉的**：不是池索引（索引 52 在两个函数里给 8 和 4）；
      不是槽内容（同一个 `_ImmutableList len:5` 给两个答案；三个单字节字符串给 16/16/45）；
      不是跨 kind 共享计数器（那会给 1，真值 16）。
      🔴 **这是本模型第三条「赢过所有对手却仍然是错的」规则**（前两条都是 `LocalBranch`）。
      **而它同时产出 1185 个精确命中 —— 从分数上看这就是「正确」的样子。**
      ✅ **写进结论：分数只是正确性的下界，永远不是它的证据。**
      → `ExternalBranchTargetIndex` 与 `FieldTableLoadIndex` 的序号是**同法验证的**，
      现在应一并视为**未经证明**。
- [~] 任务 29：**池值的形状解出来了：是「计数器 + 每函数不同的基数」** ✅ spike `5ee9e22`
      破局的实验是**在同一个函数里同时解两个池值**：
      ```
      _OneByteString._concatAll   refs=[24,25]   values=(8,9)
      _Uri._writeAuthority        refs=[804,167] values=(16,17)
      _GrowableList._shrink       refs=[42,47]   values=(1,2)
      Timer._createTimer          refs=[578,579] values=(0,51)
      StringBuffer.writeCharCode  refs=[52,52]   values=(16,16)
      ```
      → 连续的新引用拿连续的值；**同一索引复用会拿回同一个值**；
      但计数器**不从 0 开始**，基数随函数变（8/16/1/1/0/16）——
      这正是「朴素序号」对 1185 个函数对、对其余错的原因。
      🔑 **`Timer._createTimer` 的 `(0,51)` 是最锋利的一条**：同一个函数里第一处是 0、
      第二处是 51 → **在它自己的两条指令之间有 50 个值被消耗掉了**。
      函数自身的指令流做不到这件事 → 指向 `AccumulateRecursive` **在调用点就地递归**、
      且序号 map **跨整个 walk 共享**。
      ⚠️ **该假设未被证实，且有一条实测反对它**：若真跨 walk 共享，
      则「第一处池引用在 `bl` 之后」的函数都该有非零基数；实测 **503 个通过的函数里有 125 个**
      正是这个形状却基数为 0。相关性是真的（错例 107/187 vs 通过 125/503）但不是决定性的。
      ⚠️ **若计数器真跨 walk 共享，则 `self_hash` 就不是「只依赖函数字节」的函数** ——
      而那正是关于它的第一条结论。那条结论**只建立在两组同字节函数上（样本量 2）**。
      **两者必有一个要让步**，现在说出来比以后撞上便宜。
- [x] 任务 30：**判定完成 —— 跨 walk 共享「强支持，未证明」，并据此重新划定范围** ✅ spike `b1439cd`
      **支持**：`Timer._createTimer`（两处池引用要 0 和 51）——
      它第一处池引用**之前**那个调用的子树在任何深度下都含 **0** 个池引用
      （这是「第一处为 0」的必要条件，**是一次真正的证伪机会，假设活下来了**）；
      两处之间的调用子树在深度 ≥12 时含 **39** 个（想要 50）——
      我的 walk 只跟直接 `bl`、只认最简单的 `ldr [PP,#imm]`，**39 是低估不是矛盾**。
      **反对**：没有能判别的证据。那两组同字节函数**被调方不同**
      （`Allocate Object` vs `Allocate _X509CertificateImpl` 等），看着能一锤定音——
      **但四个 stub 的子树池引用数都是 0**，两个假设给出同一个哈希。
      → 上一轮标记的矛盾**不是被解决，是被消解**：样本量 2 本就回答不了这个问题；
      「`self_hash` 只依赖字节」应降级为「在一个几乎没有重复的语料里找不到反例」。
      🔴 **代价已写清**：剩下 195 个函数需要**模拟 walk**——完整的调用点识别
      （含经池的调用与 dispatch 调用）、`AccumulateRecursive` 的深度界、`CascadeLimiter`。
      **这是与逐指令模型完全不同、且大得多的一块工作。**
      **1185/1380 不是「凑整停下」，而是逐字节局部方法的真实终点。**
- [x] 任务 31：**`--dump_class_table` 已实现，且与他们逐字节相同** ✅ `734abc41d10` + spike `7e81769`
      `619 cids / 529 classes`，`cmp` 干净。**help 缺口 5 → 4。**
      ✅ **它小，是因为它是「接线」不是「新写」**：`GetClassTableLinkInfo` 早就在走活 isolate
      的类表并产出 `{id,name,hash}`，而我们的
      `--print_class_table_link_debug_info_to` **恰好就是他们 `--dump_class_table` 的 schema**；
      哈希也早就已知与他们一致（`print_class_table_link_info_to` 逐字节相同）。
      实际工作只是：给已有 JSON writer 加个 buffer 变体、加 API 入口、接 flag。
      ✅ **动手前先查了 `vm_sources.gni`**：`link_info.cc` 无 `DART_PRECOMPILED_RUNTIME` 门控，
      本来就在 analyze_snapshot 所属的 AOT 运行时里。**若不在，这就是完全另一个量级的改动。**
      🔑 **新增 `class_table_dump_check.sh`（`verify_all` 现 11 项）**：
      拿**我们对我们快照**的 dump 比**他们对他们快照**的 dump，要求逐字节相同 ——
      这在这里成立，是因为类表 dump **不含任何依赖布局的东西**；
      也是唯一可行的比法（两边 analyze_snapshot 互相读不了对方的快照）。
      ⚠️ **self-test 明确比检查本身弱，头注释已写明**：最自然的扰动（改用 `insert.dill`）
      **产出逐字节相同的 dump** —— 因为 `g_insert.dart` 只加函数不加类，
      **那是检查工作正常，不是扰动**。所以 self-test 改成损坏一个字节，
      它只证明「比较能发现差异」，不证明 dump 内容对。**这条检查靠正面结果立身。**
      负控制：发射 `cid+1` → 变红并引出差异条目。
- [~] 任务 32：**`--disassemble` 未实现（已回退），但挖出两个更重要的既有 bug**
      本轮**没有代码留下**——写的实现回退了，因为它撞上一个**先于我的改动就存在**的崩溃。
      ① 🎁 **契约已拿到**：`--disassemble` **只影响 `--shorebird` 那份 JSON**
      （对普通 `--out` 逐字节无差别），给每个函数加一个 `disassembly` 字符串数组，
      用 Dart 自己的反汇编文本格式（`r0`/`thr`/`tmp`，且**跳转是相对位移** `bl +100`）。
      → **相对位移意味着它与布局无关**，将来实现后**可以像类表那样逐字节对**。
      ② 🔴 **既有 bug A：`--disassemble` 会让我们的 `analyze_snapshot` 段错误。**
      原因是**名字冲突**：VM 自己就有 `disassemble` flag（`flag_list.h:30,37`），
      我们的 bin 不消费它，它就落到 `Dart_SetVMFlags` 打开 VM 的反汇编，然后崩。
      ⚠️ **我差点把这个记成「我的实现有 bug」**——回退后**在 HEAD 上重跑仍然 139**，
      才确认它先于我的改动存在。**回退不只是撤销，它也是一次判据。**
      ③ 🔴 **既有 bug B（更重要）：`--shorebird` 在我们自己的快照上产出 0 个函数。**
      10 次运行全部 exit 0、全部 175 字节、`functions: []`；他们同一模式在他们快照上是 **1380**。
      ⚠️ **`verify_all` 11 项全绿**——因为**没有任何一项检查跑过「我们的 analyze_snapshot
      在我们自己的快照上的 `--shorebird`」**。`verify_reproduction` 比的是 gen_snapshot 的产物。
      **这是检查矩阵的一个洞，不是运气。**
      ⚠️ 另外实测：我们的 `--shorebird` JSON 本来就是**简化占位**
      （三个哈希都填同一个值、多个数组恒空，源码注释写着 "simplified"）。
      CLAUDE.md 里「`analyze_snapshot --shorebird` B2/B4 已移植」**要按此订正**：
      它在树里，但**产不出东西**。
- [~] 任务 33：**0 函数已定位到确切原因；范围比预想的大**（本轮仍无代码留下）
      **不是遍历的问题——遍历是好的。** 插桩实测：
      ```
      PROBE discovered=1608 base=0x107763680
      PROBE zero=0 below=1608 kept=0 payload_range=[0x102cc1ec8,0x107762844]
      ```
      **1608 个 Code 全被 `payload < isolate_instr_base` 滤掉**，因为那个基址
      **高于所有 payload**（最大 `0x107762844`，基址 `0x107763680`）。
      四个区指针实测：
      `vm_data 0x1076e4340 / vm_instructions 0x107750000 /
      isolate_data 0x1076ecec0 / isolate_instructions 0x107763680`
      → `info.vm_isolate_instructions` **不是 ELF 快照里指令实际被映射到的地址**。
      🔴 **范围比任务卡预想的大**：**上游的默认模式（不带 `--shorebird`）在同一个
      快照上直接 abort（exit 134）**。所以坏的不只是 shorebird 那条路，
      **是我们的 `analyze_snapshot` 处理「我们自己的 AOT ELF 快照」这件事整体坏掉**。
      ✅ **`--dump_class_table` 正常**（619/529 与他们逐字节相同）——
      因为它只碰类表、不碰任何代码 payload。这也解释了为什么它昨天能一次做对。
- [~] 任务 34：**上游默认模式的崩溃已修好并加了回归检查；`--shorebird` 的 0 函数仍在**
      ✅ `a86e852f487` + spike `cd15195`。
      **崩在 `analyze_snapshot_api_impl.cc:355` 的 `UNREACHABLE()`**（上游代码，注释写着
      "Expected to handle all possibilities"）。插桩测出：**4 个 Code，各 8 字节、owner 为空、
      既不在 `VM_STUB_CODE_LIST` 也不是 isolate-specific 副本**。
      现在给它们 Dart 自己的名字 `code.Name()`（= `[unknown stub]`）：
      工具从 abort 变成 **exit 0、dump 出 1776 个 Code**。
      ⚠️ **代码里标明这是兜底不是诊断**：为什么我们的快照有这 4 个而他们的看不到，仍未解释
      —— 他们 dump 里每个 8 字节 Code 都有 owner，所以**他们那条分支根本走不到**，
      也就意味着**他们会打什么名字不可观测**，这个名字是我们的。
      ✅ **我们自己的 Shorebird stub 不是原因，这条查过了**（它们是最可疑的对象）：
      `ResumeOnCPU`/`RunDartOnCPU`/`CallSimulatorFromFfiTrampoline` 等**全在
      `VM_STUB_CODE_LIST` 里**，会经 `StubCode::ForEachStub` 正常命名。
      ✅ **检查矩阵的洞已就地补上**：`class_table_dump_check.sh` 本来就会造一个自己的快照，
      现在顺手用默认模式 dump 一遍，非零退出或空输出即失败。
      负控制：stash 掉修复重建 → 变红并打印 `exit 134`。
      🔴 **`--shorebird` 仍是 0 函数**（任务 33 的基址 bug，本轮未动）。
- [~] 任务 35：**诊断完成，且推翻了「基址错了」这个前提**（本轮无代码，是纯诊断）
      ① **免费判别器给了明确答案**：默认模式 1776 个 Code 的 `offset`
      **全部为负**（min `-78157752`，max `0`）→ **两条路都错**，不是只有 `--shorebird`。
      ② 🔴 **但接着测出「基址错了」是错的**：
      `instructions_tables` 只有 1 张表，它的 `start_pc` = `0x1046f7680`
      **恰好等于 `info.vm_isolate_instructions`**。**基址一直是对的。**
      ③ **真正的原因**：payload 全在这个 image **之下**（最大值离基址仅 3.6KB，
      最小值在 74MB 之外）→ **被发现的 1608 个 Code 全是 VM/stub 的，
      一个 app 函数都没有**。
      🔑 **因为在 bare-instructions 的 AOT 里，app 函数根本没有独立的 `Code` 对象**——
      它们只存在于 `InstructionsTable`（pc→offset）。
      → **`CollectAllCodes`「遍历堆找 Code」这个做法从根上就不对**，
      不管基址怎么修都不会有 app 函数。
      ✅ 这与 CLAUDE.md 早就记下的一致：`--shorebird` 的 `functions` 数组
      对应**序列化器的 code 表**、`index_in_entries` 0..1379（**1380 条**）。
- [x] 任务 36：**`--shorebird` 修好了：0 → 1589 个函数** ✅ `86dbf623588` + spike `f8c480e`
      **第一条 entry 是 `offset 128 / size 44`，与他们同程序的 dump 逐字相同。**
      改的是**枚举方式**不是基址（任务 35 已证明基址一直是对的）：
      bare-instructions AOT 下 app 函数没有独立 `Code` 对象，
      所以「遍历堆找 Code」只能找到 VM/stub 代码。现在枚举
      `InstructionsTable` 里 `first_entry_with_code` 之后的条目。
      ⚠️ **同一个类里有两套索引约定，踩了才知道**：
      `EntryPointAt` 收**绝对**条目索引，`InstructionsLengthAt` 收**相对**索引并自己加上偏移。
      而看起来最顺手的 `PayloadStartAt` **全树只有声明、没有定义**。
      ⚠️ **`Code::PayloadStart()` 在这里也是错的，我先试的就是它**：
      bare 模式下 Code 不拥有自己的指令，问出来的 payload 比 image 低约 1.5MB
      —— **又一次长得像「基址错了」**。地址必须从表里取。
      ✅ 名字改用 `Code::QualifiedName`（上游 `[Optimized] ` 前缀的出处），
      **格式与他们一致而不是我拼上去的**。
      ✅ **1589 vs 他们 1380 是预期的、不是缺陷**：我们的 VM 多带了 stub。
      检查里因此只要求 >1000 + 首条与他们一致，**不钉死一个有正当理由不同的数**。
      实测：无负偏移、无坏尺寸、无重叠，前 400 条里 351 条以 `ret/b/br/brk` 结尾。
- [x] 任务 37：**`self_hash` 真算法进树；顺带挖出我们的 SHA-1 是坏的** ✅ `bdaa00ded45` + spike `0317067`
      | 判据 | 结果 |
      |---|---|
      | C++ 移植 vs 已验证的 Python 模型 | **1589 / 1589** |
      | vs **他们的** `self_hash`（按 name+size 配对） | **777 / 950（82%）** |
      第二个数才是真判据 —— 它是**跨实现**的，不是自比；与模型已知的 1185/1380 吻合，
      差额就是那块没解的 walk 依赖序号。
      🔴 **真正的收获是一个潜伏的 bug**：移植后 entry 流与 Python **逐字节相同**却
      每个摘要都不一样 → 只剩一个可能：**`FhpSHA1` 根本不是 SHA-1**。
      ```c
      #define FF(i,f,k) t=...; e=d; d=c; c=FhpRot(b,30); b=a; a=t
      ```
      **六条语句、没有 `do{}while(0)`，而每处调用都是不带大括号的 `for` 体** ——
      于是只有 `t=` 在循环里，整个变量轮转在循环**结束后只跑一次**。
      **一个长得像 SHA-1、编得过、跑不报错、产出的十六进制看起来很正常、
      但和全世界任何 SHA-1 都对不上的函数。**
      ✅ 修好后第一条 entry 的 `self_hash` 与他们**逐字符相同**。
      ✅ 检查里钉了两条：首条 hash == 他们的值；且哈希不能几乎全部相同
      （占位符和坏摘要都会那样）。负控制：把 `FhpRot(b,30)` 改成 29 → 变红。
      ⚠️ `subgraph_hash`/`op_subgraph_hash` **仍是 `self_hash`，仍然是错的**——
      键保留以对齐 schema，代码注释已写明值不可信。它们需要模拟 walk（任务 30 的结论）。
- [x] 任务 38：**符号表已重测，并加了 `analyze_snapshot` 那一列** ✅（本轮无代码，是测量轮）
      唯一符号：他们 gs 32373 / 我们 34067（上次 34055）；他们 as 17194 / 我们 23851。
      🔴 **结构性改动：上一版只量 `gen_snapshot`**，于是把所有住在 analyze_snapshot 里的
      子系统都记成了「两边都 0 的口径陷阱」。**换个产物量，缺口就现形。**
      → **真实的「一侧为 0」缺口只剩两个，都在 `analyze_snapshot` 里：
      `SubgraphHasher`（12/0）与 `CascadeLimiter`（18/0）**，后者是**本轮首次量到的**。
      两者其实是同一块：`CascadeLimiter` 就是给 `SubgraphHasher` 的 walk 定界的。
      ✅ 顺带修正：`FieldHasher` 2/**6**（上次记 2/2）；`LinkOracle` 在 as 侧 **16/16 持平**。
      ✅ **方法教训**：`sha1_` 那行（他们 2 / 我们 0）差点被记成第三个缺口，
      **查了才知道我们有同功能的 `FhpSHA1Transform`，只是名字不同**。
      **「一侧为 0」是必要条件、不是充分条件——名字对不上也会给 0。**
- [x] 任务 39：**CLAUDE.md 的三条过期记账已按实测订正** ✅ `035f95e`
      只改事实、**不动规则**，**也没有顺手上调百分比**（36–42% 原样保留）。
      ① `analyze_snapshot --shorebird`「B4 已移植」是**一句空账**——
      它在树里、help 里没有、对我们自己的快照产出 **0 个函数**；现已真能用（1589 个）。
      ② 「口径陷阱」那条补上了它一直缺的数字：换到 `analyze_snapshot` 量，
      `SubgraphHasher` **12/0**、`CascadeLimiter` **18/0**，是**仅剩的两个一侧为 0**。
      同时写明 `sha1_`（2/0）**不是**缺口，免得它变成第四条错记账。
      ③ 「11 个 flag 完成」只覆盖 `gen_snapshot`；`analyze_snapshot` 另有 7 个，
      我们 4 个，还差 3 个；`--disassemble` 记为**已回退**而不是已实现。
- [~] 任务 40：**卡片的前提是错的；顺手量出了 `--dump_blobs` 的契约**（本轮无代码）
      🔴 **`CascadeLimiter` 不是 `SubgraphHasher` 的先决条件。** 我在任务 39 写卡时
      推断「它给 walk 定界」，**查证否掉了**：符号表里 `CascadeLimiterEntry`（48 个）
      与 `Dart_ComputeDDTable`（22 个）聚在一起，而**唯一**给 `CascadeLimiterEntry*`
      排序的 lambda 属于 `Dart_ComputeDDTable`，不属于 `SubgraphHasher`。
      → `CascadeLimiter` 服务的是 **`--compute_dd_table`**（一个**他们 help 里都没列**的
      隐藏 flag，`dd_pipeline.sh` 在用），与 subgraph 哈希的 walk 无关。
      ✅ **所以「仅剩两个缺口是同一块工作」这句也是错的**——它们是两块独立的工作。
      🎁 **顺手把 `--dump_blobs` 的契约量出来了**（它是三个缺 flag 里最小的一个）：
      输出 = **四个 region 按真实长度拼接**，以快照 data 的魔数 `f5f5dcdc` 开头。
      实测 `base.so`：blob **669622** 字节 = data **302390** + instructions **367232**；
      而 ELF 的 `.rodata`+`.text` 是 302496+367264 = 669760 —— **差 138 字节是 section 的对齐填充**，
      即**它用的是 VM 知道的真实长度，不是 ELF section 长度**。
- [x] 任务 41：**`--dump_blobs` 已实现** ✅ `b8fd30973c6` + spike `f856472`
      我们自己的快照：**504742 字节**，按各 region 的**声明长度**切回去，
      四段与 ELF 逐字节相同、无剩余。help 缺口 **4 → 3**。
      长度来源（`Dart_SnapshotAnalyzerInformation` 不带，这曾是它被记为"阻塞"的原因）：
      data 段用 `Snapshot::length()`；instructions 段用 `Image` 自带的 size 字段。
      🎁 **掉出来一个独立交叉验证**：isolate instructions 段量得 **295248** 字节，
      而这恰好是 `--shorebird` 走 `InstructionsTable` 时**最后一个函数的结束位置**——
      两个互不相干的来源give出同一个数。
      🔴 **第一版检查是废的，负控制当场证明了**：它靠「在 blob 里搜下一段的开头」
      来定边界——**边界读自被测物本身**。把每个 instructions 段截短 4 字节，
      它照样"round trip 通过"。改成**从 ELF 自己的头部重算长度**后，同一个负控制立刻变红。
      ✅ **可复用规则：检查的期望值必须来自被测物之外。**
      🔴 **另一个自己的错**：我在 `verify_all` 只看了 `tail -3` 就提交，
      **漏掉了 `1 failed`**——`analyze_snapshot_help_check` 正确地红了
      （实现了 flag 却没从 withheld 名单里删掉）。**检查按设计工作，是我没读输出。**
      提交信息里「4 → 2」也写错了（`--disassemble` 仍未实现），已 amend 订正为 4 → 3。
- [x] 任务 42：**失败项已无法被 `tail` 滚出视野** ✅ spike `b9d45a7`
      `verify_all.sh` 现在在摘要行**之后**重印失败的检查名（全绿时不加任何输出）。
      判据是按卡片要求**真造一个失败**验的，不是读代码：
      ```
      11 ran, 1 failed, 0 skipped, 0 blocked
      FAILED: analyze_snapshot_help_check.sh
      ```
      —— `tail -3` 就能看到是哪一项。还原后 11 ran / 0 failed，self-test 10 ran / 0 failed。
- [x] 任务 43：**两个假哈希已删除（不是改成占位串，是不发）** ✅ `efb63a21fdc` + spike `1159f56`
      🔴 **卡片里那个「先查我们自己的工具有没有在读」查出来了，而且是最坏的情况**：
      `tools/linker.py` **就是按 `subgraph_hash` 把 patch 函数配到 base 函数上的**，
      而且它自己的注释写着「配不上的函数**静默排除**」；
      它还把 analyzer 二进制当**参数**收，所以没有任何东西拦着它指向我们这个。
      **两边都实测了，不是推理**：
      | | `build_link_table` 的行为 |
      |---|---|
      | 旧的假值 | 返回 **1589 条**，**无任何报错** |
      | 删掉键 | 抛 `KeyError: 'subgraph_hash'` |
      → 旧行为会产出一张**填满的、语义错误的**链接表，且全程没有诊断信息。
      ✅ **所以选了「不发」而不是「填占位串」**：填空串会让所有函数塌进同一个桶，
      **又是一次静默错配**；不发则在第一个函数上就炸。
      ⚠️ **这是对他们 schema 的有意偏离**，代码注释写明了理由：
      规则 3 要的是「复刻接口以便被对照」，而**发一个已知错误的字段
      只是模仿了形状、破坏了契约**——用一个无法观测的保真度，换一个下游的静默失败。
      **等 walk 实现了再把键加回来。**
      负控制：把 `subgraph_hash` 加回去 → `class_table_dump_check` 变红。
- [x] 任务 44：**清点完成，并且把这一族的判别标准找准了**（本轮无代码，是清点轮）
      🔑 **原来的说法「静默失败」是错的分类。** 实测把它劈成了两半：
      | 形状 | 生产链路上会怎样 |
      |---|---|
      | **静默丢弃**（`linker.py` 配不上就 skip） | ✅ **已被兜住**：`broute/cli.py:568` 用 `min_link_pct` 门限拦，`linker.py:161` 也会警告 <80% |
      | **静默错值**（值合法、语义错） | 🔴 **反而击穿那道门限** |
      **实测**：把 `subgraph_hash` 换回本会话之前的假值（= `self_hash`），
      对真实 base/patch 跑 `build_link_table` → **1588 条、link% = 99.82%**。
      → **那道覆盖率门限会毫无察觉地放行。**
      ✅ **所以真正的判别标准不是「有没有声音」，而是：
      错误值会不会让下游的成功指标看起来更好。**
      丢弃会拉低 link%（被抓住）；错值会拉高 link%（抓不住）。
      这解释了本会话三次栽跟头为什么都是**生产者**侧（占位 `self_hash`、坏 SHA-1、假
      `subgraph_hash`），而不是消费者侧。
      📋 **仍存的同型嫌疑（都在 `--shorebird` 的输出里，都是「合法形状、错内容」）**：
      `subgraph_pp` **直接复用 `self_pp`**（subgraph 应含被调方，所以是错的）；
      `self_selectors` / `subgraph_selectors` / `self_field_table` /
      `subgraph_field_table` / `callees` **五个数组硬编码为空**——
      消费者读到的是「这个函数没有」，而不是「我们没算」。
- [x] 任务 45：**六个字段已删；`self_pp` 补完** ✅ `d0c9511ca67` + spike `831a84f`
      `--shorebird` 现在只发算得出来的东西：`name`/`offset`/`size`/`index_in_entries`/
      `self_hash`/`self_pp`。
      ✅ **先查消费者（任务 43 的做法）**：`tools/linker.py` 只读
      `name`/`offset`/`size`/`subgraph_hash` → 这六个**不是活的错数据**，只是待办。
      （与 `subgraph_hash` 那次不同，那次是活的。**同样的形状，紧迫度不同**，值得区分。）
      🔑 **`self_pp` 才是本轮最有意思的一个：它「正确但不完整」——同一种形状。**
      它只认 `ldr xN,[PP,#imm12]`，却把结果当成完整清单发出去；
      用大位移池访问的函数会被少报引用数，**消费者无从分辨**。
      现在它认全了池发射器实际会产生的形态，并且**复用 `ShorebirdSelfHash` 的解码器**，
      两边不会各自漂移。
      ✅ **交叉验证（同一个二进制里两套独立实现）**：`self_pp` 的条目数
      与哈希模型推出的「不同池序号个数」**对 1589 个函数全部相等**。
- [x] 任务 46：**`self_field_table` 加回来了；顺手把三个输出并成一次扫描** ✅ `8766b1f9e7b` + spike `bbf2825`
      卡片只要求「复用解码器」，但那样仍是**第三次扫描**。改成
      **一次扫描同时产出 `self_hash` / `self_pp` / `self_field_table`**。
      🔑 **理由不是整洁，是上一轮那个 bug 的根因**：`self_pp` 原本是**自己一趟独立扫描**，
      它认 1 种池加载形态而哈希认 3 种，于是**悄悄少报**，而输出里看不出任何异常。
      **两趟扫同一批指令必然漂移；一趟不会。**
      `Ordinal()` 顺手记下首次出现顺序，序号流与键清单一次走完，不需要第二次遍历。
      ✅ **判据**：与 `probe_subgraph_hash.py`（另一种语言里的独立实现）比对，
      `self_hash`/`self_pp`/`self_field_table` **1589/1589 全同**。
      ✅ **这条比对已进常设检查**——它就是抓漂移的那个东西。
      负控制：关掉三指令字段形态 → 报「25 个函数不一致」。
      ⚠️ `subgraph_field_table` 仍然缺席（它要 callee walk），未越界。
- [x] 任务 47：**可行性判定：`--compute_dd_table` 没有被那个大 walk 挡住** ✅ spike `1215236`
      ✅ **CLAUDE.md 那句「格式已逐字节解出」是准的**（本轮核实，不是所有记账都乐观）：
      解码他们的 `base.ddtable` **3969/3969 字节全部消耗**，67 条，
      与 README 记的条数一致。格式：
      `count:u, { hash:str, index:u, size:u } * count`，
      字符串是**每字符一个 signed varint**（`'a'`→`61 c0`、`'0'`→`f0`）。
      🔴 **但 README 把键的名字写错了，而这个错误正好指向最坏的结论**：
      它写的是 `subgraph_hash`（需要 callee walk，未解），
      实测 **67 个哈希里 67 个是 `self_hash`**、只有 1 个出现在 `subgraph_hash` 里
      （那是某个函数两个哈希恰好相同）。已订正 README。
      → **`--compute_dd_table` 用的是我们已经实现的 `self_hash`**
      （对他们 777/950），**不被那个大工程阻塞**。
      ⚠️ 仍未知：**67 条是怎么从 1380 个函数里选出来的**（`CascadeLimiter` 应该就是选择器），
      以及 `size` 的确切含义与 `--dd_max_bytes` 的反向关系（README 记了现象未记机制）。
- [~] 任务 48：**资格集已解出且逐字节对上；预算那半未解，但砍掉了一整族答案**
      ✅ `CASCADE_LIMITER_RECON.md` + `dd_selection_check.sh`（`verify_all` 现 **12 项**）
      🔑 **`--dd_max_bytes` 在 32 以下饱和**：预算 1/2/4/8/16 产出**逐字节相同**的
      619 条表 → 那就是**没有预算压力时的资格集**（不是「一个大样本」，这点是判据成立的前提）。
      🎉 **资格规则已解出，多重集零分歧（619 预测 / 619 实际）**：
      `有 ≥1 个调用者 AND（[Optimized] 或 allocation stub）`。
      1380 = 1179 optimized（有调用者的 532）+ 87 allocation stub（全有调用者）
      + 110 type-test stub（**有 61 个有调用者也不算**）+ 4 owner 为 null。**532+87=619**。
      🔑 **这与 `print_dd_function_identity_to` 是同一个族群谓词**（两边独立推出）：
      负控制里「去掉『有调用者』」正好给 **1266 = 87+1179**，就是那个 dump 的行数。
      🔴 **「条数随上限增大而减少」被误读成阈值规则了——整族出局**：
      上一轮探针在找 `cost(f) > budget` 的度量（最佳候选 `callers_sub` 三个预算零违例）。
      **任何**这种形式的规则都给出**嵌套**集合，而他们的表**不嵌套**
      （10 处：128 比 64 多 1、512 比 256 多 12、2048 比 1024 多 17…）。
      → `CascadeLimiter` 是**迭代/贪心**，不是阈值。
      ⚠️ **这条在三个空间各测一遍才敢信**：先用哈希展开成函数（碰撞可能造假），
      再用 `(hash,size)` 对，再用裸哈希 —— 十处违例完全一致。
      🔑 **方向也钉住了：看的是调用者一侧，不是 size、不是 callees。**
      选中的 68 个 vs 未选的 551 个：`#callers` 均值 **8.8 vs 1.7**（中位 4 vs 1），
      而 `#callees`（3.7 vs 3.4）与 `size`（334 vs 259）两组**分不开**——
      **尽管这个 flag 是按「字节」计的，size 并不是区分依据。**
      上行级联模型（callers 闭包、在 DD 节点处截断）高端贴合预算
      （16384→16264、32768→32376），中段超出（10000→10728）；
      **下行模型（subgraph 那趟）不是不准，是任何预算都超 4–60 倍。**
      ⚠️ 发射顺序**刻意留空**：前 200 条对升序索引有 9920/19900 个逆序对（基本打乱），
      与本仓库已解过的 libc++ 容器迭代序同型，**但没验证，所以不写进结论**。
- [~] 任务 49：**贪心的形状已解出，只剩遍历顺序** ✅ 研究侧 `7c46f67`
      ```
      cost(v,S) = v 的传递闭包**调用者**字节数，在已切断处停止，**不含 v 自己**
      S={}; for f in eligible（按某个遍历顺序）: if cost(f,S) > budget: S.add(f)
      ```
      🔑 **「不含 v 自己」是三个函数逼出来的，不是设定的**：预算 32 相对 16 恰好掉 3 个，
      都是 size 12、单调用者的 allocation stub，调用者闭包正好 **24 / 24 / 32**
      —— 全 ≤32 且全 >16。**把 v 自己算进去就是 36/36/44，一个都掉不了。**
      读法：v 反正要发，预算约束的是**它拖着多少别的一起发**。
      🔑 **是增长型不是收缩型**（两个都试了）：收缩型在默认预算给 19 条（他们 67），
      而且**预算 3408 以下根本无法表述**——全切时最大级联就是 3408，约束已不可满足。
      增长型**单趟即不动点**（第二趟在任何预算下都不动）。
      🎉 **按「调用者数降序」遍历，在 17 个预算里有 8 个逐条成员相同**（含全部饱和预算）。
      🔴 **本轮最该记住的一条：计数相同 ≠ 成员相同。**
      另有 1024/10000/16384 三个预算**条数完全一致而成员差 11/7/2 条**。
      **按条数打分这个顺序像 11/17，按成员打分只有 8/17。** 判据已把两件事都钉住。
      ⚠️ 两个顺序已否证并留作负控制：升序函数索引（7）、**表自己的发射顺序**（6）。
      后者本来能把「遍历顺序」和「发射顺序」两个问题合并成一个，**没成**。
      16384 那处是干净的 2 换 2：他们切的两个**各只有 2 个调用者**，
      我们切的是 37 和 4 个 —— **这正是排除调用者数的判据。**
- [~] 任务 50：🔴 **遍历顺序不是缺口 —— 天花板 8/17，模型本身不完整**（本轮无代码，是判定轮）
      15 个顺序全部按**成员**打分：调用者数升降、直接调用者字节升降、未切代价升降、
      offset 升降、索引升降、最小/最大调用者索引、size 降、name、`self_hash`。
      **最好的三个都是 8，而且精确命中的是完全相同的 8 个预算**
      （1/2/4/8/16/32/64/32768），尽管它们按毫不相干的量排序；其余全是 6 或 7，
      且总是同一串的前缀。**128 到 16384 没有任何顺序能复现。**
      🔑 **三个不相干的顺序在完全相同的地方成功，这不是「顺序错了」的样子，
      是「算法错了」的样子。** 那 8 个恰好都是顺序几乎不起作用的预算：
      5 个饱和的，加上 32/64（只少切 3 个和 58 个）与 32768（只切 18 个）。
      → 任务 49 的代价函数与「增长型单趟」形状**在两端被证实、在中段不完整**。
      **还有别的东西随预算变化。**
- [~] 任务 51：**签名已从 mangled name 拿到；并且撤回了一个我发布过的错误结论** ✅ 研究侧 `ed018b0`
      `Run` **没有自己的符号**（内联进 `Dart_ComputeDDTable`），但它内部实例化的 introsort 有，
      **mangled name 逐字带出外层签名**：
      ```c++
      Run(const unordered_map<long, unordered_set<long>>&,   // 邻接图
          const vector<long>&, const vector<string>&, long, long long budget)
      ```
      🔑 **此前把两个不同的排序混为一谈了**。`Run` 内部那个排的是**节点索引**，
      按捕获的 `vector<long>`（第二个参数）**升序**：
      `ldr x10,[x5]; ldr x10,[x10]; ldr x11,[x10,x8,lsl#3]; cmp; b.ge`。
      **有符号**（`b.ge` 不是 `b.hs`）→ 那些 long 可以是负的。
      **那个 vector 装的是什么尚未确立，刻意不猜**（size 升序与调用者数升序作为遍历顺序
      已实测得 6 和 7 分）。另一个排序在 `Dart_ComputeDDTable` 里，按 `memcmp` 比字符串，
      而 `CascadeLimiterEntry` 布局由交换代码直接读出：
      `{long; std::string(24B); long}`，sizeof `0x28` —— 正是表的 `(index, self_hash, size)`。
      🔴🔴 **撤回**：我在任务 48 写下的「发射顺序匹配不上任何东西、9920 个逆序对、
      多半是 libc++ 容器迭代序」**全错**。**表在 17 个预算下全部按 `self_hash` 升序**，
      正是 memcmp 比较器该给的结果。
      **错因**：那次测量把函数经由 `(self_hash,size)` 字典映射到 slot，
      **碰撞键互相覆盖**，多个函数拿到同一个 slot，于是**所有**顺序判定都因构造而失败——
      包括正确的那个。⚠️ 讽刺的是同一份文档往上三节就写着「`self_hash` 不能命名函数，
      所以比较要用多重集」，然后转头就拿这个对做了字典键。
      ✅ **正确结果自洽**：`self_hash` 作为遍历顺序得 6/17，
      而探针里「表自己的发射顺序」这个负控制也得 6 —— 同一个顺序、同一个分数、两次独立测量。
      判据已把发射顺序在 17 个预算上钉住，且**直接比发射出的字符串，不再经过函数表**。
- [~] 任务 52：**assert 串路线在这里不通；但挖到两个从未清点的 DD flag** ✅ 研究侧 `67f0287`
      🔴 **`strings` 里没有 `cascade_limiter.cc`、没有行号、没有条件串** ——
      破 `Assembler::PadLoadStore` 时白送的那些东西，这个子系统一样都没有。
      **这个子系统只能靠反汇编或黑盒实测**。已记进文档，别再重跑 `strings`。
      🎁 **顺带产出**：四个 DD flag `--compute_dd_table` / `--dd_max_bytes` /
      `--dd_table_data` / `--compute_dd_slot_mapping`，后两个**从未清点过**，
      且有依赖：`--dd_table_data is required with --compute_dd_slot_mapping`。
      ⚠️ **四个全部不在 help 里**（他们 help 只列 13 个）→
      「**被接受的 flag**」与「**被文档化的 flag**」在这个二进制上是两个不同的族群，
      我们的 help 缺口计数从来没看见过它们。`--no_pp_hash` 是反向的同一现象
      （在 help 里、parser 不收）。
- [~] 任务 53：**流水线全貌已解出；但这个 oracle 暂时驱动不了** ✅ 研究侧 `54384f4`
      🔑 **`Empty value for option <名>` 能精确枚举两个二进制的 embedder 选项表** ——
      比 `--help` 便宜得多，而且是**另一个族群**（help 只列 13 个，DD flag 一个都不在里面）。
      流水线：
      ```
      gen_snapshot     --print_dd_function_identity_to=I      (VM flag)
      analyze_snapshot --compute_dd_table=T --dd_max_bytes=N
      analyze_snapshot --compute_dd_slot_mapping=M --dd_table_data=T
                       --dd_caller_links=C [--dd_function_identity=I]
      gen_snapshot     --dd_slot_mapping=M                    (embedder 选项)
      ```
      ✅ **slot mapping 文件头已获一方证据**：他们产出 `55 7e ca dd | 02 00 00 00 | 80`
      = magic `0xDDCA7E55`、version `2`、varint 0。
      我们 `dd_voting.h:124-125` **本来就声明的是这两个值**（当初从 gen_snapshot 侧推的），
      **逐字节相同** —— 这是第一次看到他们自己的生产方发出它。
      🔴 **但 `dd_caller_links` 在两个二进制里都没有生产方**：
      它是 `analyze_snapshot` 的输入，却不在 gen_snapshot 的 embedder 选项里、
      不在它的 `print_*` VM flag 里、也不在 analyze_snapshot 自己的输出里
      （`out` / `compute_dd_table` / `compute_dd_slot_mapping` / `dump_object_pool_link_data`）。
      → **它产自两个二进制之外**（他们的闭源 linker 或构建编排）。
      ⚠️ **所以这个 oracle 现在驱动不了**：flag 能跑，但第二个输入造不出来。
      要先逆出 `dd_caller_links` 的格式，**这件事比排期时看起来的大**。
      ⚠️ 它的解析器无保护：喂 ddid 退 138、喂 `/dev/null` 抛 `bad_alloc`。
      **崩溃不能当格式证据**（datastream 陷阱同型，边界检查是 ASSERT、release 已编译掉）。
      🎁 顺带：gen_snapshot 的串里有**私有源文件清单** ——
      `class_table_mapper.cc` / `link_info.cc` / `linker.cc` /
      `object_pool_editor.cc` / **`object_pool_mapper.cc`**。没有 `cascade_limiter.cc`，
      与它住在 `analyze_snapshot` 一致。
- [~] 任务 54：🎉 **解出来了：那是拓扑深度；天花板 8/17 → 11/17** ✅ 研究侧 `8dc6478`
      `Dart_ComputeDDTable` 在 **`analyze_snapshot_api_impl.cc`**（**上游文件名**，
      `0x10024ebb0` 的 assert 给出文件与行号 1319），`Run` 内联在里面，
      它的 `std::sort` 就是 `0x10024ec2c`。
      ① **被排序的向量是恒等排列** `0,1,2,3,…`（`0x10024eb54` 起向量化填充）→ 排序产出的是**节点顺序**。
      ② **比较器捕获的 `vector<long>`（`sp+0x88`）是最长路径深度**，由教科书式 Kahn 填充：
      入度为 0 播种（`0x10024e980`）、`std::deque` 工作表（`sp+0x1b0`）、
      `malloc`+`memcpy` 复制入度数组、`indeg[v]--`，松弛在 `0x10024ea9c`：
      `depth[v] = max(depth[v], depth[u]+1)`。
      ⚠️ **图有环，而 Kahn 不处理环**：入度永不归零的节点从不出队（callee 图上 1380 个里有 716 个）。
      **这是他们的真实行为，必须复刻，不能抹平。**
      🔴 **2026-08-26 任务 57 订正：原文「深度保持 0」说得太强**。松弛发生在减入度**之前**、
      且不看目标的入度，所以这种节点**可以收到深度**，只是永远不往外传
      （`0→1,1→2,2→1` ⇒ `depth[1]==1`）。是一个失败的单测逼出来的订正，不是读代码读出来的。
      🎉 **按成员打分：callees 方向、升序 = 11/17**（1/2/4/8/16/32/64/**128**/**256**/16384/32768）。
      **128 和 256 是任务 50 那轮 15 个顺序里没有一个拿得到的。**
      其余三种组合：callers 降序 8、callees 降序 6、callers 升序 6。
      🔑 **任务 50 测出的「天花板 8」是猜测的天花板**；打破它的顺序来自反汇编。
- [~] 任务 55：**分叉已判定 = 分支 B（只有一个关键字）；顺带证明「只差平票顺序」** ✅ 研究侧 `bd0f18c`
      `CASCADE_LIMITER_RECON.md` §10-§12 + `tiebreak_probe.py`（**本轮无源码改动**，`~/dart-3122/sdk` 干净）
      🔴 **比较器只捕获一样东西**：调用点 `0x10024ec10 str x9,[sp,#0x170]` 是**唯一**一次往比较器对象里写
      （`x9 = sp+0x88 = &depth`，随后 `add x2,sp,#0x170`）。三个函数
      （`__introsort`@`0x100192080`、`__sort5`@`0x100192f9c`、`__insertion_sort_incomplete`@`0x1001931a4`）
      里**全部 64 处**经比较器指针的读都是 `ldr xN,[xComp]`、偏移 0。
      ✅ **否证前先说清判据覆盖了哪些编码形式**（吃过一次亏，见验证纪律）：
      `[xC,#imm]` / `[xC,xM{,lsl}]` / pre-post-index / `ldp` / 寄存器施加的 `add xT,xC,…` 五种全查，全无。
      **「按索引 tiebreak」（不需要捕获）另行否证**：`__sort5` 是完整 9 比较网络，
      条件直方图 12×`b.ge` + 1 个栈保护 `b.ne`；另两个函数里 17 处 `b.eq/b.ne` 逐条读上下文，
      全是长度分派 / 迭代器相等 / `cmp w9,#8` 的乱序计数 / 栈保护，**没有一处跟在深度比较之后**。
      🎉 **本轮真正的收获比分叉判定大**：随机平票顺序 3000 个里 **41 个 17/17 全中**
      （新中的正是缺的那六个：512/1024/2048/4096/8192/10000，baseline 分别只差 3/1/2/1/2/2 条）。
      → **代价函数、贪心形状、资格规则、深度关键字全部是对的，缺口就只剩平票顺序这一件**；
      这**撤回**了 §6 里「算法错了」的读法。
      ⚠️ **但 17/17 已经不再是判别性判据**：那 41 个顺序两两在平票组内的一致率只有 **0.497**
      （0.5 = 无关），随机顺序有 **1.4%** 能过。**下一轮不能再用它当判据。**
      ⚠️ 14 个确定性 tiebreak 全部到不了 17；最好的 `self_hash desc` 到 14，
      **几乎肯定是巧合** —— 比较器里没有任何一处读字符串。
- [x] 任务 56：🎉 **introsort 轨迹已逐元素抄对；11/17 → 17/17 全中** ✅ 研究侧 `e3e23fb`
      `LIBCXX_INTROSORT_RECON.md` + `introsort_model.py` / `libcxx_sort_oracle.cc` /
      `introsort_check.py` / `introsort_negctl.py` / `introsort_order_check.sh`
      （**`~/dart-3122/sdk` 无改动**，全在研究侧；`verify_all` 12 → **13 项**）
      ✅ **判据 (a) 转写保真度 = 精确 oracle**：用真的 libc++ `std::sort` 跑同一个 1380 元素恒等向量
      + 同一个单关键字比较器，要求模型输出**逐元素相同** → **1380/1380 全中**，
      且在 libc++ 21 与 23 两套工具链下**都**编译并给出同一置换。
      ✅ **判据 (b) 成员分 = 17/17**，新中的正是缺的那六个：512/1024/2048/4096/8192/10000，无一失败。
      🔑 **立 (a) 这条判据是本轮的真正价值，不是那个 17**：对转写做 9 个一行变异，
      **其中 3 个是真错但仍然 17/17** → **成员分对真实错误也是瞎的**，不只是对随机顺序瞎；
      而 (a) 对 9 个变异全部变红。**这条撤回了任务 55 里「14 个确定性 tiebreak 全部到不了 17」的说法。**
      ✅ **LLVM 21 vs 23 的有效性前提已裁决（往好的方向）**：macOS SDK 出的是 libc++ `210106`，
      它的 `__algorithm/sort.h` 与树内 `230000` 那份**逐字节相同**（md5 `35a0f94a…`），
      而两边的 `__config` 不同 → 确是两个版本、但排序算法没变。
      **且判据不靠这个 md5**：oracle 用两套工具链各编一次、要求给出同一置换，是行为结论不是文件结论。
      ⚠️ **它自己的第一个负控制是恒等变换**（`__limit 24→25` 全绿）→ 插桩量出
      `len==24` 出现 **0** 次、`len==23` 出现 1 次，改用 `24→23` 才变红。
      `ninther_threshold 128→127` 同样被证明是 no-op（124..132 内无分区长度），
      **每轮重测这个证明而不是豁免它**。这正是「变红之前先问这一行语义真的变了吗」。
      顺带实测（不是假定）：只排 619 个合格节点会得到**不同**的顺序（§12 得证）；
      两条选轴路径都被走到（17 次 ninther / 12 次 median-of-3）；
      深度耗尽的堆排序回落**从未到达**，模型在那里**抛异常而不是猜**。
- [x] 任务 57：🎉 **`--compute_dd_table` 已进源码树**（第一次有真 C++）✅ `32582a15fb4` + 研究侧 `4479bd6`
      新 `runtime/vm/shorebird/cascade_limiter.{h,cc}` + `cascade_limiter_test.cc`；
      改 `analyze_snapshot_api_impl.cc` / `bin/analyze_snapshot.cc` / `include/analyze_snapshot_api.h` /
      `shorebird/link_info.{h,cc}` / `vm_sources.gni`。
      研究侧 `dd_table_model.py` / `dd_table_probe.py` / `dd_table_check.sh` / `DD_TABLE_LANDING.md`。
      **`verify_all` 13 → 14 项；`run_vm_tests` 143 → 154 passed**（+11 `CascadeLimiter_*`，
      `EXPECTED_TESTS` 抬到 154 **且把 `CascadeLimiter` 加进名字过滤器** —— 不加就永远不会被选中）。
      ✅ **分叉判定 = (A) 直接用 `std::sort`**，而且是**实测**不是靠 md5 推断：
      在一个**模型从未调过参**的 1589 节点新图上，我们构建的二进制与参照模型在全部 17 个预算上逐字节一致；
      且该比较在这里**有判别力**（把模型的顺序反过来，11/17 变红）。`introsort_model.py` 降级为测试参照。
      🔴 **「与他们的产物逐字节相同」做不到，而且是结构性不可能，不是差一点**（两条独立实测）：
      ① 快照版本墙 —— 我们的 `analyze_snapshot` 读他们的 `base.so` 报
      `Wrong full snapshot version, expected '7150a2e84c1d…' found '839937ddd313…'`（反向同样被拒）；
      ② **就算从他们自己的 `base.dill` 出发，我们的 `gen_snapshot` 发 1589 条、他们 1380 条**
      （1388 `[Optimized]` vs 1179），`(name,size)` 只有 935 对共有，`self_hash` 对上 762/934。
      **群体不同，DD 表就不可能相同。**
      → 改成**两段链，每段都逐字节**：参照模型 ≡ **他们的** `--compute_dd_table` 字节（17 个预算全中，
      也等于随包的 `out_dd/base.ddtable`）；我们的二进制 ≡ 该模型字节（同样 17 个预算）。
      🔑 **本轮真正的解锁是 callees 图的定义**：它就是**函数体内 `b`/`bl` 的跳转目标**，
      拿**他们自己的字段**对过 —— **1380/1380 个集合、3629/3629 条边，零多零漏。**
      🔴 **一条 recon 断言被一个失败的单测订正了**：`CASCADE_LIMITER_RECON.md` §9 的
      「环上节点保持深度 0」**说得太强**。松弛发生在减入度**之前**、且不看目标的入度，
      所以这种节点**可以收到深度**，只是永远不往外传（`0→1,1→2,2→1` ⇒ `depth[1]==1`）。
      单测、两处代码注释、recon 文档都已改成更细的说法。**下面任务 54 的卡片同步订正了。**
      ⚠️ **负控制两个都是真的且失败在不同预算集**：`Cost` 把节点自己算进去 → 10/17 红；
      `VisitOrder` 比较器 `<`→`>` → 11/17 红。
      🔴 **但 2 号控制第一次根本没编译成功**（`ninja` exit 1，尾部 `// NEG CTL` 吞掉了 `);`），
      检查却照样变红 —— 那是 1 号控制留下的**陈旧二进制**，**数字一模一样**。
      **只有 ninja 的退出码能区分这两种情况。** 记在 `DD_TABLE_LANDING.md` §4。
      ⚠️ 两处刻意偏差已写在 `cascade_limiter.h` 里没藏：他们的 `Run()` 没有资格参数
      （我们用空 hash 编码它）；`Dart_ComputeDDTable` 七个参数里有四个归因不出来。
- [~] 任务 58：🎉 **`subgraph_hash` 已解出并进树（1380/1380 逐字节）；`op_subgraph_hash` 缺口已命名**
      ✅ `da614c52006`（只改 `runtime/vm/analyze_snapshot_api_impl.cc`）+ 研究侧 `279a83a`
      （`SUBGRAPH_WALK_RECON.md` / `subgraph_hash_model.py` / `subgraph_hash_probe.py` /
      `subgraph_hash_check.sh`；`verify_all` 14 → **15 项**）
      🔑 **三个 Hasher 的身份不用推断，他们的 ctor 直接写出来了**（`0x100195c54`，SSO 字面量）：
      `"subgraph"`@`this+0x28`（vector `+0x40`）、`"object_pool"`@`+0x60`（`+0x78`）、`"self"`@`+0x98`（`+0xb0`）。
      `Hasher = {string; vector<Entry>; bool}`，`sizeof 0x38`。
      ✅ **walk 的界是 per-root 的 `vector<bool>`**（`this+0x00`，按 instructions-table 索引，
      `ldr x8,[x26]`/`tst`/`b.ne`@`0x100196890`）。**没有深度上限** —— `depth`(w21) 只门控 `"self"`
      （每个 `+0xb0` 的 push 都在 `cbnz w21` 之后）与日志缩进。
      单一自调@`0x100196928` 带 `add w2,w21,#1` ⇒ 递归发生在调用点、按指令顺序，callee 被就地插入流中。
      `Entry{1,offset}` 的 push **在 visited 测试之前**。
      ✅ **九种 kind 的路由是穷举出来的**（全部 22 个 `push_back` 站点 + 每一处 `orr xD,xK,xV,lsl #32`）：
      `"subgraph"` 每个字拿 `(7,word)`、**不收 kind 2/3/4/5/6**，且保留折叠形式的每一个字；
      `0x100197448`/`0x1001974ec` 那两处写**是 pop 不是 push**（`mvn x9,x9` ⇒ `end += (1-n)*8`），
      而且只作用在 `"object_pool"`/`"self"` 上。
      `CodeName` = `Utils::StringHash(Code::Name())`，由 ctor 只往 `+0x78` 推一次。
      🔴 **它推翻了任务 19 的①**：序数表是**成员**（`+0x100` 池、`+0x198` 字段表），**每一层都要查** ⇒
      **`self_hash` 可证不是「某个函数字节的函数」**。`+0x128`（外部目标）在 depth-0 分支里。
      值是**插入序数**，因为 `ldr x3,[x26,#0x140]` 读的就是这张表自己的 `size()`。
      🔴 **「比划分不比摘要」这条方法在这里是空的，而且探针自己断言了原因**：
      他们的 `subgraph_hash` 在 1380 个函数上取 **1380 个不同值** ⇒ 真值划分是离散的，
      **任何单射候选都「复现」了每一个等价类**。改用摘要相等做判据：
      模型复现他们 **1380/1380**；我们构建的二进制与独立的 ELF 驱动模型一致 **1589/1589**。
      → **`subgraph_hash` 现在是真的发出来了，不再是 `self_hash` 的副本。**
      ⚠️ **`op_subgraph_hash` 仍然缺席**（路由已解，实测 **842/1380**，卡在分类器）。
      ⚠️ **`self_hash` 实测 1185 → 1208/1380**（把序数表改成 walk-global 之后）——**这个修法本轮没落地**，
      留给下一轮。
      ⚠️ **刻意没猜的四件**：`Instr::ImmLogical()` 那条臂；`movz/movk` 的寄存器偏移型池加载
      （已定位 `0x100197550`-`0x100197598`，走 `LoadStoreFromSingle`，**只描述未实现**）；
      经 `x16` 的池加载臂（已定位未实现）；`DDTableLinkInfo*` 的作用仍未知。
      ⚠️ **负控制两个都带 ninja exit 0**（上一轮那个陷阱的修法生效了）：
      Offset entry 挪到 visited 测试之后 → 红 `959/1589`；不在 root 之间重置 visited → 红 `397/1589`；
      两个都还原、diff 与控制前副本相同、之间重建过并绿过。
      ⚠️ **第三个负控制（删掉 visited 集合）被 exit 137 杀掉** —— callee 图有环，
      那是**不终止的算法，不是变红的检查**。已记在 recon 文档。
      ⚠️ **`class_table_dump_check.sh` 本轮真红了两次，两次都是真的**：先是它把 `subgraph_hash`
      守成「必须缺席」；改完之后我的替代断言又要求**单射**，而**正确实现恰恰不满足单射**
      （名字不进这个 hash ⇒ 字节相同的叶子必然碰撞）。
- [x] 任务 59：🎉 **两个缺口都归零：`op_subgraph_hash` 842 → 1380/1380，`self_hash` 1185 → 1380/1380**
      ✅ `ee99498bfb1` + 研究侧 `19344f2`（`SUBGRAPH_CLASSIFIER_RECON.md` / `hasher_model.py` /
      `SUBGRAPH_WALK_RECON.md` / `class_table_dump_check.sh` / `subgraph_hash_probe.py`）
      **`op_subgraph_hash` 第一次真正发出来了**（此前是 `self_hash` 的假数据），`self_hash` 改成 walk-global。
      判据是**摘要相等**、两段链：模型 ≡ 他们的 1380，我们的二进制 ≡ 模型（我们的 1589）。
      **不是空判据**：探针断言了真值划分大小——`self_hash` 1170 类 / 1380（有信息），
      `op_subgraph_hash` 1380/1380（离散 ⇒ 划分分数**本来就会是空的**，所以才改用摘要）。
      解出来的（全部来自 `analyze_snapshot_arm64` 反汇编）：
      · `movz`/`movk` 寄存器偏移型池加载 —— `0x100196d4c` `ubfx w10,w8,#29,#2; cmp #3`，
        要求 movk `hw==1`、pc-8 处有同 `Rd` 的 `movz`，偏移 `= movz.imm16 | movk.imm16<<16`，走 `LoadStoreFromSingle`（3 字）
      · 经 `x16` 的池加载 —— 三条 ldp 臂，闸门 `(w&0xFB400000)==0xA9400000`（只 64 位 LDP，排除 `stp`），
        前缀 `add x16,Xn,#imm` 由 `(prev&0x9F00001F)==0x91000010` 匹配。命中 6/6
      · `Instr::ImmLogical()` 两处调用点（`0x100196ed0` dispatch 头、`0x100197100` field-table 头）
      · `LoadStoreFromSingle`（`0x100195774`）数值那半是 `(offset-16)/8` **截断**（`csel mi`，不是 `asr`）
      🔑 **真正把分数补齐的三条都不在卡片上**：池/field 序数**数引用不数去重索引**
      （`0x100196c28` 无条件 push，随后 `try_emplace(idx, size-1)`）；field 闸门是
      `(w&0x0A3FFBE0)==0x08003B40` ⇒ THR+0x70/0x78；**分类器是往回看并 pop 的**
      （`0x10019744c` `mvn`）然后跳过 `3-n`；dispatch 头是 3/4/5 字。
      判据实测：`ninja` Release+Product 均 exit 0（本轮重建过）；`verify_all.sh` exit 0
      **15 ran / 0 failed / 0 skipped / 0 blocked**；`verify_reproduction.sh` **28 产物 0 失败**；
      `run_vm_tests` **154 passed**；`subgraph_hash_check.sh --self-test` exit 0（14 ok，含 3 个模型扰动变红）。
      负控制（每条都在同一轮 `ninja` exit 0 下取得）：池序数改成去重计数 → 红（self 1440、op 1167）；
      field 闸门放宽成任意 `ldr [THR,#x]` → 红（1465 / 670）；关掉往回 pop → 红（1586 / 1572）。
      ⚠️ **第四条负控制是绿的，且没有被放过**：关掉 `movz`/`movk` 池臂 → 全绿，插桩实测该臂
      在两份语料上**触发 0 次** —— 它是**已证明的 no-op**，按他们的形状实现但当前无覆盖，记在 recon §7。
      ⚠️ 同型的零覆盖还有 `Instr::ImmLogical()`（两份语料都 0）。
      ⚠️ 刻意没猜：`DDTableLinkInfo*`（`this+0x20`）的作用；
      发布的 `subgraph_pp`/`subgraph_field_table`/`self_selectors`/`subgraph_selectors` 是否去重
      —— 它们仍然不在 dump 里；固定跳过 `3-n` 与「消费 NOP」在两份语料上**不可判别**。
      ⚠️ 顺手翻正了一道陈旧护栏：`class_table_dump_check.sh` 还断言 `op_subgraph_hash` **必须缺席**，
      并驱动着已被取代的 byte-local `probe_subgraph_hash.py`，两处都已修。
- [x] 任务 60：🎉 **两个 flag 都落地；`pairs` 的来源被彻底推翻重解**
      ✅ 源码 `c316526c1cb` + 研究侧 `a33c117`（`OBJECT_POOL_DUMP_RECON.md` / `op_dump_check.sh` /
      `op_dump_probe.py`）+ 状态侧 `1cea929`、`ffb254c`
      **两个 flag 都是真注册的**（行为测试，不是 `strings`）：`--dump_object_pool_link_data` 是
      **STRING 选项、自带路径**（裸名被拒、`=` 空报 "Empty value"、`=path` 接受、**不需要 `--out`**）；
      `--dump_object_pool` 是 **BOOL**（`=value` 报 "Non-empty value"）。都不是 `--no_pp_hash` 那种死 flag。
      入口：`Dart_DumpObjectPool`@`0x10024c32c`、`GetObjectPoolLinkInfo`@`0x10024cb9c`（共享生产方）、
      `Dart_DumpObjectPoolAsJson`@`0x10024d668`。（顺带：他们的类表 dump 叫 `Dart_DumpClassTable`，
      我们叫 `Dart_DumpClassTableAsJson` —— 已知命名偏差。）
      🔑 **`pairs` 不是代码扫描，这一条推翻了此前的整个方向**：`GetObjectPoolLinkInfo` 的第一个循环
      （`0x10024cc2c`-`0x10024cc40`，`and w9,#3; cmp w9,#1`）读的是**对象池的 `entry_bits`**。
      Shorebird 把上游 4 位的 `TypeBits` **压到 2 位并移到 bit 2**，在 **bit 0..1 塞了 2 位 `PairPosition`**
      （0 无 / 1 第一 / 2 第二）。布局由**三处独立证据**钉死：`NewFromBuilder` 的 `and #0xc; cmp #4`
      （gs `0x10015d884`）、JSON dumper 的 `ubfx w8,w8,#2,#2`（as `0x10024e128`）、
      `AddObject` 对 `kImmediate128` 拆分写的字面量 `0x11`/`0x12`（gs `0x100255684`/`0x1002556a4`）。
      三个打标点：`LoadNativeEntry` 写字面量 `0x9`（gs `0x10024e68c`）；`AddObject` 的序言
      （gs `0x1002555f4`-`0x100255620`）把**紧接在已标记 native 之后加入的那一项**标成 second
      —— **是位置性的，它从不检查新项的内容**；`EmitInstanceCallAOT` 写 `csel(0x65,0x05)` 再写 `0x06`
      （gs `0x10027e23c`/`0x10027e258`）；`GenerateTTSCall`（**推断**，完全内联、零符号）。
      **92 + 6 + 287 = 他们的 385，分毫不差。**
      这个标记**必须活过反序列化**：`kResetToSwitchableCallMissEntryPoint` 那条臂会重写整个字节，
      而他们的 dump 里那 6 项既显示为 `(unknown)`（kImmediate）**又仍在 `pairs` 里**。
      `entries[].code` 是他们自己那份 `ObjectPool::DebugPrint`（串块在 `0x29aae8`，上游在 `0x290024`）：
      多了 `<%ld len string> (obj)`，`"(raw)"` 改名 `"(unknown)"`。
      ⚠️ **截断判据用 `Utf8::Length >= 0xf9`，但打印出来的数是 `String::Length()`**
      （`0x10024e218` `ldur x8,[x8,#7]; asr x8,x8,#1`）——混用会把 2112 打成 2844。`offset = index*8+16`。
      判据实测：`ninja` Release/Product 均 exit 0（末轮复跑报 `no work to do`，产物 mtime 确实推进）；
      `verify_all.sh` **16 ran / 0 failed / 0 skipped / 0 blocked**（15→16）；
      `run_vm_tests` **157 passed**（154→157，`EXPECTED_TESTS` 同步抬到 157 且实选 157）；
      `verify_reproduction.sh` 28 产物 0 失败（不变，本改动不碰 ct/dt/ft/ddid）。
      结果：我们的池 **1421 = 他们 1421**；我们的 `pairs` **385 = 他们 385，逐索引相同**；
      1421 条 entry 描述里 **1323 条逐字节相同**（另 98 条是反序列化重置槽，装的是进程内地址：
      92 个 `kResetToBootstrapNative` + 6 个 `kResetToSwitchableCallMissEntryPoint`）；
      我们的 `.op` 217349 字节，**解码→重编码逐字节相同**。
      四条负控制**全部变红且都在同一轮 `ninja` exit 0 下取得**，事后全部还原
      （`grep -c "NEG CTL"` 三个文件均为 0）：去重 pp 列表 → 红（1459/1136）；
      不再让 pair 标记活过 switchable-call 重置 → 红（385→379）；去掉 `GenerateTTSCall` 的标记 → 红（385→98）；
      长串改打 `Utf8::Length` → 红（1323→1320，且点名了确切的三个串）。**没有一条控制是绿的。**
      🔴 **本轮挖出一个新的假红陷阱，值得单独记**：**改动 `runtime/vm/` 下任何文件都会改变快照版本 hash。**
      负控制若没有同时重建 `gen_snapshot`，会死在 `Wrong full snapshot version` 上
      —— **退出码和「因预期原因变红」完全一样**。控制 2 第一次就是这样「红」的，重建后才重新计数。
      刻意没猜：`ObjectPoolBuilder::PairEntry`（他们的 builder 带一个 `std::vector<PairEntry>`，
      但 `AddObject`/`NewFromBuilder`/`GetObjectPoolLinkInfo` **没有一处读它**，且仅 `entry_bits`
      就已解释全部 385）；他们给 pair 参数的拼写（`AddObject(const Object&,...)` 内联进了每个调用方）；
      他们的 `LoadNativeEntry` **忽略自己的 `patchable` 参数**（硬编码 `0x9`，`w2` 从不读取）
      —— 我们把它传下去，**把差异留在明面上而不是照抄一个疑似 bug**；32 位的 `entry_bits` 布局（不可观测）。
      ⚠️ 顺带发现：`memory/project_dart_sdk_fork.md` 在**仓库副本**与 `~/.claude/projects/…` 副本
      **两份已经漂移**，本轮两份都补了任务 60 章节。这正是契约第四条警告的那种漂移。
- [x] 任务 61：⚠️ **本轮的产出是「任务本身不成立」—— 三处分歧早在 23 个提交之前就已全部关闭**
      三处分歧全部由 `ab58e28152d`（*"the object pool aggregator, and its weighted votes"*，2026-08-25）
      关闭；该提交是当前 HEAD `c316526c1cb` 的祖先（`git merge-base --is-ancestor` 实测为真），
      落后 **23 个提交**。`linker.cc:449-534` 现在就是加权投票 + 无 size==1 过滤 + 黏性 `csel`。
      ⚠️ 连「判别实验必须自己造」那条也是过期的 —— `make_op_fixture.py` **早已存在**
      （S2 2×2、CONTEST 2×2 两个 base code 同占池槽 20 造出 base 索引争用、FALLBACK、SG、
      W1 2×2 / W2 1×5 钉住权重除数），由 `op_aggregator_check.sh` 驱动，**已在 `verify_all.sh` 里**。
      ⚠️ `OP_AGGREGATOR_RECON.md` 说的「`GetBestMapping` 0 符号、源码 0 引用」也是假的：
      `nm -a | c++filt | grep -c ObjectPoolMappingsAggregator` **他们 8 / 我们 10**（我们高只因未 strip）。
      **本轮唯一的真实产出是三个负控制**（oracle：他们的 gen_snapshot 对合成 fixture 出 `8/7/0/121`，
      我们如实给出 `8/7/0/121`），三条分歧**各自被判别**、都变红、都还原：
      ① 权重 `1.0/N`→常数 `1.0` ⇒ `8/8/0/120`（`ObjectPoolLinkResults_WeightIsNormalisedByGroupSize`）；
      ② 加回 `size()!=1` 过滤 ⇒ `2/2/0/126`（`…_AmbiguousGroupsAreVotedOnNotDropped` +2 连带）；
      ③ 强制无条件 `self_pp` ⇒ `7/6/0/122`（`…_UsesSubgraphIndicesWhenBaseGroupExists`）。
      三轮负控制的 `ninja` 在 `ReleaseARM64` 与 `ProductARM64` **都** exit 0 —— 任务 60 立的新纪律本轮
      真的用上了：变红后逐条读了失败信息，确认原因是改坏的那处，不是 `Wrong full snapshot version`。
      判据：`verify_all.sh` **16 ran / 0 failed / 0 skipped / 0 blocked**、`--self-test` 15 ran / 0 failed /
      1 skipped、`run_vm_tests` **157 passed** —— 与基线一致，**因为没有代码改动，不变才是对的**。
      源码树**零改动**，HEAD 仍是 `c316526c1cb`，`linker.cc` 的 md5 前后一致。
      改的只有研究树：`OP_AGGREGATOR_RECON.md` §3 从「未关闭的分歧」改写为「已于 `ab58e28152d` 关闭」，
      带逐条负控制证据（提交 `5a2931d`）。
      🔴 **根因与代价**：`CLAUDE.md` 与 recon 文档都还挂着 `ab58e28152d` 之前的措辞，
      **且没有日期或提交号可供核对** —— 它生成了一个完全不存在的任务，白烧一轮。
      **这是本项目第四次同型**（`WrapCode`、`InBaseSnapshot`/`UnwrapEntryPoint`、
      `shorebird_base_instructions_table_`、本次）。→ 直接催生任务 62。
- [x] 任务 62：🎉 **记账缺陷已修 —— 11 条断言被实测推翻，其中 5 条是「记成未做、其实早做完」**
      逐条复核 `CLAUDE.md` 的子系统表与符号计数表，**11 条断言作废**，每条都附了产生订正的那条命令：
      · 对象池聚合器「不是同一个算法」→ 三处分歧全关（`ab58e28152d` 是 HEAD 祖先，退出码 0）
      · 「判别实验未做」→ `make_op_fixture.py`(10.6K) + `op_aggregator_check.sh`(5.3K) 早在 `verify_all.sh` 里
      · **「`object_pool_editor` 仍未接进 `ImageWriter::Write`，是真依赖缺失」→ 已接进**
        （`image_snapshot.cc:622` 有 `ObjectPoolEditor::Edit`，提交 `66a46515eb5`）
      · 「`InstructionCountForLoadStoreFromOffset` 在 gen_snapshot 里 0 个」→ **2/2**
      · 「`Assembler::PadLoadStore` 我们 0 次」→ **2/2**
      · 「DD 机制我们仍为 0」→ 全部持平（方法名集合 diff 两向为空；IL pass `b13e2a0d54e` 是祖先）
      · 「16 个 stub 我们只声明了 2 个」→ **声明了 16 个**（`stub_code_list.h:159-172` 连续 14 条 + :84 + :195）
      · 「mappers / field_hasher 2/0」→ `FieldHash` **2/6**；`Mapper` 两边都 0 = **第四例口径陷阱**
      · 「`LinkedValue<T>` 我们没有」→ 有（`linker.{h,cc}` 各 7 处）
      · 「`LinkOracle` 我们为 0」→ 已实现 `94ee77c3624`（他们 0 / 我们 10，运行期类）
      · 「`print_shorebird_info` 的 gen_snapshot 半被阻塞」+「证据不足以实现聚合器」→ **两半都完成**
      仍然成立但**理由已作废**的一条：`rewritten` 列我们 0 / 他们 2 —— 事实对，
      但我们的 0 是 `linker.cc:1159` **硬编码的字面量**，不是缺 DD 子系统 → 已降级进 A 类。
      仍确认成立：`--disassemble` 是唯一未做的 analyze_snapshot flag；真机 A/B **零实测**
      （`xcodebuild/` 下只有 `ProductARM64`/`ReleaseARM64`，无任何 iOS 产物）；挂起池三条全准确。
      **「真实剩余面」三分清单已写进本文件末尾**：A 有证据可依 4 项 / B 无证据 5 项 / C 结构上不可关闭 4 项。
      判据：`verify_all.sh` 16 ran / 0 failed / 0 skipped / 0 blocked、`run_vm_tests` **157 passed**、
      `verify_reproduction.sh` 28 artifacts / 0 failures —— 本轮未改源码，**不变才是对的**。
      改动：`CLAUDE.md`(+36/-8)、`memo.md`(+69)，提交 `3cbcaf9`（仅显式路径，未推送）。
      ⚠️ **本轮自己差点栽进要修的那个坑**：`find` 与 `ls` 都报 `analyze_snapshot` 不存在，
      而 `test -f` 报存在（4483952 字节）。信了前者，`nm` 会给 0 行，
      于是 `SubgraphHasher`/`CascadeLimiter` 全被读成「我们 0」的假缺口 —— 正是这轮要消灭的那类错。
      → 已把「`nm` 出 0 行时先 `wc -l` 确认二进制真被读到」写进清单末尾。
      🔴 **遗留的投毒源**：`~/.claude/projects/…/memory/MEMORY.md`（普通文件，**不是**仓库内软链）
      仍带同一条已作废的聚合器断言，会在未来轮次重新投毒。本轮边界未授权改它 → 并进任务 63。
- [x] 任务 63：🎉 **`rewritten` / `sentinel_filled` 已接上真计数器；顺带发现 IL pass 的闸门写反了**
      A1 关闭。前提未被证伪 —— `rewritten=0` / `rewritten_null=0` 确实是 `linker.cc:1159` 的硬编码字面量，
      而 `sentinel_filled` 是 `slots.size() - retained`，**一个恰好在该 fixture 上正确的代理量，不是真计数**。
      改动：`~/dart-3122/sdk` 提交 `afa1f9c73cc`（3 文件 +117/-14）——
      `linker.h` 声明 `NoteDDSlotRewritten` / `DDSlotWasRewritten` / `ResetDDSlotRewrites`
      （**静态方法**：`sizeof(ShorebirdLinker)==0x88` 有 static_assert，我们自己的记账放不进对象里）；
      `linker.cc` 存储 + 四个计数器真实计算，并删掉「which needs the DD IL subsystem we do not have」那条过期注释；
      `aot_call_specializer.cc` 在改写点计数 + 新增 resolution 驱动的 slot 查找。
      判据①**逐字节**：`cmp out_dd/dd_resolution.tsv <ours>` → **exit 0**，`rewritten=2`、slot 3/4 各为 1，
      与他们的 `DD table: 8 slots, 7 retained, 2 rewritten, 1 unrewritten-null filled with sentinel` 全同；
      我们发射的间接调用点也落在同样的 slot 上（4,4,3），只差 Thread 位移 `0xf78` vs `0x978`（C1，结构性）。
      判据②**不倒退**：`verify_all.sh` **16 ran / 0 failed / 0 skipped / 0 blocked, exit 0**、
      `run_vm_tests` **157 passed**、`verify_reproduction.sh` **28 artifacts / 0 failures**。
      判据③**负控制**：把 `NoteDDSlotRewritten(slot)` 改成 `if (slot == 12345678) …`，
      同一轮 `ninja` **exit 0**（打了 `PATCH_OK`）后变红，且原因正是改坏的那处（`rewritten=0`、slot 3/4 归零，其余全同）；已还原。
      ⚠️ **RTK 包装的 `diff` 对这次负控制报了「✅ Files are identical」—— 假阴性**，
      `command cmp` 立刻给出 `differ: char 66, line 2`。又一次印证「RTK 包装不可信，一律加 `command` 前缀」。
      🔑 **计划外发现（已升级为 A5）**：找「真正的改写路径」时发现**旧代码的闸门写反了**。
      两次跑**他们的** gen_snapshot 数三指令间接序列：voters-only（无 DDSlotMapping 段）→ **3 个改写点**；
      mapping-only（一行，kernel_offset 54623 → slot 0）→ **0 个改写点**，而同样的字节**我们发射 73 个点**。
      → 驱动他们 IL pass 的是 **resolution，不是 DDSlotMapping**；旁证是他们 DWARF 里的
      `DDSlotResolution::owner_to_slot_`（+0x28）在我们树里此前**没有任何消费者**，而它正是反查表。
      本轮**保留** kernel_offset 路径并优先查它（生产配置行为不变、`dd_pass_check.sh` 仍绿），
      删掉它是另一件需要自己证据的事，已写进源码注释与 commit message，**没有静默修掉**。
      投毒源已清：`memory/MEMORY.md` 两份副本 + `project_dart_sdk_fork.md` 里那条已作废的聚合器断言，
      均已按实测结论改写并补上「2026-08-26 + `ab58e28152d`」。仓库侧提交 `0ab306a`。
      **两份副本仍是各自独立的普通文件**，未做软链、未合并、未删除任何一份。
- [ ] 任务 64：**A2 —— `object_pool_editor` 的两处计数分歧用了 `ASSERT`，release 构建里被编译掉** ⬅️ **当前任务**
      从 A 类清单取下一项。**这是个软点，不是缺口**：断言在 release 里整条消失，
      于是「计数器与发射器不一致」这件已知的事在生产构建里没有任何东西看着。
      判据：`command grep -n 'CountFollowsPrepareLargeOffset' ~/dart-3122/sdk/runtime/vm/shorebird/object_pool_editor_test.cc` → `:369`。
      两处已知分歧：kind-3 index 62 发射器用 2 而计数器说 3；kind-1/2 offset 2²⁴ 发射器用 3 而计数器说 2 ——
      **后者是我们自己读错了折叠 ladder**（recon 里在 2²⁴ 之后读成 3），属真 bug，要修计数器而不是改断言迁就它。
      要做的两件事：① 修 kind-1/2 在 2²⁴ 之后的计数；② 把两条断言收紧成 release 也在的形式。
      ⚠️ 前者是**行为改动**，`verify_reproduction.sh` 的 28 个产物最容易被它弄坏 —— 必须跑完再报。
      ⚠️ kind-3 index 62 那处**先别改**：它是发射器与计数器谁对还没定论的一处，
      改之前要有自己的证据（他们的 `ImageWriter::Write` 自带逐字节自校验，打印 `Expected:` / `Actual:`，那是可用的 oracle）。
      ⚠️ 判据必须有负控制，且**任何 `runtime/vm/` 下的负控制都要连 `gen_snapshot` 一起重建**，
      变红后**读失败信息本身**确认原因就是改坏的那处，不是 `Wrong full snapshot version`。
      ⚠️ **`diff` 一律用 `command cmp`** —— 任务 63 实测 RTK 包装的 `diff` 会对真实差异报「Files are identical」。

  <details><summary>任务 63 原始卡片</summary>

- [ ] 任务 63：**A1 —— `rewritten` / `sentinel_filled` 两列的硬编码字面量** ⬅️ **当前任务**
      从任务 62 产出的 A 类清单取第一项。**它不是缺子系统，是一行假数据**：
      `linker.cc:1159` 把 `rewritten` 硬编码成字面量，所以 `print_dd_resolution_to` 报 0 而他们报 2。
      任务 62 已把这条从「依赖 DD IL 子系统」降级 —— DD 全链路早已跑通（1043 函数 / 1622 处间接调用点）。
      要做的是找到真正的计数源并接上，让两 pass 的报告与他们**逐字节相同**。
      oracle：`./dd_pipeline.sh`（他们那侧打印 `2 rewritten`）。
      ⚠️ **顺手先清掉投毒源**（本轮**明确授权**）：
      `~/.claude/projects/-Users-Cruz-Documents-flutter-hot-patcher/memory/MEMORY.md`
      与仓库内 `memory/` 副本里那条已作废的「🔴 对象池 link-results 我们的算法不是他们的算法」，
      按任务 62 的实测结论改掉，并补上「实测日期 + 提交号」。
      ⚠️ 两份 memory 副本**已经漂移**（`project_dart_sdk_fork.md`、`feedback_false_green_traps.md` 都是），
      改的时候两份都要改，**不要自作主张做软链或删除任何一份** —— 那是不可逆操作，要停下来问人。
      ⚠️ 判据必须有负控制，且**任何 `runtime/vm/` 下的负控制都要连 `gen_snapshot` 一起重建**，
      变红后**读失败信息本身**确认原因就是改坏的那处，不是 `Wrong full snapshot version`。
      ⚠️ 别把「报告行数对上」当通过 —— 判据是与他们的产物**逐字节比对**。

      🛑 **2026-08-27 本轮未完成，循环已停摆 —— 原因是外部额度，不是技术问题。**
      子代理跑了约 10 分钟（25 次工具调用）后被杀，返回的是
      `You've hit your org's monthly spend limit`，没有任何技术结论。
      **停摆时的树状态已核实为干净**（这是被杀的子代理最危险的地方 —— 可能留下打了一半的负控制）：
      源码树 `~/dart-3122/sdk` HEAD 仍是 `c316526c1cb`、`git status` 干净；
      研究树 `~/Documents/fhp-research` HEAD `5a2931d`、干净。**没有需要还原的东西。**
      → 任务 63 **一件都没做**：`rewritten` 列仍是 `linker.cc:1159` 的硬编码字面量；
      两份 memory 副本里那条已作废的聚合器断言**仍在，仍会在下次投毒**。
      → 恢复额度后从本卡片原样重跑即可，前提条件没有任何变化。

  </details>


  <details><summary>任务 62 原始卡片</summary>

- 任务 62：🔴 **实测重建「还剩什么没做」—— 记账已四次生成假任务，这次把它当缺陷来修**
      任务 61 整轮白烧，原因不是技术难度，是 `CLAUDE.md` 子系统表里一段过期文字**长得像证据**
      （有地址、有反汇编偏移、有 🔴 标记），却没有任何可核对的日期/提交号。
      `CLAUDE.md` 自己写着「**完成度以实测为准，不凭记账**」，而它自身正是最大的那本账。
      本轮**不写新功能**，做三件事：
      ① **逐条复核**：`CLAUDE.md` 子系统表 + 符号计数表里所有「未做 / 缺口 / 我们为 0 / 仍是错的 /
      未验证 / 被阻塞」的断言，每条用当前 HEAD 实测复核（符号计数用 `nm -a | c++filt | sort -u` 双边同口径；
      「实现了没有」看代码与测试是不是真在跑，不看表里的字）。
      ② **凡是已作废的就地改掉**，并给**每一条**补上「实测日期 + 提交号」——
      此后没有这两样的断言一律视为不可引用。已知必改至少两处：对象池聚合器那段
      「他们的算法与我们的不是同一个」（`ab58e28152d` 已关闭）；「判别实验（他们的 fixture 做不到）：未做」
      （`make_op_fixture.py` + `op_aggregator_check.sh` 已在 `verify_all.sh` 里）。
      ③ **产出一份「真实剩余面」清单**写进 memo 末尾，按「有证据可依 / 无证据（需先反汇编）/
      结构上不可关闭」三分。后续任务从这份清单取，不再从 `CLAUDE.md` 的散文里取。
      ⚠️ **判据不能是「我读着改完了」**：每条订正必须附上产生它的那条命令与输出摘要
      （`git merge-base --is-ancestor <sha> HEAD`、`nm … | grep -c`、`ls` 到具体文件、测试名）。
      ⚠️ **别把「表里写着未做」当未做，反方向同样会翻车** —— `analyze_snapshot --shorebird` 曾被记成
      「已移植」而实际对我们自己的快照产出 0 个函数。
      ⚠️ 本轮**允许**改 `~/Documents/flutter_hot_patcher/CLAUDE.md` 与 `memo.md`（这正是任务本体），
      但仍**只用显式路径提交**，禁止 `add -A`。

  </details>

  <details><summary>任务 61 原始卡片（前提已被证伪，留档）</summary>

- 任务 61：🔴 **改正对象池 link-results 聚合器 —— 我们现在的算法是「已知错的」**
      这不是新面积，是**还债**：`CLAUDE.md` 已实测记载我们的实现与他们**不是同一个算法，
      只是在当前 fixture 上重合**。三处具体分歧，证据都在 `OP_AGGREGATOR_RECON.md`：
      ① **他们是加权投票**：排序元素类型 `pair<unsigned long,double>`（mangled name 直接给出），
      `fmov d8,#1.0`@`0x10019c0e8` / `fdiv d9,d8,d0`@`0x10019c858` /
      `ldr,fadd,str d0,[x0,#0x18]`@`0x10019ca50-58` ⇒ `votes_[a][b] += 1.0/N`。
      ② **他们没有「组恰好 1 个成员才配对」这道过滤** —— 全函数**零个 `cmp #0x60`**（=`sizeof(CodeInfo)`），
      而我们 `linker.cc:376-378` 正是靠它。
      ③ **`self_pp`(+0x30) 与 `subgraph_pp`(+0x48) 之间是 `csel` 条件选择**
      （`mov w8,#0x30; mov w9,#0x48; csel x8,x8,x9,ne`@`0x10019c818-20`，闸门 `[sp,#0x5c]` 的 `tst #0x1`），
      条件已由穷举解出：**base 侧该 `op_subgraph_hash` 分组为空 ⇒ flag=1 ⇒ 用 `self_pp`；
      分组还在 ⇒ 用 `subgraph_pp`**，且**按外层组黏住**。我们 `linker.cc:379-381` **无条件用 `self_pp`**。
      🔑 **任务 60 刚把这件事的前提坐实了**：`self_pp_indices` / `subgraph_pp_indices` 的语义已实测确定
      —— 它们是**同一趟 subgraph walk 的池引用，按顺序且带重复**（他们 base.so 上各 1380/1380；
      去重只有 1250/932，排序去重 1075/775；**1380 条里有 448 条确实重复了索引**，所以这个断言是可证伪的）。
      ⚠️ **判别实验必须自己造**：他们的 fixture 做不到 —— `base.ct` 与 `patch.ct` **逐字节相同**，
      且 `self_pp`/`subgraph_pp`/两者并集在它上面**都给 1121**，三个假设**判别不出**。
      要造一个**含 2 成员组、且 base 索引有争用**的合成 `ObjectPoolLinkInfo`。
      ⚠️ 别把「八行报告仍然相同」当通过 —— 那正是当前错算法能骗过的判据。
      ⚠️ 本轮起沿用任务 60 的新纪律：**任何 `runtime/vm/` 下的负控制都必须连 `gen_snapshot` 一起重建**，
      否则会拿到 `Wrong full snapshot version` 这种「对的退出码、错的原因」。

  </details>

  <details><summary>任务 60 原始卡片</summary>

- 任务 60：**`--dump_object_pool` / `--dump_object_pool_link_data` —— 阻塞刚被任务 59 解除**
      任务 17 把这两个 flag 记为「依赖缺失」，缺的就是 `op_subgraph_hash` 的生产方，**现在它有了**。
      `ObjectPoolLinkInfo::WriteToStream` 已实现且**逐字节验证过**（`26b5e5ed6c7`，`op_link_info_check.sh`）
      → 缺的一直是生产方不是格式。
      ⚠️ 判据必须是**解码→重编码→比字节**，不能只是「解析到 EOF」（少读+少写会互相抵消，任务已栽过）。
      ⚠️ 落笔前先确认这两个 flag 在他们的 `analyze_snapshot` 里**注册过**——
      任务 18 的 `--no_pp_hash` 就是「文档里有、他们拒绝接受」的死 flag，
      而 `strings | grep <flag>` **是坏判据**（`sdk_version` 阳性对照同样没有 bare-name 串），
      只能用行为测试（看错误是不是 `Unrecognized flags`）。
      顺手要还的账（就在本文件末尾）：`memory/project_dart_sdk_fork.md` 正文缺 2026-08-25 后半段；
      `CLAUDE.md` 里「`subgraph_hash`/`op_subgraph_hash` 仍是 `self_hash`、仍然是错的」
      与「`SubgraphHasher` 他们 12 / 我们 0」两条已被任务 59 作废，需订正。

  </details>

  <details><summary>任务 59 原始卡片（缺口描述，已全部关闭）</summary>

      两件都是任务 58 量出来的具体缺口，不是新方向：
      ① **`op_subgraph_hash` 842/1380**，路由已解、卡在**分类器**。差的就是任务 58 刻意没实现的那几条臂：
      `movz/movk` 寄存器偏移型池加载（`0x100197550`-`0x100197598`，走 `LoadStoreFromSingle`）、
      经 `x16` 的池加载臂、`Instr::ImmLogical()` 那条臂。**照他们的形状实现，别猜编号。**
      ② **`self_hash` 1185 → 1208/1380 的修法已经量出来了但没落地**：序数表要 walk-global 不是 per-function。
      → 落地它，并解释剩下的 172 个。
      ⚠️ 判据：**`subgraph_hash` 那条「比划分」在这里同样可能是空的** —— 先查真值划分是不是离散的
      （任务 58 的探针有这个断言，复用它），是离散就直接用摘要相等。
      ⚠️ `DDTableLinkInfo*` 的作用仍未知，别顺手编一个。
      🔑 **它的依赖刚刚被任务 57 解除**：`CascadeLimiter` 给 `SubgraphHasher` 的 walk 定界，
      而 `cascade_limiter.{h,cc}` 现在在树里了（`32582a15fb4`）。这两件本来就是同一块工作。
      符号实测（任务 18/38，在 **`analyze_snapshot`** 里量的，不是 `gen_snapshot`）：
      `SubgraphHasher` **他们 12 / 我们 0**、`CascadeLimiter` 他们 18 / 我们 0（后者现已落地）。
      已有的地基（别重做）：任务 20 解出 SHA-1 框架
      `self_hash = SHA1(对每个 Entry: le32(e.first) ‖ le32(e.second))`、`sizeof(Entry)==8`、标准 IV 无自定义种子；
      任务 21 从他们字符串表拿到十个 entry kind 名字（`CodeName`/`RawInstructionBits`/
      `OffsetFromPayloadStart`/`ObjectPoolLoadIndex`/`DispatchTableCall`/`IndirectStaticCall`/
      `FieldTableLoadIndex`/`ExternalBranchTargetIndex`/`LocalBranch`/`Unknown`），**编号刻意没猜**；
      任务 37 把 `self_hash` 真算法进树。
      → 缺的是**把 walk 从单函数扩到 subgraph**，产出 `subgraph_hash` / `op_subgraph_hash`。
      ⚠️ **现状是错的且必须明说**：`analyze_snapshot --shorebird` 里 `subgraph_hash` 与
      `op_subgraph_hash` **目前就是 `self_hash`**，是已知的错数据（CLAUDE.md 有记）。
      解锁面：任务 17 记的 `--dump_object_pool` / `--dump_object_pool_link_data` 都卡在 `op_subgraph_hash`
      （`ObjectPoolLinkInfo::WriteToStream` 已实现且逐字节验证过 → **缺的是生产方不是格式**）。
      ⚠️ 判据要用任务 19 那条方法论：**比「划分」不比「摘要」** ——
      「这两个函数 hash 相同」与框架无关、照样可观测，①-④ 全靠它才够得到。
      ⚠️ 别再用成员分那类非判别判据（任务 56：9 变异 3 假绿）。

  </details>

## ⏳ 挂起池（连续失败 3 次的顽固 Bug）

- **跨实现读快照**（非 Bug，是**结构性不可达**，2026-08-25 双向实测）：
  他们的 `analyze_snapshot` 读我们的快照、我们的读他们的，都报
  `Wrong full snapshot version`（`839937dd…` vs `7150a2e8…`）。
  → **任何「把两边的快照内容直接对比」的判据都走不通**，
  只能像任务 16 那样从**反汇编**取共同可观测量。**不要再试。**
- **真机 A/B 验证**（2026-08-26 **部分解除**）：人类报告 **iOS 真机已连上、随时可测**，
  所以「没有设备」这条前提消失了。**但阻塞并没有消失，只是换了位置**：
  我们这边**还没有任何 iOS 产物**——所有跑通的东西（DD 全链路、wrapper、patch 加载入口）
  都是 host 的 `dart_force_simulator` 构建，C1-C7 不在任何产物里。
  → **真正缺的是「用我们的 dart-sdk 构建 iOS 引擎」这一步**，不是设备。
  在那之前，真机上能测的只有已经 PASS 过的 Route-B 产品线（Shorebird 预编译引擎 + 我们的 `.vmcode`），
  那条**不检验主任务**。**下一步要由人类决定：是插入 iOS 引擎构建任务，还是先复验 Route-B 回归。**
- **`GetBestMapping` 的不可破平票**（非 Bug，是**结构性不可达**）：已实测他们 `14/8/0/120`、
  我们 `14/13/0/115`。我们的顺序由 libc++ 的「空桶则压到链表头」决定（实测恒为「后插入者在前」），
  他们的随 key 变化 → 跟的是我们复现不出的桶布局。**匹配它需要两个容器有相同的桶宽历史，
  也就是需要两个 VM 完全一致** —— 与堆遍历序、field_table 组内序同一类，CLAUDE.md 已列为不可关闭。
  ⚠️ 已试过「把 vote map 改成按值拷贝」（他们 `0x10019ce88` 确实有这个拷贝）→ **数字一字未变**。
  拷贝保留了（照他们的样子），但注释已写明它没有解决问题。**三次尝试后停手，不要再试。**

---

# ⚙️ 环境与判据（每轮必读，别凭记忆）

## 三个工作树，别搞混

| 路径 | 分支 | 用途 |
|---|---|---|
| `~/Documents/flutter_hot_patcher` | `v1` | **本文件所在地**；生产分支 + `CLAUDE.md` + `memory/` |
| `~/dart-3122/sdk` | `shorebird-3.12.2` | **代码改动全部在这里**；主任务工作树 |
| `~/Documents/fhp-research` | `route-a-research` | 验证脚本 + 反汇编侦察文档；**他们的二进制永不入库** |

## ❗ `npm run build` / `npm run test` 在本项目**不存在**

这是 Dart SDK（C++/GN/ninja），不是 Node 项目。/loop 指令里那两条命令是模板默认值，
**照跑必然失败**。真实等价物：

```sh
# build（两个配置都要，Release 跑单测，Product 跑逐字节复现）
ninja -C ~/dart-3122/sdk/xcodebuild/ReleaseARM64 gen_snapshot run_vm_tests dartaotruntime
ninja -C ~/dart-3122/sdk/xcodebuild/ProductARM64 gen_snapshot dartaotruntime

# test（唯一权威判据，6 项检查 + 单测）
cd ~/Documents/fhp-research/spikes/shorebird_linkinfo_oracle && ./verify_all.sh
```

**新增单测后必须同步抬高 `verify_all.sh` 里的 `EXPECTED_TESTS`**，否则新测试不被
名字正则选中时连 SKIPPED 都不会打印（已踩两次）。

## 📊 基线（2026-08-25 实测，非记账）

```
verify_reproduction.sh     checked 28 artifact(s), 0 failure(s)
dd_pass_check.sh           0 failure(s)
dd_runtime_check.sh        0 failure(s)
op_link_info_check.sh      0 failure(s)
shorebird_info_check.sh    0 failure(s)
op_aggregator_check.sh     0 failure(s)
op_rewrite_check.sh        0 failure(s)
op_real_mapping_check.sh   0 failure(s)
analyze_snapshot_help_check.sh 0 failure(s)
class_table_dump_check.sh  0 failure(s)
dd_selection_check.sh      all checks passed
introsort_order_check.sh   EXACT MATCH (1380/1380), 17/17
dd_table_check.sh          exit 0（--self-test: 11 of 17 budgets went red）
subgraph_hash_check.sh     1380/1380 theirs, 1589/1589 ours
run_vm_tests               154 passed
15 ran, 0 failed, 0 skipped, 0 blocked
```
⚠️ 上一版记的是 14 项。**15 项是任务 58 加了 `subgraph_hash_check.sh`；`run_vm_tests` 停在 154
是因为任务 58 没加单测**（它改的是 `analyze_snapshot_api_impl.cc`，判据走 `subgraph_hash_check.sh`）。
**数字变了要能说出为什么，数字没变也要能说出为什么。**
⚠️ 任务 58 中途有一次 `verify_all` 用的是**陈旧的 Product 二进制**，重建后才重跑 ——
Product 那半不在默认 ninja 目标里，`analyze_snapshot` 只在 ReleaseARM64 里建。
工作树 clean。HEAD：`8766b1f9e7b`（dart-sdk，任务 46；上一版记的 `734abc41d10` 已过期）
/ fhp-research 见本轮提交。
`analyze_snapshot` help 缺口：**4 个 flag**（任务 17 是 6、任务 18 是 5）。
⚠️ `verify_reproduction` 从 24 涨到 28 是因为任务 14 的 `insert.*` 进了 `out_dd`，
不是新写了什么 —— **数字变了要能说出为什么**。
✅ **`op_rewrite_check` 的 BLOCKED 已解除**（任务 13 让补齐回到树上，编辑器重新活了）。

**补齐现在是开着的**，所以每个 AOT 快照都比以前大：
`gen_kernel_aot.dart.snapshot` 13.2M → 14.1M；hello.dart 的 AOT 产物
NOP 数 0 → **4584**（他们同一程序 4598）。
⚠️ **重建 `copy_gen_kernel_snapshot` 是必须的**，否则 kernel 编译会撞版本串不匹配
（`product ... but the VM has release ...` = 你在拿 Release 的 dartaotruntime
跑 Product 的快照，两个配置两套产物）。


## 📊 私有子系统符号实测（2026-08-25 **第二次**，任务 38）

`nm -a | c++filt | sort -u` 双边同口径（他们先 `lipo -thin arm64`，我们 `--mode=product`）。
唯一符号数：他们 gen_snapshot **32373** / 我们 **34067**（上次 34055）；
他们 analyze_snapshot **17194** / 我们 **23851**。
**只有「一侧为 0」是有意义的判据**——我们计数更高不代表进展（我们未 strip）。

🔴 **这次最重要的结构性改动：表里加了 analyze_snapshot 那一列。**
上一版只量 `gen_snapshot`，于是把住在 analyze_snapshot 里的子系统全记成了
「两边都 0 的口径陷阱」。**换个产物量，缺口就现形了。**

| 标志符号 | 他们 gs | 我们 gs | 他们 as | 我们 as | 判读 |
|---|---:|---:|---:|---:|---|
| `ShorebirdLinker::` | 20 | 38 | 0 | 0 | ✅ |
| `ObjectPoolMappings` | 8 | 10 | 0 | 0 | ✅ |
| `LinkedValue` | 4 | 12 | 0 | 0 | ✅ |
| `ObjectPoolEditor` | 2 | 4 | 0 | 0 | ✅ |
| `FieldHasher` | 2 | **6** | 0 | 0 | ✅（上次 2/2）|
| `DDTableBuilder` | 8 | 8 | 0 | 0 | 持平 |
| `DDSlotMapping::` | 2 | 2 | 0 | 0 | 持平 |
| `DDSlotVoters` | 6 | 10 | 2 | 0 | ✅ gs 侧有；as 侧他们只有一个 `kVersion` 常量 |
| `IndirectStaticCallInstr::` | 42 | 32 | 0 | 0 | ⚠️ 原始行数受 strip 影响，**不可直接比**（任务 10 已按去重方法名集合结案）|
| `LinkOracle` | 0 | 10 | 16 | **16** | ✅ **as 侧持平** |
| **`SubgraphHasher`** | 0 | 0 | **12** | **0** | 🔴 **真实缺口**（任务 18 发现，仍在）|
| **`CascadeLimiter`** | 0 | 0 | **18** | **0** | 🔴 **真实缺口，本轮首次量到**（`dart::CascadeLimiter::Run` + `CascadeLimiterEntry`）|
| `ClassTableMapper` | 0 | 0 | 0 | 0 | ⚠️ 口径陷阱：我们的映射器已实现，只是不叫这个名字 |
| `sha1_` | 0 | 0 | 2 | 0 | ⚠️ **口径陷阱，已查证**：我们有 `FhpSHA1Transform`（2 个符号），只是名字不同 |
| `WrapperAllocator` | 34 | 4 | 36 | 12 | ⚠️ **这一行不可用**（32/34 是 `std::function` 样板，其余方法全被内联）|

→ **真实的「一侧为 0」缺口只剩两个，都在 `analyze_snapshot` 里：
`SubgraphHasher` 与 `CascadeLimiter`。** 两者是同一块（后者给前者的 walk 定界）。

✅ **本轮的方法教训**：`sha1_` 那一行差点被记成第三个缺口。
**查一下才知道我们有同功能的 `FhpSHA1Transform`**——
**「一侧为 0」是必要条件不是充分条件，名字对不上也会给 0。**

## 🚨 验证纪律（本仓库的血泪，违反必出假绿）

1. **改完必须改坏看变红**。全绿只证明「没弄坏」，不证明「新代码被执行过」。
   每个任务的负控制写在任务卡里，**跑完要还原**。
2. **`ninja` 说 `no work to do` 才算构建新鲜**。时间戳会被 `mv .bak` 还原弄倒退。
3. **改 `#if defined(DART_PRECOMPILED_RUNTIME)` 里的代码必须用 `dartaotruntime` 验**，
   `run_vm_tests` 根本不编译那些块。
4. **`ASSERT` 在 release 构建里被编译掉**。要在 product 里守住的用 `RELEASE_ASSERT`。
5. **RTK 包装不可信**：`grep` / `git log` / `diff` 一律加 `command` 前缀。
6. **说某函数「已实现」之前 `grep -rn '<类名::方法名>' runtime/` 一次**。
   只搜方法名会把调用关系两端的两个函数并成一行（已发生过）。
7. **oracle 的两个输入可能是同一份文件**。用之前 `cmp` 一下。

## 🔁 /clear 的实际形态

`/clear` **不是我能调用的工具**。本循环靠 `ScheduleWakeup` 重新进入 `/loop` 协议，
上下文由 harness 自动压缩。**效果等价：每轮醒来先读本文件。**
所以本文件必须自足——**任何跨轮次的结论都要写进这里，不能只留在对话里**。

---

# 📌 任务卡（含验收判据与负控制）

## ✅ 任务 1+2 已完成（`ab58e28152d`）——但**判据是弱的，别读成已验证**

实现了 `ObjectPoolMappingsAggregator`（`votes_` + `used_` + `GetBestMapping`）替换掉
原先靠「组恰好 1 成员」过滤的配对，并把索引向量改成 sticky 条件选择。

**⚠️ `shorebird_info_check.sh` 八行仍全同，但这不是证据。**
在「每个匹配组都 1:1、每个索引对都是双射」的 fixture 上，每个内层投票表只有一个候选、
贪心永不拒绝 —— **投票与旧过滤必然给出同一答案**。所以任务 3 不是锦上添花，
它是唯一能判定这份实现对错的东西。

### 🔴 本轮学到的（第 20 种假绿）：**负控制可能测不到它想测的东西**

按计划做的第一个负控制是「把权重 `1.0/N` 改成常数 1.0」→ **全绿**。
原因不是测试弱，是**权重公式当时零覆盖**：`AddVote` 系列直接传权重进去，
link-results 系列每个键只有一个候选。

更深一层：score 与事件数**通常同向变化**——一个组贡献 `|base|×|patch|` 次
权重 `1/(|base|+|patch|)` 的投票，所以 `score = count/(b+p)`，大组一般两边都赢。
要让除数可观测，必须**刻意挑一对让两者判断相反的组**：

```
组 A：2 base × 2 patch = 4 次事件，权重 1/4 → 1.000   ← 加权时赢
组 B：1 base × 5 patch = 5 次事件，权重 1/6 → 0.833   ← 数事件时赢
```
→ 新增 `ObjectPoolLinkResults_WeightIsNormalisedByGroupSize`，此后负控制 1 才会红。

✅ **判据**：负控制不红时，先问「这一行改动在现有测试的定义域里语义真的变了吗」，
而不是先怀疑测试太弱。第 19 种（负控制是恒等变换）与这一种是同一族病。

### 四个负控制的实测结果（全部还原）

| 负控制 | 红的测试数 |
|---|---|
| 权重 `1.0/N` → 常数 `1.0` | 1 |
| 删掉 `used_` 单射检查 | 2 |
| 平票 `a.first == key` → `!=` | 2 |
| 索引向量无条件用 `self_pp` | 2 |

### 三处刻意偏离（都已在代码注释里标注）

1. 他们内层循环界是 `max(patch.size(), 1)` 且**同时索引两个向量** → base 更短或 patch 为空时越界读。
   我们按较短者取界。**为了保真去复刻一个内存越界，是拿真 bug 换一个我们根本观测不到的一致性。**
2. 他们的第四张 `groupBy(patch, self_hash_)` 建了从不读 → 我们不建。
3. 他们的比较器按引用捕获 key，我们按值 —— 无可观测差异。

## ✅ 任务 3 已完成（`9d5fb26`）——聚合器现在是**验证过的**，不再是转写的

`spikes/shorebird_linkinfo_oracle/make_op_fixture.py` + `op_aggregator_check.sh`
（已进 `verify_all.sh`，现在是 7 项检查）。

**设计上的核心约束**：报告只有四个数字，所以**只改变映射目标的错误是观测不到的**。
每个组都被设计成把一种具体错误变成一个**计数**差异：

| 组 | base×patch | 抓什么 |
|---|---|---|
| S2 | 2×2 | 歧义组被丢弃而非投票 |
| CONTEST | 2×2 | 全局单射（第二个 patch 索引必须拿到 -1） |
| FALLBACK | 1×1 | `self_hash_` 回落 + 索引向量切换 |
| SG | 1×1 | base 组存在时用 `subgraph_pp` |
| W1+W2 | 2×2, 1×5 | **权重除数** |

**W1/W2 是最不显然的一对**：两组都投 patch 索引 80，W1 得 `4×1/4 = 1.000`、
W2 得 `5×1/6 = 0.833` → 加权选 W1、数事件选 W2。而 W1 的 base 索引是 **5**、W2 的是 **82**，
**只有后者过得了 stage 1 的 `>=8` 闸门** —— 这才把「换了个映射目标」变成「line 2 变了」。

**实测结果**：
```
他们的 gen_snapshot：8 / 7 / 0 / 121   ← 与我从反汇编手推的一致
我们的            ：8 / 7 / 0 / 121   ← 逐行相同
常数权重          ：8 / 8 / 0 / 120
无条件 self_pp    ：7 / 6 / 0 / 122
size==1 过滤      ：4 / 4 / 0 / 124
```

### 🔴 写 harness 时踩的两个坑（都记下来）

1. **他们的 `gen_snapshot` 会打 `Out of memory`**（zone.cc:96）——报告在链接器初始化时打，
   OOM 在之后写快照时发生。**偶发地会把报告输出一起吞掉** → harness 必须重试，
   否则会把 flake 读成「他们没输出」。
2. **我的第一版 self-test 扰动不是扰动**：把 `synth_base.op` 同时当 base 和 patch，
   报出来**还是 8/7/0/121** —— 因为每组都恒等配对，而闸门下那个 base 索引仍是 5。
   **它长得像一个通过的 self-test，实际什么都没比。**
   现在改用「删掉 W1 组的 base」，已知会给 8/8/0/120。
   → 这是[[feedback-false-green-traps]]第 18 种（两个输入相同）在 self-test 上的变体。

## 任务 4：`LinkedValue<T>`

由两处 `vector::size()` 的除法常数算出 = base/patch 对：
类表 112 vs `sizeof(ClassInfo)`=56、对象池 16 vs `sizeof(uword)`=8，两个独立来源都恰好双倍。
`nm` 给出实例 `vector<LinkedValue<ClassInfo>>` / `vector<LinkedValue<unsigned long>>`。
元素序 `{base, patch}` 由 `mapping[second] = first` 证明。

## ❌ 任务 5：**已核实为非缺陷，关闭**（2026-08-25 实测）

原任务卡的三条，逐条查证的结果：

1. ~~「两条断言用了 `ASSERT` 而非 `RELEASE_ASSERT` → release 被编译掉」~~ **前提错误**。
   钉住那两处分歧的是 `ObjectPoolEditor_CountFollowsPrepareLargeOffset` 里的
   **`EXPECT_EQ`**，而 `EXPECT` 系列是无条件的 `dart::Expect(...)` 调用
   （`platform/assert.h:358`），**不是 `ASSERT`，release 下不会被编译掉**。
   我此前把「测试里的断言」与「`PadLoadStore` 里的 `ASSERT`」混为一谈了。
2. `PadLoadStore` 里确实有两个 `ASSERT`，但 `assembler_arm64.cc:1077-1081`
   **已经写明了为什么刻意不用 `RELEASE_ASSERT`**：那个等式在本树里不成立，
   「一个已知为假的检查比没有检查更糟」。**这是已论证的决定，不是待办。**
3. kind-1/2 在 2²⁴ 的计数分歧：`OBJECT_POOL_EDITOR_RECON.md:404` 明确指示
   **「不要重新推导那个内联 ladder；六种 kind 全部调用我们已有的
   `InstructionCountForLoadStoreFromOffset`，常量折叠是编译器产物」**。
   我们当前实现正是如此。

⚠️ **仍然成立的一个真实分歧，但不可达**：他们内联的 ladder 在 offset `2²⁴` 给 3，
我们测量 `PrepareLargeOffset` 得 2 → 该处我们的编辑器会**拒绝**改写而不是改写它。
后果是安全的（自检拦下），且 offset 2²⁴ 需要 **2097150 条 pool 条目（16MB 对象池）**，
真实 app 差几个数量级。**记为已知、已被测试钉住、不可达的偏差，不追。**

✅ **方法论**：任务卡上的「待修项」在动手前要先核实前提。这一条的三项里有两项
是我自己早先记错，如果照着改会**引入**问题（把一个已知为假的断言升级成 release 断言）。

## 任务 6：接进 `ImageWriter::Write`

### ✅ 6a 已完成（`eb17b43924d`）：补齐是**没被记下来的真依赖**

memo 原来把任务 6 的依赖只写成「mapping 表所有者未定」。动手才发现**还有第二个**：
`PadLoadStore` 自 `f426f46f5b0` 落地起就**只有 `AssembleReplacement` 和测试在调**，
19 个上游发射器一个都没走它 → **我们的 AOT 快照根本没补齐**，
而编辑器的前提是每个 PP 相对访问占固定 3 条指令的足迹。没有补齐，
`Edit()` 会拒绝每一个站点，`ImageWriter::Write` 挂上去也无事可做。

**动手前先验证前提**（同一程序同一逻辑站点）：
```
他们  ldr x4, [x27, #0x48] ; nop ; nop
我们  ldr x4, [x27, #0x48] ; str x0, [x15, #-0x8]!
```
全快照 NOP 计数：他们 4598、我们 **0** → 改动后我们 **4636**。

### 🔴 6a 踩到的架构问题：`LoadWordFromPoolIndex` **JIT 也在用**

无条件补齐 → `IL_IndirectStaticCall_SerializationRoundTrip` 与
`IsolateReload_ShapeChange_Const_AddSlot` **在 unoptimized 代码里崩溃**。
原因：`InstructionPattern::Decode*FromPool` 会**反向**解析这些序列
（`LoadDoubleWordFromPoolIndex` 的注释就写着必须与它同步），补齐破坏了它们的假设。

→ 加了 `FLAG_precompiled_mode` 门控。⚠️**这个门控是我们的，不是他们的**：
补齐只服务于「编辑器 renumber 而不移动代码」，那只对 AOT 快照有意义；
而他们的 `gen_snapshot` 是 precompiler-only，**他们的 JIT 构建补不补齐无从观测**。
门控放在**三个调用点**而不是 `PadLoadStore` 内部，这样测试里刻意构造补齐 fixture
的直接调用仍然有效。

### ✅ 6b/6c 已完成（`66a46515eb5`）

**6b**：`gap1_`（+0x28，原注「类型未知，无任何已测函数访问」）就是 `object_pool_mapping_`。
`InitializeWithObjectPoolLinkInfo` 现在保存 `LinkObjectPools` 的结果而不是丢弃它。
`sizeof==0x88` 的 static_assert 确认该槽被正好填满。

**6c**：`ImageWriter::Write` 在 `WriteText` **之前**遍历每个非 trampoline 的
Instructions payload。位置是被迫的 —— 编辑是原地的，必须趁字节还在编译器手里。

**实测（临时插桩，因为「构建通过」和「没报错」与「根本没跑」是同一种输出）**：
```
带 link data ：187 payload + 1589 payload，检测到 2324 个站点，ok=1
不带 link data：无 mapping，钩子静默
```
→ **自校验路径在 2324 个真实站点上跑通**。这是他们那个免费 oracle：
拿本编辑器的解码器与发射器，去对照同一批发射器在编译期产出的代码。
**这是 `object_pool_editor.cc` 至今最强的证据。**

⚠️ **改写路径生产零覆盖**：`nonidentity=0` —— 本 fixture 的 base 与 patch 是近乎相同的程序，
1421 项全部映射到自身。改写只有单测覆盖。

### 🔴 第一个负控制是恒等变换（第 19 种陷阱再次命中）

反转 `AssembleReplacement` 的 kind-1 分支 → **什么都没变**。
因为对 `ldr xN,[PP,#imm]`，`LoadFromOffset` 与 `LoadWordFromPoolIndex`
**发射的是同一条指令**，两条臂在常见情形下一致。
改成「拿 `op.index + 1` 去做自校验」才真正移动了字节 →
`Expected:` / `Actual:` 触发、两个镜像 `ok` 都变 false。

### 🔑（原记录）6b 的地址证据

recon (c)5 记的是 `[[0x100521xxx + 0x4b0] + 0x28]` → `[x8]` → `x8[index]`，当时判为「未确定」。
但 `linker.cc` 的注释里记着**他们的 ShorebirdLinker 单例指针就在 `0x1005214b0`** —— 两处是同一个地址。
→ **mapping 表 = `ShorebirdLinker + 0x28`**，也就是我们 `linker.h` 里标着
「8-byte gap，无任何已测函数访问」的那个槽。两次解引用（`[x8]` 再 `x8[index]`）
说明它是个指向「首字段为数组基址」的对象的指针，与 `vector<intptr_t>*` 一致。

### 6c：`ImageWriter::Write` 里的 walk

完整重构见 `OBJECT_POOL_EDITOR_RECON.md:535-590`。`Edit()` 已经实现了整个 walk，
缺的只是调用点。🎁 **他们自带 oracle**：索引未变时会重新汇编并逐字节自校验，
打印 `"Expected:\n"` / `"Actual:\n"`（两串在二进制里各恰好 1 次，已验）。



---


## ✅ 任务 7 已完成（`ecd1e5b5b20`）：`field_hasher.cc`

**盘点方式本身是重点**：不看记账，直接两边符号表对拍。结果只剩 `FieldHasher` 一个真零。

我们**早就在产这些 hash**（内容与他们逐条相同），缺的是**形状**——而形状恰恰有内容：
他们的签名 `DuplicateAwareHash(const Field&)` **只收一个 Field 却要去重**，
所以出现次数不可能是参数，**必须是状态** → 这就是它是对象而不是自由函数的原因。

⚠️ **成员还是函数内静态，从符号判不出来**（静态方法与非静态方法在这里 demangle 相同）。
选了成员，因为可测；而函数内静态会把计数带到同进程的下一次 dump——**那种 bug 只在第二次 dump 才现形**。

### 🔴 本轮又踩陈旧二进制，且差一步就得出错误结论

负控制（把后缀从「重复」改成「递增」）跑完，`verify_reproduction.sh` 报 **24/24 通过**。
差点写下「字节 oracle 覆盖不到 field hash」。真相是：那个检查用的是
**`ProductARM64/gen_snapshot`，而我只重建了 Release**。重建 Product 后立刻变成 **6 failures**。
✅ **判据**：负控制不红时，先确认**被那个检查实际执行的那个二进制**是新的，
而不是「我刚才 build 过」——两个配置是两个二进制。


## ✅ 任务 8 已完成（`041fe7f24a3` + spike `c958c6f`）：改写路径**第一次跑就崩了**

`ImageWriter::Write` 挂上之后，自校验路径在 2324 个站点上全过 —— 但 `nonidentity=0`，
**改写分支一次都没执行过**。给它一个非恒等映射（base 索引整体 +1）后，
第一次 memcpy 就是 **`Bus error: BUS_ADRALN`**：指令 payload 在**代码页**上，而代码页是写保护的。
在此之前编辑器只读不写，所以这个 bug 一直藏着。

修法：`WritableCodePages` 作用域。`CodeRelocator::Relocate` 同样原地改写指令、
同样需要它、连 isolate group 的选法都一样（`app_snapshot.cc:157`）。
⚠️ 他们有没有等价作用域**不可观测** —— recon 显示的是裸 memcpy，但 StackResource 会被内联掉。

**判据不是「没崩」，是「改到哪去了」**：`mapping[i]=i+1` 要求每个 PP 相对偏移移动 8 字节。
改写后的偏移分布距「基线平移一槽」**58**，距「基线原样」**2440**。

### 🔴 判据换过一次，第一版有碰撞底噪

第一版数「逐个移动了的站点」→ 恒等映射也能拿到 **797/2318**，
因为这个规模的快照里本来就有大量偏移的「上一槽邻居」同时存在。
改成比较**整个偏移分布的距离**就没有这个底噪：
改写时 `58 vs 2440`，恒等时 `2494 vs 0`，两个假设干净地互换。

✅ **这条是单测买不到的**：改写分支自 `f426f46f5b0` 就有单测，且全程全绿。


## ✅ 任务 9 已完结（`ead5f153d8d` + spike `3277b35`）：分歧已测出，任务转入挂起池

recon §(c)4 原记「未确定、零覆盖」。**现在不再是未确定的了。**

**怎么让它变得可观测**：四行报告是唯一的观测面，而平票只改变「选了哪个候选」，
本来看不见。做法是让两个候选**一个在 stage 1 的 `>=8` 闸门之下、一个之上** ——
于是每个平票的结果都会让 `Mappings from Link Results` 动 1。六个独立平票 = 六比特指纹。

```
他们  14 / 8  / 0 / 120     ≥8 的候选赢了 1 次
我们  14 / 13 / 0 / 115     赢了 6 次
```

**是量出来的不是推出来的**：插桩打印候选顺序，我们对那些 key 恒为
`(91,1) (93,2) (95,3) …` —— **后插入者在前**，即 libc++「空桶则压到链表头」的表现。
他们的随 key 变化 → 跟的是桶布局。

⚠️ **试过的修法（失败，已记录）**：把 vote map 从引用改成**按值拷贝**
（他们 `0x10019ce88..0x10019d1fc` 确实有这个拷贝）→ **数字一字未变**。
拷贝保留了（照他们的样子更忠实），但注释已写明它没解决问题。

→ 三次尝试后按防死循环规则停手。单测
`ObjectPoolAggregator_UnbreakableTieTakesTheLaterInsertion` 钉住**我们这一侧**，
注释里写明「钉的是已知与他们不同的行为，不是被认为正确的行为」。

### 🔴 顺带修了 harness：3 次重试不够

`op_aggregator_check.sh` 本轮真的因 flake 失败了。实测他们的二进制**约一半概率**才吐出报告
（`zone.cc` 的 OOM 是真间歇性的），3 次重试仍有 1/8 失败率 → 改成 10 次。
**实测确认输出路径不是原因**：`/dev/null` 与真实文件 flake 率相同（3/5 vs 2/5）。


## 🔴🔴 本轮最重要的事：我在任务 6a 引入了一个回归，被一个陈旧文件掩盖了整个会话

### 假绿本体：`dd_runtime_check` 一直在用**昨天的 kernel**

它把 `app.dill` 写进**持久目录** `out_ddrun/`，然后用 `[ -s app.dill ]` 当判据。
自从 `dartaotruntime` 被重建而 `gen_kernel_aot.dart.snapshot` 没跟着重建之后，
kernel 编译就一直失败（`Wrong full snapshot version`），而这个检查**一直通过** ——
命中的是**前一天**留下的 dill。整个会话的绿都没编译任何东西。

✅ 修法：先 `rm -f`，再检查**编译器自己的退出状态**，并在版本不匹配时打印该重建什么。

### 修完立刻暴露出真问题：补齐让 `gen_kernel` 段错误

`gen_kernel_aot.dart.snapshot` 是**我们自己的 gen_snapshot** 产出的。
带补齐重建 → 启动即 `SEGV_ACCERR`（无栈）。关掉补齐重建 → 正常编译出 4.4MB dill。
**一行开关的 A/B，所以补齐就是原因。**

**机制**：补齐与**固定距离的反向读取**不兼容。
`instructions_arm64.cc:32` 的 `DecodeLoadWordFromPool(pc - 2 * Instr::kInstrSize, ...)`
假定池加载正好结束在调用前 2 条指令处；插入 NOP 就把它推开了。
`:47` 的 `DecodeLoadDoubleWordFromPool` 同理 —— kind 1 和 kind 3，两个最常用的发射器。

### ⚠️ 但结论**不是**「补齐是错的」

实测他们自己的快照：**2299 个 PP 加载全部跟着 `nop,now`**，无一例外，**包括调用序列内部**。
→ **他们的反向解析能处理补齐**，所以修法在解码器那边，不在路由那边。
我当时「也许 narrow 一下就行」的猜测**被这个计数证伪了**。

### 为什么选择回退而不是继续修

一棵编译不出 kernel 的树不能留过夜。回退后编辑器重新惰化，
`op_rewrite_check.sh` 因此报 **BLOCKED**（不是 pass 也不是 fail）。

✅ **可复用规则（第 21 种假绿）**：**把中间产物写进持久目录 + 用「文件存在」当判据 = 定时炸弹。**
判据必须是**产生它的那一步的退出状态**。
✅ **第二条**：**小程序全过不等于能用。** hello.dart 规模的快照一切正常，
gen_kernel 规模的段错误。**规模本身就是一个未被覆盖的维度。**


## ✅ 任务 13 已完成（`d99ff81f8e7` + spike `d21d04d`）：修法就在上一轮猜的地方

上一轮回退时写下的判断是对的，而且**是那个计数救的**：他们快照里 2299 个 PP 加载
无一例外跟着 `nop,nop`（含调用序列内部）→ 他们改的是反向解析，不是路由。
照着这条做，一次就中。

### 一个函数覆盖八个调用点

`SkipBackOverObjectPoolLoadPadding` 加在三个解码入口
（`DecodeLoadWordFromPool` / `DecodeLoadDoubleWordFromPool` / `DecodeLoadWordImmediate`），
**八个调用点一个都没动**。原因是它们全都传「补齐之后那个地址」而不是「load 的地址」：
`CallPattern` 的 `pc - 2 * Instr::kInstrSize` 指的是 `Call()` 发的那条 `ldr`，
补齐插在它和池加载之间，所以只要解码器自己往回跳过 NOP 就够了。

⚠️ **`DecodeLoadWordImmediate` 要跳两次**：一次在开头（裸池加载），
一次在 `orri` 之后 —— 补齐在 load 与 orri **之间**，不在 orri 后面。
只加开头那次会让 odd-value 那条路静默走进 case 3 的断言。

### 常量放哪：AOT 运行期编译不到编译器头文件

`kObjectPoolLoadStoreMinInstructionCount` 在 `assembler_arm64.h`，
而 `instructions_arm64.cc` 要进 `dartaotruntime`（不 build 编译器）。
→ 在 `constants_arm64.h` 的 `Instr` 里复述成
`kMaxObjectPoolLoadPaddingInstructions`，并在 `assembler_arm64.h` 里
`static_assert` 把两个数钉在一起。**复述必须带编译期的绳子，否则就是等着漂移。**

### 门控留着，但理由换了（旧注释已作废）

`FLAG_precompiled_mode` 那道闸门**不再是正确性所必需**。旧注释说「JIT 下补齐会崩，
`IL_IndirectStaticCall_SerializationRoundTrip` 与 `IsolateReload_ShapeChange_Const_AddSlot`
为证」—— 那两条现在带补齐也过。闸门保留的真实理由只剩「JIT 永远不 renumber 池，
补它就是每个池访问白付两个字」。**注释已改写；活得比工作久的注释本轮又抓到一条。**

### 🔴 两个负控制，第二个才是真判据

| 负控制 | 结果 |
|---|---|
| 跳过循环界 → 0，跑新单测 | 两条都 exit 255 |
| 跳过循环界 → 0，跑 gen_kernel | **`SEGV_ACCERR`，不产 dill** |

第二个**只重建 Product 的 `dartaotruntime`**，快照仍是补齐过的那份 —— 这样才把
**解码器**与**发射器**分开，证明变红的是解码器。这就是上一轮那个回归，原样复现再关掉。

### 🔴 又踩一次「exit=0 是 tail 的」

第一次跑那两条测试时用了 `... | tail -8`，打出满屏 CRASH 却报 `exit=0`。
**管道里最后一个命令的退出码不是被测程序的。** 真实原因还是老朋友：
少了 `--dfe=gen/kernel_service.dill`，跟补齐一点关系没有。
✅ 判据：**先 `>log 2>&1; echo $?`，再去看 log**，别在同一行里既过滤又判成败。

### 单测怎么写才不是自证

`Arm64PadLoadStoreRemainsDecodable` + 双字版：**拿补齐的解码结果去对不补齐的解码结果**，
不写期望索引表；并且**调真的 `LoadWordFromPoolIndex` 并临时翻 `FLAG_precompiled_mode`**
（同文件既有测试就是这么翻的），而不是在测试里重抄一遍它发什么。
两条都在负控制下变红，不是摆设。

## ✅ 任务 14 已完成（spike `e9223a4`）：真映射第一次跑起来，以及它**没有**证明的东西

### 先把前提量出来，不凭记忆

memo 上写着「1421 项全部映射到自身」。**这次是量的**：拿 `patch.dill` 对 `base.op`
链接，1122 个不同的 PP 偏移**一个都没动**。恒等这件事从记账变成了实测。

原因是 fixture 太温和：`c_body.dart` 只把 `x + 1` 改成 `x + 2`，
`d_sig.dart` 只改签名，`b_shift.dart` 只加两行注释 —— **没有一个会挪动池的顺序**。

### `g_insert.dart`：插在前面，后面全体位移

新增一个带自己字符串常量的函数并在 `main` **开头**调用它，
它贡献的池条目排在 `main` 原有条目之前 → 其后全部位移。
这是真实补丁的常态形状，也是这里唯一一个映射非恒等的 fixture。

```
2321 个池访问；linked vs unlinked 分布距离 = 592
四个阶段计数 606 / 0 / 13 / 1113 / 292 / 19   ← 与他们逐行相同
```

**backfill 19 而不是 16** —— 这个数字变了，说明各阶段确实被问了新问题，而我们答得和他们一样。

### 两个判据，缺一不可

| 判据 | 单独用会怎样 |
|---|---|
| 分布距离 > 0 | **错的映射也能过** |
| 阶段计数 == 他们 | **退化 fixture 上人人都对**，等于没测 |

self-test 喂退化 fixture（距离 0）→ 必须报失败。已实测。

### 🔴 最重要的一条：**它不取代 `op_aggregator_check`，而且这是实测的**

我本来以为「有了真程序 fixture，合成 fixture 就多余了」。**动手量了一下，反了**：

```
把投票权重 1.0/N 改成常数 1.0：
  op_real_mapping_check   绿   ← 真程序 fixture 测不到
  shorebird_info_check    绿
  op_aggregator_check     红   ← 只有合成 fixture 测得到
```

原因和任务 1/2 记的是同一条：**真实程序里每个匹配组都是 1:1**，
每个键只有一个候选，**权重从来不参与决定**。
→ **真输入够到的是改写路径，够不到的是投票算术。** 两个检查测的是不相交的东西，
已写进 `verify_all.sh` 的注释，免得下一个人当冗余删掉。

⚠️ 这条同时是「负控制全绿要先确认补丁真的进去了」的正面例子：
两个绿之所以可信，是因为**同一次构建里 `op_aggregator_check` 变红了**。
只有两个绿的话，分不清「测不到」和「没编译进去」。

### ⚠️ 仍然没有的东西：被改写的那 592 个站点没有逐字节判据

他们自带的 `Expected:`/`Actual:` 自校验**只在索引未变时触发**，
所以它覆盖的恰恰是**没被改写**的站点。真正改写过的字节，
目前只由「阶段计数和他们一样」间接背书。→ 任务 15。

### ⚠️ 链接产物**故意不执行**

它的池访问指向 **base 快照**的槽位（这正是链接补丁的意义），
单独跑没有意义。正确性靠的是与他们 `gen_snapshot` 的对照，不是「跑起来没崩」。

### 顺手记两条环境坑

- **`timeout` 在 macOS 上不存在**（要 `gtimeout`），照抄 Linux 写法会得到 `exit 127`，
  长得像脚本失败。
- 生成步骤写进 `dd_pipeline.sh` 之后**真的跑了一遍**（不是只读一遍），
  产出的 `insert.{ct,op,dill}` 与手工那份**逐字节相同**。
  「记录下来但从没被调用过的步骤」正是这个目录存在的理由。

## ✅ 任务 15 已完成（`8c9ae52a50d` + spike `a505c58`）：两个判据一起放过了 655 个错站点

### 先确认前提（任务卡要求的那一步，做了）

`grep -n 'Expected:'` → 自校验在 `new_index == op.index` 那条分支里。
**他们那个 oracle 覆盖的恰恰是没被改写的站点**；改写分支是裸 `memcpy`，写完不回头。

### 🔴 缺口是量出来的，不是想出来的

把 `AssembleReplacement` 瞄偏一格（`{new_index + 1, op.kind}`）后：

```
分布距离            444（>0）        ← 判据 1 通过
阶段计数            606/0/13/1113/292/19，与他们逐行相同   ← 判据 2 通过
实际情况            655 个站点全部指向错误的池槽
```

**两个判据都绿，快照全错。** 这就是为什么「和他们的计数一样」不能当字节判据用——
计数描述的是**映射怎么算出来的**，与**字节怎么写下去**是两件事。

### 定位方式刻意不用计数器

读回位置用「从 footprint 末尾往回跳过 NOP」找，**不用 `InstructionCountNoPadding`**：

1. 计数器与发射器**已知在两个操作数区间差 1**（`ObjectPoolEditor_CountFollowsPrepareLargeOffset`
   钉着这件事）→ 用计数器定位会把一个已知的良性分歧变成假红。
2. 这样这条检查测的正好是**真正要紧的不变量**：
   **编辑器写下去的东西，必须是 `InstructionPattern` 读得回来的东西** ——
   也就是任务 13 的 `SkipBackOverObjectPoolLoadPadding` 所依赖的那个契约。
   两个任务在这里闭环。

### 两个负控制（都已还原）

| 负控制 | 结果 |
|---|---|
| 发射 `new_index + 1` | 655 站点报错，`gen_snapshot` 打出汇总行 |
| 完全不跳过补齐（定位逻辑坏掉） | `ObjectPoolEditor_RewriteMovesTheIndex` 与 `_RewriteLeavesNeighboursAlone` 变红 |

**第二个负控制的用途是回答「要不要补单测」**：它证明 `run_vm_tests` 里已有的测试
**单独就守得住这条读回**（不是靠字节被写坏顺带发现的）→ **不补单测**。
✅ 这是「先量再决定要不要写」的一个正例：不量就会白写一条测试。

### 🔴 harness 差点把证据扔掉

`op_real_mapping_check.sh` 原本把 `gen_snapshot` 直接 `2>&1 | grep 'Mappings from'`，
**其余输出全丢**。而编辑器报错**不中止**——`gen_snapshot` 照样 exit 0、照样写出快照。
→ 检查会在一个损坏的快照上报绿。现在整份输出留下，出现
`reads back as` / `did not verify` / `is not padded` / `outside the` 任一即失败。
✅ **可复用规则：`cmd 2>&1 | grep <想要的>` 是一种丢证据的写法。**
先落盘再 grep，尤其当被测程序「报错但不退出」时。

## ✅ 任务 16 已完成（spike `463ba49`）：两条预想的路都被墙挡死，第三条更强

### 可行性先答（任务卡要求的那一步，做了，没硬撞）

| 路线 | 结论 |
|---|---|
| 在 host 上把 patch 对着 base 装载起来跑 | ❌ 需要引擎侧装载链路，本 harness 够不到 |
| 用 `analyze_snapshot` dump 两侧池内容直接比 | ❌ **双向实测被墙**：他们的读不了我们的、我们的读不了他们的 |

```
theirs on ours: Wrong full snapshot version, expected '839937dd…' found '7150a2e8…'
ours on theirs: Wrong full snapshot version, expected '7150a2e8…' found '839937dd…'
```
→ 这就是 CLAUDE.md 里「需要两个 VM 完全一致」那一类，**结构性的，不用再试**。

### 🔑 第三条路：映射可以从代码里反推

改写是**原地**的、footprint 固定 → 同一个访问站点在链接前后**地址不变**。
于是「按地址配对两份反汇编」就直接得到**实际应用的索引映射**。
两边都这么做，然后逐条比：

```
1123 条，零分歧，键集合完全相同
```

**这比四个阶段计数强得多**：计数说的是映射*怎么算出来的*，这个是映射*本身*。
⚠️ 地址集合相等是**断言出来的**不是假定的——真要是不等，按地址配对会静默比较无关站点。

### 🔑 顺带关掉一个从来没人查过的假定

映射是用**他们的** `.op` 文件算的，却应用在**我们生成的代码**上——
**这只有在「我们的对象池顺序和他们一致」时才成立**。
因为版本墙，两个池没法直接比；但**两份映射逐条相同这件事，在顺序不一致时不可能发生**。
→ 假定关闭，代价为零。

### ⚠️ 六条映射指向装着不同对象的槽位——**不是 bug，别去"修"**

```
patch[759]='inserted-alpha-marker'  ->  base[759]='rex'
patch[762]='rex'                    ->  base[762]='null'
...
```
**他们的 gen_snapshot 一模一样是这六条。** 判据是「与他们一致」，
不是「符合我对映射应该长什么样的想象」。已写进检查的头注释防止后人"修好"它。

### 负控制：判据 3 抓到了判据 2 抓不到的

把发射器瞄偏一格：

| 判据 | 结果 |
|---|---|
| 1 分布距离 444 | 通过 |
| 2 阶段计数与他们逐行相同 | **通过** |
| 3 逐条映射 | **红：484 条不同**，且给出 `index 764: ours -> 766, theirs -> 765` |

这条负控制花费为零——四份快照本来就在这个检查里生成。

## 〜 任务 17 部分完成（`fbcefad7224` + spike `f989967`）：把「还差多少」变成一个数字

### 核实前提救了这一轮

任务卡写的是「我们的 `--help` 一条 Shorebird flag 都没有」——**症状对，结论会错**。
`--shorebird` **在源码里是有的**（`analyze_snapshot.cc:28,226`，B2 就实现了），
只是从没进过 help 文本。照着「补上 flag」去写就会重写一个已经能用的东西。

### 做了什么

补上 `--shorebird` 的三行 help（与他们**逐字节相同**），
**没有**补另外六个——**help 里写一个 parser 会拒绝的 flag，比 help 短更糟**。

新增 `analyze_snapshot_help_check.sh`：**拿他们的 `--help`，删掉那六个 flag 的块，
要求剩下的与我们的逐字节相同**。

```
--help matches theirs with 6 unimplemented flag(s) removed
(7 documented, 14 lines withheld)
```

✅ **判据刻意不是「我们的是他们的子集」**——子集判据在 help 为空时也通过。
它是**重建 + 相等**，所以我们打印的每一行每轮都在跟他们对。
✅ 实现掉一个 flag = 从脚本的 `MISSING` 列表里删掉它的名字 →
检查会保留它的行并**变红，直到 help 也补上** —— 这正是「有人会发现 help 忘了更新」的时刻。

### 🔴 尾随空格是契约的一部分，第一次跑就抓到了

他们每行都补到 **76 列**，唯独 `Shorebird options:` 前的分隔行是**裸 `\n`**。
我按「都补到 76」写，第一次跑就红了，diff 直接指出是第 11 行。
✅ **一个会 strip 空白的检查会在这里放过错误的 padding，而 padding 恰恰是最容易写错的部分。**

### 两个方向的负控制（都已还原）

| 负控制 | 结果 |
|---|---|
| 清空 `MISSING` 列表（= self-test） | 红：列出 14 行我们没打印的 |
| 把我们**打印的**某行挪一个空格 | 红：直接引出那一行 |

✅ **self-test 只覆盖「我们少打印」这个方向**，第二个才覆盖「我们打印错了」。
两个方向要分别测。

### ⚠️ 另外六个 flag 是**依赖缺失**，不是没做

| flag | 缺什么 |
|---|---|
| `--dump_object_pool_link_data`、`--no_pp_hash` | **`op_subgraph_hash`**。⚠️ 注意：`ObjectPoolLinkInfo::WriteToStream` **已实现且逐字节验证过** → **缺的是生产方，不是格式** |
| `--dump_blobs` | 四个 region 的**长度**，`Dart_SnapshotAnalyzerInformation` 结构里没带 |
| `--dump_object_pool` / `--dump_class_table` / `--disassemble` | JSON 生产方 |

→ 这就是任务 18 的由来：`op_subgraph_hash` 是**整条 pipeline 对他们二进制的最后一处硬依赖**
（`.op` 文件目前只能由他们的 `analyze_snapshot` 产出）。

## 〜 任务 18（`7ca20d214ea` + spike `63a658c`）：一条记错的符号表，和一个死 flag

### 🔴 订正：`SubgraphHasher` 不是「两边都 0 的口径陷阱」，是真实缺口

符号表里那一行记的是「他们 0 / 我们 0，读不出结论」。**错在量错了二进制。**
它住在 **`analyze_snapshot`**（`dart::snapshot_analyzer::` 命名空间），
而我们一直只量 `gen_snapshot`。换一个产物量，立刻出来：

```
dart::snapshot_analyzer::SubgraphHasher::SubgraphHasher(InstructionsTableInterface&, char const*, DDTableLinkInfo const*)
dart::snapshot_analyzer::SubgraphHasher::Hasher::Hash()
dart::snapshot_analyzer::SubgraphHasher::AccumulateRecursive(unsigned long, int)
sha1_transform(SHA1_CTX*, unsigned char const*)
dart::CascadeLimiter::Run(unordered_map<long, unordered_set<long>> const&, ...)
```
我们这一侧：**0**。

✅ **可复用规则（新）：符号表里的「两边都 0」在换一个二进制之前不算结论。**
量之前先问「这个子系统本来该出现在哪个产物里」：
**运行期设施在引擎、分析器设施在 `analyze_snapshot`、编译期设施才在 `gen_snapshot`**。
（同型旧坑：wrapper 子系统当年也是因为量错产物被记成「最大缺口」。）

### ✅ `--no_pp_hash`：忠实复刻 = 写进 help 且**不**注册

它在他们 help 里，但**他们自己的 parser 不收**——落到 `Dart_SetVMFlags` 被拒：

```
theirs: Setting VM flags failed: Unrecognized flags: pp_hash
ours  : Setting VM flags failed: Unrecognized flags: pp_hash     ← 改动前就已相同
```

六个 flag 里**五个被他们的 parser 接受，只有这一个不被接受**（逐个实测出来的）。
→ 我们的行为本来就和他们一致，**只差两行 help**。补上即完成，缺口 6/14 → **5/12**。
⚠️ 已在代码里写明「**不要通过注册它来"修好"**」，并让检查断言两边拒绝方式相同。

### 🔴 差点用错判据：字符串考古回答不了「有没有注册」

第一反应是 `strings | grep no_pp_hash` → 只有 help 那一行 → 想判「死 flag」。
**跑了阳性对照才发现这个判据是坏的**：`sdk_version` 明确是注册过的，
它**同样没有 bare-name 字符串**。
→ 判据换成**行为测试**（逐个 flag 试，看错误是「Unrecognized flags」还是别的）。
✅ 这正是 CLAUDE.md 那条「否证一个断言，判据必须可能命中它」的又一次命中。

### 负控制

把 `--no_pp_hash` 注册进我们的 option 表 → 我们能接受、他们仍拒绝 → 检查变红。
这道负控制守的就是上面那句「不要注册它」。

# 📖 关键参考文档（别重新推导）

| 文档 | 内容 |
|---|---|
| `fhp-research/spikes/shorebird_linkinfo_oracle/OP_AGGREGATOR_RECON.md` | 任务 1/2 的算法全文 + 地址级证据 + 复现命令 |
| `fhp-research/spikes/shorebird_linkinfo_oracle/OBJECT_POOL_EDITOR_RECON.md` | 任务 5/6 |
| `memory/project_dart_sdk_fork.md` | 主任务全史（正文缺 2026-08-25 后半段，见下） |
| `memory/feedback_false_green_traps.md` | 19+ 种假绿陷阱 |
| `CLAUDE.md` | 规则 0-3，优先于本文件之外的一切 |

## ⚠️ 已知的记账不一致（待补）

`memory/project_dart_sdk_fork.md` 的 frontmatter `description` 已更新到最新
（提到 `f426f46f5b0`、加权投票聚合器），但**正文没有对应章节**——
`command grep '加权投票\|votes_\|OP_AGGREGATOR_RECON'` 在正文 0 命中。
2026-08-25 后半段的两项发现只活在 `MEMORY.md` 索引里。**任务 1 完成时顺手补进正文。**

---

# 🎯 真实剩余面（三分清单）—— 2026-08-26 任务 62 实测重建

> **这份清单取代 `CLAUDE.md` 子系统表作为待办来源。** 那张表是历史与证据来源，
> 里面的「未做 / 缺口 / 我们为 0」已经四次生成不存在的任务
> （`WrapCode`、`InBaseSnapshot`/`UnwrapEntryPoint`、`shorebird_base_instructions_table_`、
> 对象池 link-results 聚合器）。**后续任务只从这份清单里取。**
>
> 基线（本轮实测，未改源码，数字不应变化）：`verify_all.sh` **16 ran / 0 failed / 0 skipped / 0 blocked**、
> `run_vm_tests` **157 passed**、`verify_reproduction.sh` **28 artifacts / 0 failures**。
> HEAD = `c316526c1cb`（`~/dart-3122/sdk`，分支 `shorebird-3.12.2`）。
>
> **每一项都带产生它的那条命令。没有命令的条目不许进这张表。**

## A. 有证据可依（oracle / 反汇编 / DWARF 已在手，可以直接开工）

| # | 条目 | 现状与支撑它的实测命令 |
|---|---|---|
| ~~A1~~ | ✅ **已关闭（2026-08-27 任务 63，`afa1f9c73cc`）** —— ~~**`print_dd_resolution_to` 的 `rewritten` / `sentinel_filled` 两列**~~ | 我们发 `rewritten=0`，他们读 **2**。判据：`cd ~/Documents/fhp-research/spikes/shorebird_linkinfo_oracle && ./dd_pipeline.sh` → 他们 `DD table: 8 slots, 7 retained, 2 rewritten, 1 unrewritten-null filled with sentinel`。**0 是硬编码字面量**：`command grep -n 'rewritten=0' ~/dart-3122/sdk/runtime/vm/shorebird/linker.cc` → `:1159`。⚠️**旧理由「依赖我们没有的 DD IL 子系统」已作废**——该子系统已于 `b13e2a0d54e` 实现（`git merge-base --is-ancestor b13e2a0d54e HEAD` → 0），`dd_pass_check.sh` / `dd_runtime_check.sh` 常设通过。`linker.cc:1153-1155` 那条注释是过期的。→ **是「把计数器接到已存在的改写路径上」，不是缺子系统。** |
| A2 | **`object_pool_editor` 两处计数分歧用了 `ASSERT` 而非 `RELEASE_ASSERT`** | release 构建里被编译掉 = 软点。判据：`command grep -n 'CountFollowsPrepareLargeOffset' ~/dart-3122/sdk/runtime/vm/shorebird/object_pool_editor_test.cc` → `:369`；该用例体内是 `EXPECT_EQ`（`ISOLATE_UNIT_TEST_CASE` 下 `EXPECT` 会计入失败，但 `.cc:501` 引用的那条推导仍靠 `ASSERT`）。两处已知分歧：kind-3 index 62 发射器用 2 而计数器说 3；kind-1/2 offset 2²⁴ 发射器用 3 而计数器说 2（**后者是我们自己读错了折叠 ladder**）。→ 收紧断言 + 修计数器。 |
| A3 | **plurality tie-breaking 零覆盖 / `refreshed` / `dropped-stale` 三条分支未被任何 fixture 走到** | 判据：`./dd_pipeline.sh` 两个 pass 都打印 `0 refreshed, 0 dropped-stale`，且每 slot 恰好一票。→ 需要**自造 fixture**，方法已有先例：`make_op_fixture.py` + `op_aggregator_check.sh` 就是为「他们的 fixture 判别不出来」而造的。 |
| A4 | **`analyze_snapshot --disassemble`** | 唯一还没做的 `analyze_snapshot` flag。判据：`./analyze_snapshot_help_check.sh` → `--help matches theirs with 1 unimplemented flag(s) removed (12 documented, 3 lines withheld)`。曾实现后**回退**——撞上 VM 自己的同名 flag，原因记在 `~/dart-3122/sdk/runtime/bin/analyze_snapshot.cc:112-123`。→ 证据齐全，缺的是解名字冲突的办法。 |
| A5 | **他们的 DD IL pass 由 resolution 驱动，不是由 `DDSlotMapping` 驱动 —— 我们两条路径都留着** | 2026-08-27 任务 63 的计划外发现。两次跑**他们的** `gen_snapshot` 数三指令间接序列：voters-only（无 `DDSlotMapping` 段）→ **3 个改写点**；mapping-only（一行，kernel_offset 54623 → slot 0）→ **0 个改写点**，而同样的字节**我们发射 73 个点**（`dd_pass_check.sh` 的 StringBuffer.write 用例）。旁证：他们 DWARF 里 `DDSlotResolution::owner_to_slot_`（+0x28）在任务 63 之前**我们树里没有任何消费者**，而它正是 resolution 驱动的 pass 所需的反查表。任务 63 已加上 resolution 路径并**保留** kernel_offset 路径（优先查后者），所以生产配置行为不变。→ **剩下的是「能不能删掉 kernel_offset 路径」**，而建表仍按 kernel_offset 键，删它需要自己的证据，不能靠这一次观测推。 |

## B. 无证据（必须先反汇编或先找 oracle）

| # | 条目 | 缺的是哪一段证据 |
|---|---|---|
| B1 | **`IndirectStaticCallInstr` 的 `@0xd8`（int32）字段含义** | 已确立**不是** entry kind（那个硬编码 0）。`EmitNativeCode` 反汇编只给出 `@0xc8`=表索引、`@0xc0`=原始 `Function`。→ **缺一个会让 `@0xd8` 取到不同值的输入**；`--compute_dd_table` 与 `--print_dd_resolution_to` 两个 oracle 都不暴露它。 |
| B2 | **装着稀疏 dispatch table 的快照能否真正执行** | `print_dispatch_table_link_info_to` 已 **byte-identical**（`cd4aeecd189`，6 个 fixture 全对），但**从未验证过装着这张更稀疏的表的快照跑得起来**。→ 缺的是一条端到端装载路径；`verify_reproduction.sh` 只比字节不执行。 |
| B3 | **`LinkOracle::RunTargetFromBaseOffset` 的正确性** | 它在**他们引擎里是死方法**（DWARF 有声明、无内联实例、无外联符号），我们的实现是对称读法、**未经验证**。→ 缺的是任何一个会调用它的生产路径。`Install()` 同理是我们加的（他们的安装方尚未还原）。判据：`command grep -n 'Install\|RunTargetFromBaseOffset' ~/dart-3122/sdk/runtime/vm/shorebird/shorebird.h` → `:82 :88 :110`。 |
| B4 | **用我们的 dart-sdk 构建 iOS 引擎** | ⛔ **这是唯一一条会让完成度百分比在真机上大幅缩水的。** 判据：`command ls ~/dart-3122/sdk/xcodebuild/` → 只有 `ProductARM64` `ReleaseARM64`，**没有任何 iOS 产物**。所有跑通的东西（DD 全链路、wrapper、patch 加载入口）都是 host 的 `dart_force_simulator` 构建。人类已报告 iOS 真机随时可测 → **设备不是阻塞，产物才是。需要人类决定是否插入这个任务。** |
| B5 | **真机 A/B：C6 删掉 safepoint guard 后的安全性** | 依赖 B4。目前**零实测**。 |

## C. 结构上不可关闭（是完成度的*度量*，不是待办）

> 这三类本质上要求「两个 VM 完全一致」。**写进百分比只会让它永远差一截。**

| # | 条目 | 判据 |
|---|---|---|
| C1 | **所有编码 Thread 偏移的指令** | 他们的 Shorebird 块在 `Thread` 结构**中部**（`+0x8d8`），我们只能**追加在末尾**（`+0xf18`）——中间插入会被 `CheckOffsets` 在构建期打死，重生成偏移表要 16 个配置、本机磁盘不够。后果：16 个 stub 里只有 `CallClangCodeWithSimulatorArgs` **38/38** 完全一致（它不碰 Thread，**这恰好证明无结构障碍时能做到逐字节相同**），其余残差全是这一类。逐字节命中率见 `WRAPPER_STUBS.md`。 |
| C2 | **快照版本 hash** | `568671cd` vs `839937dd`（`gen_snapshot`）/ `839937dd…` vs `7150a2e8…`（双向装载）。**跨实现读快照已双向实测不可达**：两边的 `analyze_snapshot` 互读对方快照都报 `Wrong full snapshot version`。→ 任何「直接对比两侧快照内容」的判据都走不通，只能像任务 16 那样从**反汇编**取共同可观测量。**不要再试。** |
| C3 | **堆遍历顺序 / `field_table` 组内顺序 / dispatch table offset 分配** | `print_field_table_link_info_to` **内容全同**（622 条、多重集合相等），仅同 id 内顺序不同。⚠️ 判别法：看置换有没有结构 + 局部相对序是否保住——`field_table` 已证伪**不是** libc++ 容器 artifact，是堆遍历顺序。 |
| C4 | **`GetBestMapping` 的不可破平票** | 实测他们 `14/8/0/120`、我们 `14/13/0/115`。我们的顺序由 libc++「空桶则压到链表头」决定，他们的随 key 变化 → 跟的是我们复现不出的桶布局。**匹配它需要两个容器有相同的桶宽历史 = 需要两个 VM 完全一致。** 已试过「把 vote map 改成按值拷贝」（他们 `0x10019ce88` 确实有）→ **数字一字未变**。**三次尝试后停手，不要再试。** |

## D. 本轮查出的记账缺陷（已就地改掉，列此以防复发）

全部实测于 2026-08-26，HEAD `c316526c1cb`：

| 原断言 | 实测结果 |
|---|---|
| 「对象池聚合器我们的算法不是他们的算法，只在 fixture 上重合」+「判别实验未做」 | **三处分歧全部已于 `ab58e28152d` 关闭**（`git merge-base --is-ancestor` → 0，落后 HEAD 23 个提交）。`linker.cc:449-534` = 加权投票 + 无 `size()!=1` 过滤 + 黏性 `use_self_pp`。判别 fixture `make_op_fixture.py` + `op_aggregator_check.sh` 早已在 `verify_all.sh` 里 |
| 「`object_pool_editor` 仍未接进 `ImageWriter::Write`，是真依赖缺失」 | **已接进**，`runtime/vm/image_snapshot.cc:622` 调 `ObjectPoolEditor::Edit(...)`，提交 `66a46515eb5` |
| 「`InstructionCountForLoadStoreFromOffset` 在 `gen_snapshot` 里 0 个（无生产调用点）」 | **2/2**（`nm -a … \| c++filt \| sort -u \| grep -c`） |
| 「`Assembler::PadLoadStore` 我们 0 次」 | **2/2** |
| 「DD 机制我们仍为 0，真实剩余面两项」 | **全部持平**：`IndirectStaticCallInstr::` 方法名集合 diff 两向为空、`DDTableBuilder` 8/8、`DDSlotMapping::` 2/2；IL pass 已实现（`b13e2a0d54e`） |
| 「16 个私有 stub 我们只声明了其中 2 个」 | **声明了 14 个**（`stub_code_list.h:159-172`）+ 2 个上游被改的（`:84` `:195`）= 16/16，与同格「全部有真 body」一致 |
| 「mappers / field_hasher 2 / 0 / 未变」 | `FieldHash` **2/6**（`field_hasher.{h,cc}` 于 `ecd1e5b5b20` 落地）；`Mapper` 两边**都是 0** = 第四例口径陷阱 |
| 「`LinkedValue<T>` 模板（我们没有）」 | **已有**，`linker.h` 7 处 / `linker.cc` 7 处 |
| 「`LinkOracle` 我们为 0」 | **已实现** `94ee77c3624`；`nm` 他们 0 / 我们 10（它是运行期类，他们的在引擎里不在 `gen_snapshot`） |
| 「`print_shorebird_info` 的 gen_snapshot 那半被阻塞」/「证据不足以按规则 3 实现聚合器」 | **两半都已完成**，`shorebird_info_check.sh` 在 `verify_all.sh` 里 ok / 0 failure(s) |
| 「`rewritten` 列真正依赖 DD IL 子系统」 | **事实仍成立（我们 0 / 他们 2）但理由已作废**——子系统已有，0 是 `linker.cc:1159` 的硬编码 → 降级为 A1，一件小活 |

⚠️ **本轮踩到的第 N 例工具假阴性**：`find ~/dart-3122/sdk/xcodebuild -name "analyze_snapshot*"` 与
`ls` 都报**不存在**，而 `test -f` 报 **EXISTS（4483952 字节）**。若信了前者，会把
`analyze_snapshot` 的全部符号计数读成「我们 0」——正好是本轮要修的那种假缺口。
→ **`nm` 出来 0 行时，先确认二进制真的被读到了**（`wc -l` 符号文件，不是只看 `grep -c` 的 0）。
本项目 `memory/feedback_rtk_diff_unreliable.md` 早有记录：**RTK 包装的 `ls`/`find`/`grep` 会静默说谎，一律加 `command` 前缀。**
