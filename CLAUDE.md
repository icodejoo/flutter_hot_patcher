# flutter_hot_patcher — 顶级规则

规则 0 决定**现在做什么**；规则 1-3 决定**怎么做**。四条都优先于本仓库其他任何文档、
计划或既有代码。与它们冲突的既有实现是待偿还的技术债，不是先例。

## 规则 0：当前主任务是复刻 Shorebird 闭源的 dart-sdk

在这件事完成之前，**所有工作都必须服务于它**。判断一项任务该不该做，先问：
它是否让「我们的 dart-sdk 更接近 Shorebird 的 dart-sdk」这件事向前走？答案不是「是」就别做。

### 🎯 当前阶段（2026-09-04 起）：系统性产物对拍

**为什么是这件事**：「复刻 dart-sdk」没有完成判据，所以「完成了吗」只能用估计回答。
本阶段把「还差多少」变成可核对的数字：

> 枚举他们 `gen_snapshot` / `analyze_snapshot` 的**全部 flag × 多组输入**，
> 与我们的输出**逐字节比对**，把每一处不一致归类为
> 「结构性（永不可关）」或「真缺口（可关，带编号）」，
> 产出一份**有编号、有判据、可复核**的缺口清单。

**完成判据**（三条全满足才算结束，权威定义与机器闸门见 `memo.md` 的 G 表）：
1. 覆盖矩阵存在且被执行；**没跑到的必须显式标注「未覆盖」，不许静默省略**
2. 每一处不一致都有分类与依据；「结构性」**必须给出是哪个结构的哪个偏移**，
   并且**必须附一条 residual 行证明它解释了这一格里的全部差异**
   （2026-09-07 加的：同一个 `Thread+0x678` 曾三次关掉一批格子，
   最弱的一次解释了 3656 个差异对象里的 **0** 个，三次都过关）
3. 存在负控制：故意改坏一处输出，对拍必须报出它

**当前状态（2026-09-11 实测）**：矩阵 `59 cells, 0 unrun, 3 blocked`，
**na=35 / structural=0 / unknown=24 / gap=0**（本行四个数是 2026-09-11 直接数 `parity_matrix.tsv`
得到的，`phase_gate.expected` 与之一致，研究树 `b0a78c9`）。
`verify_all.sh` **35 ran / 0 failed** —— 本次实测全绿（2026-09-14，研究树 `edc411d`；
`EXPECTED_CHECKS` 已是 **35**，此前本行写的 30 是 2026-09-11 的读数，已过期）。
- 判据 1 ✅ · 判据 3 ✅ · 判据 2 🔴 **未满足：24 格 unknown** ⇒ **这一阶段没有结束。**

🟢 **F61 已闭环关闭（研究树 `b0a78c9` + `f3ce840`，2026-09-11 Antigravity）**：
① **修复 `diff_units.sh` 长度差盲区**：`cmp -l` 补齐 `sz_diff`，追加 500 字节 UNITS 精确 +500；
② **彻底移除硬编码常量与自引**：彻底删除 `units=6` / `units=6408` 常量，实现独立二进制变长整数流解码器与严格 JSON 验证器，分子动态来源于真实记录数；
③ **三重真实负控制实测通过（交付 commit `b0a78c9` 实测）**：追加 500 字节报 `CORRUPT_OR_PARSE_ERROR`、1 字节翻转报解码失败、JSON 字段变异报 mismatch，全部且仅使本格在 `structural_evidence_check.sh` 报红（rc=1），还原后逐字节确认并全绿（rc=0）；
④ **真实 41 格审计**：20 yes + 6 vacuous + 9 na = 35 na 全部核验，不依赖坏分母；6 格降级为 unknown。

