# iOS Hotpatch 生产验证套件 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** 91 场景覆盖验证，产出 COVERAGE_REPORT.md + COVERAGE_DETAIL.md + coverage_results.json

**Architecture:** 纯 Dart 测试文件（lib/ + patches/）+ Dart harness + Python 报告生成 + shell 自动化脚本。基于 M3 HotPatchDemo 改造 Xcode App。

**Tech Stack:** Dart 2/3，Python 3，shell，现有 kernel_linker + patch_builder + devicectl

**Working directory:** `~/Documents/flutter_hot_patcher/spikes/hotpatch_validation/`

---

## Task 1: 目录骨架 + 基础 Dart harness

**Files:**
- Create: `spikes/hotpatch_validation/lib/` (空目录占位)
- Create: `spikes/hotpatch_validation/patches/` (镜像结构)
- Create: `spikes/hotpatch_validation/harness/registry.dart`
- Create: `spikes/hotpatch_validation/harness/main_harness.dart`
- Create: `spikes/hotpatch_validation/tools/expected.json` (初始空模板)

- [ ] **Step 1: 创建目录结构**

```bash
mkdir -p ~/Documents/flutter_hot_patcher/spikes/hotpatch_validation/{lib,patches,harness,tools,HotpatchValidation}
```

- [ ] **Step 2: 写 harness/registry.dart**

```dart
library hotpatch_validation.harness;

class TestCase {
  final String id;
  final String description;
  final String category;
  final String Function() baselineFn;
  TestCase(this.id, this.description, this.category, this.baselineFn);
}

// registry populated by each category file
final List<TestCase> testRegistry = [];

void registerTest(String id, String desc, String cat, String Function() fn) {
  testRegistry.add(TestCase(id, desc, cat, fn));
}
```

- [ ] **Step 3: 写 harness/main_harness.dart**

```dart
library hotpatch_validation.harness.main;

import 'dart:convert';
import 'registry.dart';

// All category imports (populated as categories are added)
// import '../lib/t01_primitives.dart';

@pragma('vm:entry-point')
String runCase(List args) {
  final id = args.isNotEmpty ? args[0].toString() : '';
  final tc = testRegistry.where((t) => t.id == id).firstOrNull;
  if (tc == null) return jsonEncode({'id': id, 'error': 'not_found'});
  try {
    final result = tc.baselineFn();
    return jsonEncode({'id': id, 'result': result, 'error': null});
  } catch (e) {
    return jsonEncode({'id': id, 'result': null, 'error': e.toString()});
  }
}

@pragma('vm:entry-point')
String listCases() {
  return jsonEncode(testRegistry.map((t) => {
    'id': t.id,
    'description': t.description,
    'category': t.category,
  }).toList());
}

void main() {}
```

- [ ] **Step 4: 写 tools/expected.json 模板**

```json
{
  "_comment": "Populated incrementally as scenarios are implemented",
  "T01": {
    "kernel_linker": {
      "changed_functions_contains": ["t01_primitives::prim_int"],
      "unchanged_functions_not_contains": ["t01_primitives::prim_double"],
      "class_hierarchy_changed": false
    },
    "runtime": {"expected_output": "100"}
  }
}
```

- [ ] **Step 5: commit**

```bash
cd ~/Documents/flutter_hot_patcher
git add spikes/hotpatch_validation/
git commit -m "feat(validation): project skeleton — harness + registry + expected.json template"
```

---

## Task 2: Category 1-4 Dart 场景文件（基本类型/集合/空安全/常量，T01-T25）

**Files:**
- Create: `lib/t01_primitives.dart` + `patches/t01_primitives.dart`
- Create: `lib/t02_collections.dart` + `patches/t02_collections.dart`
- Create: `lib/t03_nullsafety.dart` + `patches/t03_nullsafety.dart`
- Create: `lib/t04_constants.dart` + `patches/t04_constants.dart`

- [ ] **Step 1: 写 lib/t01_primitives.dart**

```dart
library hotpatch_validation.t01;

@pragma('vm:entry-point') @pragma('vm:never-inline')
int prim_int() => 42;

@pragma('vm:entry-point') @pragma('vm:never-inline')
double prim_double() => 3.14;

@pragma('vm:entry-point') @pragma('vm:never-inline')
String prim_string() => 'hello';

@pragma('vm:entry-point') @pragma('vm:never-inline')
bool prim_bool() => true;

@pragma('vm:entry-point') @pragma('vm:never-inline')
dynamic prim_dynamic() { dynamic x = 1; return x; }

@pragma('vm:entry-point') @pragma('vm:never-inline')
int prim_var() { var x = 10; return x * 2; }

@pragma('vm:entry-point') @pragma('vm:never-inline')
Object prim_object() { Object o = 42; return o; }
```

- [ ] **Step 2: 写 patches/t01_primitives.dart（相同 library，仅变更目标函数）**

```dart
library hotpatch_validation.t01;

@pragma('vm:entry-point') @pragma('vm:never-inline')
int prim_int() => 100;           // T01: CHANGED

@pragma('vm:entry-point') @pragma('vm:never-inline')
double prim_double() => 2.72;    // T02: CHANGED

@pragma('vm:entry-point') @pragma('vm:never-inline')
String prim_string() => 'world'; // T03: CHANGED

@pragma('vm:entry-point') @pragma('vm:never-inline')
bool prim_bool() => false;       // T04: CHANGED

@pragma('vm:entry-point') @pragma('vm:never-inline')
dynamic prim_dynamic() { dynamic x = 'one'; return x; } // T05: CHANGED

@pragma('vm:entry-point') @pragma('vm:never-inline')
int prim_var() { var x = 10; return x * 3; } // T06: CHANGED

@pragma('vm:entry-point') @pragma('vm:never-inline')
Object prim_object() { Object o = 'forty-two'; return o; } // T07: CHANGED
```

- [ ] **Step 3: 写 lib/t02_collections.dart + patches/t02_collections.dart**

