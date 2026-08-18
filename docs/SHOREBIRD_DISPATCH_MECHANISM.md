# Shorebird 双模执行机制 —— 对照分析

> 2026-08-18。目的：搞清 Shorebird 如何让**未改动的代码保持原生 AOT、被改动的函数走
> ARM64 模拟器**，以便我们在自建引擎里实现等效能力。
>
> 方法：符号表 + 反汇编对照，样本是本机 Shorebird SDK 自带的
> `Flutter.xcframework/ios-arm64`（真机 arm64）及其 dSYM。
> **只分析机制，不复制代码。**
>
> 注意：dSYM 的 `__text` 只有段头没有字节，反汇编必须用真实二进制，
> 地址与 dSYM 符号一致。

---

## 1. 是双向的，不是单向逃逸

```
dart::Simulator::Transition                     抽象基类（有 vtable）
  ├─ dart::SimulatorToCPU  :: IsSimulating(uword) const / ToCString() const
  └─ dart::CPUToSimulator  :: IsSimulating(uword) const / ToCString() const
```

配套符号：

```
dart::Simulator::DecodeSimulatorToNativeTransition(dart::Instr*)
dart::RunDartOnCPU(unsigned long long, dart::Simulator*)
dart::CallClangCodeWithSimulatorArgs(unsigned long long, dart::Simulator*)
dart::Exceptions::JumpToCPUFrame(uword, uword, uword, dart::Thread*)
dart::shorebird::WrapperAllocator::AllocateMetadata()
dart::shorebird::WrapperLayout<dart::shorebird::SimToCPUConfig>
dart::shorebird::WrapperLayout<dart::shorebird::CPUToSimConfig>
```

栈上可以出现「原生帧 → 模拟帧 → 原生帧」交替，每层用一个 `Transition` 记录方向。

## 2. `IsSimulating` 是记账，不是分派

两个子类各 16 字节，只差比较极性：

```asm
; SimulatorToCPU::IsSimulating(uword pc) const   @0x7d85e8
ldr  x8, [x0, #0x30]      ; this+0x30 = 边界 PC
cmp  x1, x8
cset w0, eq               ; return pc == boundary
ret

; CPUToSimulator::IsSimulating(uword pc) const   @0x7d9794
ldr  x8, [x0, #0x30]
cmp  x1, x8
cset w0, ne               ; return pc != boundary
ret
```

用途是**栈回溯时判断某一帧当时以哪种模式执行**（profiler / 异常展开 / 调试），
不参与"这次调用该走哪条路"的决策。

## 3. 转换点：一族魔数 HLT 伪指令

`DecodeSimulatorToNativeTransition` (@0x7d7bfc) 取指令的 `imm16` 分派：

```asm
ubfx w8, w1, #5, #16      ; bits[20:5] = HLT/BRK 的 imm16
```

九个码的完整语义（反编译得出）：

| imm16 | 目标（`x21`） | 落点 | PC 推进 | 语义 |
|---|---|---|---|---|
| `0xb128` | `sim[0x48]` | `CallClangCodeWithSimulatorArgs` | +4 | 调 C++ |
| `0xb129` | `sim[(next_instr>>5)&0x1f]` | 同上 | **+8** | 调 C++，**寄存器号编码在下一条指令** |
| `0xb12a` | `sim[0x80]` | 同上 | +8 | 调 C++ |
| `0xb12b` | 固定 thunk `0x76b02c` | 同上 | +4 | 固定 thunk |
| `0xb12c` | 固定 thunk `0x76b408` | 同上 | +4 | 固定 thunk |
| `0xb12d` | `sim[0x80]` | **`RunDartOnCPU`** | 不变 | **在真实 CPU 上跑 Dart** |
| `0xb12e` | `sim[0x28]` | `CallClangCodeWithSimulatorArgs` | +4 | 调 C++ |
| `0xb12f` | 固定 thunk `0x76a424` | 同上 | +4 | 固定 thunk |
| `0xb130` | `sim[0x80]` | **`RunDartOnCPU`** | 不变 | 同 `0xb12d`，另一变体 |

