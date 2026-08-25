---
name: project-wrapper-upstream-ancestor
description: Shorebird 的 WrapperAllocator 是上游 FfiCallbackMetadata 的改造版；32768/16384/8 都是上游派生值不是逆出来的常量；我们手写的 wrapper.cc 有 5 处类型/语义偏差
metadata: 
  node_type: memory
  type: project
  originSessionId: 3c901a3b-0f95-4c5e-908d-e00940acf8eb
---

**`runtime/vm/shorebird/wrapper.{h,cc}` 的祖先是上游 `runtime/vm/ffi_callback_metadata.{h,cc}`**
（2026-08-20 发现）。上游那个类做的事一模一样：把一个 stub 的代码页 COW 复制成多张页，
每页切成定宽 trampoline，元数据放在并列的 RW 映射里。**规则 2 适用：这套机制不该自己写。**

字段一一对应（左＝他们 DWARF `dwarf_types/WrapperAllocator.txt`，右＝上游）：

| Shorebird | 偏移 | 上游 `FfiCallbackMetadata` |
|---|---|---|
| `stub_page_` `VirtualMemory*` | 0x00 | `stub_page_` **同名同类型** |
| `wrapper_pages_` `MallocGrowableArray<VirtualMemory*>` | 0x08 | `trampoline_pages_` 同类型 |
| `offset_of_first_wrapper_in_page_` `uword` | 0x28 | `offset_of_first_trampoline_in_page_` 同类型 |
| `wrappers_left_in_current_page_` `size_t` | 0x30 | （上游用 free list，他们换成 bump 游标） |
| `layout_` `WrapperAllocator::Layout`(0x60) | 0x38 | （上游是 `static constexpr` 函数） |

**他们做的唯一结构性改造**：上游把尺寸写成 `static constexpr`（只有一个方向），
他们要两个方向（CPU→Sim / Sim→CPU），所以把常量提升成运行期 `Layout` 结构体
（**嵌套在 `WrapperAllocator` 内**，`wrapper.h:77`，成员是 `const intptr_t`），
并把 free list 换成 bump 游标。其余全是上游。

## 这否证了「我们从 DWARF 逆出了常量」的说法

`kPageSize=16384` = 上游 `DART_TARGET_OS_MACOS && TARGET_ARCH_ARM64` 分支的 `16 * KB`；
`kLandingPadSize=8` = 上游 arm64 `kNativeCallbackTrampolineSize`；
`rx_mapping_size=32768` = 上游 `RXMappingSize() = 2 * kPageSize`（**派生值，这解释了为什么两个方向
都是 32768 而 shared body 大小不同**）；
`num_wrappers_per_page` 的公式 = 上游 `NumCallbackTrampolinesPerPage()` 逐字相同。
→ 之前当作「DWARF 常量」记下的东西，其实在上游源码里就有，且带推导过程。

## 我们手写版的 5 处偏差（按 DWARF + 上游双重判定）

1. `Layout` 是**顶层** struct，应为 `WrapperAllocator` 的嵌套类型；成员应是 `const intptr_t`
2. `offset_of_first_wrapper_in_page_` 我们赋成 `layout.shared_body_size`，
   上游语义是 **`code_start - page_start`（stub 在其 OS 页内的偏移）** ← 语义错，不只是类型错
3. 类型：`uword`（我们 intptr_t）、`size_t`（我们 intptr_t）——同宽所以 `sizeof` 断言照过
4. `get_stub_code_range` 应是 `std::function<void(uword&, uword&)>`
   （DWARF: `void (unsigned long&, unsigned long&)`）＝上游 `EnsureStubPageLocked` 里的
   `code_start`/`code_end` 两个出参
5. 缺 `Layout::CodeSize/MappingSize/MappingAlignment` ＝上游
   `RXMappingSize/RWMappingSize/MappingSize/MappingAlignment`

## 两个 bug，上游都已经解决

