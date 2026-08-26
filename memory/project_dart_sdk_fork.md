---
name: project-dart-sdk-fork
description: 主任务=复刻 Shorebird 私有 dart-sdk；**11/11 私有 flag 全部完成**、16/16 私有 stub 全有真 body、DD 全链路端到端跑通、三阶段映射两张表都已复刻（八行报告逐行相同）；**2026-08-25 `object_pool_editor.cc` 已落地**（`f426f46f5b0`，`run_vm_tests` 128 全绿）；实现约 36-42%、逆向 80-85%；剩余：`ImageWriter::Write` 集成（阻塞于 old→new 索引映射表所有者未定）、加权投票聚合器（他们没有「组恰好 1 成员」过滤，我们有）、`LinkedValue<T>`、**真机 A/B 仍零实测**；快照 hash 是 15 个源文件的 MD5 且不可达，别当判据
metadata: 
  node_type: memory
  type: project
  originSessionId: cae5863d-feae-468d-8c8b-6c16f076bdaf
---

## 🔑 发现一：他们把私有实现的符号表一起发布了

**`gen_snapshot_arm64`（15,917 符号）与 `analyze_snapshot_arm64`（8,409 符号）都没 strip。**
C++ mangled name 直接给出私有类与方法签名。证据存于
`docs/shorebird_symbols/*.symbols.txt`（route-a-research，commit `d71fc5f`）。

关键符号：`Dart_ComputeDDSlotMapping`、`SubgraphHasher(InstructionsTableInterface&, char*, DDTableLinkInfo*)`、
`ShorebirdLinker::shared()`、`InitializeWith{ClassTable,ObjectPool}LinkInfo(ptr,ptr)`（各**两个**参数）、
`InitializeWith{FieldTable,DispatchTable}LinkInfo(ptr)`（一个）、`ResolveDDSlots(Thread*,Zone*)`、
`DDSlotResolution::SetSlotOwner(long, unsigned long, FunctionKey const&)`、
`Assembler::Shorebird{Enter,Leave}CFrame()`、`WrapperLayout<{CPUToSim,SimToCPU}Config>`、
`FLAG_print_shorebird_info`。

**差距（实测 grep，带阳性对照）**：`ShorebirdLinker`/`DDSlotMapping`/`DDSlotVoters`/`ResolveDDSlots`/
`ShorebirdEnterCFrame`/`WrapperAllocator`/`CPUToSimConfig`/`SimToCPUConfig`/`FieldTableLinkInfo`/
`DispatchTableLinkInfo` **十个全部无匹配**；对照组 `SetLinkedFunction`/`shorebird_link_table_`/
`ShorebirdLoadVmcode` 三个均命中，故「无匹配」为真。
→ **我们复刻了部分行为，内部结构完全不同，整套 DD slot 机制没有。**

## 🔑 发现二（2026-08-19，重大）：他们的二进制会自己 dump 内部链接状态

**规则 3 的 oracle 已打通，且不需要版本对齐。** 全部产物、解码器、验证脚本在
**`spikes/shorebird_linkinfo_oracle/`**（`./probe.sh && ./test_parsers.py`）。

做法：拿他们的 `gen_snapshot` 与 **stock Dart 3.12.2** 的 flag 表对拍
（`--help --verbose`，262 vs 249），挖出 10 个 Shorebird 独有 flag。
其中 `--print_*_link_info_to=<f>` 出二进制，`--print_*_link_debug_info_to=<f>` 出**同一份数据的 JSON**
——JSON 就是解二进制的独立 oracle。

**四个格式已全部按字节验证**（与他们 JSON 逐项相等）：

```
ClassTableLinkInfo    := count:u, {id:u, name:str, hash:str}*count, num_cids:u
FieldTableLinkInfo    := count:u, {id:u, name:str, hash:str}*count, max_field_id:u
DispatchTableLinkInfo := count:u, {offset:u, hash:str, n:u, (lo,hi)*n}*count
DDFunctionIdentity    := count:u, {u,u,u,u,u,u}*count      ← 列含义未知
str := len:u, char:s*len     编码 = Dart runtime/vm/datastream.h（无符号 marker 0x80，有符号 0xC0）
```

语义：class `hash` 是十进制 ASCII 串（`Object`→`2528784171`），即**类布局变更的判定闸门**；
field `hash` 不是数字而是 `"Owner.field <offset> <flag>"`，即**字段偏移重映射数据**；
dispatch `ranges` 是**闭区间 cid 段**。

**DD identity 六列差分实验结果（已做，2026-08-19）**：6 个 fixture 各改一个变量，
存 `fixtures/variants/`。加注释 → **零变化**（注释不进 kernel）；改函数体但长度不变 → **零变化**；
给 addOne 加一个参数 → **只有 2 行、只有 col3 变、delta 恒 +4**；换成极简程序 → 几乎全行平移。
→ 六列分三类：**col0** 是稠密递降序号（行数少 5 则全体低 5，是位置索引不是身份）；
**col2/col3** 是 kernel 派生的偏移（不是源码字节偏移：源码长 7 字节而 col3 只 +4）；
**col1/col4/col5** 是位置无关的结构属性（col5 = 31³ 的小倍数，35 个不同值，
低熵故不可能是逐函数 hash，疑为 `FunctionKey`）。
**col1 已排除是 `UntaggedFunction::Kind`**：`FOR_EACH_RAW_FUNCTION_KIND` 我们 3.7 是 17 个成员(0..16)，
拿他们 3.12.2 二进制里 `KindToCString` 的字符串逐个探测，**同样 17 个无新增**，而 col1 取值到 21。
col1/col4/col2/col3 的具体含义**仍未定性**。

**顺带发现**：他们有符号 **`CallSimulatorFromFfiTrampoline`**，我们没有对应物；
我们的 FFI 缺口正在此处（逃逸只挂 BLR、ADRP 未实现），动手前先看他们怎么处理。

## 🔑 发现三（2026-08-19 同日）：patch 链接路径已走通，拿到他们的链接算法

`spikes/shorebird_linkinfo_oracle/dd_pipeline.sh`（可复现）。
`--print_shorebird_info` 在 base 构建下静默，**喂进 base+patch link data 后吐出链接器自己的分阶段报告**：

```
Link Results 606 / Mappings from Link Results 606 / Pair Constraints 0 / Backfill 13   ← class table(606=条目数)
Link Results 1121 / Mappings from Link Results 1113 / Pair Constraints 292 / Backfill 16 ← object pool
Sorted ObjectPool, moved 0 of 1421 entries.
```

→ **base→patch 映射分三阶段依次执行：直接 link results → pair constraints → backfill**，
对 class table 和 object pool 各跑一遍（对应他们的 `class_table_mapper.cc`/`object_pool_mapper.cc`），
最后 object pool 原地重排。**这是我们完全没有的那块，现在有 oracle 了。**

**DDTable 格式已 byte-exact 破解**（`analyze_snapshot --compute_dd_table`）：
`count:u, { subgraph_hash:str(40位小写SHA-1), index:u, size:u } * count`。
hash 按字典序排序但**可重复**（66 unique/67，故不是唯一键）；`size` 恒为 4 的倍数（arm64 指令宽），12..2744。
`--dd_max_bytes` **反向**影响条目数（16→619, 64→561, 256→438, 1024→244，默认仅 67），
而 size 最大值四次都是 3408 不受影响 → 它不是对 size 的过滤器，含义未定。

**仍不可达的闭源边界**：`--compute_dd_slot_mapping` 需要 `--dd_caller_links` 作为**输入文件**，
而**两个二进制都产不出它**（gen_snapshot 无此选项）→ caller links 由闭源 `aot-tools.dill` 在 Dart 侧算。
与 `Dart_ComputeDDSlotMapping(ptr,len ×3, char**, long*)` 三对输入吻合。
**故 DD slot mapping 的 oracle 仍不可达；DD table 的可达。** `--print_dd_resolution_to` 因此仍静默。

**ObjectPoolLinkInfo 格式未定**：header `count=1380` 后是 SHA-1 串，前几条像 base/patch 成对，
但严格按 1380 条解在第 7 条错位。**又一次假 CLEAN**（误读长度吞掉大段刚好落在边界）。
优先级低——我们已有能用的 `.op.link` 读取（A4，与 GT 完全匹配）。

## 🔑 发现四（2026-08-19 同日，**最大杠杆**）：他们发布了带完整 DWARF 的未 strip dSYM

```
.../engine/ios-release/Flutter.xcframework/ios-arm64/dSYMs/Flutter.framework.dSYM
```
149 MB，**`__debug_info` 51 MB + `__debug_str` 52 MB，覆盖私有 `runtime/vm/shorebird/`**。
给出成员名/偏移/字节大小/类型/声明文件+行号/`DW_AT_const_value`——**等于拿到他们的头文件，无需推断**。
导出脚本 `spikes/shorebird_linkinfo_oracle/dump_dwarf_types.sh`。

**局限（实测）**：该 dSYM 只覆盖 **Flutter runtime 侧**类型（`WrapperAllocator`/`FunctionKey`/
`SlotVoter`/`CPUToSimConfig` 等 OK）；`ShorebirdLinker`/`*LinkInfo`/`SubgraphHasher`/各 Mapper
**全部 MISS**，因为它们在 gen_snapshot 侧，而 **gen_snapshot/analyze_snapshot 只有符号表、无 DWARF**。
那部分仍需 Ghidra 反编译。

**13 个私有源文件**（比断言路径的 6 个多）：`wrapper.{h,cc}`、`cpu_to_sim_wrapper.cc`、
`sim_to_cpu_wrapper.cc`、`link_info.{h,cc}`、`linker.cc`、`class_table_mapper.cc`、
`object_pool_{editor,mapper}.cc`、`subgraph_hasher.cc`、**`cascade_limiter.cc`**、
**`dd_voting.cc`**、**`field_hasher.cc`**（后三个此前完全不知道存在）。

### `dd_identity` 六列**已全解**（此前记为「最大空白」，现关闭）

每行 = `id` + 序列化的 `dart::FunctionKey`（DWARF 给出真名，`link_info.h`，32 字节）：

```c++
struct FunctionKey {                  // 5 个无符号 varint 上线
  intptr_t library_kernel_offset;     // 0x00
  intptr_t owner_class_kernel_offset; // 0x08
  intptr_t kernel_offset;             // 0x10
  uint8_t  kind;                      // 0x18  UntaggedFunction::Kind，255 = kAllocStubKind
  uint32_t signature_hash;            // 0x1c  base-31 Horner over 参数个数
  // IsZero/==/!=/ReadFromStream/WriteToStream/FromFunction/ForAllocStub/FromCodePtr
};
signature_hash = fixed*29791 + optPositional*961 + optNamed*31 + numTypeParams
```

**三方独立互证**：① DWARF 字段名与偏移；② 我的差分实验（加注释零变化＝注释不进 kernel；
同长度改函数体零变化；加一个参数使其后两行的 `kernel_offset` 恰好 +4）；
③ 取值分布（`kind` 全落在合法 Kind 上：0=Regular 779、3=Getter 140、5=Constructor 77、1=Closure 46；
`kind==255` 有 87 行＝93.1% 合法值的精确补集 6.9%；`library_kernel_offset` 仅 15 个值；
`signature_hash` 95.6% 是 31³ 倍数）。
→ 此前「col1 不是 Function::Kind」的结论**是对的**：kind 在 col4，col1 是 library_kernel_offset。

### DDSlotVoters 格式 + **绕过闭源 aot_tools 的路子**

**头是定宽 4 字节、不是 varint**（目前唯一破例处）：
```
u32 magic=0xDDCA7E55 (盘上 55 7E CA DD) | u32 version=2 (=DDSlotVoters::kVersion)
uvar num_slots | 每 slot: uvar slot_id, uvar num_voters,
                每 voter: FunctionKey caller_key(5 varint) + FunctionKey target_key(5 varint)
```
`SlotVoter` = 64 字节，`caller_key`@0x00 / `target_key`@0x20（DWARF 独立确认）。

**关键**：`--dd_slot_mapping=<file>` **一个 flag 吃两种格式**，`main` 嗅探前 4 字节：
`==0xDDCA7E55 && size>=8` → `DDSlotVoters::ReadFromStream`，否则 → `DDSlotMapping::ReadFromStream`。

### ✅ 已验证：闭源 aot_tools 依赖被绕过（2026-08-19）

`write_dd_slot_voters.py` 自造 DDSlotVoters，`dd_pipeline.sh` 第 6 步喂进去。
拿真实 `dd_identity` 里的 FunctionKey 当 voter，**8 个 slot 有 7 个解析到真实 Dart 函数**：

```
DD resolution: 7 resolved, 0 preserved, 0 carried, 1 dropped (tgt_miss=1) from 2878 functions in key map
DD resolution: 0 resolved, 7 preserved (0 would-have-flipped), 7 carried, 1 dropped ... from 2983
DD table: 8 slots, 7 retained, 2 rewritten, 1 unrewritten-null filled with sentinel
slot 0 resolved dart:core_::__objectEquals@0150898 / slot 2 sentinel / slot 4 resolved dart:core_Expando_[]
```

**这就是 FunctionKey wire format 与五字段语义的端到端证明**——字段错一个就会落到别的函数或 miss，
能解析到*预期*函数说明格式与语义都对。同时实证两条反汇编结论：报告**打印两次**
（`DoCompileAll` 调两次，key map 2878→2983）；第二遍 `preserved=7/resolved=0` 即 verify-only 路径。

**writer 编码器已用他们自己的字节验证**：解析 `base.ddtable` 与 `class_table.bin` 再编码回去
**逐字节相同**（3969/3969、31416/31416）。编码规则：
无符号 `while v>0x7F: emit(v&0x7F); v>>=7` 末尾 `emit(v|0x80)`；有符号末尾 `emit(v|0xC0)`。
故 ≤63 的字符（数字、`.`）占 1 字节、字母占 2 字节。

**至此 DD slot 的完整 oracle 打通：能读、能写、能驱动他们的决议并观测结果。**

### DD slot 决议算法（`ResolveDDSlots`，被 `Precompiler::DoCompileAll()` 调用两次）

三阶段：① 建 `FunctionKey → vector<uword>` 索引（遍历 库→类→函数，外加每类的 `ForAllocStub` 合成键）；
② **逐 slot 投票**：每个 voter 是 base 构建时记录的一个 (caller,target) 键对；
**仅当两个键都唯一解析**时该票有效，否则记 `tgt_miss/tgt_ambig/caller_miss/caller_ambig`；
胜者取**相对多数 plurality**（不是绝对多数、不是最小 id、不是首个）；
③ **carry-over/rescue**：未解析的 slot 回查上一次决议存的 FunctionKey。
另有 **verify-only 路径**：若上次已有 owner，则重算但**不调 SetSlotOwner**，
上次的决定优先，分歧只打 `DD slot %ld WOULD HAVE FLIPPED ... (preserved by fix)` ——
这就是跨两次 DoCompileAll 保持 slot 归属稳定的机制。

```c++
class DDSlotResolution {                                 // 128 字节
  unordered_map<long,uword>       slot_to_owner_;  // @0x00
  unordered_map<uword,long>       owner_to_slot_;  // @0x28
  unordered_map<long,FunctionKey> slot_to_key_;    // @0x50
  long max_slot_ = -1;                             // @0x78
};
```
`SetSlotOwner(slot, owner, key)` 写三张表、overwrite-on-collision、再抬 `max_slot_`。
`owner` 对真实函数是裸 `FunctionPtr`、对分配 stub 是裸 `CodePtr`（真实的不对称，不是误读）。
**复刻陷阱**：plurality 平票时保留 libc++ `__hash_table` 节点序中较早者
→ 要 bit-for-bit 一致得复现 libc++ 插入序。

### CPU↔Sim wrapper：**没有机器码模板**

DWARF 常量 + 两个内联 `Layout::fromTemplate<>` 点：`kPageSize`=16384、`kLandingPadSize`=8、
`rx/rw_mapping_size`=32768/32768、`sizeof(Metadata)`=8(`uword target_entry_point`)；
**两个方向唯一实质差异是 `kSharedBodySize`：CPUToSim=272 vs SimToCPU=28**，
由此 `num_wrappers_per_page = (kPageSize - kSharedBodySize)/kLandingPadSize` = 2014 / 2044（精确）。
一个 wrapper page 64KB：`[0,32768)` 是对 stub 自身代码页的 `mach_vm_remap(copy=1)` COW 重映射，
`[32768,65536)` 是纯 RW 元数据 → `metadata_addr == wrapper_addr + rx_mapping_size`。
**运行时从不写指令**，`WrapEntryPoint` 只往元数据存 8 字节目标地址。
landing pad 与 shared body 由正常 `StubCodeCompiler` 在构建期生成
→ **复刻需要 stub 生成器，不是字节模板**。
`StubCode::StubNames` 188 条里的新 Shorebird stub：`CallClangCodeWithSimulatorArgs`、
`CallSimulatorFromFfiTrampoline`、`SimulatorCallToRuntime`、`TransitionDartTo{Cpu,Simulator}IfNeeded`、
`RunDartOnCPU`、`ResumeOn{CPU,Simulator}`、`Simulator{Enter,Exit}Safepoint`。

### 两处纠正（都是我先前记错的）

- **`DDTableLinkInfo` 在 `analyze_snapshot`（5 个符号），不在 `gen_snapshot`（0 个）。**
  只 grep gen_snapshot 会误判「该类型不存在」。
- **`WrapperAllocator` 的「65 个符号」是错的**：那是把 universal binary 两个 arch slice
  相加、还混进了 `std::function` 机制。arm64 slice 上 shorebird 符号约 18 个。**一律加 `-arch arm64`。**

## 🔧 rebase 到 3.12.2 已开工（2026-08-19）

**决定依据**：memory 原先反对先 rebase 的理由是「等挖清 DD slot 后还要再改一遍」——
DD slot 现已挖清，该理由消失；且几乎所有 oracle 要用于**验证我们的实现**都需版本对齐
（同一 kernel 喂两边对拍 dd_identity，前提是我们能读 3.12.2 的 kernel）。

**工作区**：**`~/dart-3122/sdk`**，git worktree，分支 **`shorebird-3.12.2`** 从 `d684a576a6a` 起。
用 worktree 而非切分支，保住 `~/dart/sdk` 的构建产物。

⚠️ **必须用独立的 gclient 根 `~/dart-3122/`，不能挂在 `~/dart/.gclient` 下**：
Dart 的 DEPS 用**绝对路径** `sdk/third_party/...`（不是相对 solution 的路径），
所以在 `~/dart/.gclient` 里加第二个 solution 会报
`Dependency sdk/third_party/binaryen/src specified more than once`，
而且真跑下去会把 3.7 树的依赖升级成 3.12.2 版，**破坏 3.7 的构建**。
已还原 `~/dart/.gclient`（备份 `.gclient.backup-before-3122`）。

**复用 3.7 依赖的路走不通**（试过，别再试）：符号链接 `buildtools`/`third_party` 能过 binaryen，
但 `third_party/perfetto/src/src/protozero/BUILD.gn` 在 **3.7 树里根本不存在**——
3.12.2 的 perfetto 布局变了。递归补链 203 个符号链接后仍卡住，只能正规 `gclient sync`。
另需手动补 `build/config/gclient_args.gni`（gclient 生成物，内容仅一行注释）。

### 移植面实测（不是猜）

| 类别 | 数量 | 结论 |
|---|---|---|
| 新增文件 | 10 | **零冲突**，已提交 `741c7607c62`（967 行） |
| `isnan` 机械替换 | 13 | 已提交 `6070f5396bf`（97+/97-） |
| `directory_macos.cc` | 1 | **丢弃**：我们的 diff 与上游 37+/30- **完全相同**（规则 2 已换成上游实现） |
| 上游无变化的文件 | 7 | 零冲突 |
| 真实手工移植 | ~20 | ~1100 行核心逻辑，**未开始** |

**35 个修改文件在 3.12.2 全部仍存在**（没有被删），消除了一个大风险。

### ⚠️ 关键：上游把 `USING_SIMULATOR` 全局改名为 `DART_INCLUDE_SIMULATOR`

3.7：`USING_SIMULATOR` 42 文件 / `DART_INCLUDE_SIMULATOR` 0；
3.12.2：`DART_INCLUDE_SIMULATOR` 41 文件 / `USING_SIMULATOR` 仅剩 2 处。
→ **我们所有引用 `USING_SIMULATOR` 的代码在 3.12.2 上都要改名**（含刚移植进去的
`shorebird_sim_to_cpu_test.cc`，它现在还写着旧名，尚未改）。

上游另新增 `TARGET_HOST_MISMATCH`，但**实测只用于 `cpu_arm.cc` 的 `IS_SIMARM_HOST64`
（64 位 host 跑 32 位 ARM），与 FFI 无关** → 它**不是**我们 C3 要的
「代码生成 vs Simulator 可用性」分离。**C3 仍然必须做**，只是要基于新宏名重写。

### 🔑 三处「上游已经做了」——按规则 2 弃用我们的自研版

移植时逐个核对上游现状，发现三件我们手写的东西已被上游正式实现，我们的版本作废：

1. **`dart_force_simulator` GN 参数**（`runtime/runtime_args.gni:35`，注释字面是
   "Force use of the simulator even when the Dart target arch matches the current cpu"）
   → **A1 手改 `globals.h` 强开 simulator 完全作废**，改用 `--gn-args dart_force_simulator=true`。
   3.7 基线**没有**这个参数。已实测 gn 接受该参数。
   *（这也可能解释 Shorebird 的 `macos_simarm64`：他们大概就是这么构建的。）*
2. **`SIMULATOR_FFI`**（`runtime/BUILD.gn:220`，`dart_force_simulator && arch==arm64` 时自动定义）
   → **我们的 `SIMULATOR_HOST_ARCH_MATCH` 作废**，`ffi_dynamic_library.cc` 整个回退到上游。
   上游这套覆盖 `il_arm64.cc`、`stub_code_compiler_arm64.cc`、`ffi_callback_metadata.cc`（6 处），
   **我们的宏一处都没碰过** → **memory 里记的 FFI 缺口（ADRP/BR 逃逸未覆盖）很可能已被上游解决，
   待构建后复验**。
3. **`analyze_snapshot` 的平台限制**：上游已把 `#if ... && (ANDROID || LINUX)` 整个去掉，
   只留 `TARGET_ARCH_IS_64_BIT && DART_PRECOMPILED_RUNTIME`
   → 我们「放宽到 macOS」的改动作废。

**C3 仍然必需**（上游只把 `USING_SIMULATOR` 改名，没做分离），但缩到最小形态：
只在 `globals.h` 末尾保留 `DART_INCLUDE_SIMULATOR → SIMULATOR_AVAILABLE` 的推导，
分离构建靠命令行传 `-DSIMULATOR_AVAILABLE`，不再按架构硬编码。

### 移植完整性核对（45 = 36 移植 + 9 剔除）

7 条提交，36 文件，1997+/120-。**9 个未移植文件，每个都有规则依据**：
`directory_macos.cc`（规则 2，与上游 diff 完全相同）、
`ffi_dynamic_library.cc`（规则 2，SIMULATOR_FFI 取代）、
`stub_code_compiler.cc`（规则 1，改动在 `#if DART_DYNAMIC_MODULES` 内）、
`lib/object.cc` + `bootstrap_natives.h` + `internal.dart` + `internal_patch.dart`
（规则 1，5 个 Gate 1 spike native：`loadDynamicModuleClosure`/`invokeDynamicModuleClosure`/
`redirectDispatchTableEntry`/`redirectClosureEntryPoint`/`countClosuresForFunction`）、
`dispatch_table.h` + `dispatch_table_generator.cc`（规则 1，Gate 1 V2 spike）。
**共 202 行 Route-A 技术债没有搬进新分支。**

**核心文件用真三方合并**（`git merge-file --diff3`，base `37bbc285d8d`），不是 checkout：
两侧改动真实重叠（我们在 `InvokeFloatLeafRuntime` 附近插 166 行，上游在 `DoRedirectedCall`
附近插 173 行，且都改 `JumpToFrame`）。结果 `simulator_arm64.h` **零冲突**，
`.cc` 仅 2 处（都是宏名碰撞）。全部文件合计只有 10 个冲突块。

### ✅ 构建通过（2026-08-19）：`gen_snapshot` 已在 3.12.2 上编译链接成功

```
我们:      Dart SDK version: 3.12.2 (stable) (2026-08-19) on "macos_simarm64"
Shorebird: Dart SDK version: 3.12.2 (stable) (2026-06-11) on "macos_simarm64"
```
**同版本、同平台串**。构建命令：
`python3 ./tools/gn.py --mode=release --arch=arm64 --no-rbe --no-verify-sdk-hash --gn-args 'dart_force_simulator=true'`
然后 `ninja -C xcodebuild/ReleaseARM64 gen_snapshot`。
产物含 `SetPendingVmcodeFile`、`Dart_ShorebirdLoadVmcode` 符号（我们的 B4 确实进了二进制）。

**构建踩的坑（会再遇到）**：
- `NO_SANITIZE_UNDEFINED` 从 3.7 的 GNU `__attribute__((no_sanitize))` 变成 3.12.2 的
  **C++11 attribute `[[clang::no_sanitize]]`** → **不能再写在 `static` 与返回类型之间**
  （报 `attribute cannot be applied to types`）。上游风格是 `NO_SANITIZE_UNDEFINED_FUNCTION`
  单独一行置于声明最前。我们 A2 的 `InvokeWithTHR`/`CallHostFunction` 两处需改。
- 必须 `--no-verify-sdk-hash`，否则我们改过源码的 gen_snapshot 拒收 stock 3.12.2 的 kernel
  （`Can't load Kernel binary: Invalid SDK hash`）。

### 快照 hash 的机制已查明（2026-08-19 订正，此前记错）

`Wrong full snapshot version, expected '839937ddd3133a1c0758aeeefce5448c'`。
三个值：他们 `839937ddd3133a1c0758aeeefce5448c`、stock 3.12.2
`ace654289f5abc240509fc941453ebc5`、我们 `f85c65b51394e211aedeb05f0ab508c1`。

⚠️ **此前记的「该 hash 由 VM 数据结构布局决定」是错的。**
它是 **`tools/make_version.py: MakeSnapshotHashString()` 对 15 个指定源文件原始字节的 MD5**：
`app_snapshot.{cc,h}`、`dart.cc`、`dart_api_impl.cc`、`datastream.h`、
`image_snapshot.{cc,h}`、`object.{cc,h}`、`raw_object.{cc,h}`、`snapshot.{cc,h}`、
`symbols.{cc,h}`。**已实测确认**：对我们这 15 个文件算 MD5，结果与我们二进制自报的
`snapshot_hash_` 逐字符相同。**与构建 mode、架构、他们新增的私有文件全部无关。**