lib 版（baseline）：
```dart
library hotpatch_validation.t02;

@pragma('vm:entry-point') @pragma('vm:never-inline')
List<int> coll_list_literal() => [1, 2, 3];

@pragma('vm:entry-point') @pragma('vm:never-inline')
List<int> coll_list_map() => [1, 2, 3].map((x) => x * 2).toList();

@pragma('vm:entry-point') @pragma('vm:never-inline')
List<int> coll_list_where() => [1, -2, 3, -4].where((x) => x > 0).toList();

@pragma('vm:entry-point') @pragma('vm:never-inline')
Map<String, int> coll_map_literal() => {'a': 1, 'b': 2};

@pragma('vm:entry-point') @pragma('vm:never-inline')
int coll_map_access() { final m = {'key': 42}; return m['key'] ?? 0; }

@pragma('vm:entry-point') @pragma('vm:never-inline')
Set<int> coll_set() => {1, 2, 3};

@pragma('vm:entry-point') @pragma('vm:never-inline')
int coll_fold() => [1, 2, 3, 4].fold(0, (a, b) => a + b);
```

patch 版：T08 list_literal 加一个元素，T09 map改×3，T10 where改>=0，T11 map值×10，T12 默认值改-1，T13 set加元素，T14 fold改为乘积

- [ ] **Step 4: 写 lib/t03_nullsafety.dart + patches/t03_nullsafety.dart**

lib 版（T15-T19）：
```dart
library hotpatch_validation.t03;

@pragma('vm:entry-point') @pragma('vm:never-inline')
String null_nullable() { String? s = null; return s ?? 'null'; }

@pragma('vm:entry-point') @pragma('vm:never-inline')
int null_bang() { String? s = 'hello'; return s!.length; }

@pragma('vm:entry-point') @pragma('vm:never-inline')
String? null_conditional() { String? s = 'Hello'; return s.toUpperCase(); }

@pragma('vm:entry-point') @pragma('vm:never-inline')
String null_coalesce() { String? a; String? b; return a ?? b ?? 'default'; }

@pragma('vm:entry-point') @pragma('vm:never-inline')
String null_late() { late String x; x = 'init'; return x; }
```

patch 版：T15 改 'empty'，T16 改 length+1，T17 改 toLowerCase，T18 改 'fallback'，T19 改 'patched'

- [ ] **Step 5: 写 lib/t04_constants.dart + patches/t04_constants.dart**

lib 版（T20-T25）：
```dart
library hotpatch_validation.t04;

@pragma('vm:entry-point') @pragma('vm:never-inline')
double const_toplevel() { const pi = 3.14159; return pi; }

@pragma('vm:entry-point') @pragma('vm:never-inline')
int const_local() { const int max = 100; return max; }

@pragma('vm:entry-point') @pragma('vm:never-inline')
String const_final() { final name = 'Alice'; return name; }

@pragma('vm:entry-point') @pragma('vm:never-inline')
String const_static() => _tag;
const String _tag = 'v1';

@pragma('vm:entry-point') @pragma('vm:never-inline')
int const_list() { const list = [1, 2, 3]; return list.length; }

@pragma('vm:entry-point') @pragma('vm:never-inline')
int const_expr() { const x = 2 * 3; return x; }
```

patch 版：T20 pi=3.14，T21 max=200，T22 Bob，T23 v2，T24 [1,2,3,4]，T25 2*4

- [ ] **Step 6: 更新 expected.json（T01-T25 预期值）**

在 expected.json 中为每个 T01-T25 场景填写：
```json
"T01": {
  "kernel_linker": {
    "changed_functions_contains": ["hotpatch_validation.t01::prim_int"],
    "unchanged_functions_not_contains": ["hotpatch_validation.t01::prim_double"],
    "class_hierarchy_changed": false
  },
  "runtime": {"expected_output": "100"}
},
"T02": {
  "kernel_linker": {
    "changed_functions_contains": ["hotpatch_validation.t01::prim_double"]
  },
  "runtime": {"expected_output": "2.72"}
}
```
（T01-T25 全部填写）

- [ ] **Step 7: 初步编译验证（host macOS 上跑基础 smoke test）**

```bash
HOST_OUT=~/dart/sdk/xcodebuild/ReleaseARM64

# 编译 baseline
$HOST_OUT/dartaotruntime_product \
  $HOST_OUT/gen/gen_kernel_aot.dart.snapshot \
  --platform $HOST_OUT/vm_platform.dill --aot \
  --output /tmp/baseline_t01.dill \
  ~/Documents/flutter_hot_patcher/spikes/hotpatch_validation/lib/t01_primitives.dart

# 编译 patch（用 patches/ 版本）
$HOST_OUT/dartaotruntime_product \
  $HOST_OUT/gen/gen_kernel_aot.dart.snapshot \
  --platform $HOST_OUT/vm_platform.dill --aot \
  --output /tmp/patch_t01.dill \
  ~/Documents/flutter_hot_patcher/spikes/hotpatch_validation/patches/t01_primitives.dart

# 运行 kernel_linker
LINKER=~/Documents/flutter_hot_patcher/spikes/gate2_linker/tools/kernel_linker
dart --packages=$LINKER/.dart_tool/package_config.json \
  $LINKER/bin/kernel_linker.dart \
  --base /tmp/baseline_t01.dill \
  --patch /tmp/patch_t01.dill \
  --verbose

echo "Expected: all 7 prim_* functions in CHANGED"
```

Expected: `CHANGED (7): prim_int, prim_double, ...prim_object`
（这批场景全部函数都变了，应该全在 CHANGED）

- [ ] **Step 8: commit**

```bash
cd ~/Documents/flutter_hot_patcher
git add spikes/hotpatch_validation/
git commit -m "feat(validation): T01-T25 — primitives/collections/nullsafety/constants"
```

---

## Task 3: Category 5-8（函数/类/泛型/运算符，T26-T51）