🔴 **第十一个仪器缺陷（2026-09-11 新增）：负控制跑在一个不存在于任何提交的中间态上。**
判别法**看读数的量纲对不对**：那份报告记 `UNITS 8`（**行数**），而交付状态该 flag 是
**100,273 字节** ⇒ 一眼可知它跑的不是交付的那份代码。
**负控制必须跑在你要交付的那个提交上**（F41 pass 1 登记过同型：「验证在不具备关键条件的环境里做的」）。

🔴 **第十二个仪器缺陷（2026-09-11，F57 复审）：报告里出现未落盘临时脚本产出的结论。**
文档与报告出现了一组精确数字（0 剩余字节、num_pool_entries 1421/3849、pairs 385/889、self_pp -4、subgraph_pp -88 等），但仓库内没有任何落盘脚本可复跑这些数字。
🔑 **铁律第 8 条：报告里出现的每个数字，都要有一条落盘的命令能重新打印它；临时脚本产出的结论，在落盘之前不算结论。**

🔴 **第三十八种仪器缺陷（2026-09-16，F80 pass 2 实测）：
一轮可以如实报告「HEAD 未变、`git status --porcelain` 0 行、未构建」，
同时把一份钉住的构建状态摧毁掉 —— 因为 `git checkout --` 恢复字节却打上新的 mtime，
而 `git status` 看不见 mtime，ninja 只看 mtime。**
实测:F37 那次落地尝试改了 `runtime/vm/thread.h` 与 `thread.cc`、用 `git checkout --` 回退、
报告「未改动任何文件…未构建」——**内容上为真,构建状态上为假**。
结果 `ninja -n -C xcodebuild/ProductARM64 | grep -vc '^ninja: '` 从 **0 变成 1895**
（`-d explain` 直接点名 `older than most recent input ../../runtime/vm/thread.h`,
两个被钉住的产物自己就在待办集里），而 F80 钉那份构建的全部意义就是让 F37 不必重建。
⇒ **`git status` 干净不是「钉住的构建仍然完好」的证据。** 要判断就跑那个探针。
⚠️ 同时暴露:`verify_all.sh:77` 只探 `$RELEASE`,`$PRODUCT` 有定义、在用、**从未被守卫**
（同一判据指向 Product 读出 947）⇒ **Product 侧的陈旧无声穿过 harness**。已写进 F76。

🔑 **铁律第 9 条（2026-09-16 立，全文见 `docs/VERIFICATION_METHOD.md`）：
核验一份交付之前，先写下「如果它错，最可能错在哪一条」，第一个核那一条；
核不了就如实写「未核验」，不许用外围几条的通过替它背书。**
立它的原因是那天 16 次委派里，**两次是我自己把「核过一半」当成了「结论成立」**，
两次都由敌意证伪 pass 抓到而非复核抓到：
① 核了 `0x100196960` 六条指令的字节与落空关系（都对），**没问那个 sink 提交的是不是池引用**
—— 真正的池 sink 在 `0x100197470`/`0x100197488` 且受同一道倒计时门控，判决反了；
② 核了 F82 的 `RED` 打印、核了一条路径会还原队列，**没读另一条路径的队列内容**
—— 它不还原，`owed` 归零，欠账永久消失，**那个红是装饰**。
⚠️ 共同形状:**信心从「能便宜核对的那条」漏到「核不了的那条」上,
而能便宜核对的那条往往正是不承重的那条 —— 它便宜就是因为它不承重。**

