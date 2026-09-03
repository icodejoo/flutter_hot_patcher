---
name: feedback-false-green-traps
description: 本仓库 run_vm_tests 与产物检查有十七种「假绿/假红」，判据必须是 ninja exit code + 测试 exit code + 产物时间戳，且每个测试要做负控制
metadata: 
  node_type: memory
  type: feedback
  originSessionId: de13fb95-54ec-4a86-a27b-1ad12342445f
---

在 `~/dart-3122/sdk` 上执行 plan 时实测出四种「看起来通过、实际没测到」的形式，
**四种全部会让人以为工作完成了**。判据依次收紧：

1. **`run_vm_tests` 测试失败时照样打印 `Done: <TestName>`**
   → 只看 stdout 文本会把失败当成功。只有 exit code 能区分（0 通过 / 255 失败）。
2. **构建失败时，陈旧二进制仍会运行、仍打印 `Done:`、仍 exit 0**
   → 「测试全绿」可以等于「你的改动一行都没编进去」。
   **必须先看 `ninja` 的 exit code，它非 0 则任何测试结果都无意义。**
3. **产物检查脚本会对着过期二进制给出「正确」答案**
   实例：`ProductARM64/gen_snapshot` 比 `wrapper.cc` 早一天，符号检查脚本照样打印
   `0` 并 exit 1，与预期失败一模一样，但它测的是一个从未编译过该文件的二进制。
   → 加时间戳护栏：`[ "$BIN" -ot "$SRC" ] && echo STALE`。
   ⚠️ 这条在「期望非零」时更致命：陈旧二进制报 0 会被读成「工作失败」而其实没跑。
4. **测量脚本自身报错**：`echo "$out" | tail` 之后读 `$?` 读到的是 `tail` 的状态。
   → 与上面同一类：**报出来的数字不是它声称在测的东西**。

**Why**：这四种都不会报错，只会给虚假信心。而本仓库的主任务是逆向复刻，
唯一的判据就是「实测」——判据本身失效时，整条证据链一起失效。
最贵的一次：plan 里的 COW 测试对 `copy=FALSE`（共享映射，恰是它要排除的东西）
通过，若照原样执行就会得到一个绿色的 COW 测试和一个从未验证过的 COW 实现。

**How to apply**：
- 顺序固定：`ninja; echo $?` → 时间戳护栏 → 逐测试 `echo "exit: $?"`
- **每个 task 至少做一次负控制**：翻转一个期望值，确认它真的会失败（exit 255）。
  «An assertion that cannot fail is not a test.»
- 负控制要打在**最可能空洞**的断言上，而不是随便一个。例：验证循环真的迭代，
  应该「少消耗一个」（2043/2044）而不是翻转字面量——前者才能证明容量与翻页是真的。
- 警惕「名字宣称的比断言保证的多」：`CountIsDerivedNotHardcoded` 实际只验字段自洽，
  值被写死照样通过。这类缺陷永不失败，只误导。

相关：[[feedback-verify-by-running]]、[[project-dart-sdk-fork]]、[[feedback-rtk-diff-unreliable]]

## 第 7 种：「唯一可接受的 skip」不存在（2026-08-20，第 10 处缺陷）

dd_voting plan 里有个 env-var fixture 测试，plan 自称那是「唯一可接受的 skip」。**不成立**——
缺少 `DD_SLOT_VOTERS_FIXTURE` 会让它静默通过，而且在正常运行中**会对一个完全损坏的 reader 通过**。

正解不是「缺失时失败」，是**消除缺失的可能**：把 185 字节 oracle 直接嵌进测试
（`kOracleVotersBin`）。仍是真独立 oracle（`write_dd_slot_voters.py` 产生、**他们的**
gen_snapshot 成功消费，日志 `7 resolved / 8 slots, 7 retained`），但无 skip 路径、每次都跑。

## 结构断言无法替代字段断言 —— 最完整的一次实证