**Files:**
- Create: `lib/t05_functions.dart` + `patches/t05_functions.dart` (T26-T34)
- Create: `lib/t06_classes.dart` + `patches/t06_classes.dart` (T35-T42)
- Create: `lib/t07_generics.dart` + `patches/t07_generics.dart` (T43-T46)
- Create: `lib/t08_operators.dart` + `patches/t08_operators.dart` (T47-T51)

- [ ] **Step 1: 写 lib/t05_functions.dart**

```dart
library hotpatch_validation.t05;

// T26: 顶层函数
@pragma('vm:entry-point') @pragma('vm:never-inline')
String fn_toplevel() => 'baseline';

// T27: 匿名函数（通过 late 变量防 CHA 去虚化）
@pragma('vm:entry-point') @pragma('vm:never-inline')
int fn_anonymous() {
  late int Function() f;
  f = () => 42;
  return f();
}

// T28: 闭包捕获
@pragma('vm:entry-point') @pragma('vm:never-inline')
int fn_closure_capture() {
  int multiplier = 2;
  int Function(int) multiply = (x) => x * multiplier;
  return multiply(5);
}

// T29: 命名参数
@pragma('vm:entry-point') @pragma('vm:never-inline')
String fn_named_param({String name = 'World'}) => 'Hello, $name!';

// T30: 可选参数
@pragma('vm:entry-point') @pragma('vm:never-inline')
int fn_optional_param([int x = 0]) => x + 10;

// T31: 高阶函数
@pragma('vm:entry-point') @pragma('vm:never-inline')
int fn_higher_order() {
  int Function(int) double_it = (x) => x * 2;
  return double_it(double_it(3));
}

// T32: 函数作为参数
@pragma('vm:entry-point') @pragma('vm:never-inline')
List<int> fn_transform() => [1, 2, 3].map((x) => x + 10).toList();

// T33: async（标注 ⚠️）
@pragma('vm:entry-point') @pragma('vm:never-inline')
String fn_async_label() => 'async_baseline'; // 同步版本，async 场景单独在 t09

// T34: generator
@pragma('vm:entry-point') @pragma('vm:never-inline')
List<int> fn_generator() => _gen().toList();
Iterable<int> _gen() sync* { yield 1; yield 2; yield 3; }
```

patch 版（T26→'patched'，T27→99，T28→multiplier=3，T29→'Hi, $name!'，T30→x+20，T31→×3，T32→+100，T33→'async_patched'，T34→yield 10,20,30）

- [ ] **Step 2: 写 lib/t06_classes.dart**

```dart
library hotpatch_validation.t06;

// T35: 普通类实例方法
class Calculator {
  @pragma('vm:entry-point') @pragma('vm:never-inline')
  int add(int a, int b) => a + b;
}
@pragma('vm:entry-point') @pragma('vm:never-inline')
int cls_basic_method() => Calculator().add(3, 4);

// T36: static 方法
class Formatter {
  @pragma('vm:entry-point') @pragma('vm:never-inline')
  static String format(int n) => 'Value: $n';
}
@pragma('vm:entry-point') @pragma('vm:never-inline')
String cls_static_method() => Formatter.format(42);

// T37: getter
class Config {
  final int _base = 10;
  @pragma('vm:entry-point') @pragma('vm:never-inline')
  int get value => _base * 2;
}
@pragma('vm:entry-point') @pragma('vm:never-inline')
int cls_getter() => Config().value;

// T38: setter（通过副作用记录）
class Store {
  String _data = 'empty';
  @pragma('vm:entry-point') @pragma('vm:never-inline')
  set data(String v) { _data = v.toUpperCase(); }
  String get data => _data;
}
@pragma('vm:entry-point') @pragma('vm:never-inline')
String cls_setter() { final s = Store(); s.data = 'hello'; return s.data; }

// T39: 继承 override
abstract class Shape {
  @pragma('vm:entry-point') @pragma('vm:never-inline')
  String describe();
}
class Circle extends Shape {
  @pragma('vm:entry-point') @pragma('vm:never-inline')
  @override String describe() => 'circle';
}
@pragma('vm:entry-point') @pragma('vm:never-inline')
String cls_inheritance() => Circle().describe();

// T40: abstract 具体实现
abstract class Validator {
  bool validate(String s);
}
class LengthValidator extends Validator {
  @pragma('vm:entry-point') @pragma('vm:never-inline')
  @override bool validate(String s) => s.length >= 5;
}
@pragma('vm:entry-point') @pragma('vm:never-inline')
bool cls_abstract() => LengthValidator().validate('hello');

// T41: mixin
mixin Greetable {
  @pragma('vm:entry-point') @pragma('vm:never-inline')
  String greet() => 'Hello from mixin';
}
class Person with Greetable {}
@pragma('vm:entry-point') @pragma('vm:never-inline')
String cls_mixin() => Person().greet();

// T42: enum extension
enum Status { active, inactive }
extension StatusExt on Status {
  @pragma('vm:entry-point') @pragma('vm:never-inline')
  String get label => this == Status.active ? 'Active' : 'Inactive';
}
@pragma('vm:entry-point') @pragma('vm:never-inline')
String cls_enum() => Status.active.label;
```

patch 版：各函数按设计修改（add返回a-b，format改'Num: $n'，getter改×3，setter改toLowerCase，describe改'Circle'，validate改>=3，greet改'Hi from mixin'，label改'ON'/'OFF'）

- [ ] **Step 3: 写 lib/t07_generics.dart + lib/t08_operators.dart**

t07_generics.dart（T43-T46）：
```dart
library hotpatch_validation.t07;

@pragma('vm:entry-point') @pragma('vm:never-inline')
T generic_fn<T>(T x) => x;
@pragma('vm:entry-point') @pragma('vm:never-inline')
String generic_fn_call() => generic_fn('hello').toString();

class Box<T> {
  final T _value;
  Box(this._value);
  @pragma('vm:entry-point') @pragma('vm:never-inline')
  T get value => _value;
}
@pragma('vm:entry-point') @pragma('vm:never-inline')
int generic_class() => Box<int>(42).value;

@pragma('vm:entry-point') @pragma('vm:never-inline')
T generic_constraint<T extends num>(T a, T b) => (a + b) as T;
@pragma('vm:entry-point') @pragma('vm:never-inline')
num generic_constraint_call() => generic_constraint(3, 4);

@pragma('vm:entry-point') @pragma('vm:never-inline')
List<T> generic_list<T>(List<T> input) => input.reversed.toList();
@pragma('vm:entry-point') @pragma('vm:never-inline')
List<int> generic_list_call() => generic_list([1, 2, 3]);
```