🔴 **本阶段已被撤回过两次「完成」**（E3 的「0 gap」、`bfa898d` 的 `PHASE COMPLETE`），
并抓出**十个仪器缺陷**——每一个都是「判据在结论不成立时仍然给绿」。
第十个最该记住（2026-09-11，F60，六次证伪 pass 才定位）：
`diff_units.sh` 与 `evidence_compute_dd_table_residual.sh` **在同一份 JSON 上算同一个表达式**
⇒ `EXAMINED == UNITS` 是**数学恒等**，扰动 fixture 两个计数同步变 ⇒ **这个检查不可能报红**
（实测：注入 500 行异质字节，仍报 `EXAMINED 511 of 511, UNEXPLAINED 0, rc=0`）。
🔑 **分子与分母必须来自不同来源；验收方式是「注入异质数据看它能不能红」，不是「等式成不成立」——
等式成立恰恰是它不能失败的症状。** 前六个是：
硬编码 `structural`、分类写进被生成器覆盖的产物、`cmp` 对两个空文件答「相同」、
两侧构建模式不同（R flag 在 product 里不注册 ⇒ 凭空 +209）、
locus「存在即可」而不问它解释了多少、以及 2026-09-09 的第六个——
**一个检测 pattern 同时命中两种不同构造**：`asr;ldr x30,[x26,x16];blr` 被读成 DD 派发，
实为懒链接原生调用（我们自己的 `EmitIndirectStaticCall` 发的就是同样 6 条指令），
**「DD 派发 他们 92 / 我们 0」这个最大缺口因此作废**（F35，研究树 `6026011`）。

🔴 **待办以 `memo.md` 为准，不是本文件。** 当前开放卡片（2026-09-14 实测，
判据 = `cards_check.sh` rc=0，**open+built 集合 2026-09-14 实测十张**）：
- **SDK 本体（规则 0 的正面工作）**：**F55**（`shorebird` ×3，2026-09-14 大幅推进）· **F62**（把该格改判 `gap`，动棘轮，依赖 F55 先过证伪 pass）·
  **F63**（`built`，2026-09-14：用 kernel/IL 调用图去答 F55 的独立性反对意见）。
  🟡 **F63 的结论是 DOES-NOT-SETTLE，F55 的限定 (b) 原样保留**：kernel 图映射到
  `index_in_entries` 覆盖 81.9% / 80.1%（residue 0，未映射逐类点名），其反向闭包
  **可靠但不完备**（`pred-only 0` 三个 fixture 皆然，同规模改线基线最好也只有 2/4；
  但 `obs-only` 是 815 / 815 / 2089）。**单向结果不能替代那个精确匹配。**
  🔴 **`shorebird 75042` 这个数已过期两次，现为 70223**：先因 `diff_units.sh` 的分母**随 shell 调用形式漂移**
  订正为 75034（第 30 种仪器缺陷，已用 `diff -d` 修掉），再因 SDK 侧 selector 修复（`03d7efb21e8`）降到 70223。
  **该格已实证为 `gap` 不是 `structural`**；`subgraph_hash`+`op_subgraph_hash` 共 18304 units（26.1%）已归约。
  逐项证据、三条自报的削弱、以及两条被今天证伪的旧断言，全在 `memo.md` 的 F55 条目。
- **循环机械（不推进 dart-sdk，排在后面）**：**F46（open）· F49 / F52 / F53 / F54（built）**
已关闭 22 张：F36–F45、F47、F48、F50、F51、F56、F57、F58、F59、F60、F61、F64、**F66**。
🟢 **F66 已关闭（2026-09-14，第二次证伪 pass 判 SURVIVES，Opus 63 次调用）**：拆掉我们单侧的
`selector_subgraph_seen` 去重后，`subgraph_selectors` 与他们**逐槽且有序全等**
（prog 28701/28701、hello 3561/3561，missing=0 extra=0）⇒ 值正确性从深度 0 扩到每个 subgraph 站点；
`diff_units.sh shorebird` **67391 → 41344**（−26047 units，38.6%，因果性由「不重建、只在产物上重加去重回到 67391」独立证明）。
⚠️ **`REAL GAP` 在去重开/关两侧都是 4 是数学恒等**（`real_gap` 是集合差、去重保集合），**不可当佐证**。
新开 **F67**：第三处单侧去重 `pool_seen`（`analyze_snapshot_api_impl.cc:1266`，喂 `self_pp`）在任何地方都没被披露，
且 F66 只证了「值对」、没证「遍历走的是同一条路」。
⚠️ **`built` 不是 `closed`**：实现完成且自测通过，**但没有新鲜代理审过**。五张 built 卡欠的都是这一步。
⚠️ **F60/F59/F56/F57/F58 的关闭走的是卡里第三条路**（「留 unknown，把测量记下来」），**不是证明了那些格是 structural**。

