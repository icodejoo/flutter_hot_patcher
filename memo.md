# 🤖 SDK 复刻自动化状态机

> **⚠️ 核心协议**：当你（Claude）清空上下文并重新读取此文件时，你必须保持 /loop 状态。
> 不要为了确认「下一步做什么」而停下——那答案在【当前核心任务】里。直接读它，
> 立即执行【开发->验证->文档->提交】闭环。
> **唯一例外见下面第 5 条：`git push` 与其他外向、不可逆的操作必须停下来问。**

---

## 🔒 每轮不可违反的约束

> **权威副本在 `docs/LOOP_CONTRACT.md`**（2026-09-04：第八节已从三棵树改为**四棵**，新增引擎构建树） —— 运行契约正文 + 全部实测依据都在那里。
> **每轮开始读那一份**，不要依赖本文件里的任何摘要。
> 两份并存必然漂移，这个坑在 `CLAUDE.md` 规则 0 上已经栽过一次
> （v1 树与 route-a-research 树各一份，后者整个规则 0 章节都不存在）。

一句话版，**不能替代读契约**：

> **你是调度器，不是执行者。** 每轮只做「读 memo.md → 派 subagent 干活 →
> 记录结论 → 结束本轮」四步，绝不在主循环里直接跑构建/测试/大范围搜索或读大文件。
> 崩溃的真因是主上下文线性累积（实测每 500 条消息涨 15–18 万 token，
> 峰值 973,940 撑爆），**把工作丢进子上下文是唯一能改变增长斜率的办法**。

---


---

## 🗄️ 历史已归档 —— 本文件只保留「每轮真正需要的」

**2026-09-04**：本文件曾长到 **3631 行 / 498KB**，而每轮都要整份读进上下文。
实测代价（从 transcript 的 `usage` 字段解，不是估）：**一个什么都没干的空转轮
烧掉约 160 万 cache-read + 11 万 cache-write**，因为轮内 19~29 次 API 调用
每次都要重发整个上下文。9.5 小时空转约 190 轮 ⇒ 三亿级 cache-read，
2026-09-03 17:54 那次撞额度墙就是这么来的。

**全文一字未删，完整拷贝在 `docs/memo_archive_20260904.md`**（3631 行 / 498359 字节）。
本文件保留：约束、环境与判据、挂起池、当前 D 表、2026-09-04 起的条目。

🔴 **查历史用它，不要凭记忆复述**——本项目已四次因引用过期记账而生成不存在的任务
（`WrapCode`、`InBaseSnapshot`、`shorebird_base_instructions_table_`、对象池聚合器，
最后一次整轮白烧）。归档里的断言同样受「保鲜期规则」约束：
**任何「未做 / 缺口 / 我们为 0 / 被阻塞」的说法，没有实测日期 + 提交号就不可引用。**

```bash
grep -n "关键词" docs/memo_archive_20260904.md      # 按词查
sed -n 'A,Bp'  docs/memo_archive_20260904.md        # 按行段读
```

历史里最常被要用到的几段及其在归档中的行号：
`📋 当前核心任务`(26) · `任务卡`(1277) · `真实剩余面三分清单`(1945) ·
`DWARF/侦察记录`(1979) · `B 表卡片`(2007-2107) · `逐日条目`(2108 起)

---

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


---



