要点：

- **只有 `0xb12d` / `0xb130` 落到 `RunDartOnCPU`**（模拟器→原生 Dart，热更新真正需要的）。
  其余七个落到 `CallClangCodeWithSimulatorArgs`（模拟器→VM 的 C++ 运行时），
  上游用一个 `kSimulatorRedirectCode` 就干这事，他们按调用约定拆细了。
- `+8` 的两个码，**下一条指令是操作数**（`0xb129` 从 `*(instr+4)>>5 & 0x1f` 取寄存器号）。
- 落到 `RunDartOnCPU` 的两个**不推进 PC** —— 控制权直接转交，不回模拟器译码。

上游对照：

```cpp
// runtime/vm/constants_arm64.h:1338
static constexpr int32_t kSimulatorRedirectCode = 0xca11;   // "call"
static constexpr int32_t kSimulatorRedirectInstruction =
    HLT | (kSimulatorRedirectCode << kImm16Shift);
```

`RunDartOnCPU` 本身极小 —— 跳到一个预编译 stub 的入口：

```c
(**(code **)(DAT_00b5ab10 + 7))();    // +7：从 tagged 指针读 Code::entry_point_
```

分派器里还能看到日志格式串与双重 setjmp：

```
"[%s] Calling %s at 0x%llx on the CPU\n"
__setjmp();                             // 挂两条链：
*(param_1 + 0x350)   = &buf;            //   Simulator 上
*(thread    + 0x20)  = &buf;            //   Thread 上
buf.vtable = &DAT_00b41730;             //   = Simulator::Transition 的 vtable
```

**那个 setjmp buffer 本身就是一个 `Transition` 对象**（vtable 落在
`SimulatorToCPU` 的 `0xb41740` 前 16 字节，即基类布局）。这解释了
`IsSimulating` 为什么是虚函数：异常展开沿 setjmp 链走，每个节点报告
自己这一段是哪种执行模式。我们的 A2 只挂了一条链。

## 4. 关键：两个方向各自怎么进入

### 4.1 CPU→Simulator：改写 `Thread` 缓存的 stub 入口

`CPUToSimulator::~CPUToSimulator()` (@0x7d960c) 在做恢复，据此反推构造：

```asm
x8 = [x0+0x20]                    ; 保存的 Thread*
str xzr, [x8, #0x8d8]             ; 清标志位
; 7 组相同模式：
ldr  x10, [x9 + off]              ; x9 = 0xb5a2d0，一张 Code* 表
ldur x10, [x10, #0x7]             ; +7：从 tagged 指针读 Code::entry_point_
str  x10, [x8, #N]                ; 写回 Thread 的缓存入口
                                  ; N ∈ {0x208, 0x268, 0x908, 0x910, 0x918, 0x920, 0x928}
```

进入/退出模拟器模式，就是**把 `Thread` 里那 7 个缓存的 stub 入口在
原生版 ↔ 模拟器版之间对调**，析构还原。

### 4.2 wrapper 从哪来：`vm_remap`，不是生成代码

这是整个设计最关键的一手。`WrapperAllocator::AllocateMetadata()` (@0x7d0728)
调的是 Mach VM 原语（`vm_remap` / `vm_map` / `munmap` / `mach_task_self`）：

```c
// 先通过虚调用取回本 Config 的模板地址范围（两个 out 参数）
(**(code **)(*layout + 0x30))(layout, &tpl_start, &tpl_end);
page_base = tpl_start & -PAGE_SIZE;
size      = tpl_end - page_base;
offset_in_page = tpl_start - page_base;      // 存入 param_1[5]

cur_prot = max_prot = 5;                      // VM_PROT_READ | VM_PROT_EXECUTE
vm_remap(
    /* target_task    */ mach_task_self(),
    /* target_address */ &out_addr,
    /* size           */ (tpl_size + PAGE-1) & -PAGE,
    /* mask           */ 0,
    /* flags          */ 0x4000,               // VM_FLAGS_ANYWHERE
    /* src_task       */ mach_task_self(),
    /* src_address    */ tpl_page_base,
    /* copy           */ 1,
    /* cur_protection */ &cur_prot,            // 5 = R|X
    /* max_protection */ &max_prot,            // 5 = R|X
    /* inheritance    */ 2                     // VM_INHERIT_NONE
);
```