交换 decoder 里 `caller_key`/`target_key` 的读取顺序（流保持完美对齐）：
```
ReadFromStream 返回 true            通过
PendingBytes() == 0                 通过
slot_count() == 8                   通过
voters().size() == 8                通过
voters_for_slot() != nullptr (×8)   通过
idxs->size() == 1 (×8)              通过
────────────────────────────────────────
第一个失败 = 第一个字段比对          ← 只有这里
```
**六层结构断言全部放过。** 所以：断言必须指名「谁/什么值」，不能只验「有/几个/流是否消费干净」。
同理，投票算法里「选出了赢家」的断言会在选错赢家时通过——必须断言**哪个函数赢**。

## 第 8 种：符号计数的**前缀污染**（2026-08-20）

`nm | c++filt | grep "dart::FunctionKey"` 命中 **26** 个——全部是 `precompiler.h` 里既有的
`dart::FunctionKeyTraits`。我们自己的 `FunctionKey` 真实计数是 **0**。
任何按这个模式 grep 的人会读到 26 并断定「已落地」。
→ **符号 grep 必须带尾部 `::`**（`dart::FunctionKey::`），否则前缀匹配会伪造进度。
（无命名冲突，只是名字互为前缀。）

## 第 9 种：exit code 也会不够 —— 两条路径同一个退出码

`--dd_slot_mapping` 的格式嗅探负控制：强制 `if (true)` 走错分支后，
**正确版与错误版对非 voters 文件都 exit 255**，只有错误消息不同
（`DDSlotVoters: bad magic` vs `neither ... nor`）。
→ 当一个检查有**两条通向同一退出码的合理路径**时，exit code 不足以判据，
**消息断言是承重的**。已在源码标注，防止后人「简化」成 exit-code 检查。

## 第 10 种：符号计数**无法判定「某段代码有没有被编译」**（2026-08-20）

想证明 `#if defined(SIMULATOR_HOST_ARCH_MATCH)` 那块没被编译，我数了
`nm ...simulator_arm64.o | c++filt | grep -icE "CallHostFunction|InvokeWithTHR|IsHostCodeAddress"`
得 **0**，并且还带了阳性对照（同一 `.o` 里 `DecodeExceptionGen` = 1），于是判定三个函数都没编译。
**其中 `InvokeWithTHR` 判错了**：它是 `static` 且被内联，所以
「编译了」与「没编译」在符号表里**长得完全一样**。它实际是编译的、活的，
被 A5 的 BL 拦截与 BLR 拦截调用——差点把它跟死代码一起删掉。

✅ **正确工具：往块里插 `#error`，并对一个已知会编译的块插同样的 `#error` 做阳性对照。**
```
#if defined(SIMULATOR_HOST_ARCH_MATCH)     → 构建照过           = 真的没编译
#if defined(__aarch64__)（阳性对照）        → ninja: build stopped = 工具有效
```
⚠️ 阳性对照不可省：只看「构建照过」无法区分「没编译」与「ninja 根本没重跑这个文件」。

**教训（与 [[project-wrapper-upstream-ancestor]] 的三次翻车同型）**：
阳性对照证明的是**工具能报出存在**，不代表它能回答**你问的那个问题**。
`nm` 能回答「符号在不在」，不能回答「代码在不在」。**先问工具的语义匹不匹配问题。**

## 第 11 种：**zsh 不对未加引号的变量分词**（2026-08-24）

```zsh
TESTS=$(... | awk '{print $1}')     # 71 行
for t in $TESTS; do run "$t"; done  # bash：跑 71 次；zsh：跑 1 次
```
zsh 默认**不做 word splitting**，整个 71 行的多行字符串被当成**一个**参数传进去，
`run_vm_tests` 拿到一个不存在的测试名、报一次失败，输出是 `PASS=0 FAIL=1`。
危险在于它**长得像「测试挂了」而不是「循环坏了」**——如果那次恰好期望失败，就会被读成成功。