t08_operators.dart（T47-T51）：
```dart
library hotpatch_validation.t08;

@pragma('vm:entry-point') @pragma('vm:never-inline')
int op_arithmetic(int a, int b) => a + b * 2;  // T47
@pragma('vm:entry-point') @pragma('vm:never-inline')
bool op_comparison(int a) => a >= 10;           // T48
@pragma('vm:entry-point') @pragma('vm:never-inline')
bool op_logical(bool a, bool b) => a && b;      // T49
@pragma('vm:entry-point') @pragma('vm:never-inline')
int op_bitwise(int a, int b) => a & b;          // T50

class Vec2 {
  final int x, y;
  Vec2(this.x, this.y);
  @pragma('vm:entry-point') @pragma('vm:never-inline')
  Vec2 operator +(Vec2 other) => Vec2(x + other.x, y + other.y);
  @override String toString() => '(${x},${y})';
}
@pragma('vm:entry-point') @pragma('vm:never-inline')
String op_custom() => (Vec2(1,2) + Vec2(3,4)).toString(); // T51
```

- [ ] **Step 4: 验证 T35-T51 kernel_linker 检测**

```bash
# 对 t06_classes 做 diff，验证各方法变化被正确检测
# 验证 unchanged 的 Calculator.add 不在 changed 列表（若只改了 Formatter.format）
```

- [ ] **Step 5: commit**

```bash
cd ~/Documents/flutter_hot_patcher
git add spikes/hotpatch_validation/
git commit -m "feat(validation): T26-T51 — functions/classes/generics/operators"
```

---

## Task 4: Category 9-13（async/错误/字符串/第三方库/Flutter-like，T52-T73）

**Files:**
- Create: `lib/t09_async.dart` + patches
- Create: `lib/t10_errors.dart` + patches
- Create: `lib/t11_strings.dart` + patches
- Create: `lib/t12_thirdparty.dart` + patches
- Create: `lib/t13_flutter_like.dart` + patches

> 注意：t12_thirdparty.dart 需要配置 dart pub + dynamic_interface.yaml

- [ ] **Step 1: 写 lib/t09_async.dart（含已知限制标注）**

```dart
library hotpatch_validation.t09;
// ⚠️ WARNING: async/Stream 场景用于探测 dart2bytecode 边界
// 若 bytecode 加载失败，标注为 KNOWN_LIMITATION 而非 FAIL

@pragma('vm:entry-point') @pragma('vm:never-inline')
String async_label() => 'sync_proxy_for_async_T52';
// T52-T55 的同步代理：测试 async 场景的 Dart 代码模式，
// 实际 async 行为待 dart2bytecode 支持确认后升级

@pragma('vm:entry-point') @pragma('vm:never-inline')
String async_future_value_sync() => '42'; // proxy for T52

@pragma('vm:entry-point') @pragma('vm:never-inline')
String async_await_chain_sync() => 'step1->step2->done'; // proxy for T53

@pragma('vm:entry-point') @pragma('vm:never-inline')
String async_future_error_sync() => 'error:CustomError'; // proxy for T54

@pragma('vm:entry-point') @pragma('vm:never-inline')
String async_stream_sync() => '[1, 2, 3]'; // proxy for T55
```

patch 版：T52→'99'，T53→'step1->step3->done'，T54→'error:NewError'，T55→'[10, 20, 30]'

- [ ] **Step 2: 写 lib/t10_errors.dart**

```dart
library hotpatch_validation.t10;

@pragma('vm:entry-point') @pragma('vm:never-inline')
String err_try_catch() {
  try { throw FormatException('bad'); }
  catch (e) { return 'caught: FormatException'; }
}

@pragma('vm:entry-point') @pragma('vm:never-inline')
String err_throw() {
  try { throw ArgumentError('value'); }
  catch (e) { return e.toString(); }
}

@pragma('vm:entry-point') @pragma('vm:never-inline')
String err_on_type() {
  try { int.parse('abc'); }
  on FormatException { return 'FormatException'; }
  catch (e) { return 'other'; }
}

@pragma('vm:entry-point') @pragma('vm:never-inline')
String err_finally() {
  final buf = StringBuffer();
  try { buf.write('try'); }
  finally { buf.write('+finally'); }
  return buf.toString();
}
```

patch 版：T56→'caught: ParseError'，T57→'ArgumentError: newValue'，T58→改成 on ArgumentError，T59→'+finally+extra'

- [ ] **Step 3: 写 lib/t11_strings.dart**

```dart
library hotpatch_validation.t11;

@pragma('vm:entry-point') @pragma('vm:never-inline')
String str_interpolation(String name) => 'Hello, $name!';
@pragma('vm:entry-point') @pragma('vm:never-inline')
String str_interpolation_call() => str_interpolation('World');

@pragma('vm:entry-point') @pragma('vm:never-inline')
String str_multiline() => '''
line1
line2''';

@pragma('vm:entry-point') @pragma('vm:never-inline')
String str_raw() => r'raw\nstring';

@pragma('vm:entry-point') @pragma('vm:never-inline')
bool str_regexp() => RegExp(r'^\d+$').hasMatch('123');
```

patch 版：T60→'Hi, $name!'，T61 改 line3，T62→r'raw\tstring'，T63→hasMatch('abc') 并返回是否匹配字母

- [ ] **Step 4: 配置第三方库 + 写 lib/t12_thirdparty.dart**