错误路径里的字符串暴露了它的出处：

```
"../../flutter/third_party/dart/runtime/vm/virtual_memory_posix.cc"
"munmap failed: %d (%s)"
```

**所以这是扩展上游 Dart 的 `VirtualMemory`，改动落在上游已有文件里。**

机制总结：

1. 引擎 `__TEXT` 里有**预编译的 wrapper 模板**（已签名、可执行），
   两个方向各一份（`SimToCPUConfig` / `CPUToSimConfig` 只是模板不同）
2. `vm_remap(copy=1, prot=R|X)` 把模板**重映射到新地址** ——
   权限继承自源映射，**不创建任何新的可执行页**，因此不受 iOS W^X 限制
3. 每份副本配一块可写 metadata（`malloc(0x30)` 描述符 + `vm_map` 的数据页）
4. 补丁函数的 `Code::entry_point_` 指向它自己那份 remap 副本，
   副本从相邻 metadata 读真实目标地址

**没有数量上限，模板只需一份。** iOS 上不能新建可执行页，但可以把已有的
可执行映射 remap 出任意多份 —— 这是 Darwin 上的既有手法。

### 4.3 上游已有完整蓝本：`FfiCallbackMetadata`

**`vm_remap` 这一步我们不用写 —— 上游 Dart 已经实现并在生产中使用。**

```cpp
// runtime/vm/virtual_memory.h
// Duplicates `this` memory into the `target` memory. This is designed to work
// on all platforms, including iOS, which doesn't allow creating new
// executable memory.
bool VirtualMemory::DuplicateRX(VirtualMemory* target);
```

`runtime/vm/virtual_memory.cc:52` 的实现就是 `vm_remap(copy=true, R|X)`，
注释与我们的推断一字不差。单测已存在：
`VM_UNIT_TEST_CASE(DuplicateRXVirtualMemory)`（`virtual_memory_test.cc:100`）。

差别仅在 flags：上游 `VM_FLAGS_FIXED | VM_FLAGS_OVERWRITE`（目标地址自备），
Shorebird `VM_FLAGS_ANYWHERE`（内核选址）。

更重要的是，**上游 `runtime/vm/ffi_callback_metadata.{h,cc}` 解决的是同一个问题**
（FFI 回调在 iOS AOT 下需要每回调一个 trampoline，而不能生成代码），
`ffi_callback_metadata.cc:118` 正是 `stub_page_->DuplicateRX(new_page)`。
Shorebird 的 `WrapperAllocator` / `AllocateMetadata` 是照它做的，命名都对得上。

其头部注释还回答了最难的那个问题 —— **remap 出来的副本怎么知道哪块 metadata 是自己的**：

> In the past, callbacks were primarily identified by an integer ID... The
> trampolines are allocated in pages. On iOS in AOT mode, we can't create new
> executable memory, but we can duplicate existing memory. When we were using
> numeric IDs to identify the trampolines, each trampoline page was different,
> because the IDs were embedded in the machine code. So we couldn't use
> trampolines in AOT mode. **But if we key the metadata table by the trampoline
> pointer, then the trampoline just has to look up the PC at the start of the
> trampoline function, so the machine code will always be the same.** This
> means we can just duplicate the trampoline page.

即：**副本以自身地址为身份**，运行时读自己的 PC 去查 metadata 表。
所以模板机器码恒定，一份模板可以 remap 出任意多份。