✅ 测试循环一律写成 `while read -r t; do ...; done < file`，别用 `for t in $VAR`。
（同源坑：`${PIPESTATUS[0]}` 在 zsh 里是空的，要用 `$pipestatus[1]`；
所以 `cmd | tail; echo $?` 这类取退出码的写法在本机一律先落盘再取 `$?`。）

## 第 12 种：还原源码后 **mtime 倒退**，ninja 不重建（2026-08-24）

负控制的标准流程「改坏 → 构建 → 还原 → 构建」有个陷阱：
```bash
sed -i.bak 's/target/caller/' x.cc   # .bak = 原件，mtime = 此刻
ninja                                # 用改坏版编出 x.o，mtime 更晚
mv x.cc.bak x.cc                     # 还原，但 x.cc 的 mtime 回到 sed 那一刻
ninja                                # ← x.cc 比 x.o 旧，判定无需重建！
```
结果：源码是对的、`grep` 也证明是对的，**跑出来却还是负控制的行为**。
这次表现为「还原后测试仍然 FAIL」，幸好方向是变红所以被发现；
**如果负控制的期望是变绿，就会被读成成功**。

✅ 还原源码后 `touch` 再构建，或确认 ninja 日志里真的重编了那个文件。

## 假红的第二形态：参数错误伪装成功能失败（plan 缺陷 #11）

plan 的验证命令用了 `--snapshot_kind=app-aot-macho`，而本构建只有
`app-aot-macho-dylib`。于是 `gen_snapshot` 在**到达被测代码之前**就因参数校验 exit 255,
产生一个看起来很确信的红色，与功能完全无关。
**只有 before-control 抓到**（跑不带该 flag 的对照，输出完全相同）。
→ 第一形态是「既有差异被归因给改动」；这一形态是「参数错误被归因给功能失败」。
**任何声称验证了某功能的命令，都要先证明它真的执行到了那段代码。**

## 第 12 种：**负控制自己没跑，却看起来像跑了**（2026-08-24）

```bash
python3 -c "assert s.count(old)==1; ..." && ninja ... && run_vm_tests X; echo "SABOTAGED exit=$?"
```
补丁脚本因为字符串被 clang-format 重排而 assert 失败 → python 退出 1 →
`&&` 链断掉、**二进制根本没重建** → 打印出 `SABOTAGED exit=1`。
「1」看着就像测试失败，实际是补丁失败，负控制**一次都没执行**。
紧接着的 `RESTORED exit=0` 也是在未修改的文件上跑的，同样无意义。

✅ 判据：负控制的失败退出码要**明确区分**（测试失败是 255，不是 1）；
或者让打补丁那步单独 `echo` 一句成功标记。改行号比改字符串稳。
**一个静默没执行的负控制，比没有负控制更糟——它会让你以为验过了。**

### 第 12/13 种的**第二次复发**（同日，同一轮内）

修好「补丁 assert 失败」之后，同一个负控制又没跑成——这次是
`N=$(command grep -n ... | cut -d: -f1)` 里 grep 返回了 0 匹配（输出被 RTK 装饰成
`🔍 0 for '...'`），`$N` 成了垃圾，python 语法错误、**没打补丁**，
而紧随其后的 `restored exit=0` 照常打印，看着完全正常。

✅ **可用的做法**：打补丁那步必须 `print('PATCH_OK')`，并且**先单独跑一遍确认看到 PATCH_OK**，
再接 `&& ninja && 测试`。行号写死在 python 里（先人工确认），不要从命令替换里取。
一轮之内同一个陷阱踩两次，说明「知道有这个陷阱」不足以避开它，**必须有显式成功标记**。

## 第 14 种：**从 product 构建抓期望值，拿到 release 测试里断言**（2026-08-24）

stub 字节里有些字是**构建配置相关**的（如 `native_safepoint_state_acquired()`——
product 与 release 不同值）。我把 product 产物里的 42 个字全抓成字面量、在 release 里断言，
两个字直接对不上。它**不是我写错了代码**，是我把一个会变的东西钉成了常量。