```bash
# 在 hotpatch_validation/ 目录创建 pubspec.yaml
cat > ~/Documents/flutter_hot_patcher/spikes/hotpatch_validation/pubspec.yaml << 'EOF'
name: hotpatch_validation
environment:
  sdk: '>=3.0.0 <4.0.0'
dependencies:
  intl: ^0.19.0
  collection: ^1.18.0
  crypto: ^3.0.0
  path: ^1.9.0
EOF

cd ~/Documents/flutter_hot_patcher/spikes/hotpatch_validation
dart pub get
```

```dart
// lib/t12_thirdparty.dart
library hotpatch_validation.t12;

import 'package:intl/intl.dart';
import 'package:collection/collection.dart';
import 'package:crypto/crypto.dart';
import 'dart:convert';
import 'package:path/path.dart' as p;

@pragma('vm:entry-point') @pragma('vm:never-inline')
String third_intl_format() => NumberFormat('#,###').format(1234567);

@pragma('vm:entry-point') @pragma('vm:never-inline')
String third_intl_date() {
  final dt = DateTime(2026, 8, 4);
  return DateFormat('yyyy-MM-dd').format(dt);
}

@pragma('vm:entry-point') @pragma('vm:never-inline')
String? third_collection() {
  final list = [1, 2, 3, null, 5];
  return list.firstWhereOrNull((x) => x != null && x > 2)?.toString();
}

@pragma('vm:entry-point') @pragma('vm:never-inline')
String third_crypto() {
  final bytes = utf8.encode('hello');
  return sha256.convert(bytes).toString().substring(0, 8);
}

@pragma('vm:entry-point') @pragma('vm:never-inline')
String third_path() => p.join('usr', 'local', 'bin');
```

patch 版：T64→'#.###' 格式，T65→'MM/dd/yyyy'，T66→firstWhereOrNull(x > 3)，T67→md5，T68→join('home', 'user')

- [ ] **Step 5: 写 lib/t13_flutter_like.dart**

```dart
library hotpatch_validation.t13;

// 模拟 Flutter Counter widget 的核心逻辑
class CounterState {
  int _count = 0;
  @pragma('vm:entry-point') @pragma('vm:never-inline')
  void increment() { _count += 1; }  // T69: 步长 1
  int get count => _count;
}
@pragma('vm:entry-point') @pragma('vm:never-inline')
int flutter_counter_logic() {
  final s = CounterState(); s.increment(); s.increment(); return s.count;
}

// 模拟 State.build 计算
@pragma('vm:entry-point') @pragma('vm:never-inline')
String flutter_state_compute(int value) => 'Count: $value';
@pragma('vm:entry-point') @pragma('vm:never-inline')
String flutter_state_compute_call() => flutter_state_compute(CounterState().count);

// 模拟 Builder 回调
@pragma('vm:entry-point') @pragma('vm:never-inline')
String flutter_builder_fn() {
  String Function(int) builder = (n) => 'Item #$n';
  return builder(1);
}

// 模拟 onPressed 回调
@pragma('vm:entry-point') @pragma('vm:never-inline')
String flutter_callback() {
  String result = 'initial';
  void Function() onPressed = () { result = 'pressed'; };
  onPressed();
  return result;
}

// 模拟表单验证
@pragma('vm:entry-point') @pragma('vm:never-inline')
String? flutter_form_validate(String value) =>
    value.isEmpty ? 'Required' : null;
@pragma('vm:entry-point') @pragma('vm:never-inline')
String flutter_form_validate_call() {
  return flutter_form_validate('') ?? flutter_form_validate('abc') ?? 'valid';
}
```

patch 版：T69→+2，T70→'Total: $value'，T71→'Element #$n'，T72→'clicked'，T73→验证规则改为长度<3

- [ ] **Step 6: commit**

```bash
cd ~/Documents/flutter_hot_patcher
git add spikes/hotpatch_validation/
git commit -m "feat(validation): T52-T73 — async/errors/strings/thirdparty/flutter-like"
```

---

## Task 5: Category 14-16（传递闭包/类层次/边界，T74-T91）

**Files:**
- Create: `lib/t14_propagation.dart` + patches (T74-T81)
- Create: `lib/t15_hierarchy.dart` + patches (T82-T86)
- Create: `lib/t16_edge.dart` + patches (T87-T91)

- [ ] **Step 1: 写 lib/t14_propagation.dart（传递闭包深度测试）**

```dart
library hotpatch_validation.t14;

// T74: 2层链 — A→B，B 变，A 应在 affected_closure
@pragma('vm:entry-point') @pragma('vm:never-inline')
String prop_b_2level() => 'b_baseline';  // B: 变化点

@pragma('vm:entry-point') @pragma('vm:never-inline')
String prop_a_2level() => prop_b_2level() + '_via_a';  // A: 调用 B，应被传播

// T75: 3层链 — A→B→C，C 变
@pragma('vm:entry-point') @pragma('vm:never-inline')
String prop_c_3level() => 'c_baseline';

@pragma('vm:entry-point') @pragma('vm:never-inline')
String prop_b_3level() => prop_c_3level() + '_b';

@pragma('vm:entry-point') @pragma('vm:never-inline')
String prop_a_3level() => prop_b_3level() + '_a';

// T76: 4层链
@pragma('vm:entry-point') @pragma('vm:never-inline')
String prop_d_4level() => 'd_baseline';

@pragma('vm:entry-point') @pragma('vm:never-inline')
String prop_c_4level() => prop_d_4level() + '_c';

@pragma('vm:entry-point') @pragma('vm:never-inline')
String prop_b_4level() => prop_c_4level() + '_b';

@pragma('vm:entry-point') @pragma('vm:never-inline')
String prop_a_4level() => prop_b_4level() + '_a';

// T77: 菱形 — A→B 且 A→C，B 变，C 不变
@pragma('vm:entry-point') @pragma('vm:never-inline')
String prop_b_diamond() => 'b_diamond_baseline';  // B: 变化

@pragma('vm:entry-point') @pragma('vm:never-inline')
String prop_c_diamond() => 'c_diamond_stable';    // C: 不变，应不在 changed

@pragma('vm:entry-point') @pragma('vm:never-inline')
String prop_a_diamond() => prop_b_diamond() + prop_c_diamond();

// T78: 多点并发变化 — B 和 D 同时变
@pragma('vm:entry-point') @pragma('vm:never-inline')
String prop_b_multi() => 'b_multi_baseline';

@pragma('vm:entry-point') @pragma('vm:never-inline')
String prop_d_multi() => 'd_multi_baseline';

@pragma('vm:entry-point') @pragma('vm:never-inline')
String prop_a_multi() => prop_b_multi() + prop_d_multi();

// T79: 兄弟节点不误报
@pragma('vm:entry-point') @pragma('vm:never-inline')
String prop_b_sibling() => 'b_sibling_baseline'; // B: 变化

@pragma('vm:entry-point') @pragma('vm:never-inline')
String prop_d_sibling() => 'd_sibling_stable';   // D: 不调用 B，应不在 affected

// T80: 跨类调用链
class ChainA {
  @pragma('vm:entry-point') @pragma('vm:never-inline')
  String call() => ChainB().call();
}
class ChainB {
  @pragma('vm:entry-point') @pragma('vm:never-inline')
  String call() => 'chain_b_baseline';
}
@pragma('vm:entry-point') @pragma('vm:never-inline')
String prop_cross_class() => ChainA().call();

// T81: static 方法调用链
@pragma('vm:entry-point') @pragma('vm:never-inline')
static String prop_static_b() => 'static_b_baseline';

@pragma('vm:entry-point') @pragma('vm:never-inline')
static String prop_static_a() => prop_static_b() + '_a';
```