**这改变了它的性质**：它不是「随复刻自动收敛的度量」，而是**对 15 个上游文件的校验和**。

### 🔴 结论：快照 hash **不可达**，别再把它当完成度判据（2026-08-20 定案）

`MakeSnapshotHashString` 是 `open(f,'rb').read()` 喂 md5 → **对原始字节做哈希，包含注释、
空白、行尾**。而注释和空白在**任何**编译产物里都不存在：DWARF 给声明、行号、类型，
给不出注释。所以除非他们的源码泄露，这个 hash **永远不会匹配**。

它「完全客观」但**不可达**，因此作为判据无效。**别在它上面投入。**
完成度要用别的判据：byte-identical 的 dump 输出、功能等价性、真机行为。
（此前我在同一会话里称它为「唯一完全客观的 100% 判定」——客观是对的，可达是错的。）

### ✅ 但行表差分本身产出了高价值结果（task #8 已完成）

产物：`spikes/shorebird_linkinfo_oracle/scripts/dsym_line_diff.py` + `DSYM_LINE_DIFF.md`。

**4 个文件确证被改，且全部是「尾部追加」，不是散布在文件中间的手术式改动**：

| 文件 | stock 行数 | 他们最大代码行 | 最小 Δ |
|---|---:|---:|---:|
| `app_snapshot.cc` | 10293 | **10930** | **+637** |
| `object.cc` | 28690 | **28810** | **+120** |
| `object.h` | 13832 | **13884** | **+52** |
| `dart_api_impl.cc` | 7255 | **7296** | **+41** |

- `app_snapshot.cc` 的 +637 追加在 stock 约 10288 行之后（`FullSnapshotReader::InitializeBSS`
  里的 `BSS::Initialize`）——**最大的一处，与 vmcode 加载/链接胶水代码的位置吻合**。
- `dart_api_impl.cc` 的 +41 对应 2 个导出函数（`Dart_ShorebirdLoadVmcode` +
  `Dart_DumpSnapshotInformationShorebirdAsJson`），与此前结论独立互证。

**11 个文件无信号 ≠ 未改**：停留在 stock 行数范围内的改动、或只改注释/声明，本方法看不见。
`snapshot.cc`（整个文件被内联，只有一条 end_sequence）与 `dart.cc`（AOT 构建下仅 5 行有代码）
**完全不可测**。

**这个结果的真正价值不在 hash，而在告诉我们钩子该加在哪**：改动集中在 4 个文件的尾部，
总量约 850+ 行（下界）。做**功能复刻**时这就是挂载点地图。

**定位他们改了哪几行的方法（已验证可行）**：他们 dSYM 的 DWARF 行表给出每条指令的
`(file,line)`，即每个上游文件「真正有代码的行号集合」，插入会使其后整体平移。
按 CU 走 `DW_AT_stmt_list`（整体 `--debug-info` 有 51 MB 不可用；`--die-offset` 返回空；
`--debug-line=<stmt_list>` 可用）：
```bash
dwarfdump --debug-info --recurse-depth=0 Flutter | grep -n 'dart_api_impl.cc'
dwarfdump --debug-line=0x00827d1e Flutter
```
首个结果：他们 `dart_api_impl.cc` 行表到 **7296 行**，而 stock 3.12.2 整个文件才 **7255 行**
（我们 7289）→ **他们至少加了 41 行**，与 `Dart_ShorebirdLoadVmcode` /
`Dart_DumpSnapshotInformationShorebirdAsJson` 在该文件吻合。他们 `object.h` 到 13647 行。

### 📊 差距已量化到 flag 层面：只差 11 个

同一份 stock kernel 喂两边产汇编，我们 208697 行 vs 他们 143197 行（多 45%）。
定性结论：**构建 mode 不同**——我们独有的 flag 全是 debug 类
（`coverage`/`deoptimize_alot`/`gc_during_reload`/`identity_reload`/`heap_snapshot_on_oom`…），
说明他们的 `ios-release` 是 **product mode**，我们用的是 release+develop。下次对比要用 `--mode=product`。

**而他们独有的 flag 恰好就是那 11 个 Shorebird 私有 flag，除此之外零差异**：
`print_{class_table,field_table,dispatch_table}_link{,_debug}_info_to`、
`print_dd_function_identity_to`、`print_dd_resolution_to`、
`print_dispatch_table_debug_info_to`、`print_shorebird_info`、`load_obfuscation_map`。
→ **这就是剩余功能差距的完整清单，且这 11 个的语义与文件格式我们已全部破解**
（见 `spikes/shorebird_linkinfo_oracle/`）。下一步就是在这个分支上实现它们，
用他们的输出逐字节对拍。

### ✅✅ 首个 byte-identical 复刻完成（2026-08-19）：class table link info

`runtime/vm/shorebird/link_info.{h,cc}`（放在他们自己的目录布局下）实现了
`--print_class_table_link_info_to` 与 `--print_class_table_link_debug_info_to`。
**同一份 kernel 下，二进制(31416 B)与 JSON(36761 B) 与 Shorebird 的输出 `cmp` 逐字节相同。**
11 个私有 flag 中的 2 个已完成。

**hash 算法（反推 + 数据双证，非猜测）**：
```
hash = str(Utils::StringHash(ScrubName(name))) + str(nth_occurrence)
```
① 反编译他们的 `GetClassTableLinkInfo` 得调用链
`Class::Handle → String::ScrubName → Utils::StringHash → std::to_string`（还有 `__base_10_u32`，暗示 u32）；
② 数据侧验证：去掉末位后 **606/606 全部 < 2³²**（不去掉只有 62 个），
且末位为 `2` 的恰好是三个 ScrubName 重名类
（`Function` cid 7/598、`Symbol` 308/521、`_UnmodifiableMapMixin` 384/432），
各自与 cid 较小的孪生兄弟**共享同一 hash 主体**。
挂载点：`Precompiler::DoCompileAll()` 末尾（此时 class table 已定稿）。
文件写入走 embedder 的 `Dart::file_{open,write,close}_callback()`——
与他们的错误串 "requires Dart file callbacks (open/write/close)" 一致。

### field table link info：622/622 条数与 max_field_id 已对上，剩 3 类残余差异

`FieldHasher::DuplicateAwareHash` 已反推出：
```
ScrubName(owner) + '.' + ScrubName(name, is_ext) + ' ' + kind_bits + ' ' + occurrence
```
反汇编依据：`push_back(0x2e='.')`、`push_back(0x20=' ')`、
`__base_10_u32` 的入参是 `ldur w8,[x8,#0x5f]`——**整个 `kind_bits_` 字**（不是取某几位）。
同一偏移被 `>>0xb`/`>>0xc` 用来判 is_extension，由此确定 `ConstBit` 在 bit 0，
`IsExtensionMemberBit`=11、`IsExtensionTypeMemberBit`=12。
`id` = `Field::field_id()`（原始 `host_offset_or_field_id` Smi，他们代码是 `[x+0x27]` 再 `>>1`），
**不限于静态字段**，所以 id 会跨类重复。

**他们的 `CollectAllStaticFields` 是遍历堆**（`Heap::ResetObjectIdTable` +
`UntaggedObject::VisitPointers`），不是走 library 字典——走字典只能找到 360/622。

**挂载点靠实测定位**（三次试错）：`DoCompileAll` **末尾**字段已被 drop（只有 423）；
**开头**字段还没从 kernel 加载（更少）；**`DropFunctions()`/`DropFields()` 之前**才对（622）。

**最终结果：内容完全一致（多重集合相等、排序后逐条相等、输出 47426 B 同尺寸），
仅剩同 field_id 内的顺序不同。** 又解出两个编码细节：

1. **kind_bits 要 mask 掉 bit16(`NoSanitizeThreadBit`) 与 bit17(`HasDeeplyImmutableTypeBit`)**：
   他们的输出里这两位**从不出现**（我们原有 5 条 bit17、1 条 bit16），
   mask 后 11 条差异全部消失。这两位描述线程/内存模型而非字段身份。
   ⚠️ **这否证了我先前「Shorebird 关闭了 deeply-immutable」的猜测**——
   他们二进制里 `EnsureDeeplyImmutable`/`CheckedStoreIntoShared` 都在（12 处），
   且这些 stub 无条件编译；那次汇编体积差异是 **build mode 差异**，不是缺特性。
2. **重复项是追加 `" 1"`，不是把计数递增**：`ClassID` 的 93 个字段名各出现两次，
   编码为 `ClassID.cidNull 3 1`(id 0) 与 `ClassID.cidNull 3 1 1`(id 94)；
   529 条三段条目的末段恒为常量 1，故首个 `" 1"` 总在，每多一次出现再追加一个。

**残余的顺序差异不是算法问题**：他们同 id 内既非字母序也非 owner cid 序
（实测 id=1 的 owner cid 依次是 501,521,187,442,…），即**堆遍历顺序**，
取决于堆布局 → 要对齐需两个 VM 分配行为完全一致，与快照 hash 属同一类约束。
（之前记的「93 个 id 差 94」是我按 (name,qualified) 配对时错位造成的假象，**id 实际全部一致**。）

需要 `Field::kind_bits()` 新 accessor（`kind_bits_` 是 protected）。

### ✅ dispatch table link info：**已 byte-identical**（2026-08-19，commit `cd4aeecd189`）

**offset 差异已解决，改动只有一处**：`RowFitter::FitAndAllocate` 只在 **256 的网格上**
发 offset（`Utils::RoundUp(min_offset, 256)`，循环里 `RoundUp(next_offset, 256)`）。
换密度换稳定性——patch 构建才能和 base 对上同一个 selector 的 offset。

**为什么能断定只有 fitter 不同**：落在 `kOriginElement`(arm64=4096) 上的 21 个 selector
在两个二进制里**本来就是同一批**，说明 pass 1 与三个排序全是上游原样。
（arm64 `kOriginElement=4096`、`kLargestSmallOffset=8192`。）

**验证**：六个 fixture（hello + 五个差分 variant）**两边都用新编的 dill 现场重跑**，
不是比对旧快照 → **6/6 逐字节相同**，`_debug_` JSON 孪生也逐字节相同。
`e_minimal` 是 3182 B 而其余 3214 B，说明 fixture 内容确实不同而仍然全对。

**仍未验证**：装着这张更稀疏的表的快照能不能**真正执行**。能干净地序列化成 ELF，
且超过 `kLargestSmallOffset` 的 offset 走的是上游本来就有的慢路径，但没跑过任何快照。

<details><summary>原始记录（offset 未解时的推断，已被证实）</summary>

selector 数一致(123)，共同 offset 的 ranges 与 hash **全部相等** → 收集与序列化正确。
DWARF 确认记录就是 `SelectorRowInfo{offset_, hash_, ranges_}`。
收集逻辑必须放在 `dispatch_table_generator.cc`（`SelectorRow` 是该 TU 局部类型，
这也是他们的 `GetDispatchTableLinkInfo` 为何是 `DispatchTableGenerator` 成员），
且要在 `ComputeSelectorOffsets()` 之后。

**offset 对不上，且这像是他们的实质 VM 改动而非格式误解**：
他们发出的 offset **全部是 256 的倍数**（0,256,512,…,6656,8192,9728），
我们的是 `RowFitter` 紧凑打包的结果（1,2,3,…,1702,2992）。
把 selector offset 按 256 对齐能让 offset 在 base 与 patch 之间保持稳定——
这正是匹配所需 → **推测他们替换了 `ComputeSelectorOffsets` 的打包算法**。
证实需反推其分配器，而**复刻它会改变生成的快照本身**，不只是这个诊断输出。

</details>

### 🔴 结构性发现：DD 整套机制是 Shorebird 私有发明，上游零基础

实测：`FinalizeIndirectStaticCallTable` / `IndirectStaticCall` /
`ReplaceStaticCallsWithIndirectCalls` / `dd_slot` 在 3.12.2 上游 **各 0 个文件**
（阳性对照 `StaticCallInstr` 有 24 文件）。所以这些全是他们自己加的：
新 IL 指令 `IndirectStaticCallInstr`、IL 变换 `AotCallSpecializer::ReplaceStaticCallsWithIndirectCalls`、
建表 `Precompiler::FinalizeIndirectStaticCallTable` + `DDTableBuilder::VisitCode`、
以及 DD slot 决议全套。

**后果：`print_dd_function_identity_to` 与 `print_dd_resolution_to` 无法作为「再写一个 dump」来复刻**
——它们是 DD 机制的诊断输出，必须先实现 DD 机制本身。
「继续做 dump flag」这条路到此为止，剩余 flag 依赖关系：

| flag | 依赖 | 可否单独做 |
|---|---|---|
| `print_dispatch_table_debug_info_to` | 无 | ✅ **已完成**——**它在他们自己的二进制里就是死 flag**（见下） |
| `load_obfuscation_map` | 仅 Obfuscator（上游已有） | ✅ **已完成**（见下） |
| `print_dd_function_identity_to` | ~~DD 机制~~ **global object pool + FunctionKey** | ✅ **可以，此前判错了**（见下） |
| `print_dd_resolution_to` | DD 机制 + 决议 | ❌ |
| `print_shorebird_info` | 三阶段映射 | ❌ |

### 🔁 订正（2026-08-20）：`print_dd_function_identity_to` **不被 DD 阻塞**

脚本 `spikes/shorebird_linkinfo_oracle/dd_identity_probe.sh`（可复跑，exit 0）。
此前判它「blocked on DD」只是因为名字里有 DD。**而 `dd_pipeline.sh` 第 6 步早就反证了**：
它在**纯 base 构建**上调这个 flag，无 link data、无 `--dd_slot_mapping`，照样出完整 dump。

### 🔴 再订正（2026-08-24）：**不是 object pool，是 code 表**——行谓词已逐条验证

下面「它 dump 的是 global object pool」**是错的**，1380 这个数不是 pool 条目数。
实测：`analyze_snapshot --dump_object_pool=` 的 raw pool 是 **1421** 条
（1323 obj + 92 native + 6 unknown，**没有任何子集等于 1380**），索引空间根本对不上。

**1380 的真身**：`analyze_snapshot --shorebird --out=` 的 **`functions` 列表**长度，
也等于 `--dump_object_pool` JSON 里 `code_infos` 的长度。每条带 `index_in_entries`，
span 恰好 `0..1379`。→ **col0 = code entry index，不是 pool index**，
这也正好解释了为什么读取点在 `Serializer::PrepareInstructions`——那里建的就是 `code_index_`。

**行谓词（逐条判定，0 例外，不再是计数算术）**：对 code 表里第 i 条，
```
[Stub] Allocate <Class>      → 出行，kind=255（ForAllocStub）   87 条
[Stub] Type Test Type: ...   → 不出行                           110 条 ┐ 合计 114
[unknown stub]               → 不出行                             4 条 ┘
其余（真 Dart 函数）          → 出行，kind=FromFunction         1179 条
```
双向零例外：`kind==255` 里非 `Allocate` 的 **0** 个；`kind!=255` 里是 `[Stub]` 的 **0** 个；
`Allocate` 总数 87 与 `kind==255` 行数 **精确相等**。
`kind` 直方图全落在 `UntaggedFunction::Kind` 上且语义自洽：
3=Getter(`.value`)、4=Setter(`.value=`)、5=Constructor(`new X._`)、
6/7=Implicit{Getter,Setter}、12=InvokeFieldDispatcher(`_Closure.call`)、最大 14。

⚠️ **教训（与 [[feedback-false-green-traps]] 同型）**：「差值恒为 114、两数随程序同步变化」
是真不变量，但它**只约束计数，不定性语义**。旧结论把它读成「每行=一个 pool 条目」，
按 pool index 对照时 present/missing 两边都混着字符串和 Field，**本该当场证伪却没做这一步**。
定性结论必须有逐条判定，计数不变量不够。

<details><summary>旧记录（已被上面证伪，保留作对照）</summary>

**它 dump 的是 global object pool**。六个 fixture 全测：

```
hello/b_shift/c_body/d_sig  dd_identity=1266  op_count=1380  diff=114
e_minimal                   dd_identity=1261  op_count=1375  diff=114
f_heavy                     dd_identity=1292  op_count=1406  diff=114
```

`op_count` = `analyze_snapshot --dump_object_pool_link_data` 的头部计数。
**差值恒为 114**，而两个数随程序同步变化；`col0` 恰好铺满 `0..op_count-1` 且全互异。
→ **每行 = 一个「是函数或分配 stub 」的 object pool 条目，键就是 pool index**；
缺的 114 个是与程序无关的其余 pool 条目。`kind==255`（分配 stub，87 个）**按 index 与函数交错**，不成组。

</details>

→ 需要的只是 **序列化器的 code 表** + `FunctionKey`（两样都有），
**不需要 `IndirectStaticCallInstr` / DD 表 / slot 决议**。挂载点是 `Serializer::PrepareInstructions`。
**真正被阻塞的 flag 是 2 个，不是 3 个。**

### ✅✅✅ `ResolveDDSlots` + `print_dd_resolution_to` 已实现（2026-08-24，`d1fd67bb607`）——第 10 个 flag

🔴 **它也不被 DD 阻塞——memo 又一次因为「名字里有 DD」误判。** 与
`print_dd_function_identity_to` 完全同型的错误，同一天连中两次。
**slot 来自 voters 文件本身**，不来自 `IndirectStaticCallInstr` 或 DD 表。

实现在 `linker.cc`：`BuildKeyMap`（走 库→类→函数 + 每类一个 `ForAllocStub` 合成键）
→ 逐 slot 投票（**两个键都唯一解析才算有效票；胜者取 target**）→ carry-over。
调用点在 `precompiler.cc` **两处**：`Iterate()` 之前（pass 1）与 `DropFunctions()` 之前（pass 2）。

⚠️ **调用点不能放在 `DoCompileAll` 末尾**：那里库字典已被 drop，直接 SEGV（`si_addr=0x438`）。
与 memo 记的 field table 挂载点是同一个坑。

**验收（他们自己的 gen_snapshot 跑同一 fixture）**：
- **pass 2 报告行逐字节相同**（`0 resolved, 7 preserved, 7 carried, 1 dropped, from 2983`）
- pass 1 **每个决议计数器都相同**，只有 key map 大小差（我们 2896 / 他们 2878，差 18 个函数的时机差）
- **TSV 全部 8 行相同**，含 slot 2 的 sentinel 与每个 slot 决议出的**函数全名**

**负控制**：把胜者从 target 改成 caller → 每个 slot 都决议成 voter 的 caller
（`Map._fromKeyValues`、`_objectHashCode`…），TSV 对拍与新单测双双变红（255）。
**这个交换能穿过所有结构性断言**（流照样解析、slot 照样决议、计数照样是「7 resolved」），
只有比对**赢家的身份**才抓得到——正是 memo 早就记过的那条。

**明确未做（不粉饰）**：
① TSV 的 `rewritten` 列与 header 计数属 DD 表改写步骤，**确实需要 DD IL 子系统**，
我们发 0 而不是猜（他们 `rewritten=2`，我们 0）；
② **相对多数的平票分支零覆盖**——所有能造的 fixture 每 slot 只有 1 个 voter，
他们靠 libc++ hash 序、我们靠 first-encountered，oracle 过了**不代表这条分支对**；
③ `refreshed` / `dropped-stale` 恒为 0，没有 fixture 能走到。

⚠️ **第 12 种假绿（本次新踩）**：`sed -i.bak` 改坏 → 构建 → `mv .bak` 还原后，
**还原的文件 mtime 早于负控制那次构建的 `.o`**，ninja 判定无需重建 → 测试仍用负控制版本、
报 FAIL。还原源码后必须 `touch` 再构建，或直接看 ninja 有没有真的重编那个文件。

### ✅✅ 已实现（2026-08-24，commit `555cb48abd6`）——第 9 个 flag

`runtime/vm/shorebird/link_info.{h,cc}` 的 `DDFunctionIdentity` +
`FunctionKey::{FromFunction,ForAllocStub}`（`dd_voting.{h,cc}`），
挂载点 `Serializer::PrepareInstructions`，在 `RelocateCodeObjects` **之前**（`code_objects` 已定稿）。

**验收（六 fixture，用他们自己的 `.ddid` 对拍）**：行多重集合**全等**，
文件字节数也**全等**（14925/14874/15242 两边相同）。73/73 shorebird 测试通过。
flag 描述串与他们 `--help --verbose` **逐字节相同**：
`Print DD function identity table to the given file`。
→ **我们的 flag 面现在是他们的严格子集**，只差 `print_dd_resolution_to` 与 `print_shorebird_info`。

**字段来源（全部实测，非推断）**：
`library_kernel_offset` = `Library::kernel_library_index()`——**`Library` 根本没有
`kernel_offset()`，这个选择是被强制的**，名字是他们 DWARF 的；
`owner_class_kernel_offset` = `Class::kernel_offset()`；alloc stub 的
`kernel_offset` 与 `signature_hash` **恒为 0**（他们 87 行全是）。

**两个负控制都做了**（memo 铁律）：
① `library_kernel_offset + 1` → 恰好 1179 个函数行变化、87 个 stub 行不变（精确到子集）；
② 给 `ForAllocStub` 写上「最自然的错误实现」`kernel_offset = cls.kernel_offset()`
→ 新测试 exit 255。说明断言承重（`Object` 类的 `kernel_offset()` 非零）。

⚠️ **过程中两次踩到 memo 记过的假绿，护栏都当场抓到**：
① 负控制那轮 `NINJA_EXIT=1` 但 `gen_snapshot` 照跑照 exit 0、还报「行集相等」
——陈旧二进制（第 2 种）；
② `for t in $TESTS` 在 **zsh 下不分词**，71 个测试被当成 1 个参数跑了一次，
报 `PASS=0 FAIL=1`。**bash 习惯在 zsh 上会静默退化成单次迭代**，
测试循环一律用 `while read -r` + 文件。

🔓 **顺序仍未解，但有新线索**：他们 = 1 条 1187 行降序长跑（1379→29）+ 79 行散在 52 个短跑；
**尾部行两两配对、差值恒为 797**（825/28、824/27、823/26、…、最后一对 797/0）
→ 像**两条降序流的交织**。`sorted(theirs) == ours` 精确成立。
`--dump_object_pool` 的 raw pool = 1421 条这一事实也已记下，别再拿它当索引空间。

### ✅ 发出顺序也已解（2026-08-24，commit `10bc4f54b6d`）：**七个 fixture 逐字节相同**

顺序不是任何算法，是 **libc++ `std::unordered_map<intptr_t,…>` 的迭代顺序**
（按 code index 升序插入）。两条容器性质就决定了全部形状：

- 插入**空桶**时节点被压到唯一那条侵入式链表的**头部** → 不碰撞的键倒序出来，
  正是 1379→29 那条 1187 行的长跑；
- `__do_rehash` 只搬「新桶已被占用」的节点，其余原地不动 → 碰撞过的键永远黏在一起，
  正是那 79 行的短跑。

桶宽走 **2, 5, 11, 23, 47, 97, 197, 397, 797, 1597**（不小于 2 倍前值的最小素数），
尾部每个短跑都是某个桶宽下的碰撞：47..48 在宽 47 撞、97..103 在 97、197..204 在 197、
397..409 在 397、797..825 在 797。旧记录里的 `b, b+96, b+196, b+396, b+796`
**偏移记错了 1**，实际是 `b, b+47, b+97, b+197, b+397, b+797`，而 797 跨程序恒定
——「常数不随程序规模变化」本身就该指向容器宽度而不是数据属性。

实现只改了一处：收集用 `std::unordered_map` 代替 `std::vector`，按迭代序写出。
⚠️ **绝不能 `reserve()`**，桶宽历史就是顺序。方法论见 [[reference-stl-container-order-artifacts]]。

*仍然成立的旧结论*：全表 **1266 个 key / 1266 行，零重复** →
**`FunctionKey` 在这个快照上是单射的**，是真身份不是桶。

### ✅ `load_obfuscation_map` 已完成（2026-08-19，commit `0d9a2320028`）

11 个私有 flag 中的第 3 个。`gen_snapshot --help` 与 Shorebird **逐字节相同**，
VM flag 描述串也逐字节相同。

**它是 VM flag，不是（只是）bin 选项**——他们的 flag 描述串自己说明了原因：
"Path to a JSON obfuscation map file to load **before kernel translation**."
bin 侧 `--load-obfuscation-map=<f>` 只是把 `--load_obfuscation_map=%s` 转发给 VM
（两个串都在他们二进制里），VM 自己用 embedder file callbacks 读文件
（他们的错误串 `Could not load obfuscation map: file callbacks not set`）。

⚠️ **memory 此前记的方案是错的，已实测证伪**：「在 `precompiler.cc:3387` 的
`Obfuscator` 构造之前灌 object store」做不到。`Dart_CreateIsolateGroupFromKernel`
**加载 dart:core 时就已经在改名**，等 embedder 有机会调用时类成员早已按
*新计数器* 的改名注册好了，之后再灌 map 会让后续查找解析到不同的名字：
`Lookup failed: _normalized in dart:core in @constructors in _BigIntImpl`。
**只有编译与 map 来源不同的程序才暴露**——自身 round-trip 会通过，因为新生成的
改名恰好与 map 一致。正确做法：在 `Obfuscator` 构造函数里**惰性**播种
（首次改名即触发），这才真正早于 kernel translation。

**计数器必须重建**：`SerializeMap` 只写改名、不写 `kSavedStateNameIndex` 的计数器。
我们从 map 里最大的改名之后续接，序按 `NextName` 的进制（小端位 `a..z A..Z`，长者更后，
末字符最高位）。**他们续接得偏早（2237 vs 实际 2280），重发了 44 个已被库 URI 占用的名字**，
破坏了他们自己 fresh 构建保持的单射性 → **我们刻意不复刻这个 bug**（实测重复值：我们 0、他们 8）。

**交叉验证**：喂他们的 map、编同一程序，我们的输出与他们**完全相同（4568/4568）**；
编改动过的程序只差 12/4582 条（就是新符号那几条）。
另外我们 fresh map 与他们只差 103 条**库 URI** 改名——又是「堆遍历顺序」那类差异
（URI 改名走堆遍历），与 field_table 的残余差异同源。

### ✅ ShorebirdLinker slice 1 已完成（2026-08-20，6 提交，33 测试全 exit 0）

plan：`docs/superpowers/plans/2026-08-20-shorebird-linker-slice1.md`。
**这是第一个真正进入生产产物并被证明跑对了的新子系统**（wrapper.cc 至今被 dead-strip）。
两半证据都有：符号检查证明 *linked in*，B1–B6 端到端证明 *ran correctly*，缺一不可。

