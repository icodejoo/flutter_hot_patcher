---
name: reference-wrapper-stub-bodies
description: Sim→CPU wrapper 的 28 字节 body 已逐指令转写；metadata 靠常量位移 0x8000 不靠掩码，我们的 MetadataForWrapper 因此差一个 offset；依赖 Thread::is_simulating_ 与 brk hypercall
metadata: 
  node_type: memory
  type: reference
  originSessionId: 3c901a3b-0f95-4c5e-908d-e00940acf8eb
---

来源：`spikes/shorebird_linkinfo_oracle/WRAPPER_STUBS.md`（route-a-research，commit `1838d3d`）。
两个生成器的定位见 [[project-wrapper-upstream-ancestor]]。

## Sim→CPU shared body，28 字节 = 7 条指令

```asm
0x00  d2900011  mov  x17, #0x8000        ; pad → metadata 的位移
0x04  8b110210  add  x16, x16, x17       ; x16 = &Metadata[i]（pad 用 adr x16,#0 给出 &pad[i]）
0x08  f9400210  ldr  x16, [x16]          ; Metadata::target_entry_point
0x0c  f9446f51  ldr  x17, [x26, #0x8d8]  ; Thread::is_simulating_，THR = R26
0x10  b4000051  cbz  x17, 0x18           ; 不在模拟 → 跳过 hypercall
0x14  d43625a0  brk  #0xb12d             ; RunDartOnCPUCode hypercall
0x18  d61f0200  br   x16                 ; 已在 CPU 上 → 尾跳
```

**「纯 thunk」假设被推翻**：body 里没有 `adr`、没有 `and`、没有页掩码
（`Assembler::AndImmediate` 在该生成器中从未被调用）。它是按 `Thread::is_simulating_`
的双向分支。CPU→Sim 的 body 里 `0x8000` 与 `0x8d8` 字节相同，但 `cbz` 极性相反
——这是整份读数的自校验。

## 🔴 由此发现我们的 `MetadataForWrapper` 是错的

他们靠 `kLandingPadSize == sizeof(Metadata) == 8`，用**一个常量位移**完成映射：

```
他们：Metadata_i = pad_i + 0x8000        = P + offset + i*8 + 32768
我们：先 MappingStart 掩码还原 P、再算 index → P + 32768 + i*8
差值 = offset_of_first_wrapper_in_page_
```

`0x8000` = 32768 = `rx_mapping_size`。所以他们的 `MetadataForWrapper(uword)` 就是一条 `add`，
`WrapperOfMetadata(void*)` 就是一条 `sub`。

⚠️ **这否证了我此前的推断**「该方法不收 page 参数是因为靠 `MappingAlignment()` 掩码还原页基址」
——真实原因是**根本不需要页基址**。`MappingStart`/`MappingAlignment` 在这条路径上没用到
（上游 `FfiCallbackMetadata` 用，他们不用）。

我们的版本自洽、测试全绿，**但和他们不是同一个函数**。所有现有测试都看不见这个差异，
因为它们断言的是我们自己的公式。修的时候测试要一起改。

## Task 6b 的前置依赖（比预想重）

粘这七条指令之前需要两样我们没有的东西：

1. **`Thread::is_simulating_`** —— `uword`，偏移 `0x8d8`（`thread.h:1643`，名字来自 Flutter dSYM）。
   紧邻其后是 `dart_state_is_on_cpu_`。
2. **`brk #0xb12d`** —— 它是 `Simulator::DecodeSimulatorToNativeTransition`（`0x1001aa518`）
   从 `brk` 的 `imm16` 解码的**九个** Sim→CPU hypercall 之一，范围 `0xb128`–`0xb130`，
   各带日志串（`RunDartOnCPUCode` / `CallFFIOnCPUCode` / `ResumeDartOnCPUCode` …）。
   `0xb12d` 与 `0xb130` 是其中唯二**不推进模拟 PC** 的。完整表在 WRAPPER_STUBS.md。

## ⚠️ 一条负控制已失效