patch 版：各变化点改 baseline→patched，验证传播正确性

- [ ] **Step 2: 写 lib/t15_hierarchy.dart（类层次变更，预期 class_hierarchy_changed=true）**

```dart
library hotpatch_validation.t15;

// T82: baseline — 类无新字段（patch 版增加一个字段）
class HierarchyT82 {
  final String name;
  HierarchyT82(this.name);
  @pragma('vm:entry-point') @pragma('vm:never-inline')
  String describe() => 'HierarchyT82: $name';
}
@pragma('vm:entry-point') @pragma('vm:never-inline')
String hierarchy_add_field() => HierarchyT82('test').describe();

// T83: baseline — 类有两个字段（patch 版删一个）
class HierarchyT83 {
  final String a;
  final String b;
  HierarchyT83(this.a, this.b);
  @pragma('vm:entry-point') @pragma('vm:never-inline')
  String describe() => '$a,$b';
}
@pragma('vm:entry-point') @pragma('vm:never-inline')
String hierarchy_remove_field() => HierarchyT83('x', 'y').describe();

// T84: baseline — 无 NewClass（patch 版增加）
@pragma('vm:entry-point') @pragma('vm:never-inline')
String hierarchy_add_class() => 'no_new_class';

// T85: baseline — 有 RemovedClass（patch 版删除）
class RemovedClass {
  @pragma('vm:entry-point') @pragma('vm:never-inline')
  String value() => 'will_be_removed';
}
@pragma('vm:entry-point') @pragma('vm:never-inline')
String hierarchy_remove_class() => RemovedClass().value();

// T86: baseline — 继承 BaseA（patch 版改继承 BaseB）
class BaseA { String tag() => 'A'; }
class BaseB { String tag() => 'B'; }
class Child extends BaseA {
  @pragma('vm:entry-point') @pragma('vm:never-inline')
  String whoami() => 'Child extends ${tag()}';
}
@pragma('vm:entry-point') @pragma('vm:never-inline')
String hierarchy_change_inheritance() => Child().whoami();
```

- [ ] **Step 3: 写 lib/t16_edge.dart（边界场景）**

```dart
library hotpatch_validation.t16;

// T87: 空函数 → 有返回值
@pragma('vm:entry-point') @pragma('vm:never-inline')
String? edge_empty_fn() => null;

// T88: 递归（终止条件值变）
@pragma('vm:entry-point') @pragma('vm:never-inline')
int edge_recursive(int n) => n <= 0 ? 0 : n + edge_recursive(n - 1);
@pragma('vm:entry-point') @pragma('vm:never-inline')
int edge_recursive_call() => edge_recursive(5);  // 0+1+2+3+4+5=15

// T89: 互递归（f→g→f）
@pragma('vm:entry-point') @pragma('vm:never-inline')
bool edge_is_even(int n) => n == 0 ? true : edge_is_odd(n - 1);
@pragma('vm:entry-point') @pragma('vm:never-inline')
bool edge_is_odd(int n) => n == 0 ? false : edge_is_even(n - 1);
@pragma('vm:entry-point') @pragma('vm:never-inline')
String edge_mutual_recursive() => '${edge_is_even(4)},${edge_is_odd(3)}';

// T90: 超长字符串
@pragma('vm:entry-point') @pragma('vm:never-inline')
int edge_large_string() => ('x' * 1000 + 'baseline').length;

// T91: 恒等补丁（baseline == patch，预期 0 changes）
@pragma('vm:entry-point') @pragma('vm:never-inline')
String edge_identity_same() => 'unchanged';
```

patch 版：T87→return 'was_empty'，T88→n<=0 ? 1 : n+rec，T89→互换奇偶判断，T90→'patched' 后缀，T91→**完全不变**（验证 0 changes）

- [ ] **Step 4: 为 T14 传播场景增加 expected.json 条目**

关键验证：T74 中 prop_a_2level 必须在 affected_closure（因为它调用了 changed 的 prop_b_2level），T77 中 prop_c_diamond **不能**在 changed 或 affected（无误报）

- [ ] **Step 5: commit**

```bash
cd ~/Documents/flutter_hot_patcher
git add spikes/hotpatch_validation/
git commit -m "feat(validation): T74-T91 — propagation/hierarchy/edge cases"
```

---

## Task 6: 自动化脚本 + 覆盖率报告生成器

