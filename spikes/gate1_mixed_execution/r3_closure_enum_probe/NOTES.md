# R3.1 spike — 闭包重定向完备性:堆遍历枚举活跃 Closure 实例可行性

**背景**：`PRODUCTION_LINKER_SPEC.md` R3.1（本次新识别的独立生产需求，见
`spikes/gate2_linker/r3_boundary_contract/NOTES.md`）指出，Gate1 V2 的闭包重定向
（改 `Closure` 实例自己的 `entry_point` 字段）是**每实例**粒度，但"枚举堆上所有指向某个
被改函数的活跃 Closure 实例"这件事从未验证过——V2 只测试了重定向一个已知变量。这轮不等
Mac，直接在桌面 x64 上探测：VM 有没有机制能做这个枚举，做不做得到。

## 源码级发现：两条候选机制，一条被 PRODUCT 排除，一条没有

- `ObjectGraph::IterateObjects`/`IterateObjectsFrom(class_id, ...)`
  （`runtime/vm/object_graph.h`）——功能上正是想要的（按 class id 过滤堆遍历），但整个类被
  `#if defined(DART_ENABLE_HEAP_SNAPSHOT_WRITER)` 包住，而这个宏在 `globals.h` 里明确写
  `#if !defined(DART_ENABLE_HEAP_SNAPSHOT_WRITER) && !defined(PRODUCT)` ——**只要
  `PRODUCT` 被定义就不会启用**。真实发布用的 `dartaotruntime_product`/`gen_snapshot_product`
  永远定义 `PRODUCT`，所以这条机制在生产运行时里**完全不存在**。
- `HeapIterationScope`/`ObjectVisitor`（`runtime/vm/heap/heap.h`、`runtime/vm/visitor.h`）——
  读了 `heap.cc` 的实现（`HeapIterationScope` 构造函数、`IterateObjects`），**没有任何
  `PRODUCT`/`DART_ENABLE_HEAP_SNAPSHOT_WRITER` 之类的宏保护**——这是 GC 自己內部也在用的机制
  （`isolate_group()->safepoint_handler()->SafepointThreads` 做安全点、`old_space_->tasks()`
  等 GC 内部状态），**在所有构建变体（含 product/AOT）里都编译进去**。这是可用于生产的机制。

## 实测：新增 `Internal_countClosuresForFunction` 原生入口，实测堆遍历枚举

按 V1/V2 同样的模式（`bootstrap_natives.h` 注册 + `runtime/lib/object.cc` 实现 +
`dart:_internal`/`internal_patch.dart` 暴露），新增一个原生函数：给一个"样本"闭包（借它取出
目标 `Function`），用 `HeapIterationScope` 遍历整个堆，对每个 `class id == kClosureCid` 的
对象检查其 `function()` 字段是否等于目标，逐一计数返回。完整改动见
`apply_probe_patch.py`（脚本化的 4 处文件改动，可重复应用）。

**构建踩坑（预期内，vm_patch/README.md 已文档化的两处依赖追踪失效再次踩中）**：
`vm_platform.dill` 和 `bootstrap_natives.cc` 的强制刷新步骤都用上了，符号用 `nm` 确认存在
才继续测（`DN_Internal_countClosuresForFunction`）。另外这次 `./tools/build.py` 跑出一个
**跟本次改动无关**的 `samples/embedder/run_main.cc` 编译错误（`std::vector` 缺 include，
是工具链版本漂移导致的既有问题，不是这次改动引入的）——ninja 仍然把 `gen_snapshot_product`
构建出来了（独立的依赖子图），只有 `dartaotruntime_product` 因为在失败前的队列里没轮到而
保持旧的，按 README.md 的强制刷新步骤单独重建了它，符号确认后再往下走，没有因为这个无关错误
被卡住。