Task 1 曾用「`mov w?, #0x7de/#0x7fc` 在我们的基线里出现 0 次」当负控制。
**现在不成立了**：我们自己的 `ProductARM64/gen_snapshot` 已导出这两个生成器
（各 140 字节骨架 vs 他们的 868/648）。任何新结论都不能再靠这条。
教训：负控制会随实现推进而过期，引用前先复跑。

## ✅ 6b-i 已完成（2026-08-20，commit `a398183529d`，60/60）

`Thread::is_simulating_` 已加，落在 **0xf18**（他们 0x8d8）。只能追加在末尾、
不能插中间的完整理由与实测见 [[reference-thread-field-offsets]]。
字段是纯存储，**VM 里没有任何地方设置它**；注释里那个极性来自他们两个 body 的对拍，
**未经运行观测**。测试断言的是 body 真正依赖的东西：
`compiler::Address::CanHoldOffset` 能编码这个偏移（负控制 `offset+1` 为 false）。

## ✅ 6b-ii / 6b-iii 也已完成（2026-08-20，`99fe5206f9c` + `d5625eae25c`，76/76）

**Sim→CPU 的 28 字节 body 已落地，是我们 15 个私有 stub 里第一个有真 body 的。**
七个字里**六个与他们逐字节相同**；第四个（`ldr x17,[THR,#off]`）因我们 offset 不同而不同,
测试改成**按公式反推编码**，并顺带断言同一公式能从 `0x8d8` 复现他们的 `0xf9446f51`。

**hypercall**：`brk` imm16 落在 `0xb128..0xb130` 时先于 SimulatorDebugger 被截走
（他们用 `brk` 不是 `hlt`，所以必须插在 brk 分支最前面）。九个只实现 `0xb12d`，
其余八个各自 `FATAL` 报出自己的名字。常量在 `constants_arm64.h`，
方法名沿用他们的 `Simulator::DecodeSimulatorToNativeTransition`（那个名字是实测到的）。
实现复用 A2/A5 的 `InvokeWithTHR` + `SimulatorSetjmpBuffer`，不另造机制；
**「从 LR 继续」是推断**（唯一实测事实是他们这一支不推进 PC）。

🔴 **两个必须记住的度量事实**：
1. **生成器里的 `ASSERT_EQUAL` 在 release/product 全被编译掉**，我们只构建这两种
   → 那条 28 字节断言**从未运行过**。真正把 body 钉在 28 字节的是单测
   （加一个 `nop` → pad-array 测试报 16380 vs 16384，已实测）。
2. **`wrapper_symbols_check.sh` 仍是 0 且 exit 1**，符合预期：发 body 不产生
   `WrapperAllocator` 的调用者。要非零得有**转换路径上真的去 wrap entry point** 的代码。

`target::Thread` 装不下 `is_simulating_`（见 [[reference-thread-field-offsets]]），
生成器用宿主 offset，并加了 `RELEASE_ASSERT` 拿表里已有的邻近 Thread 字段对拍
→ 交叉编译的 gen_snapshot 会当场炸而不是发错位移。

CPU→Sim 仍是 `Breakpoint()` 占位（272 字节、要调 `compiler::RunOnSimulator`，属 Phase D），
其 `GetStubCodeRange` 仍报空区间，所以不会映射页、pad 进不去。**真机零验证。**

## 6b-i 的起点已查（2026-08-20，省下次会话一次排查）

我们的 `runtime/vm/thread.h` 里 `is_simulating|on_cpu|dart_state_is` **零命中** ——
`Thread::is_simulating_` 确实要新加，不是改名问题。

⚠️ **他们的 `0x8d8` 不能直接照搬**：我们 `thread.h` 是 1974 行、他们 dSYM 说该字段在 1643 行，
两边字段集不同（我们多了 Route-A 残留与自研 simulator 字段），所以**偏移必然不同**。
新字段位置要按我们自己的布局定，`0x8d8` 只用于理解他们的 body 在读什么，
不能当成我们要对齐的常量。生成器里引用它必须走 `OFFSET_OF(Thread, ...)` 或
`compiler::target::Thread::` 访问器，不能写死立即数。

## 未确立

位移为何是**两页**而非一页（`Layout::fromTemplate` / `MetadataOffset` 全被内联，
layout 成员上没有 `DW_AT_const_value`）。