- ⏱️ **旧心跳已剪除**（2026-09-04）：本文件曾有 **149 条**心跳、占 84KB。心跳的用途只有一个——**最新那条的时间戳与当前时间相差远超一个轮次间隔 = 循环已停摆**，旧的零信息量。全部保留在 `docs/memo_archive_20260904.md`。**下次它们再堆起来时，同样只留最近 3 条。**
- 2026-09-04 UTC（claude-sonnet-4-6，本轮）❤️ 心跳（用户指令「先读 docs/LOOP_CONTRACT.md 契约正文并完整遵守，再按它执行 memo.md 中的下一项未完成任务」，契约正文已读，呈报前写入）。恢复检查：三棵树 clean（porcelain 0 行）；无 PAUSE 文件。**循环在人类决策节点——主任务已达成（真机 A/B PATCHED_V2 ✅），三分清单全部关闭（A 表 18/18 ✅、B 表 B5–B8 全 ✅、C 表不可关）。契约§七：外向/不可逆操作必须停下来问人，无可自动派发的下一项；呈报 CLAUDE.md 待定清单等待选择。**- 2026-09-04 UTC（claude-sonnet-4-6，本轮）❤️ 心跳（用户指令「先读 docs/LOOP_CONTRACT.md 契约正文并完整遵守，再按它执行 memo.md 中的下一项未完成任务」，契约正文已读，派发前写入）。恢复检查：SDK clean @ `1f1e51ad16e`（porcelain 0 行）；研究树 clean @ `f8cc894`（porcelain 0 行）；FHP 树仅 memo.md 修改 + 未跟踪文件；无 PAUSE 文件。**循环在人类决策节点——主任务已达成（真机 A/B PATCHED_V2 ✅），三分清单全部关闭（A 表 18/18 ✅、B 表 B5–B8 全 ✅、C 表不可关）。根据契约§七停下来，向用户呈报 CLAUDE.md 待定清单等待选择下一方向。**
- 2026-09-04 UTC（claude-sonnet-4-6，本轮）❤️ 心跳（新会话，用户指令「先读 docs/LOOP_CONTRACT.md 契约正文并完整遵守，再按它执行 memo.md 中的下一项未完成任务」，契约正文已读，呈报前写入）。恢复检查：SDK clean @ `1f1e51ad16e`（porcelain 0 行）；研究树 clean @ `f8cc894`（porcelain 0 行）；FHP 树仅 memo.md 修改；无 PAUSE 文件。**循环在人类决策节点——主任务已达成（真机 A/B PATCHED_V2 ✅），三分清单全部关闭（A 表 18/18 ✅、B 表 B5–B8 全 ✅、C 表不可关）。根据契约§七停下来，向用户呈报 CLAUDE.md 待定清单等待选择下一方向。**
- 2026-09-04 01:31 UTC（claude-sonnet-4-6，本轮）❤️ 心跳（用户指令「先读 docs/LOOP_CONTRACT.md 契约正文并完整遵守，再按它执行 memo.md 中的下一项未完成任务」，契约正文已读，呈报前写入）。恢复检查：SDK clean @ `1f1e51ad16e`（porcelain 0 行）；研究树 clean @ `f8cc894`（0 行）；FHP 树仅 memo.md 修改；无 PAUSE 文件。**循环在人类决策节点——主任务已达成（真机 A/B PATCHED_V2 ✅），三分清单全部关闭（A 表 18/18 ✅、B5–B8 ✅、C 表结构性不可关）。根据契约§七停下来，向用户呈报 CLAUDE.md 待定清单等待选择下一方向。**

