---
name: reference-thread-field-offsets
description: 往 dart::Thread 加字段只能追加在末尾——中间插入会被 CheckOffsets 在构建期打死，而重生成 runtime_offsets_extracted.h 要 16 个配置的构建，本机磁盘不够
metadata: 
  node_type: memory
  type: reference
  originSessionId: 54ae03f7-8165-4751-8bcc-db9ab1bb3695
---

2026-08-20，加 `Thread::is_simulating_`（6b-i）时实测出来的硬约束。**下次加任何
`Thread` 字段都适用**，不用重新排查。

## 规则：只能追加到最后一个成员之后

我们的落点是 `regexp_backtracking_stack_cache_` 之后。得到 offset **0xf18 (3864)**，
他们是 **0x8d8 (2264)** —— **对不上是必然的，不是缺陷**。生成代码一律走
`Thread::is_simulating_offset()`，**永远不要写死立即数**。

## 为什么不能插在中间（实测，非推理）

在 `stack_limit_` 与 `write_barrier_mask_` 之间插一个 `uword` 试了一次，**构建直接失败**：

```
runtime/vm/dart.cc: 257: error: CheckOffsets failed.
  Try updating offsets by running ./tools/run_offsets_extractor.dart
```

不是某条测试变红——是 **ninja 挂掉**，因为构建过程要跑 VM 生成快照，VM 启动即 abort。
⚠️ 当时那次我先看了 `run_vm_tests` 的输出，它照常打印 `Done:` 并 exit 0 ——
**那是上一轮的陈旧二进制**。判据必须是 ninja 的退出/输出，见 [[feedback-false-green-traps]]。

生成代码用的 Thread 偏移存在**签入的表** `runtime/vm/compiler/runtime_offsets_extracted.h`，
32 个 `#if` 块 = mode × 8 arch × compressed × jit/aot。中间插入会平移其后所有条目。
`Thread` 的 `sizeof` **不在表里**，所以追加不影响任何条目。

## 为什么不重生成那张表

`tools/run_offsets_extractor.dart` 会 `tools/build.py` 构建
**8 arch × 2 mode = 16 个配置**的 `offsets_extractor` + `offsets_extractor_aotruntime`。
本机 `~` 只剩 **66 GB**，装不下。所以「把新字段登记进 `runtime_offsets_list.h`」这条路
**当前不可用**，只能追加 + `OFFSET_OF`。

## 生成代码能不能读到它，用汇编器自己的谓词判

```c++
compiler::Address::CanHoldOffset(offset, compiler::Address::Offset,
                                 compiler::kEightBytes)
```
arm64 的 `ldr Xt,[Xn,#imm]` 是 12 位立即数 × 8 缩放。别手写边界，会和编码器漂移。
负控制已跑：`CanHoldOffset(offset+1)` 为 false（对齐那一半是真约束；
3864 距 32760 的上限还很远，边界那一半在这里是白送的）。

坑：`kEightBytes` 在 `compiler::` 命名空间里；`ISOLATE_UNIT_TEST_CASE` 已经给了
名为 `thread` 的形参，别再声明一个。

相关：[[reference-wrapper-stub-bodies]]、[[project-dart-sdk-fork]]、[[feedback-false-green-traps]]