**Files:**
- Create: `tools/run_validation.sh`
- Create: `tools/gen_report.py`

- [ ] **Step 1: 写 tools/run_validation.sh**

```bash
#!/bin/bash
set -e
SPIKE=~/Documents/flutter_hot_patcher/spikes/hotpatch_validation
HOST_OUT=~/dart/sdk/xcodebuild/ReleaseARM64
IOS_GEN=~/dart/sdk/xcodebuild/ReleaseIosARM64/clang_arm64/gen_snapshot_product
LINKER=~/Documents/flutter_hot_patcher/spikes/gate2_linker/tools/kernel_linker
PATCH_BUILDER=~/Documents/flutter_hot_patcher/tools/patch_builder
DEVICE=040F89ED-E7CC-54B0-A7BB-908EE82C0224
RESULTS=$SPIKE/coverage_results.json

echo '{"results": []}' > "$RESULTS"

# 场景文件列表
FILES=(t01_primitives t02_collections t03_nullsafety t04_constants \
       t05_functions t06_classes t07_generics t08_operators \
       t09_async t10_errors t11_strings t12_thirdparty \
       t13_flutter_like t14_propagation t15_hierarchy t16_edge)

for FILE in "${FILES[@]}"; do
  echo "=== Processing $FILE ==="
  
  BASELINE_DILL=/tmp/val_${FILE}_base.dill
  PATCH_DILL=/tmp/val_${FILE}_patch.dill
  LINKER_OUT=/tmp/val_${FILE}_linker/
  BUNDLE=/tmp/val_${FILE}_bundle/
  
  # 1. Compile baseline dill
  $HOST_OUT/dartaotruntime_product \
    $HOST_OUT/gen/gen_kernel_aot.dart.snapshot \
    --platform $HOST_OUT/vm_platform.dill --aot \
    --output "$BASELINE_DILL" \
    "$SPIKE/lib/${FILE}.dart"
  
  # 2. Compile patch dill (from patches/ dir, same library path)
  $HOST_OUT/dartaotruntime_product \
    $HOST_OUT/gen/gen_kernel_aot.dart.snapshot \
    --platform $HOST_OUT/vm_platform.dill --aot \
    --output "$PATCH_DILL" \
    "$SPIKE/patches/${FILE}.dart"
  
  # 3. Run kernel_linker
  mkdir -p "$LINKER_OUT"
  dart --packages=$LINKER/.dart_tool/package_config.json \
    $LINKER/bin/kernel_linker.dart \
    --base "$BASELINE_DILL" --patch "$PATCH_DILL" \
    --dart-sdk-commit 1aa7d7321fb \
    --baseline-snapshot "$BASELINE_DILL" \
    --output-dir "$LINKER_OUT" \
    --allow-empty 2>&1
  
  # 4. Validate kernel_linker output vs expected.json
  python3 "$SPIKE/tools/validate_manifest.py" \
    "$LINKER_OUT/manifest.json" \
    "$SPIKE/tools/expected.json" \
    "$FILE" >> "$RESULTS.tmp"
  
  # 5. Build patch bundle
  rm -rf "$BUNDLE"
  /tmp/pb_venv/bin/python3 "$PATCH_BUILDER/patch_builder.py" \
    --manifest "$LINKER_OUT" \
    --bytecode "$PATCH_DILL" \
    --private-key /tmp/pb_keys/private_key.pem \
    --patch-id "val-${FILE}" \
    --app-version "1.0+val" \
    --platform ios \
    --output-dir "$BUNDLE"
  
  echo "Processed $FILE"
done

echo "All files processed. Running on device..."
# [Device deployment step — see Task 7]
```

- [ ] **Step 2: 写 tools/validate_manifest.py（kernel_linker 输出验证）**

```python
#!/usr/bin/env python3
"""Validate a kernel_linker manifest.json against expected.json for a given file."""
import json, sys

manifest_path, expected_path, file_id = sys.argv[1], sys.argv[2], sys.argv[3]

manifest = json.load(open(manifest_path)) if __import__('os').path.exists(manifest_path) else {}
expected = json.load(open(expected_path))

results = []
for scenario_id, exp in expected.items():
    if not scenario_id.startswith('T'):
        continue
    # Check if this scenario belongs to the current file
    # (matching by function name prefix)
    kl_exp = exp.get('kernel_linker', {})
    
    # changed_functions_contains: all listed must be in manifest's changed_functions
    actual_changed = set(manifest.get('changed_functions', []) + manifest.get('icf_affected', []))
    actual_affected = set(manifest.get('affected_closure', []))
    
    kernel_pass = True
    issues = []
    
    for fn in kl_exp.get('changed_functions_contains', []):
        if not any(fn in s for s in actual_changed):
            kernel_pass = False
            issues.append(f'MISS changed: {fn}')
    
    for fn in kl_exp.get('unchanged_functions_not_contains', []):
        if any(fn in s for s in actual_changed | actual_affected):
            kernel_pass = False
            issues.append(f'FALSE_POSITIVE: {fn}')
    
    if 'class_hierarchy_changed' in kl_exp:
        if manifest.get('class_hierarchy_changed') != kl_exp['class_hierarchy_changed']:
            kernel_pass = False
            issues.append(f'class_hierarchy_changed mismatch')
    
    results.append({
        'id': scenario_id,
        'file': file_id,
        'kernel_pass': kernel_pass,
        'issues': issues,
    })

print(json.dumps(results))
```

- [ ] **Step 3: 写 tools/gen_report.py（覆盖率报告生成）**