**测试用例设计的一次返工（有价值的反面案例，别丢）**：第一版用例是"顶层函数 `targetFn`"，
分别赋值给局部变量、List 元素、类字段、嵌套闭包，共 5-6 处"看起来不同"的 tear-off——
实测 `COUNT=1`。**原因**：`targetFn` 是无捕获状态的顶层函数，AOT 编译器把它反复 tear-off
的结果**规范化成同一个共享 Closure 实例**（没有绑定 receiver，纯函数值，天然可 intern）——
这正是 Gate1 V2 NOTES.md 早就点出的教训（"AOT 闭包特化会把测试用例本身优化掉"）在这里的
翻版。**改用绑定不同 receiver 的实例方法 tear-off**（5 个不同的 `Handler` 对象各 tear-off
自己的 `handle` 方法，构造函数参数是运行时才知道的循环变量，规避常量折叠）——这次每个
tear-off 必须绑定不同的 `this`，编译器无法规范化成一个实例：

```
total=10 handlers=5 COUNT=6
```

`total=10`（0+1+2+3+4，5 个 Handler 都被正确调用，闭包语义没坏）；`COUNT=6` ==
**5 个存进 List 的 tear-off + 1 个之后单独对 `handlers[0]` 再 tear-off 一次的 `sample`**，
后者**没有**和 List 里那个共享（说明同一 receiver 的两次独立 tear-off 表达式，AOT 也不会
规范化合并，各自是独立的 Closure 实例）——**跟手算的 ground truth 完全吻合**。

## 结论

- ✅ **确证**：`HeapIterationScope` 能在**生产可用的构建变体**（product 模式，无
  `DART_ENABLE_HEAP_SNAPSHOT_WRITER`）下，完整、精确地枚举堆上所有指向某个 Function 的
  活跃 Closure 实例——R3.1 提出的"补丁应用引擎能否完备枚举"这个问题，**答案是能，机制已找到
  且实测验证**，不是无解的硬缺口。
- ✅ **收获**：顶层/静态函数（无 receiver）的 tear-off 会被 AOT 规范化成共享实例——这对
  R3.1 反而是好消息（需要枚举/重定向的实例更少），但也说明"从源码数量推断闭包实例数"不可靠，
  必须靠运行时枚举，不能靠静态计数假设。

## 诚实边界（这轮没测的部分）

- **只测了枚举(count)，没测边遍历边重定向(patch)**——`HeapIterationScope` 默认
  `writable=false`；真要在 `VisitObject` 回调里调用 `set_entry_point` 写入，需要确认
  `writable=true` 模式下这样做是否安全（`VisitObject` 的文档要求"不能分配堆内存/触发 GC"，
  `set_entry_point` 只是写一个非指针字段，大概率没问题，但没有实测，留作下一步）。
- **只测了单 isolate、小规模（5-6 个实例）、桌面 x64**——`HeapIterationScope` 构造函数用的是
  `isolate_group()->heap()`，只遍历**当前 isolate**的堆；一个函数如果在**多个 isolate**
  （如 `Isolate.spawn` 产生的隔离堆）里各自持有闭包实例，这个机制**看不到其他 isolate**，
  真要做完备补丁应用需要对 isolate group 里的每个 isolate 都跑一次——这轮没有测试多 isolate
  场景，是真实的、需要在生产化时处理的额外维度。
- **没测大规模堆遍历的性能代价**——真实 App 堆可能有几十万个存活对象，每次打补丁都全堆扫描
  一遍的开销未测量，可能是个需要工程优化的点（比如限定扫描范围/增量标记），不是本轮探测目标。
- **没测跨 GC 场景**——理论上 `HeapIterationScope` 构造时做了安全点(safepoint)，遍历期间
  不应该有并发 GC 打断，但"遍历完成后到实际写入 entry_point 之间"如果发生了 compacting GC，
  拿到的对象指针是否还有效，没有实测验证（真要做需要在同一个 writable HeapIterationScope 内
  完成"找到 + 写入"，不能分两步跨越 GC 边界，这点已经能从 API 设计上合理推断，但没做实测确认）。

## 对 PRODUCTION_LINKER_SPEC 的更新

R3.1 从"完全未知、需要专门验证的独立风险项"更新为："机制已找到（`HeapIterationScope`，非
`ObjectGraph`——后者被 PRODUCT 排除）并 spike 级实测验证枚举正确（5 个不同 receiver 的
tear-off + 1 个后补的都被完整、精确计数），核心可行性问题解决；剩余是工程细节（边遍历边写入、
多 isolate、大堆性能），不是"能不能做"的问题，是"怎么做扎实"的问题"。
