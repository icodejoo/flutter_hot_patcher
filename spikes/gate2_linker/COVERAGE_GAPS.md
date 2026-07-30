# 差分样本覆盖复盘 —— 未覆盖面与风险分级

对 P1/P2 大样本做覆盖复盘：还有哪些数据类型 / 语法 / 第三方库 / 底层(FFI/isolate) 以及
**改动形态**没测到。重点按**对差分器"完备性(sound)/精确度"的风险**分级——高风险=可能让
当前 spike 方案出错或漏判，中=大概率能处理但未验证，低=多半无碍或不在 diff 范围。

> **本文是"语言/样本覆盖面"的复盘。`diff_linker` 工具自身的实现级缺口（含多个当前 x86-64
> 即可复现的静默漏判）见 [`REVIEW_diff_linker.md`](REVIEW_diff_linker.md)（多 agent 评审，
> 59 发现/52 验证存活）。** 其中一条属本文范畴、红线级、此前完全未列，补记如下：
>
> **0. cid / dispatch-table / vtable 布局漂移（改动形态盲区，SPEC §4.3）· 高风险**：diff_linker 只
> 比"函数机器码字节 + 直调边"，对**类的 cid 分配 / dispatch slot / vtable 顺序零建模**。补丁若只增删/
> 重排类成员使既有类的 cid 或 dispatch slot 平移、而**无任何函数字节改变** → byte-changed=∅、闭包=0、
> 工具报"0 must reinterpret"，但字节未变的虚调用方在设备上按旧 slot 布局派发到错误目标 → 行为错乱。
> 与 S1/S2 同属"字节没变但行为变了、闭包为空、无告警"的红线类。正解=SPEC §4.3 cid 稳定化 +
> 差分器消费 cid/dispatch 元数据做布局比对（或类声明集合变化时保守告警）。**未测。**

已覆盖（基线）：int/double/bool/String、List/Map/Set/record、类 method/getter/setter/
operator/static、mixin、enum(带方法)、泛型类、匿名闭包、直接调用链级联、多态虚调用边界；
Flutter 的 StatelessWidget/StatefulWidget/build/setState。**改动形态只测了"改函数体常量"。**

---

## 高风险（可能破坏完备性 / 冲击当前 keying，优先补）

> **已补测（`p3b_completeness/`）**：#1 async ✅、#2 tear-off ✅、#3 const 内联 ✅。async 用例
> **暴露并修复了一个 diff-linker 完备性 bug**——`parse_snapshot` 曾在首个 `ret` 截断函数块，
> async 的真实 `return` 在其后被丢 → 漏判；已改为块到下一符号头。此 bug 影响**任何多返回点/
> 提前 return/分支 return 的函数**，比单个 async 用例更重要。P1/v6/v7/v8 回归全 PASS 无变化。

1. **async / await / Stream / 生成器(sync*/async*)**：✅ async 已测（暴露并修复首-ret 截断漏判）。
   Stream/`sync*`/`async*` 仍未测。
2. **tear-off（方法撕裂）**：✅ 已测——改被撕裂的**方法本身**被完备捕获（target 双入口经多重集
   捕获；`_held` 单态被去虚化 → direct/useHeld 均级联）。P2 那次"不级联"是因改的是 setState
   闭包体、方法本身没变，属正确。**运行时注意**：补丁前已缓存旧 entry 的 tear-off 闭包需 V2 式
   entry 重定向刷新（运行时缓存失效项，非 diff-linker 完备性问题）。
3. **const 内联 / 被广泛使用的 const**：✅ 已测——改 `const K` 被内联进每个使用点、逐个作条件1
   命中，完备。**残留风险**：若 const 入对象池、改动只体现为池 slot 值，会撞 normalize 池通配
   漏报（tools/NOTES），真 linker 需精确 slot→常量映射。
4. **混淆构建(--obfuscate)**：✅ 已测（单次 P1 语料、同源同布局）——`--save-debugging-info` 的
   DWARF **保留真实名字**，按真名对齐即可，混淆字符串在池里被通配，closure==ground truth。
   **订正（见 REVIEW_diff_linker.md #14）**：这是单次语料结论，**跨构建**混淆名漂移会改 call-site
   文本、可能塌陷精度，未测。**strip release ⚠ 从未真测**（见 REVIEW #9）：工具结构上需**未 strip**
   的快照（逐函数 ELF 符号）；生产的已 strip `libapp.so` 只剩 ~4 blob 符号 → 逐函数差分失效。
   （本条曾误记为"strip release ✅ 已测"，实为过度声明，已订正。）
5. **dart:ffi（底层）**：✅ 已测（`ffi_case`）——Struct 字段偏移访问、FFI 值算术、
   `Pointer.fromFunction` 回调都正常差分，且改回调函数会级联到编译器生成的 native trampoline
   `_FfiCallbackcb`。**未测**：Struct **布局变更**（FFI 版 V9，影响所有访问者偏移）。