✅ **可靠的判别法**：**把同一个 stub 从两个构建里各抽一次，逐字 diff。
差异索引集合 = 必须用推导而不能写字面量的集合。** 比人肉猜哪些字「看起来像偏移」靠谱得多。

在已落地的六个 stub 上跑一遍的结果：
`ResumeOnCPU {0,1,2}`、`CallSimFromFfi {17}`、`BootstrapNative {}`、`CallToRuntime {}`、
`ResumeOnSimulator {0,1,2,21,26,27,41,57,62}`、`CallNativeThroughSafepoint {12,16,26,32}`。
前五个的差异索引都已在推导集合内（是查出来的，不是假设的），只有第六个漏了 12 和 26。

## 第 15 种：**派发出去的 agent 没有文件工具，却"报告"完成了**（2026-08-24）

同一会话里连派三个 doc agent：**前两个真写了文件，第三个只拿到 `tool_search_tool_regex`**，
于是它把要写的内容当作最终答复返回了。它的结论段还写着
「Files to edit: ...README.md and ...project_dart_sdk_fork.md」——

**如果只读 agent 的报告摘要，会读成"两个文件已更新"。实际两个文件一个字都没变。**

危险点与本文件其他各条同型：**没有任何东西报错**。agent 状态是 `completed`，
返回内容详实且正确，只是从未落盘。而且它返回的正文里带 HTML 实体（`&lt;` `&gt;` `&amp;`），
直接粘贴还会引入第二个缺陷。

✅ **判据：agent 说改了文件，就去看文件，不看它的报告。**
`git status` / `grep` 目标串 / `tail` 文件尾，三选一，必须做。
同一批次里其他 agent 成功过**不能**推断这个也成功——工具可用性在 agent 之间不一致。

⚠️ 这条对本仓库尤其致命：文档与 memory 是「实测结论」的唯一载体，
一次静默丢失会让下一轮基于**上一轮的旧状态**继续推进，而 CLAUDE.md 的整个方法论
都建立在「记录的就是实测的」这个前提上。

相关：[[feedback-verify-by-running]]（写完必须回读，不能只看退出码——这是它的 agent 版本）

## 第 16 种：反汇编正则漏掉「零位移」形式（2026-08-24，假红）

`dd_pass_check.sh` 数间接调用点时，第二条指令的正则写成要求 `, #` 位移：

```
ldr\tx16, \[x16, #...\]      # 漏掉了 slot 0
```

**slot 0 的偏移是 0，objdump 不打印位移**，发出的是 `ldr x16, [x16]`。
而**单行 mapping 永远把函数放在 slot 0** —— 于是 harness 报 0 处、手测是 73 处，
看起来像 pass 整个坏了。批量 mapping（slot 0..1271）时绝大多数 slot 非 0，所以那条路径一直是绿的：
**这个 bug 只在最小、最该用来做单点验证的输入上发作。**

✅ **判别法：harness 与手测不一致时，先怀疑 harness，不要先怀疑被测物。**
（与第 13 种「失败数等于测试总数时先怀疑参数」同源：都是「工具坏了」伪装成「东西坏了」。）

✅ **可复用规则**：任何匹配汇编操作数的正则，都要显式覆盖**零值被省略**的写法
（`[reg]` vs `[reg, #N]`、`lsl #0` 被省略、等等）。

⚠️ 同一轮里 zsh 不分词又发作了两次：`$(echo $T)` 只跑了 1 个测试却 exit 0；
`for pair in "a b"; do set -- $pair` 没拆开、脚本崩了但**用上一轮的陈旧 m1.bin 跑出了 0 处**。
第二次尤其危险——它是「崩溃 + 陈旧输入」合成的假结果。

## 第 17 种：**在不编译这段代码的构建里**「编译通过」（2026-08-24）

给 `Thread::SetupDartMutatorStateDependingOnSnapshot` 加了两行，写错了命名空间
（写 `shorebird::X`，而 X 在 `dart::`）。`ninja -C xcodebuild/ReleaseARM64 run_vm_tests` **返回 0**。