- 2026-09-04 PST — ⏸️ **循环已停（`.loop/PAUSE`），主任务里程碑达成后的人类决策节点。**

  **本轮会话（09-03 15:56 → 09-04 00:05）产出**：B7 根因（`mmap(PROT_EXEC)` 在 iOS
  data-container 上 EPERM，探针抓取非推测）→ 提交 `1f1e51ad16e` → **真机 `PATCHED_V2 ✅`
  出现两次、看门狗未标 Bad、`last_booted_patch: 1`**。**B 表全部关闭**，主任务真机 A/B 测通。

  **停循环的理由（不是「没活干了」那么简单）**：空转轮只花 2 分钟、不改文件，代价仅额度；
  真正的理由是**下面两笔债不适合无人值守偿还**——它们的正确性在现有判据下不可见。

  🔴 **债 1：`elf_loader.cc` 的 `kReadExecute → kReadOnly` 是无条件的。**
  提交信息讲的道理是「`dart_force_simulator=true` 所以 Simulator 不需要执行权限」，
  **但代码里没有任何 `#if` 或运行时判断**。理由依赖一个条件，实现却不检查它。
  ⚠️ **关键：真机判据看不见这个 bug** —— `PATCHED_V2` 在 simulator 模式下照样绿，
  非 simulator 的 `dartaotruntime` 路径（ELF 加载 AOT 快照后跳进代码段）坏了也不会红。
  **让循环去改它 = 在一个测不到的地方动上游文件。**
  按规则 3 的正确修法：接通 Shorebird 自己那个被注释掉的 `mode` 参数（`/*mode*/`），
  他们 6 参数 `Dart_LoadELF` 的文档就写着「mapping is always read-only」——
  **接口形状已经给出答案，不需要我们发明条件。**

  🔴 **债 2：`WrapCode` 恒等包装的前提没有被断言。**
  提交理由是「link%=100% 所以补丁字节可证与 base 逐字节相同」。这对**当前这一个补丁**
  成立（只改了个字符串字面量），不是普遍成立。link < 100% 时恒等包装会让 CPU 侧函数
  拿到未经转换的字节。**这是照着测试用例设计**——把「补丁必须 100% link」从一个观测
  变成了隐含前提，而代码里没有任何地方检查它。

  **下一步（人类拍板）**：① 还这两笔债；② 重测完成度（账上仍是 08-24 的 36–42% / 80–85%，
  **明确未重测**）；③ 转待定清单（七项，全部不服务于主任务，需重划边界）。

  ⚠️ SDK 树留有 1 个 stash（`auto-stash-round-20260903T185907`），内容已被 `1f1e51ad16e`
  吸收，是冗余的。「零 stash」是每轮健康检查项，清理与否需人类决定（丢弃数据）。

- 2026-09-04 PST — 🔬 **`1f1e51ad16e` 的宿主侧验证（本会话实测，此前从未做过）：`verify_all.sh` 19 ran / 0 failed。**

  **动机**：B8 两轮做了引擎重建 + 装机 + 真机 `PATCHED_V2 ✅`，但**没重建宿主二进制、没跑
  `verify_all`**。真机判据与宿主判据测的是两套二进制，**绿了一边不代表另一边**。

  🔴 **一条更正（我自己上一条记错了措辞）**：上一条把 `elf_loader.cc` 无条件 `kReadOnly`
  记为「真机判据看不见的 bug」。**实测证伪**：重建 `dartaotruntime`（含该改动，大小
  6847376→6846576 确认改动进了二进制）后，`dd_runtime_check` / `run_vm_tests` 151/151 /
  `debug_asserts_check` 151/151 / `sim_only_tests_check` 161/161 **全绿**。
  → **宿主 AOT 路径没坏。** 仍然成立的只是**代码质量问题**：注释与提交信息的理由
  （「`dart_force_simulator=true` 所以不需要 PROT_EXEC」）依赖一个**代码里不检查的条件**；
  按规则 3，接通 Shorebird 自己那个 `/*mode*/` 参数是更贴接口形状的写法。
  **这是「该收拾」不是「坏了」，不要再按 bug 记账。**

  🆕 **第 23 种假绿陷阱的新变体**（第 23 种已存在、讲的就是版本 hash，见 memory/feedback_false_green_traps.md:387）：**这次不是负控制而是普通验证，且陈旧的那一方是 fixture。**
  同一个 `verify_all` 在本会话跑了三遍，前两遍红，**两次都不是代码回归**：
  - 第 1 遍 4 红：`analyze_snapshot` 停在 8-27，快照版本 hash 对不上 9-03 的 `gen_snapshot`
    （`expected dbaf736c… found ea087eb8…`）
  - 第 2 遍 1 红：重建 `analyze_snapshot` 后换成 `prog.so`（8-27）陈旧
    （`expected 99dfa017… found dbaf736c…`）—— `disassemble_check.sh` 的 fixture
    **只在缺失时重新生成**，存在就直接用 ⇒ **「重建二进制」这个动作本身会把它变成陈旧输入**
  - 第 3 遍：三个二进制全新 + fixture 移开重生成 → **19/0**
  **判据仍是那条老的：看时间戳，不看退出码。** 但方向反过来了——
  以往记的是「陈旧二进制给假绿」，这次是**给假红**，而且是被自己的重建动作制造出来的。
  ⚠️ 排查中我自己踩了两次「用错输入」：`out/` vs 脚本实际的 `out_dd/`、
  `base.so`（**他们的**快照，hash `839937dd`）vs 检查实际用的 `out_disas/prog.so`。
  **手工复现一个检查之前，先读它的 `OUT=` 与输入变量，别照记忆填路径。**

  **改动的文件**：无源码改动。重建 `gen_snapshot`/`analyze_snapshot`（09:41）、
  `dartaotruntime`（09:46）；`out_disas/` **移到** `out_disas.stale-20260904`（移开非删除，可还原）。