相关：[[project-wrapper-upstream-ancestor]]、[[feedback-false-green-traps]]、[[feedback-verify-by-running]]

## 🔴 订正（2026-08-24）：CPU→Sim 的 272B body **不是「再抄 232 字节」**

把 `GenerateTransitionDartToSimulatorIfNeededStub` 整段反汇编（868 字节，
`0x10046d81c`..`0x10046db80`）后拿到完整发射清单。2014 个 pad 之后是：

1. `Bind(&body)`；2. `LoadImmediate(R17, 0x8000)`；3. 字面量 `0x8b110210` = `add x16,x16,x17`；
4. `ldr x11,[x16]`；5. `ldr x17,[THR,#0x8d8]`；6. `cbz x17, L`；7. 字面量 `0xd61f0160` = `br x11`；
8. `L:`；9. `ldr x10,[THR,#0x688]`（`Thread::isolate_`）；10. `ldr x10,[x10,#0x20]`；
11. `str x11,[x10,#0x310]`；
12. **其余全部**来自 `compiler::RunOnSimulator(Assembler*, Register, Register, Simulator::SimulatorExecutionSource)`，
    实参 source=0。

前 11 条只占约 **40/272** 字节。`RunOnSimulator` 在 `0x10046c878`..`0x10046d81c`，
**4004 字节**，而且是**共享**的（不止这个 stub 用）。
→ 只落地前 11 条会得到一个 40 字节的 stub 对他们的 272 字节，不算部分复刻。
**前置条件是先复刻 `RunOnSimulator`。**

## 私有 stub 生成器：不是 15 个，是 **16 个**（有名字清单）

```
CallClangCodeWithSimulatorArgs      SimulatorCallAutoScopeNative
CallSimulatorFromFfiTrampoline      SimulatorCallBootstrapNative
ResumeInterpreter                   SimulatorCallNativeThroughSafepoint
ResumeOnCPU                         SimulatorCallNoScopeNative
ResumeOnSimulator                   SimulatorCallToRuntime
Resume                              SimulatorEnterSafepoint
RunDartOnCPU                        SimulatorExitSafepoint
TransitionDartToCpuIfNeeded         TransitionDartToSimulatorIfNeeded
```
我们只声明了最后两个，只有 `TransitionDartToCpuIfNeeded` 有真 body。
新符号：`Simulator::SimulatorExecutionSource`（枚举，值未读）、
`Simulator::Execute(const char*, SimulatorExecutionSource)`、`SimulatorExecute(Simulator*, …)`。

## 🔴🔴 再订正（同日，第二次）：发射字节一直可以直接读

上一条说「要先复刻 4004 字节的 `RunOnSimulator`」——**尺寸错了**（实为 **1760** 字节，
我拿的是「我列出的下一个符号」而不是「地址序的下一个符号」），**结论也错了**。

他们的 `gen_snapshot` 把每个 stub 都发射进它产出的快照，而且 ELF **保留 stub 名**：

```bash
$SB/gen_snapshot_arm64 --snapshot_kind=app-aot-elf --elf=hello.so hello.dill
objdump -d --no-show-raw-insn hello.so | grep -n '<stub TransitionDartTo'
```

**全部 16 个私有 stub 的确切发射字节都在里面**，带名字带尺寸。两个 wrapper stub
各 **16384 / 16380** 字节 = 2014×8+272 与 2044×8+28 —— 反过来印证了先前辛苦从
生成器反汇编推出来的 pad 数与 body 尺寸。

**方法论要点**：要**逐字节复刻**，不需要复刻他们的生成器。生成器反汇编回答的是
「该调哪个 `Assembler` 方法」；**目标字节从产物读，`cmp` 判定**。
先前那棵「必须先做」的依赖树（`RunOnSimulator` 1760 + `LoadRegistersFromSim` 1160 +
`StoreRegistersToSim` 1100 + `ShorebirdLeaveCFrame` 436 + `ShorebirdEnterCFrame` 360 +
`RestoreClangRegisters` 268 = **5084 字节生成器**）对这个 stub 的全部贡献，
就是那 **272 字节输出**。