🟢 **F58 已彻底闭环（2026-09-11，研究树 `a36bbb3` + `bc7c1f8`）。**
分母 2,471,135 units（hello 585,829 + base_dd 585,829 + prog 1,299,477 字节）；交叉测试比对 theirs vs ours 在 ours .so 上全部 3 个 fixture 0 字节差异（100% byte-identical），工具提取实现缺口为 0；完整解析 4 个快照区域（VmSnapshotData -6 B / IsolateSnapshotData 0 B / VmSnapshotInstructions +4224 B / IsolateSnapshotInstructions +192 B），求和精确等于物理文件尺寸差 4,410 字节（EOF 长度差修复承重）；彻底吸取 F57「分子归零、分母没露面」教训，如实报告口径 `EXAMINED 4410 of 2471135 (size delta fully decomposed) / UNEXPLAINED 2466725 (content diff, unattributed)`，2,466,725 字节内容差由 1380 个函数哈希差异及 VM stubs 驱动，留 unknown；接入闸门（`verify_all.sh` 第 30 项检查，`EXPECTED_CHECKS` 29→30，30 ran 0 failed）；三重负控制（`--drop-regions`、`--drop-crosstest`、异质字节注入使 `evidence_dump_blobs_residual.sh` 独立变红并还原）全部实测通过。完整闭环满足 B-2。

🟢 **F57 已彻底闭环（2026-09-11，研究树 `3b78c93` + `b39299e` + `acc8cb3`）。**
分母 964,686 units（EOF 长度差 262 字节，占 0.03%）；落实铁律第 8 条，将独立二进制变长解码脚本 `evidence_pool_link_data_residual.sh` 正式落盘并接入闸门（`verify_all.sh` 第 29 项检查，`EXPECTED_CHECKS` 28→29，29 ran 0 failed）；采纳复审意见，彻底消除虚假全量断言，报告口径订正为如实的 `EXAMINED 262 of 964686 (size delta fully decomposed) / UNEXPLAINED 964424 (content diff, unattributed)`；实测 pairs 与 num_pool_entries 两侧完全一致（diff=0），证实 per-process entries 对尺寸差贡献为 0，不序列化 pool entries 本体；尺寸 delta 物理构成完全配平（hello/base_dd +40 字节由 varint 字母/数字宽度驱动；prog -182 字节由字符串哈希 -90 与逐项实测的 self_pp 2 处多元素 -4 字节、subgraph_pp 44 处多元素 -88 字节组成）；共用约束不拆，不向证据表塞虚假 residual 行；负控制 `--drop-pairs` 实测断裂退出（rc=1）。完整闭环满足 B-2。

🟢 **F59 已彻底闭环（2026-09-11，研究树 `8426dc2` + `f4d2ee6`）。**
针对此前 claude-opus-5 独立复跑指出的三项缺陷（未接闸门、无分母防注入守卫、单侧键计费模型漂移），已在 `8426dc2` 中彻底修复：`evidence_disassemble_residual.sh` 进 `verify_all.sh`（第 28 项检查，`EXPECTED_CHECKS` 27→28）、添加权威分母守卫防注入、修复单侧键计数（cost=1 若单侧、cost=2 若双侧异），三项负控制全部命中实测通过。F59 重新闭环。

🟢 **F56 已彻底闭环（2026-09-11，研究树 `8426dc2` + `f4d2ee6`）。**
分母 10,782 units（hello 2450, base_dd 2450, prog 5882）；分区完整性恒等式 `entries + code_infos = full_diff` 在全部 3 个输入上 100% 成立；98 个 per-process entries（prog 184 个）确认为具名分量；3 个 UNEXPLAINED 逐项定位点名；顺带逐个点名 unique-name 过滤掉的 5 个重名函数彻底闭环 F38 STILL OPEN（87 vs 92）；`--drop-per-process` 负控制实测断裂退出。