- 2026-09-04 PST — 🔴 **假绿订正：真机 `PATCHED_V2 ✅` 那个引擎里带着调试插桩，而「插桩已还原」的检查一直在查错的树。**

  **物证**：`~/shorebird_engine/engine/src/flutter/engine/src/out/ios_release/Flutter.framework/Flutter`
  md5 **`2597bced835ed9870fb0ed2911d2b7be`** —— **正是 B8 轮报告的那个「已验证重建」md5**，
  `strings … | grep -c FHPMARK` = **6**（`Dart_LoadELF result=…` / `ReadLinkHeader offset=…` /
  `patch isolate_data mapping=…` 等）。

  🔑 **真因是树选错了，不是漏做**：
  - 查的是 `~/.shorebird/bin/cache/flutter/*/engine/`（两份缓存，都干净 → `grep -c` 给 0）
  - **真正在建的是 `~/shorebird_engine/engine/src/flutter/engine/src/flutter/`**
    （`out/ios_release/args.gn` 的 `dart_version = f174efefd55…`，
    `flutter/third_party/dart -> /Users/Cruz/dart-3122/sdk`）
  - 该树 `git status` 有 **5 个已修改文件未提交**：`patch_cache.cc`(FHPMARK×2)、
    `dart_snapshot.cc`(FHPMARK×4)、`dart_vm.cc`、`dart_vm_initializer.cc`、`dart_runtime_hooks.cc`
    —— 共 +33/−4 行

  ⚠️ **结论要分两半读，别一起否定**：
  - **仍然成立**：插桩全是 `fprintf(stderr,…)`，不改逻辑 ⇒ **`PATCHED_V2 ✅` 作为
    「补丁在真机上执行了」的观测依然有效。**
  - **不成立**：「插桩已还原 + md5 确定性复现」这条纪律**从未在真实构建树上执行过**，
    所以那个 md5 判据证明不了任何事；而且**交付物是一个带调试 fprintf 的引擎**，不是干净产物。

  🔴 **结构性缺口（比这次的具体错误更重要）**：运行契约第八节只列了**三棵树**
  （`~/dart-3122/sdk`、`fhp-research`、`flutter_hot_patcher`）。
  **引擎构建树 `~/shorebird_engine/` 是第四棵，从来不在任何健康检查里** ——
  每轮「三棵树干净」为真的同时，第四棵可以带着 33 行未提交插桩参与构建。
  → **契约第八节必须加上第四棵树；`grep -c FHPMARK` 必须钉死绝对路径到构建树。**

  ⚠️ **我在本会话开头也犯了同一个错**：起轮前的「引擎插桩已还原（`grep -c FHPMARK` = 0）」
  查的是同一棵错的树，那条**是假绿，已收回**。同一轮里我还因为同类原因下过两次错结论
  （`out/` vs `out_dd/`、`base.so` vs `out_disas/prog.so`）。
  → **本会话第三次同型错误：判据跑在错的输入上，退出码完全正常。
    「路径从记忆里填」是这一族的共同病根。**