CPU→Sim body 已完整反汇编（68 条，语义连贯：metadata 取目标 → `is_simulating_` 快路径 →
存 x15/x19-x30/SP/q8-q15 进模拟器寄存器文件 → 翻转 `THR+0x8e0`（就是 §7.8 注意到但没查的
`dart_state_is_on_cpu_`）→ 换 SP 到 `THR+0x8e8` → 存 x0-x9/q0-q7 → `blr THR+0x8f8` →
镜像恢复 → 翻回标志 → `ret`）。**完整清单刻意不入库**（origin 公开，且几秒可再生）。

⚠️ **一般化教训**：连续两轮我都在「怎么造」上花力气，而没先问「产物里能不能直接看到」。
这个仓库的 oracle 传统本来就是「用他们自己的产物」——对 stub 同样成立。

## CPU→Sim body：全部位移已解析成具名字段（2026-08-24）

从引擎 dSYM 拿到两份布局，body 里再没有魔数：

**他们 `Thread` 里的 Shorebird 连续块（6 个 uword）**
`is_simulating_` 0x8d8 / `dart_state_is_on_cpu_` 0x8e0 / `simulator_csp_` 0x8e8 /
`simulator_async_resume_pc_` 0x8f0 / `simulator_execute_` 0x8f8 / `simulator_call_from_ffi_` 0x900。
**我们只有第一个**，其余五个要加；而 Thread 只能追加在末尾（见 [[reference-thread-field-offsets]]），
所以**我们的偏移必然与他们不同**，68 个字里有 **8 个**的位移字段注定不一致——
和 Sim→CPU body 第 7 个字不一致是同一个结构性原因。

**他们 `Simulator`**（`simulator_arm64.h:58`，0x498 字节）就是上游布局：
`registers_` 0x000、`vregisters_` 0x100、flags 0x300、`last_pc_` 0x308、**`pc_` 0x310**、
`stack_` 0x318、`stack_limit_` 0x320。
→ 寄存器文件的位移可以**从我们自己的 Simulator 推**，不用抄。
→ 一直没解释的 `str x11,[x10,#0x310]` 就是**写 `Simulator::pc_`**：把 wrapper 的目标
交给模拟器当下一条 PC。它被发射**两次**（stub 生成器一次、`RunOnSimulator` 一次），
是他们代码里的冗余，不是解码错误。
`x10` = `Thread::isolate_`(0x688) 再 `+0x20`，即 isolate 的 simulator 指针。

剩下的是转写 + 加五个 Thread 字段，机械活，判据是对现提取的 stub 做 `cmp`。

## ✅ CPU→Sim body 已落地（2026-08-24，commit `516d56e80ef`）

两个方向都有真 body 了。两个 stub 尺寸与他们完全一致：**16384 / 16380**。
CPU→Sim 272 字节：**68 条里 60 条逐字节相同**；另外 8 条编码 Thread 偏移，
只有位移字段不同（结构性，不可关闭）。
新增 4 个 Thread 字段（`dart_state_is_on_cpu_`/`simulator_csp_`/
`simulator_async_resume_pc_`/`simulator_execute_`/`simulator_call_from_ffi_`，全部追加在末尾）。
⚠️ 生成器里的 `ASSERT_EQUAL` 在 product 构建被编译掉，**钉住 272 的是单测**。
单测把 60 条写成字面量、8 条从 offset 访问器**再推导**，所以以后有人给 Thread 加字段时
期望值会跟着代码走而不是变红。
**负控制做了**：`mov x0,x10` → `mov x0,x11`（尺寸检查看不见的错），单测 exit 255；还原后 0。

## 又两个 stub（2026-08-24，commit `0fba1624683`）

`ResumeOnCPU` 16B（4 条，1 条逐字节同，另 3 条都是 Thread 访问）与
`CallSimulatorFromFfiTrampoline` 124B（31 条，**29 条逐字节同**）。
尺寸与他们完全一致。**16 个私有 stub 现在声明 4 个，4 个都有真 body。**