- 单例 136 字节布局、`dart::` 命名空间（**不是** `dart::shorebird::`，那个只归 Wrapper 家族）、
  static 名 `shared_linker` —— guard 符号与他们**逐字符相同**
- 3 个 `Initialize*` 签名匹配他们实测的 `unique_ptr<T, default_delete<T>>`
- 3 个 wire format decoder，count 驱动，文件与流路径共用同一个 decoder
- 4 个 bin 选项：拼写、配对错误串、**以及「都不出现在 --help --verbose」**均与他们逐字节一致
- 畸形输入大声拒绝而非静默返回空表（B3–B6 在此之前全部 exit 0）

**七个 `ShorebirdLinker` 方法我们有 4 个**（`shared` + 3 个 Initialize），
缺 4 个：`InitializeWithObjectPoolLinkInfo`、`InitializeWith DDSlot{Mapping,Voters}`、`ResolveDDSlots`。

**它读取并持有 link info，不链接任何东西** —— 快照没有任何变化。唯一能证明产生效果的是
`ResolveDDSlots`，未动。`ObjectPoolLinkInfo` 缺席不是选择：没有输出 flag 能造 fixture，
所以它的 reader 无法被 oracle 验证。

**D1（计划外前置）**：`*LinkInfo` 不能继承 `ZoneObject`。
`ZoneObject::operator new` 走 `Thread::Current()->zone()`（无 isolate 时空指针，实测 si_addr=0x18）；
`operator delete` 是 `UNREACHABLE()` = `FATAL(...)` 且**无 DEBUG 门控** →
`unique_ptr<*LinkInfo>` 在 **Release/Product 也会 abort**。是个潜伏的生产崩溃。
方向由他们的 `default_delete` 符号决定（实测），不由方便决定。
**六 fixture 对拍证明整个 slice 零字节变化**（36/36，与 pre-D1 基线比，累计）。


### DD slice 2a 已完成（2026-08-20，4 提交，34 测试全 exit 0）

plan：`docs/superpowers/plans/2026-08-20-shorebird-dd-voting.md`（含 12 处执行期修正）。
提交 `40d82013929` / `61b55e88196` / `cd9d3510be8` / `a9a5341e8e9`。

**DD 数据层完成且经 oracle 验证**：`FunctionKey`(32B)、`SlotVoter`(64B)、
`DDSlotResolution`(128B) 全部 size-assert；`DDSlotVoters` reader 逐字段解析他们真实的
`voters.bin`（185 字节已嵌入测试，`PendingBytes()==0`）；`ShorebirdLinker` 在实测偏移持有
三个 DD 字段；`--dd_slot_mapping` 带格式嗅探 + 校验 + 大声拒绝。
端到端：`DDSlotVoters loaded: 8 slots, 8 voters`，与他们的 `DD table: 8 slots` 吻合。

**⚠️ 落地口径（实测，不记账）**：4 个 DD 类型里 **3 个进产物，`DDSlotResolution` 是 0**。
`SetSlotOwner` 无生产调用者（仅定义 + 21 处测试使用），`resolution_` 恒为 nullptr
→ 与 `sim_bridge.cc` 同一回事，**要等 slice 2b 的 `ResolveDDSlots` 调它才算落地**。

**裁决记录（陈旧条目）**：`SetSlotOwner` overwrite 后 `owner_to_slot_[旧owner]` 留陈旧条目。
四条证据证明他们那边 `owner_to_slot_` 是**只写**的（无导出 accessor；唯一内容读是 `+0x18`
即 `slot_to_owner_.size()` 而非 `+0x28`；三个算法阶段都读别处；另一处 `+0x28` 访问是析构）
→ **忠实复刻，不擦除**。与 `load_obfuscation_map` 刻意不复刻其 bug 的区别在于：
那个**可测量地破坏输出**（重发已占用改名，8 vs 0），这个不可达、不可能影响输出。
`SlotForOwner()` 是我们发明的、他们没有，已标为 test-only 非复刻面。

**slice 2b 验收基线**（他们的二进制，同一份 voters.bin）：
```
Pass 1: 7 resolved, 0 preserved, 0 carried, 1 dropped (tgt_miss=1) from 2878 functions
Pass 2: 0 resolved, 7 preserved (0 would-have-flipped), 7 carried, 1 dropped from 2983
DD table: 8 slots, 7 retained, 2 rewritten, 1 unrewritten-null filled with sentinel
```
**slice 2b 的阻塞依赖**：DD IL 子系统（`FinalizeIndirectStaticCallTable` /
`ReplaceStaticCallsWithIndirectCalls` / `IndirectStaticCall`，他们最大的私有发明约 100 符号）
必须先存在，否则没有真实 slot 可决议。

### ⚠️ 符号计数在 stripped vs unstripped 之间不可比

我们未 strip 的 Product 构建带 **STABS debug-map 重复项**，他们 stripped 的二进制没有。
所以 `linker.cc` 的 22（我们）vs 20（他们）**不能当成数值对比**。
**只有「两边都非零 / 一边为零」和去重后的方法列表有意义。**
（此前完成度表里「他们 44 我们 0」那类仍然有效——0 vs 非0 是真信号；
两边都非零时比数值则不可靠。）
另：`std::__2` vs `std::__fl` 是 libc++ ABI 命名空间版本差异，不是分歧。

### 📏 完成度实测基线（2026-08-19，可复跑）

**别再凭感觉估。** 方法：两边 `nm -a | c++filt`（他们的先 `lipo -thin arm64`），
按私有子系统的标志符号分组计数。我们的产物里为 0 就是真没实现。

| 子系统 | 他们 | 我们 | |
|---|---:|---:|---|
| `link_info.cc` | 204 | 103 | **部分**（class/field/dispatch） |
| `wrapper.cc`（WrapperAllocator/Layout/CPU↔Sim） | 260 | 0 | 缺 |
| DD core（IL 指令/变换/建表） | 128 | 0 | 缺 |
| `dd_voting.cc` | 58 | 0 | 缺 |
| `linker.cc`（ShorebirdLinker） | 20 | 0 | 缺 |
| sim bridge | 10 | 0 | 缺（见上：编译了但被 dead-strip） |
| `object_pool_mapper`/`class_table_mapper`/`field_hasher` | 4/2/2 | 0 | 缺 |

**私有子系统 1/12（且那 1 个只是部分）；11 个 flag 完成 8 个（2026-08-19 更新）。**
→ **实现总体约 15%**，逆向/oracle 约 60–70%（估计值，无客观权重依据）。

⚠️ **子系统数才是主导项，而它没动**：flag 工作与 dispatch offset 修复全部落在
`link_info.cc` 和既有的 `dispatch_table_generator.cc` 里，剩下 11 个子系统一个没碰，
**单是 `wrapper.cc`（260 符号）就比至今复刻的全部加起来还大**。

⚠️ **上表口径有偏**：我们是 `--mode=release`、他们是 `--mode=product`（已实测确认，见下）。
**重建成 product 之后再读这些差值**，否则分不清「缺代码」与「被 mode 编译掉」。

### ✅ `print_dispatch_table_debug_info_to`：**他们自己也没实现**（2026-08-19）

此前记「silent on a base build」，暗示存在没找到的触发条件。**没有**——
它在任何构建下都静默，包括完整的 patch relink。
`FLAG_print_dispatch_table_debug_info_to`(0x100526798) 在他们 arm64 `gen_snapshot` 里
**零代码引用**，两种独立方法确认：
① `spikes/shorebird_linkinfo_oracle/scripts/xref.py`——按函数跟踪 `adrp` 目标寄存器并在
重定义时失效（否则 `ldr x8,[x8,#off]` 会把过期页泄漏进下一个函数，实测会造成假阳性）；
② 高召回扫描：命中页 `0x100526000` 的全部 **720** 个 `adrp` 点，往后 40 条指令内找
`0x798` 立即数——唯一命中是 `Thread::InitVMConstants` 里 `str x8,[x19,#0x798]`，
经 `x19` 访问的无关 `Thread` 字段。
阳性对照：同一工具查出 `print_dispatch_table_link_info_to` 在
`Precompiler::DoCompileAll` 被读一次 → 工具有效，「无引用」为真。

→ **复刻方式就是声明它而不读它**，`--help` 因此一致。「11 个 flag」实为
**10 个可实现 + 1 个死 flag**。

**顺带产出**：`xref.py` 是可复用的 arm64 全局交叉引用工具；用它定位到
`print_dd_function_identity_to` 的读取点在 **`Serializer::PrepareInstructions`**，
即 DD identity dump 的产出位置（对任务「DD 子系统」直接有用）。

### ✅ flag 描述串已对齐；flag 面已量化

我们原来 6 个 link-info flag 的描述是**意译**，`--help` 与他们不同。已换成他们的原文。
现在我们声明的 8 个 flag 的 `--help --verbose` 行**全部逐字节相同**。

`--help --verbose` 只取 flag 名：**他们 263、我们 300**。
- **他们有我们没有：恰好 3 个**——`print_dd_function_identity_to`、
  `print_dd_resolution_to`、`print_shorebird_info`（正是已知被 DD/linker 阻塞的三个）。
- **我们有他们没有：40 个**——`profiler`、`coverage`、`verify_after_gc`、`trace_*`、
  `reload_*`、`deoptimize_*`、`use_osr`、`interpreter`…
  **全部是 stock 里 `!defined(PRODUCT)` 门控的 flag** → **他们是 `--mode=product`，
  我们是 `--mode=release`**（此前只是「定性推测」，现在有精确名单）。

⚠️ **上一轮我报的 15–20% 偏高**，原因是把「已移植的 simulator 工作」计入了进度，
实测显示它没进产物。教训与 [[feedback-verify-by-running]] 同源：进度也要实测，不能靠记账。

口径说明：此表只量 `gen_snapshot`。`subgraph_hasher`/`cascade_limiter` 在 `analyze_snapshot` 侧，
表里的 0 是口径问题不是缺失；`vmcode loader` 我们 4、他们 0，因为那是引擎运行时侧。
另：`dart::Simulator::` 我们 117、他们 58（我们更多，未深究）。

### 🚧 「100% 完成度」的现实边界（2026-08-19 修订：三类变两类）

1. **快照版本 hash**——**不是**「VM 布局决定、自动收敛」，而是 15 个上游源文件的 MD5
   校验和（见上）。要靠**逐字节重建那 15 个文件**，dSYM 行表可定位改动位置。
2. **堆遍历顺序**（field_table 同 id 内）——由堆布局/分配历史决定，仍是度量。
3. ~~**dispatch table offset 分配**~~ → **已复刻，byte-identical**（见下）。
   它原来被归成「要求两个 VM 完全一致」，**实测是个普通算法改动**，
   教训：先验证「不可单独攻克」这个判断本身，别直接接受。

### 🐞 顺带修掉一个长期存在的构建缺陷（3.7 就错了）

`sim_bridge.cc`、`sim_bridge_arm64.S`、`sim_transition.{cc,h}` 在 3.7 分支上
**一直注册在 `vm_sources_tests` 而不是 `vm_sources`**
→ **A2/C1 的 SimBridge 只被编进 `run_vm_tests`，从未进入 `gen_snapshot` 等任何生产产物。**
这解释了两件事：① 之前在链接后的 gen_snapshot 里查不到
`InvokeWithTHR`/`CallHostFunction`/`ShorebirdSimToCpu`，我一度误判为「static 被内联」，
**实际是根本没编译**；② memory 里「A2/A5+C1-C7 已落地但真机未验」——
生产产物里本来就没有这些代码。已修正，现在 ninja 确实编译
`libdart_vm_precompiler.sim_bridge.o` 等。

#### ⚠️ 2026-08-19 复测：修了编译，**没修落地**

三个 `.o` 确实生成（`sim_bridge.o` / `sim_transition.o` / `sim_bridge_arm64.o`），
但 `nm gen_snapshot | grep -icE "InvokeWithTHR|CallHostFunction|SimToCpu|sim_bridge"` = **0**。
构建带 `-ffunction-sections` + dead-strip，**没有任何调用点引用它们，整体被剥离**。
→ 状态从「没编译」变成「编译了但被剥掉」，**C1–C7 仍然没进任何生产产物**。
真正落地要先接上调用点，不是改 BUILD.gn 就完事。
对照：他们 gen_snapshot 里 `ShorebirdEnterCFrame`/`CallSimulatorFromFfiTrampolineStub` 等 10 个符号都在。

### 两个被证伪的旧猜测

- 「`isnan`→`__builtin_*` 那 13 个文件可能整批作废」——**假的**：
  3.12.2 上游**仍然是裸 `isnan`/`isinf`**（`double.cc` 3 处、`constants_arm.cc` 6 处等），
  改动不作废。但它是纯机械替换，**脚本重做比解冲突安全**
  （`simulator_riscv.cc` 上游 +526/-149，硬 rebase 会很痛）。
- 「替换处数比 3.7 版多，可能过度匹配」——**假的**：是我两次用了不同口径
  （`grep -c` 数行 vs `re.subn` 数次数，一行可含两处）。同口径下 6 个可疑文件**全部一致**。
  教训：跨两次测量务必统一口径再判断差异。

## Ghidra 已跑通（本机可用）

`/opt/homebrew/Cellar/ghidra/12.1.2/libexec/support/analyzeHeadless`，
**必须 `JAVA_HOME=/opt/homebrew/opt/openjdk@21`**（默认 Java 11 跑不起 Ghidra 12），
且**必须先 `lipo -thin arm64`**，否则它去分析 universal binary 的 x86_64 那一半。
脚本 `spikes/shorebird_linkinfo_oracle/scripts/DecompShorebird.java` 批量反编译私有符号。

analyze_snapshot 已反编译出 17 个函数，其中：
`Dart_ComputeDDTable(char**,long*,char**,long*,long long,char const*,long)`（**7 参数**，两对 ptr/len 输出，8120 字节代码）、
`Dart_ComputeDDSlotMapping`（1943 行伪代码）、
**`dart::CascadeLimiterEntry`——之前不知道存在的类型**，ComputeDDTable 会对它的数组排序。
`SubgraphHasher` 构造函数存了多个**命名 hash 分量**：`0x6870617267627573`="subgraph"、
"object_pool"、"loop"、"self"（SSO 串，长度 8/11/4/4）→ **subgraph hash 是分量组合**，
需核对 `GROUND_TRUTH.md` 复刻的版本是否漏了这些分量。

**踩过的坑**：标量 `num_cids`/`max_field_id` 写在**末尾**不是头部。
「读到 EOF 为止」会**假通过**——越界刚好停在最后一字节，报告 consumed 完全相等。
所以 parser 必须由 count 驱动，并与 JSON 对照。这个假阳性是 JSON 对照抓出来的。

**完整管道契约**（`strings` 挖出的隐藏选项；analyze_snapshot 的在 `--help` 里自带文档）：
生产端 `analyze_snapshot --compute_dd_slot_mapping/--compute_dd_table/--dd_function_identity/
--dd_caller_links/--dd_table_data/--dump_object_pool_link_data/--no_pp_hash/--dump_blobs`；
消费端 `gen_snapshot --base_ct_link_data/--patch_ct_link_data/--base_op_link_data/
--patch_op_link_data/--base_ft_link_data/--base_dt_link_data/--dd_slot_mapping`。
错误串 `--base_ct_link_data must be used with --patch_ct_link_data`（op 同）
→ **ct/op 收 base+patch 一对，ft/dt 只收 base**，与符号表的两参数/一参数推断**独立互证**。

**他们的私有源码目录**（断言路径泄露）：`runtime/vm/shorebird/{linker,link_info,class_table_mapper,
object_pool_editor,object_pool_mapper,wrapper}.cc`。

## 版本差：不再是阻断（2026-08-19 修订）

| | Dart 版本 | 平台串 |
|---|---|---|
| Shorebird `gen_snapshot_arm64` | 3.12.2 stable（2026-06-11） | `macos_simarm64` |
| **fvm 3.44.6 自带 stock dart-sdk** | **3.12.2 stable（2026-06-09）** | `macos_arm64` |
| 我们（基线 `37bbc285d8d`） | 3.7.0-260.0.dev（2024-12） | `macos_simarm64` |

**本机已有与他们仅差两天的 stock 3.12.2** → stock vs Shorebird 干净差分**现在就能做，无需 rebase**，
同时确认 `d684a576a6a`(3.12.2) 是正确 rebase 目标。
`simarm64` 只有他们有，上游全是 `arm64` —— A1 的 `USING_SIMULATOR` 方向被独立证实。
旧结论「拿他们 AOT 喂我们 analyze_snapshot 被 `Wrong full snapshot version` 挡住」仍成立，
但**已绕过**：不需要加载他们的快照，让他们的二进制自述即可。

## ⏭ 下一步（2026-08-19 重排；前两项已完成故移除）

「继续做 dump flag」这条路**已经走到尽头**——剩下 3 个 flag 全被 DD/linker 阻塞。
所以下一步不再是 flag，而是子系统本体：

1. ✅ **已完成：`--mode=product` 重建**。
   `python3 ./tools/gn.py --mode=product --arch=arm64 --no-rbe --no-verify-sdk-hash --gn-args 'dart_force_simulator=true'`
   → `ninja -C xcodebuild/ProductARM64 gen_snapshot`。
   **结果精确**：我们多出的 40 个 flag **归零**，`260 + 3 = 263`
   → **flag 面现在是他们的精确子集**，只差被 DD/linker 阻塞的那 3 个。
   dispatch table 在 product 构建下仍与他们**逐字节相同**。
   **product 下重测符号数，各处的 0 都是真的**（不是 mode 造成的）：
   `WrapperAllocator|CPUToSim|SimToCPU` 他们 44 我们 0；
   `DDTable|IndirectStaticCall|DDSlot` 100 vs 2；`DDSlot{Voters,Resolution}` 12 vs 0；
   `ShorebirdLinker` 20 vs 0；sim bridge 20 vs 0；各 Mapper 2 vs 0。
   （`link_info|LinkInfo` 他们 40 我们 63——我们更多，是我们的辅助符号命名不同，不是缺失。）
2. ✅ **`wrapper.cc` 第一份 plan 已完成（2026-08-20，8 条提交，12 个单测全 exit 0）**
   plan：`docs/superpowers/plans/2026-08-20-shorebird-wrapper-allocator.md`。
   已对上他们 DWARF 的：`Layout` 0x60 + 九个字段偏移；推导计数 2014 与
   floor(2044.5)=2044；`WrapperAllocator` 0x98（用 `static_assert` 而非单测强制，
   因为 `layout_` 是私有成员，`offsetof` 编译不过）。

   ⚠️ **但「对上 DWARF」只是尺寸对上，字段类型与 API 形状都不同**（final review 发现）。
   `static_assert` 只查 `sizeof`，**同宽替换全部畅通无阻**：
   `get_stub_code_range` 他们是 `std::function<void(uword&,uword&)>` 我们是
   `std::function<CodeRange()>`（都 32B）；`stub_page_` 他们 `VirtualMemory*` 我们 `uword`（都 8B）；
   `wrapper_pages_` 他们 `MallocGrowableArray<VirtualMemory*>` 我们 `<uword>`。
   **他们根本没有 `WrapEntryPoint`**，等价物是 `AllocateMetadata()`（无参、返回 `void*`）
   → 他们的 code range 是**一次性存进 `stub_page_`**，不是每次调用传入。
   还缺 `Layout::CodeSize/MappingSize/MappingAlignment` 三个方法。

   🐞 **真 bug：我们泄漏每一个 wrapper page** —— `wrapper_pages_` 存裸 `uword`、
   `~WrapperAllocator` 空实现，从不 unmap。他们的 `VirtualMemory*` 带所有权，析构能释放。
   **plan #2 接调用点之前必须先修**，否则每次 wrap 都漏。

   **教训**：尺寸匹配是弱证据，只约束布局。**DWARF 给了类型的地方就要查类型。**
   COW 只有行为级验证，**无字节级 oracle**（已知边界，不粉饰）。
   **符号数仍是 0/44** —— `wrapper.o` 有 15 个 T 符号、`gen_snapshot` 有 0 个，
   即「编译了但被 dead-strip」，与 `sim_bridge.cc` 同一回事。要非零得等 plan #2 接调用点。

   **三个 plan 缺陷是执行中实测发现的（我写的 plan 有错）**：
   ① COW 测试**测不出 COW**——`copy=FALSE`（共享映射）能通过。因为 metadata 写在
   offset 32768、落在 remap 跨度 `[0,32768)` 之外，且 `EXPECT_EQ(0,src[0])` 恒真。
   已改成「写穿 remap 再验源未变」，A/B/C 三控制实验确认修好。
   ② Task 4 的 `current_page_` 字段与 `static_assert(0x98)` **直接冲突**（加了变 0xA0）。
   他们五个成员总和恰好 0x98，**没有当前页槽位** → 他们必然从 `wrapper_pages_.Last()`
   推导。这是从尺寸约束反推出的设计信息，不只是变通。
   ③ Step 1 的测试要 Mach 头但 plan 只给 `wrapper.cc` 加。

3. ✅ **`wrapper.cc` plan #2 的 Sim→CPU 半边已完成**（2026-08-20，6b-i/ii/iii，
   4 条提交，76/76）：`Thread::is_simulating_` + `brk 0xb128..0xb130` hypercall 分派 +
   28 字节 body（**6/7 字与他们逐字节相同**）。详见 [[reference-wrapper-stub-bodies]]。
   ⚠️ **`wrapper_symbols_check.sh` 仍是 0** —— 发 body 不产生 `WrapperAllocator` 的调用者，
   所以 `wrapper.cc` 依旧被 dead-strip，C1–C7 **仍未进产物**。
   剩 CPU→Sim 那半边（272 字节，要 `compiler::RunOnSimulator`）= Phase D。
3. **`wrapper.cc` plan #2 余下部分：CPU→Sim body + 落地 C1–C7**。DWARF 已给全部布局参数；
   **它同时就是 C1–C7 缺的那个调用点**（现在编译了但被 dead-strip，仍不在任何生产产物里），
   也是真机 A/B 验 C6 的前置。注意 `WrapEntryPoint` 只往元数据写 8 字节目标，
   landing pad / shared body 由构建期 `StubCodeCompiler` 生成 → **要写 stub 生成器，不是字节模板**。
3. **DD 子系统**（新 IL 指令 + IL 变换 + 建表 + slot 决议，128+58 符号）。
   oracle 先于实现就位（`write_dd_slot_voters.py` 已能驱动他们的决议器）。
4. **三阶段映射**（link results → pair constraints → backfill），解锁 `print_shorebird_info`。
   ⚠️ 实测新发现：**只要给了 base+patch link data，那份分阶段报告就会打印，
   不需要传 `--print_shorebird_info`。**
5. 查 `SubgraphHasher(..., DDTableLinkInfo*)`：我们的 subgraph hash 可能少了 DD 表这个输入。
6. 把 dSYM 行表差分铺到全部 15 个 hash 输入文件——通往快照 hash 的唯一路径。
7. ~~补宿主逃逸覆盖面（BR / ADRP）~~ **已出局**（规则 2，上游 `SIMULATOR_FFI` 覆盖，
   实测 7/7 PASS，见下文「FFI 缺口已关闭」）；真机 A/B 验证 C6 **仍未做**。

详见 `docs/DARTSDK_REPRODUCTION.md`（route-a-research 分支）与
`spikes/shorebird_linkinfo_oracle/README.md`。

## `~/dart/sdk` fork 现状

规则 3 下的自研 VM fork。分支 `flutter-hot-patcher`，**20 条**自研提交
（CLAUDE.md 原写「8 条」已订正），从上游 `37bbc285d8d` 起算：
A2/A5/A7 → B2/B4 → C1–C7 → 2026-08-19 归档的 5 条。

**没有可推的 remote**：`~/dart/sdk` origin 是上游 googlesource（推不上去），
`flutter_hot_patcher` origin 是**公开** GitHub，自研 VM 改动不往那推。
走离线备份 `archive/dartsdk_backup/fhp-dartsdk-20260819.bundle`
（增量，仅 `37bbc285d8d..flutter-hot-patcher`，20 提交/103KB，`bundle verify` 通过）。
**还原依赖上游基点 `37bbc285d8d` 先在仓库里**（bundle 不自足）。
备份与源码同机，挡不住整机故障。`archive/` 已进 `.gitignore`（仓库 origin 公开）。

## 跑 run_vm_tests 的坑（踩过，别再踩）

- 不带参数只打印用法并 exit 1，**它不会跑全量**；全量得 `--list` 后逐条调
- 逐条跑**必须传 `--dfe=<kernel service snapshot>`**，否则需运行时编译 Dart 的用例全挂
  （2026-08-19 实测 443/1935 失败全因此，不是回归）
- `xcodebuild/ReleaseARM64/` 里**没有** `kernel-service.dart.snapshot`，跑全量得先构建
- `.ninja_log` 与产物失配（`command line not found in log`），`ninja -n` 说几千步待跑，
  但产物时间戳其实新于全部源码。别据此判断树是脏的

## ✅ FFI 缺口已关闭（2026-08-20 实测，在 3.12.2 分支上）

**结论：上游 `SIMULATOR_FFI` 解决了它，我们那套宿主逃逸作废（规则 2）。**
7/7 全 PASS：`Dart_SetFfiNativeResolver{,_MissingResolver,_DoesNotResolve}`、
`DartAPI_{,Implicit,Negative}NativeFieldAccess`、`DartAPI_NativeFieldAccess_Throws`。
再没有 `word=0xf00118c0`（ADRP）那类报错。

🔴 **其中 FFI 那一支在 3.12.2 上根本没编译**（不是 dead-strip，是预处理就没进）：
`simulator_arm64.cc:1804`（`AddressInImage`/`IsHostCodeAddress`/`CallHostFunction`/
`HostCallResult`）与其唯一调用点 `:2427` 守在 `#if defined(SIMULATOR_HOST_ARCH_MATCH)`，
而这个宏在整棵树里**从未被定义**（只剩 `globals.h:442` 一句注释提它）。
→ 「宿主逃逸在树里、只挂 BLR 不挂 BR」这条旧记录**对这棵树是错的**：
FFI 那一支一行都没运行过，7 条测试能过全靠上游。**约 100 行死代码待处理（未删，已上报）。**

⚠️ **必须区分开的另一支**：`InvokeWithTHR`(1760) 守在 `#if defined(__aarch64__)`(1754)，
**是编译的、活的**，被 A5 的 BL 拦截(2312) 与 BLR 拦截(2408) 调用——那是 A2/A5 的
link-table 逃逸，与 FFI 逃逸并存于同一函数但**两回事**。别一起删。

