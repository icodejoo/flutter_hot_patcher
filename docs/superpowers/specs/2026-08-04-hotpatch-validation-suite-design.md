# iOS Hotpatch 生产验证套件 设计规格

版本 v1.0 · 2026-08-04

---

## 0. 目标

在 iPhone 14 真机上，对 91 个覆盖全面的场景系统性地验证：
1. **kernel_linker 精确度**：0 漏判（false negative），0 误报（false positive）
2. **运行时正确性**：补丁函数在设备上执行结果与预期完全一致
3. **崩溃率**：0
4. **已知限制文档化**：async/Stream 等已知受限场景明确标注

产出：`COVERAGE_REPORT.md`（汇总）+ `COVERAGE_DETAIL.md`（逐条）+ `coverage_results.json`（机器可读）

---

## 1. 项目结构

```
spikes/hotpatch_validation/
├── lib/                         baseline 实现（16 个场景文件）
│   ├── t01_primitives.dart
│   ├── t02_collections.dart
│   ├── t03_nullsafety.dart
│   ├── t04_constants.dart
│   ├── t05_functions.dart
│   ├── t06_classes.dart
│   ├── t07_generics.dart
│   ├── t08_operators.dart
│   ├── t09_async.dart
│   ├── t10_errors.dart
│   ├── t11_strings.dart
│   ├── t12_thirdparty.dart
│   ├── t13_flutter_like.dart
│   ├── t14_propagation.dart
│   ├── t15_hierarchy.dart
│   └── t16_edge.dart
│
├── patches/                     patch 版本（与 lib/ 结构镜像，相同文件路径重编）
│   └── t01..t16_*.dart
│
├── harness/
│   ├── main_harness.dart        顶层 runner：runAll() 返回所有结果 JSON
│   └── registry.dart            场景注册表（ID + 函数引用 + 预期值）
│
├── tools/
│   ├── run_validation.sh        端到端自动化脚本
│   ├── gen_report.py            从 results.json 生成覆盖率报告
│   └── expected.json            所有场景的预期 kernel_linker 输出
│
├── HotpatchValidation/          Xcode App 项目（基于 M3 HotPatchDemo 改造）
│
├── COVERAGE_REPORT.md           汇总（自动生成）
├── COVERAGE_DETAIL.md           逐条记录（自动生成）
└── coverage_results.json        机器可读结果
```

---

## 2. 场景矩阵（91 个场景）

### Category 1：基本类型变量（7 个）

| ID | 函数名 | baseline | patch | 验证点 |
|----|--------|---------|-------|--------|
| T01 | `prim_int` | `return 42` | `return 100` | int 字面量变化 |
| T02 | `prim_double` | `return 3.14` | `return 2.72` | double 字面量变化 |
| T03 | `prim_string` | `return 'hello'` | `return 'world'` | String 字面量变化 |
| T04 | `prim_bool` | `return true` | `return false` | bool 字面量变化 |
| T05 | `prim_dynamic` | `dynamic x = 1; return x` | `dynamic x = 'one'; return x` | dynamic 类型赋值 |
| T06 | `prim_var` | `var x = 10; return x * 2` | `var x = 10; return x * 3` | var 推断 + 计算变化 |
| T07 | `prim_object` | `Object o = 42; return o` | `Object o = 'forty-two'; return o` | Object 类型变化 |

### Category 2：集合类型（7 个）

| ID | 函数名 | baseline | patch |
|----|--------|---------|-------|
| T08 | `coll_list_literal` | `[1, 2, 3]` | `[1, 2, 3, 4]` |
| T09 | `coll_list_map` | `list.map((x) => x * 2)` | `x * 3` |
| T10 | `coll_list_where` | `where((x) => x > 0)` | `x >= 0` |
| T11 | `coll_map_literal` | `{'a': 1, 'b': 2}` | `{'a': 10, 'b': 20}` |
| T12 | `coll_map_access` | `return m['key'] ?? 0` | `m['key'] ?? -1` |
| T13 | `coll_set` | `{1, 2, 3}` | `{1, 2, 3, 4, 5}` |
| T14 | `coll_fold` | `fold(0, (a, b) => a + b)` | `fold(1, (a, b) => a * b)` |

### Category 3：空安全（5 个）