两处他们的怪癖照抄没改：`ResumeOnCPU` 载入 `is_simulating_` 到 x17 却从不使用（清理成 3 条会得到 12B 对他们的 16B）；
`CallSimulatorFromFfiTrampoline` 存了 x8/x9 却不恢复、只往返 q0-q7。**契约是他们的字节，不是我认为应该是什么。**

⚠️ **加 stub 到 `VM_STUB_CODE_LIST` 有回归风险**：它可能移动序列化器的 code 表、
从而打破已逐字节相同的 `.ddid`。这次实测没有（VM stub 只在被引用时才进那张表），
但**每次加 stub 都要跑一遍 `verify_reproduction.sh`**。

## 三个 SimulatorCall*Native（2026-08-24，commit `a53dc02b0f4`）

Bootstrap / AutoScope / NoScope 是**同样的 34 条指令，只差 hypercall 立即数**，共用一个生成器。
各 136B，尺寸与他们一致，**27/34 逐字节相同**，不同的 7 条全是 Thread 位移。
**16 个私有 stub 现在 7 个有真 body。**

⚠️ **写之前先把每个位移解析成具名字段**（用 dSYM 的 Thread 布局按偏移反查名字），
再用我们的 `target::Thread::*_offset()`。否则会把**他们的**偏移硬编码进来——
那种错能编译、能过尺寸检查、指令助记符还一样，只有位移字段不同，
**和「已知的结构性差异」长得一模一样，无法分辨**。这是这条线上最危险的假绿。

他们的 Thread 与我们的偏移差**不是常数**（有的 0x10、有的 0x20），说明他们的 Thread
中间还插了别的成员，不只是末尾追加。

**顺带印证**：hypercall 立即数与 `constants_arm64.h` 里已有的常量名一一对上
（`kCallBootstrapNativeOnCPUCode` 等）。`WRAPPER_STUBS.md` 曾把这套命名记为「我们的发明」，
现在 stub 名是他们的、且与常量名吻合 → 那套命名是对的。

## 首个 100% 逐字节相同的 stub（2026-08-24，commit `91af57163e3`）

`CallClangCodeWithSimulatorArgs` 152B / 38 条 → **38/38 全同**。
原因很清楚：**它是唯一一个完全不碰 Thread 字段的 stub**，只读 Simulator 寄存器文件
（上游布局、可从我们自己推导）和 C 栈。别的 stub 差那几个字，全是 Thread 布局分歧导致的。
→ **反过来证明：只要没有结构性障碍，这套转写方法产出的是「完全一致」而不是「大致一致」。**

**16 个私有 stub 现在 11 个有真 body。**

### 刻意没做：`ResumeInterpreter`

只有 13 条指令，看着最容易，但它通过 `Thread::ResumeInterpreter_entry_point_`
调一个 **runtime entry**。复刻它意味着要新增一个 runtime entry 并**写出它的函数体**——
那是从 stub 字节里推不出来的行为。**这是另一种工作，不能伪装成转写混进来。**

## 两个 Safepoint stub（2026-08-24，commit `3cb35b791d9`）→ **13/16**

`SimulatorEnterSafepoint` / `SimulatorExitSafepoint` 各 292B / 73 条，**各 72/73 全同**，
唯一不同的那条就是加载哪个 leaf entry point，且只差位移。两者互相只差这一条，共用生成器。

⚠️ **踩过的两个小坑，都值一分钟**：
1. `EnterSafepoint_entry_point_offset()` 是**宏生成**的（`thread.h` 的 `name##_entry_point_offset`），
   直接 grep 名字**找不到**——差点据此判定「这是 Shorebird 新增的 runtime entry、需要写函数体」而放弃。
   要 grep `runtime_entry_list.h` 里的 `V(void, EnterSafepoint)`。
2. 它只在 `dart::Thread` 上，不在编译期的 `target::Thread` 上。

寄存器配对乍看错乱（`(x14,x16)`、`(x17,x19)`），是因为跳过了 **x15（SPREG，正在被压栈的那个栈）**
与 **x18（平台 ABI 保留）**。

## `RunDartOnCPU`（2026-08-24，commit `e44d126dde0`）→ **14/16**

