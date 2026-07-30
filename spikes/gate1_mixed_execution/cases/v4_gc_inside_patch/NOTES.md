# V4 — 解释执行代码内部触发 GC

## 命题

V1-V3 证明了替换 + 异常传播在混合 AOT<->解释器栈上成立。V4 要问：如果解释执行的
替换体在运行期间触发 GC 会怎样？

- GC 能不能正确扫描/保住调用方 AOT 帧（经运行时改写的调用点抵达）上存活的对象？
- GC 之后，解释器内部的分配是否依然正常？

## 结果（2026-07-30）：V4 PASS

```
BEFORE: g() got: ORIGINAL; markerIntact=true
AFTER:  g() got: PATCHED-AFTER-ALLOC-last=garbage-299999; markerIntact=true
V4 PASS
```

`g()` 在调用 `f()`（重定向到解释执行的 `fPatched()`）前持有一个堆上的标记数组，
`fPatched()` 内部分配 30 万个短生命周期字符串（足以触发多次 scavenger GC，大概率
有晋升），返回后 `g()` 里的标记数组内容原样不变，`fPatched()` 自己的返回值也正确。

## 关键发现（比 V4 本身更重要）：字节码模块的符号解析被闭世界 AOT 树摇严格限制

这次测试踩了三次同一类坑，逐步把真正的机制定位清楚了——**这条发现比"GC 正不正确"
更重要，直接影响这套机制能不能用于真实的热更新场景**：

1. 第一次尝试用 `VMInternalsForTesting.collectAllGarbage()`（`dart:_internal`）
   显式强制 GC——字节码**加载阶段**报错：
   `Unable to find class VMInternalsForTesting in Library:'dart:_internal'`。
   猜测是树摇问题，让宿主也引用这个类——**依然失败**，排除了"只是没保留"这个假设。
2. 改用 `List<int>.filled(...)`（`dart:core`）——**同样**在加载阶段失败：
   `Unable to find function _List@....filled in Library:'dart:core' Class: _List`。
   说明不是 `dart:_internal` 特有的问题。
3. 改用字符串插值分配垃圾（`'garbage-$i'`，这是 V1/V2/V3 宿主代码本来就在用的操作）
   ——能过；但紧接着在插值结果上调一个普通 getter `garbage.isNotEmpty`——**又失败**：
   `Unable to find function get:isNotEmpty in Library:'dart:core' Class: String`。

**真正的机制**：不是"这个符号属于哪个库"，是**闭世界 AOT 树摇**——字节码读取器
（`BytecodeReaderHelper::ReadConstantPool`/`ReadObjectContents`）只能把字节码模块
常量池里的符号引用，链接到宿主编译产物**自己已经保留下来**的声明。宿主代码里
没有任何地方调用过 `.isNotEmpty`、`.filled`，或引用 `VMInternalsForTesting`，
这些符号在 AOT 树摇时就被整个删掉了，字节码模块引用它们时自然找不到。
字符串插值之所以每次都能用，纯粹是因为 V1/V2/V3 的宿主代码本来就用它构造返回值
（`'g() got: ${f()}'` 这种写法），插值机制本身被保留了下来。

**这对"热更新补丁能调用什么 API"是个硬约束**：按官方设计，要让补丁调用宿主/核心库
任意 API，必须靠 `dynamic_interface.yaml` 的 `callable` 声明显式打通——这正是
`pkg/dynamic_modules/README.md` 里"默认什么都不暴露，除非显式声明"那条设计原则的
具体体现，我们在 `gate1-dynamic-modules-cannot-replace` 那条发现里已经记录过这个
原则，这次是从"补丁调用普通 API 也受限"这个角度又实测确认了一遍。真实生产场景下
补丁能调用的 API 面，取决于宿主愿意在 `dynamic_interface.yaml` 里声明多大的
`callable` 范围——范围越大，AOT 编译器需要保留的东西越多，越接近关闭 tree-shaking，
和官方 FAQ 里"暴露太多会实质性关掉全程序优化"的权衡完全对应。

## 状态

- [x] GC 触发时调用方 AOT 帧上的存活对象未被破坏——PASS
- [x] GC 之后解释器内部分配依然正确——PASS
- [x] 发现并记录了字节码模块符号解析受闭世界 AOT 树摇严格限制这一通用约束
- [ ] V5：压测（V1/V2/V3/V4 机制在高频调用/并发下的稳定性）
- [ ] 若要支持"补丁调用任意宿主 API"，需要接入 `dynamic_interface.yaml` 的
      `callable` 声明机制（当前不是阻塞项，先记录）