6. **代码生成第三方库(freezed / json_serializable / built_value)**：✅ 已测（`codegen_case`，
   手写 json_serializable 风格、未引三方依赖）——加字段重生成的 fromJson/toJson 被完备检出、
   User 构造经 ambiguous-changed 捕获、只读旧字段的 summarize 判等价。**注**：真实生成代码在
   `part` 文件里(本用例内联)，part-file 对齐见 #19；map 字面量池常量改动可能撞池通配近似。

## 中风险（大概率能处理，但未验证——扩样本应逐一纳入）

7. **构造函数**：generative/factory/const/redirecting/命名构造、初始化列表、super() 链、
   `late` 字段初始化。改构造体是否独立符号、是否级联到所有 `new` 点。
8. **扩展方法 `extension` / 扩展类型 `extension type`**：静态分派、特殊降级。
9. **Dart 3 模式匹配**：`switch` 表达式/模式、`if-case`、解构赋值、record 具名字段——新 codegen。
10. **泛型方法 + reified 类型检查**：泛型**方法**(非泛型类)、`is T`/`as T`、类型参数特化产生的
    多份实例化代码(与 ICF/ V9 交织)。
11. **异常处理的差分**：try/catch/finally/rethrow、自定义异常类、throw 位置变化。V3 只测了运行时
    穿透，没测"改了异常处理逻辑的函数"的差分。
12. **deferred import（延迟加载）**：拆成独立 loading unit，AOT 里是单独单元——对齐/闭包边界特殊。
13. **class 修饰符(Dart 3)**：sealed/final/base/interface、exhaustive switch、abstract interface。
14. **闭包进阶**：**捕获局部变量**的闭包(会分配 context)、嵌套闭包、存进字段的闭包、
    实例方法 tear-off（见 #2）。
15. **operator 全集**：`[]`/`[]=`、`==`+`hashCode`、`call()`(可调用对象)、一元 `-`/`~`、比较运算符。
16. **isolate 入口**：`Isolate.spawn` 的入口函数是特殊根；改 isolate 入口代码的差分未测。
17. **Flutter 底层**：RenderObject/CustomPainter 的 `paint`/`performLayout`、动画
    (AnimationController/Ticker/Tween)、InheritedWidget 依赖传播、Slivers、LayoutBuilder。
18. **const widget 规范化**：const 构造 widget 被规范化(canonicalize)，改一个 const widget 的行为。
19. **part / part of**：一个 library 跨多文件——canonical key 用源文件，DWARF decl_file 与
    library 的对应关系需确认(同库多文件会不会误分/误合)。
20. **平台通道/插件(MethodChannel)**：插件 Dart 侧 + 原生侧；补丁只能动 Dart 侧。

## 改动形态维度（我们只测了"改常量"，这些形态影响差分本身）

21. **改函数签名**（参数/返回类型）→ 影响所有调用点的传参代码，可能大范围级联。
22. **新增 / 删除** 函数、方法、类、字段（added/removed 记账已有，但没专门验证保留/链接/级联）。
23. **增删类字段**（V9 已单独测过布局，但没并进大样本精确度测量）。
24. **改动触发不同内联决策**（某改动让函数从可内联变不可内联，内联边界移动）→ 精确度扰动。
25. **成员重排序 / 加注释 / 格式化**（应为 no-op）——测对齐稳定性(不应产生任何闭包)。
26. **改类型注解 / 泛型约束**——可能改类型检查代码。

## 低风险 / 不在 diff-linker 范围（记录，别当遗漏）

27. **资源(图片/字体/asset)、.arb 本地化**：非代码，属整体补丁系统(下发/打包)而非 diff-linker。
    但真实补丁常含资源改动，系统层要覆盖。
28. **纯 Dart 无代码生成的三方库**：与 framework 同性质，多半与 P2 结论一致，低优先。
29. **dart:mirrors**：AOT 不支持，天然排除。

---

## 建议的补测优先级（下一轮扩样本）

第一梯队（完备性风险，必做）：async 状态机、tear-off 改被撕裂方法、const 内联扩散、
混淆构建下的对齐、FFI(struct 布局 + 回调入口)。
第二梯队（真实场景占比高）：代码生成库(freezed/json_serializable)、构造函数、模式匹配、
签名变更、增删符号。
第三梯队（Flutter 底层）：RenderObject/paint、动画、InheritedWidget、平台通道。

注：#1(async)、#2(tear-off)、#3(const 内联)、#4(混淆) 若在真机/真 app 上暴露漏判，会直接
冲击"完备性=不漏改动"这条产品红线，应最先证伪。