| ID | 函数名 | baseline | patch |
|----|--------|---------|-------|
| T15 | `null_nullable` | `String? s = null; return s ?? 'null'` | `s ?? 'empty'` |
| T16 | `null_bang` | `return s!.length` | `return s!.length + 1` |
| T17 | `null_conditional` | `return s?.toUpperCase()` | `s?.toLowerCase()` |
| T18 | `null_coalesce` | `return a ?? b ?? 'default'` | `a ?? b ?? 'fallback'` |
| T19 | `null_late` | `late String x = 'init'; return x` | `x = 'patched'` |

### Category 4：常量（6 个）

| ID | 函数名 | baseline | patch |
|----|--------|---------|-------|
| T20 | `const_toplevel` | `const PI = 3.14159; return PI` | `const PI = 3.14` |
| T21 | `const_local` | `const int MAX = 100; return MAX` | `MAX = 200` |
| T22 | `const_final` | `final name = 'Alice'; return name` | `'Bob'` |
| T23 | `const_static` | `static const TAG = 'v1'; return TAG` | `'v2'` |
| T24 | `const_list` | `const [1, 2, 3]` 长度 | `const [1, 2, 3, 4]` 长度 |
| T25 | `const_expr` | `const x = 2 * 3; return x` | `const x = 2 * 4; return x` |

### Category 5：函数类型（9 个）

| ID | 函数名 | 说明 |
|----|--------|------|
| T26 | `fn_toplevel` | 顶层函数返回值变化 |
| T27 | `fn_anonymous` | `final f = () => 42;` → `() => 99` |
| T28 | `fn_closure_capture` | 捕获外部变量的闭包，被捕获值改变 |
| T29 | `fn_named_param` | `f({required String name})` 拼接方式变 |
| T30 | `fn_optional_param` | `f([int x = 0])` 默认值变 |
| T31 | `fn_typedef` | typedef 函数类型签名使用方式变 |
| T32 | `fn_higher_order` | `applyTwice(f, x)` 中 f 的逻辑 |
| T33 | `fn_async` | `async` 函数返回的 Future 值变 |
| T34 | `fn_generator` | `sync*` generator yield 值变 |

### Category 6：类（8 个）

| ID | 函数名 | 说明 |
|----|--------|------|
| T35 | `cls_basic_method` | 普通类实例方法返回值 |
| T36 | `cls_static_method` | static 方法逻辑变 |
| T37 | `cls_getter` | `get value` 返回值变 |
| T38 | `cls_setter` | setter 存储转换方式变 |
| T39 | `cls_inheritance` | 子类 override 父类方法 |
| T40 | `cls_abstract` | abstract 基类的具体实现变 |
| T41 | `cls_mixin` | mixin 方法逻辑变 |
| T42 | `cls_enum` | enum 扩展方法返回值变 |

### Category 7：泛型（4 个）

| ID | 函数名 | 说明 |
|----|--------|------|
| T43 | `generic_fn` | `T identity<T>(T x)` 加个 toString 包装 |
| T44 | `generic_class` | `Box<T>.value` getter 逻辑变 |
| T45 | `generic_constraint` | `T extends num` 的函数计算方式变 |
| T46 | `generic_list` | `List<T>` 泛型操作逻辑变 |

### Category 8：运算符（5 个）

| ID | 函数名 | 说明 |
|----|--------|------|
| T47 | `op_arithmetic` | `a + b * c` → `a * b + c` |
| T48 | `op_comparison` | `>=` → `>` |
| T49 | `op_logical` | `&&` → `\|\|` |
| T50 | `op_bitwise` | `a & b` → `a \| b` |
| T51 | `op_custom` | operator+ 自定义返回值变 |

### Category 9：异步（4 个）

> 注意：dart2bytecode 对 async/await 的支持有限制，这批场景用于探测边界

| ID | 函数名 | 说明 | 预期状态 |
|----|--------|------|---------|
| T52 | `async_future_value` | `async { return 42; }` → `return 99` | ⚠️ 待验证 |
| T53 | `async_await_chain` | await 链中间值变 | ⚠️ 待验证 |
| T54 | `async_future_error` | 抛出不同错误类型 | ⚠️ 待验证 |
| T55 | `async_stream` | `Stream.fromIterable` 值变 | ⚠️ 待验证 |

### Category 10：错误处理（4 个）

| ID | 函数名 | 说明 |
|----|--------|------|
| T56 | `err_try_catch` | catch 块返回不同字符串 |
| T57 | `err_throw` | throw 不同错误消息 |
| T58 | `err_on_type` | `on FormatException` → `on ArgumentError` |
| T59 | `err_finally` | finally 块副作用 flag 变 |

