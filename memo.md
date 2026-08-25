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
- [ ] 任务 10：`IndirectStaticCall` 68 vs 64 ⬅️ **当前任务** —— 先查清差额是 strip 差异还是真缺口

## ⏳ 挂起池（连续失败 3 次的顽固 Bug）

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
verify_reproduction.sh     checked 24 artifact(s), 0 failure(s)
dd_pass_check.sh           0 failure(s)
dd_runtime_check.sh        0 failure(s)
op_link_info_check.sh      0 failure(s)
shorebird_info_check.sh    0 failure(s)
op_aggregator_check.sh     0 failure(s)
op_rewrite_check.sh        0 failure(s)
run_vm_tests               141 passed
8 ran, 0 failed, 0 skipped
```
`--self-test` 模式下 6 个 harness 全部能正确报错。工作树 clean。
HEAD：`ead5f153d8d`（dart-sdk） / `3277b35`（fhp-research）。


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
| `SubgraphHasher` / `CascadeLimiter` / `ClassTableMapper` | 0 | 0 | ⚠️ 已知口径陷阱，两边 0 读不出结论 |

→ **除 `IndirectStaticCall` 待查外，不再有「一侧为 0」的私有子系统。**

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