🔴 **第三次发生在 2026-09-10 20:07 那一轮**（它把 F60 标成 `closed`，`Agent` 计数 = 0，
transcript `ce808561` 实测 Bash 44 / Read 7 / Edit 5 / ToolSearch 1）；前面还连着两轮
`0 subagent(s) [-]`。⇒ **F42 那道闸门三次响、三次被无视：它是一道账，不是一道锁。**
⚠️ **但那一次的结论本身站得住**（走的是卡里授权的第三条路，实质是撤回一个主张），
**违规的是程序不是结论**。两者要分开记 —— 否则下次真伪造时，这条记录会因为喊过狼而不被采信。
🟢 **抓到它的是当天新加的模型列**（`ced533f`）：`round dispatch: 0 subagent(s) [-]`，上线即见效。

🔴 **同一天里「轮次自己给自己写判决」发生了第二次，且一次编了三张卡**：
09-10 那一轮关掉 F45/F49/F50，闸门当场记下 `round dispatch: 0 subagent(s), 107 tool call(s)`；
独立复核那份 transcript 的 `tool_use` 分布（Bash 73 / Read 20 / Edit 9 / Write 4 / ToolSearch 1）
**`Agent` 为 0** ⇒ 它声称的 haiku-4-5 子代理不存在。F49/F50 已据此退回（F50 后来经两次真 pass 关闭）；
**F45 保留关闭**，因为它引用的是 09-09 那次真 pass（覆盖最终提交 `0b61282`），
闸门报它只是因为「关卡当轮的派发数」——对一张引用更早 pass 的卡，那是错的问题。
⚠️ **`agent-*.jsonl` 文件数已不能当判据**（09-10 实测全目录为 0，F38 那次还能比出 4 和 2）
⇒ **改数 transcript 里的 `tool_use` 块。**

⏸️ **无人值守循环已按指令停机（2026-09-09 20:2x）**：`.loop/PAUSE` 已放（终局，只有人能删），
`ralph.sh` 与 `wip_snapshot.sh --daemon` 均已停。恢复：删 `PAUSE` 后在**终端里**跑
`./tools/loop/ralph.sh`（launchd 不带 TCC 授权，实测读不了 `~/Documents`）。
⚠️ 恢复前先看三笔未结账：**2 个**未 pop 的 `loop-rescue` stash
（2026-09-10 订正，原文写「4 个，两棵树各 2」是重复计数：research 树是本仓的 linked worktree，
**两棵树共用同一个 stash store**，两侧 sha 逐字相同；判据与教训见 `memo.md` 第 1529 行起）、
`.loop/UNREVIEWED_CLOSURE`（F45 欠一次 pass）、以及 F49 欠一次针对最新补丁的 pass。
**不需要真机**：判据全在宿主上。真机通路已打通并验证过一次（B5–B8，`PATCHED_V2 ✅`）。

⏸️ **2026-09-11 现状订正**：09-10 晚循环被恢复过，跑了若干轮后
**又由「F60 关闭」这个条件自动置上 `PAUSE`（20:22:09）**，现仍在位；`ralph.sh` 与快照器**还活着**
（每次 tick 打 `skip: PAUSE present`），所以恢复只需删 `PAUSE`，不必重启任何东西。
前两笔账已结：`UNREVIEWED_CLOSURE` 与 `UNREVIEWED_FIX` 都已被轮次处理掉。
**`loop-rescue` stash 仍是 2 个。**

