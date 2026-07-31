<!-- 本报告由多 agent 评审 workflow 产出并对抗验证；主 agent 汇编。
     8 维度评审 → 每发现对抗验证 → 综合 + 完备性批判。
     发现 59 条，验证存活 52 条（REFUTED 已剔除）。 -->

> **修复状态**：S2 / S4 / S5 + 健壮性守卫 + 文档/标签 已就地修复（全语料回归无回归，见
> `PRODUCTION_LINKER_SPEC.md` §2）。**A2(arm64) 已就地修复并 spike 级验证**（`ARCH_CONFIG`
> 参数化 + 架构自动探测，P1 大样本在真实 Android arm64 反汇编上 closure==ground truth，
> 见 `ARM64_PORT_NOTES.md`；iOS arm64 待 Mac）。S1(池内容)、S3(实例级对齐)、S6/R4(ICF)、
> 批判#3(cid/dispatch) 仍属**生产 linker 需求**，排进 `PRODUCTION_LINKER_SPEC.md` R1–R9
> （做在 Kernel 层、排在 iOS W^X go/no-go 之后）。

---

# diff_linker.py 覆盖审查报告

审查对象：`spikes/gate2_linker/tools/diff_linker.py`（x86-64 / objdump 版 diff-linker）
红线：**SOUND**——绝不能漏掉一个真实改动（漏 = 设备跑陈旧机器码 = 生产事故）；其次才是 PRECISE（不过度转解释）。

下述条目已跨维度去重合并。severity 采用各 finding 的 corrected 值；`[CONFIRMED]` = 有对当前代码成立的具体复现，`[PLAUSIBLE]` = 机理属实但当前工具链无法复现（潜伏）。

---

## Tier S —— 静默漏判（对当前 x86-64 代码即可复现的 SOUNDNESS miss，产品红线）

这一层每条都能让工具对一个**真改动的函数打印 "equivalent"**，设备继续跑旧机器码，且无任何告警。

### S1. 对象池常量类改动整类漏报 `[CONFIRMED · high]`
合并：`pool-constant-masking` + `pool-wildcard-miss`（+ 撞名放大版 `ambiguity-multiset-pool-wildcard`）

- **是什么**：两层叠加。(a) 工具唯一的代码来源是 `objdump -d`（L100），只反汇编代码段，**从不解析对象池数据**——池内常量值变了、访问指令一字未动时永远不可见。(b) `normalize()` L148 `re.sub(r'0x[0-9a-f]+\(%r15\)', 'POOL(%r15)')` 把池 slot 索引也通配掉，连"改引另一个既有 slot"都掩蔽。`sig()`（L155-157）只比归一化后的助记符文本，`raw` 字节被 `parse_snapshot` 存进元组（L122）却从不比对——所谓 docstring L8 的 "byte-for-byte equal" 名不副实。
- **可见/不可见分界**：Smi 小整数走立即数（`x*3+1→x*3+2` = `add $0x1→$0x2`，**可见**，正是 patchleaf 用例）；double / String / 超 Smi 的 Mint / const 对象·List·Map / Type 字面量全走对象池，**整类漏报**。
- **复现**：`const fee = 0.07; double total(v)=>v*(1+fee);` 改成 `0.08`。`total` 里是 `movsd POOL(%r15),%xmm0`，两版 sig 相同 → 非 byte_changed → 判 equivalent → 设备继续用 0.07 算钱。字符串热修 `'hello'→'world'` 同样静默漏。
- **已文档化**：是（tools/NOTES L60-64、COVERAGE #3）。但文档给的正解"精确 slot→常量映射"对撞名 key 仍不足（见 S3）。
- **修法**：真 linker 必须解析对象池内容、逐 slot 比对两版同一 slot 的常量；补映射时注意别成为新漏报源（NOTES L64 已警示）。

### S2. 直调重定向到"同裸名不同函数"漏报 `[CONFIRMED · high]`
合并：`sig-drops-call-retarget` + `seed-samename-retarget` + `ambiguity-multiset-callname-wildcard`

- **是什么**：`parse_snapshot` L117-121 明明已用 addr_map 把 call 目标解析成 canonical key（元组第三元素 `target`），但 `sig()` L156 只遍历 `for _, m, _ in block` 用助记符、**丢弃 target**；`normalize()` L147 又把 `call 14d318 <parse>` 削成 `call <parse>` 只剩裸符号名。于是把调用从 `b.dart::parse` 改指到 `a.dart::parse`（两者裸名同为 `parse`——正是 NOTES L30 记的 12% 撞名场景）时：调用方两版归一化 sig 完全相同 → 条件1不命中；新目标本身未改、不在 must_interp → 条件2不传播（且 fixpoint L220 只读 `all_targets(patch[n])`，等价函数在设备上真正执行的是 **base 侧的边**，从未被校验——同一缺陷的另一面）。
- **复现**：`caller.dart: int run(x)=>helper(x);` 补丁仅把 `import 'b.dart'` 换成 `import 'a.dart'`（两个 `helper` 都 `@pragma('vm:never-inline')`、都被别处引用不摇树）。`run()` 两版仅 call 目标地址不同、符号文本同为 `<helper>` → 判 equivalent → 设备跑 base 的 `run`，仍调 b 的旧 helper。DWARF 模式与裸名模式都漏。
- **已文档化**：否。
- **修法**：`sig()` 把每条指令已解析的 canonical target 并入签名（如 `normalize(m)+'→'+target`），让 CanonicalName 的成果真正进入条件1；等价判定应额外要求 base/patch 两侧解析后的边集合相等。

