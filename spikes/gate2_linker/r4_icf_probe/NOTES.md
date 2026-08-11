# R4 ICF 探测 —— 尝试用 analyze_snapshot 验证 ICF ground truth，未跑通

**背景**：Mac 设计 kernel_linker R4（ICF/dedup 感知）时提出两个选项——Option A（Kernel 层
fingerprint 相同就保守播种，可能过报）vs Option B（Kernel 层不处理，留给 AOT 层后处理）。
这轮尝试找第三条路：ICF 折叠后，两个函数的 `Function` 对象理论上会指向同一个 `Code`/
`Instructions` 对象，`analyze_snapshot`（R5 用过的诊断工具）的 JSON 输出里 Function→Code
的映射能不能直接给出这个 ground truth，把"猜"变成"读"。

## 源码确认（不是猜测）

ICF 在 VM 里是 `ProgramVisitor::DedupInstructions`（`runtime/vm/program_visitor.cc`），由
`ProgramVisitor::Dedup()` 统一调度：

```cpp
// Reduces binary size but obfuscates profiler results.
if (FLAG_dedup_instructions) {
  DedupInstructions(thread);
}
```

`flag_list.h`：`R(dedup_instructions, true, bool, false, "Canonicalize instructions when
precompiling.")`——默认开启，比对对象是 `Instructions`（实际生成的 AOT 机器码），发生在
`gen_snapshot` 生成快照阶段，**严格晚于 Kernel IR**。这确认了 kernel_linker 在 Kernel 层
结构上就看不到 ICF 折叠决定，不是实现疏漏。

## 实测：没有观察到折叠

`test-lib/probe.dart` 写了三个函数：`functionA()`/`functionB()` 都返回 `42`（预期字节完全
相同，应该被 ICF 折叠成一个），`functionC()` 返回 `43`（对照组，预期不折叠）。

用非 product 模式的 `gen_snapshot` + `analyze_snapshot --out` 查 Function→Code 映射
（`inspect_icf.py`）：

```
functionB -> Function id 24217 -> Code id 24238 (offset=711424, size=8)
functionA -> Function id 24221 -> Code id 24223 (offset=711432, size=8)
functionC -> Function id 24225 -> Code id 24227 (offset=711416, size=8)
```

**三个函数各自指向不同的 Code 对象**——`functionA`/`functionB` 没有被折叠到一起，尽管
源码上看应该逐字节相同。

## 诚实边界：没有查清楚原因，这个负面结果不能当结论用

可能的原因（都没有验证）：
- `analyze_snapshot` 只能读**非 product** 模式的快照（product 模式会因版本字符串不匹配崩溃，
  这是本项目已知限制）——ICF 在非 product 构建下是否表现不同，没有查证。
- 这两个玩具函数太小/太简单，没有触发 `InstructionsKeyValueTrait` 判定折叠所需的某个阈值
  或额外条件（比如指令数、是否被去虚化调用过等）。
- `Deduper<Instructions, InstructionsKeyValueTrait>` 的相等判定可能不只看指令字节，还看
  一些没在这轮考虑到的元数据（比如 pc descriptors、debug info 关联），trivial 例子可能恰好
  在这些元数据上不同。

**这条路有源码依据、方向对，但没有实测证实"analyze_snapshot 能可靠暴露 ICF 分组"**——不能
当作已验证结论。如果以后有时间，值得：(a) 换更真实的语料（不是两个玩具函数）；(b) 确认
product/非 product 模式下 ICF 触发条件是否一致；(c) 检查 `Deduper`/`InstructionsKeyValueTrait`
的具体相等判定逻辑，而不是纯粹从外部观察结果反推。

## 结论

给 Mac 的建议是**先用 Option A**（Kernel 层 fingerprint 相同就保守播种）——理由跟项目"完备性
优先于精确度"的原则一致，不是因为这条第三条路走不通就退而求其次；这条路仍然是有价值的后续
方向，只是这轮没有验证成功，如实记录，不夸大也不隐藏。
