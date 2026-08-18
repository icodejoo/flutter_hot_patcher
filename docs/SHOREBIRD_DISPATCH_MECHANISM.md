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

## 3. 转换点：一族魔数 BRK 伪指令

`DecodeSimulatorToNativeTransition` (@0x7d7bfc)：

```asm
ubfx w8, w1, #5, #16      ; 取指令 bits[20:5]，即 HLT/BRK 的 imm16
cmp  w8, #0xb128          ; 0xb128 … 0xb130 共 7 个魔数，各对应一种转换
...
; imm == 0xb130 时：
ldr x21, [x19, #0x80]
adr x25, 0x7d845c         ; → dart::RunDartOnCPU
; 默认：
adr x0,  0x7d844c         ; → dart::CallClangCodeWithSimulatorArgs
```

上游 Dart 本来就有这个手法，只有一个码：

```cpp
// runtime/vm/constants_arm64.h:1338
static constexpr int32_t kSimulatorRedirectCode = 0xca11;   // "call"
static constexpr int32_t kSimulatorRedirectInstruction =
    HLT | (kSimulatorRedirectCode << kImm16Shift);
```

Shorebird 把它**扩成一族**（0xb128–0xb130），每个码是一种转换语义。
这是可以照做的：加自己的码，在 `DecodeSpecial` 里分派。

## 4. 关键：CPU→Simulator 靠切换 `Thread` 缓存的 stub 入口

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

`ldur [ptr, #7]` 是 Dart 的惯用法：对象指针带 `kHeapObjectTag = 1`，
`+7` 即未加 tag 时的偏移 8，也就是 `Code::entry_point_`。

**所以进入/退出模拟器模式的动作，就是改写 `Thread` 里那 7 个缓存的 stub 入口地址**
（原生版 ↔ 模拟器版），退出时还原。

### 这解决了 W^X 的疑问

iOS 禁止新建可执行页，我原以为必须为补丁函数造 trampoline。**实际不需要**：
模拟器版 stub 是**预先编译进引擎**的，切换只是重指 `Thread` 字段，
不产生任何新代码。`WrapperAllocator` 分配的是这些 wrapper 的**元数据/布局**
（`AllocateMetadata` 里通过虚调用取回一对 out 参数，再按全局对齐值做掩码对齐），
不是可执行内存。

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

## 7. 未解与下一步

- `WrapperAllocator` 分配的元数据具体布局（`SimToCPUConfig` vs `CPUToSimConfig`
  差在哪）尚未拆完 —— `dart::shorebird::` 只导出 2 个符号，其余全内联，
  需要 Ghidra 的反编译与交叉引用才能继续。
- 0xb128–0xb130 这 7 个码各自的语义还没一一对上。