### S3. 撞名实例 body 置换 / 池差异漏报（"multiset 相同=未变"不成立）`[CONFIRMED · high]`
合并：`ambiguity-multiset-swap`（CONFIRMED high）+ `multiset-permutation-unsound`（PLAUSIBLE，实际根因是 S1 池通配）

- **是什么**：L199-202 对撞名 key 用 `multiset(base)==multiset(patch)` 判等价，probe NOTES 宣称其 sound。**不成立**：多重集相等只证明两版"等价 sig 块的集合"存在双射，不证明"每个实例的 body→函数"映射不变。同一文件的匿名闭包共享同一 canonical key（key=`file::f.<anonymous closure>`，probe NOTES 明确 decl_line 刻意不入 key，兜底从未实现）。
- **复现（置换）**：`inc=(x)=>x*3+1; dec=(x)=>x*3+2;` 补丁互换两个 body。两版 multiset `{S1,S2}` 排序后相同 → key 判 equivalent、closure=0 → 设备 inc 仍返回 x*3+1。（因 `x*3+1` 走 Smi 立即数、`normalize` 不通配，此支独立于 S1 成立。）
- **复现（池差异，与 S1 叠加）**：`greetEn=()=>'Hello'; greetZh=()=>'Nihao';` 补丁只改 'Hello'→'Howdy'。两闭包归一化后均 `mov POOL(%r15),%rax` → multiset `{S,S}` 恒等 → 漏。
- **已文档化**：否（文档反向声称 sound）。count 变化的子情形是安全的（不同长度 sorted 列表永不相等）。
- **修法**：撞名 key 需实例级对齐（CanonicalName + decl_line/column），不能用无序多重集；条件1需并入 target 与精确池常量（见 S1/S2）。

### S4. `<sym+0xNN>` 次入口直调边丢失（条件2静默断链）`[CONFIRMED · high]`
合并：`edges-offset-entry-canonical-fallback`(CONFIRMED) + `calltarget-entry-offset-fallback`(CONFIRMED) + `ambiguity-propagation-target-fallback`(PLAUSIBLE) + `fixpoint-mixedkey-offset-entry`(PLAUSIBLE)

- **是什么**：Dart AOT x64 函数有多入口，TFA 去虚化直调常落在 unchecked entry（`call 9d62e <_StringBase.[]+0x16>`，demo 快照实测存在，low_pc=0x9d618）。`parse_snapshot` L117 正则 `<([^>+]+)` 剥掉 `+0x16`，L121 `addr_map.get(taddr, ...)`——但 `dwarf_canonical_map` 只登记 DW_AT_low_pc（L90-91，忽略 high_pc、无区间归属），`taddr=low_pc+0x16` 必 miss → 回退裸名。而被调函数按 low_pc 进 must_interp 是 canonical key `app.dart::Sq.area`。裸名 `Precompiled_area` 与 canonical key 永不相交（L220）→ 调用方字节又没变 → 判 equivalent。**只在 canonical 模式发作**（裸名模式两边都是裸名反而匹配）。
- **复现**：改 `Sq.area` 体，`useShape` 去虚化直调 `<Precompiled_area+0x18>`。area 进闭包，useShape 提出裸名、交集空 → 判 equivalent → 设备 useShape 原生码 pc-relative 直调旧 area。
- **潜伏说明**：v6-v8 全 PASS 说明那些用例的直调恰好落在 +0 入口；代码里 `[^>+]` 正则本身就预期了 +偏移形态，属随调用形态触发的雷。
- **已文档化**：否（但 REVIEW_diff_linker.md #5 已列）。
- **修法**：`addr_map` 用 low_pc/high_pc 建区间，任意目标地址向下取最近 low_pc 归属；至少对 miss 且带 `+偏移` 的目标打 mixed-key 告警。

### S5. 符号名含 `+`/`>` 被 `[^>+]` 截断 → 边键错位 `[CONFIRMED · high(operator+) / low(closure>)]`
合并：`edges-plus-in-operator-name`(high) + `edges-gt-in-closure-name`(low)

- **是什么**：同一条 L117 正则 `<([^>+]+)`。函数头正则 L104 `<(.+)>:$` 保留整名，而 call 目标正则遇 `+` 或内部 `>` 就截断：`<OpC.+>`（operator+，实测符号存在于 p1_sample manifest `mod0.dart::OpC.+`）→ 目标截成 `OpC.`；`<main.<anonymous closure>>` → 目标截成 `main.<anonymous closure`（少一个 `>`）。边键与函数键永不相等。
- **复现**：`class OpC{ @pragma('vm:never-inline') OpC operator+(o)=>...; } int sum(a,b)=>(a+b).x;` **裸名模式**下改 operator+ 体，`OpC.+` 进 seed，但 sum 的边键 `OpC.` → 不级联 → sum 判 equivalent。closure 名情形要求优化器直调闭包体（demo 中为 0，理论）。
- **已文档化**：否（operator+ 见 REVIEW #6）。
- **修法**：修正字符类/锚定——`+0xNN` 后缀应精确剥离而非用 `[^+]` 排除字符 `+`；`>` 同理。一处修好同时关掉两条。