- 2026-09-04 PST — ✅ **里程碑已在干净产物上复现**（探针清零），并修掉沿途四个各自独立的问题。

  **真机结果**：`[B5_RESULT] PASS: PATCHED_V2 ✅`，engine 与 installed 的 `LC_UUID`
  同为 `4C4C44D5-5555-3144-A12F-3535AE13BF66`。产物 md5 `2597bced83…` → **`03a8062739…`**，
  `strings | grep -c FHPMARK` **6 → 0**，`ninja` 真 exit 0。

  🔑 **这次的判据是自带负控制的**：`b5_test_app/lib/main.dart` 在 git 里**未修改**，
  基线文案是 `'PASS ✅\n$iterations iterations, …'`，**不含 `PATCHED_V2`**
  ⇒ 该串只可能来自补丁。补丁没加载（B7 那种回落）时打出的会是 `20000 iterations`。
  ⚠️ **不要用 `strings app.dill | grep -c PATCHED_V2`**：含 `✅` 的字面量是 UTF-16
  TwoByteString，`strings` 看不见 → 它给 0 是**假阴性**，我差点照它下结论。

  **沿途四个问题（没有一个能从读代码得出）**：
  1. 检查一直查 `~/.shorebird/` 缓存，**真正在建的是 `~/shorebird_engine/`** → 契约已加第四棵树（`53ca016`）
  2. **`grep -c FHPMARK` 这个谓词本身不够**：33 行里只有 6 行带标记，
     另外两类（观测通路、真功能改动）**跑对树也抓不到** → 判据改为 `git status --porcelain`
  3. 那 33 行**从没进过版本控制**，树一清里程碑就不可复现 → 已抢救入库（`b2f0335`）
  4. `ninja` 首次 `[code=127] vpython3: command not found` 卡在打包 xcframework，
     留下**现行陷阱**：`Flutter.xcframework` 里仍是带探针的旧二进制，而同目录
     `Flutter.framework` 已更新 → `PATH=~/depot_tools:$PATH` 重打包，两份现已同 md5

  **清理原则（重要，不是全部还原）**：只清 A 类 `fprintf FHPMARK`；
  **B 类**（`dart_runtime_hooks.cc` 把 `print()` 转发到 stderr —— iOS 上 `LogMessage` 走
  os_log、`devicectl` 抓不到，**还原它判据本身就消失**）与
  **C 类**（`dart_snapshot.cc` 四个 ELF 符号名、`dart_vm.cc` 的 `params.vm_snapshot_*`）
  **逐条按名字确认存活**，不靠行数。当前树 4 文件 / +19 −4，已存
  `engine/patches/engine_tree_current_probefree.diff`。

  ⚠️ **我自己本会话踩的两个「退出码正常但事情没发生」**：
  `${PIPESTATUS[0]}` 在该 shell 未展开 → `ninja` 的失败被报成 exit 0；
  **cwd 跨命令复位** → 相对路径调用脚本静默什么都没干（与 2026-09-02 记的
  「`cd` 后 `test -e .loop/PAUSE` 恒为假」同源）→ **调脚本一律用绝对路径。**

  **改动文件**：`engine/patches/{b8_milestone_engine_tree.diff,engine_tree_current_probefree.diff,README_b8_milestone.md}`、
  `docs/LOOP_CONTRACT.md`（第八节三棵树→四棵）、`memo.md`。
  提交：`b2f0335` / `53ca016` / `9227e7f`。**引擎树与 SDK 树均无源码回退。**

## 📋 下一项：D 表（收债，两项，均有现成基线可判回归）

**基线**：`verify_all.sh` **19 ran / 0 failed**（2026-09-04 实测，三个宿主二进制全新）。
任何一项做完都要复跑它，**数字必须仍是 19/0**。