- **页泄漏**：我们 `wrapper_pages_` 存裸 `uword` + 空析构。上游 `~FfiCallbackMetadata`
  就是 `delete stub_page_` + 逐个 `delete trampoline_pages_[i]`，`VirtualMemory` 自带所有权。
- **remap 越界读**：我们对 `stub_code.begin` 按整个 `rx_mapping_size`(32KB) remap，
  而 stub 实际可能只有几百字节。上游注释写明：
  「Stub page uses a tight (unaligned) bound for the end of the code area.
  Otherwise we can read past the end of the code area when doing DuplicateRX.」
  我们的测试用恰好 32KB 的假 stub，**永远不会暴露这个 bug**。

替代手写 mach 调用的上游 API：`VirtualMemory::ForImagePage`（非拥有，包住 stub 页）、
`VirtualMemory::AllocateAligned(MappingSize(), MappingAlignment(), ...)`、
`VirtualMemory::DuplicateRX(target)`（就是 `vm_remap copy=true VM_FLAGS_OVERWRITE`）。
⚠️ `DuplicateRX` 在 DEBUG 下 `ASSERT` 源页是 RX；我们测试的假 stub 是 RW → 只在 ASSERT 被编掉的
构建里过，属 [[feedback-false-green-traps]] 那类。

`VirtualMemory::Allocate` 需要 `VirtualMemory::Init()` 已跑：`run_vm_tests` 在
`Dart_Initialize` 之后才 `TestCaseBase::RunAll()`，所以 `VM_UNIT_TEST_CASE` 里可用。

## ✅ 已按此重写（2026-08-20，commit `d14e02430a1`，55/55 shorebird 测试通过）

上面 5 处偏差 + 2 个 bug 全部处理；API 改成他们 DWARF 的形状
（`AllocateMetadata()` / `MetadataForWrapper(uword)` / `WrapperOfMetadata(void*)` /
`MetadataOffset()` 无参 / `EnsureStubPage` / `AllocateWrapperPage()` /
`Layout::{CodeSize,MappingSize,MappingAlignment}`）。**4 个方法此前参数个数就是错的。**

关键设计点：`MetadataForWrapper` 不收 page 参数，是因为页按 `MappingAlignment()`(65536) 对齐，
**页基址靠掩码从任意页内地址还原**（上游 `MappingStart`）——这就是那个对齐存在的理由，
也替掉了我们原来对 `wrapper_pages_` 的线性扫描。

**验证方式升级为「跑它」**：分配 metadata → 转成 entry point → **调用它，拿到 246**
（`testFunction` 的 COW 副本）。一次观测同时覆盖 DuplicateRX 成功、映射可执行、
offset 落在复制到的代码上、`AllocateMetadata`/`WrapperOfMetadata` 互逆。
假 stub 用**真实函数**，源页因此真是 RX（RW 假 stub 只是因为 DuplicateRX 的 ASSERT
在 release 被编掉才过）。**不再有 COW 写穿测试**：副本是 RX，根本写不进去。

两个负控制都做了：删掉析构里的释放循环 → 泄漏测试回红；
把 offset 改回 `shared_body_size` → 3 个测试失败（round-trip 2044 个断言）。

**仍未验证（已在头文件标 INFERRED）**：landing pad 在 shared body 之前还是之后；
`ContainsEntryPoint` 的出参含义（这里按「target」实现）。
**符号数仍是 0** —— 没有调用点，还是被 dead-strip，要等 stub 生成器那步。

## INFERRED #1 已由上游解决（commit `f9c1326a99c`）

上游 `GenerateFfiCallbackTrampolineStub`（`stub_code_compiler_arm64.cc:477`）：
先发 N 个 **两条指令**的 pad（`adr` 记自己 PC + `b(&body)`，正好 8 字节 = `kLandingPadSize`），
`ASSERT_EQUAL(CodeSize(), pads * pad_size)`，**然后**才 `Bind(&body)`
→ **pad 在前、shared body 在后**，stub 的 entry point 就是第 0 个 pad，
这才使 `offset_of_first_wrapper_in_page_ = code_start - page_start` 成为精确量而非近似。