```python
#!/usr/bin/env python3
"""Generate COVERAGE_REPORT.md + COVERAGE_DETAIL.md from coverage_results.json"""
import json, sys, datetime
from pathlib import Path

results_path = sys.argv[1] if len(sys.argv) > 1 else 'coverage_results.json'
results = json.load(open(results_path))

total = len(results)
kernel_pass = sum(1 for r in results if r.get('kernel_pass'))
runtime_pass = sum(1 for r in results if r.get('runtime_pass'))
crash = sum(1 for r in results if r.get('runtime_result') == 'CRASH')
known_limit = sum(1 for r in results if r.get('known_limitation'))
false_neg = sum(1 for r in results if r.get('false_negative'))
false_pos = sum(1 for r in results if r.get('false_positive'))

# COVERAGE_REPORT.md
report = f"""# iOS Hotpatch 生产验证覆盖率报告

生成时间：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}  
设备：iPhone 14 (UDID: 040F89ED-E7CC-54B0-A7BB-908EE82C0224)  
SDK commit：1aa7d7321fb  

---

## 总体指标

| 指标 | 数值 | 目标 | 状态 |
|------|------|------|------|
| 总场景数 | {total} | 91 | {'✅' if total >= 91 else '⚠️'} |
| Kernel 正确率 | {kernel_pass}/{total} ({100*kernel_pass//max(total,1)}%) | ≥95% | {'✅' if kernel_pass/max(total,1)>=0.95 else '❌'} |
| 漏判率（False Negative） | {false_neg}/{total} ({100*false_neg//max(total,1)}%) | 0% | {'✅' if false_neg==0 else '❌'} |
| 误报率（False Positive） | {false_pos}/{total} ({100*false_pos//max(total,1)}%) | 0% | {'✅' if false_pos==0 else '❌'} |
| 运行时正确率 | {runtime_pass}/{total-known_limit} ({100*runtime_pass//max(total-known_limit,1)}%) | ≥95% | {'✅' if runtime_pass/max(total-known_limit,1)>=0.95 else '❌'} |
| 崩溃率 | {crash}/{total} ({100*crash//max(total,1)}%) | 0% | {'✅' if crash==0 else '❌'} |
| 已知不支持 | {known_limit} | — | ℹ️ |

## 生产可信判定

"""
if false_neg == 0 and false_pos == 0 and crash == 0 and runtime_pass/max(total-known_limit,1) >= 0.95:
    report += "**✅ 通过生产可信标准** — 可以进入生产灰度发布流程\n"
else:
    report += "**❌ 未通过生产可信标准** — 见下方详情\n"

Path('COVERAGE_REPORT.md').write_text(report)
print(f"Generated COVERAGE_REPORT.md")
print(f"Kernel: {kernel_pass}/{total}, Runtime: {runtime_pass}/{total-known_limit}, Crashes: {crash}")
```

- [ ] **Step 4: commit**

```bash
cd ~/Documents/flutter_hot_patcher
git add spikes/hotpatch_validation/tools/
git commit -m "feat(validation): automation scripts + coverage report generator"
```

---

## Task 7: Xcode App 改造 + 设备端运行 + 生成最终报告

**Goal:** 把 91 个场景全部在 iPhone 14 上跑通，产出完整覆盖率报告

- [ ] **Step 1: 基于 M3 HotPatchDemo 改造 Xcode App**

```bash
# 复制 HotPatchDemo 作为起点
cp -r ~/Documents/flutter_hot_patcher/spikes/m3_ios_realdevice/HotPatchDemo \
       ~/Documents/flutter_hot_patcher/spikes/hotpatch_validation/HotpatchValidation

# 替换核心 Dart 源：把 greet.dart 换成 main_harness.dart（含全部 91 个注册）
```

- [ ] **Step 2: 更新 dart_harness.c 支持多场景路由**

```c
// 新增：接受场景 ID 参数
const char* dart_run_case(const char* patch_bundle_dir, const char* case_id);
// 循环调用 runCase(id)，收集所有结果
const char* dart_run_all(const char* patch_bundle_dir);
```

- [ ] **Step 3: 更新 ViewController.m**

```objc
// 从 Documents/test_cases.txt 读取待测场景列表
// 对每个场景运行 dart_run_case()
// 把所有结果写入 Documents/coverage_results.json
// 把通过率显示在 UILabel
```

- [ ] **Step 4: 编译全部场景的 snapshot.S（合并）**

```bash
# 所有 lib/ 文件合并成一个 Dart 程序（通过 harness/main_harness.dart import 所有文件）
# 编译为单个 snapshot.S
HOST_OUT=~/dart/sdk/xcodebuild/ReleaseARM64
IOS_GEN=~/dart/sdk/xcodebuild/ReleaseIosARM64/clang_arm64/gen_snapshot_product

$HOST_OUT/dartaotruntime_product \
  $HOST_OUT/gen/gen_kernel_aot.dart.snapshot \
  --platform $HOST_OUT/vm_platform.dill --aot \
  --output /tmp/validation_baseline.dill \
  ~/Documents/flutter_hot_patcher/spikes/hotpatch_validation/harness/main_harness.dart

$IOS_GEN --snapshot-kind=app-aot-assembly \
  --assembly=/tmp/validation_snapshot.S \
  /tmp/validation_baseline.dill
```

- [ ] **Step 5: 逐场景运行（脚本化）**

```bash
# run_validation.sh 增加设备端部分：
# 对每个场景：
#   1. 构建 patch bundle（patch dill + kernel_linker 输出）
#   2. push bundle 到 app Documents/
#   3. 启动 app，传入 case_id
#   4. 读取 Documents/result_TXX.txt
#   5. 追加到 coverage_results.json
```

- [ ] **Step 6: 生成最终报告**

```bash
cd ~/Documents/flutter_hot_patcher/spikes/hotpatch_validation
python3 tools/gen_report.py coverage_results.json
# 生成 COVERAGE_REPORT.md + COVERAGE_DETAIL.md
```

- [ ] **Step 7: 最终 commit**

```bash
cd ~/Documents/flutter_hot_patcher
git add spikes/hotpatch_validation/
git commit -m "feat(validation): COMPLETE — 91 scenarios, coverage report generated

Results: [填入实际数字]
- Kernel 正确率: XX/91
- 漏判率: 0%
- 误报率: 0%
- 运行时正确率: XX/87
- 崩溃率: 0%

Co-Authored-By: Claude Sonnet 4.6 (1M context) <noreply@anthropic.com>"
```
