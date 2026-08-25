# 🤖 SDK 复刻自动化状态机

> **⚠️ 核心协议**：当你（Claude）清空上下文并重新读取此文件时，你必须保持 /loop 状态。
> 严禁停下来等待人类确认，严禁偷懒。请直接阅读下方的【当前核心任务】，
> 立即执行【开发->验证->文档->提交->清理】闭环！

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
      ① `self_hash` **只取决于指令字节**（1378 个不同 blob，无一 blob 对应两个 hash）
      → 名字/索引/位置都不参与；
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
- [ ] 任务 21：**恢复 entry 流：`Entry` 的 kind 与 value 到底是什么** ⬅️ **当前任务**
      `Entry = {int32 kind; int32 value}`，kind 至少 0..8
      （log 分支用 `<=3 / <=5 / ==6 / ==7 / ==8 / default` 分派）。
      **两条路，先走便宜的那条**：
      ① 🎁 **他们自带日志**：`Hash()` 里有一条被 `this+0x30` 的 bool 门控的分支，
      会把每个 entry 格式化后经 `dart::Log` 打印出来。**打开它就是 ground truth，不是解读。**
      门控很可能是 `SubgraphHasher` 构造函数收的那个 `char const*`（疑似函数名过滤器）。
      ⚠️ `--disassemble` **不是**这个门（已试，无任何输出）。**值得先花一次探测。**
      ② 反汇编构造函数（`0x100195c54`，868B）与 `AccumulateRecursive`（`0x100196694`）。
      🎁 解出后 oracle 立即可用：`probe_subgraph_hash.py` 已能对 1380 个函数逐个验证。
      ⚠️ 每轮先确认还够得到，够不到就转下一项。

## ⏳ 挂起池（连续失败 3 次的顽固 Bug）

- **跨实现读快照**（非 Bug，是**结构性不可达**，2026-08-25 双向实测）：
  他们的 `analyze_snapshot` 读我们的快照、我们的读他们的，都报
  `Wrong full snapshot version`（`839937dd…` vs `7150a2e8…`）。
  → **任何「把两边的快照内容直接对比」的判据都走不通**，
  只能像任务 16 那样从**反汇编**取共同可观测量。**不要再试。**
- **真机 A/B 验证**（非 Bug，是**结构性不可自动化**）：需物理 iOS 设备 + 签名 + 部署，
  无人值守做不到。CLAUDE.md 里「真机零实测」这条只能由人类关闭。**不要反复尝试。**
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
run_vm_tests               143 passed
10 ran, 0 failed, 0 skipped, 0 blocked
```
`--self-test` 模式下 9 个 harness 全部能正确报错（`9 ran, 0 failed, 1 skipped`）。
工作树 clean。HEAD：`7ca20d214ea`（dart-sdk） / `848c903`（fhp-research）。
`analyze_snapshot` help 缺口：**5 个 flag / 12 行**（任务 17 是 6/14）。
⚠️ `verify_reproduction` 从 24 涨到 28 是因为任务 14 的 `insert.*` 进了 `out_dd`，
不是新写了什么 —— **数字变了要能说出为什么**。
✅ **`op_rewrite_check` 的 BLOCKED 已解除**（任务 13 让补齐回到树上，编辑器重新活了）。

**补齐现在是开着的**，所以每个 AOT 快照都比以前大：
`gen_kernel_aot.dart.snapshot` 13.2M → 14.1M；hello.dart 的 AOT 产物
NOP 数 0 → **4584**（他们同一程序 4598）。
⚠️ **重建 `copy_gen_kernel_snapshot` 是必须的**，否则 kernel 编译会撞版本串不匹配
（`product ... but the VM has release ...` = 你在拿 Release 的 dartaotruntime
跑 Product 的快照，两个配置两套产物）。


## 📊 私有子系统符号实测（2026-08-25，规则 0 的规定方法）

`nm -a | c++filt | sort -u` 双边同口径（他们先 `lipo -thin arm64`，我们 `--mode=product`）。
他们 32373 / 我们 34055 唯一符号。**只有「一侧为 0」是有意义的判据**——
我们计数更高不代表进展（我们未 strip）。

| 标志符号 | 他们 | 我们 | 判读 |
|---|---:|---:|---|
| `ShorebirdLinker::` | 20 | 38 | ✅ |
| `ObjectPoolMappings` | 8 | **10** | ✅ 本轮之前是 0 |
| `LinkedValue` | 4 | **12** | ✅ 本轮之前是 0 |
| `ObjectPoolEditor` | 2 | 4 | ✅ |
| `FieldHasher` | 2 | **2** | ✅ 任务 7 关闭 |
| `DDTableBuilder` | 8 | 8 | 持平 |
| `DDSlotMapping::` | 2 | 2 | 持平 |
| `IndirectStaticCall` | 68 | 64 | ⚠️ 差 4，**未查证**（原始行数受 strip 影响，不可直接比）|
| `groupBy` | 2 | 0 | ⚠️ **不是缺口**：我们的 `GroupBy` 是头文件模板，被内联 |
| `SubgraphHasher` / `CascadeLimiter` | 0 | 0 | 🔴 **这一行是错的，2026-08-25 任务 18 实测订正**：它们不在 `gen_snapshot` 里，在 **`analyze_snapshot`** 里（`dart::snapshot_analyzer::` 命名空间）。换个二进制量：**他们 4+ / 我们 0**，是**真实的一侧为 0**，不是口径陷阱 |
| `ClassTableMapper` | 0 | 0 | ⚠️ 仍是口径陷阱（我们的映射器已实现，只是不叫这个名字） |

🔴 **上面这句「不再有一侧为 0 的私有子系统」是错的**（任务 18 订正）：
`SubgraphHasher` 就是，只是它住在 `analyze_snapshot` 而我们只量了 `gen_snapshot`。
✅ **可复用规则：符号表的「两边都 0」在换一个二进制之前不算结论。**
量之前先问「这个子系统应该出现在哪个产物里」——运行期设施在引擎、
分析器设施在 `analyze_snapshot`、编译期设施才在 `gen_snapshot`。

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