348B / 87 条，**80/87 全同**，7 条不同全是 Thread 位移。是 CPU→Sim body 的镜像：
存模拟器自己的 C 帧状态 → 从模拟器寄存器文件接管 Dart 寄存器状态 →
`dart_state_is_on_cpu_` 0→1 → 把模拟器的 CSP 存进 `Thread::simulator_csp_`
（转换 stub 就是去那里找它）→ 调用 → 结果经 isolate 的 simulator 指针写回 → 全部还原。
`0xd0` 这个帧位移与 CPU→Sim body 用的是同一个常量。**不需要新增 Thread 字段。**

### 🔴 剩余 2 个的判断**两条都是错的**（2026-08-24 订正）

**`ResumeInterpreter`：根本不是任务，我们早就复刻了。**
它是**上游 stub**（`stub_code_list.h:84` 就有 `V(ResumeInterpreter)`），
`ResumeInterpreter` 也**在** `runtime_entry_list.h:90`、`runtime_entry.cc:4896` 有完整
`DEFINE_RUNTIME_ENTRY(ResumeInterpreter, 3)`。实测我们产出的 stub **13/13 条、12/13 逐字节相同**，
唯一差异是 `ResumeInterpreter_entry_point_` 的 Thread 位移。
→ 我曾两次断言「它需要新增 runtime entry 并写函数体、不能转写」，还声称「已复查」。**全错。**

**`Resume`：也是上游 stub**（`stub_code_list.h:195`），生成器在**架构无关的**
`compiler/stub_code_compiler.cc` 里。他们 48 条 / 我们 30 条 → Shorebird 在上游版本上
**加了 18 条**（模拟器分派）。所以这不是「新增 stub」，是**改上游 stub**，
而且改的是共享文件，会影响 x64/riscv 构建，要小心。

### ⚠️ 方法论：否定性结论没有 oracle
肯定性结论有 `cmp` 兜底（抄错了就是不过）。**否定性结论（「这做不了」「这需要另一种工作」）
没有任何机制会推翻它**——它会安静地变成一条永久搁置的任务。
本轮之前我用同一个理由搁置了 `ResumeInterpreter` 两轮，而它其实开箱即中。
**下判断说「不能做」之前，必须像验证「能做」一样验证它。**

## ✅ 16/16 全部有真 body（2026-08-24，commit `6db441570b5`）

最后一个是 `Resume`——**上游 stub，Shorebird 在其上加了 18 条**（上游 30 → 他们 48）：
① 取出 resume PC 后存进 `Thread::simulator_async_resume_pc_`（已有值就 trap）；
② 把无条件跳转换成范围分派：PC 在 base 快照指令区间内 → `ResumeOnCPU`，
区间外 → `ResumeOnSimulator`，没记录区间 → 清掉再直跳。
48/48 条、40 字全同，8 处差异全是 Thread 位移。两处插入都用
`#if defined(TARGET_ARCH_ARM64)` 守住（这个生成器与 x64/riscv 共享）。

**16 个中有 2 个是上游 stub**（`Resume`、`ResumeInterpreter`），其余 14 个是他们新增的。

### ⚠️ 上游 stub 的尺寸随构建配置变
上游生成器带 debug/非 product 检查，所以 release 的 `run_vm_tests` 看到
`Resume` 312B、`ResumeInterpreter` 60B，而他们的 product `gen_snapshot` 是 192B/52B。
→ **这两个的单测只能验「Shorebird 那几条指令在不在」，验不了分支方向。**
我实测过这个弱点（把 `LESS` 改成 `GREATER`，单测照过），没有假设。
→ 逐字对比只能在**两个 product 构建之间**做，落在 `compare_stubs.py`。

### `compare_stubs.py`（新增，已接入 `verify_reproduction.sh`）
对 14 个 stub 断言「指令条数」+「差异字数」+「每个差异字都必须是 Thread 访问」。
差异字数是每个 stub 的固定属性（因为差异只来自 Thread 布局分歧）。
**不存他们的任何字节**——他们那边每次现跑现生成。
负控制：同一个 `LESS`→`GREATER` 让它报 `Resume` 9 个差异字（期望 8）、指出 index 29、exit 1。