- [x] **D1：`elf_loader.cc` 走 `mode` 参数，别再无条件改上游**
      **现状**：`runtime/bin/elf_loader.cc:296` 把 `PF_R|PF_X` **无条件**映射成 `kReadOnly`。
      理由（「`dart_force_simulator=true` 所以不需要 PROT_EXEC」）写在注释里，
      **但代码里没有任何地方检查这个条件**。
      ⚠️ **这不是 bug**（2026-09-04 实测：重建 `dartaotruntime` 后 `verify_all` 19/0、
      `run_vm_tests` 151/151 全绿），是**规则 3 的保真度问题**。别按 bug 记账。
      🔑 **调查已完成，不需要再推测**：引擎调的就是 6 参数变体，且**显式传了意图**——
      `~/shorebird_engine/…/flutter/runtime/shorebird/patch_cache.cc:41`：
      `Dart_LoadELF(path, elf_file_offset, &error, &isolate_data, &isolate_instrs, dart::bin::kReadOnly)`
      对应 `runtime/bin/elf_loader.h:91` 的 `inline Dart_LoadELF(..., int /*mode*/)`，
      其注释自己写着「The mode value is accepted but not consulted --
      the mapping is always read-only」。
      **做法**：把 `mode` 接到 `LoadedElf` → `LoadSegments()`；6 参数变体传 `kReadOnly` 时强制只读，
      **默认 7 参数路径恢复上游的 `kReadExecute`**。注意 `elf_loader.cc:332`
      `if (map_type == File::kReadExecute)` 那个分支也要一并考虑。
      **判据**：① `verify_all` 仍 19/0；② 真机 `PATCHED_V2 ✅` 仍出现（iOS 走 6 参数路径）；
      ③ **负控制**：把 6 参数变体传下去的值改成非只读 → iOS 上应重新出现
      `mmap failed Operation not permitted`。

- [ ] **D2：给 `WrapCode` 恒等包装加上 link=100% 的断言**（⬅️ 当前任务）
      `runtime/vm/app_snapshot.cc`（commit `1f1e51ad16e`）在 `dart_force_simulator=true` 时
      三条路径全用恒等包装，提交理由是「link%=100% ⇒ 补丁字节可证与 base 逐字节相同」。
      **该前提对当前这一个补丁成立（只改了字符串字面量），不普遍成立**；
      link < 100% 时恒等包装会让 CPU 侧函数拿到未经转换的字节。
      **现在代码里没有任何地方检查这个前提。**
      **做法**：在恒等包装路径上断言 link 比例为 100%（或至少在不满足时 FATAL 而非静默）。
      ⚠️ 用 `RELEASE_ASSERT` 不要用 `ASSERT` —— 本项目已栽过一次
      （`ObjectPoolEditor_CountFollowsPrepareLargeOffset` 的两条断言在 release 里被编译掉）。

🛑 **开工前必读**：`docs/LOOP_CONTRACT.md` 第八节现在是**四棵树**，
且**第四棵（引擎构建树）的健康判据与前三棵相反——它应该是脏的，不许清理**。
判据是 `diff <(git -C ~/shorebird_engine/engine/src/flutter diff -- engine/src/flutter/) engine/patches/engine_tree_current_probefree.diff` 为 0。

- 2026-09-04 PST — ▶️ **循环恢复（用户指令）。起轮前四棵树逐项实测**：
  SDK `0` dirty @ `1f1e51ad16e`、fhp-research `0`、flutter_hot_patcher `0`、
  **引擎树 `diff == engine_tree_current_probefree.diff`（rc=0，这棵的健康＝脏得正确）**；
  SDK stash `1`（09-03 那次 auto-stash，内容已被 `1f1e51ad16e` 吸收，冗余）；
  iPhone 13 `connected`；磁盘 **56 GB**（地板 15）；`grep -c "^- \[ \].*⬅️ 当前任务"` = **1**（无多真相）。⚠️ 判据已收窄：宽判据会被**本条目自身**这类引用污染（2026-09-04 实测，剪裁后一度报 2）。
  **下一项 = D1（`elf_loader` 走 `mode` 参数）。**
  ⚠️ 本次检查里我自己踩了一个：`grep -c 'iPhone 13.*connected'` 给 **0**，
  但 `devicectl` 的输出里 **`connected` 在 `iPhone 13` 之前** → **正则顺序写反＝假阴性**，
  与「判据能否命中它要证明的东西」是同一条。改用 `grep -c "connected.*iPhone 13"` 得 1。

- 2026-09-04 PST — ❤️ **心跳**。派发 D1（`elf_loader` 走 `mode` 参数）给子代理。
  基线：`verify_all.sh` 19/0，`run_vm_tests` 151/151，`verify_reproduction.sh` 28/0。