### S6. ICF 折叠使被改函数落入 `removed`，而 removed 从不播种 `[CONFIRMED · high]`
合并：`icf-removed-not-seeded`(CONFIRMED high) + `icf-dedup-lastwins`(PLAUSIBLE med)

- **是什么**：p1 实测——Dart AOT 把整数常量入池，仅差常量的同构函数指令全同被 identical-code-folding 合并成一个块，且 DWARF 不为被折叠函数发 subprogram。若补丁把函数 R 改得与既存未变函数 F 字节相同，patch 里 R 被折叠、canonical key 消失，只在 base 侧 → 进 `removed = set(base)-set(patch)`（L190）。而 `must_interp = byte_changed | added | seed_ambiguous`（L210），**removed 不是任何一项**；fixpoint L217 只 `for n in patch` 迭代，base-only key 也永不被传播触达；`equivalent = set(patch)-must_interp`（L224）按 patch key 算，R 既不在 must_interp 也不在 equivalent——运行时对它零重定向，工具连 warning 都不打（removed 仅用于 L230 计数）。
- **复现**：`int half(x)=>x~/2; int rate(x)=>x*3;` 补丁把 rate 改成 `=>x~/2`。patch 里 rate 与 half 被 ICF 折叠、DWARF 无 rate DIE → `app.dart::rate` 只在 base → removed → 设备经 dispatch/tear-off 到 rate 仍跑旧 x*3。（直调方通常因 call 符号名变化被条件1捕获；虚调/dispatch/tear-off 路径漏。）
- **已文档化**：部分（COVERAGE #10、p1 NOTES 记 ICF 是 spike 局限）；"落 removed 且从不播种、无告警"这一具体机理未文档化。
- **修法**：真 linker 从 Kernel 层做 ICF 感知的对齐；至少 `removed` 非空或"折叠导致 key 消失"时硬告警/保守播种其调用方。

### S7. DWARF-less 单实例裸名错配 `[CONFIRMED · medium]`
`partial-dwarf-bare-name-single-instance-misalign`

- **是什么**：addr_map 非全覆盖（合成 thunk、无源位置的编译器生成函数无 DIE），这些块 L107 回退裸 ELF 名。ambiguous 检测 L201 `len(base[n])>1 or len(patch[n])>1` 只拦"同 key 多块"，拦不住"两侧各恰好一个同裸名的不同函数"。base 删一个 DWARF-less `foo`、patch 新增另一个 `foo`（各一块）→ `foo ∈ common`（既不进 added 也不进 removed），被当 aligned pair 直接 diff；池通配后结构同构小函数 sig 极易相等 → equivalent。
- **复现**：base liba 的返回 'A' 的 thunk `foo` 删除，patch libb 新增结构同构、返回 'B' 的 `foo`。两侧各一块 → sig 相同 → 设备把新 foo 绑到旧 thunk 机器码，跑出 'A'。
- **已文档化**：否（多块 ambiguous 兜底已记，单实例错配未记）。
- **修法**：DWARF-less 块不得与 canonical key 混同对齐；无法解析源身份的函数应保守播种或告警。

---

## Tier A —— 换工具链/架构即触发的静默漏判（sound-critical，需非 GNU/x86 环境）

### A1. llvm-objdump 静默空解析 → 打印"全部等价" `[CONFIRMED · medium]`
合并：`parse-silent-empty-format` + `llvm-objdump-silent-empty`

- **是什么**：指令正则 L111 `\s+[0-9a-f]+:\t([0-9a-f ]+?)\t(.*)` 硬要求 GNU 的双 tab 列格式；llvm-objdump（macOS 上 `objdump` 即它）用空格分隔、分支目标带 `0x` 前缀。后果：头正则 L104 仍匹配 → funcs 键正常填充，但**每个块解析为空**，`sig([])=''`，所有对齐对判等；byte_changed=∅、closure 只剩 added。全工具无一处 sanity check（如"解析指令总数>0"）。对一对有真改动的快照打印 `byte-changed: 0 / must reinterpret: 0`，exit 0，无报错。
- **已文档化**：否（NOTES 只说"x86-64、基于 objdump"，未说此静默成功失败模式）。
- **修法**：pin GNU binutils 或按格式分派；加"解析块非空/指令数>0"断言，否则硬失败。

### A2. arm64（真实部署目标）：条件2整体失效 + 池噪音洪泛 `[CONFIRMED · medium]`
合并：`edges-arm64-bl` + `x64-only-silent-on-arm64` + `pool-reg-x27` + `adrp-add-pair-drift`(PLAUSIBLE) + `bl-range-veneers`(PLAUSIBLE)

- **是什么**：喂 aarch64 快照，objdump 成功、头/指令正则都匹配、打印貌似正常的统计——但：
  - L117 `call[a-z]*` 匹配不到 `bl`/`blr`/`b`（Gate 1b 真机记录即 `bl 0x1409f8 <f>`）→ **直调图为空、条件2零传播**。这是最危险形态：`pureLeaf` 靠条件1仍被抓，但字节不变、直调它的 `caller` 永不进闭包 → P2 陷阱原样复活，静默漏判。
  - L148 池通配写死 `%r15`+十六进制 AT&T 语法；arm64 是 `ldr xN,[x27,#十进制]`（PP=X27，THR=X26）→ 永不命中 → 池漂移原样进 sig，未改函数成片假 byte-changed，闭包滚向近 100%（方向 sound，但量化结论全失真）。
  - adrp+add 成对 PC 相对寻址无归一化模型（潜伏）；text>128MB 时 bl 经 veneer/trampoline，天真移植会把边挂到 veneer（潜伏）。