🔧 **测「某个 `#if` 块有没有被编译」的正确工具是 `#error` + 阳性对照，不是数符号。**
我先用 `nm` 数了 `CallHostFunction|InvokeWithTHR|IsHostCodeAddress` 得 0，
据此把 `InvokeWithTHR` 也判成没编译——**错的**：它是 `static` 且被内联，
所以「编译了」和「没编译」在符号表里长得一样。
改用在块内插 `#error` 重测：`SIMULATOR_HOST_ARCH_MATCH` 块 → 构建照过（未编译，真）；
阳性对照往 `__aarch64__` 块插同样的 `#error` → `ninja: build stopped`（工具有效）。
与 [[project-wrapper-upstream-ancestor]] 记的三次翻车同型：**度量工具本身要先验证。**

⚠️ 对照：`sim_bridge.cc` 情况**不同**，它守在 `SIMULATOR_AVAILABLE` 上而该宏是定义的，
`.o` 里 50 个符号，**确实编译了**，只是链接期被 dead-strip（缺调用点）。两者别混。

⚠️ **`--dfe` 的正确参数已找到**（此前记「ReleaseARM64 里没有 kernel-service，跑全量得先构建」）：
`--dfe=xcodebuild/ReleaseARM64/gen/kernel_service.dill` **已存在且可用**。
不传它这 7 条会以 `Compilation failed Error while starting Kernel isolate task` 假失败，
**看起来像 FFI 回归，其实是缺 dfe**——我这次先踩了一遍。
另：`run_vm_tests --list` 每行末尾的 `Pass` 是**期望值不是结果**，别读成通过。

## A2 逃逸的现状（C6/C7）

已修，`ShorebirdSimToCpu_BasicCall` 等四条 PASS。修法是**删掉 `HasScheduledInterrupts()` guard**，
不是修控制流。**但支撑它的安全性论证未经实测**，且 C6 commit message 里
「回落会解释 C++ 所以挂死」只对单测成立（该测试 link 目标是 C++ 函数 `ShorebirdTestNativeDoubler`），
生产中目标是 base snapshot 的 Dart AOT 代码。结论待真机 A/B 证伪。

注意 `DecodeUnconditionalBranchReg` 的 BLR 分支里**并存两套逃逸**：
A2 的 link-table 逃逸，和 FFI 的「目标不在任何 Dart 指令段」逃逸（见 [[project-x1-research-branch]]）。

相关：[[feedback-verify-by-running]]、[[feedback-rtk-diff-unreliable]]

## 📊 重测（2026-08-24，19 轮之后）：只有一行动了

19 轮里我一直在递增计数器而**没重跑测量**。规则要求实测，递增记账不算。重测结果：

| 标志符号 | 他们 | 我们 | 变化 |
|---|---:|---:|---|
| shorebird stub 生成器 | 144 | **32** | 4 → 32（唯一移动的一行） |
| `ShorebirdLinker::` | 20 | 20 | 持平未变 |
| **DD core** | **68** | **0** | **未变，仍是最大缺口** |
| mappers / field_hasher | 2 | 0 | 未变 |
| 唯一符号总数 | 32373 | 33774 | 33714 → 33774 |

**实现估计 15–18% → 22–28%**，唯一原因是 stub 子系统 1/16 → 16/16。
⚠️ 别读成「进展加速」：DD core 与三阶段映射一行未动。
⚠️ **32 vs 144 不能读作「完成 22%」**——多个 stub 共用生成器、我们的构建未 strip。
**stub 的真判据是输出逐字对比（`compare_stubs.py`），不是符号数。** 这是同一个口径陷阱的第四个实例。

## 🔴 DD core 审计（2026-08-24）：**旧描述四项里错了三项**

「DD core = IL 指令 + IL 变换 + 建表 + slot 决议，上游零基础，68 vs 0，最大缺口」——审计结果：

1. **没有 `DDTable` 类。** 正则 `DDTable|IndirectStaticCall` 命中 68 行；拆开看，
   `IndirectStaticCall` 命中全部 68，`DDTable` 命中其中 8 行，**全部**是
   `Precompiler::FinalizeIndirectStaticCallTable()::DDTableBuilder`——**函数内局部类**。
   那 68 行是**一个 IL 指令类的 19 个方法**被 nm 反复列出。
   对比：同一二进制里上游 `StaticCallInstr` 是 **142 行 / 26 方法**。
2. **slot 决议已经是我们的**：`DDSlotVoters`/`DDSlotResolution`/`DDSlotMapping`
   是他们唯一的三个 DD 前缀类，我们三个都实现了。
3. **上游基础不是零**：那 19 个方法就是 Dart IL 调用指令的标准契约，
   `StaticCallInstr`（`il.h:5562`）就是模板。
   （`IndirectEntryInstr` 会被同一个 grep 捞到，但它是**上游**的 indirect-goto entry，无关。）

**真实剩余面 = 两项 + 一件不可见的**
- `IndirectStaticCallInstr`：19 方法（`nm` 给了方法名，形状照上游 `StaticCallInstr`）
- `Precompiler::FinalizeIndirectStaticCallTable()`：**唯一**一个他们有我们没有的 Precompiler 方法，
  内含局部 `DDTableBuilder`，有 `VisitCode(const Code&)`
- 把 static call 改写成 indirect 的那个 IL pass：**完全内联、零符号**，真的看不见

**oracle 两个都现成**：`analyze_snapshot --compute_dd_table` 格式已逐字节解出；
`--print_dd_resolution_to` 的 `rewritten` 列（他们 2 / 我们 0）是变换的计数级判据。

⚠️ **这是同一个口径陷阱的第五次**（前四次：`wrapper.cc` 的 34、`sim bridge` 与
`subgraph_hasher` 两行都是 0 但原因不同、static 内联）。
**规则：相信一个符号计数之前，先拆正则、再列出去重后的方法名。**
不改变 DD core 未做的事实，但**改变它的成本估计**——而这个项目已经因为「错误的度量长出错误的战略」栽过一次。

### `IndirectStaticCallInstr` 字段表已还原（从它自己的 IL 序列化器）

`gen_snapshot` 没有 dSYM，类声明读不到。但 **Dart 的 IL 序列化器每个字段一个带类型的调用**，
所以 `WriteTo(FlowGraphSerializer*)`（316 字节）就是一份机器可读的字段表。反汇编得：

```
TemplateDartCall<0>::WriteTo(s)          // 与 StaticCallInstr 同基类
WriteTrait<const Function&>::Write(s, this[0xc0])
<LEB128 this[0xc8]>                      // int64，varint
this[0xd0] ? (0xc1; CompileType::Write) : 0xc0   // 可空 CompileType*
<LEB128 this[0xd8]>                      // int32（`ldr w` 不是 `ldr x`）
```

**不是上游的克隆**：上游 `StaticCallInstr` 的 `FIELD_LIST` 有 8 项，他们只序列化 4 项。
缺的正好是 precompiler-only 指令用不上的（AOT 无 IC data、无 rebind rule、无 list 构造标记、无 alias identity）。

**已确立**：基类、字段数、每个字段的类型与偏移。
**未确立**：两个数值字段的**含义**（int64 可能是 `call_count_` 也可能是 DD slot 索引；int32 可能是 `entry_kind_` 也可能是标志位）。
序列化器证明的是**形状，不是语义**，凭猜命名就是规则 3 禁止的自由发挥。

⚠️ **没有普通构造函数符号**，只有反序列化那个 → 真正的构造函数在其创建点被内联，
而创建点就是那个**零符号的 IL pass**。

**可复用技术**：在 strip 过的二进制里，任何 IL 指令的 `WriteTo` 都是它的字段清单。

**下一步取证**：`EmitNativeCode`（1000 字节，call 怎么发）、
`FinalizeIndirectStaticCallTable()::DDTableBuilder::VisitCode`（1328 字节，表怎么建）。

### 🔑 DD 的实际机制已确立（从 `EmitNativeCode`，1000 字节）

发射序列：`ArgumentsDescriptor::New` → `ICData::NewForStaticCall` →
`LoadObjectHelper(R4=ARGS_DESC_REG, args_desc)` →
`LoadFromOffset(TMP, THR, **0x978**, kEightBytes)` → `<int64 字段> * 8`（`lsl x3, x24, #3`）→
`AddImmediate` → **发一条裸指令**（就是那个 call）→ `EmitCallsiteMetadata` →
`AddStaticCallTarget(function_, **硬编码 0**)`。

**`Thread+0x978` = `indirect_static_call_table_`**（引擎 dSYM 按名字确认）。

→ **`@0xc8` 就是 `Thread::indirect_static_call_table_` 的索引**，即 DD slot。
→ `@0xc0` 的 `Function` 仍然交给 `AddStaticCallTarget`，所以**原始静态目标依旧记在快照的
static-call 表里**，而调用本身走间接。**这就是它可打补丁的原理**：表项可以改指向，
而记录下来的目标仍然说明这个调用原本是什么意思。

| 偏移 | 类型 | 含义 | 证据 |
|---|---|---|---|
| 0xc0 | `const Function&` | 原始静态目标 | 序列化器类型 + 传给 `AddStaticCallTarget` |
| 0xc8 | `int64` | **表索引（DD slot）** | `lsl #3` 后用于表基址；`PrintOperandsTo` 的格式串 `[dd_slot=%ld]` —— **他们自己命名的** |
| 0xd0 | `CompileType*` 可空 | result type | 序列化器调 `CompileType::Write` |
| 0xd8 | `int32` | **未确立** | 三个 oracle 都沉默（序列化器只给形状；`PrintOperandsTo` 不读它；`AttributesSerializer` 只读 0xc0） |

⚠️ **两轮前我刻意没给这两个数值字段命名。现在看：`0xc8` 猜对了，`0xd8`（猜 `entry_kind_`）猜错了。**
如果当时两个都命名，记录里会同时出现一条真的和一条假的、置信度相同，
而下游**永远不会有任何东西反驳那条假的**。这是"证据只支持形状时不要给语义"的实证。

**还缺**：`DDTableBuilder::VisitCode`（1328 字节，表怎么填）、创建这些指令的 IL pass（内联、零符号）。

### 🔑 IL printer 是命名 oracle（2026-08-24）

格式串 `0x1004cbd3e` 处读到 ` %s<%ld> [dd_slot=%ld]`，位于
`IndirectStaticCallInstr::PrintOperandsTo` @ `0x1002faeb4`。

- **`0xc8` = `dd_slot`** —— 他们自己在 printer 里这样命名，与 `EmitNativeCode` 的推断（`lsl #3` 后用作表索引）完全一致。两条独立证据指向同一个名字。
- **`0xa0` = `type_args_len()`** —— 是 `TemplateDartCall` 基类字段，`<%ld>` 插槽与上游 `StaticCallInstr::PrintOperandsTo` 的格式 ` %s<%" Pd ">` 精确对应。
- **`0xd8` 仍不命名** —— `PrintOperandsTo` 不读它，`AttributesSerializer::VisitIndirectStaticCall` 只读 `0xc0`（Function 名），序列化器仅给形状。三个 oracle 全都沉默，是比单次沉默更强的否定结果。
- **可复用规则**：`WriteTo` 给**形状**，`PrintOperandsTo` 给**名字**，两个配对使用才完整。

### `DDTableBuilder::VisitCode` 序幕已解（2026-08-24）

`dart::Precompiler::FinalizeIndirectStaticCallTable()::DDTableBuilder::VisitCode(dart::Code const&)` @ `0x10022faf4`，1328 字节。

全函数 BL 扫描：外部调用只有 `std::__fl::__next_prime(unsigned long)`（×2）、`__throw_bad_alloc`、`__throw_bad_array_new_length`，其余 84 个分支都是内部标签。因此函数体完全内联，两次 `__next_prime` 调用确认它在建 libc++ `std::unordered_map`——与 `print_dd_function_identity_to` 顺序那条的分析同源（同一个容器、同一套桶宽序列）。

已解序幕（C++ 伪码）：

```cpp
void VisitCode(const Code& code) {
  ObjectPtr owner = code.ptr()->untag()->owner_;      // ldur x8, [x8, #0x37]
  if (owner->GetClassId() == kWeakSerializationReferenceCid)  // cid 16
    owner = WSR::Unwrap(owner);                       // ldur x8, [x8, #0x7]
  if (owner->GetClassId() != kFunctionCid) return;    // cid 7
  ...                                                 // 后面：null 检查，再哈希查找
}
```

两个 class id 常量已对我们同版本 `runtime/vm/class_id.h` 核实：`7 = kFunctionCid`，`16 = kWeakSerializationReferenceCid`，语义完全吻合（函数闸门 + WSR 解包），是互证而非单一读数。

闸门之后：owner Function 存入 `this[0x8]` 的成员 handle，与全局 `0x100518880` 比较（null 检查），再对 `this[0x10]` 的 `unordered_map` 做查找，键是**从 untagged Function `+0x6c` 加载的一个 uint32**（`ldur w9, [x9, #0x6b]`）。

`+0x6c` 处的字段已确立：是 **`UntaggedFunction::kernel_offset_`**（`uint32`）。
通过从我们自己的同版本构建导出 DWARF 解决：

```
xcrun dwarfdump --name=UntaggedFunction --show-children \
  xcodebuild/ReleaseARM64/obj/runtime/vm/libdart_vm_precompiler.raw_object.o
```

布局（untagged 偏移）：`0x08 entry_point_`、`0x10 unchecked_entry_point_`、`0x18 name_`、`0x20 owner_`、`0x28 signature_`、`0x30 data_`、`0x38 ic_data_array_or_bytecode_`、`0x40 code_`、`0x48 positional_parameter_names_`、`0x50 unoptimized_code_`、`0x58 unboxed_parameters_info_`、`0x60 token_pos_`、`0x64 end_token_pos_`、`0x68 kind_tag_`、**`0x6c kernel_offset_`**、`0x70 usage_counter_`。

因此 `DDTableBuilder` 的 `unordered_map` 以每个 Function 的 `kernel_offset_` 为键——它在同一源码的多次重编译间稳定，地址则不然，这正是 base↔patch 身份映射所需要的键。

剩余：`VisitCode` 余下的 map insert / table fill 逻辑，以及创建 `IndirectStaticCallInstr` 节点的 IL pass（完全内联、零符号）。

### 🔑 我们自己的 DWARF 是上游类型的布局 oracle（2026-08-24）

**可复用技术**：我们自己的未 strip 构建的 DWARF，是他们被 strip 的 `gen_snapshot` 里**所有上游 Dart 类型**的布局 oracle。同版本（3.12.2）、同架构（arm64）、同 `dart_use_compressed_pointers = false`，上游结构体布局完全相同。`xcodebuild/ReleaseARM64/obj/` 下的 `.o` 文件通过 macOS debug map 携带完整 DWARF，可用 `xcrun dwarfdump --name=<类型名> --show-children` 直接查询。

这条纠正了一个既有假设：「因为他们的 `gen_snapshot` 没有 dSYM，所以类型布局不可得。」这只对 **Shorebird 私有类型**（如 `IndirectStaticCallInstr`、`DDSlotVoters`）成立。所有上游类型都可从我们自己的 DWARF 读出。

⚠️ **例外**：对 Shorebird 改动过的类型不适用。已知被改的是 `Thread`——他们的 Shorebird 字段块在结构中部（~0x8d8），我们的追加在末尾（0xf18）。对 `Thread`，我们的 DWARF 给的是**我们的**偏移，不是他们的。

## 完成度（2026-08-24 现状）：实现 22–28%、逆向 75–80%

实测于「重跑 nm 双边对比」那轮；此后几轮全是 DD core 取证，**实现未动**。

**已核验的硬事实**：11 个 flag 完成 10（4 个逐字节相同）；**16/16 私有 stub 有真 body**
（全部逐字对比，`compare_stubs.py` 守）；`ShorebirdLinker::` 符号 20 vs 20 持平；
`LinkOracle` 已实现；`verify_reproduction.sh` 24 产物 + 14 stub 全过；92 条单测全过。

**仍为 0**：DD core（机制已查清但一行未写）、三阶段映射（`print_shorebird_info` 唯一仍阻塞的 flag）、
`AllocateMetadata()` 的生产调用点（C1-C7 因此进不了任何产物）。

### 读这个百分比的三条限定
1. **没有客观权重依据** —— 数量级指示，不是刻度。
2. **一部分结构上到不了 100%**：Thread 字段只能追加 → 所有编码 Thread 偏移的指令永不逐字节相同
   （16 个 stub 里只有 `CallClangCodeWithSimulatorArgs` 38/38）。快照 hash、堆序、field_table 组内序同理。
   **是「两个 VM 必须完全一致」的代价，不是待修的 bug。**
3. ⚠️ **已落地的东西没有一处在运行时被执行过。** 字节对、单测绿，但无调用点、不在产物里、真机零实测。
   **「逐字节相同」证明的是抄对了，不是能跑。** 三条里最容易被百分比盖掉，也是唯一一条会让 22–28% 在真机上归零的。

**不是 24 小时能收尾的任务**（第 6 轮起未变）。剩余面：DD core 两项 + 不可见的 IL pass、
三阶段映射、wrapper 运行期接线、真机验证。前两项量级各自与一个 stub 子系统相当，
但**证据条件差得多**——stub 那条线快是因为「产物里能直接读发射字节」，DD 与 mapper 没有等价捷径。

### ✅ DDSlotMapping::ReadFromStream 已实现（2026-08-24，commit baf1d3f6af8）

Wire format（`DDSlotMapping::ReadFromStream` @ `0x100198fb0`，664 字节）：

```
N = varint
repeat N:
    a = varint;  b = varint;  c = varint
    map_a[a] = b
    if (c >= 1)  map_b[c] = b
```

无 magic/无 version——首个操作就是 varint 解码，因此它直接续接 `DDSlotVoters` 留下的流，两者之间没有任何分界标记。`make_unique<DDSlotMapping>` 调 `operator new(0x50)` = 80 字节 = 恰好两个 40 字节的 libc++ hash table，**两张表就是整个对象，没有其他成员。**

**证伪了旧猜测**：头文件里记的「两张表是 base_slot→patch_slot 与 patch_slot→base_slot（互逆）」——两张表都以 `b` 为值，`map_a` 以 `a` 为键、`map_b` 以 `c` 为键，是**两个键指向一个值，不是互逆关系**。a/b/c 的语义**刻意不在此断言**——它们取决于 `DDTableBuilder::VisitCode` 里 `this+0x10` 的外层对象身份，该对象尚未追踪到，这正是无法给三列命名的原因。

此提交**移除了 `runtime/vm/shorebird/` 树里最后一处占位符**。

⚠️ **这个格式没有独立 oracle**：他们不提供 `DDSlotMapping` fixture，writer 在闭源 `aot-tools.dill` 里。三个单测只能证明 reader 符合我从反汇编读出的格式，**不能证明那个格式符合他们的 writer**。用一个真实的 `--dd_slot_mapping` 文件（DDSlotMapping 格式而非 DDSlotVoters 格式）跑通决议，才是未执行的载重验证。

验证：ninja exit 0 + 时间戳护栏通过 + **76/76 shorebird 测试 exit 0**。负控制：把 `map_b` 的键从 `c` 换成 `b` → exit 255，两条 `map_b` 断言的行号都打出来了。

### `DDTableBuilder::VisitCode` 已完整解出（2026-08-24）

完整 C++ 伪码（`0x10022faf4`，1328 字节，全函数内联，两次 `__next_prime` 调用确认内建 `unordered_map`）：

```cpp
void DDTableBuilder::VisitCode(const Code& code) {
  ObjectPtr owner = code.ptr()->untag()->owner_;
  if (cid(owner) == kWeakSerializationReferenceCid) owner = unwrap(owner);
  if (cid(owner) != kFunctionCid) return;
  function_ = owner;                                 // this+0x08
  if (function_.ptr() == Object::null()) return;
  auto it = map1.find(function_->kernel_offset_);    // *(this+0x10) + 0x28
  if (it == map1.end()) return;
  intptr_t slot = it->second;
  if (slot < 0) return;
  slot_to_code_[slot] = code.ptr();                  // this+0x20, inline map
  if (slot > max_slot_) max_slot_ = slot;            // this+0x18
}
```

libc++ 节点布局（访问模式确认）：`[0]=next, [8]=hash, [0x10]=key, [0x18]=mapped`，32 字节，由 `operator new(32)` 分配。

产出：**slot→Code 表**（`slot_to_code_`，`this+0x20`）+ **max slot**（`this+0x18`，用于定表大小）。

`this+0x10` 的外层对象**尚未追踪到**——这正是 `DDSlotMapping` wire format 里 a/b/c 三列无法命名的原因。

### 假红第三次实例：`--list` 的输出带状态列（2026-08-24）

我用 `run_vm_tests --list | grep shorebird` 取测试名，但 `--list` 每行格式是 `TestName Pass`（`Pass` 是期望值，不是结果）。把整行字符串传给 `run_vm_tests`，harness 找不到该名字的测试，**PASS=0 FAIL=76**——看起来像全线崩溃，实际是参数错误，76 个测试一个都没跑。

✅ **判别法**：失败数等于测试总数时，先怀疑 harness/参数问题，而不是被测物出了 bug。取列要用 `awk '{print $1}'`，不能直接用 `--list` 的原始输出做参数。

与 [[feedback-false-green-traps]] 同型（第 13 种）。

### ✅ DD 列语义已确定：b=dd_slot、c=kernel_offset（2026-08-24，commit `4d9beaf06af`）

上一条记为「语义未确立，原因是 `VisitCode` 的 map 指针未追踪」。**那个原因已关闭**，本节是它的直接续篇。追踪链，每一环均实测：

1. `DDTableBuilder` 在 `0x10021b420` 构造，位于 `Precompiler::DoCompileAll()` 内
   ——`FinalizeIndirectStaticCallTable()` 无自有符号，已被内联进去。构造全程可见：
   `+0x00` vptr、`+0x08` `Function::Handle(zone)`、`+0x10` 来自 `ldr x19,[x26,#0x40]`、
   `+0x18` = `max_slot_` 初值 **-1**、`+0x20` 清零的内联 map（mlf 1.0f）。随后以
   `&builder` 调 `ProgramVisitor::WalkProgram(...)`，之后 `tbnz max_slot_,#0x3f`
   在其仍为 -1 时跳过全部后续。`[x26,#0x40]` 为 null 则 `cbz x19`（`0x10021b414`）跳过整个建表。
2. `x26` 来自 `ldr x26,[x23,#0x4b0]`（`0x10021b2a4`），`x23` 由
   `adrp x23,0x100521000`（`0x10021b1a4`）设置 → 即加载 `0x1005214b0`。
3. **`ShorebirdLinker::shared()` 从完全相同的地址加载单例**（`adrp x8,0x100521000` /
   `ldr x0,[x8,#0x4b0]`，magic-static guard byte 在 `0x1005214b8`）→ x26 就是 ShorebirdLinker，
   `shared()` 在此调用点被内联。
4. `ShorebirdLinker+0x40` = `dd_slot_mapping_` —— 该偏移由 LINKER_RECON §3 从
   `InitializeWithDDSlotMapping` 自己的 null check **独立**确立。两条路径，同一偏移。
5. `DDSlotMapping` = `{map_a_ @0x00, map_b_ @0x28}` → `VisitCode` 在 `pointee+0x28`
   读到的就是 `map_b_`。

**结论：列 b 是 `dd_slot`**（他们自己的 IL printer 用 `[dd_slot=%ld]` 命名它所索引的字段），
**列 c 是 Function 的 `kernel_offset_`**。

⚠️ **列 a 仍未命名。** 它映射到同一个 b，是同一 slot 的第二个身份。在 base↔patch linker 里
「另一个构建的 kernel_offset」是显而易见的读法——**正因为显而易见且零实测支撑，所以不写成事实**
（同 `0xc8` 猜对/`0xd8` 猜错那条教训：假的那条永远不会有人反驳）。

新增 `SlotForKernelOffset()`。`map_b_` **刻意不改名**：他们的字段名不可恢复，起个有意义的名字
会被后人读成「复刻的」而其实是我们发明的——与 `DDFunctionIdentity` 同型的错误。

验证：ninja exit 0 + 时间戳护栏 + **77/77** + 负控制 exit 255（把不存在的键从 -1 改成 0，
恰好打红分隔「slot 0」与「不存在」的那两条断言；slot 0 合法这点由
`DDSlotResolution_MaxSlot_ZeroIsALegalSlot` 另行钉住）。

遗留：`WalkProgram` 调用点设了 `x0..x3` 四个寄存器，而 demangle 出的签名只有三个参数
——实现 `FinalizeIndirectStaticCallTable` 前必须先核实真实参数表。

### 🔧 新工具 `scripts/adrp_scan.py`（commit `9319d0d`）

不需要全量反汇编就能找出谁材料化了某个地址（gen_snapshot 全量反汇编约 200MB，`xref.py`
需要现成的 objdump 清单）。做法：直接解原始 `__text` 字节，按寄存器追踪 adrp 页，
找到配对的 `add`/`ldr` 即报出，并归属到最近的前置 `nm` 符号。用法
`./adrp_scan.py <macho> <addr>...`。

⚠️ **先用阳性对照验过才敢用**：让它找 `VisitCode` 比较的那个全局，它报出 `0x10022fb90`，
与手读指令一致。正是它定位到 `DDTableBuilder` 的构造点，从而打通上面整条链。

### ✅ WalkProgram 的 4 参数之谜已解，实现阻塞解除（2026-08-24）

上一条留了个尾巴：调用点设了 `x0..x3` 四个寄存器，而 demangle 出的签名只有 3 个参数。
**用我们自己的二进制做对照实验解决**（同版本、同函数、栈帧同为 `0x140`、寄存器保存序列相同）：

| | 序幕 |
|---|---|
| 我们 `0x100118a78` | `mov x20,x2` / `mov x19,x0` —— **不读 x3** |
| 他们 `0x10016cc44` | `mov x21,x3` / `mov x20,x1` / `mov x19,x0` —— **读 x3** |

他们的 x2 被 `stp x9,x2,[sp,#0x28]` 存成 `ProgramWalker` 的第一个成员（x9 =
`vtable for dart::ProgramWalker+0x10`），而我们源码里 `ProgramWalker(Zone*, Heap*, ClassVisitor*)`
第一个成员正是 `heap_`。→ 他们把 heap 提进了参数表，visitor 挪到 x3。

⚠️ **记为异常，不编解释**：`0x10016cc44` 上只有一个符号且 demangle 为 3 参数，
而 4 参数的定义不该产生这样的名字。**别在这个 mangled name 上建任何推论。**

