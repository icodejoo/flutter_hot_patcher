# flutter_hot_patcher — 顶级规则

规则 0 决定**现在做什么**；规则 1-3 决定**怎么做**。四条都优先于本仓库其他任何文档、
计划或既有代码。与它们冲突的既有实现是待偿还的技术债，不是先例。

## 规则 0：当前主任务是复刻 Shorebird 闭源的 dart-sdk

在这件事完成之前，**所有工作都必须服务于它**。判断一项任务该不该做，先问：
它是否让「我们的 dart-sdk 更接近 Shorebird 的 dart-sdk」这件事向前走？答案不是「是」就别做。

**在做（服务于主任务）**

工作分支：**`shorebird-3.12.2`**（worktree `~/dart-3122/sdk`）。旧的 3.7 基线分支
`flutter-hot-patcher`（`~/dart/sdk`）只留作参照，新工作不在它上面做。

| 方向 | 状态 |
|---|---|
| **基线版本对齐** → 3.12.2 | **已完成**：36 文件移植 + 9 文件按规则剔除，`gen_snapshot` 编译通过，报 `macos_simarm64`（与他们同版本同平台串） |
| 用他们的产物做 oracle 交叉验证（规则 3 的方法） | **已打通**，且不需要版本对齐：`--print_*_link_info_to` 出二进制、`--print_*_link_debug_info_to` 出同一数据的 JSON |
| `print_class_table_link_info_to` | **byte-identical** |
| `print_field_table_link_info_to` | **内容全同**（622 条、多重集合相等），仅同 id 内顺序不同 |
| `print_dispatch_table_link_info_to` | **byte-identical**（commit `cd4aeecd189`，6 个 fixture 全对，product 构建下同样逐字节）。原先的 offset 差异已解决：`RowFitter::FitAndAllocate` 只在 **256 的网格**上发 offset。⚠️ 仍未验证装着这张更稀疏的表的快照**能否真正执行** |
| `load_obfuscation_map` | **已完成**：`--help` 与 flag 描述串均与他们逐字节相同。它是 **VM flag**（必须早于 kernel translation），不是 embedder API；计数器需重建，我们刻意不复刻他们的重发 bug（重复改名：我们 0、他们 8） |
| `print_dispatch_table_debug_info_to` | **已完成**——它在他们自己的二进制里就是死 flag（零代码引用），复刻方式就是声明它而不读它 |
| **DD 机制** | 我们仍为 0，但 ⚠️**2026-08-24 审计：旧描述「IL 指令 + IL 变换 + 建表 + slot 决议，上游零基础」四项里错了三项**。**没有 `DDTable` 类**——那 68 个符号全是 `IndirectStaticCall`，即**一个 IL 指令类的 19 个方法**被 nm 重复列出（对比：同一二进制里上游 `StaticCallInstr` 是 142 行 / 26 方法）；`DDTable` 的 8 个命中全是 `Precompiler::FinalizeIndirectStaticCallTable()::DDTableBuilder`，一个**函数内局部类**。**slot 决议已经是我们的**（`DDSlotVoters`/`DDSlotResolution`/`DDSlotMapping` 三个都实现了）。**上游基础不是零**——那 19 个方法就是 Dart IL 调用指令的标准契约，`StaticCallInstr`（`il.h:5562`）就是模板。~~→ 真实剩余面只有两项：`IndirectStaticCallInstr`（19 方法）与 `Precompiler::FinalizeIndirectStaticCallTable()`；加上一件真正不可见的：把 static call 改写成 indirect 的那个 IL pass 被完全内联、零符号。~~ 🟢 **【2026-08-26 实测：这两项加那个 IL pass 都已关闭，本行开头「我们仍为 0」同样作废】**判据：① `IndirectStaticCallInstr::` 去重方法名集合 diff 两个方向都为空（原始 `nm` 行数他们 42 / 我们 32 不可比——我们未 strip）；② `DDTableBuilder` **他们 8 / 我们 8**、`DDSlotMapping::` **2 / 2**（`nm -a … \| c++filt \| sort -u \| grep -cE`）；③ IL pass 已实现（`b13e2a0d54e`，`git merge-base --is-ancestor` → 0），常设检查 `dd_pass_check.sh` 与 `dd_runtime_check.sh` 在 `verify_all.sh` 里均为 **ok / 0 failure(s)**。****DD 机制已从 `EmitNativeCode` 确立**：`Thread+0x978` = `indirect_static_call_table_`，指令的 int64 字段（@0xc8）是它的索引（×8），原始 `Function`（@0xc0）仍进 static-call 表——**这就是可打补丁的原理**：表项可改指向，而记录的目标仍说明该调用原本是什么。⚠️ `@0xd8`（int32）含义**未确立**，且**不是** entry kind（那个硬编码 0）。两个 oracle 已就位：`--compute_dd_table` 格式已逐字节解出；`--print_dd_resolution_to` 的 `rewritten` 列（他们 2 / 我们 0）是变换的计数级判据 |
| `print_dd_function_identity_to` | **已完成**（commit `555cb48abd6`，2026-08-24）。⚠️ 2026-08-20 的旧记录「dump 的是 global object pool」**是错的**：raw object pool 有 1421 条，任何子集都凑不出 1380 行。正确读出点是 `Serializer::PrepareInstructions`，对应序列化器的 **code 表**（`analyze_snapshot --shorebird` 的 `functions` 数组，`index_in_entries` 0..1379）。行谓词（逐条实测零例外）：`IsAllocationStubCode()` → 行（kind=255，87 条）；`IsTypeTestStubCode()` → 无行（110 条）；`IsStubCode()` 即 owner 为 null → 无行（4 条）；owner 为 Function → 行（1179 条）。七个 fixture 上与他们**逐字节相同**（`cmp` 全过）。发出顺序也已复刻（commit `10bc4f54b6d`）：它是 **libc++ `std::unordered_map<intptr_t,…>` 的迭代顺序**——按索引升序插入，空桶插入把节点压到侵入式链表**头部**（所以不碰撞的键倒序出来，即 1379→29 那段 1187 行），`__do_rehash` 只搬新桶已被占用的节点（所以碰撞过的键永远黏在一起）；桶宽走 2/5/11/23/47/97/197/397/797/1597（不小于 2 倍前值的最小素数），尾部每个短 run 都是某个桶宽下的碰撞（47..48 在宽 47 时撞、97..103 在 97、…、797..825 在 797）。旧记录里「常数差 797」只是最后那组没看出成因。⚠️ 实现上**绝不能 `reserve()`**：桶宽历史就是顺序 |
| `print_dd_resolution_to` / `ShorebirdLinker::ResolveDDSlots` | **已完成**（commit `d1fd67bb607`，2026-08-24）。⚠️ 曾被记为「依赖 DD 机制」，与 `print_dd_function_identity_to` 一样因「名字里有 DD」被误判。slot 实际来自 DDSlotVoters 文件，不依赖 `IndirectStaticCallInstr` 或 DD 建表。实测：pass 2 的报告行**逐字节相同**；pass 1 各 resolution 计数器全同（key-map size 仅差 18：ours 2896 / theirs 2878，是 18 个函数的调用点时序差）；8 行分辨 TSV **全同**（包括各 slot 的 resolved function name）。已知缺口（**2026-08-26 复核，事实仍成立但理由已过期**）：`rewritten` 列我们发 **0**、他们读 **2** —— 判据 `./dd_pipeline.sh` 输出他们那行 `DD table: 8 slots, 7 retained, 2 rewritten, …`，我们那行 `# table_size=8 retained=7 rewritten=2 sentinel_filled=1` 中的 0 来自 `linker.cc:1159` 的**硬编码字面量** `" rewritten=0 sentinel_filled=%" Pd " rewritten_null=0\n"`。⚠️**旧理由「真正依赖 DD IL 子系统」已作废**：那个子系统已于 `b13e2a0d54e` 实现且 `dd_pass_check.sh`/`dd_runtime_check.sh` 常设通过；`linker.cc:1153-1155` 那条「which needs the DD IL subsystem we do not have」是**活得比工作久的过期源码注释**。→ 现在这是一件**有证据可依**的小活：把两个计数器接到已存在的改写路径上，而不是「缺子系统」。plurality tie-breaking 零覆盖（每个 fixture 每 slot 恰好一票）与 `refreshed`/`dropped-stale` 分支未能到达**仍然成立**（`dd_pipeline.sh` 两个 pass 均打印 `0 refreshed, 0 dropped-stale`）|
| FFI 缺口 | **已关闭**：上游 `SIMULATOR_FFI` 覆盖，7 条相关测试全 PASS（需 `--dfe=xcodebuild/ReleaseARM64/gen/kernel_service.dill`）；我们自研的宿主逃逸约 100 行**已按规则 2 删除**（它守在从未定义的 `SIMULATOR_HOST_ARCH_MATCH` 上，本就没编译） |
| 三阶段映射（link results → pair constraints → backfill） | **已完成**（2026-08-25，`8275b3de81f` + `26f299efa8f`）：两张表的三个阶段 + link-results 生产方全部解出并实现，`--print_shorebird_info` 的**八行报告与他们逐行相同**（类表 606/606/0/13、对象池 1121/1113/292/16），常设检查 `shorebird_info_check.sh`。🔑生产方是 `dart::groupBy<T>`（外联符号 `0x10019aa08`，签名直接给出）：类表按 `ClassInfo::hash` 分组（body 读 +0x20 不是 +0x08）、对象池按 `CodeInfo::op_subgraph_hash_`（+0x18），**两侧都只有恰好 1 个成员的组才配对**。⚠️对象池的 link results 是**索引对**不是记录对：配上的每对 CodeInfo 贡献其索引向量的逐元素配对再去重（1121 由此算出；1089/1378 都不对）。⚠️`self_pp` / `subgraph_pp` / 两者并集在**他们的** fixture 上都给 1121，**他们的 fixture 判别不出用的是哪个** —— **【2026-08-26 实测：这条已由自造 fixture 解决】**`make_op_fixture.py` + `op_aggregator_check.sh` 就是为此造的，选择规则（黏性 `csel`）已于 `ab58e28152d` 实现。✅**【2026-08-26 实测订正 · 已关闭】以下侦察段落描述的三处分歧，全部已于 `ab58e28152d` 关闭**（判据：`git merge-base --is-ancestor ab58e28152d HEAD` → 退出码 0，落后 HEAD `c316526c1cb` 23 个提交）。`linker.cc:449-534` 现在就是**加权投票**（`aggregator.AddVote(patch_indices[i], base_indices[i], weight)`，`weight = 1.0/(base_buffer.size()+patch_group.size())`）+ **无 `size()!=1` 过滤** + **黏性 `use_self_pp`**（回落到 `base_self_groups` 时才置位）。**任务 61 整轮白烧就是因为把下面这段读成了待办**——它有地址、有反汇编偏移、有 🔴，长得像证据，却没有日期或提交号可核对。**保留仅为记录证据来源，不是缺口**（`OP_AGGREGATOR_RECON.md`，逐条经我复验）：① `GetBestMapping` **自身没有符号**（`_ZN4dart28...GetBestMappingEm` 零命中），`nm` 的 8 条命中**就是那组 introsort 实例本身**（lambda 是它的局部类）——旧记「`nm` 只剩 GetBestMapping 这个符号」是把名字出现在别的符号*里面*读成了独立符号；② 排序元素是 `pair<unsigned long,double>`（mangled name 直接给出）→ 它是**加权投票**：`fmov d8,#1.0`@`0x10019c0e8`、`fdiv d9,d8,d0`@`0x10019c858`、`ldr/fadd/str d0,[x0,#0x18]`@`0x10019ca50-58`，即 `votes_[a][b] += 1.0/N`；③ 全函数**零个 `cmp #0x60`**（=sizeof(CodeInfo)）→ **没有「组只含 1 个成员才配对」这道过滤**，~~而我们 `linker.cc:376-378` 正是靠它~~ **【2026-08-26 实测：该过滤已于 `ab58e28152d` 删除，现在两边都没有】**；唯一的 `cmp x8,#0x1` 是 `csinc`→`max(count,1)` 的循环钳位（对象是 `asr #3` 的索引向量，不是 CodeInfo）；④ `self_pp`(+0x30) 与 `subgraph_pp`(+0x48) 之间是 **`csel` 条件选择**（`mov w8,#0x30; mov w9,#0x48; csel x8,x8,x9,ne`@`0x10019c818-20`，闸门是 `[sp,#0x5c]` 的 `tst #0x1`），**不是**「主路读 +0x48、失败回落 +0x30」——全函数**零个 `ldr [xN,#0x48]`**。🔓**`[sp,#0x5c]` 的条件已解出并经我复验**（穷举法，不是读 happy path）：该栈槽在 8184 字节里**恰好 4 次访问**——写 `str wzr`@`0x10019c4d4`(=0)、写 `str w8`@`0x10019c688`(=1)、读@`0x10019c518`、读@`0x10019c810`，故 `tst #0x1` 是对一个可证只取 0/1 的 bool 测试；含「写 1」的块（`0x10019c530`-`0x10019c68c`）**只有一条入边**（全函数仅 `b.eq 0x10019c530`@`0x10019c514` 一处跳进来，闸门是 `cmp x21,x24`@`0x10019c50c` 即 base 候选缓冲的 begin/end **是否为空**），且 flag=0 那条路被 `b 0x10019c690`@`0x10019c52c` 无条件跳过，落不进来。→ **flag=1 ⟺ base 侧该 `op_subgraph_hash_` 分组为空**（查表是 `operator[]`，缺键得空 vector 而非 miss）；随后块内读 patch 的 `self_hash_`(+0x00)、在 base-by-`self_hash_` 表里查、把该组接上缓冲，才置 flag。**它按外层组黏住**（唯一的写 0 被内层回边 `0x10019c4f8→0x10019c50c` 绕过）。结论：`off = flag ? 0x30(self_pp) : 0x48(subgraph_pp)`，即**base 的 subgraph 组还在时用 `subgraph_pp`，一旦回落到 self_hash 就改用 `self_pp`**。→ ~~我们 `linker.cc:379-381` 无条件用 `self_pp`，一般情况下是错的~~ **【2026-08-26 实测：已于 `ab58e28152d` 修好】**`linker.cc:449-534` 现在实现的就是这条黏性 `csel`，行号也早已漂移（该文件现有 1170+ 行）。⚠️**我自己在这里踩了「正则太窄＝假红」**：我曾用「全函数零个 `ldr [xN,#0x48]`」去否证 +0x48 的读取，但**这个偏移是寄存器施加的**（`add x8,x20,x8`@`0x10019c690`、`add x8,x19,x8`@`0x10019c87c`），立即数形式本来就不可能存在——否证一个断言，必须先确认自己的判据覆盖了它真实的编码形式。~~判别实验（他们的 fixture 做不到）：造一个含 2 成员组且 base 索引有争用的合成 `ObjectPoolLinkInfo`。原记录：未做~~ **【2026-08-26 实测：早已做完】**该 fixture 生成器是 `make_op_fixture.py`（10.6K），检查是 `op_aggregator_check.sh`（5.3K），两者都在 `~/Documents/fhp-research/spikes/shorebird_linkinfo_oracle/` 且**已在 `verify_all.sh` 的 16 项里**（`./verify_all.sh` → `ok op_aggregator_check.sh 0 failure(s)`）。`verify_all.sh` 自己的注释就写着「their fixture cannot tell weighted voting from the filter it replaced, so the aggregator needs a fixture of its own」。⚠️fixture 的 base.ct 与 patch.ct **逐字节相同**→ 单独用它测不到「配不上」的路径，所以检查另造了一份删掉 20 个类的输入（586/33，同样相同）。~~`print_shorebird_info` 的 **gen_snapshot 那半**被它阻塞。~~ **【2026-08-26 实测：两半都已完成】**`shorebird_info_check.sh` 在 `verify_all.sh` 里是 **ok / 0 failure(s)**，八行报告与他们逐行相同。⚠️**2026-08-24 订正：它只被阻塞了一半**——同名 flag 在**引擎**里门控 `Deserializer::PrintShorebirdStats`，那半**已实现**（`0bf2ef86f1c`）。~~⚠️**2026-08-24 查证：目前证据不足以按规则 3 实现它**~~ **【2026-08-26：已作废，聚合器已于 `ab58e28152d` 按反汇编实现，见本格开头】**——`gen_snapshot` 没有 dSYM（DWARF 只覆盖引擎），映射器整体被内联，`nm` 只剩 `ObjectPoolMappingsAggregator::GetBestMapping(unsigned long)`（带一组 introsort 实例，说明它对候选排序后取最优）与 `ObjectPoolEditor::InstructionCountNoPadding(ObjectPoolOp const&)` 两个符号。只凭 606/0/13 与 1113/292/16 六个计数去设计算法就是规则 3 明令禁止的自由发挥。**解锁路径是反汇编**（报告串在 `0x4bff11/0x4bff43/0x4bff67`），量级与 `RunOnSimulator` 相当。🔑**2026-08-25 订正：上一句「解锁路径是反汇编」是对的，而「证据不足」现在只对聚合器成立**——**编辑器那半已解**：`object_pool_editor.cc` 四个函数全部定位（`DetectObjectPoolOp` 884B / `LoadStoreFromSingle` 192B / `InstructionCountNoPadding` 420B / `AssembleReplacement` 1016B）。⚠️**这四个我们一个都没实现**——已落地的是它们调用的**上游** assembler 辅助 `InstructionCountForLoadStoreFromOffset`（`45e94243ce9`）。~~它在 `gen_snapshot` 里 0 个（无生产调用点）~~ **【2026-08-26 实测：现在是 2/2】**`nm -a xcodebuild/ProductARM64/gen_snapshot | c++filt | sort -u | grep -c InstructionCountForLoadStoreFromOffset` → **我们 2**、同口径他们 **2**（他们先 `lipo -thin arm64`）。⚠️**同一轮里那四个函数也不再是「一个都没实现」**——见本行末尾 `f426f46f5b0`。此前表里把编辑器那行记成「已实现」是记账错误，2026-08-25 实测订正，`struct ObjectPoolOp{int64 index; int32 kind}` 由三处独立解码互相印证，`Assembler::PadLoadStore`（~~我们 0 次~~ **【2026-08-26 实测：2/2】**`nm … | grep -c PadLoadStore` → 我们 2、他们 2，@`0x10024b2e8`）**已完整还原**：它在**上游** `assembler_arm64.cc:1310-1322`（两条 assert 串给出文件名、行号 1316/1322、条件），常量 `kObjectPoolLoadStoreMinInstructionCount` **两处独立算出 = 3**。⚠️两个不可从签名推出的细节：填充值是 **NOP**（`0xd503201f`）；退出判据的 `eor`/`cmp #3` 是编译器对 `emitted+expected==3` 的编码，**照抄异或就是抄优化产物**。只在 `base==PP` 补齐。~~**仍未写进树**：唯一调用方 `AssembleReplacement` 未解，单独落地就是死代码。~~🔓**2026-08-25 已解锁**（`OBJECT_POOL_EDITOR_RECON.md`，全部经我复验）：四个函数的**签名与地址已确证**（`nm` 逐条对上：`DetectObjectPoolOp(unsigned long, ObjectPoolOp&, unsigned long, int*)`@`0x1001a2720`、`LoadStoreFromSingle(Instr const&, unsigned int)`@`0x1001a2a94`、`ObjectPoolEditor::InstructionCountNoPadding(ObjectPoolOp const&)`@`0x1001a2b54`、`AssembleReplacement(compiler::Assembler*, ObjectPoolOp const&, unsigned long)`@`0x1001a2de8`；884/192 由地址差精确确认）。🔑**「死代码」这条阻塞已消失——唯一生产调用方是上游的 `dart::ImageWriter::Write`**（`0x1000bc568`，`image_snapshot.cc`，**我们本来就有这个文件**）：全 `__text` 的 BL 扫描共 13 处，其中 **10 处都在 `ImageWriter::Write` 体内**（`0x1000bc76c`..`0x1000bca4c`），另 3 处是族内自调（`AssembleReplacement`→`DetectObjectPoolOp`@`0x1001a2e2c`、`DetectObjectPoolOp`→`LoadStoreFromSingle`@`0x1001a2950`/`0x1001a2a5c`）。`ObjectPoolEditor` 其余部分被内联进 `ImageWriter::Write`。⚠️**`kind` 已穷举且是证出来的不是猜的**：每个臂装一个 `std::__func<…>` vtable，mangled name 直接拼出发射器名——1=`LoadWordFromPoolIndex`、2=`StoreWordToPoolIndex`、3=`LoadDoubleWordFromPoolIndex`(`Address::PairOffset`=3)、4/5/6=`LoadS/D/QFromOffset`(`OperandSize` 7/8/**11**，`kQWord`==11 不直观)；kind 1 分叉：`Rn==Rt || Rn==PP` 走 `LoadWordFromPoolIndex`，否则 vtable 尾调 `AssemblerBase::LoadFromOffset`(+0xc8)。尺寸**全部来自 `PadLoadStore`**，每个臂都以 `base=PP` 调用 → 每次替换恒为 3 条指令/12 字节。🎁**他们自带 oracle**：`ImageWriter::Write` 的循环在索引未变时会重新汇编并**逐字节自校验**，打印 `"Expected:\n"`/`"Actual:\n"`（两个串在二进制里各恰好 1 次，已验）。⚠️**ABI 陷阱**：五个符号全是 `t`（LTO 内部化），LLVM 改写了调用约定——`InstructionCountNoPadding(const ObjectPoolOp&)` 实到 `(x0=index, w1=kind)`，`PadLoadStore` 收到裸 `__func*`。**mangled name 才是源码签名，寄存器分配不是。**✅**2026-08-25 已落地并提交**（`f426f46f5b0`，7 文件 **1331 行**）：`runtime/vm/shorebird/object_pool_editor.{h,cc}` + 13 单测，`Assembler::PadLoadStore` + `kObjectPoolLoadStoreMinInstructionCount=3` 落在**上游** `assembler_arm64.{h,cc}` + 2 单测。全套实测：`verify_all.sh` **6 ran / 0 failed**、`run_vm_tests` **128 passed**（113→128）、`verify_reproduction.sh` 24 个产物仍逐字节相同（这是本改动最容易弄坏的东西）。三次负控制都变红后还原：`PadLoadStore` 循环界→1、kind-1 臂的 `rn==rt||rn==kPP`→`rn==kPP`、常量 3→4（后者只红 2 个测试——常量只管 padding，仅逐字节断言依赖它）。~~⚠️仍未接进 `ImageWriter::Write`，且这是真依赖缺失不是偷懒：那个循环要读 old→new 索引映射表，这张表的所有者未定（属聚合器那块），没有输入就接不上。~~ **【2026-08-26 实测：已接进，提交 `66a46515eb5`「the pool mapping's owner, and the image writer」】**调用点在 `runtime/vm/image_snapshot.cc:622`：`if (!ObjectPoolEditor::Edit(start, start + insns.Size(), mapping->data(), …`（判据：`grep -n "ObjectPoolEditor::Edit" runtime/vm/image_snapshot.cc` 退出码 0）。映射表所有者也随之确定。运行期覆盖由 `op_rewrite_check.sh` 与 `op_real_mapping_check.sh` 两项常设检查看住（`verify_all.sh` 中均为 ok）。⚠️**两处计数分歧已知**（只有跑起来才发现）：kind-3 index 62 发射器用 2 而计数器说 3；kind-1/2 offset 2²⁴ 发射器用 3 而计数器说 2，**后者是我们自己的错**（recon 里那个折叠 ladder 在 2²⁴ 之后读成 3）。两条记在 `ObjectPoolEditor_CountFollowsPrepareLargeOffset`，但用的是 `ASSERT` 而非 `RELEASE_ASSERT`——**release 构建里被编译掉了，是个软点**，待收紧。🔑**2026-08-25 二次推进**：(a) **三个阶段就内联在 `InitializeWithClassTableLinkInfo`（`0x100199928`，4320B）与 `InitializeWithObjectPoolLinkInfo`（`0x10019bd8c`，8184B）里**——两个都打报告，而报告是**四行不是三行**（漏记的是 `Mappings from Link Results`）；这解释了 `GetBestMapping` 为何没有独立符号。第五个私有文件名 `class_table_mapper.cc`。类表那趟的外联 helper 给出算法结构：`unordered_map<string,vector<ClassInfo>>`、~~`LinkedValue<T>` 模板（我们没有）~~ **【2026-08-26 实测：已有】**`grep -rc LinkedValue runtime/vm/shorebird/linker.h` → **7**、`linker.cc` → **7**、两张 `vector<bool>` taken 位图、`set<long>`、cityhash。(b) ⚠️**「映射器类型不在引擎 dSYM 里」只对映射器成立**——`link_info.h` 自己的类型**全在**（`Sha256Hash`/`CodeInfo`/`ClassInfo`/`IntervalInfo`/`SelectorRowInfo`，带偏移与声明行号），**`ObjectPoolLinkInfo` 格式据此已关闭并落地**（`26b5e5ed6c7`），他们两份产物**逐字节重现**（`op_link_info_check.sh`，判据是解码→重编码→比字节，不是解析到 EOF）。🔑🔑**2026-08-25 三次推进：类表映射器已解出并实现**（`7260c35198d`）——直接反汇编 `InitializeWithClassTableLinkInfo` 拿到全部算法：`vector<intptr_t>(n,-1)` + stage1 按 pair 直写并在 `vector<bool>` 占位 + stage3 给剩余的分配最小空闲 cid；复现他们公布的 **606/0/13**。🔑**中间那个阶段是结构性缺席**（计数器清零后无任何路径再碰它），所以类表报 0、对象池报 292 —— **对象池是另一个函数**（`0x10019bd8c`，8184B），那才是剩下的工作。⚠️`LinkedValue<T>` = base/patch 对（由两处 `vector::size()` 除法常数算出：112 vs sizeof(ClassInfo)=56、16 vs 8）。⚠️**引擎 dSYM 够不到映射器**（`ShorebirdLinker` 在引擎里 0 符号、DWARF 0 命中）→ 内联行号法在这里用不了 |
| **`LinkOracle`**（新发现，2026-08-24） | ~~我们为 0~~ **【2026-08-26 实测：已实现，见本格末尾 `94ee77c3624`；`nm` 给他们 0 / 我们 10，因为它是运行期类、他们的在引擎里不在 `gen_snapshot`】**当初 DWARF 给了整份头文件：`runtime/vm/shorebird/shorebird.h:27`，0x60 字节，`backing_`/`header_size_`/两个 `unordered_map<int,int>` 偏移缓存、`enum RunTarget{cpu=0,sim=1}`、`struct RunTargetOffset{int64 offset; RunTarget target;}`、`fromBuffer`/`ReadHeaderSize`/`shared()`/`RunTargetFrom{Base,Patch}Offset`，连声明行号都有。它就是 **`.vmcode` link table 的运行期读取方**，与 `tools/linker.py` 写出的格式是同一份契约。**已实现**（commit `94ee77c3624`）：`runtime/vm/shorebird/shorebird.h` + `runtime/vm/shorebird.cc`（文件配对照抄他们的），13 条单测 + 负控制（把命中分支从 cpu 改成 sim 恰好 2 条变红）；`Dart_ShorebirdLoadVmcode` 已接上安装它，不是死代码。两处刻意偏差已在头文件标注：`Install()` 是我们加的（他们的安装方尚未还原）；`RunTargetFromBaseOffset` 在他们引擎里是**死方法**（DWARF 有声明、无任何内联实例、无外联符号），我们的实现是对称读法、未经验证 |
| `WrapperAllocator` | **已重写到上游 `ffi_callback_metadata` 机制上**（它就是这个类的祖先，规则 2）；修掉页泄漏与 remap 越界读；API 改成他们 DWARF 的形状。⚠️**「符号 0 = 无调用点」已证伪**（2026-08-24）：`stub_code_compiler_arm64.cc` 实实在在实例化了 `fromTemplate<WrapperLayout<{CPUToSim,SimToCPU}Config>>` 两个配置，两边产物里 `TransitionDartToCpuIfNeeded`/`TransitionDartToSimulatorIfNeeded` 字符串**各出现恰好 1 次**；我们为 0 只是因为编译器把 `fromTemplate` 内联掉了（他们那边是写在 `fromTemplate` 里的 lambda，才留下 `__func<>` 外联实例）。**🔴 2026-08-24 两条都已作废**：(a) CPU→Sim 272 字节 body **早已转写完成**，那句「仍是占位符」是活得比工作久的过期注释（同一文件里还有第二条同型的）；(b) **`AllocateMetadata()` 现在有生产调用点了**（`1f836a400a6`）——`Deserializer::WrapperForRunTarget` 的两个 lambda，且**实测会被执行**：每个 app entry point 都过 wrapper，把存进 metadata 的目标改坏 4 字节则每个用例段错误 |
| 两个方向的 wrapper stub | **两个方向都已有真 body**（CPU→Sim commit `516d56e80ef`，2026-08-24）。两个 stub 尺寸与他们完全相同：16384 / 16380 = 2014×8+272 与 2044×8+28。Sim→CPU 28 字节：7 个字里 6 个逐字节相同。CPU→Sim 272 字节：**68 条里 60 条逐字节相同**，另外 8 条编码 Thread 偏移、只有位移字段不同（他们的 Shorebird 块在 0x8d8..0x900 结构中部，我们只能追加）——这是结构性差异，不可关闭。转写来源是他们**发射出来的 stub**（`objdump -d` 产出的 .so 带 stub 名），不是生成器；所有位移都已解析成具名字段（`WRAPPER_STUBS.md` §9/§10），`str x11,[x10,#0x310]` 是写 `Simulator::pc_`。新增 4 个 Thread 字段。负控制：把 `mov x0,x10` 改成 `mov x0,x11` → 单测 exit 255 |
| **Deserializer 的 Shorebird 面**（新，2026-08-24） | **大部分已实现**：`EntryPoints`(48B, ctor 逐条转写)、`WrapperForRunTarget` 两臂、`Stats`+`PrintShorebirdStats`、`instructions_type_{vm,app}` 闸门、`ReadIndirectStaticCallTable`。字段名与 ctor 参数表全部来自**他们引擎的 dSYM**（`Deserializer+0xc0..0xd8`）。⚠️**2026-08-25 实测订正：原记的三项「未做」全部已完成**——`WrapCode` 在 `app_snapshot.cc:817`（`1076a3598b6`，方法见 [[reference-dwarf-inline-call-lines]]）且**有真调用点**（:9943）；`InBaseSnapshot`/`UnwrapEntryPoint` 已实现并在 `shorebird_test.cc:541-588` 有单测。此行「未做」是活得比工作久的过期记账 |
| **patch 加载链路**（新，2026-08-24） | 三个 C 入口已实现（`Shorebird_ReadLinkHeader`/`SetBaseSnapshots`/`UsingLinking`，`b283033b4df`）。🔑 **调用方是开源的**——引擎源码就在本机且 revision 匹配（`patch_cache.cc:39`、`shell/.../shorebird.cc:93`），这部分**不需要逆向**（规则 2）。⚠️**2026-08-25 实测订正：`shorebird_base_instructions_table_` 已建出**（`60cec3c40c2`，字段在 `app_snapshot.cc:1029`、接线在 :9336、`:9637` 打 no/yes），成功路径已进常设回归（`efa07a3774e`）|
| Simulator / SimToCpu / SimBridge | 已移植到 3.12.2，`.o` 也确实生成了；`nm gen_snapshot` 为 0。⚠️**2026-08-24 订正：一半是找错了二进制**——wrapper/allocator 是**运行期**设施，本来就不该出现在 `gen_snapshot` 里；它在引擎里，`Flutter.framework` 有 `WrapperAllocator::AllocateMetadata()` @0x7d0728，被 `Deserializer::WrapperForRunTarget(LinkOracle::RunTarget)` 的两个 lambda 各调一次（反汇编实测只有这 2 处）。所以「接调用点」是**运行期**的事，且要先有 `LinkOracle`。**2026-08-24：已接上**（`1f836a400a6`），两个 allocator 挂在 `IsolateGroup` 上（他们的名字：`shorebird_cpu_to_sim_wrappers_`@0x8d0 / `shorebird_sim_to_cpu_wrappers_`@0x8d8） |
| `Dart_ShorebirdLoadVmcode` | B2 已移植 |
| `analyze_snapshot --shorebird` | 🔴 **「B4 已移植」曾是一句空账**（2026-08-25 实测订正）：它在树里、`--help` 里没有、而且**对我们自己的快照产出 0 个函数**——因为它遍历堆找 `Code`，而 bare-instructions AOT 下 app 函数根本没有独立 `Code` 对象。同一个二进制在上游默认模式下还会 **abort**（4 个无名 stub 撞 `UNREACHABLE`）。**现已真正可用**：改为枚举 `InstructionsTable`，我们的快照给出 **1589 个函数**，首条 `offset 128/size 44` 与他们逐字相同；`self_hash` 换成复刻算法后，与**他们的**哈希按 name+size 配对命中 **777/950**。🟢 **2026-08-26 订正：「`subgraph_hash`/`op_subgraph_hash` 仍是 `self_hash`、仍然是错的」这条已作废**——任务 59（`ee99498bfb1`）把 callee walk 做出来了，三个 hash 在**他们自己的 1380 个函数上 1380/1380 摘要相同**，判据是两段链（模型 ≡ 他们的 1380；我们的二进制 ≡ 模型，1589/1589），`subgraph_hash_check.sh` 常设 |
| **`--dump_object_pool` / `--dump_object_pool_link_data`** | **已完成**（2026-08-26，任务 60）。两个 flag **都真注册过**（行为实测，不是 `strings`）：前者是 bool 走 `--out`，后者是**带自己路径的 string option**，不需要 `--out`。生产方 `GetObjectPoolLinkInfo`（他们 `0x10024cb9c`）三部分全部解出：① `self_pp_indices`/`subgraph_pp_indices` 就是同一趟 walk 的**池引用序列，保序且保留重复**（他们 1380/1380；去重只有 1250/932）；② `pairs` **不是扫代码扫出来的，是对象池 `entry_bits` 里的一个位域**——🔑 他们把上游 4 位的 `TypeBits` 缩到 2 位（bits 2..3），在 **bits 0..1** 插了一个 `PairPosition`（0 无 / 1 first / 2 second），三处独立印证（`NewFromBuilder` 的 `and #0xc; cmp #4`、JSON dumper 的 `ubfx #2,#2`、`AddObject` 拆 `kImmediate128` 时写的字面量 `0x11`/`0x12`）；标记点：`LoadNativeEntry` 写 `0x9`、`AddObject` 前言把**紧跟在 first-native 后面的任何一条**改成 second、`EmitInstanceCallAOT` 写 `0x05`/`0x65` 与 `0x06`、`GenerateTTSCall`（**推断，它全内联没有符号**）；92+6+287 = 他们的 **385**；③ `entries[].code` 是他们自己那份 `ObjectPool::DebugPrint`，多一条 `<%ld len string>`、`(raw)` 改叫 `(unknown)`。⚠️ **长串的阈值用 `Utf8::Length`、印出来的数字用 `String::Length()`**，两者混用会把 2112 印成 2844。实测：我们的 `pairs` 与他们**逐项相同（385/385）**、池大小同为 1421、1421 条 entry 里 **1323 条逐字相同**，其余 98 条全是**反序列化重写成本进程地址**的槽（92 个 `kResetToBootstrapNative` + 6 个 `kResetToSwitchableCallMissEntryPoint`），跨进程本就不可能相同。`op_dump_check.sh` 常设，`OBJECT_POOL_DUMP_RECON.md` 有全部地址级证据 |
| 真机 A/B：验证 C6 删掉 safepoint guard 后的安全性 | **单侧已实测（2026-09-03，`B5-swap`）**：iPhone 13 上装着由我们的 dart-sdk 编出的 arm64 引擎（LC_UUID `4C4C440F-5555-3144-A1C1-4D8732B23E93` 与构建树逐条对上）、以 `DART_INCLUDE_SIMULATOR` 代码生成模式运行，app 自报 `[B5_RESULT] PASS: 20000 iterations, 200000 GC objects`。可复跑：`tools/b5_device_test/build_and_run_b5.sh`。⚠️ **A/B 两侧（base vs patched）仍未测**，阻塞已定位：`B6-basesnap-crash` —— 只要 `Shorebird_SetBaseSnapshots` 注册 base snapshots，VM 就在启动时 signal 11，**与补丁无关**，有同二进制负控制（`FHP_NO_SETBASE=1` 跑通 / 默认崩）。宿主侧补丁链路已通：`tools/b5_device_test/build_ab_vmcode.sh` 用全自研工具产出 `out.vmcode`，link 100% |

### 🔴 引用本表之前必读：断言的保鲜期规则（2026-08-26 立，任务 62）

**本文件自己就是本项目最大的一本账，而「完成度以实测为准，不凭记账」这条规则一直没有约束到它。**
它已经**四次**生成了不存在的任务：`WrapCode`、`InBaseSnapshot`/`UnwrapEntryPoint`、
`shorebird_base_instructions_table_`、以及对象池 link-results 聚合器（任务 61 整轮白烧——
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
4. **真实剩余面以 `memo.md` 末尾的「真实剩余面（三分清单）」为准**，那份清单每项都带实测命令。
   本表是历史与证据来源，**不是待办列表**。

**完成度以实测为准，不凭记账**（方法与逐项数字见 spike README「How much is actually
reproduced」）：两边 `nm -a | c++filt` 数各私有子系统的标志符号。⚠️~~我们为 0 即真没写~~ **【2026-08-26：这条判据已被四例证伪，见本表末尾的口径说明——`sha1_`、`ClassTableMapper`、`SubgraphHasher`、`mappers`，全是「名字对不上」而非「功能没有」。「一侧为 0」现在只是**提示**，不是判据；真判据是逐项对比他们的产物。**
**2026-08-24 实测**（`nm -a | c++filt | sort -u` 双边同口径，他们先 `lipo -thin arm64`，我们 `--mode=product` 构建；他们 32373 / 我们 **33774** 唯一符号）。⚠️ 重测动机：19 轮里我一直在递增计数器而没重跑测量——规则要求实测，递增记账不算：

| 子系统 | 他们 | 我们 | 备注 |
|---|---:|---:|---|
| `link_info.cc` | 34 | 61 | 部分：class/field/dispatch |
| `linker.cc`（ShorebirdLinker） | **20** | **20** | **第一个标志符号达到持平的私有子系统**；`ResolveDDSlots` 本身 2/2 |
| `dd_voting.cc` | 12 | 非零 | `FunctionKey::` 4/8、`DDSlotVoters::` 2/6、`DDSlotResolution::` 4/10；product 构建下 oracle 已验证 |
| `DDFunctionIdentity`（类名） | **0** | **9** | **该类名是我们的发明**，他们没有同名类；按规则 3 这是已知的接口形状偏差，不是进展 |
| `wrapper.cc`（WrapperAllocator） | **34** | **4**（2026-08-26 实测，旧记 0） | ⚠️**这行数字不可用**（2026-08-24 审计；2026-08-26 复测：我们那 4 条**全是同一个析构函数**的 STABS 重复，`nm … \| grep WrapperAllocator` 只有 `~WrapperAllocator()`，其余方法同样被内联 → 结论不变，此行两边都零判别力）：34 里 32 条是两个 `fromTemplate` 实例的 `std::function` 样板、2 条是同一个析构函数；他们其余方法**全被内联**，`nm` 根本看不见这个子系统 |
| **`IndirectStaticCallInstr::`** | **19 方法** | **19 方法** | **持平**（2026-08-24，commit `ccad100b37c`）。判据是**去重方法名的集合 diff**，`comm` 两个方向都为空；原始 nm 行数 42 vs 30 不可比（我们未 strip）。⚠️ 别用 `DDTable\|IndirectStaticCall` 正则量它——会把 `DDTableBuilder` 算进来（第 8 种前缀污染的第二例）|
| `::VisitIndirectStaticCall`（3 个 visitor） | 3 | **3** | 集合相同 |
| `DDTableBuilder` | 8 | **8** | **持平**（2026-08-24 实测）。`Precompiler::FinalizeIndirectStaticCallTable()` 已实现并**真跑通** |
| `DDSlotMapping::` | 2 | **2** | **持平**：`ReadFromStream` 已实现，树里最后一处占位符已消除 |
| ~~mappers / field_hasher~~ `FieldHash` | 2 | **6** | 🟢 **【2026-08-26 实测订正，不再是缺口】**旧行「2 / 0 / 未变」已作废：`field_hasher.{h,cc}` 于 `ecd1e5b5b20` 落地（`git merge-base --is-ancestor` → 0），`nm -a … \| c++filt \| sort -u \| grep -cE "FieldHash"` 给**他们 2 / 我们 6**。⚠️「mappers」那半是**匹配串失效**不是缺口：`grep -cE "Mapper\|mapper"` 两边**都是 0**——他们的映射器全被内联进 `InitializeWith*LinkInfo`，我们的写成 `ShorebirdLinker` 的成员，**两边都没有同名类**，此行对「有没有」零判别力（第四例口径陷阱） |
| `LinkOracle` | **0** | **8** | 与 `DDFunctionIdentity` 同型：它是**运行期**类，他们的在引擎里而非 `gen_snapshot`，这一行两边都不构成判据 |
| shorebird stub 生成器 | 144 | **32** | =**14** 个 stub，**全部有真 body、尺寸与他们完全一致**（两个 wrapper + `ResumeOnCPU` 16B + `CallSimulatorFromFfiTrampoline` 124B + 三个 `SimulatorCall*Native` 各 136B）。逐字节命中率：CPU→Sim 60/68、Sim→CPU 6/7、CallSimFromFfi 29/31、三个 Native 各 27/34、CallToRuntime 32/39、ResumeOnSimulator 56/66、CallNativeThroughSafepoint 30/42、**CallClangCodeWithSimulatorArgs 38/38（首个完全逐字节相同）**、两个 Safepoint 各 72/73、RunDartOnCPU 80/87、ResumeInterpreter 12/13、Resume 40/48、ResumeOnCPU 1/4——**所有不一致都只是 Thread 位移字段**。⚠️「15 个私有 stub」是估数，`nm` 按名字给出的是 **16 个**（见 `WRAPPER_STUBS.md` §8 的完整清单）。~~我们只声明了其中 2 个~~ **【2026-08-26 实测订正：我们声明了 14 个】**`runtime/vm/stub_code_list.h:159-172` 连续 14 条 `V(...)`：`TransitionDartToSimulatorIfNeeded` / `TransitionDartToCpuIfNeeded` / `ResumeOnCPU` / `CallSimulatorFromFfiTrampoline` / `SimulatorCallBootstrapNative` / `SimulatorCallAutoScopeNative` / `SimulatorCallNoScopeNative` / `SimulatorCallToRuntime` / `ResumeOnSimulator` / `SimulatorCallNativeThroughSafepoint` / `CallClangCodeWithSimulatorArgs` / `SimulatorEnterSafepoint` / `SimulatorExitSafepoint` / `RunDartOnCPU`；另两个（`ResumeInterpreter`:84、`Resume`:195）是**上游 stub 被 Shorebird 改过**，本来就在列表里 → 合计 16/16，与「16 个私有 stub 全部有真 body」一致。旧文「只声明 2 个」与同格里「=14 个 stub，全部有真 body」自相矛盾，是过期记账 |

⚠️ **口径说明**：我们的计数高于他们之处**不代表进展**——我们的构建未 strip、带 STABS 重复符号，他们的已 strip。只有「一侧为 0」是有意义的判据。
⚠️ 两条口径陷阱：`sim bridge` 与 `subgraph_hasher`/`cascade_limiter` 在此表里两边都是 0，
前者是匹配串失效、后者在 `analyze_snapshot` 侧，**都不能读作「双方都没有」**。
🔴 **2026-08-25 已换二进制实测，后者是真缺口**：在 `analyze_snapshot` 里
`SubgraphHasher` **他们 12 / 我们 0**、`CascadeLimiter` **他们 18 / 我们 0**。
**这是目前仅剩的两个「一侧为 0」的私有子系统**，且是同一块工作
（`CascadeLimiter` 给 `SubgraphHasher` 的 walk 定界）。
🟢 **2026-08-26 重测订正，两条都不再是缺口**（同口径 `nm -a | c++filt | sort -u`；
他们 `analyze_snapshot` **17194** 唯一符号 / 我们 **24050**）：
`CascadeLimiter` **他们 18 / 我们 31**（任务 57 已落地）；
`SubgraphHasher` **他们 12 / 我们 0，但这是第三例口径陷阱，不是缺口**——
那趟 walk 的三个 hash 与两条 pp 列表全部实现且**逐项验证过**
（在他们自己的 1380 个函数上：`self_hash` 1380/1380、`op_subgraph_hash` 1380/1380、
`self_pp_indices` 1380/1380、`subgraph_pp_indices` 1380/1380），
只是我们写成 `analyze_snapshot_api_impl.cc` 里的自由函数（`ShorebirdSelfAndOpHashes` 等），
**没有同名类**。同批新增两处持平：`GetObjectPoolLinkInfo` 2/2、`Dart_DumpObjectPool` 4/4。
⚠️ 同批实测里 `sha1_`（他们 2 / 我们 0）**不是缺口**：我们有同功能的 `FhpSHA1Transform`，只是名字不同。
**「一侧为 0」是必要条件不是充分条件——名字对不上也会给 0。**
→ 三例同型之后（`sha1_`、`ClassTableMapper`、`SubgraphHasher`），
**符号表对「功能有没有」已经基本失去判别力**；真判据是逐项对比他们的产物。
⚠️ 曾按「已移植」记成 15–20%，实测发现那部分没进产物 —— **进度也要实测**。
⚠️ **第三条口径陷阱（2026-08-20）**：本表的「0」只能读作「产物里没有这个符号」，
**不能读作「这段代码没被编译」**——`static` 函数被内联后，编译与没编译在 `nm` 里一模一样
（`InvokeWithTHR` 就这样被我误判过）。要回答「有没有被编译」只能往 `#if` 块里插 `#error`，
并对一个已知会编译的块做同样的阳性对照。

私有子系统 **5/12** 有实质存在，其中 **2 个基本完成**（`linker.cc` 标志符号持平；stub 生成器 16/16 输出已逐字对比）、11 个 **gen_snapshot** flag 完成 **10.5** 个（`print_shorebird_info` 的引擎半已实现，只剩 gen_snapshot 半等三阶段映射；⚠️ **2026-08-25 订正：这个「11 个」只覆盖 `gen_snapshot`**——`analyze_snapshot` 那一组另有 7 个，**2026-08-26 已实现 7 个里的 7 个减 1**：`--shorebird`/`--out`/`--dump_class_table`/`--dump_blobs`/`--dump_object_pool`/`--dump_object_pool_link_data`，加上「文档化但按他们的样子刻意不注册」的 `--no_pp_hash`；**只剩 `--disassemble`**，它曾实现后**回退**——撞上 VM 自己的同名 flag。`analyze_snapshot_help_check.sh` 现在是 **12 documented / 3 lines withheld**，上一轮是 7/14）、**16 个私有 stub 全部有真 body**（14 个是他们新增的；2 个是上游 stub——`ResumeInterpreter` 开箱即中 12/13，`Resume` 被 Shorebird 加了 18 条）。逐字节命中率：CallClangCode **38/38**、两个 Safepoint 各 72/73、RunDartOnCPU 80/87、CPU→Sim 60/68、ResumeOnSimulator 56/66、Resume 40/48、CallSimFromFfi 29/31、CallToRuntime 32/39、三个 Native 各 27/34、CallNativeThroughSafepoint 30/42、ResumeInterpreter 12/13、ResumeOnCPU 1/4、Sim→CPU 6/7。**所有不一致都只是 Thread 位移字段**——他们的 Shorebird 块在结构中部、我们只能追加，属结构性差异，不可关闭。
→ **实现约 36–42%**（2026-08-24 一轮内的多项落地；⚠️**这次上调的主要不是新面积，而是「原本就存在的东西现在接上了、并且真的在跑」**——DD 全链路、wrapper 子系统、patch 加载入口。三阶段映射与 base instructions 一行未动）（2026-08-24 两次重测：先是 `DDTableBuilder`/`DDSlotMapping::` 持平，再是 `IndirectStaticCallInstr::` 19/19 集合相同。**DD core 能被符号看见的部分现已全部持平**。⚠️ 旧注「不代表机制能跑、零符号的 IL pass 量不到、没有任何测试构造过这个类」**已全部作废**：IL pass 已实现（`b13e2a0d54e`，方法见 `reference_differential_flag_oracle`），该类有 5 个单测真正构造并执行它，**整条链路已端到端跑通**——1043 函数 / 1622 处间接调用点，输出完全正确）；逆向/oracle 约 **80–85%**。

**读这个百分比之前，三条限定（缺一条就会读错）**

1. **没有客观权重依据。** 按「子系统数 + flag 数 + stub 数」估的，但 `wrapper.cc` 与 DD core
   的分量本来就不可等权。它是数量级指示，不是刻度。
2. **一部分结构上到不了 100%。** Thread 的 Shorebird 字段在他们结构中部、我们只能追加
   （见 `Thread::is_simulating()` 的注释），所以**所有编码 Thread 偏移的指令永远不会逐字节相同**
   ——16 个 stub 里只有 `CallClangCodeWithSimulatorArgs`（38/38）完全一致，其余的残差全是这一类。
   快照版本 hash、堆遍历顺序、field_table 组内顺序同理。**这些不是待修的 bug，是「两个 VM 必须
   完全一致」的代价，写进百分比只会让它永远差一截。**
3. 🔴 **这一条已从「几乎没有东西被执行过」翻转成「主链路都在跑」（2026-08-24 一轮之内）。**
   旧文写的是「16 个 stub 字节正确只证明抄对了不证明能跑、`AllocateMetadata()` 没有生产调用点」。
   现在实测跑通的有：
   - **DD 全链路**：建表 → IL pass → 表安装 → 表派发。1043 函数 / **1622 处间接调用点，输出完全正确**
     （`dd_runtime_check.sh`，自带 `--self-test`）
   - **wrapper 子系统**：每个 app entry point 都过 Sim→CPU wrapper，**每次运行被进入上千次**
   - **patch 加载链路的三个 C 入口**（`Shorebird_ReadLinkHeader` / `SetBaseSnapshots` / `UsingLinking`）
   ⚠️ **每一条的判据都是「改坏看变红」，不是「跑通了」**：把 wrapper 存的目标改坏 4 字节 → 全部段错误；
   把 polymorphic 偏移换成 monomorphic → 五个用例全红。**只有正向结果时，「跑对了」与「这段代码被绕过了」
   是分不开的。**
   🟡 **2026-09-02 部分翻转，两半要分开读**（实测，非记账）：
   · **「C1-C7 不在任何产物里」已作废** —— 用我们的 dart-sdk 编出了 iOS 引擎：
     `Flutter.framework/Flutter` **19,854,224 字节**、`lipo -info` = **arm64**、
     `ninja exit=0` 且末步是 `[504/504] ACTION //flutter/shell/platform/darwin/ios:flutter_framework`；
     `args.gn` 的 `dart_version = f174efefd55…` 就是我们树的 HEAD，`third_party/dart` 是指向
     `~/dart-3122/sdk` 的 symlink。**C1-C7 现在在一个真实的 arm64 产物里。**
   · **真机通路也已打通**：设备 iPhone 13 / iOS 26.5.2 / UDID `00008110-000868212686601E`，
     签名可用组合是 `CODE_SIGN_STYLE=Automatic` + **`DEVELOPMENT_TEAM=WAL983V9MH`** +
     `-allowProvisioningUpdates`（证书是 `Apple Development: Cruz Jr (MGDM32NW4K)`）；
     **Intune MDM 不拦装机**（曾是最大未知，已证伪）。
   ✅ **2026-09-03 更新：「真机零实测」已作废** —— `B5-swap` 关闭，C1-C7 已在真机上执行并给出正确结果（三条物证见 `memo.md` 末尾）。⚠️ **仍然成立的**：**A/B 两侧对比（base vs patched）仍是零实测**，下面这三段路当时的描述已被走通，留作历史。
   已装机跑通的那个 app 用的是 **stock Flutter 3.38.10 的 JIT 引擎**，与我们的复刻 VM 无关。
   要真测，还差三段：编 host 引擎（`gen_snapshot` 在那半）、加 `dart_force_simulator=true`
   重编 iOS 引擎（不开这个 flag，Simulator/wrapper/C1-C7 在真机上根本不会被执行）、
   `--local-engine` 出 release app。⚠️ **AOT/JIT 口味不可混**：Debug app 装的是 kernel + JIT 引擎（39 MB），
   我们的是 AOT（19.8 MB），互换起不来且报错与要测的东西无关。
   → **这仍是唯一一条会让百分比在真机上大幅缩水的**，只是阻塞点从「没有产物」移到了「没有验证」。
⚠️ **不要把这次上调读成「进展加速」**：三阶段映射一行未动（仍无证据可依，`gen_snapshot` 无 dSYM）。
**DD core 做掉的是小的那一半**：`FinalizeIndirectStaticCallTable`（8 符号）已持平，
但 `IndirectStaticCallInstr`（42 符号）仍为 0，且那个把 static call 改写成 indirect 的 IL pass
**零符号、完全不可见**。表建出来了，**但没有任何调用点会去索引它**。
⚠️ 两个百分比都是估计值，**没有客观权重依据**。stub 生成器符号 **32 vs 144 也不能读作「完成 22%」**——我们多个 stub 共用生成器，且我们的构建未 strip。**stub 的真判据是输出逐字对比，不是符号数。**

**三类差异本质上要求两个 VM 完全一致**，是完成度的*度量*而非可单独攻克的任务：
快照版本 hash（`568671cd` vs `839937dd`）、堆遍历顺序、dispatch table offset 分配。

规则 2 的三次应用（我们的自研版已弃用，改用上游的）：`dart_force_simulator` GN 参数
取代 A1 手改 `globals.h`；`SIMULATOR_FFI` 取代 `SIMULATOR_HOST_ARCH_MATCH`；
上游已自行放宽 `analyze_snapshot` 的平台限制。

详见 `spikes/shorebird_linkinfo_oracle/README.md`。

**真机验证状态另见 `docs/DEVICE_VERIFICATION.md`**（2026-09-03 起）。那份文档只记在真机上实际观测到的东西 + 每条的可复核物证，并明确分「已验证 / 未验证」两栏。⚠️ 它不改本节的两个百分比：它回答的是「有没有被执行过」，不是「实现了多少」。

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