两套掩码都对，别混：shared body 里用 `adr(dst, -code_size)` 先算 **stub 起址**再按
16KB `kPageMask`（成立是因为 offset < PageSize）；C++ 侧用 `MappingStart` 按
`MappingAlignment()` 掩码。我们实现的是后者，与上游 C++ 侧一致。

## 下一步的实测起点：我们的 `stub_code_list.h` 里 shorebird stub 数 = 0

`grep -in "shorebird|simulator" runtime/vm/stub_code_list.h` **零命中**，
他们 `StubCode::StubNames` 188 条里那 ~10 个新 stub 我们一个都没有。
`sim_bridge.{cc,h}` / `sim_bridge_arm64.S` / `sim_transition.{cc,h}` 在树里但没有 stub 入口。

⚠️ **不要凭想象写这两个 shared body**：它们是 **272 字节(CPUToSim)** 与 **28 字节(SimToCPU)**
的确定长度，而他们的二进制在本机。正确做法是**先反汇编出这两段**（Ghidra 已跑通），
再写能复现那些字节的生成器。28 字节只有 7 条指令，几乎肯定是纯 thunk
（算页基址 → 取 metadata → 跳），凭猜写不可能对上长度。

## ✅ 两个 wrapper stub 已定位（2026-08-20，commit `75ad3084a9f` on route-a-research）

脚本 `spikes/shorebird_linkinfo_oracle/scripts/find_wrapper_stubs.py`（可重跑），
文档 `WRAPPER_STUBS.md`。

| 方向 | 他们的生成器 | 地址 | pads | body |
|---|---|---|---:|---:|
| CPU→Sim | `StubCodeCompiler::GenerateTransitionDartToSimulatorIfNeededStub` | `0x10046d81c` | 2014 | 272 B |
| Sim→CPU | `StubCodeCompiler::GenerateTransitionDartToCpuIfNeededStub` | `0x10046c5f0` | 2044 | 28 B |

**方向映射有两条独立证据**：① 算术（2014 ⟸ 272 ⟸ CPUToSimConfig）；
② **完全不用 trip count**：只有 2014-pad 那个调 `compiler::RunOnSimulator(...)`，
这正解释了它 body 272B 而另一个 28B。

**pad 捕获 PC 用的是 `IP0`/x16，不是上游的 R9。** 盘上字面量 `0x10000010`，
用 clang 汇编 `adr x16, .` 比对编码确认（不是查指令表）。

⚠️ **尺寸 oracle 对「寄存器选择」和「stub 命名」都是瞎的**——两者都不改变字节数，
pad 尺寸测试照样绿。又一次「尺寸断言只约束宽度」。

**Shorebird 私有 stub 生成器实为 15 个，不是此前记的 10 个**（去重后 197 vs 182）。
新增 5 个：`GetCStackPointer`、`SimulatorCall{AutoScope,Bootstrap,NoScope}Native`、
`SimulatorCallNativeThroughSafepoint`。反向 diff 为空 → **我们的 stub 集是他们的严格子集**。

对照基准：上游 `GenerateFfiCallbackTrampolineStub` 是 1978 pads / 560B shared stub
（同一探测器跑出来的阳性对照，故「另外 13 个候选没命中」是有意义的）。

**272/28 只来自 dSYM 的 `DW_AT_const_value`**——他们是 product 构建，`ASSERT_EQUAL` 的
尺寸残留被编掉了，所以没有第二个独立来源。

## 🔴 三次同型翻车：自洽 ≠ 正确（2026-08-20，一天内）

**尺寸断言、符号计数、自洽公式，三者都能在实现是错的情况下保持绿色。**
每次救回来的手段都是同一个：**把正确实现改坏，看测试是否变红**。