🔑 **这不阻塞复刻**：签名变化是他们的内部重构，不是行为契约。我们 3 参数的
`WalkProgram(zone, isolate_group, visitor)` 走同一趟遍历，把 builder 当 visitor 传即可。

### `FinalizeIndirectStaticCallTable` 的 walk 后阶段（2026-08-24）

`max_slot_` 仍为 -1（`tbnz x8,#0x3f` @ `0x10021b474`）则整段跳过。否则分配
`Function::Handle` 与 `Code::Handle`，然后**沿 libc++ 侵入式节点链遍历 builder 的内联 map**
（首节点 = `builder+0x30` 即 `__p1_`，后继 = `[node]`），对每个表项：

```
x8 = node[0x18]                  // VisitCode 存进去的 CodePtr
code_handle->ptr = x8
owner = code->untag()->owner_    // ldur x8,[x8,#0x37]
if (cid(owner)==kWeakSerializationReferenceCid) owner = unwrap(owner)
Precompiler::AddTypesOf(function)
```

`x21` 预载 `0x1004c6567` 的字符串 = **`"DD table target"`**，是 retain reason。
→ 这一阶段把**所有 Code 进了 DD 表的函数在树摇中保活**，正是"表可以派发到它们"的必然要求。
邻近串 `0x1004c652e` = `"Dispatch table references code for function to drop: %s\n"`，
就是这一阶段所预防的那个失败的诊断信息。

**仍未解码**：retain 循环之后，slot→Code 这张 map 如何变成快照真正携带的那张表。

### ✅ `FinalizeIndirectStaticCallTable` 已完整解出（2026-08-24，commit `854659e`）

最后一段（`0x10021b550` 起）：

```
bl Array::New(90, max_slot_+1, 1)            // (class_id, len, Heap::kOld)
for (node = builder+0x30; node; node = node[0])
    array[node[0x10] /*slot*/] = node[0x18] /*CodePtr*/   // StoreCompressedArrayPointer
str array, [object_store + 0x810]
```

**宿主是 ObjectStore，是实测不是假设**：`[Precompiler+8]`→Thread、`[Thread+0x690]`→IsolateGroup、
`[IsolateGroup+0x20]`→`object_store_`，最后这个偏移由**我们自己的 DWARF** 给出。

🔑 这同时从第二个方向印证了 WalkProgram 那条：调用点的第 2 参走**同一串** `[+0x690]`→`[+0x20]`，
所以它是 `ObjectStore*` 而不是 `IsolateGroup*`——正是我们 `WalkProgram` 开头那两个局部变量
（`object_store`、`heap`）中的第一个。→ 他们的签名是
**`WalkProgram(Zone*, ObjectStore*, Heap*, ClassVisitor*)`**，两个局部提进参数表、visitor 挪到第 4 位。

**cid 90 = `Array`**（可变，不是 ImmutableArray——表项在 patch 加载时要被改指向，必然如此）。
用 `scripts/cids.py` 展开 `CLASS_ID_LIST` 得到，**内建阳性对照**：必须先复现本会话从他们反汇编里
直接实测的 7=Function、16=WeakSerializationReference，否则脚本拒绝作答。

⚠️ **他们的 `ObjectStore+0x810` 是插入的新字段，不是我们的那个**：我们 `0x810` 是
`instructions_tables_`、`0x808` 是 `dispatch_table_code_entries_`（语义上最相邻的表，插入点应在其后）。
**与 Thread 同型**：我们必须自己加字段，且无法匹配他们的偏移——而这不重要。

**实现所需已齐**：表是长度 `max_slot+1` 的 `Array`，按 dd_slot 索引，装 `Code`，old-space 分配，
从 ObjectStore 可达。

**仍未解**：这张表在运行期如何进到 `Thread::indirect_static_call_table_`（Thread+0x978）。

### ✅✅ `FinalizeIndirectStaticCallTable` **已实现并第一次真正跑起来**（2026-08-24，commit `72f79dc5133`）

DD core 的前一半落地了。三个阶段与他们的控制流一一对应：无 mapping 早退 → WalkProgram 收集
`dd_slot→Code` → `max_slot` 仍为 -1 早退 → retain（reason 串 `"DD table target"` 是**他们的**，
在 `0x1004c6567`）→ `Array::New(max_slot+1, kOld)` + `array[slot]=code` + 存进 ObjectStore。

🔑 **ObjectStore 字段落在 `0x810`，与他们同偏移**。这次能对齐而 Thread 不能，原因是 `CheckOffsets`
钉住的 5 个 ObjectStore 字段都在字段表很靠前的位置，插在 `dispatch_table_code_entries_` 之后
不会让它们移位。**先查了这一点才动手**。

他们的 `Array::New(90, len, 1)` 是 protected 三参版——反汇编看到的是公开两参版被内联进去，
所以我们的 `Array::New(len, kOld)` 是同一件事。

⚠️ **一处刻意偏差**（已在源码标注）：builder 存 zone handle，他们存裸 `CodePtr`。
phase 3 的 `Array::New` 会分配，压缩式 GC 会让裸指针失效。**这是关闭隐患，不是复刻隐患。**

### 🔑 这是 DD 代码第一次在运行时执行（不只是逐字节对比）

CLAUDE.md 长期记着「已落地的东西没有一处在运行时被执行过」。这一条对 DD 建表这部分**不再成立**：

用 `--print_dd_function_identity_to` dump 里的**真实 kernel_offset** 造 mapping
（`scripts/mk_mapping.py`，commit `e306831`），喂给我们的 gen_snapshot，用**上游自带**的
`--write_retained_reasons_to` 观测（没有发明新 flag）：

| 输入 | `"DD table target"` 出现次数 |
|---|---|
| 5 行 mapping | **5**（挂在真实函数名上，`"retained":true`） |
| 不传 `--dd_slot_mapping` | **0**（早退分支有效，且没有别处发这个 reason） |
| 3 行 mapping | **3**（数字跟输入走，不是常量） |

⚠️ **用真实 offset 是关键**：编造的 key 匹配不上任何函数 → `max_slot` 停在 -1 → 早退，
于是得到一个「全绿」但只证明了早退分支能跑的运行。

**回归**：ninja exit 0（Release+Product）、时间戳护栏、76/77 单测、
`verify_reproduction.sh` 24 产物 + 14 stub 全过（**`ddid` 在七个 fixture 上仍逐字节相同**
——往 ObjectStore 中部插字段没有破坏任何既有复刻）。

**仍未验证**：这张表运行期如何进到 `Thread::indirect_static_call_table_`；真机零实测。
**DD core 的另一半（`IndirectStaticCallInstr` 19 方法 + 那个零符号的 IL pass）仍为 0。**

### ✅✅ `IndirectStaticCallInstr` 已实现——DD core 的符号面全部持平（2026-08-24，commit `ccad100b37c`）

两个 product 二进制同口径重测：

| 标志 | 他们 | 我们 | |
|---|---:|---:|---|
| `IndirectStaticCallInstr::` 原始 nm 行 | 42 | 30 | 不可比（我们未 strip）|
| **去重方法名** | **19** | **19** | **集合完全相同**（`comm` 两个方向都为空）|
| `::VisitIndirectStaticCall` | 3 | 3 | 集合相同 |
| `DDTableBuilder` / `DDSlotMapping::` / `ShorebirdLinker::` | 8/2/20 | 8/2/20 | 持平 |

🔑 **判据是集合 diff 不是计数**。本仓库已经两次被"数对了个数、数错了东西"的正则坑过。

**这意味着什么、不意味着什么**：
- ✅ 类、三个 visitor、序列化字段、codegen 入口都存在；且加进 `FOR_EACH_INSTRUCTION`
  与往 Thread 加字段**都没有移动** class table 或任何 dump（`verify_reproduction.sh` 24+14 全过）。
- ❌ **不代表机制能跑**：把 static call 改写成 indirect 的那个 **IL pass 零符号**，
  符号口径在结构上就报不了它。唯一判据是 `--print_dd_resolution_to` 的 `rewritten` 列（他们 2 / 我们 0）。
- ❌ **不代表实现正确**：截至此 commit **没有任何测试构造过这个类**，19 个方法一个都没执行过
  ——这正是 `AllocateMetadata()` 的老毛病，已写进 commit message 而非默默留着。

**三处是判断不是誊抄**（后人从二进制分辨不出来，所以必须记）：
1. `ConstantPropagator` 返回 `non_constant_`——**正确答案而非保守选择**：折叠会把 patch 前的目标固化。
2. `ComputeType` 不从目标函数体收窄类型，同理。
3. Thread 字段**追加**并走 `indirect_static_call_table_offset()`。他们的 `0x978` 不可用
   （他们的块在结构中部、我们只能追加）；硬编码会读到无关字段，**而症状会伪装成「表内容错了」**。

`PrintOperandsTo` 逐字节复刻格式串，含一处细节：上游格式以空格结尾，
**他们以 `]` 结尾、仅在有参数时才发分隔空格**（反汇编里被 `cmp x0,#1` 门控）。

**实现估计 26–32% → 30–36%**。⚠️ 上调的是"看得见的部分"，未被执行这一条不变。

### ✅✅✅ DD IL pass 已实现——DD core 两半都落地了（2026-08-24，commit `b13e2a0d54e`）

「那个把 static call 改写成 indirect 的 IL pass 完全内联、零符号、真的看不见」——**这条已被推翻**。
看不见的是它的代码，不是它的行为。方法见 [[reference-differential-flag-oracle]]：
用**他们的** gen_snapshot 把同一份 kernel 跑两遍，只差 `--dd_slot_mapping`，diff 产物。

**由此确立的四件事（全部实测）**

1. **闸门就是 mapping**：无 mapping 时 `Thread+0x978` 的加载数为 **0**，有 mapping 时 **3**。
   与 `FinalizeIndirectStaticCallTable` 同一个闸门。
2. **规则是完备的**：`patch.so` 对 DD-slot 目标有 3 处直接调用（`Expando.[]` ×2、
   `_FinalizerImpl._runFinalizers` ×1），`patch_dd.so` **0 处直接、恰好 3 处间接**。
   没有遗漏，也没有多改；7 个 resolved slot 里另外 5 个没有调用点，就没产生调用点。
3. **它是纯粹的调用点替换**：`_NativeFinalizer._removeEntries` 两边 77 vs 79 条指令，
   归一化 diff **只有**一条 `bl <Expando.[]>` 对三条间接序列，其余 **76 条完全相同**。
4. **发射序列的真值字节**（此前只从他们的 `EmitNativeCode` 反推过形状）：
   ```
   ldr x16, [x26, #0x978]   ; 表基址出自 Thread
   ldr x16, [x16, #0x20]    ; table[dd_slot]，slot 折进立即数
   blr x16
   ```
   🔑 **第二条 ldr 同时说明了「表是什么」**：加载出来的字直接被 `blr`，所以**表项是裸的 entry point，
   不是装 Code 的 Dart Array**——tagged Array 需要 0x17 数据偏移和一次 untag，两者都没有。
   偏移 0x18/0x20 = 索引 **3/4**，正是 `dd_resolution.tsv` 里 `rewritten=1` 的那两个 slot。

⚠️ **顺带订正一个长期判据**：`rewritten` 列曾被记为「IL 变换的计数级判据」。它是**逐 slot** 的
（slot 3、4 各 1 → 表头 2），而调用点是 **3** 处。它数的是「有几个 slot 至少有一处被改写」，
比调用点粗一级。**真判据是数发射出来的调用点。**

⚠️ **pass 的位置：证据允许、但不强制。** 放在 `UseTableDispatch` 紧后（`SelectRepresentations_Final`
之后、`AllocateRegisters` 之前）。「其余 76 条指令完全相同」与晚跑一致，但**分辨不了早跑**——
本 fixture 里那 3 处本来就没被内联，早于 inliner 的 pass 会给出同样输出。已在源码注释里写明这点。

**我们的实现与验证**（`dd_pass_check.sh`，可复跑，带 `--self-test`）

发射端从 4 条缩到 3 条（原来是算出 slot 地址再间接调用）；`blr x16` = `d63f0200` **与他们逐字节相同**，
另两条只差立即数字段（Thread 偏移我们是追加的 **0xf78**、他们 0x978；slot 索引随 mapping）。

用我们的 gen_snapshot 在他们的 fixture 上：

| 输入 | 间接调用点 | 消失的直接调用 |
|---|---:|---|
| 无 mapping | **0** | — |
| 全部 1272 个可用函数 | **1724**（跨 539 个 slot） | — |
| 只映射 kernel_offset 215094 | **103** | `_StringBase._interpolate` ×103，**且只有这一个名字** |
| 只映射 kernel_offset 18339 | **79** | `RangeError.checkValidRange` ×79 |
| 只映射 kernel_offset 54623 | **73** | `StringBuffer.write` ×73 |

单函数那三行是最强的判据：**改写数 = 该函数被直接调用的次数，且没有第二个名字受影响**。

回归：81/81 shorebird 测试；`verify_reproduction.sh` 24 产物 + 14 stub 全过
（ct/dt/ddid 的逐字节复刻没被动到）。

⚠️ **假红实例（第四次）**：`dd_pass_check.sh` 的调用点计数器最初要求第二条 ldr 带 `, #` 位移，
但 **slot 0 的偏移是 0，objdump 不打印位移**（`ldr x16, [x16]`）——而单行 mapping 永远用 slot 0。
harness 报 0、手测是 73，看起来像 pass 坏了。**判别法：harness 与手测不一致时先怀疑 harness。**

**仍未解**：这张表运行期如何进到 `Thread::indirect_static_call_table_`；真机零实测。

### ✅✅✅✅ DD 表的运行期安装已实现，且**整套机制第一次真正跑起来**（2026-08-24，commit `c14537ce1ae`）

**契约几乎全部来自他们引擎的 dSYM，不是推测**（`ios-release/.../Flutter.framework.dSYM`）：

| 符号 | 类型 | 位置 |
|---|---|---|
| `Thread::indirect_static_call_table_` | **`const uword*`** | `thread.h:1685` @0x978 |
| `IsolateGroup::indirect_static_call_table_` | **`unique_ptr<unsigned long[]>`** | `isolate.h:987` @0x450 |
| `IsolateGroup::indirect_static_call_table_size_` | `intptr_t` | `isolate.h:988` @0x458 |
| `Deserializer::ReadIndirectStaticCallTable()` | void | `app_snapshot.cc:1031`，调用点 `:7717` |

字段位置在 dispatch table 诸字段与 `saved_unlinked_calls_` **之间**。⚠️ 我们此前把 Thread 那个字段声明成 `uword`（值），应为指针 —— 发射的码看不出差别，但所有权语义写反了。

`ReadIndirectStaticCallTable` 逐条转写自 `0x741f1c..0x74204c`：
```
length = ReadUnsigned();  if (0) return;
for i: ref = ReadUnsigned();  if (ref == 0) FATAL;      // 0 是致命错误，不是「缺省」
       table[i] = refs[ref]->untag()->entry_point_;
group->indirect_static_call_table_ = table;  ..._size_ = length;
```
写侧极简（长度 + 每槽一个 ref），**不用**上游 dispatch table 的 delta/repeat/recent 编码。

🔑 **ObjectStore 字段名可恢复**（此前记「不可恢复、拼法是我们自己起的」——**错**）：
`WriteRoots` 用 `EMIT_FIELD_NAME(type,name) #name "_\0"` 把整个字段表发成 strtab，
所以他们 gen_snapshot 里按**表序**存着字段名。实测（阳性对照：5 个已知上游名都在）：
```
dispatch_table_code_entries_
indirect_static_call_table_code_entries_   ← 他们的真名，正是我们放的位置
selector_row_entries_                      ← 第二个我们没有的私有字段
instructions_tables_
```
⚠️ `selector_row_entries_` 意味着**此后所有 ObjectStore 字段我们与他们差一格**，别再从他们二进制读后面字段的偏移。

**三个 bug，全是「把快照装载起来」才发现的，读代码/数调用点一个都发现不了**

1. **陈旧 Code**：建表在 `DropFunctions` 前（保活要求），而 `DiscardCodeObjects`/`Dedup` 在其后
   → 槽里可能是被丢弃的重复体；把它 Push 成根就让两个 Code 共享 Instructions，
   打中 `CodeSerializationCluster::Insert` 的 `RELEASE_ASSERT(!FLAG_precompiled_mode)`。
   加了 `RefreshIndirectStaticCallTable()`（dedup 后重指向）。⚠️ 他们的反汇编里没有这一步，这步是我们的。
2. **调用约定**：`FlowGraph::InsertMoveArguments` 按**指令类型**认目标函数，不认识我们的新指令
   → `target=null` → 退回**栈传参**，而被调方按**寄存器**编译。
   `RangeError.checkValidRange` 于是读到地址当长度。`InsertRecordBoxing` 有同样的缺口（藏在 `UNREACHABLE()` 后面）。
   ⚠️ 我在此之前先改了 `EmitIndirectStaticCall` 的 ARGS_DESC 判据（改成上游的
   `PrologueNeedsArgumentsDescriptor()`）——**那个改动没有修好 bug**，已在注释里写明，免得留下假线索。
3. **`dartaotruntime` 从来没链接过**：`linker.cc` 用 `Class::allocation_stub()`，AOT 运行时没有这个 API。

**端到端实测**（我们的 gen_snapshot + 我们的 dartaotruntime，跑他们的 fixture）

| mapping | 间接调用点 | 运行结果 |
|---|---:|---|
| 无 | 0 | ✅ 输出正确 |
| `_StringBase._interpolate` | 102 | ✅ |
| `RangeError.checkValidRange` | 79 | ✅（修前是错值） |
| `StringBuffer.write` | 73 | ✅ |
| **1043 函数（去冲突）** | **1622** | **✅ 输出完全正确** |
| 1106 函数（全量） | 1698 | ❌ Stack Overflow |

🔑 **最后两行的差别是 fixture 不是机制**：`hello.ddid` 里 **63 个 kernel_offset 被多个函数共享**
（1176 行 → 1106 个不同 offset），多个函数塌进同一 slot，调用 A 落到 B → 无限递归。
去掉冲突项后 1622 处调用全部到达正确目标。**这条必须写清楚，否则「是 fixture 问题」听起来就像借口。**

**这推翻了长期挂着的第三条限定的大部分**：「已落地的东西没有一处在运行时被执行过」——
DD 建表 + IL pass + 表安装 + 表派发，现在是一条被真实执行并产出正确结果的完整链路。
⚠️ 仍然成立的部分：**真机零实测**；wrapper/simulator 那条线仍无生产调用点；
且这是 `dart_force_simulator=true` 的 host 构建，不是 iOS 真机。

回归：81/81 shorebird 测试、`verify_reproduction.sh` 24 产物 + 14 stub、`dd_pass_check.sh` 全过。

### 端到端运行验证已固化（2026-08-24，`08cbcc0`）

`dd_runtime_check.sh` + `scripts/mk_clean_mapping.py`。**判据是 stdout 与无 mapping 构建逐字相同**，
不是「没崩」——派发到错函数的快照照样能打印东西。期望输出**写死在脚本里**而不是现场采集，
这样「对照自己坏了」是失败而不是新基线。

`--self-test` 除了把三个 site 计数各加 1，还用 `--keep-collisions` 重建全量 mapping
（把 63 个被多函数共享的 kernel_offset 放回去）。**它精确复现了那个栈溢出**——
这比「harness 能报错」更有价值：它把「冲突是原因」从事后解释变成了可复现的因果。

### 🔴 `print_shorebird_info` 复核（2026-08-24）：仍然阻塞，但结构解出了一层

重新核查证据面（因为本会话已两次推翻「不可得」的旧结论）：
- Shorebird 缓存里**没有** gen_snapshot / analyze_snapshot 的 dSYM（`find` 全仓，只有 Flutter.framework 的）
- 映射器类型**不在引擎 dSYM 里**（`ObjectPoolMappingsAggregator` / `ObjectPoolEditor` / `InstructionCountNoPadding` 全无命中）
→ **旧结论成立**：反汇编是唯一路径，量级与 `RunOnSimulator` 相当。按规则 4 延后。

但输出本身给了结构（此前只记了「六个计数」）：
```
Link Results 606     Mappings from Link Results 606,  Pair Constraints 0,   Backfill 13
Link Results 1121    Mappings from Link Results 1113, Pair Constraints 292, Backfill 16
Sorted ObjectPool, moved 0 of 1421 entries.
```
🔑 **pass 2 的 1113 + 292 + 16 = 1421，恰好等于 object pool 条目总数**。
→ 三个阶段合起来必须为**每一个** base object-pool 条目给出对应的 patch 索引，
最后把 patch 的 pool **重排**到与 base 同序（"moved 0" = 本例已同序）。
pass 1 的 606+0+13=619 不等于 1421，说明 pass 1 作用域更小（是个子集）。

### 🔑 引擎 DWARF 还给了整套 wrapper 与 Deserializer 私有面（2026-08-24）

查 `dart::shorebird::` 与 `dart::Deserializer::` 得到（全部带 linkage name）：

- `WrapperAllocator::{AllocateMetadata, EnsureStubPage, AllocateWrapperPage, EnsureNextWrapperEntry, ContainsEntryPoint(uword,uword*)}`
- `WrapperLayout<{CPUToSim,SimToCPU}Config>::{RWMappingSize, RXMappingSize, NumWrappersPerPage}`
- `WrapperAllocator::Layout::fromTemplate<...>`
- **`std::function<uword(uword)> Deserializer::WrapperForRunTarget(LinkOracle::RunTarget) const`** @ `app_snapshot.cc:894`
- **`Deserializer::PrintShorebirdStats()`**、**`Deserializer::Stats::Record(LinkOracle::RunTarget, long)`** ← 两个此前完全不知道的成员

→ 「`AllocateMetadata()` 没有生产调用点」这个缺口**证据已经齐了**，且 `LinkOracle` 已实现（`94ee77c3624`）。
这是下一个该做的（任务 #7），优先级高于三阶段映射。

### ✅ `Deserializer::EntryPoints` 已实现——wrapper 的接缝就位（2026-08-24，`ef984048a03`）

引擎 dSYM 给出整块 Shorebird Deserializer 面（`app_snapshot.cc` 约 700–1030）：

| 成员 | 签名 | 行 |
|---|---|---|
| `EntryPoints`（类，48B） | `payload_start`@0 / `entry_point`@8 / `unchecked_entry_point`@0x10 / `monomorphic_entry_point`@0x18 / `monomorphic_unchecked_entry_point`@0x20 / `unchecked_offset_`@0x28 / `has_monomorphic_entry_point_`@0x2c | 702–741 |
| ctor | `(uword, std::function<uword(uword)>, uint32_t)` | 716（体在 `0x733174`） |
| `PrintShorebirdStats()` | void | 804 |
| `AssertInstructionMatch(uword, uword) const` | void | 909 |
| `WrapCode(CodePtr, long, uint32, uword, uint32&, uword&)` | → `EntryPoints` | 923 |
| `WrapperForRunTarget(LinkOracle::RunTarget) const` | → `std::function<uword(uword)>` | 894 |
| `WrapFunction(long, uword) const` | → `EntryPoints` | 979（体 `0x732d4c`，1060B / 265 条） |
| `Stats::Record(LinkOracle::RunTarget, long)` | void | — |

🔑 **机制**：上游在 `ReadInstructions` 里内联算四个 entry point；他们把这段算术提成一个类，
**每个结果都过一遍传进来的函数**——因为被模拟的函数必须经 CPU→Sim wrapper 进入而不能直接跳。
构造函数体（`0x733174`，已逐条读出）与上游算式逐项对应：

```cpp
has_mono = payload_info & 1;  unchecked_offset = payload_info >> 1;
base = payload_start + (has_mono ? kPolymorphicEntryOffsetAOT : 0);
entry_point           = w(base);
unchecked_entry_point = unchecked_offset ? w(base + unchecked_offset) : entry_point;
monomorphic_entry_point = has_mono ? w(payload_start + kMonomorphicEntryOffsetAOT) : entry_point;
monomorphic_unchecked   = (has_mono && unchecked_offset)
                            ? w(payload_start + kMonomorphicEntryOffsetAOT + unchecked_offset)
                            : unchecked_entry_point;
```

⚠️ **与上游的一处真实差异（是他们的，不是我们的）**：上游无条件加 `unchecked_offset`（加 0 免费），
他们**判零**——因为 `w()` 可能分配，对同一地址调两次就会拿到两个 wrapper。

⚠️ **一个差点写错的常数**：他们 `add x8, x1, #0x18` = 24。我们 `object.h` 里紧邻的 22 是 **X64** 分支，
ARM64 分支才是 24。**核对了架构块才落笔**——否则会写下一条「他们的常数和我们不同」的假发现。

⚠️ **订正记忆**：此前记「`WrapperForRunTarget` 的**两个** lambda 各调一次 `AllocateMetadata`」。
DWARF 里 mangled name 只有**一个** lambda 类型（`UlmE_`）。lambda 体尚未读出。

**我们实现了什么**：`EntryPoints` 全部（逐条对应他们的构造函数），`ReadInstructions` 改由它计算，
`WrapperForRunTarget` 的 **cpu 臂**（恒等——这不是占位符，CPU 上运行的代码就是从自身地址进入）。
**sim 臂是 `FATAL` 而不是悄悄恒等**：没读出他们的 lambda 就写一个是发明；
且一个没包 wrapper 的模拟 entry point 不会在出错的地方失败。

**验证**：`ReadInstructions` 对快照里每个 Code 都跑，所以运行检查是强判据 ——
`dd_runtime_check.sh` 五个用例全过（1622 处间接调用仍全部到达）；
**负控制**：把 polymorphic 偏移换成 monomorphic → 五个用例全红（exit 134）。
81/81 shorebird 测试、`verify_reproduction.sh` 24+14 全过。

**剩余**（任务 #7 续）：lambda 体、`WrapCode`、`WrapFunction`(265 条)、`AssertInstructionMatch`、
`PrintShorebirdStats`、`Stats::Record`。

### `Deserializer::WrapFunction` 已重建（2026-08-24，见 `WRAP_FUNCTION_RECON.md`）

体在 `0x732d4c`，265 条。返回 48 字节的 `EntryPoints` → **x0 是 sret**，故 x1=this、x2=long、x3=uword。

🔑 **用我们自己未 strip 的构建做布局 oracle**（同 [[reference-differential-flag-oracle]] 一样是可复用手法）：
`instructions_table_`@0xb8 ✓、`refs_`@0x80 ✓（顺带**独立印证**了上一轮 `ReadIndirectStaticCallTable` 的 `[x19+0x80]` 读法）。
我们的 Deserializer 到 0xc0 就结束了 → **`+0xc0` 与 `+0xc8` 是 Shorebird 追加的字段**。