这把实现风险降了一个数量级：原语、模式、单测上游都有，我们只需按同一模式
为「模拟器 ↔ 原生」两个方向各写一份模板与一张表。

## 5. 与我们 A2 的对照

| 能力 | Shorebird | 我们（`~/dart/sdk` A2/A5/A7/B2/B4） |
|---|---|---|
| 模拟器 → 原生 | `SimulatorToCPU` + `RunDartOnCPU` | ✅ `ShorebirdSimToCpuCall`（内联汇编 + link table）|
| **原生 → 模拟器** | `CPUToSimulator`：切换 Thread 的 7 个 stub 入口 | ❌ **没有** |
| 转换点识别 | 一族魔数 BRK（0xb128–0xb130）| BLR/BL 拦截 + link table 查表 |
| 统一 Transition 抽象 | ✅ 含 `IsSimulating(pc)` 供栈回溯 | ❌ 无 |
| 异常跨模式传播 | 双向（`JumpToCPUFrame` + setjmp）| 单向（`SimulatorSetjmpBuffer`）|
| 无补丁时是否模拟 | 不模拟，纯原生 | **也模拟**（A1 无条件强开）|
| 启动阶段 | 正常 | 需 `icount > 5000万` 阈值绕开 |

## 6. 我们要做什么

按依赖顺序：

1. **实现 `CPUToSimulator` 等效物**：保存 `Thread` 的 stub 入口 → 换成模拟器版 →
   析构还原。需要先在引擎里预编译一套模拟器版 stub。
2. **去掉 A1 的无条件强开**，改为「仅当补丁被加载时进入模拟器模式」。
   这依赖第 1 条 —— 没有 CPU→Sim 入口就只能一开始就在模拟器里。
3. **补齐 Transition 抽象**，让 profiler / 异常展开能正确识别混合栈。
   这大概也是我们那个 5000 万指令启动阈值的根因：启动阶段栈上模式混杂，
   没有记账就会崩。
4. 引擎侧接线：目前我们的引擎**从不调用** `Dart_ShorebirdLoadVmcode` /
   `SetPendingVmcodeFile`，link table 从未填充、SimToCpu 阈值停在 `~0ULL`
   （永不触发）。这是为什么之前 benchmark 上打不打补丁都是 70–74 ns/迭代。
   私有 API 清单里的 `Shorebird_SetBaseSnapshots` 我们也没实现。

## 7. 实现路径（按依赖顺序）

| # | 步骤 | 依据 | 验证方式 |
|---|---|---|---|
| 1 | ~~加 `vm_remap` 能力~~ **上游已有** `VirtualMemory::DuplicateRX` | `virtual_memory.cc:52`，单测 `DuplicateRXVirtualMemory` | 已有单测；FFI 回调在 iOS 生产中依赖它 |
| 2 | 两份 wrapper 模板（汇编），对应两个方向 | `SimToCPUConfig` / `CPUToSimConfig` | 单测：模板可被 remap 且可跳入 |
| 3 | 分配器：remap 模板 + 配 metadata | `AllocateMetadata` 的结构 | 单测：分配 N 份互不干扰 |
| 4 | 魔数 `HLT` 族（立即数我们自选，不必与他们相同） | 上游只有 `0xca11` | 单测：模拟器正确分派 |
| 5 | `Transition` 抽象 + 双 setjmp 链 + `IsSimulating(pc)` | §3 末尾 | 单测：混合栈上抛异常能正确展开 |
| 6 | 去掉 A1 无条件强开，改为「仅补丁在场时进模拟器」 | 依赖 1–5 | 真机：无补丁时热函数应回到原生速度 |
| 7 | 引擎侧接线：调用 vmcode 加载、传基线映射 | 当前引擎从不调用，见 §6 | 真机 OTA + A/B |

**原本判断第 1 步是全局风险点，现已排除**：`vm_remap` 路径是上游实现、
上游单测覆盖，且 FFI 回调在 iOS 生产中就依赖它。真正的工作从第 2 步开始，
而第 2–3 步可以直接照 `ffi_callback_metadata.{h,cc}` 的模式写。