- **已文档化**：是（x86-64 scope 在 docstring L22、NOTES L66-67 记了 3 次），但**无任何 arch 断言强制**，且 arm64 是产品两个真实目标之一——所有 "closure==ground truth" 证据都只在 x86 取得。
- **修法**：指令层（call 提取 / normalize / sig，约 50 行但承载 100% 信号-噪音语义）按 arm64 重写并重跑 V9 式噪音量化；不动点/多重集/DWARF 概念层可移植。加 arch 探测，拒跑不支持的架构。

### A3. stripped 快照 → 整程序成单块、错配单一 key `[CONFIRMED · medium]`
`parse-stripped-symtab-merge`

- **是什么**：块边界只在 objdump 打出符号头处（=符号表项）。默认 strip 的 release `libapp.so` 只剩 ~4 blob 符号 → 整个 isolate 指令段解析成**一个块**，键为 blob 裸名。任意改动 → must_interp={单个 blob key}，真正改的函数既不在 must_interp 也不在 equivalent → 设备跑旧机器码。无 `解析函数数 vs len(addr_map)`（~1 vs ~数千）的对比告警。
- **已文档化**：是（COVERAGE #4/L33-34 记"需未 strip 快照、strip 从未真测"）；"失败是静默而非硬失败"这点未记。
- **修法**：解析函数数远小于 DWARF addr 数时硬失败。

---

## Tier B —— 潜伏/条件性漏判（PLAUSIBLE，当前工具链未复现）

- **B1. 跨函数 jmp 无边（`edges-tail-jmp` + `jmp-target-drop-no-edge-backstop`）· low**：L147 对 `jmp ADDR <sym>` 同样丢地址只留裸名，而 L117 只从 `call[a-z]*` 提边 → 跨函数 jmp 既被同名掩蔽（条件1）又无边可传（条件2），双盲。demo 实测 395 个跨函数 jmp **全指向 VM stub**（不 diff、无害），故现实触发面窄；但"x64 Dart 间不发 Dart→Dart 尾跳"是未断言的隐式不变量。修法：目标提取正则从 call 扩到 jmp，或落实 P2 保守兜底（无法解析的跨函数控制转移一律播种）。

- **B2. 池介导/间接调用无边 + docstring 误述（`indirect-call-claim-mischaracterized` + `pool-mediated-call-targets` + `edges-pool-indirect-static-calls`）· low/medium**：docstring L22-24 把被忽略的间接调用框定为 `call *off(%r14)`（THR 上 VM runtime stub）——**不准确**。Dart x64 的 instance/switchable/megamorphic 调用点从 r15 对象池 slot 取目标再间接调（`call *0xNN(%r15)`/`call *reg`），deferred import 的跨 loading-unit 静态调也走池；这些是真 app→app 边，对 diff-linker 完全不可见。是否有害取决于运行时是否重定向**所有**池介导调用形态（Gate1 V2 兜底），属运行时契约，静态侧零检测能力。修法：至少修正注释；逐类核实运行时重定向覆盖面（switchable 单态缓存、megamorphic cache、池内 tear-off/闭包目标），任一类未覆盖即静默漏判。

- **B3. debug ELF 与快照零一致性校验（`no-debug-snapshot-consistency-check`）· low**：`dwarf_canonical_map` 与 `parse_snapshot` 仅靠 `addr_map.get(addr)` 精确地址相等 join，无 build-id / 命中率阈值告警。传错/陈旧 `.debug` 时多数地址 miss → 静默回退裸名、added/removed 暴涨（sound 但闭包爆）。（原 finding 举的 User.name↔User.id 错配漏判被证伪：normalize 保留字段偏移，两 getter sig 不同、会 byte_changed 兜底 sound。）修法：加 build-id 或 mapped-fraction sanity check。

- **B4. DWARF 前向 abstract_origin 未解析（`forward-abstract-origin-unresolved`）· low**：`dwarf_canonical_map` L60-92 单趟按文本流填 `spec[off]`，`spec.get(ref)` 对尚未见过的 offset 必 miss。当前 Dart 恰好 abstract 在前，未断言的顺序假设。上游发射顺序一变 → 大面积回退裸名。同 SDK 构建 base/patch 会对称退化（sound）；仅非对称跨 SDK 才漏。修法：两趟（先收全 spec 再解析 concrete）。

---

## Tier C —— 误报型精度损失（sound，闭包膨胀，冲击"解释比例是命门"）

- **C1. 纯文件移动/改名级联（`seed-filemove-added-cascade` CONFIRMED med + `filepath-canonicalname-proxy` PLAUSIBLE low）**：canonical key = `fpath::name`（L91），`git mv` 一个文件使其所有函数旧 key 进 removed、新 key 进 added（L189 全量播种 L210）→ 所有直调方经条件2级联。一次 utils 搬家可把语义 no-op 滚到程序可观比例。跨库移动/依赖版本 bump 情形部分被证伪（Dart DWARF decl_file 用版本无关的 `package:` URI；跨库移动理想对齐器也会 added/removed）；**唯一真残留**是同一 library 跨 `part` 文件移动（COVERAGE #19）。修法：真 linker 用 Kernel library-URI→类→成员，而非源文件路径。

