# 改动形态批次 —— 签名变更 / 增删符号 / 构造函数 / 模式匹配 / part

COVERAGE_GAPS"改动形态"维度剩余项（此前只测过"改函数体常量"）。复用 v6-v8 的 canonical
harness（`run_case.sh`）。

## 签名变更 —— PASS（且是正面结论：调用约定使改动天然可见）

`price(int qty)` 改成 `price(int qty, {int discount=0})`。`callerA` 更新为传
`discount:5`（源码变），`callerB` **源码逐字节不变**（仍是 `price(n)`，靠新参数默认值）。

**踩坑**：base 里 callerA/callerB 若源码恰好完全相同会被 ICF 合并（S6 的另一面——`callerB`
在 base 的符号表/DWARF 里完全不存在，diff_linker 正确地把它归进 `added` 保守播种，这是
**安全方向的过度保守**，不是漏判；用一个依赖运行时输入的算式 `+ (n & 1)` 让两者结构不同、
避开 ICF，才能干净测出"签名变更对未改调用点"这个真正想测的问题）。

**结果**：`callerB` 被条件1直接命中（byte-changed），尽管源码没变。反汇编差异：

```
patch 比 base 在 call price 之前多一条:
  mov  POOL(%r15),%r10     ; 加载 ArgumentsDescriptor(1个位置参数,0个命名参数)
```

**机制**：Dart 的调用约定——被调函数一旦带有可选/命名参数，**每个调用点**（即便不传该参数）
都必须在调用前把 ArgumentsDescriptor 加载进 r10 传给被调方，供其判断哪些可选参数被提供。
`price` 从"无可选参数"变成"有可选参数"，**牵动了它所有调用点的机器码**——不管调用点源码
变没变。

**结论**：签名变更（加/删可选或命名参数）**不是**评审担心的"不可见改动形态"——调用约定的
物理约束使它必然体现为调用点字节变化，被条件1天然捕获，完备性有保障。（若被调函数一直没有
可选参数、纯改变参数**类型**或**必需参数个数**，调用点的物理约束可能不同，未测，留作细分项。）

## 增删符号（`add_remove`）—— PASS，干净基线

`oldFn` 整体删除（死代码），`newFn` 新增并接进 `helperCaller`。结果精确匹配预期：
`added={newFn}`、`removed={oldFn}`、`byte-changed={helperCaller}`（源码改为调 newFn）、
级联 `main`；`unrelatedX` 不动。行为 6→3 确认。added/removed 记账在这个基线场景下正确。

## 构造函数 + Dart 3 模式匹配（`ctor_pattern`）—— PASS

`Derived.make`（工厂构造函数，改动落在 factory body）+ `describe`（switch 表达式模式匹配，
改动落在 `_ when` 分支）均被条件1精确捕获，级联 main；`Base`/`Base.named`（命名构造+初始化
列表）/`Derived`（super 链）/`unrelatedCtor` 均未改动、正确不入闭包。行为 4→5 确认。
构造函数与模式匹配降级出的机器码，与普通函数走同一套条件1/条件2逻辑，无特殊坑。

## part/part-of 多文件同库（`part_case`）—— PASS，且精确复现了 REVIEW C1 预测的残留精度损失

`app.dart` 用 `part 'helpers.dart';` 引入 `helpers.dart`（`part of 'app.dart';`）。两个变化：
`helperB` 原地改动（留在 helpers.dart，body 变）；`helperA` **从 helpers.dart 移到 app.dart，
逻辑完全不变**（仿代码生成器重新生成到不同 part 文件的场景）。

结果：
- `helperB`：条件1直接命中（真实逻辑改动，物理位置未变，key 对齐正常）。✅
- `helperA`：**canonical key 从 `helpers.dart::helperA` 变成 `app.dart::helperA`**（key=源文件
  路径+名）→ 判定为 `removed`（旧 key）+ `added`（新 key），尽管逻辑一字未改。

**这精确复现了 REVIEW `research_shorebird_compare.md`/`C1` 早先的预测**："同一 library 跨
part 文件移动"是 canonical-key-as-源文件路径 方案下**唯一真残留**的文件移动误报场景（应用内
文件改名/搬家已被 Kernel `package:` URI 天然免疫，只有**同库跨 part 物理文件**这种"库身份不变、
物理位置变"的情况会撞上路径代理的局限）。

**方向判定**：sound（helperA 被安全地转解释，不会漏判），但**不精确**（逻辑未变的函数被当作
"改了"）。真实 linker 用 Kernel CanonicalName（库URI→类→成员，不含物理文件路径）会天然免疫
这类移动——这与 P0/PRODUCTION_LINKER_SPEC R1 的结论一致，这里是它的一次具体实锤。

## 本批次小结

四个改动形态（签名变更/增删符号/构造函数+模式匹配/part 多文件）全部完备（无漏判）；part
用例额外坐实了一条已知精度残留（非新发现，是既有预测的首次具体复现）。COVERAGE_GAPS 中风险项
基本清空，剩纯 Stream 订阅/StreamController 形态、捕获局部变量的闭包等边角。