## 8. 仍未拆的

- `0xb128`/`0xb12a`/`0xb12e` 三个码取目标的槽位（`sim[0x48]` / `sim[0x80]` /
  `sim[0x28]`）分别对应 Simulator 的哪个成员，尚未一一对上 —— 不影响我们自行选型。
- 三个固定 thunk（`0x76b02c` / `0x76b408` / `0x76a424`）的具体职责。
- `Thread` 那 7 个偏移（`0x208`/`0x268`/`0x908`–`0x928`）对应哪些 stub 字段，
  需要用我们自己的 `Thread` 布局比对确定 —— 实现时按字段名选，不照搬偏移。

## 9. 实现进展

### C1：`SimBridge` —— CPU → Simulator 方向（**已完成，单测通过**）

`~/dart/sdk` commit `348397748e8`。新增
`runtime/vm/sim_bridge.{h,cc}` 与 `runtime/vm/shorebird_cpu_to_sim_test.cc`。

给一个位于只读（补丁）映射里的目标地址，返回一个**原生可调用**的地址；
调用它即进入模拟器执行该目标并返回结果。布局照 `FfiCallbackMetadata`：

```
[RX] 模板页   trampoline i:  adr x9, #0            ; 自身地址
                             b   body
             body:           x10 = x9 & ~(RegionAlignment()-1)
                             x10 += EnterFnOffset()
                             x11 = [x10]           ; 从 RW 半区取 helper 指针
                             x4  = x9              ; 身份，作第 5 参数
                             br  x11
[RW] 数据页   [0]   uword  EnterSimulatorFromNative
             [1..] uword  targets[TrampolinesPerRegion()]
```

模板经 `DuplicateRX`（即 `vm_remap`）复制，副本字节完全相同，
身份与 helper 地址都由自身 PC 推出。

**单测 5 项全过**，其中两项是承重的：

- `NativeCallEntersSimulator` —— 真实原生代码通过普通 C 函数指针调用
  remap 出来的 trampoline，落进模拟器，执行一段**不可执行内存**里的代码，
  返回正确值
- `ManyTrampolinesDistinct` —— 同一个 remap 区域里 4 个 trampoline
  各自解析到自己的目标，坐实「机器码相同 + 按 PC 索引」这个设计

A2 既有单测与上游 `DuplicateRXVirtualMemory` 均无回归。

#### 过程中踩的三个坑（都是跑出来的，不是读出来的）

1. **`constexpr` 变量不能在类体内调用本类的 `constexpr` 成员函数** ——
   类在那里还不完整。改成 `constexpr` 函数即可，这也是
   `FfiCallbackMetadata` 写成函数形式的原因。
2. **`DuplicateRX` 按 `source->size()` 重映射** ——
   把整个 template region（含 RW 半区）传进去，会把目标区域全部设成 R|X，
   随后写 helper 指针就 bus error。模板必须只覆盖 RX 半区。
3. **`LDR` 的 imm12 是 12 位缩放立即数**，最大可达 `4095*8 = 32760`，
   而 `EnterFnOffset()` 是 32768 —— 直接编码会溢出到相邻字段，
   生成一条完全不同的指令。`ASSERT` 在 release 构建是空操作所以没拦住，
   崩溃 PC 恰好是 trampoline 自己的指令字节才暴露出来。
   改用 `ADD imm12 lsl #12` + `LDR`，并换成 `static_assert`。

#### 已知边界

当前模板是**运行时写出来再 mprotect 成 RX** 的 —— macOS 允许，**iOS 不允许**。
生产必须让模板来自已签名 `__TEXT` 里的代码，即一个 `StubCodeCompiler` stub，
与 `FfiCallbackMetadata` 用 `StubCode::FfiCallbackTrampoline()` 的做法一致。
这是下一个增量（C2）。
