# 差分样本覆盖复盘 —— 未覆盖面与风险分级

对 P1/P2 大样本做覆盖复盘：还有哪些数据类型 / 语法 / 第三方库 / 底层(FFI/isolate) 以及
**改动形态**没测到。重点按**对差分器"完备性(sound)/精确度"的风险**分级——高风险=可能让
当前 spike 方案出错或漏判，中=大概率能处理但未验证，低=多半无碍或不在 diff 范围。

已覆盖（基线）：int/double/bool/String、List/Map/Set/record、类 method/getter/setter/
operator/static、mixin、enum(带方法)、泛型类、匿名闭包、直接调用链级联、多态虚调用边界；
Flutter 的 StatelessWidget/StatefulWidget/build/setState。**改动形态只测了"改函数体常量"。**

---

## 高风险（可能破坏完备性 / 冲击当前 keying，优先补）

1. **async / await / Stream / 生成器(sync*/async*)**：async 体降级成**状态机 + 多个合成
   闭包符号**。改动落在合成符号里、调用者经 Future/Stream 机制间接衔接——闭包是否完备进闭包、
   级联是否正确，完全未验。真实 app async 无处不在，这是最大功能盲区。P1 已知故意跳过。
2. **tear-off（方法撕裂）**：P2 实测 `onTap: increment` 这个 tear-off 在闭包改动时**没有级联**
   到 build。需确认：被撕裂的**方法本身**改了时，tear-off 出的闭包 entry 会不会仍指向旧实现
   → **潜在完备性漏洞**（V2 处理过 closure entry_point 重定向，但 linker 对 tear-off 的分类
   判定没测）。这条要专门做一个"改被撕裂方法"的用例证伪。
3. **const 内联 / 被广泛使用的 const**：改一个 `const`/`static const` 值会被**内联进每个使用
   点**（const 折叠，ICF 的对偶）。linker 必须抓到**所有**使用者（否则跑旧值=Bug）。这是继
   ICF 之后第二个"编译期展开导致改动扩散"的机制，未测，完备性风险高。
4. **混淆构建(--obfuscate) / strip release**：当前 CanonicalName 靠 DWARF 里的函数名。release
   常开混淆→名字被改/剥离→**DWARF 对齐直接失效**。生产必须改用混淆映射表或 Kernel 层对齐。
   这是"后验 DWARF 方案"的部署级硬伤，必须在正式研发前定方案。
5. **dart:ffi（底层）**：`Pointer`/`Struct`/`Union` 布局、`@Native`/`NativeFunction` trampoline、
   `Pointer.fromFunction`/`NativeCallable` 回调(是新的入口根)。改 Struct 字段布局 ~ V9 但面向
   native；FFI 回调入口的分类与级联未测。底层且真实插件常用。
6. **代码生成第三方库(freezed / json_serializable / built_value)**：改一个 model 会**重生成
   整个 .g.dart**（大量机械代码）。测点：大批量生成代码的差分、跨生成代码的对齐、以及"改一个
   字段→重生成→闭包多大"。真实 app 的补丁大头往往在这里。

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
