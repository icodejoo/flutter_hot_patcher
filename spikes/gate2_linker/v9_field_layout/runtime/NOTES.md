# V9 类字段布局变更 —— 第 2 层(运行时实跑)

**问题**：字段布局变更本质是"定义新布局的类"。在真实 VM 上，补丁能否定义/分配/访问
带新字段的类，跨 AOT↔解释边界不内存错乱？（V3 曾踩坑：补丁声明新类在字节码**加载
阶段**报 `Unable to find function Object. in Library:'dart:core'`——新类分配需要把隐式
`Object()` 构造链接到宿主 dart:core，靠 `dynamic_interface.yaml` 打通。）

跑：`DART_SDK_SRC=/root/dart/sdk ./run_v9_runtime.sh`

## 用官方 dynamic modules 完整流程（不是 Gate 1 简化流程）

关键差异（照 `pkg/dynamic_modules/test/runner/vm.dart`）：
- host 编 kernel 时加 `--dynamic-interface <yaml>`（按 interface 保留 API）。
- 补丁编 bytecode 时加 `--import-dill <host_no_aot.dill> --validate <yaml>`。
- host 用官方 `loadModuleFromBytes`（`package:dynamic_modules`）加载，非自加的
  `loadDynamicModuleClosure`。
- `dynamic_interface.yaml` 的 `callable: - library: 'dart:core'` 正是打通"新类分配需
  要 Object() 构造"的钥匙（V3 坑的解法）。

先手动跑通官方 `extend_class` example 确认自编译 VM 支持完整 dynamic modules（补丁
`Child extends Base` 定义+分配+虚方法覆盖），输出 successToken、exit 0 —— 环境 OK。

## 结果：V9 第 2 层 PASS

用例：`shared/Shape`（host 只通过虚接口 `area()` 认识它）；补丁定义带新字段的类：
- `entry1`：`Box{w,h}`，`area()=w*h`，`Box(3,4)` → **area=12 PASS**
- `entry2`：`Box{w,pad,h}`（pad 插在中间且被读，h 偏移后移），`Box(3,999,4)` →
  **area=12 PASS**

两种布局都对 → 解释器按各自布局正确分配/读字段；插入字段使 h 偏移后移后，解释执行
的访问代码仍读对（自适应新布局）。host 通过 `Shape.area()` 虚调用拿结果，从不硬编码
Box 字段偏移。

## 为什么"内存错乱"在正确模型下被设计排除（V9 的核心结论）

- 访问新布局字段（w/h/pad）的代码**全在补丁里**，走解释器、用补丁的新布局。
- host AOT 只经**虚调用边界**（`Shape` 接口）访问对象，拿不到、也不硬编码子类字段
  偏移 → 不存在"AOT 用旧偏移访问新布局对象"的错乱路径。
- 这正是 SPEC §5"补丁即权威 + 虚调用边界"、§3"正确模型下不再是内存错乱、而是解释
  比例上升"。第 1 层已证 linker 完备识别所有访问变布局字段的函数（字节必变、逐字节
  比对不漏），把它们全转解释；错乱只会发生在"linker 漏判某访问者"——那是完备性问题，
  第 1 层已排除。故 V9 第 2 层不需实跑"故意漏判→错乱"（那需完整 linker 且价值低），
  用完备性 + 边界论证即可。

## 综合：V9（最可能推翻方案的用例）双层 PASS

- 第 1 层（静态完备性）：字段布局变更 → 所有访问者被完备且精确识别（归一化后真实
  闭包个位数，见 `../NOTES.md`）。
- 第 2 层（运行时）：补丁定义/分配/访问新布局类，真机 VM 上行为正确、跨虚调用边界
  不错乱。
→ V9 未推翻方案。字段布局变更在"补丁即权威 + 虚调用边界 + 完备转解释"下可靠成立。