原因：那段函数体在 `#if defined(DART_PRECOMPILED_RUNTIME)` 里，而 `run_vm_tests` 是
**precompiler** 构建 —— **不定义**这个宏。所以它"编译通过"是因为**它根本没被编译**。
换成 `ninja -C xcodebuild/ProductARM64 dartaotruntime` 立刻报错。

✅ **判别法**：改动落在 `#if` 块里时，**必须在会定义该宏的那个构建里编译**。
本仓库的对应关系：
- `DART_PRECOMPILED_RUNTIME` → `dartaotruntime`（**不是** `run_vm_tests`、**不是** `gen_snapshot`）
- `DART_PRECOMPILER` → `gen_snapshot`

⚠️ 这与本文件第 4 种（符号计数答不了「有没有被编译」）**是同一个失效模式的另一个方向**：
「产物里没有」与「从没编译过」长得一模一样。**换一个构建的绿色什么都不证明。**

## 第 18 种：测试写了、手跑绿了、**harness 的名字过滤器从来没选中它**（2026-08-25）

`45e94243ce9` 给 `Assembler::InstructionCountForLoadStoreFromOffset` 写了单测，
手跑通过，当时记成「95/95」。第二天跑 `verify_all.sh` 报的是 **94 passed**。

差的那 1 个就是它。原因不是测试坏了，是 **harness 选不中**：
`verify_all.sh` 用名字正则挑测试——
`shorebird|DDSlot|Wrapper|Linker|FunctionKey|IndirectStaticCall`——
而这个函数是 Shorebird **加在上游文件**（`assembler_arm64.cc`）里的，
测试名随上游风格叫 `Arm64InstructionCountForLoadStoreFromOffset`，
**一个关键词都不含**。于是它整整一天存在但从未被跑过。

✅ **判别法：手记的数与 harness 报的数不一致时，先把差额定位到具体名字**，
不要含糊成「大概是重命名了」。`--list | grep -c` 与 `--list | grep <新名>` 两条命令就能定位。

✅ **可复用规则**：靠**名字**选测试的 harness，对「装在上游文件里的私有改动」天生盲。
每加一个这样的函数，都要同时问：*它的测试名会被选中吗*。
已把 `ObjectPool|InstructionCount|PadLoadStore` 加进正则（实测只多选中我们这一个，
不会误拉上游测试），`PadLoadStore` 落地时会自动被覆盖。

⚠️ 这与第 4 种、第 17 种同源：**「没被跑」和「跑过且通过」在汇总行里长得一模一样**。
`verify_all.sh` 已经为「缺二进制」做了这件事（记 SKIPPED 并让整体失败），
但对「过滤器没选中」没有对应的护栏——**没被选中的测试连 SKIPPED 都不会打印**。

## 第 18 种的复发（2026-08-25，**记下第二天就又踩**）+ 结构性修复

昨天记了「靠名字正则选测试的 harness 对上游文件里的私有改动天生盲」，
今天加了 4 个 `ClassTableMapping_*` 测试，`verify_all.sh` 报的仍然是 **102**——一个没变。
而且回头看，昨天自己加的 `Sha256Hash_*` / `IntervalInfo_*` **也一直没被选中**。

⚠️ **「知道这个陷阱」并不能防住它。** 我昨天写下它、今天照样踩，因为
**判据是「0 failed」，而没被选中的测试不产生 failure，也不打印 SKIPPED——它什么都不打印。**

✅ **结构性修复**（只往正则里加名字是治标）：把期望测试数钉死在脚本里
```bash
EXPECTED_TESTS=${EXPECTED_TESTS:-108}
...
if [ "$fail" -eq 0 ] && [ "$pass" -lt "$EXPECTED_TESTS" ]; then  → FAILED
```
于是「选中数量少于声明」本身就是失败，即使被选中的全绿。
加测试时必须**手动抬这个数**——**那一次编辑就是发现「新测试没被选中」的时刻**。
已实测：`EXPECTED_TESTS=200 ./verify_all.sh` → `FAILED ... only 108 selected`。