- **C2. rawline/DWARF 格式脆弱 → 静默退回 `?::name`（`rawline-file-table-format-fragility` CONFIRMED med + `decl-file-unresolvable-collapses-to-question` + `readelf-format-lockin` PLAUSIBLE low）**：L56 文件表正则硬编码 DWARF2-4 五列 tab 格式；DWARF5 三列表→`files={}`→全部 `?::name`，跨库同名重新合并，ambiguous 兜底保 sound 但闭包无声爆回 30% 量级，而头行仍打印 `alignment: CanonicalName (N mapped)` 且 N 看着正常。同类：多 CU 时 files 全局 dict 互相覆盖（当前 Dart 单 CU 才侥幸）；`decl_file` 缺失/带注释 `isdigit()=False` → fidx=None → `?`。修法：解析后校验 files 表非空/含真实路径、`?` 组规模超阈值告警；DWARF5 三列格式适配。

- **C3. 跨构建混淆名漂移（`obfuscation-general-overclaim`）· low**：条件1的 sig 内嵌 call 目标的**混淆后 ELF 名**（L117 取名、L147 只丢地址留 `<name>`）。Dart 混淆按赋值序命名，补丁增删标识符会平移大量未改函数的混淆名 → 每个 call-site 文本变 → 成片假 byte-changed → 闭包近 100%。COVERAGE #4 已订正（跨构建未测）。修法：`sig()` 用块已存的 resolved target（真名）而非 objdump 文本名。

- **C4. 新增同名函数拖累未改代码（`seed-added-collision-drag`）· low**：裸名模式新增一个与既存函数同裸名的函数 → 该 key base 1 块 patch 2 块 → ambiguous_changed → 整 key（含未变旧实例）播种 → 旧实例调用方级联。已文档化（裸名保守代价）。

- **C5. 跨引擎版本构建洪泛（`r14-thr-offsets-not-wildcarded`）· low**：**r14 不通配是正确的**（THR 偏移同引擎逐位相同，通配反而漏报"换了运行时调用"）。真边界在跨引擎：patch 用升级后 SDK 构建 → Thread 布局/stub 变 → r14 偏移与 call 目标全体平移 → 闭包近 100%。方向 sound 但补丁退化为全量解释，工具不提示根因。修法：加"byte-changed 占比异常高→疑似引擎版本不一致"哨兵；把"base/patch 须同一 gen_snapshot 构建"写进 NOTES 前提清单。

- **C6. 正则脆弱（`abstract-origin-ref-regex-loose` + `strip-prefix-unanchored-replace`）· low**：L77 `0x?([0-9a-f]+)` 语义是"字面0+可选x"，某 readelf 变体渲染成无 `0x` 前缀时会截错 DIE 偏移（当前 GNU 恒带 `0x`，潜伏）。L87-89 strip_prefix 用非锚定 `str.replace`、无尾斜杠归一，root 传错/互为前缀时路径截错、两侧 key 全量失配（sound 但 100% 转解释）。修法：恢复 probe 的锚定 `<0x…>` 形式；strip 改前缀剥离并做尾斜杠归一 + key 空间重合校验。

---

## Tier D —— 报告/性能/scope（不影响闭包正确性）

- **D1. `--list` propagated 段漏显 ambiguous（`list-propagated-omits-ambiguous` = `ambiguity-list-reporting-hole`）· low[CONFIRMED]**：L248 `propagated = must_interp - byte_changed - added - ambiguous` 减掉**全部** ambiguous，而种子只含 ambiguous_changed（L209），控制台计数 L239 用 seed_ambiguous——两处口径不一致。经条件2进闭包的 multiset-equal 撞名 key 在 `--list` 任何段都不显示，各段之和对不上闭包总数，人工审计漏看。闭包集合本身与 `--emit-closure` 正确。修法：L248 改减 `seed_ambiguous`，并给 ambiguous_changed 单列一段。

- **D2. `--optimistic` 非"理想对齐"、误用即漏（`optimistic-not-ideal-aligner` + `optimistic-drops-real-seeds`）· low**：L209 `seed_ambiguous = set() if optimistic else ...` 把 ambiguous_changed 整体丢弃——这不是理想对齐模拟（理想对齐器会定位到变了的实例并播种），而是**不可用作产出补丁的下界**。p3b tearoff 用例（byte-changed=0、靠 ambiguous_changed 捕获、真闭包=4）在 `--optimistic` 下 closure=0，却标注 "OPTIMISTIC (ideal aligner)"。且 V9 的 62.6%→0.1% 数字用 `--optimistic` 产出、NOTES L55 叙述未标注模式。修法：改文案为"测量下界"；输出加"此结果不可用于生成补丁"硬提示。

- **D3. docstring 与代码漂移（`docstring-conservative-drift`；byte-for-byte 见 S1）· low[CONFIRMED]**：docstring L17-20 承诺"每个撞名都强制转解释"，但代码 L202/209 把 multiset-equal 撞名清为 equivalent（输出 L234 自己印 "multiset-equal → equivalent"）。审查者据 docstring 会误判撞名永不漏。修法：docstring 同步为多重集精化的实际策略。