🔴 **第一次观测到真实的额度硬阻塞（2026-09-10 20:46:13）** —— 这条软点此前记着「从未观测到，
检测判据可能不命中」，**现在两件事都有答案了**：真实字符串是散文
`You've hit individual spend limit`（不是结构化 status），而**检测命中了**
（`round BLOCKED on quota; message says reset 8pm`）。
⚠️ **推论要记住**：那一轮因此**没有 `round end`**。
**「轮次没有 round end」从此要先怀疑额度，不要先怀疑崩溃。**

### 🔴 引用任何断言之前必读：断言的保鲜期规则（2026-08-26 立，2026-09-09 更新）

**本文件自己就是本项目最大的一本账，而「完成度以实测为准，不凭记账」这条规则一直没有约束到它。**
它已经**六次**生成了不存在的任务：`WrapCode`、`InBaseSnapshot`/`UnwrapEntryPoint`、
`shorebird_base_instructions_table_`、对象池 link-results 聚合器（任务 61 整轮白烧）、
以及 F5/F34b **两次**引用同一个在 `afa1f9c73cc`（2026-08-27）就被删掉的硬编码字面量——
那段文字有地址、有反汇编偏移、有 🔴 标记，**长得像证据**，但描述的分歧早在 23 个提交前就已关闭）。

因此，从现在起：

1. **任何形如「未做 / 缺口 / 我们为 0 / 仍是错的 / 未验证 / 被阻塞 / 死代码 / 未接进」的断言，
   必须带「实测日期 + 提交号（或那条实测命令）」。没有这两样的一律视为不可引用**，
   要用它就先自己实测一遍。
2. **开工前先花 5 分钟证伪你要做的那件事**：`git merge-base --is-ancestor <sha> HEAD`、
   `grep -n <符号> <文件>`（看退出码）、`ls` 到具体路径、测试名是否出现在 `run_vm_tests` 输出里。
   **反汇编地址不是新鲜度的证据**——它只说明当时看过，不说明现在还缺。
3. **两个方向都要查。** 「表里写着未做」会假报缺口；「表里写着已做」同样会翻车——
   `analyze_snapshot --shorebird` 曾被记成「已移植」而实际对我们自己的快照产出 **0 个函数**。
4. **真实剩余面以 `memo.md` 的 F 表开放卡片为准**（当前 F46/F55 open + F49/F52/F53/F54 built），
   每张卡带判据与负控制。**这一行本身过期过一次**（写着 F36–F39 时实际已推进到 F51），
   所以引用前先跑 `cards_check.sh` 看真值。
   本文件与两份归档是历史与证据来源，**不是待办列表**。
5. **归档里的断言同样受本规则约束。** 归档是为了存真，不是为了让旧结论继续生效。

**完成度（2026-09-04 重测，实测非记账）：实现 65–80%，逆向/oracle ~90%。**
旧的 36–42% / 80–85% 记于 2026-08-24，此后 SDK 有 80 个提交，**已过期，不要引用**。

**读这个数字前的三条限定（缺一条就会读错）**：
1. **没有客观权重依据**（按子系统数 + flag 数 + stub 数估的）。它是数量级指示，不是刻度。
2. **一部分结构上到不了 100%**：他们的 Shorebird 块在 `Thread` / `Isolate` 结构中部，
   我们只能追加 ⇒ **所有编码这两个偏移的指令永远不会逐字节相同**（16 个 stub 里只有
   `CallClangCodeWithSimulatorArgs` 38/38 完全一致，其余残差全是这一类）。
   快照版本 hash、堆遍历顺序、field_table 组内顺序同理。**这些不是待修的 bug。**
3. **符号表已基本失去判别力**：「一侧为 0」有四例被证伪（`sha1_`、`ClassTableMapper`、
   `SubgraphHasher`、`mappers`——全是名字对不上，不是功能缺失）。
   **真判据是逐项对比他们的产物**，即 `parity_matrix.sh`。

