# R2/R1 spike级探索 —— 对象池精确比对可行性 + CanonicalName 捷径证伪

**背景**：`PRODUCTION_LINKER_SPEC.md` 的 R1(Kernel CanonicalName 实例级对齐)、R2(对象池内容精确
比对) 是评审找出的最基础/最安全关键的硬缺口。用户明确态度："宁可不用也不能出问题"——这轮
在**不投入 1-2 人月正式建 Kernel 层 linker**的前提下（仍等 iOS W^X 门），先做 spike 级探索：
这两条硬缺口**能不能做出来、大概怎么做**，而非继续搭功能覆盖用例。

## R2（对象池内容精确比对）—— 可行，找到具体机制

**问题**：当前 diff_linker 只 `objdump -d`（反汇编代码段），对象池数据从不解析；`normalize()`
把池 slot 通配成 `POOL(%r15)`，S1 发现——改 `const fee=0.07→0.08` 这类改动只体现在池内容、
指令一字不变，被完全漏判。

**探索**：Dart VM 有 `--disassemble --code_comments` 诊断标志（`support_disassembler` 开关，
**只在非 product 的 `gen_snapshot`（不是 `gen_snapshot_product`）里可用**）。跑
`gen_snapshot --disassemble --code_comments --snapshot-kind=app-aot-elf ...` 会在 stdout 产出：

1. 每个函数的反汇编（同 objdump，但带 IL 级注释）；
2. 一份独立的 **`ObjectPool len:N { [pp+0xNN] <内容> }` 完整列表**——每个 slot 的内容都列出来，
   Field/Class/字符串等给可读描述，**数值常量（如 double）给原始 IEEE754 位模式**（标注 `(raw)`）。

**实测验证（`pool_double.dart`，S1 的确切复现场景）**：

- base（`const fee=0.07`）：`total()` 里 `movsd xmm2,[pp+0x58b7]`；池列表 `[pp+0x58b7] 0x3ff11eb851eb851f (raw)`
  → 解码 = **1.07**（`1+0.07` 编译期常量折叠）。
- patch（`fee=0.08`）：**同一条指令逐字节相同**（`[pp+0x58b7]`，坐实 S1 漏判在当前 objdump-only
  工具下确实无法区分）；但该 build 自己的池列表 `[pp+0x58b7] 0x3ff147ae147ae148 (raw)` → 解码
  = **1.08**。

**结论**：只要在各自 build 里查"这条池引用指令对应的 slot，在这份快照自己的池列表里内容是什么"，
就能拿到常量真实值、跨版本比对，**不需要逆向对象池的二进制内存布局**——VM 自带的诊断反汇编器
已经把它解析成文本了。这条路可行，且比"自己解析快照二进制里的池数据结构"轻量得多。

**未做的部分（诚实边界，非本轮范围）**：
- 未把这条机制接进 diff_linker（会员=真正开发一套新工具，属于 R1-R9 那 1-2 人月的正式研发，
  不是这轮 spike 探索的范围，遵循已定的"iOS 门后再建"顺序）。
- 池列表的 slot 索引本身会随程序改动整体漂移（同 V9 的 pool-slot drift 发现）；本探测靠"各自
  build 查自己的池"绕开了这个问题，但若要做成通用工具，仍需把"哪个函数的哪次访问对应哪个语义
  常量"这件事做扎实（例如靠指令在函数体内的相对位置/访问顺序作为语义锚点，而非 slot 索引）。
- 生产环境是否始终能拿到非 product、`--disassemble` 能跑的 gen_snapshot（这一构建变体体积更大、
  更慢）需要在正式研发时确认——但由于对比在**构建流水线内**做（不是设备上），这不是运行时约束，
  只是 CI 构建时长/产物大小的工程权衡。

## R1（Kernel CanonicalName）—— 探索一条捷径，证伪

**假设**：既然 `gen_snapshot --disassemble` 已经吐出每个函数的完整限定名，会不会顺带给出比
DWARF 更本质的 CanonicalName（库 URI，不含物理文件绝对路径）？

**实测**（复用 P0 探针 `probe_canonical_name/`，liba.dart/libb.dart 撞名 `foo`/`K.m`）：反汇编
输出里函数名仍是 `file:///mnt/c/.../liba.dart_::_foo`——**跟 DWARF 方案是同一套"绝对源文件路径
+ 成员名"表示**，不是 `package:`/库 URI 形式。

**结论（诚实、负面）**：这条捷径**不成立**——`gen_snapshot` 的诊断反汇编器不会免费给出比 DWARF
更好的 CanonicalName。R1 真要做（消除源文件路径代理的残留问题：part 文件移动、pub 版本升级
路径变化，见 P1 NOTES 和 part_case 用例），仍需**解析 Kernel `.dill` 二进制本身**（走 CFE/
kernel-service 的 AST 读取 API，拿库 URI→类→成员的规范路径），这是一块独立、需要单独评估工作量
的工程，不能指望从现有诊断工具白捡。

**2026-07-31 后续（这条"独立工程"已经跑通并正面验证）**：见
`../r1_kernel_dill_probe/NOTES.md`——`package:kernel` 的 `loadComponentFromBinary`
就是现成的 CFE AST 读取 API，不需要自己写解析器；实测 `lib/` 下被 `package:` 引用的库文件
拿到真正的 `package:xxx/yyy.dart` URI，且跨越完全不同的构建目录逐字节稳定（整个包目录搬家
重编译，CanonicalName 不变）——直接解决这里点出的 part 文件移动/路径变化残留问题。

## 对 PRODUCTION_LINKER_SPEC 的更新

- **R2 从"待研究"降级为"已知可行路径"**：用 `gen_snapshot`(非 product) `--disassemble
  --code_comments` 的 ObjectPool 文本列表做池内容比对，是目前验证过的最低风险实现路径。
- **R1 维持"需要 Kernel .dill 解析"的原判断**，排除了"从 disassemble 输出白捡"这个曾经设想的
  捷径，避免生产研发阶段走这条弯路。