**查表的键**：
```
[this+0xb8] → handle → ptr_ → untagged+0x18 = rodata_
rodata + index*8 → ldrsw [+0x10] = entries[index].pc_offset      ← int32 pc 偏移
```
（`UntaggedInstructionsTable`：`code_objects_`@8 / `length_`@0x10 / `rodata_`@0x18 / `start_pc_`@0x20；
rodata 头 16 字节后是 8 字节一条的 `{pc_offset, stack_map_offset}`。）
这正对上我们 `LinkOracle` 里 `unordered_map<int,int>` 的键类型。

**控制流**：`[0xc0]!=1` → wrapper A；`LinkOracle::shared()==nullptr` → wrapper B(line 993)；
否则查表，未命中 → wrapper C(line 1000)、命中 → wrapper B(line 1000)。
最后一律 `EntryPoints(payload_start, wrapper, payload_info=0)`
——**每个调用点都是 `mov w3,#0`**，所以函数的四个 entry point 全塌成 `wrap(payload_start)`。
line-1000 那个内联实例有**两段**范围（`0x732f88` 与 `0x733060`），就是 `WrapperForRunTarget` 的两个 switch 臂。

🔑 **命中分支就是 `AssertInstructionMatch`**（`:909`）：取出映射值（base 侧 pc 偏移），
比较 `start_pc_+映射值` 处与 `payload_start` 处的**首条指令字**，不等则报错。
即：链接过的配对只有在 base 的代码确实以同一条指令开头时才被采信 —— 便宜，且能抓到过期的 link table。

**刻意未断言**（三项，都是「显而易见所以危险」的那类）：
`[0xc0]`/`[0xc8]` 是什么；vtable `+0xcc0` 与 `+0xd08` 哪个是 cpu 哪个是 sim（lambda 体未读）；
命中分支传给 `EntryPoints` 的 `payload_start` 是 patch 的还是按映射重算的（未命中分支是 `mov x1,x3` 原样传）。

**本轮没有实现 `WrapFunction`**：上面三项不确定意味着写出来就是发明。`WrapCode`@:923 同理未做。

### ✅✅ `WrapperForRunTarget` 的两个 lambda 已解出——`AllocateMetadata` 的生产调用点找到了（2026-08-24）

`operator()` 在 libc++ `__func` vtable 的 **+0x30**（`EntryPoints` 构造函数就是 `ldr x8,[x0]; ldr x8,[x8,#0x30]; blr x8`）。
从 `__DATA_CONST,__const` 读出三个 vtable：

| vtable | +0x30 | 是什么 |
|---|---|---|
| `+0xc78` | `0x73344c` | `__func<uword(*)(uword)>` —— **函数指针**，不是 lambda |
| `+0xcc0` | `0x733304` | `WrapperForRunTarget::'lambda'` |
| `+0xd08` | `0x7333a8` | `WrapperForRunTarget::'lambda0'` |

两个 lambda 体**只差一个偏移**：
```
ldr x20,[x1]         ; entry_point 实参
ldr x8,[x0,#8]       ; 捕获的 this(Deserializer*) → [+8]=thread_ → [+0x690]=isolate_group_
ldr x19,[x8,#0x8d0]  ; 'lambda'（'lambda0' 用 0x8d8）
bl  0x7d0728         ; WrapperAllocator::AllocateMetadata()   ← 生产调用点，两处
str x20,[x0]         ; *metadata = entry_point
ldr x8,[x19,#0x40]
sub x0,x0,x8         ; 返回 metadata - layout_.rx_mapping_size
```

🔑 **DWARF 直接命名，不用推理**：
```
IsolateGroup+0x8d0  shorebird_cpu_to_sim_wrappers_  shorebird::CPUToSimWrapper*
IsolateGroup+0x8d8  shorebird_sim_to_cpu_wrappers_  shorebird::SimToCPUWrapper*
```
→ `'lambda'` = **sim 臂**（模拟目标要经 CPU→Sim wrapper 进入），`'lambda0'` = **cpu 臂**。
上一轮我刻意没写下的那条推理（命中=已链接=cpu）**被独立来源证实了**——但记录的理由是 DWARF 命名，不是控制流暗示。
⚠️ 注意 **cpu 臂也分配 wrapper**：wrapper 两个方向都需要，原生代码也得能被模拟器调到。

**`WrapperAllocator` 布局与我们的字段名逐项相同**（`stub_page_`@0 / `wrapper_pages_`@8 /
`offset_of_first_wrapper_in_page_`@0x28 / `wrappers_left_in_current_page_`@0x30 / `layout_`@0x38，
`Layout{page_size, rx_mapping_size, rw_mapping_size, num_wrappers_per_page, metadata_size,
landing_pad_size, shared_body_size}`）→ **`+0x40` = `layout_.rx_mapping_size`**。
RX/RW 双映射连续排布，从 RW 侧 metadata 减去 RX 区大小即得对应可执行 wrapper —— 与上游
`FfiCallbackMetadata` 的 trampoline↔metadata 关系同构。

**仍未确立**：`Deserializer+0xc0`/`+0xc8` 两个 Shorebird 字段；命中分支传给 `EntryPoints` 的
`payload_start` 是否重算；`+0xc78` 那个函数指针指向谁（要去构造点找）。

**下一步（实现）**：给 IsolateGroup 加两个 WrapperAllocator（他们是指针，多半惰性创建）+ 访问器，
在 `WrapperForRunTarget` 的两臂里按上面的伪码接上。**这会关闭「`AllocateMetadata()` 无生产调用点」这个长期缺口。**

### ✅✅ wrapper allocator 已接线——`AllocateMetadata()` 的生产调用点缺口关闭（2026-08-24，`1f836a400a6`）

`Deserializer::WrapperForRunTarget` 两臂按解出的 lambda 实现；`IsolateGroup` 加了
`shorebird_cpu_to_sim_wrappers_` / `shorebird_sim_to_cpu_wrappers_`（惰性创建 —— 他们是指针，
且各自要预留地址空间）。归属来自 DWARF 命名，不是从控制流推的。
我们的 `WrapperOfMetadata()` 就是他们的 `sub x0,x0,[x19,#0x40]`：`MetadataOffset()` 定义为
`layout_.rx_mapping_size`，与他们一致（第三次独立印证，另两次是反汇编与 wrapper.cc 里已有的注释）。

🔴 **两个「读代码发现不了、接上去用才暴露」的问题**

1. **`CPUToSimConfig::GetStubCodeRange` 还在报空范围**，注释写着「272B body 尚未转写」——
   **但它早就转写了**（`GenerateTransitionDartToSimulatorIfNeededStub` 就在树里，`compare_stubs.py` 也在比它）。
   注释活得比工作久。而空范围**不是无害的**：`EnsureStubPage` 什么也不映射 →
   `AllocateMetadata()` 永远返回 nullptr → **这个方向一个 wrapper 都发不出来**。
2. **两个既有测试正是把这个空范围当成期望**（拿 `CPUToSimConfig` 当「没有 stub 的配置」的替身）。
   **它们就是这个过期状态能活下来的原因：测试同意它。**
   已改成用「构造上就为空」的 layout，并且 `CodeSizeComesFromTheCallback` 现在**断言两个生产配置都报非零**
   —— 下一个丢掉 stub 的配置会失败，而不是被当成预期。

⚠️ **闸门**：`ReadInstructions` 只在装了 `LinkOracle` 时才包。没有 patch 时包 wrapper 每个 entry point
要花一个 landing pad 且毫无收益。他们的闸门是 `Deserializer+0xc0`（含义未确立），
所以我们用**能说清楚的条件**，而不是猜他们的。

验证：83/83 shorebird 测试；`verify_reproduction.sh` / `dd_runtime_check.sh` / `dd_pass_check.sh` 全过。
**两个负控制各自只抓自己的失效模式**：报 CPU→Sim stub 缺席 → 只有 round-trip 红；
给 cpu_to_sim 访问器配错 config → 只有 config 检查红。

### ✅✅✅ wrapper **真的跑起来了**，Deserializer 的 Shorebird 字段全部命名（2026-08-24，`7bdc43af652`）

上一轮 `WRAP_FUNCTION_RECON.md` 留白的两个字段，直接从**他们的** dSYM 查出来了
（⚠️ 上一轮我用的是**我们自己**的 DWARF 做上游布局 oracle，忘了他们的 dSYM 里有完整的 Deserializer）：

```
0xc0  instructions_type_                   InstructionsType { vm=0, app=1 }
0xc4  shorebird_instructions_only_         bool
0xc8  shorebird_base_instructions_table_   const InstructionsTable&
0xd0  shorebird_base_instructions_buffer_  const uint8_t*
0xd8  stats_ { cpu_instructions_length_, sim_instructions_length_,
                cpu_entry_point_count_, sim_entry_point_count_ }
```

→ `:991` 那个 FATAL 读通了：**base instructions table 为 null 而 LinkOracle 存在**（装了 patch 却无 base 可链接）。
→ 顶层闸门是 `instructions_type_ == app`；非 app 走**恒等函数指针**（`0x733170` 就是一条 `ret`，已实测）。

**🔑 两个实验证明 wrapper 真的在执行**（这是本项目最大的一条空白）：

1. 去掉「有 patch 才包」的闸门 → fixture 里 1400 多个 entry point 全部走 wrapper → **程序输出仍然完全正确**
2. 再把存进 metadata 的目标改成 `entry_point + 4` → **每个用例都段错误**

**第二个才是判据**。只有第一个的话，「跑对了」与「wrapper 被悄悄绕过了」无法区分。
两个合起来说明：我们的 **Sim→CPU stub body 每次运行被进入数千次，并正确经 metadata 路由到目标**。
这是 wrapper 子系统第一次被证明**能跑**，而不只是字节对得上。

因此闸门已改成与他们一致（`instructions_type_ == app`，不看 patch 是否存在）——
原先保守是因为「从没执行过」，那个理由已经不成立。
⚠️ 证据来自一个小程序、一个平台；真实 app 的 entry point 多得多，wrapper 页也相应更多。

🔴 **第二条过期注释**（与 `GetStubCodeRange` 同型）：`wrapper.cc` 写着 Sim→CPU 的 shared body
「仍是断点占位符」。**不是**——它是转写好的 7 条指令，由 `ASSERT_EQUAL` 钉死 28 字节；
里面那条 `brk` 是 `kRunDartOnCPUCode`，是**机制本身**（模拟器靠它交还控制权），不是占位。
⚠️ **一个会话里两条过期注释都出自同一个文件**，且都声称「某某还没做」而其实早做完了。

验证：83/83；`dd_runtime_check.sh` / `dd_pass_check.sh` / `verify_reproduction.sh` 全过。

### ✅ `print_shorebird_info` **不再是「唯一被阻塞的 flag」**——引擎那半已实现（2026-08-24，`0bf2ef86f1c`）

长期记着「11 个 flag 完成 10，只差 `print_shorebird_info`（需三阶段映射）」。
**这个说法漏了一半**：`print_shorebird_info` 在**两边**都存在。
- gen_snapshot 侧：门控三阶段 object-pool 映射报告 → **仍然阻塞**
- **引擎侧：门控 `Deserializer::PrintShorebirdStats`** → **不需要任何我们没有的东西，已实现**

引擎里那个字符串就在二进制里（`strings` 可见），门控是 `ldrb [0xb874d0]; cmp #1`（bool flag）。
flag 描述串 `"Print shorebird information"` 逐字取自他们的 gen_snapshot。

**全部转写，无发明**：`Stats` 四个字段与顺序来自 dSYM（`Deserializer+0xd8`）；
`Record` 是每个包装点之后内联的 28 字节（加长度、计数加一）；
七行输出是他们内联版打印的七个格式串，含两行计数标签冒号后的**三个空格**（用于对齐数字）。

实测输出：
```
Shorebird stats:
  Has shorebird base instructions table: no
  Has LinkOracle: no
  CPU instructions length: 267504
  Sim instructions length: 0
  CPU entry point count:   1380
  Sim entry point count:   0
```

🔑 **1380 这个数可交叉验证**：同一份 dill 的 `--print_dd_function_identity_to` 是 **1266 行**，
而该 dump **不为 type-test stub（110）与 stub（4）产生行** → `1266+110+4 = 1380`，精确吻合。
（110/4 是早先在他们 fixture 上测的，所以记作**一致**而非证明。这是两个 dump 之间第一次交叉验证。）

⚠️ **instructions length 是上界不是他们的数**：他们在取 `end - start` 前会**回扫尾部 padding**
（`0x73aab4..0x73aad4`），而 padding 字未确立，所以我们用的是到下一个 entry 的原始距离，会多算。
**计数是精确的。** 这句写进了代码注释，免得后人发现两个数对不上时才知道。

⚠️ 顺带一个坑：`code->untag()->instructions_length_` 在 **AOT 主路径上根本没被设置**
（只有 deferred 早退那支设为 0）。第一版实现读了它 —— 会记录垃圾值。

### ✅ instructions length 已精确（2026-08-24，`08b52875f9f`）——上一条的「上界」告诫已可撤销

上一轮记「padding 字未确立，所以长度是上界」。**现在确立了**：他们的长度计算在
`0x73aa5c..0x73aad4`，trim 循环比较的常量是 **`0xd4200000` = `brk #0`**（镜像的填充字）。

而且形状也订正了上一条的说法：**只有最后一个 entry 需要 trim**。
其余 entry 量到「下一个 entry 起点」，本来就停在真实代码处。
所以旧说法错了两处：它**不多算**（非末尾 entry 是精确的），而它**漏算了整个最后一个 entry**（当成 0）。

```
267504  改前（最后一个 entry 记为 0）
267892  改后
267904  改后但故意用错 padding 常量
```
第三行是判据：差 **12 字节 = 3 条 `brk #0`**，说明 trim 循环真的在跑而不是被跳过。

⚠️ **这是「上界/未确立」这类保守说法本身也要复核的例子**：写下它时是诚实的，
但它同时掩盖了一个真 bug（最后一个 entry 被当成 0）。
**保守的措辞会让错误看起来像已知的不精确。**

### `WrapCode` 结构已明（2026-08-24），但**未实现**——它依赖 patch 加载链路

`WrapCode(CodePtr, long index, uint32 payload_info, uword payload_start, uint32&, uword&)` → `EntryPoints`，`:923`，
内联进 `ReadInstructions`。与 `WrapFunction` 同构，差别在它带真实的 `payload_info`（不是常数 0）。

已解出的部分：
- **长度算法**（`0x73aa5c..0x73aad4`）——已实现，见上一节
- **顶层闸门** `instructions_type_ != app` → 恒等函数指针（`0x733170` 是一条 `ret`）
- **非 app 分支上有一处自检**：`mach_vm_region(mach_task_self(), &addr, &size, flavor=9 /*VM_REGION_BASIC_INFO_64*/,
  info, &infoCnt=9, &object_name)`，随后查返回码与 `prot & 4`（VM_PROT_EXECUTE）——
  即「这段内存真的可执行吗」。是诊断，不是包装逻辑。
  ⚠️ 认出它靠的是**参数形状**（7 参 + x0 来自 `mach_task_self_` 这个 int 全局 + flavor/count 都是 9），
  不是符号——stub 走 GOT，名字没直接读出来。

**仍未确立**：两个出参的含义（很可能是「实际采用的 payload_info / payload_start」，即链接命中时用 base 的那一组，
但没有证据，**不写成事实**）。

**为什么这轮不实现**：忠实的 `WrapCode` 需要 `shorebird_base_instructions_table_` /
`shorebird_base_instructions_buffer_`，那是 patch 加载链路，我们还没有。只做包装那一半会是残缺的。

### ✅ 统计块已纳入自动检查（`c4b04f8`）

`PrintShorebirdStats` 上一轮落地时数字只被**手读过一次**。已加进 `dd_runtime_check.sh`：
不钉死字节数（会随编译器变），钉的是**结构 + 无 patch 时必然成立的不变量**（两个 Sim 数为 0、无 LinkOracle、
不带 flag 时静默）+ **一条跨源下界**：entry point 计数不得低于 identity dump 命名的函数数
（1380 ≥ 1043），因为该 dump 是 code 表的子集。`--self-test` 翻转 LinkOracle 期望。

### ✅✅ patch 加载链路的三个 C 入口已实现（2026-08-24，`b283033b4df`）

🔑 **最重要的一条：他们引擎的源码就在本机，且是与二进制匹配的那个 revision**
（`~/.shorebird/bin/cache/flutter/c2515c46.../engine/src`）。
patch 加载的**调用方全是开源的**，根本不需要逆向（规则 2）：

```
runtime/shorebird/patch_cache.cc:39     int off = Shorebird_ReadLinkHeader(buf, size);
                                        Dart_LoadELF(path, off, ...);
shell/common/shorebird/shorebird.cc:93  Shorebird_SetBaseSnapshots(iso_data, iso_instrs,
                                                                   vm_data, vm_instrs);
```

→ `.vmcode` = link header + 普通 ELF，`ReadLinkHeader` 的返回值就是 **ELF 起始偏移**；
所以「无 header 时返回 0」是正确的（0 会让它按普通 ELF 加载），不是错误码。

**这让 `LinkOracle::Install` 这个「我们的发明」退役了**。它当初被加进来是因为
「一个没人能填的单例没法测试」，并注明「他们的安装方尚未还原」。**现在还原了：就是 `Shorebird_ReadLinkHeader`。**
`Install` 保留为底层机制，但现在有真实调用方了。

`Shorebird_UsingLinking()`（`0x7ba16c`）= oracle 非空 **且** 两个 base-snapshot 全局非空。
那两个是文件级 static、无符号，认不出是哪两个 —— 但 `SetBaseSnapshots` 四个一起写，
所以「那两个」与「四个都」在运行期不可能分歧。代码里写的是这个理由，而不是随便挑两个。

他们该文件的其余内部件（尚未实现）：`BaseSnapshotInstructions` / `PatchSnapshotInstructions` /
`InBaseSnapshot` / `InPatchSnapshot` / `UnwrapEntryPoint` / `DebugPC`，以及
`shorebird_base_instructions_table_` / `_buffer_` 如何被填。

验证：86/86 shorebird 测试（新增 3 个）。两个负控制各自只抓自己的失效模式：
不安装 oracle → 2 红 1 绿；`SetBaseSnapshots` 忽略参数 → 只有 UsingLinking 红。

🔴 **一个流程教训（真的丢了代码）**：对**含未提交改动**的文件用 `git checkout <file>` 回滚负控制补丁，
会把实现一起丢掉 —— 本轮就这么丢了一次，只能重写。
**规矩：负控制之前先提交；回滚用打补丁的脚本，不用 `git checkout`。**
⚠️ 同一轮还连踩两次：负控制补丁触发 `-Werror` 导致构建失败，而 `&&` 链断掉后
**打印出来的红绿是陈旧二进制的结果**。判据必须是「先看 ninja exit，再跑测试」。

### ✅ 消除了 link header 的重复读取（2026-08-24，`ac76610139a`）

`Dart_ShorebirdLoadVmcode` 自己又解析了一遍 header（读计数 → 定缓冲 → `fromBuffer` → `Install`），
与新落地的 `Shorebird_ReadLinkHeader` 完全重叠。**而且两份上限互相矛盾**：
它封顶 65536 条，`LinkOracle` 封顶 `1<<24` —— 介于两者之间的文件在这里被拒、在那里被接受。
现在计数只用来定读取长度（那是文件 I/O），解析与安装一律委托。

**`Dart_ShorebirdLoadVmcode` 本身是我们的**（不在他们 DWARF 里、开源引擎也从不调用）。
保留的理由是 Simulator 需要文件路径，而 `Shorebird_ReadLinkHeader` 不接受路径。

⚠️ **它此前没有任何测试** —— 这正是那份重复解析能活下来的原因。已补两个（对真实磁盘文件）：
三条表能装入、空表能装入但报「无可链接」。
🔑 第一个断言返回 **true**，而 `#else` 分支只可能返回 false ——
**这一条同时证明了被编译进去的是 simulator 那个分支**，不需要额外的 `#error` 探针。

负控制：删掉委托那一行 → 两个新测试红、`ReadLinkHeaderInstallsTheOracle` 仍绿。
88/88 shorebird 测试。

⚠️ 本轮遵守了上一轮定下的规矩：**先提交再做负控制**，回滚用 `git checkout` 才是安全的。

### Deserializer 构造函数的完整参数表（2026-08-24）

mangled name 直接把参数表拼了出来
（`_ZN4dart12DeserializerC4EPNS_6ThreadENS_8Snapshot4KindEPKhlS6_S6_bNS0_16InstructionsTypeElRKNS_17InstructionsTableES6_`）：

```cpp
Deserializer(Thread*, Snapshot::Kind, const uint8_t* buffer, intptr_t size,
             const uint8_t* data_buffer, const uint8_t* instructions_buffer,
             bool is_non_root_unit, InstructionsType instructions_type,
             intptr_t offset,
             const InstructionsTable& base_instructions_table,  // → +0xc8
             const uint8_t* base_instructions_buffer);          // → +0xd0
```

🔑 我们上一轮把 `instructions_type` 插在 `is_non_root_unit` 之后、`offset` 之前 —— **位置与他们完全一致**（独立印证）。
→ 那两个 base 字段是**构造参数**，不是运行期赋值。剩余工作是**从 base 快照建出一张 `InstructionsTable`**。

⚠️ 另有一个短构造函数 `(Thread*, const uint8_t*, long, const uint8_t*, const uint8_t*, long)`，用途未确立。

### ✅ CLAUDE.md 已按实测订正（2026-08-24，`4052149`）

两个问题一起修：**受控副本（research）比 v1 里那份未跟踪的更旧**（还写着 22–28%）——
与 memory 早先那次分叉同型，说明「改了工作树副本、没同步回受控分支」这个模式**会重复发生**。
另外六处论断被本会话证伪：`print_shorebird_info` 只被阻塞一半、CPU→Sim body 不是占位符、
`AllocateMetadata()` 已有生产调用点、DD core 那三句「不能跑/量不到/没测试」全部作废。

第三条限定**改写而非修补**：从「几乎没有东西被执行过」翻成「主链路都在跑」，
但保留了仍然成立的部分（真机零实测、全部是 host 的 simulator 构建），
并写明**每条结果都有「改坏看变红」的对照** —— 只有正向结果时，「跑对了」和「被绕过了」分不开。

百分比 30–36% → **36–42%**，并注明**上调的主要不是新面积，而是既有部分被接上并跑通**。

### ✅ base 指令范围已写入（2026-08-24，`03bc51a3938`）

`Thread::base_instructions_entry_point_` / `base_instructions_end_` 自移植以来
**有 getter/setter/offset getter，却从没有任何地方写过** —— 又一个死字段。
现在由 `SetupDartMutatorStateDependingOnSnapshot` 写入（与 dispatch table、DD 表并列）。

两个边界**只需要 instructions 镜像**（上游 `GetBareInstructionsAt(0)` 就是 buffer 本身、
`GetBareInstructionsEnd` 只需一个 `Image`），不需要 ImageReader、不需要 data 镜像。
`BaseSnapshotInstructions` 是他们的名字（`runtime/vm/shorebird.cc:161`）。

### 「从 base 快照建 InstructionsTable」的路径已探明（尚未实现）

`InstructionsTable::New(len, start_pc, end_pc, rodata)` 的四个输入全部来自快照自己的头，
而头很紧凑 —— `Deserializer::Deserialize()` 开头五个 varint：
`num_base_objects_ / num_objects_ / num_clusters_ / instructions_table_len / instruction_table_data_offset`。

🔑 **这解释了他们那个短构造函数** `Deserializer(Thread*, const uint8_t*, long, const uint8_t*, const uint8_t*, long)`
——没有 Kind、没有 InstructionsType、没有 base 参数，**正是一个只用来读 base 快照头部的精简 Deserializer**。
（此前记为「用途未确立」。）

剩余工作：用它读出 base 的 `instructions_table_len` 与 `instruction_table_data_offset`，
配合 base 的 data/instructions 镜像建 ImageReader，再 `InstructionsTable::New`。

### ✅✅ base 快照的 InstructionsTable 已建出来（2026-08-24，`60cec3c40c2`）——Task 9 收尾

Deserializer 的 Shorebird 面里最后一个「有名字没实现」的部分。
patch 会**替换** app 快照，所以 base 只以裸映射存在，没人反序列化过它，也就没有现成的 InstructionsTable。

`InstructionsTable::New(len, start_pc, end_pc, rodata)` 的四个输入全在 base 自己的头里，
而那个头就是 clustered stream 开头的**五个 varint**（与 `Deserialize()` 读的是同一组）。
🔑 **他们那个短构造函数就是干这个的**——`(Thread*, buffer, size, data, instructions, offset)`，
没有 Kind、没有 InstructionsType、没有 base 参数，**一个只读头的 reader**。（两轮前记为「用途未确立」。）

Deserializer 现在按他们长构造函数的参数表收下那两个 base 参数，
`ReadProgramSnapshot` 供给它们，`PrintShorebirdStats` 报真实状态而不是写死的 "no"。

**两种验证**：
- **null 路径**（每个未打补丁的 app 都走这条）端到端跑通，是常设回归覆盖的
- **非 null 路径没有 embedder 可用**（`dartaotruntime` 从不调 `Shorebird_SetBaseSnapshots`，那是 Flutter shell 的事），
  所以**强制走了一次**：把 app 自己的快照当 base 喂进去 → `Has shorebird base instructions table: yes`，
  说明 `SetupFromBuffer` / 版本校验 / 五个 varint / `ImageReader` / `InstructionsTable::New`
  在真实快照上全部走通，且程序仍输出正确。

⚠️ **那是实验不是常设回归**（任务 #10）。给 `dartaotruntime` 加个 flag 来测它属于**发明 API**，不是复刻。
这条要写清楚，否则下一轮很容易把「实验验证过」记成「有测试守着」。

### base 头部解析已可在任意构建下测试（2026-08-24，`d6ef8730582`）

`ReadBaseInstructionsTable` 整体在 `#if defined(DART_PRECOMPILED_RUNTIME)` 里
（末尾的镜像访问器是 precompiled-only）。**那个 guard 同时挡住了最容易写错的部分**
——五个 varint 的顺序与流的起点——因为 `run_vm_tests` 是 precompiler 构建，一行都没编译。
（这正是上一轮记的第 17 种陷阱。）