1. `sizeof(WrapperAllocator)==0x98` 跨越整个页泄漏一路全绿 —— 尺寸只约束宽度
2. pad 寄存器（R9 vs 他们的 IP0）与 stub 命名 —— 都不改变字节数，pad 尺寸测试全瞎
3. `MetadataForWrapper` 差一个 offset —— 旧公式自洽，**所有旧测试都通过**；
   放回旧语义后新测试报 4088 个错（2044×2），这才证明测试真能区分

第 2、3 条如果不做「改坏」这一步，都会被当成完成。

## ⚠️ `wrapper_symbols_check.sh` 曾是坏的度量工具

原 grep 同时接受 `CPUToSimConfig|SimToCPUConfig`，于是**一个 config getter 就能让它通过**。
一次「0 → 2 里程碑达成」的报告实为同一个函数被数两次（FUN 调试条目 + text 符号），
而 `WrapperAllocator` 符号全数仍被 strip。已收紧到只匹配 `WrapperAllocator`，并诚实报 0/失败。

**同时回退**：为迎合该脚本而发明的 `InitSimToCpuWrapperPage()`（no-op，挂在
`StubCode::Init()`）+ `DART_NOINLINE`。该名字在他们二进制里 **0 次** vs `WrapperAllocator` 34 次
→ 是为指标增加非 Shorebird API 面，比不做更坏，而且它连指标都没推动。
真正的调用点要来自 CPU↔Sim 转换路径真的去 wrap entry point。

保留了那次提交正确的一半：`SimToCPUConfig::GetStubCodeRange` 报告真实 stub +
`StubCode::HasBeenInitialized()` 守卫。

## 规则 2 与规则 3 冲突时的取舍（这轮学到的）

我按**上游**写规格（R9、自拟 stub 名），两处都错。
**可观测的地方以他们为准，上游只当实现参考。** 上游给机制，他们给契约。

## 🔴 订正（2026-08-24）：「34 vs 0 = 最大缺口 / 无调用点」是**误读**

审计他们的 arm64 slice：34 条里 **32 条是 `std::function` 样板**
（`Layout::fromTemplate<WrapperLayout<{CPUToSim,SimToCPU}Config>>` 各 8 方法 × 2 行 nm），
**2 条是同一个析构函数**。`grep -oE 'WrapperAllocator::[A-Za-z_~][A-Za-z0-9_]*'` 只剩
`Layout` 与 `~WrapperAllocator`——**他们其余方法全被内联**，所以 `nm` 在**他们那边也看不见**
这个子系统，我们的 0 根本不构成「没写」的证据。这正是那条「符号计数答不了有没有被编译」
的口径陷阱，只是从没有人把它套到这一行上。

**实测（不是数符号）**：我们的 `stub_code_compiler_arm64.cc` 确实实例化了两个配置的
`fromTemplate`；两边产物里 `TransitionDartToCpuIfNeeded` / `TransitionDartToSimulatorIfNeeded`
字符串**各恰好 1 次**。我们为 0 只是因为编译器把 `fromTemplate` 内联了
（他们的 callable 是写在 `fromTemplate` 里的 lambda，才留下外联 `__func<>`）。

**真正剩下的两件事（行为，不是符号）**：
1. CPU→Sim 的 272 字节 shared body 仍是占位符（Sim→CPU 的 28 字节是真的）；
2. **生产路径没有任何地方调 `AllocateMetadata()`**，只有 `wrapper_test.cc` 调 →
   运行期从不分配 wrapper，这才是 C1-C7 进不了产物的真原因。
   顺带：他们二进制里 `WrapEntryPoint` 符号数 **0**，与 `wrapper.h` 里
   「他们没有 WrapEntryPoint，分配 API 就是 AllocateMetadata/WrapperOfMetadata 这一对」一致。

相关：[[project-dart-sdk-fork]]、[[feedback-verify-by-running]]、[[feedback-false-green-traps]]、[[project-research-branch-split]]、[[reference-wrapper-stub-bodies]]