- **D4. fixpoint 无缓存 O(轮×全程序指令数)（`fixpoint-quadratic-no-cache`）· low**：L214-222 每轮对全部 patch 函数重跑 `all_targets`（L160-161 每次从元组重建 set），无缓存、无反向边 worklist。~3000 函数样本无感；深直调链的真实 app 会退化。终止性无问题。修法：预计算 `{n: all_targets(patch[n])}` 一次，或建反向边 worklist（线性）。（"数小时/不可用"的量级被高估——虚调边界封顶了直调链深度。）

- **D5. 交叉/iOS 工具链（`ios-macho-toolchain` + `hardcoded-native-objdump`）· medium/low[CONFIRMED]**：L53-54/L100 写死 `readelf`/`objdump` 裸名，无 `--tool`/交叉前缀参数。喂 arm64 ELF（单目标 binutils）或 iOS Mach-O（GNU objdump 读不了、调试信息在 dSYM）→ CalledProcessError **崩溃**。失败是响的（fail-safe，不漏机器码），但连"指定交叉工具链"入口都没有；若用户以 multiarch/软链绕过，即落入 A1/A2 的静默失效。修法：加 `--objdump/--readelf` 参数；iOS 需换 llvm-objdump/otool+dsymutil 整条提取链，并处理 Mach-O 下划线符号前缀。

- **D6. objdump `\t...` 零省略 / >7 字节续行截断（`parse-zero-elision-invisible` + `parse-wrap-raw-truncated`）· low[PLAUSIBLE]**：零省略行与续行都不匹配 L111 正则，被丢弃；`raw` 只存首 7 字节。当前 Dart x64 无害（填充是 int3、常量在池、`sig` 不读 raw），是为 NOTES 两个规划升级（精确池映射、切 raw 比对）埋的雷。修法：objdump 加 `-z`；升级 raw 比对前先修续行拼接。

---

## 净新增（未在 NOTES.md / COVERAGE_GAPS.md 记录）

以下为文档**未覆盖**、本轮新暴露的缺口（尤其前几条是 SOUNDNESS 级）：

1. **S2** 同裸名调用重定向漏报（sig 丢弃已解析 target + normalize 只留裸名）——high，红线。
2. **S3** multiset-equal 在 body 置换下不 sound（文档反向宣称 sound）——high。
3. **S4** `<sym+0xNN>` 次入口直调边在 canonical 模式断链（addr_map 只按 low_pc 精确查址）——high。
4. **S5** `[^>+]` 截断 operator `+` / `<anonymous closure>` 的 `>`——high/low。
5. **S7** DWARF-less 单实例裸名错配（ambiguous 检测拦不住一对一）——medium。
6. **S6 细化** ICF 折叠使 key 落 `removed` 且从不播种、无告警（ICF 本身部分文档化，此静默机理未记）——high。
7. **A1** llvm-objdump 静默空解析→全等价，无任何 sanity check——medium。
8. **A3 细化** stripped 快照单块错配是**静默**而非硬失败（strip 未测已记，静默性未记）——medium。
9. **C1** app 内部纯文件移动/`part` 跨文件移动的 added 级联（构建根归一化已记，文件移动未记）——medium。
10. **C2** DWARF5/多 CU/`?::name` 退化仍打印 "CanonicalName (N mapped)"、无格式失配告警——medium。
11. **B2 细化** docstring "间接调用=r14 runtime stub" 不准确（漏 r15 池介导的 app→app 调用）。
12. **D1/D2/D3** `--list` propagated 口径错、`--optimistic` 误标 "ideal aligner"、docstring 保守策略过期。
13. **D4** fixpoint 无缓存/反向边（纯性能）。
14. **C5** "base/patch 须同一 gen_snapshot 构建" 前提未写进 NOTES；缺引擎不一致哨兵。

---

## 诚实的底线判断

作为 **spike（目的是量化"闭包不爆炸、对齐精度才是命门"这一方向性结论）**，绝大多数条目是**可接受**的：iOS/arm64/llvm 不支持是明示 scope，跨引擎/文件移动/DWARF5 退化都是 sound 的过报，性能与报告瑕疵不碰红线，池通配与裸名撞名的近似 tools/NOTES 已如实记为局限并指向真 linker 的正解（精确 slot→常量映射、CanonicalName 对齐）。**但在把这套方法搬到真实 arm64/混淆目标去产出可信补丁之前，有一批红线级漏判必须先解决**：条件1只比归一化文本而丢弃已解析的 call target（S2）、multiset-equal 在置换/池差异下不 sound（S3）、`<sym+0xNN>` 次入口断链（S4）、`[^>+]` 截断 operator/closure 名（S5）、ICF key 落 removed 静默丢（S6）——这五条在**当前 x86-64 代码上即可复现让工具漏掉真改动**；再叠加 arm64 上 `bl` 使条件2整体失效（A2）与 llvm-objdump 静默空解析（A1），意味着**在产品真正部署的架构上，目前零经过验证的 soundness**。方向可信，实现层的 soundness 尚不可信——生产 linker 必须：从 Kernel 层做 CanonicalName + ICF 感知对齐并把 target 身份并入条件1、按被调地址区间（含次入口）归属调用边、按目标架构重写指令层并做池内容精确比对、且在解析退化/格式失配/引擎不一致时硬失败而非静默出好看的数字。