已拆分：头部那半 `ReadBaseSnapshotHeader()` 任何构建都能跑，镜像那半仍受 guard。

⚠️ **两个测试写法上的教训**：
1. 第一版写的是 `if (ok) { ... }` —— **无论 ok 是真是假都会通过，等于没测**。
   先探针测出实际值（本二进制是 JIT 快照，不声明 instructions table，所以解析在**长度处**退出），再写成明确断言。
2. 光断言「退出了」还不够：**分不清「版本校验通过但没有表」与「版本校验没过」**——
   两者返回值相同、含义天差地别。所以测试单独再验一次版本校验通过且 offset > 0。

负控制：少读一个 varint → 真实快照那个测试红、garbage 那个仍绿。

⚠️ **这没有关闭上一条记的缺口**：`ReadBaseInstructionsTable` 的**非空路径**在这棵树里仍无 embedder，
仍然只被一次性实验验证过（任务 #10）。

### ✅ 三个 group 级 pc 查询已实现（2026-08-24，`723a32c8221`）

签名来自引擎 dSYM，而且**位置与文件布局的暗示不同**——三个都声明在 **`isolate.h`**，不是 `shorebird.cc`：

```cpp
bool InBaseSnapshot(IsolateGroup*, uword);            // isolate.h:393
bool InPatchSnapshot(IsolateGroup*, uword);           // isolate.h:394
bool UnwrapEntryPoint(IsolateGroup*, uword, uword&);  // isolate.h:865
```

⚠️ **订正**：此前记 `UnwrapEntryPoint` 返回 `uword`。**它返回 `bool` 带出参** ——
就是 `WrapperAllocator::ContainsEntryPoint` 提升到 group 层、两个方向都问一遍。
那个返回 uword 的是**另一个同名符号**（`shorebird.cc:37`），别混。

给 `IsolateGroup` 加了**不创建**的 allocator 取值器，查询走那一对：
创建式的会为了回答「不是」而映射页，而这个查询大多数时候问的正是不是 wrapper 的地址。

测试的着眼点：pc 那个检查**两个镜像是分开回答的**（没设 base 时，一个确实在 patch 里的 pc
仍然不在 base 里 —— 两个查询问的是不同镜像，不是互补关系）；unwrap 那个两个方向各跑一次往返，
并验证普通整数被拒。

负控制各自只抓自己：把 `InBaseSnapshot` 改成答 patch 镜像 → 只有 pc 测试红；
去掉 `UnwrapEntryPoint` 的 sim→cpu 那一支 → 只有 unwrap 测试红。

### 🔴 `WrapCode` 停止尝试（第 4 次，按规则 4）——**理由要写清楚，不然下轮会再试一遍**

它**只有内联副本**，range 为 `0x73aa5c-aa98 / aa9c-ae54 / aeec-b0c4 / b0ec-b154`（约 1588 字节）。
签名 `(CodePtr, long, uint32 payload_info, uword payload_start, uint32&, uword&)` → `EntryPoints`。

**卡点不是「没读懂」，是「读不到」**：两个出参在内联后与 `ReadInstructions` 的局部变量**无从区分**
——编译器把它们优化没了。我能写出一个自洽的形状（命中→用 base 的 payload、否则用 patch 的），
但「base 侧的 `payload_info` 从哪来」这类细节仍属发明。

⚠️ 本轮还纠正了自己上一轮的一处误读：那个 7 参外部调用**不是** WrapCode 的出参写入，
是 `mach_vm_region`。

**解锁条件**（下次要么满足其一，要么别再试）：
1. 找到未内联的副本（他们其他平台/配置的产物）
2. 用**行为差分**反推（同 [[reference-differential-flag-oracle]]）——但这需要真实 `.vmcode`
   **和一个能装载它的 embedder**，后者正是任务 #10 缺的那个

已完成的相邻部分（不受此阻塞）：Deserializer 两个未名字段全部命名、`Stats`+`PrintShorebirdStats`、
长度算法（含 `brk #0` padding trim）、三个 group 级 pc 查询。

### ✅ 四个校验合并为一个入口（`8406244`）

`verify_all.sh`：reproduction / dd_pass / dd_runtime / 单测。四个此前要分别手动跑
——**这正是某个校验悄悄不再被跑的方式**。

🔑 值得留的是**跳过的记账**：缺二进制记为 SKIPPED 并**让整体失败**，
因为没跑的校验什么都不证明，而它的沉默读起来和成功一模一样。
「模式内的预期跳过」单独计数，所以 `--self-test` 不会因为故意不跑单测而失败，
而真的缺构建仍然会。三种情形都实测过（全绿 exit 0 / self-test exit 0 / PRODUCT 指向不存在 exit 1）。

### 📊 重测（2026-08-24，本会话结束前）：DD core 不再是零，剩下的零只有映射器

按 CLAUDE.md 规则 0「完成度以实测为准」重跑符号对比（两边 `nm -a | c++filt | sort -u`，
他们先 `lipo -thin arm64`，我们用 product 构建）。总数：他们 32373 / 我们 **33866**（上次 33714）。

| 标志（去重方法名） | 他们 | 我们 | |
|---|---:|---:|---|
| `ShorebirdLinker::` | 20 | 20 | 持平 |
| **`IndirectStaticCallInstr::`** | **19** | **20** | **持平**（`comm -23` 为空；多出的是我们的 `FromCall`）|
| `DDTableBuilder` | 8 | 8 | 持平 |
| `DDSlotMapping::` | 2 | 2 | 持平 |
| **`ObjectPoolMappings`** | **8** | **0** | **唯一剩下的零** |

🔴 **但那个「8」是同一种幻觉——第 6 次了**：
- 4 个是 `__introsort`/`__sort3`/`__sort5`/`__insertion_sort_incomplete` 对
  **`GetBestMapping` 内一个 lambda** 的实例化（std::sort 样板）
- 1 个是 `ObjectPoolEditor::InstructionCountNoPadding`
- 其余 3 个是重复的 nm 行

⚠️ **`GetBestMapping` 本身连独立符号都没有** —— 只有它的比较器 lambda 借 sort 实例化活了下来。
README 此前记「nm 只剩 GetBestMapping 与 InstructionCountNoPadding 两个符号」，**比实际更乐观**。

🔑 **但这些实例化给出了三阶段映射的第一条算法证据**（此前只有六个计数）：
比较器排序的是 **`std::pair<unsigned long, double>`** ——
**候选带 double 分数，打分后取最优**。所以各阶段的输出是「(候选, 分数)」而不是「是/否匹配」。
这是对任何重建方案的实质约束。

### 🔑 三阶段映射有实质进展了（2026-08-24，`45e94243ce9`）——文件名 + 第一个函数

从上一节那条新证据（比较器排序 `pair<unsigned long, double>`）顺藤摸到
`ObjectPoolEditor::InstructionCountNoPadding`（`0x1001a2b54`，唯一有独立符号的映射器函数）。

**它的 FATAL 串给出了文件名**：**`runtime/vm/shorebird/object_pool_editor.cc`**，行号 **525**。
→ 三阶段映射器住在这个文件里，且至少 525 行。这是复刻的目标文件。

**函数本身已解**：把 pool 条目**索引**换算成字节偏移（`index*8 + 0x10`），
再按 op kind（1..6）判断材料化它要几条指令；kind 4/5/6 分别用 OperandSize 7/8/11、
`AddressType=0`，然后调
**`compiler::Assembler::InstructionCountForLoadStoreFromOffset(int, OperandSize, Address::AddressType)`**
——**我们没有这个函数，它是 Shorebird 加到 assembler 上的**。已实现。

🔑 **它揭示了映射器为什么需要这个**：编辑器要判断「把某个 pool 条目挪位置，会不会改变读它那些点的代码尺寸」
——仍是一条指令就能自由挪，变成两三条就不能。这也解释了
`Sorted ObjectPool, moved 0 of 1421 entries` 那行。

**实现方式：真汇编一遍再数，不手写规则。** `PrepareLargeOffset` 在三种情形间选择，
而 `LoadImmediate` 本身是长度随位模式变化的 movz/movk 串；手写一份计数就是同一套规则的第二份实现，
任一侧一改就会漂移。他们的分支结构与我们实测吻合（8 字节时 <32768 返回 1，正是
`Address::CanHoldOffset` 的 12 位缩放范围）。

⚠️ **它需要当前线程**（`AssemblerBase` 是 `StackResource`）。这是**段错误**发现的：
第一版测试用了 `VM_UNIT_TEST_CASE`（无 isolate），构造 Assembler 直接空指针解引用。
现已加断言，测试改用 `ISOLATE_UNIT_TEST_CASE`。
**教训：构造 VM 对象的「纯函数」往往并不纯。**

测试对照的是**汇编器实际发射的条数**而不是一张期望值表 —— 表会是同一套规则的第三份copy。
负控制：把 `+1` 改成 `+2` → 变红。95/95。

### 🗺 `object_pool_editor.cc` 已测绘（2026-08-24）——四个函数、职责清楚

用 `adrp_scan.py` 扫谁材料化了该文件的名字串（`0x1004bfd5e`，每处 FATAL 都会引用它），得到全部函数：

| 函数 | 地址 | 大小 | 职责 |
|---|---|---:|---|
| `dart::DetectObjectPoolOp(uword, ObjectPoolOp&, uword, int*)` | `0x1001a2720` | 884 B | 把某处指令序列**识别**成一个 pool 操作 |
| `dart::LoadStoreFromSingle(Instr const&, uint32)`（static） | `0x1001a2a94` | 192 B | 解码单条指令 → `(index, kind)` |
| `ObjectPoolEditor::InstructionCountNoPadding(ObjectPoolOp const&)` | `0x1001a2b54` | 420 B | 代价（已解出，**未实现**） |
| `dart::AssembleReplacement(Assembler*, ObjectPoolOp const&, uword)`（static） | `0x1001a2de8` | 1016 B | 按新偏移**重新发射** |

🔑 **编辑器做什么，至此清楚了**：识别代码里的 object-pool 加载序列 → 算它的指令代价 →
在新偏移处重新汇编。这正是「挪动 pool 条目而不改变代码尺寸」所需的全部机器，
也解释了 `Sorted ObjectPool, moved 0 of 1421 entries`。

**`LoadStoreFromSingle` 已解**（返回 `(index, kind)` 一对）：
```
if (!bit26)  kind = (w & 0x400000) ? 1 : 2;                  // 整数
else switch (w >> 30) { 0→6; 1→FATAL(:51); 3→5; default→4; } // 浮点
index = ((arg-1) < 15 ? (arg-1)-8 : (arg-1)-15) >> 3
```

🔑 **两个独立解码互相印证**：这里产出的 kind 集合 **{1,2,4,5,6}**
正是 `InstructionCountNoPadding` switch 的那组（4/5/6 → OperandSize 7/8/11）。
kind 3 走别的识别路径。

⚠️ **`arg` 的语义刻意不命名**：那个 `-8`/`-15` 二分支没有调用点证据。
（同 `0xc8` 猜对 / `0xd8` 猜错那条教训。）

**下一步**：`DetectObjectPoolOp`（884 B，外部符号、是入口）。
它填 `ObjectPoolOp`，所以解它同时能给出那个 struct 的形状 —— 其余三个函数都收它。

### 🔑 `ObjectPoolOp` 的形状已确立（2026-08-24）——三处独立解码互相印证

`DetectObjectPoolOp`（`0x1001a2720`，884 B）**只往那个 out 引用写两处**：
```
str x0, [x1]        // 偏移 0，8 字节
str w8, [x1, #0x8]  // 偏移 8，4 字节
```
→ **`struct ObjectPoolOp { int64 <index>; int32 kind; }`**（12 字节，多半补齐到 16）。

**三处独立证据一致**：
1. `DetectObjectPoolOp` 写这两个偏移
2. `LoadStoreFromSingle` 正好返回 `(long, int)` 一对
3. `InstructionCountNoPadding` 被 IPA-SROA 标量化成 `(x0=long, w1=int)` —— 正是两字段结构的拆解

**检测逻辑的开头已解**：
```
w = *(uint32*)pc
if ((w & 0x3a000000)==0x38000000 && (w & 0x04400000)==0x04000000) {
    if ((w & 0xfb400000) != 0xa9400000) fail;   // 0xa9400000 = LDP 64 位有符号偏移
    Rn = (w>>5)&0x1f;
    if (Rn == 27) → kind 3      // 27 = PP，直接从对象池加载
    else if (Rn == 16) → 多指令形式  // 16 = IP0/TMP，说明前面有一条 add
    else fail
}
```

🔑 **第四处印证，而且是可计算的**：kind 3 = 从 PP 的 LDP，
而 `InstructionCountNoPadding` 的 kind-3 分支限值是 **512**。
用**我们自己的**源码算：`Address::CanHoldOffset(PairOffset, kEightBytes)` 是 `IsInt(7+3, offset)`
→ `[-512, 511]`。**逐值吻合** —— 这是算出来的，不是「看起来像」。

**至此 op 模型完整**：
| kind | 形态 | 代价判据 |
|---|---|---|
| 1, 2 | 整数 LDR 两种变体 | offset < 32768（12 位缩放） |
| 3 | 从 PP 的 LDP | offset ∈ [-512,511]（7 位缩放对） |
| 4, 5, 6 | 浮点，OperandSize 7/8/11 | 走 `InstructionCountForLoadStoreFromOffset` |
| Rn=27 / Rn=16 | 直接 / add 之后 | 决定 1 条还是 2–3 条 |

**未解**：`DetectObjectPoolOp` 余下约 178 条指令（其他 kind 的识别分支）、
`AssembleReplacement`（1016 B）、以及三阶段映射本身。

### 🔑 `Assembler::PadLoadStore` 已完整解出（2026-08-25）——三阶段映射的「无证据」判决对编辑器那半失效

`AssembleReplacement`（`0x1001a2de8`，1016 B）的反汇编指向最后一块拼图：

```
dart::compiler::Assembler::PadLoadStore(std::__fl::function<void()>, Register,
                                        int, OperandSize, Address::AddressType)  @ 0x10024b2e8
```

**我们树里 `PadLoadStore` 出现 0 次**（实测 `grep -rn PadLoadStore runtime/` = 0）——
又一个 Shorebird 加到 arm64 汇编器上的方法，且是我们已实现的
`InstructionCountForLoadStoreFromOffset` 的**对偶**（一个算代价、一个真发射并补齐）。

**🔑 它的两条 assert 直接交出文件、行号、条件串**（从 `__TEXT` 读出）：

```
0x1004c8e84  ../../flutter/third_party/dart/runtime/vm/compiler/assembler/assembler_arm64.cc
0x1004c8f13  num_added_instrs == expected_instr_count                                  (行 1316)
0x1004c8f3c  (after_code_size - before_code_size)
             <= Assembler::kObjectPoolLoadStoreMinInstructionCount * Instr::kInstrSize (行 1322)
```

→ 它住在**上游的 `assembler_arm64.cc`**，不在私有文件里，约 1310–1322 行。
→ 并且暴露出一个我们没有的常量名：**`Assembler::kObjectPoolLoadStoreMinInstructionCount`**。

**它的值是算出来的，不是猜的 —— 两处独立钉住 = 3**：
- `0x10024b384`：`cmp x0, #0x3`，与 `InstructionCountForLoadStoreFromOffset` 的返回比
- `0x10024b398`：`cmp x8, #0xd` / `b.ge` 进 1322 那条失败，即 `bytes_added <= 12`；
  `Instr::kInstrSize == 4` → `3 * 4`

**函数体已还原**（`x19`=this、`w23`=base、`x22`=offset、`x21`=OperandSize、`x20`=AddressType；
`Assembler+0x20`/`+0x28` 是 buffer 的 base 与 cursor，发射前后相减时 base 项正好抵消）：

```cpp
const intptr_t before = buffer_.Size();
emit();
ASSERT((buffer_.Size() - before) / Instr::kInstrSize ==
       InstructionCountForLoadStoreFromOffset(offset, sz, addr_type));
if (base == PP) {                       // ⚠️ 只在 PP 上补齐
  intptr_t count = InstructionCountForLoadStoreFromOffset(offset, sz, addr_type);
  while (count < kObjectPoolLoadStoreMinInstructionCount) { Emit(NOP); count++; }
}
ASSERT((buffer_.Size() - before) <=
       kObjectPoolLoadStoreMinInstructionCount * Instr::kInstrSize);
```

**两个签名看不出、必须记下的细节**：
1. 填充值 `0x10024b3d8` 的 `movz #0x201f`/`movk #0xd503,lsl#16` = `0xd503201f` = **NOP**，
   不是断点也不是 0。
2. 循环退出判据是 `eor x21, x20` / `cmp #3` —— **异或不是加**。
   在唯一可达的定义域（expected ∈ {1,2}、emitted ∈ {1,2}）上没有进位，异或与加相等，
   所以它是编译器对 `emitted + expected == 3` 的编码。
   ⚠️ **照抄那个异或就是抄优化产物而不是算法**。

**🔑 两个函数的名字至此互相解释**：`InstructionCountNoPadding` 答「这条 pool 加载现在要几条指令」，
`PadLoadStore` 让**每条 pool 加载都占满 3 条指令的固定尺寸**。
这正是「挪动 pool 条目而周围代码尺寸不变」所需的不变量，也是
`Sorted ObjectPool, moved 0 of 1421 entries` 背后的机器。
⚠️ 有闸门：**只有 `base == PP` 才补齐**；走 `IP0`/`TMP` 的多指令形式
（`DetectObjectPoolOp` 用 `Rn == 16` 识别的那种）不补。

**⚠️ 为什么还没写进树里**：它唯一的调用方是尚未解出的 `AssembleReplacement`。
单独落地就是加一个没人调用的函数——本目录已经记过死代码的代价：
`AllocateMetadata()` 在符号表说「子系统存在」的同时，好几周没有生产调用点。
两个一起进，用 `AssembleReplacement` 当调用点。

**订正 2026-08-24 的记录**：那天写的「目前证据不足以按规则 3 实现三阶段映射」
对**聚合器**（三个阶段本身）仍然成立，对**编辑器**已经失效——
文件名、四个函数、`ObjectPoolOp` 布局、`PadLoadStore` 全文都已拿到。
当时同时写了「解锁路径是反汇编」，那句是对的。

### 🔴 记账错误订正（2026-08-25 实测）：`object_pool_editor.cc` 我们一个函数都没实现

回答「完成度多少」时按规则 0 重测符号，发现
`InstructionCountForLoadStoreFromOffset` 在我们 `gen_snapshot` 里是 **0**，
而我们上一轮明明实现了它。查清楚了，两件事都要记：

**(a) 那个 0 是真的，但不代表没实现**（第 4 / 第 17 种陷阱的又一次）：
```
run_vm_tests  : 6 个符号   ← 实现在这里，被单测调用
gen_snapshot  : 0 个符号   ← 没有生产调用点，所以不进产物
```
源码确实在 `assembler_arm64.cc:1043` / `.h:1885`。**「产物里没有」≠「没写」**。

**(b) 更要紧的：表里「`InstructionCountNoPadding` 已实现」是错的。**
我们实现的是**上游 assembler 里的辅助函数** `InstructionCountForLoadStoreFromOffset`，
不是 **`ObjectPoolEditor::InstructionCountNoPadding`**。后者
`grep -rn InstructionCountNoPadding runtime/` 只有 1 处命中，还是**注释**。

→ **`object_pool_editor.cc` 的四个函数，我们实现了 0 个。**
→ `ObjectPoolMappings` 8 vs 0 仍是完整的零，一点没动。

⚠️ **这个错误是怎么进来的**：`45e94243ce9` 的提交信息是正确的（写的是 assembler 那个名字），
但转抄进「四个函数」那张表时，落到了**它服务的那一行**上。
**两个名字长得像、处在调用关系的两端，抄表时最容易并成一行。**

✅ 判据：说某函数「已实现」之前，`grep -rn '<确切的类名::方法名>' runtime/` 一次。
类名前缀（`ObjectPoolEditor::`）就是区分这两者的东西。

### ✅✅ `ObjectPoolLinkInfo` 格式已关闭（2026-08-25，`26b5e5ed6c7`）——两份产物逐字节重现

**🔑 方法上的教训比结果更值钱**：本文件长期记着「映射器类型不在引擎 dSYM 里」，
当时查的是三个名字（`ObjectPoolMappingsAggregator` / `ObjectPoolEditor` /
`InstructionCountNoPadding`），**这三个至今仍然不在**。
**从没查过的是它们下面那一层**——`link_info.h` 自己的类型**全在**那份 DWARF 里，
带偏移和声明行号：

| 类型 | 声明行 | 大小 | 字段 |
|---|---:|---:|---|
| `Sha256Hash` | :18 | 0x18 | `std::string value_` @0x00 (:29) |
| `CodeInfo` | :48 | 0x60 | `self_hash_`@0x00(:74)、`op_subgraph_hash_`@0x18(:80)、`self_pp_indices_`@0x30(:85)、`subgraph_pp_indices_`@0x48(:90) |
| `ClassInfo` | :93 | 0x38 | `class_id_`@0x00(:107)、`class_name_`@0x08(:110)、`class_hash_`@0x20(:113) |
| `IntervalInfo` | :141 | 0x10 | `start_`@0x00(:153)、`end_`@0x08(:156) |
| `SelectorRowInfo` | :162 | 0x38 | `offset_`@0x00(:179)、`hash_`@0x08(:182)、`ranges_`@0x20(:185) |

每个都有 `ReadFromStream`/`WriteToStream`/逐字段访问器。
**ctor 的 mangling 决定哪些名字是 typedef**：`ClassInfo(int, std::string, std::string)`、
`CodeInfo(std::string, std::string, vector<ulong>, vector<ulong>)`
→ `ClassName`/`ClassHash`/`SelfHash`/`SubgraphHash` 都是 `std::string`；
而 `SelectorRowInfo(int, const Sha256Hash&, const vector<IntervalInfo>&)`
→ `SelectorHash` 真的是那个类。**这个不对称是他们的，不是抄错。**

**格式（两份产物逐字节重现，193312 / 193325 字节）**：
```
unsigned count = 1380
count × CodeInfo（按声明顺序）
unsigned 385
385 × unsigned   递增的 pool 索引
unsigned 1421    整个 pool 的条目数
```
🔑 三阶段报告的 `1113 + 292 + 16` **恰好 = 1421**。

⚠️ **判据必须是「解码→重编码→逐字节比」，不能只是「解析到 EOF」**：
少读一个字段 + 少写同一个字段会互相抵消，照样停在最后一字节。
`op_link_info_check.sh --self-test` 丢掉 `subgraph_pp_indices_`，两份文件都在第 463 字节起分叉。

⚠️ **两处刻意留粗糙**（都是 `0xd8` 那条教训）：
1. `Sha256Hash` 是他们的名字，但每个值都是 **40 个十六进制字符 = SHA-1 宽度**，不是 SHA-256。
   他们的类不校验宽度，我们也不校验。
2. **385 个索引的含义未确立**。实测：递增、base 与 patch 完全相同、是记录引用的 1126 个索引的真子集；
   但 `all-self` / `all-subgraph` / `all-either`（后者只有 295 个）**三个假设全部证伪**。
   → 用描述性名字，不用解释性名字。

⚠️ 单测只能证明 reader 与 writer 互逆——**同一个猜测的两半和真相的两半一样自洽**。
外部裁判只能是他们的产物，而他们的产物**不能入库**（origin 公开），所以裁判放在 spike 里。

### 🔑 三阶段映射就在那两个 `Initialize*LinkInfo` 里（2026-08-25）

用 `adrp_scan.py` 查谁材料化报告串，得到两个函数——**并且报告是四行不是三行**：
```
0x1004bff11  Link Results %zu
0x1004bff23  Mappings from Link Results %zu      ← 「六个计数」那句漏了这一行
0x1004bff43  Mappings from Pair Constraints %zu
0x1004bff67  Mappings from Backfill %zu
```
`ShorebirdLinker::InitializeWithClassTableLinkInfo`（`0x100199928`，**4320 B**）与
`InitializeWithObjectPoolLinkInfo`（`0x10019bd8c`，**8184 B**）**都打这四行**。
→ **三个阶段被内联进这两个函数**，这也解释了 `GetBestMapping` 为什么没有自己的符号。

**第五个私有文件名**：`runtime/vm/shorebird/class_table_mapper.cc`
（来自一个 FATAL，旁边是 `Duplicate index: %zu` 诊断串）。

**类表那一趟的外联 helper 交出了真正的算法结构**（比六个计数器强得多）：
- `unordered_map<std::string, vector<ClassInfo>>` —— 按名字分组
- `vector<LinkedValue<ClassInfo>>` 与 `vector<LinkedValue<unsigned long>>`
  —— **`LinkedValue<T>` 模板，我们没有，DWARF 里也没有**
- 两个 `vector<bool>::resize(n,false)` —— 每侧一张 taken 位图
- `std::set<long>`、字符串键走 `__murmur2_or_cityhash`

**下一步**：反汇编这两个函数（4320 B 的类表那个先做，它更小且同样打四行）。

### 🔴 `WrapCode`：解锁条件 1 已被**穷尽排除**（2026-08-25）——不是「没找到」，是「不存在」

上一轮按规则 4 停止时写了两个解锁条件。今天 `link_info.h` 的收获来自引擎 dSYM，
所以先回头验条件 1（「找到未内联的副本」）。**验完了，条件 1 永久关闭。**

**查了本机全部 Shorebird 产物**，不是只查那一个 release 二进制：
两个 Flutter revision（`c2515c46…` / `c15ef637…`）×
{`ios`, `ios-profile`, `ios-release`, `darwin-x64`, `darwin-x64-profile`, `darwin-x64-release`} ×
{`Flutter` framework, `gen_snapshot_arm64/x64`, `analyze_snapshot`}
—— `nm -a | c++filt | grep Deserializer::WrapCode` **全部为 0**。
连 debug / profile 构建都没有外联副本。

**两份 dSYM 也都查了**（iOS arm64 + macOS 的 x64/arm64 两个 slice）：
`WrapCode` 只有 `DW_TAG_subprogram` + `DW_AT_declaration(true)`，
形参**只有类型没有名字**，也没有任何 `DW_TAG_inlined_subroutine` 引用它。

→ **DWARF 给不出那两个出参的名字，而「读不到出参」正是唯一的卡点。**
（对照：同一份 DWARF 今天交出了 `link_info.h` 全部类型和 `LinkOracle` 整份头文件——
所以这不是「dSYM 没用」，是**这一个函数**恰好只有声明。）