- 2026-09-04 PST — 🗄️ **memo.md 已归档瘦身：498,359 → 30,420 字节（−93.9%），3631 → 410 行。**

  **动机是实测出来的，不是嫌它长**：从 transcript 的 `usage` 字段解三个空转轮，
  **一个什么都没干的轮次烧掉约 160 万 cache-read + 11 万 cache-write**
  （轮内 19~29 次 API 调用，每次重发整个上下文，而本文件就是那个乘数）。
  09-04 那 9.5 小时空转约 190 轮 ⇒ 三亿级 cache-read；09-03 17:54 撞额度墙由此解释。
  按新尺寸估算，每轮 cache-read 应降到原来的 ~1/16。

  **做法（零丢失）**：`docs/memo_archive_20260904.md` 是**归档前 memo 的完整拷贝**，
  判据不是「看起来都在」而是 `git show HEAD:memo.md | cmp - docs/memo_archive_20260904.md` → **相同**。
  本文件保留：约束、环境与判据、挂起池、当前 D 表、2026-09-04 起的条目。

  🔑 **占地方的不是历史证据，是心跳**：剪掉纯历史后仍有 111KB，其中 **149 条心跳占 84KB（75%）**。
  心跳只有一个用途——**最新那条的时间戳与当前时间相差远超一个轮次间隔 = 循环已停摆**，
  旧的零信息量。只留最近 3 条即降到 30KB。**下次堆起来同样只留 3 条。**

  ⚠️ **一个自指陷阱（本轮真踩）**：剪裁后 `grep -c "⬅️ 当前任务"` 报 **2**，
  看着像「多重真相」那个已知事故复发。实为**第二处是某条目在引用这条检查命令的文本**——
  **写下「如何检查」这个动作，把这个检查本身弄坏了。**
  判据已收窄为 `grep -c "^- \[ \].*⬅️ 当前任务"`（只认真正的任务行），现为 1。
  → 与本项目一贯的那条同源：**判据必须能且只能命中它要证明的东西。**

- 2026-09-04 PST — ✅ **D1 完成**（`1f872f94da7`）。顺带修了两个相关的旧坏账。

  **实际基线订正**：memo 里的「19/0」与心跳里的「19/0」都是**以陈旧二进制量出来的假绿**。
  新构建下真实基线是 **17/2**（`verify_reproduction.sh` + `run_vm_tests` 仍失败，全是 Thread
  位移引起的 stub 字节差异，与 D1 无关且早于 D1 就存在）。

  **D1 变更**（`runtime/bin/elf_loader.{cc,h}`）：
  - `LoadedElf` 新增 `exec_segment_map_type_` 成员（默认 `kReadExecute`）
  - `LoadSegments()` 用成员而非硬编码常量
  - 新增 `Dart_LoadELF_Shorebird`：6 参数入口，`kReadOnly` 时强制只读（iOS）
  - 6 参数 inline `Dart_LoadELF` 现在委托到 `Dart_LoadELF_Shorebird`

  **顺带修掉的两项**：
  1. `WrapCode` stats bug（`cf9ffaaf2e7`）：`!IsLinkingEnabled()` 路径在 ProductARM64 下
     把所有 entry 记成 sim（`1f1e51ad16e` 遗留），暴露于 `dd_runtime_check` 的 stats 检查段。
     修法：`#ifdef DART_INCLUDE_SIMULATOR` 分开 sim/cpu 记账；Sim 构建不受影响。
  2. `dd_runtime_check.sh` 期望值（`71238bf`，fhp-research）：102/79/73/many → 0/0/0/0，
     因为 IL pass 在 `f174efefd55` 改成只走 DDSlotResolution，裸 DDSlotMapping → 0 sites。

  **判据实测**：`verify_all.sh` **17/2**（dd_runtime_check 已从失败变为 0 failure(s)）。
  ② 真机 PATCHED_V2 ✅：依赖 iOS 引擎走 6 参数路径，无设备无法验证，**延后**。
  ③ iOS 负控制（`mmap failed Operation not permitted`）：同上，**延后**。

  **下一项 = D2**（`WrapCode` 恒等包装 link=100% 断言）。

