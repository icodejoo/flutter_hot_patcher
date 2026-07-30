# P1 探路：AOT 如何编码实例字段访问

**问题**：给类增删字段会改变对象内存布局。基线 AOT 里访问该类字段的代码，字段偏移
是怎么编码的？增删字段会不会改变访问代码的机器码？这是 V9 的事实地基。

**方法**：两份几乎相同的源码（`probe_base.dart` / `probe_patched.dart`），后者在
类 `Box` 的 `a` 和 `b` 之间插入一个字段 `x`。`writeB(box.b = v)` 的源码两份完全
一样。AOT 编译成快照，反汇编 `writeB`，对比 `box.b = v` 编译出的 store 指令偏移。

跑：`DART_SDK_SRC=/root/dart/sdk ./run_probe.sh`

## 结果（2026-07-30，x86-64，ReleaseX64）

```
[probe_base]    writeB @ ...: mov %rsi,0xf(%rdi)     # b @ offset 0xf
[probe_patched] writeB @ ...: mov %rsi,0x17(%rdi)    # b @ offset 0x17 (+8)
```

同一行源码 `box.b = v`，机器码从 `...0f` 变成 `...17`，偏移 **+8 字节（一个 word）**
——插入的 `x` 把 `b` 往后推了一格。（tagged pointer，rdi = 对象地址|1；
base 布局 header@0..8 / a@8 / b@16 / c@24，offset 0xf=15 对应对象内偏移 16。）

## 两个关键结论

1. **实例字段访问偏移硬编码在机器码里**（load/store 指令的立即数）。字段布局一变，
   偏移立即数就变，访问该字段的函数机器码**逐字节不等价**。
   → 推论：linker 的"逐字节等价判定 + 保守优先"会**自动、完备地**把所有访问变布局
   字段的函数判为不等价、转解释。完备性不需要额外的"找出所有访问者"分析，它等价于
   "逐字节比对是否彻底"——因为漏不掉：访问者的机器码必然带着变化的偏移。

2. **write-only 字段会被 AOT tree-shaking(TFA) 删除**。第一版实验里插入的 `x` 只在
   构造时赋值、之后没人读，被 TFA 删掉了，布局根本没变（`writeB` 偏移仍是 0xf，
   `AllocateObject` 的 size class 参数也没变）。只有被**读取**的字段才进入对象布局。
   → 对 V9 的影响：判断"加字段是否改布局"要看字段是否真被使用；也提示未来 diff 工具
   分析布局变更时，参照的是 AOT 后的实际布局（经过 TFA），不是源码声明的字段集合。

## 遗留观察

- `readB`（纯读返回）在符号表里 `NOT FOUND`——尽管标了 `@pragma('vm:never-inline')`，
  仍被优化掉/未独立成符号。用 `writeB`（有副作用的 store）观察偏移更稳。未深究，
  不影响本探路结论。

## 下一步

P1 只证明了"变布局 → 访问者机器码必变"。但要真正做出 diff linker，先要解决一个更
底层的问题（P2）：两份快照里**逻辑没变**的函数，因为地址重定位（pc-relative 的
call/jmp 目标随快照布局变化），naive 逐字节比对会不会把它们也误判成"不等价"？
若会，则必须做"符号化 / 地址无关"的等价判定——这是 §4.2 未展开、却决定 linker
可行性的关键。见 `../probe_reloc_equivalence/`。