✅ **可复用规则**：任何「按模式挑一批东西然后报告成功率」的 harness，
都要**同时断言挑出来的数量**。只报成功率的 harness，对「挑漏了」永远是绿的。

## 第 19 种：**负控制本身可能是恒等变换**（2026-08-25）

给类表映射器写完实现后，按惯例做负控制：把 backfill 的
`cid = cursor + 1`（他们的写法）改成 `cid = 0`（从头找），**四个测试全绿**。

第一反应是「测试太弱」。真相是**这两个规则在语义上完全等价**：
没有任何东西会被「释放」，所以最小空闲 cid 永远大于上一个发出去的 cid，
「从 cursor+1 找」与「从 0 找」必然给出同一个答案。
20 万组随机输入暴力验证：**0 组不同**。

→ 那个「负控制」是**恒等变换**，它不红不是因为测试瞎，是因为**什么都没改**。

⚠️ 连带发现：我给测试起的名字 `BackfillResumesFromTheCursor` 是**错的**——
它根本测不到 cursor；注释里写的「the cursor matters」也是错的（它只影响复杂度）。
**已改名并把注释改成相反的说法**，因为「声称某性质重要」的注释会诱使别人
去信任一个**永远不会失败**的测试。

✅ **判别法**：负控制变红**之前**，先问「我改的这一行，在语义上真的变了吗」。
能用暴力枚举回答的就去枚举。
✅ 有效的负控制长这样：删掉 stage 1 里的 `taken[base_cid] = true`
→ 四个测试红两个，另外两个绿是因为它们本来就不覆盖这条（**这也要说清楚**）。

## 第 20 种：**oracle 的两个输入其实是同一份东西**（2026-08-25）

给 `--print_shorebird_info` 写对拍脚本，用他们的 `out_dd/base.ct` 和 `out_dd/patch.ct`
做 base/patch，八行报告与他们逐行相同——看起来是很强的验证。

写 self-test 时想「把两个文件对调，数字应该变」，结果**没变**，脚本自己判定
「the altered input still matched, so this check proves nothing」并**拒绝通过**。

查下去：**`cmp out_dd/base.ct out_dd/patch.ct` 完全相同。**
两个「不同」的输入是同一份字节。于是：
- 每个 hash 都和**自己**配对 → `groupBy` 的分组、size==1 判定全部走的是恒等情形
- 「配不上」「有歧义」这两条真正容易写错的路径**一次都没被走到**
- 606/606/0/13 里那个 `Backfill 13` 只反映 619-606，不反映任何配对逻辑

✅ **修法**：另造一份**真的不同**的输入——拿 base.ct 删掉 20 个类，
于是 20 个 hash 配不上任何东西，数字变成 **586/33**，我们同样逐行相同。
两个输入一起跑，self-test 也才有东西可破坏。

✅ **可复用规则**：用「一对文件」做 oracle 之前，**先 `cmp` 一下**。
两侧相同的 fixture 只能证明恒等情形成立，而恒等情形通常正是最不容易写错的那条路径。

⚠️ 与第 19 种同源但方向相反：第 19 种是**负控制**没改变语义，
这一种是**正向输入**没提供差异。两者都表现为「全绿」，也都不是被测物的功劳。

---

## 第 20 种：**负控制测不到它想测的东西**（2026-08-25，聚合器）

与第 19 种同族，但病灶不同。第 19 种是负控制**语义没变**（两个规则等价）；
这一种是负控制**语义确实变了，但被测量的定义域里没有它的用武之地**。

实现完加权投票聚合器后，按计划做负控制：把权重 `1.0 / (base.size() + patch.size())`
改成常数 `1.0` → **9 个测试全绿**。

第一反应「测试太弱」不准确。真正的原因是**权重公式当时零覆盖**：
- `AddVote` 系列测试直接把权重当参数传进去，根本不经过那个公式
- link-results 系列测试每个键只有一个候选，权重乘任何正数都不改变 argmax