---

# 完备性批判补充（综合报告之外新增的 6 项遗漏）

I've read all four files and verified the mechanics against the source. The review is unusually thorough, but here are 6 genuinely missed gaps — each distinct from every finding in the report.

---

## 遗漏项 1 — 单边 DWARF 调用即产生"貌似 CanonicalName、实为不相交键空间"的静默降级 `[soundness-adjacent · medium]`

**机理**：L179-180 各自独立 `dwarf_canonical_map(base_dbg,...)` / `(patch_dbg,...)`；L181 只要**任一** map 非空就打印 "alignment: CanonicalName"。若用户只传了 `--base-debug` 而漏 `--patch-debug`（或反之），`base` 全按 canonical key（`app.dart::foo`）、`patch` 全按裸名（`Precompiled_foo`）。两套键**永不相等**（canonical 键含 `::` 和路径，裸名是 `Precompiled_*`）→ L189-191：`common≈∅`、几乎整个 patch 落入 `added`、整个 base 落入 `removed` → 闭包 ≈100%。

**失败场景**：脚本化调用漏拼一个参数，工具打印 `alignment: CanonicalName (2936 base / 0 patch mapped)`、`must reinterpret: 2936 (100%)`、exit 0，看起来是"改动巨大"而非"参数配错"。方向 sound（全转解释不漏码），但结果完全不可用，且**没有任何守卫**拒绝这种非对称调用。

**为何未覆盖**：B3 讲的是"两侧都传了、但传错/陈旧的 debug 文件按地址 miss 回退裸名"——B3 建议的 mapped-fraction 检查在这里也失效（base 侧 100% 命中、patch 侧本就无 debug，各自看都正常）。这是不同的失败模式。修法：要求两侧 DWARF 存在性对称，否则硬失败；或校验 `common` 占比过低即报错。

---

## 遗漏项 2 — 函数**自身头地址**与 DWARF `low_pc` 不等时静默回退裸名（区别于 S4 的调用目标侧）`[soundness · plausible-medium]`

**机理**：L107 `key = addr_map.get(addr, h.group(2))`，`addr` 是 objdump 打印的**符号头地址**，`addr_map` 按 DWARF `low_pc`（L90-91）建。整个 canonical 对齐隐含一个未声明不变量：**objdump 符号值 == DWARF low_pc**。Dart AOT 函数是多入口的（checked / unchecked entry），若某类函数的 ELF 符号指向的入口 ≠ DWARF `low_pc` 记录的函数起点，`get()` 对该函数**自己的头**就 miss → 回退裸 ELF 名。

**失败场景**：这批函数在"canonical 模式"下悄悄退回裸名对齐，重新暴露 12% 撞名不确定性——而 header 依旧印 "CanonicalName (N mapped)"，只是 N 略小、无人察觉。更糟是**非对称**：base/patch 两版若入口偏移策略不同，同一函数一版 canonical 键、一版裸名 → 落入 added/removed 级联，或裸名撞名下判等价漏码。

**为何未覆盖**：S4 讲的是 L117 **调用目标**地址落在 `low_pc+0x16` 次入口而 miss；这里是 L107 **被解析函数自己的头**与 low_pc 不齐而 miss，是对齐管线的另一端。修法：`addr_map` 用 low_pc/high_pc 建区间，头地址落区间内即归属；或断言 objdump 符号数 ≈ DWARF 映射数，偏差超阈值告警。

---

## 遗漏项 3 — cid / dispatch-table / vtable 布局漂移完全在差分器模型之外（SPEC §4.3 盲区）`[scope soundness · medium]`

**机理**：工具只比"函数机器码字节"（cond1）+"直调边"（cond2），刻意止步于虚调边界（docstring L10-11，交给 Gate1 V2 运行时重定向）。但它对**类的 cid 分配、dispatch table 布局、vtable 顺序**零建模。一个补丁若只是增删/重排类成员或类声明，使既有类的 cid 或 dispatch slot 平移，而**没有任何 Dart 函数字节改变**：`byte_changed=∅`、无新边 → 闭包为空 → 工具报 "must reinterpret: 0"。

**失败场景**：补丁在某基类中间插入一个新方法，导致子类 vtable / switchable-call 缓存的 slot 序号整体后移；一个字节未变的 caller 的虚调用点现在派发到错误的 slot。差分器判全部 equivalent，设备上未变的调用方按旧 dispatch 布局跑 → 行为错乱。这类改动的正确性依赖 §4.3 cid 稳定化，而差分器**既不检测也不告警**它是否发生。

**为何未覆盖**：NOTES L43 明确点名 "§4.3 的 cid 稳定化"是命门之一，但整篇审查（尽管大量引用 §4.1 CanonicalName）从未把 "cid/dispatch 布局漂移对代码-only 差分器不可见"列为盲区。修法：差分器须消费 cid/dispatch 元数据做布局比对，或在类声明集合变化时保守告警"需 cid 稳定化验证"。

---

## 遗漏项 4 — 未 strip 快照中"无符号头的相邻代码"被并入前一块（区别于 A3 全 strip 与 S7 裸名错配）`[soundness · plausible-low/medium]`