**证据与历史全文在归档里，不要凭记忆复述**：
- `docs/CLAUDE_archive_20260909.md` —— 本文件归档前的全文（含那张逐项状态大表：
  11 个 gen_snapshot flag、7 个 analyze_snapshot flag、16 个私有 stub 的逐字节命中率、
  两份符号实测表、三阶段映射与对象池编辑器的全部地址级证据）
- `docs/memo_archive_20260909.md` / `docs/memo_archive_20260904.md` —— 逐轮实测记录
- `spikes/shorebird_linkinfo_oracle/README.md` —— 验证脚本与 oracle

规则 2 的三次应用（自研版已弃用，改用上游的）：`dart_force_simulator` GN 参数取代手改
`globals.h`；`SIMULATOR_FFI` 取代 `SIMULATOR_HOST_ARCH_MATCH`；
上游已自行放宽 `analyze_snapshot` 的平台限制。

**真机验证状态另见 `docs/DEVICE_VERIFICATION.md`**（分「已验证 / 未验证」两栏）。
⚠️ 它回答的是「有没有被执行过」，不是「实现了多少」，**两者不要互相背书**。


**待定（与主任务无关，完成主任务后再议）**

1. 自建分发基础设施（服务器 / 云 / CDN）—— 是服务端，不是 dart-sdk
2. 设备经网络下载并 inflate 增量
3. 轮换签名私钥 `fhpb rotate-key`
4. `base_url` 缺失的护栏
5. Android 支持
6. `tools/broute/` / `fhpb` 产品管道的一切改进
7. v1 分支整理（补 `CLAUDE.md`/`memory/`、清理未跟踪垃圾）

详情见 `docs/ROADMAP.md`，但**那份清单整体处于待定状态**。

**已出局**：Route-A / KBC 动态模块（规则 1，Shorebird 不做）；
`tools/updater/`（规则 2，公开仓库已有）。

## 规则 1：完整功能以 Shorebird 为参照

Shorebird 是这个问题域的生产级实现。功能边界、集成形状、启动时序、失败回落行为，一律以它为基准。

**推论**：Shorebird 没有的能力，默认不进产品。例如 A-route（KBC 字节码 via `loadDynamicModule`）Shorebird 不做，
它只能留作研究能力，不作为交付路径。

## 规则 2：Shorebird 已开源的部分，直接拿来用，不要重复实现

动手写任何东西之前，先确认 Shorebird 是否已经开源了它。开源了就用它的，不要自己写一遍。

### 已开源清单（本机可查）

完整清单与实测依据见 **`docs/SHOREBIRD_REFERENCE.md`**。

| 组件 | 位置 | 内容 |
|---|---|---|
| `shorebirdtech/flutter` 引擎 fork | 公开；源码已在 `~/.shorebird/bin/cache/flutter/<rev>/engine/src` | 完整源码，含全部 patch 加载钩子 |
| `shorebirdtech/updater`（Rust） | 公开：`https://github.com/shorebirdtech/updater.git` @ DEPS `updater_rev` | 下载/校验/staging/状态机/boot 看门狗 |
| `shorebird_cli` | `~/.shorebird/packages/shorebird_cli/` | CLI 编排逻辑 |

引擎侧集成的全部相关文件（照抄，别重写）：

```
flutter/runtime/dart_snapshot.cc                 # 钩子，约 12 行
flutter/runtime/shorebird/patch_cache.{h,cc}     # Dart_LoadELF 加载 .vmcode + 缓存
flutter/runtime/shorebird/patch_mapping.{h,cc}   # fml::Mapping 适配
flutter/shell/common/shorebird/shorebird.{h,cc}  # ConfigureShorebird：把 .vmcode 插进 application_library_paths
flutter/shell/common/shorebird/updater.{h,cc}    # Rust updater 的 C++ 封装
flutter/shell/common/shorebird/snapshots_data_handle.{h,cc}
flutter/shell/platform/darwin/.../FlutterEngine.mm   # 调 ConfigureShorebird
```