### Category 11：字符串（4 个）

| ID | 函数名 | 说明 |
|----|--------|------|
| T60 | `str_interpolation` | `'Hello $name'` → `'Hi $name!'` |
| T61 | `str_multiline` | 多行字符串内容变 |
| T62 | `str_raw` | `r'\n'` → `r'\t'` |
| T63 | `str_regexp` | RegExp pattern 变 |

### Category 12：第三方库（5 个）

> 使用纯 Dart 包：`intl`、`collection`、`crypto`、`path`

| ID | 函数名 | 说明 |
|----|--------|------|
| T64 | `third_intl_format` | `NumberFormat` 格式符变 |
| T65 | `third_intl_date` | `DateFormat` 模板变 |
| T66 | `third_collection` | `IterableExtension.firstWhereOrNull` 条件变 |
| T67 | `third_crypto` | `sha256` → `md5`（返回不同哈希） |
| T68 | `third_path` | `path.join` 子路径变 |

### Category 13：Flutter-like 模式（5 个）

> 无 Flutter Engine，测试 widget 等价的纯 Dart 模式

| ID | 函数名 | 说明 |
|----|--------|------|
| T69 | `flutter_counter_logic` | `Counter.increment()` 步长 1→2 |
| T70 | `flutter_state_compute` | `State.build()` 计算逻辑变 |
| T71 | `flutter_builder_fn` | Builder 回调返回的字符串变 |
| T72 | `flutter_callback` | `onPressed` 回调逻辑变 |
| T73 | `flutter_form_validate` | 表单验证规则变 |

### Category 14：传递闭包传播（8 个）

| ID | 函数名 | 说明 | 验证重点 |
|----|--------|------|---------|
| T74 | `prop_2level` | A→B，B 变 → A 在 affected | 2 层链 |
| T75 | `prop_3level` | A→B→C，C 变 → B、A 都在 affected | 3 层链 |
| T76 | `prop_4level` | A→B→C→D，D 变 | 4 层链 |
| T77 | `prop_diamond` | A→B、A→C，B 变 → A affected，C 不变 | 菱形 |
| T78 | `prop_multichange` | B+D 同时变，传播合并 | 多点同时 |
| T79 | `prop_unchanged_sibling` | A→B→C，C 变，D 调 B 但 B 未变 | 兄弟节点不误报 |
| T80 | `prop_cross_class` | 跨类方法调用链 | 类边界传播 |
| T81 | `prop_static_chain` | static 方法调用链 | 静态调用传播 |

### Category 15：类层次变更检测（5 个）

| ID | 说明 | 预期 kernel_linker 输出 |
|----|------|----------------------|
| T82 | 类增加实例字段 | `class_hierarchy_changed: true`，补丁被拒 |
| T83 | 类删除实例字段 | `class_hierarchy_changed: true`，补丁被拒 |
| T84 | 新增顶层类 | `added` 集合包含新类的方法 |
| T85 | 删除顶层类 | `removed` 集合包含 |
| T86 | 改变继承关系 | `class_hierarchy_changed: true` |

### Category 16：边界/回归（5 个）

| ID | 函数名 | 说明 |
|----|--------|------|
| T87 | `edge_empty_fn` | 空函数 `{}` → `return null` |
| T88 | `edge_recursive` | 递归函数终止条件值变 |
| T89 | `edge_mutual_recursive` | 互递归 f→g→f，g 变 |
| T90 | `edge_large_string` | 返回 1000+ 字符字符串，内容变 |
| T91 | `edge_identity_same` | 基线 == 补丁（identity），预期 0 changes |

---

## 3. 场景实现规范

每个 `lib/tXX_*.dart` 文件：

```dart
// lib/t01_primitives.dart
library hotpatch_validation.t01_primitives;

// 每个函数必须加 @pragma('vm:entry-point') 和 @pragma('vm:never-inline')
@pragma('vm:entry-point') @pragma('vm:never-inline')
int prim_int() => 42;

@pragma('vm:entry-point') @pragma('vm:never-inline')
double prim_double() => 3.14;

// ...
```

对应 `patches/t01_primitives.dart`（**相同 library 声明，相同文件路径编译**）：