**机理**：块边界只在 objdump 打出符号头（L104）处切分，块跑到**下一个符号头**为止（L123-127）。即使是未 strip 的快照，Dart 也会发射一些**无 ELF 符号**的可执行区域（编译器生成的 trampoline/thunk、某些 stub、或最后一个符号之后的尾部代码）。这些无符号区域被**吸收进紧邻的前一个具名块**，成为该块 sig 的一部分。

**失败场景**：补丁只改了一段无符号 thunk 的字节。工具把它算作**前一个具名函数**的 sig 变化——要么误报前一函数 byte-changed（归因错人），要么（若该 thunk 在最后一个符号之后）追加进最后一个块。而这段 thunk 运行时**没有独立 key、没有独立 entry**，闭包里也就没有它的重定向项——它以旧机器码继续跑。

**为何未覆盖**：A3 是"整个快照被 strip 成 ~4 blob"的极端；S7 是"两侧各一个同裸名 DWARF-less 块被错配对齐"。本条是"未 strip 快照中局部无符号区被静默并入邻块"的第三种机制，前两者都没描述这个 merge 路径。修法：校验解析出的块数/覆盖字节数与 DWARF 函数数一致；对无符号头的可执行区间显式登记或保守播种。

---

## 遗漏项 5 — DWARF 文件表的"目录索引 + 基名"分解未处理，同名基名跨目录合并 canonical 键 `[soundness-adjacent · plausible-low]`

**机理**：L56 `re.finditer(r'^\s*(\d+)\t\d+\t\d+\t\d+\t(.+)$', raw)` 只取文件表**第 5 列（name）**做 `files[idx]`，L83 `fpath=files.get(fidx)`，L91 canonical key = `fpath::nm`。DWARF 标准的行号程序文件表常把路径拆成 **目录索引 + 基名**（DWARF5 尤甚），第 5 列只是 `util.dart` 这样的基名，真实目录在另一列/目录表里。当前 Dart 恰好在 name 列放了完整 `file:///...` 路径（P0 NOTES 所见），本条才没触发——这是又一个未声明不变量。

**失败场景**：上游 SDK 改用目录索引+基名编码后，`package:a/util.dart` 与 `package:b/util.dart` 都解析成 `util.dart` → 两库同名函数合并到同一 canonical 键 → 进 ambiguous 兜底（多数情况 sound 但闭包膨胀），若两版多重集恰好相等则退化成 S3 型漏判。

**为何未覆盖**：C2 讲的是 DWARF5 三列表导致 `files={}`→全 `?::name`（键**置空**）；本条是文件表存在但**基名分解**导致键**跨目录合并**——不同的解析缺陷、不同后果。修法：解析文件表时按 dir-index 拼回完整路径，并校验解析出的路径含目录成分。

---

## 遗漏项 6 — normalize 只建模 r15 对象池，rip-relative 数据寻址完全未处理 `[precision + soundness channel · plausible-low]`

**机理**：`normalize()`（L146-149）只做两件事：删 `HEX <sym>` 绝对地址、把 `0xNN(%r15)` 通配成 `POOL`。它对 **rip 相对寻址 `0xNN(%rip)` 零处理**——既不通配偏移，objdump 注释里的 `# ADDR <sym>` 地址虽被 L147 删掉，但 `0xNN(%rip)` 的**偏移量本身留在助记符里**。这隐含"Dart AOT x64 从不用 rip-relative 引用数据、只走 r15 池"的未声明假设。

**失败场景**：两面。(a) 精度：若存在 rip-relative 引用（rodata 常量、链入的 C 运行时 stub），代码段布局一平移，`0xNN(%rip)` 的偏移就变 → 未改函数被误报 byte-changed（与 pool slot 漂移同源的噪音，却没被通配）。(b) 对称于 S1 的 soundness 通道：若某指令 rip-relative 引用的**数据内容变了、偏移没变**（布局未动），指令文本一字不差 → cond1 看不见改动。normalize 精确建模了 r15、有意保留了 r14（C5 判定为正确），却把 rip 这条数据引用通道整个漏在模型之外。

**为何未覆盖**：S1 专指 r15 对象池、C5 专指 r14 THR；rip-relative 作为 x86 上第三条数据引用通道，审查从未提及。修法：确认 Dart AOT 是否发射 rip-relative 数据引用；若有，须与池同等处理（偏移归一化 + 内容比对），并把"仅 r15/r14 被建模"写进 NOTES 前提。

---

**总评**：审查在"当前 x86-64 可复现漏判 + arm64/工具链 scope"两个维度上已接近穷尽。上述 6 条集中在它**结构性没碰到的三类地方**：(1) CLI/DWARF 对齐管线两端的隐含不变量（项 1、2、5）——工具在这些前提破裂时不是漏码就是出"貌似正常"的垃圾数字且无守卫；(2) 差分器模型**边界之外**的正确性载体（项 3 的 cid/dispatch 布局，SPEC §4.3 明列却被审查完全略过）；(3) 指令归一化只建模了两个寄存器、把第三条数据通道 rip 漏在外（项 6）。其中项 3（cid/dispatch 盲区）最值得进 COVERAGE_GAPS——它和 S1/S2 同属"字节没变但行为变了、闭包为空、无告警"的红线类，却不在任何 finding 里。