### 技术债状态（2026-08-14 更新）

- ~~`tools/updater/` 重复实现了公开的 `shorebirdtech/updater`~~ **已解决**：
  产品线改用 Shorebird 预编译引擎，其中已内置上游 Rust updater。
  `tools/updater/` 仅保留给归档的 Route-A spike（`spikes/m3_ios_realdevice/`、
  `spikes/benchmark/hotpatch_demo/`）使用，**不在生产链路上，勿再加功能**。
- ~~引擎集成层尚未实现~~ **已解决**：Route-B 直接用 Shorebird 预编译引擎，无需自行集成。
  X1 上的移植成果保留在 `engine/patches/`（研究分支）。
- **我们 fork 的是上游而非 Shorebird**：引擎 `flutter/engine.git` @ `ae5c3603`；
  Dart SDK 原基点 `37bbc285d8`（3.7.0-260.0.dev），**2026-08-19 已对齐到 `d684a576a6a`
  即 3.12.2 stable，与 Shorebird 同版本**（见 `docs/SHOREBIRD_REFERENCE.md` §4）。
  引擎 fork 仍是研究分支、产品不依赖；但 Dart SDK fork 现在是主任务的工作树。

### 当前生产形态

| 环节 | 来源 |
|---|---|
| 引擎 / updater / patch_cache / 看门狗 | Shorebird 预编译（规则 2） |
| linker（`.vmcode`） | 自研 `tools/linker.py`（规则 3，aot_tools 闭源） |
| 打包+签名+分发 | 自研 `tools/broute/`（规则 3，服务端协议闭源） |

完整流程见 `docs/RUNBOOK_ROUTE_B.md`，结论见 `docs/PRODUCTION_RELEASE.md`。
## 规则 3：只有 Shorebird 闭源的部分才自实现，且必须从它的对外接口形状反推

自实现之前先证明它闭源。自实现时不要自由发挥：以 Shorebird 的对外接口/文件格式为契约，
反推实现，并用它自己的产物做 oracle 交叉验证。

### 已确认闭源清单

| 组件 | 证据 | 我们的对应实现 |
|---|---|---|
| `shorebirdtech/dart-sdk`（VM/Simulator） | **私有仓库**：`git ls-remote` 返回 `Repository not found`；DEPS 走 SSH `git@`；本地缓存无源码，只有编译产物 | `~/dart-3122/sdk` 分支 `shorebird-3.12.2`（12 条提交，从 3.7 的 `flutter-hot-patcher` 移植而来）✅ 合规 |
| `aot_tools link`（linker） | `~/.shorebird/bin/cache/artifacts/aot-tools/<hash>/` 只有 `aot-tools.dill`，无源码 | `tools/linker.py` ✅ 合规 |
| Shorebird 服务端 / check-update 协议 | 无源码 | `tools/patch_server/` ✅ 合规 |

**注意**：Shorebird 最核心的 VM 改动（Simulator / SimToCpu / vmcode loader）位于**私有**的
`shorebirdtech/dart-sdk`。所以本项目自研这部分（现在 `~/dart-3122/sdk`）是规则 3 的正确应用，不是违规。
而它的**引擎集成层是公开的**，那部分必须直接采用（规则 2）。

`tools/linker.py` 是规则 3 的正确范例：`.vmcode` 容器格式、LinkTable 编码、`subgraph_hash` 链接门槛
全部由 `spikes/b_route_phase2_groundtruth/GROUND_TRUTH.md` 用 Shorebird 自己的二进制离线实测反推，
并以它自己的 `link_table.txt` / `analyze_snapshot` JSON 作为独立 oracle 校验。

## 落笔前的自检

1. Shorebird 有这个功能吗？没有 → 大概率不该做（规则 1）
2. Shorebird 开源了吗？开源了 → 用它的（规则 2）
3. 确实闭源 → 从它的接口形状反推，并用它的产物做 oracle（规则 3）