**剩下的唯一解锁条件是原来的第 2 条**：用真实 `.vmcode` 做行为差分，
而它需要一个会调 `Shorebird_SetBaseSnapshots` 的 embedder。
⚠️ 上一轮把这条记成「任务 #10 缺的那个」是**记错了**：任务 #10 是测试覆盖，已完成（`efa07a3774e`），
它并没有、也不该引入 embedder。**给 `dartaotruntime` 加 flag 去装 base 属于发明 API，不做。**

✅ **方法论**：否定性结论要和肯定性结论一样验证。上一轮说的是「只有内联副本」，
证据只有一个二进制；这一轮把同一句话验成了「全部 12 个产物 + 2 份 dSYM 都没有」。
**前者是猜，后者是结论。**

### ✅✅ `WrapCode` 已实现（2026-08-25，`1076a3598b6`）——卡了四轮，用第三条路解开

**不是**上一轮写的两个解锁条件中的任何一个（都没满足）。是第三条：
**DWARF 的 `DW_AT_call_line`**，方法见 [[reference-dwarf-inline-call-lines]]。

内联不丢行号归属。把 `WrapCode` 地址范围内每条 `DW_TAG_inlined_subroutine` 的
`(abstract_origin, call_line, ranges)` 取出来按行排序，1588 字节的盲读变成逐行清单：

```
:929 InstructionsLengthAt   :935 ASSERT(IsExecutable)   :936 返回 identity
:941 IsLinkingEnabled       :942 ASSERT                 :944/:945 只包装
:950 RunTargetForPatchIndex :951 WrapperForRunTarget    :952 Stats::Record
:955 EntryPointForOffset    :958 AssertInstructionMatch
:959 FindEntry              :967 rodata  :969 SetCodeAt  :970/:972 返回
```
**四个 `EntryPoints::Code` 返回点 = 四条路径。**

**有了地址区间，反汇编就是定点的**（0x73aeec–0x73b0c4，180 字节）：
- `0x73af24  add x23, x9, x10` = `base_start_pc + offset`（:955）
- `0x73af28  ldr w11,[x23]; ldr w12,[x21]; cmp` = **`AssertInstructionMatch` 只比一个指令字**（:958），
  失败进 `0x73b124` 的 assert（:919）。**不是比整个函数体——他们根本没传长度。**
- `0x73af38..0x73afac` = `ContainsPc` + 对 `entries()[i].pc_offset` 的二分 = `FindEntry`（:959）
- `0x73afb4  sub x9, x9, first_entry_with_code` → `0x73afd4 SetCodeAt`（:967/:969）
- 🔑 **`0x73b078  mov x1, x23`** → `EntryPoints::Code(x23, wrapper, payload_info)`
  —— **返回的 EntryPoints 用的是 base 的地址，不是 patch 的**。这就是 linking 的全部意义。

🔑 **`SetCodeAt` 出现两次**：`:969` 在 **base** 表上，`:10225` 在 patch 表上（调用方里）。
**不是同一个调用。** base 表那次是为了让「按 base 地址查 Code」在打补丁后仍然成立。

**顺带还原了调用方**：`WrapCode` 自己那条内联记录的 `call_line=10214`
直接指出 `ReadInstructions` 在哪调它，于是 `:10204/:10205/:10208/:10214/:10225/:10227`
与我们的 9924–9958 **一一对应**。

**同时落地两个上游类的 Shorebird 增补**（由同一批记录点名）：
`InstructionsTable::EntryPointForOffset`（:955）与 `InstructionsLengthAt`（:929，
把原先内联在 ReadInstructions 里的长度计算搬到他们放它的地方）。

⚠️ **一处刻意偏差，已在头文件标注**：他们的签名有 `uint32_t&` / `uword&` 两个出参，**我们没有**。
两份 dSYM 都不给形参名字，本机 12 个产物没有外联副本，优化后那两个写与调用方局部变量无从区分。
我们的调用方自己算得出它需要的东西。**编一个自洽的解释就是规则 3 明令禁止的自由发挥。**

⚠️ **构建配置**：改的是 `#if defined(DART_PRECOMPILED_RUNTIME)` 里的代码
→ 必须用 `ninja -C ProductARM64 dartaotruntime` 验（第 17 种陷阱）。

**负控制**（重构后全绿可能只是新代码没被走到）：非 linking 路径返回 `payload_start + 4`
→ `dd_runtime_check` 5 处失败。**`WrapCode` 对全部 1380 个 entry point 都在真跑。**
用反向补丁还原。102 单测 / verify_all 5 ran 0 failed。

**仍未实现**：linked 路径本身在这棵树里跑不到（需要 base + LinkOracle 同时就位，
即一个会调 `Shorebird_SetBaseSnapshots` 的 embedder）。代码在，路径未被执行过——
**这一条要写清楚，别读成「linked 路径验证过了」。**

### 🔑 `LinkedValue<T>` 已确立 = base/patch 对（2026-08-25）+ 内联行号法**够不到映射器**

**先说否定的那一半，它同样重要**：解开 `WrapCode` 的 `DW_AT_call_line` 方法
（[[reference-dwarf-inline-call-lines]]）**用不到映射器上**。实测：
`ShorebirdLinker` / `ObjectPoolMappings` / `class_table_mapper` / `GetBestMapping`
在引擎 DWARF 里**全部 0 命中**，引擎二进制里 `ShorebirdLinker` 符号也是 **0**。
→ **linker 只在 gen_snapshot 里，而 gen_snapshot 没有 dSYM。**
**这才是映射器比 `WrapCode` 难的结构性原因，不是「还没花力气」。** 别在这儿重试那个方法。

**肯定的那一半是算出来的**：两个 `Initialize*LinkInfo` 都把 `Link Results` 当
`vector::size()` 打印，而 libc++ 的精确除法会把元素大小暴露在常数里。

类表 `0x10019a75c`：
```
sub x8, x8, x9 ; asr x8, x8, #4 ; mov x9, #0x6db6db6db6db6db7 ; mul x8, x8, x9
```
`0x6db6db6db6db6db7` 是 **7 的模逆**（7×它 ≡ 1 mod 2⁶⁴）→ 16×7 = **112**，
而 `sizeof(ClassInfo)` = 0x38 = 56。**正好两个。**

对象池 `0x10019dba8`：
```
sub x8, x8, x9 ; asr x8, x8, #4      ← 没有 mul
```
→ **16**，而 `sizeof(unsigned long)` = 8。**又是两个。**

🔑 **两个独立的元素大小都恰好是双倍** → **`LinkedValue<T> { T base; T patch; }`**，
与 `nm` 早就给出的 `vector<LinkedValue<ClassInfo>>` / `vector<LinkedValue<unsigned long>>`
两个实例互相印证。
🔑 **它还说明两边 link 的东西不同**：类表配的是**整条 `ClassInfo`**，
对象池配的是**裸索引**（不是 `CodeInfo`）。

**四个计数器的位置**：
```
0x10019a75c  Link Results                    ← vector<LinkedValue<ClassInfo>>::size()
0x10019a78c  Mappings from Link Results      ← [sp, #0x80]
0x10019a7a0  Mappings from Pair Constraints  ← [sp, #0x88]
0x10019a7b4  Mappings from Backfill          ← x20
```
其中三个是**打印时现读的活槽位**，每个阶段的累加器都有了确切的回溯起点。
**下一步就是从这三个槽位往回追——那也就是剩下的全部工作（三个阶段本身）。**

### ✅✅ 类表映射器已解出并实现（2026-08-25，`7260c35198d`）——「无证据」判决对它彻底作废

两天前记的是「证据不足以按规则 3 实现三阶段映射」。**对类表那半已经彻底作废**：
直接反汇编 `InitializeWithClassTableLinkInfo` 就把算法全给出来了。

```
0x10019a464  operator new(n*8) + memset(0xff)  → vector<intptr_t>(n, -1)
0x10019a4f4  stage 1 循环，步长 0x70 = sizeof(LinkedValue<ClassInfo>)
0x10019a4f8  base cid @+0x00，patch cid @+0x38 = sizeof(ClassInfo)
0x10019a500  mapping[patch_cid] = base_cid
0x10019a4cc  在 vector<bool> 里置 base cid 的位
0x10019a588  stage 3 循环：仍是 -1 的条目
0x10019a5e0  下面没空位就落到末尾之后（cid 空间会长）
```

**算法全文**：stage 1 把每个 pair 直接写进 mapping 并占位；
stage 3 给剩下的 -1 分配**最小空闲 cid**。**stage 2 不存在。**

🔑 **中间那个阶段是结构性缺席，不是「这个 fixture 上恰好为 0」**：
它的计数器在 `0x10019a4ac` 被清零后**没有任何代码路径再碰它**。
这才是类表报 `Pair Constraints 0` 而对象池报 292 的原因——
**对象池是另一个函数**（`0x10019bd8c`，8184 B），那才是剩下的工作。

复现了他们公布的数字：606 pairs / 619 patch classes → **606 / 0 / 13**。

### 🔴 第 19 种假绿：**负控制本身可能是恒等变换**（2026-08-25）

写完就按惯例做负控制：把 backfill 的 `cid = cursor + 1`（他们的写法）改成 `cid = 0`
→ **四个测试全绿**。第一反应「测试太弱」是**错的**：

**这两个规则语义完全等价**——没有东西会被释放，所以最小空闲 cid 永远大于上一个发出去的，
「从 cursor+1 找」与「从 0 找」必然同解。**20 万组随机输入暴力验证：0 组不同。**

→ 那个负控制**什么都没改**，不红是正确的。

⚠️ 连带查出**我自己起错的测试名**（`BackfillResumesFromTheCursor` 根本测不到 cursor）
和**写反的注释**（「the cursor matters」——它只影响复杂度）。两者都已改正，
因为「声称某性质重要」的注释会诱使别人信任一个**永远不会失败**的测试。

✅ **有效的负控制**：删掉 stage 1 的 `taken[base_cid] = true` → 四红二，
另两个绿是因为它们本来就不覆盖这条（**这一点也要一起说清楚，否则「二绿」看起来像漏网**）。

详见 [[feedback-false-green-traps]] 第 19 种。

### ✅✅ 对象池映射器已解出并实现（2026-08-25，`bda9d0f74f9`）——385 个索引的含义已确立

**三个计数器是三个连续槽位、各写一次**，据此把 8184 字节切成三段，不用读全部 2046 条指令：
`0x10019d768→[x29,-0x88]`、`0x10019d828→[x29,-0x80]`、`0x10019da88→[x29,-0x78]`。

🔑🔑 **385 个索引 = pair-constraint 列表**（此前明确记为「含义未确立，三个假设全证伪」）。
`0x10019d644` 拷贝 `[x19+0x18]`，正是 `ObjectPoolLinkInfo` 的第二个 vector 成员。stage 2 走它：
```
0x10019d7c0  ldrsw x8, [x22, x21, lsl #2]   ; int32 索引 i
0x10019d7cc  ldp   x9, x1, [x8]             ; 同时取 mapping[i] 与 mapping[i+1]
0x10019d7d0  两个都 -1  → 跳过（无从推导）
0x10019d7dc  两个都已知 → 跳过（无需推导）
0x10019d7f0  i 已知   → mapping[i+1] = mapping[i] + 1
0x10019d80c  i+1 已知 → mapping[i]   = mapping[i+1] - 1
```
→ **每个索引断言 pool 槽位 i 与 i+1 必须相邻**。385 个里 292 个在 stage 1 后恰好一侧已映射
——**正是他们报的数字**。字段已改名 `indices_` → `pair_constraints_`，类型改 `int32_t`
（他们用 `ldrsw ... lsl #2` 索引它）。

**两个猜不出来的细节**：
1. **stage 1 有下限**：`0x10019d72c` 的 `cmp`/`ccmp` 对 8 —— **两侧都 ≥8 才处理**，pool 前 8 个槽位是固定的。
2. **backfill 不是简单的「最小空闲」**：当一个约束的两半都还没映射时，
   `0x10019d930` 找的是**第一个「它和它的后继都空闲」的位置**，两个一起占，循环多进一格、计数加 2
   （`w21 = 2` @`0x10019da68`）。只找最小空闲会把这一对拆开。

⚠️ **有一个测试第一次就红了，错的是测试不是代码**：我拿 base index 1 配对，
而 stage 1 自己的下限会丢掉它，于是那个槽走了 backfill。已改写成真正覆盖它声称的东西。

**负控制**：把反向推导的 `b - 1` 改成 `b + 1` → 推导那个测试红，另外四个绿（它们本就不覆盖这个方向）。

### ⚠️ ~~`print_shorebird_info` 仍未解锁~~ **已作废，同日晚些时候完成**（见本文件末尾的 🎉 一节）

> 保留这条是因为它记录了判断是怎么改的：当时以为生产方要靠反汇编两个函数前面
> 各约 1500 条指令，而实际上 `dart::groupBy<T>` 是**外联符号**，mangled name
> 直接给出签名。**「读不到」有时只是没找对地方看。**

### （原文）差的是「Link Results」的**生产方**

三个阶段两张表都做完了。但报告第一行 `Link Results N` 数的是**别人产出的 pair**，
那个产出者是两个函数**前面约 1500 条指令**，**尚未解出**。
它的外联 helper 给出形状（`unordered_map<string, vector<ClassInfo>>`、cityhash、`std::set<long>`）
——按 hash 分组、组内配对——但**那是描述不是转写**。
**flag 需要它；光有三个阶段打印不出任何东西。**

### 🎉 `print_shorebird_info` 已完全复刻（2026-08-25，`8275b3de81f` + `26f299efa8f`）——八行报告与他们逐行相同

最后一块是 **link results 的生产方**，而它有个**外联符号一直摆在那儿**：
**`dart::groupBy<ClassInfo>` @ `0x10019aa08`**，mangled name 直接给出完整签名：
```cpp
unordered_map<string, vector<T>> groupBy(const vector<T>&, string (T::*key)() const)
```
在 `0x100199a88` / `0x100199a94` 被调两次（base 一次、patch 一次）。

**配对规则（两处 size 检查）**：
- `0x10019aa70`：groupBy 的 body 步长 `0x38`=sizeof(ClassInfo)，读的是 **+0x20 = `class_hash_`**，不是 +0x08 的 name
- `0x100199ad4`：`cmp #0x38` —— patch 侧的组必须**恰好 1 个**
- `0x100199dd4`：除以 56 后 `cmp #1` —— base 侧同样**恰好 1 个**
→ **一个 hash 在任一侧对应多个类就是歧义，配不出任何东西。**

**对象池同型但有一处关键差异**：`0x10019bdc4` 步长 `0x60`=sizeof(CodeInfo)，
key 是 **+0x18 = `op_subgraph_hash_`**（不是 +0x00 的 `self_hash_`）。
⚠️ **但它的 link results 是「索引对」不是「记录对」**：配上的每对 CodeInfo
贡献其索引向量的**逐元素配对再去重**。这一步读不出来，是**算出来的**：
按 self_hash 分组得 1089 对、按 subgraph 分组得 1378 对，**都不是 1121**；
subgraph 分组 + 逐元素展开去重 **恰好 1121**。再跑三个阶段得 **1113/292/16**，和 = **1421** = pool 大小。

**结果：八行报告与他们逐行相同**
```
606 / 606 / 0 / 13          ← 类表
1121 / 1113 / 292 / 16      ← 对象池
```

**同时补上**：`--base_op_link_data` / `--patch_op_link_data`（名字与不匹配时的错误串都来自他们二进制的 strings）、
`ReadObjectPoolLinkInfo`、以及把 header 里 16 字节 reserved 换成真正的
`base_object_pool_` / `patch_object_pool_`。

⚠️ **一处刻意不声称**：`self_pp_indices_` / `subgraph_pp_indices_` / 两者并集
在这个 fixture 上**都给 1121**，所以**判别不出他们用的是哪个**。
我们用 `self_pp_indices_`，并在头文件写明这个选择未经验证。

⚠️ **fixture 的 base.ct 与 patch.ct 逐字节相同**（实测 `cmp` 通过）——
单独用它每个 hash 都和自己配对，**「配不上」的路径一次都走不到**。
所以 `shorebird_info_check.sh` 另造了一份**删掉 20 个类**的输入：数字变成 586/33，我们同样逐行相同。
**这条比结果本身更值得记：一个 oracle 的输入如果两侧相同，它测到的只是恒等情形。**

**负控制**（针对推得最费劲的那一步）：把分组键从 `hash` 换成 `name` → **600/19** 而不是 606/13，
因为有 6 个类同名而 hash 不同（hash 尾部的出现序号正是为此存在）。
**于是「键是 hash」从「读到的偏移」升级成「行为验证过的结论」。**

→ **11 个私有 flag 全部完成。**


### ✅✅ 对象池聚合器已实现并**行为验证**（2026-08-25，`ab58e28152d` + spike `9d5fb26`）

补上本文件正文长期缺失的 2026-08-25 后半段。`MEMORY.md` 索引里早有，正文一直没有。

**做了什么**：`ComputeObjectPoolLinkResults` 原先靠「组恰好 1 成员」过滤配对
——**那不是他们的算法**，只在他们的 fixture 上重合。换成 `ObjectPoolMappingsAggregator`：
`votes_[patch][base] += 1.0/(|base组|+|patch组|)`，`GetBestMapping` 按分数降序、
平票让恒等映射胜出、`used_` 保证**跨调用的全局单射**。索引向量改成 sticky 条件选择
（base subgraph 组非空时用 `subgraph_pp`，回落后用 `self_pp`）。

🔑 **判别性 fixture 是关键产出**（`make_op_fixture.py` + `op_aggregator_check.sh`）。
**他们的 fixture 判别不出任何东西**：每个匹配组都 1:1、每个索引对都是双射
→ 每个内层投票表只有一个候选、贪心永不拒绝 → 加权投票与旧过滤给出**同一份报告**。

**设计约束：报告只有四个数字 → 只改变映射目标的错误观测不到。**
每组都被设计成把一种错误变成**计数**差异。最不显然的是 W1/W2：
两组都投 patch 索引 80，W1 得 `4×1/4=1.000`、W2 得 `5×1/6=0.833`
→ 加权选 W1、数事件选 W2；而 W1 的 base 索引是 **5**、W2 的是 **82**，
**只有后者过得了 stage 1 的 `>=8` 闸门** —— 这才把不可见的目标变化变成 line 2 的变化。

**实测**（他们的 gen_snapshot 当裁判）：
```
他们        8 / 7 / 0 / 121   ← 与反汇编手推值一致
我们        8 / 7 / 0 / 121   ← 逐行相同
常数权重    8 / 8 / 0 / 120
无条件self_pp 7 / 6 / 0 / 122
size==1过滤 4 / 4 / 0 / 124
```

⚠️ **两个 harness 坑**：(a) 他们的 `gen_snapshot` 打完报告后会 `Out of memory`（zone.cc:96），
**偶发吞掉报告输出** → 必须重试，否则 flake 被读成「他们没输出」。
(b) **第一版 self-test 扰动不是扰动**：`synth_base.op` 自己配自己**还是 8/7/0/121**
（每组恒等配对，闸门下的 base 索引仍是 5）——长得像通过的 self-test，实际什么都没比。

⚠️ **三处刻意偏离**（代码注释已标）：他们内层循环界是 `max(patch.size(),1)` 且同时索引两个向量
→ **越界读**，我们按较短者取界；他们第四张 `groupBy(patch,self_hash_)` 建了从不读，我们不建；
比较器捕获方式无可观测差异。

**遗留**：`GetBestMapping` 的平票且**双方都非恒等**时，顺序由 unordered_map 桶布局 + introsort 决定
（**绝不 `reserve()`**）；当前 fixture 零覆盖。

---

### 🎉 `--dump_object_pool` / `--dump_object_pool_link_data` 已完成（2026-08-26，任务 60）

`analyze_snapshot` 的 flag 面**只剩 `--disassemble`**（它撞 VM 自己的同名 flag）。
help 检查从「7 documented / 14 lines withheld」变成 **12 / 3**。
全部地址级证据在 `OBJECT_POOL_DUMP_RECON.md`。

**先证「不是死 flag」再动手**：`strings` 在这里是坏判据（任务 18 的阳性对照），只能行为测试。
实测他们的二进制：`--dump_object_pool_link_data` 是**带自己路径的 string option**
（裸名被拒、`=` 空值报 "Empty value"、`=path` 通过，且**不需要 `--out`**），
`--dump_object_pool` 是 **bool**（`=value` 报 "Non-empty value"）。

**生产方是 `GetObjectPoolLinkInfo(Thread*)`**（`0x10024cb9c`），
两个 flag 分别经 `Dart_DumpObjectPool`(`0x10024c32c`) 与 `Dart_DumpObjectPoolAsJson`(`0x10024d668`)。
三部分：

1. **`self_pp_indices` / `subgraph_pp_indices` 就是同一趟 walk 的池引用序列，保序且保留重复。**
   他们 1380/1380 两条都对；**去重**只有 1250/932，**排序去重**只有 1075/775。
   448 条列表里真的有重复索引，所以这个比较能证伪而不只是附和。
2. 🔑 **`pairs` 不是扫代码扫出来的，是对象池 `entry_bits` 里的一个位域。**
   他们把上游 4 位的 `TypeBits` 缩到 **2 位（bits 2..3）**，在 **bits 0..1** 插了
   `PairPosition`（0 无 / 1 first / 2 second）。三处独立印证：
   `ObjectPool::NewFromBuilder` 的 `and #0xc; cmp #4`（gs `0x10015d884`）、
   JSON dumper 的 `ubfx w8,w8,#2,#2`（as `0x10024e128`）、
   `AddObject` 拆 `kImmediate128` 时写的字面量 **`0x11` / `0x12`**（gs `0x100255684`/`0x1002556a4`）。
   标记点：`LoadNativeEntry` 写 **`0x9`**（gs `0x10024e68c`）；
   `AddObject` 前言（gs `0x1002555f4`-`0x100255620`）把**紧跟在 first-native 之后的任何一条**改成 second
   ——它**根本不看新条目是什么**，是位置性配对，写成「若新条目是立即数」在所有 fixture 上同分但规则不同；
   `EmitInstanceCallAOT` 写 `csel(0x65,0x05)` 与 `0x06`（gs `0x10027e23c`/`0x10027e258`）；
   `GenerateTTSCall`（⚠️ **推断，不是反汇编出来的**——它全内联、零符号，
   但它是 `(null, string)` 那种形状的唯一生产者，而他们 385 条里有 287 条正是这个形状）。
   92 + 6 + 287 = **385**，与他们一字不差。
   ⚠️ 这个位不仅要建，还要**活过反序列化**：`kResetToSwitchableCallMissEntryPoint`
   那条臂会把整个字节重写掉，而他们的 dump 里那 6 条既是 `(unknown)`（=kImmediate）**又**在 `pairs` 里。
3. **`entries[].code`** 是他们自己那份 `ObjectPool::DebugPrint`
   （字符串表里两份：上游那份在 `0x290024`，他们的在 `0x29aae8`），
   多一条 `<%ld len string> (obj)`、`(raw)` 改叫 `(unknown)`。
   ⚠️ **阈值用 `Utf8::Length`（`cmp #0xf9`），印出来的数字用 `String::Length()`**
   （`0x10024e218`：`ldur x8,[x8,#7]; asr x8,x8,#1`）。两者混用会把 2112 印成 2844 ——
   实测抓到过一次，然后又做成了负控制。

**判据**（`op_dump_check.sh`，已进 `verify_all.sh`）：pp 列表走两段链（模型 ≡ 他们 1380/1380；
我们的二进制 ≡ 模型 1589/1589），但**第三段是直接对比**——
`pairs`、池大小、1421 条 entry 描述都描述池本身，两边的池都由同一份 `base.dill` 生成：
**池大小 1421 = 1421；`pairs` 385 条逐项相同；1421 条 entry 里 1323 条逐字相同**。
其余 98 条全是**反序列化重写成本进程地址**的槽（92 个 `kResetToBootstrapNative`
+ 6 个 `kResetToSwitchableCallMissEntryPoint`），跨进程本就不可能相同。
**pairs 的唯一 oracle 就是这一段直接对比**——这棵树里以前没有任何东西记录过配对约束。

**四个负控制，每个都在同轮 `ninja` exit 0 下取得**：pp 列表去重 → 红（1459/1136）；
不保留反序列化时的 pair 位 → `pairs` 385→**379**；去掉 `GenerateTTSCall` 的标记 → 385→**98**；
长串印 `Utf8::Length` → entry 相同数 1323→1320。
⚠️ **新踩到的坑**：改 `runtime/vm/` 下任何文件都会变**快照版本 hash**，
所以负控制必须把 `gen_snapshot` 一起重建——否则检查是以
`Wrong full snapshot version` **崩掉**，而不是为了预期的原因变红，
而从退出码上这两者一模一样。

**顺手订正的两条陈旧记账**（都已实测，不是凭记忆）：
- 「`subgraph_hash`/`op_subgraph_hash` 仍是 `self_hash`、仍然是错的」——任务 59 已作废。
- 「`SubgraphHasher` 他们 12 / 我们 0 是真实缺口」——**是第三例口径陷阱**。
  那趟 walk 的三个 hash 加两条 pp 列表全部实现且逐项验证（他们 1380 个函数上四项全 1380/1380），
  只是我们写成自由函数、**没有同名类**。同批 `CascadeLimiter` 已变成 18 vs **31**。
  → 三例同型之后（`sha1_`、`ClassTableMapper`、`SubgraphHasher`），
  **符号表对「功能有没有」基本失去判别力**，真判据是逐项对比他们的产物。

**刻意没猜**：`ObjectPoolBuilder::PairEntry`（他们 `ObjectPoolBuilder` 上有这个 vector，
但 `AddObject`/`NewFromBuilder`/`GetObjectPoolLinkInfo` 一处都不读它，
而 385 条已被 entry_bits 全部解释，所以它的用途未确立，不发明替代品）；
他们那个 pair 参数的写法（`AddObject(const Object&,...)` 在他们那边全被内联，只有
`AddObject(ObjectPoolBuilderEntry)` 有符号）；
他们 `LoadNativeEntry` 把 `patchable` 形参**完全无视**、硬写 `0x9` 这件事
——我们照常传参，**把差异留在明处而不是照抄**，因为凭一个常量就复刻一个疑似 bug 划不来。

基线：`verify_all.sh` **16 ran / 0 failed / 0 skipped / 0 blocked**（上轮 15）、
`verify_reproduction.sh` **28 产物 0 失败**、`run_vm_tests` **157 passed**（上轮 154，新增 3 个
`ObjectPoolPairPosition_*`；其中一个**断言的是字节**——他们那六个 entry_bits 常量，
因为一个只和自己自洽的位布局照样能 round-trip）。