```dart
library hotpatch_validation.t01_primitives;

@pragma('vm:entry-point') @pragma('vm:never-inline')
int prim_int() => 100;    // ← 唯一变化

@pragma('vm:entry-point') @pragma('vm:never-inline')
double prim_double() => 3.14;  // ← 不变，验证无误报
```

---

## 4. harness 设计

```dart
// harness/registry.dart
class TestCase {
  final String id;
  final String description;
  final String Function() baselineFn;
  final String expectedPatchResult;
  TestCase(this.id, this.description, this.baselineFn, this.expectedPatchResult);
}

// 所有 91 个场景注册
final testRegistry = [
  TestCase('T01', 'prim_int', () => prim_int().toString(), '100'),
  TestCase('T02', 'prim_double', () => prim_double().toString(), '2.72'),
  // ...
];
```

```dart
// harness/main_harness.dart
@pragma('vm:entry-point')
String runAll() {
  // 对已加载的 patch 库调用每个函数，收集结果
  // 返回 JSON 字符串
  return jsonEncode(results);
}

@pragma('vm:entry-point')
String runCase(String id) {
  // 运行单个场景
}
```

C 层：

```c
// 加载 patch dill 后，调用 Dart_Invoke(patch_lib, "runCase", ...) 
// 用 ID 参数指定场景，返回结果字符串
```

---

## 5. expected.json 格式

```json
{
  "T01": {
    "kernel_linker": {
      "changed_functions": ["hotpatch_validation.t01_primitives::prim_int"],
      "affected_closure": [],
      "class_hierarchy_changed": false,
      "unchanged_functions": ["hotpatch_validation.t01_primitives::prim_double", "..."]
    },
    "runtime": {
      "expected_output": "100"
    }
  }
}
```

---

## 6. 覆盖率报告格式

### COVERAGE_REPORT.md（汇总）

```markdown
# iOS Hotpatch 生产验证报告
日期：2026-08-XX | 设备：iPhone 14 (iOS 26.5.2) | SDK：1aa7d7321fb

## 总体指标
| 指标 | 数值 | 目标 |
|------|------|------|
| 总场景数 | 91 | 91 |
| Kernel 正确率 | XX/91 (XX%) | ≥95% |
| 漏判率（False Negative） | 0/XX (0%) | 0% |
| 误报率（False Positive） | 0/XX (0%) | 0% |
| 运行时正确率 | XX/87 (XX%) | ≥90% |
| 崩溃率 | 0/91 (0%) | 0% |
| 已知不支持 | 4 (async/Stream) | — |

## 按类别分布
| 类别 | 总数 | Kernel通过 | 运行时通过 |
|------|------|-----------|-----------|
| 基本类型 | 7 | 7/7 | 7/7 |
| ...
```

### COVERAGE_DETAIL.md（逐条）

每条场景：
```markdown
### T01 prim_int ✅
- **类别**：基本类型 / int 字面量
- **Kernel**：PASS — changed=[prim_int], unchanged=[prim_double,...], hierarchy=false
- **Runtime**：PASS — expected="100", actual="100"
- **备注**：—
```

---

## 7. 成功标准

| 层面 | 指标 | 生产可信阈值 |
|------|------|------------|
| Kernel 正确率 | 无漏判 | **100%（硬性要求）** |
| Kernel 误报率 | 无误报 | **0%（硬性要求）** |
| 运行时正确率 | 非 async 场景 | **≥95%** |
| 崩溃率 | 任何场景 | **0%（硬性要求）** |
| 已知限制 | 有完整文档 | async/Stream 标注 |

---

## 8. 已知限制（预置）

| 限制 | 涉及场景 | 原因 |
|------|---------|------|
| async/await 不完整支持 | T52-T55 | dart2bytecode 对 async 字节码的支持有限 |
| 第三方库需 dynamic_interface.yaml | T64-T68 | 补丁引用的符号须在基线 AOT 保留 |
| class_hierarchy_changed 补丁被拒 | T82-T86 | 设计如此，非缺陷 |
| Flutter Engine 渲染 | T69-T73 | 裸 Dart VM，无渲染层 |

---

## 9. 与其他里程碑的接口

- **kernel_linker**：使用生产版（`spikes/gate2_linker/tools/kernel_linker/`）
- **patch_builder**：使用 `tools/patch_builder/patch_builder.py`
- **Xcode App**：基于 M3 HotPatchDemo 改造，添加多场景路由
- **设备**：iPhone 14（UDID `040F89ED-E7CC-54B0-A7BB-908EE82C0224`）