**更深一层，也是可复用的那一层**：score 与事件数**通常同向变化**。
一个组贡献 `|base| × |patch|` 次权重 `1/(|base|+|patch|)` 的投票，
所以 `score = count / (b+p)` —— 大组一般在「比分数」和「数票数」两种口径下都赢。
**除数在多数输入上是不可观测的。**

要让它可观测，必须刻意挑一对让两种口径判断相反的输入：
```
组 A：2 base × 2 patch = 4 次事件，权重 1/4 → 1.000   ← 加权时赢
组 B：1 base × 5 patch = 5 次事件，权重 1/6 → 0.833   ← 数事件时赢
```
补了 `ObjectPoolLinkResults_WeightIsNormalisedByGroupSize` 之后，负控制 1 才变红。

✅ **可复用规则**：负控制不变红时，**先问「这一行在现有测试的输入定义域里是可观测的吗」**，
再问「测试是不是太弱」。前者是覆盖问题（补输入），后者是断言问题（补断言），修法完全不同。

⚠️ 尤其危险的形态：**一个参数在「典型输入」上恒被其他因子淹没**。
这类参数即使写错也永远不会被发现，除非有人专门去构造让它单独说话的输入。

## 第 23 种：改 `runtime/vm/` 会换掉快照版本 hash —— 负控制拿到「对的退出码、错的原因」

2026-08-26 任务 60 实测，代价是一条被误记的负控制。

`runtime/vm/` 下任何改动都会改变快照版本 hash。负控制若只重建 `analyze_snapshot`
而没重建 `gen_snapshot`，检查会死在 `Wrong full snapshot version` 上——
**退出码与「因预期原因变红」完全一样**。

**为什么它比普通假绿更阴**：假绿是「该红没红」，你会继续挖；
这个是「该红、也真红了、但红的原因不是你改的那一处」，看起来完全符合预期，
于是它会被当成「负控制通过」记进账本。

判据：负控制变红后，**读一眼失败信息本身**，确认失败原因就是你改坏的那一处。
纪律：**`runtime/vm/` 下的负控制必须连 `gen_snapshot` 一起重建。**
与已记的「同一轮 `ninja` 必须 exit 0」是**两条独立要求**——
这次 `ninja` 确实 exit 0，陷阱照样成立。

**2026-09-02 新增四种，全是「判据本身是坏的」这一族（本会话真踩，不是推想）**：
- **cwd 跨命令持续** → `cd` 进子目录后，此后所有 `test -e .loop/PAUSE` 查的是**不存在的相对路径**，恒为假 → 连报两条「循环在跑」，而它已停了 4 小时；`rm -f` 也删的是空气。日志里 `skip: PAUSE present` 一直在说真话，是失效的检查覆盖了它。→ **查状态一律用绝对路径脚本，不用相对路径 + `test -e`。**
- **`pgrep -f 'claude -p'` 自匹配**：轮询命令自己的文本就含该串 → `until ! pgrep …` 永不退出，还报出「round RUNNING 45 分钟」而那进程 cpu 仅 0.41 秒。→ **用只有目标进程才有的串（本项目用 `LOOP_CONTRACT`）并排除自身。** 一个会话内踩两次。
- **`${PIPESTATUS[0]}` 在 zsh 里是空的**（zsh 用 `$pipestatus`，下标从 1 开始）→ 落盘的退出码变成 `exit=`（空值），**看起来像命令没返回码**。要写 `${pipestatus[1]}`。⚠️ 这条是**指令给错**导致的假象，不是执行方偷懒 —— 排查时先怀疑自己给的写法。
- **陈旧日志给出错的答案**：同一任务留下三份日志（失败/中间/成功），先读到最旧那份就会把**已成功**的工作判成失败。→ **先 `ls -lat` 再读，判据取最新那份。**与「陈旧二进制仍 exit 0」同源，只是换成了日志。
- **判据搜错形式**：用产物名 `grep 'Flutter.framework'` 找构建目标得 0 命中，差点判定「构建图里没有这个目标」；真名是 `flutter_framework`。**产物名不是目标名。**
