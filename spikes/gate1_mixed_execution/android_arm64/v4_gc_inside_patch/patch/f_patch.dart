// Copyright / 版权: spike code for flutter_hot_patcher Gate 1 (V4 GC inside patch).
//
// The interpreted replacement allocates enough garbage to reliably trigger
// real GC (scavenge, likely promotion to old-gen) WHILE running — tests
// whether a GC happening mid-interpreted-execution, with the caller an AOT
// frame reached via a runtime-patched call site, corrupts anything (caller's
// live roots, the interpreter's own temporaries, or the eventual return
// value).
//
// Two earlier versions hit the SAME class of failure via different paths:
// 1. `VMInternalsForTesting.collectAllGarbage()` (dart:_internal) — failed
//    at bytecode LOAD time: "Unable to find class VMInternalsForTesting in
//    Library:'dart:_internal'" — EVEN after making the host also reference
//    the class (rules out plain tree-shaking).
// 2. `List<int>.filled(...)` (dart:core) — ALSO failed at load time:
//    "Unable to find function _List@....filled in Library:'dart:core'
//    Class: _List" — so it's not specific to dart:_internal either; some
//    dart:core internals (private VM-backed factory constructors) aren't
//    resolvable by the bytecode reader by default.
// What DOES reliably resolve (proven by V1/V2/V3 all using it without
// issue): string interpolation, i.e. `_StringBase._interpolate`. So this
// version allocates garbage purely via string interpolation — short-lived
// String objects, real generational GC pressure, zero cross-library calls
// beyond the one path already known to link correctly.
//
// 两个更早的版本都撞上了同一类失败，走的是不同路径：
// 1. `VMInternalsForTesting.collectAllGarbage()`(dart:_internal)——字节码
//    **加载**阶段失败："Unable to find class VMInternalsForTesting in
//    Library:'dart:_internal'"——即使让宿主也引用这个类(排除纯树摇问题)
//    依然失败。
// 2. `List<int>.filled(...)`(dart:core)——**同样**加载阶段失败：
//    "Unable to find function _List@....filled in Library:'dart:core'
//    Class: _List"——所以不是 dart:_internal 特有的问题；dart:core 里一些
//    私有的、VM 内建实现的工厂构造函数，字节码读取器默认也解析不了。
// A THIRD attempt (`garbage.isNotEmpty`, a getter call on the interpolated
// String) hit the exact same failure class: "Unable to find function
// get:isNotEmpty in Library:'dart:core' Class: String" — even a totally
// ordinary getter, never called anywhere in the host, isn't resolvable.
// That narrows the real mechanism down: it's not "dart:core vs
// dart:_internal", it's **closed-world AOT tree-shaking** — the bytecode
// reader can only cross-link against whatever the host's own compiled
// program already retains, and nothing calls `.isNotEmpty` (or `.filled`,
// or references `VMInternalsForTesting`) anywhere in host/main.dart, so none
// of it survives tree-shaking. String interpolation survives ONLY because
// V1/V2/V3's host code already uses it themselves.
//
// So: don't call ANY method/getter inside the patch beyond what the host
// itself already exercises. Pure interpolation + assignment, nothing else.
//
// 第三次尝试(`garbage.isNotEmpty`，对插值出来的 String 调一个 getter)撞上了
// 一模一样的失败：
// "Unable to find function get:isNotEmpty in Library:'dart:core' Class: String"
// ——哪怕是再普通不过的 getter，只要宿主里没人调用过，就解析不了。这就把真正
// 的机制锁定了：不是"dart:core 还是 dart:_internal"的区别，是**闭世界 AOT 树摇**
// ——字节码读取器只能跨链接到宿主编译产物**自己已经保留下来**的东西，
// host/main.dart 里没有任何地方调用 `.isNotEmpty`(或 `.filled`，或引用
// `VMInternalsForTesting`)，树摇当然就把它们全删了。字符串插值之所以能用，
// 纯粹是因为 V1/V2/V3 的宿主代码自己就在用它。
//
// 所以：补丁里除了宿主自己已经在用的东西，不调用任何方法/getter。
// 只用插值 + 赋值，别的都不碰。
library;

/// Interpreted replacement for host f(). Allocates a large number of
/// short-lived interpolated strings — enough to reliably trigger real
/// scavenger GC (and likely promotion) mid-execution under default heap
/// growth heuristics — using ONLY string interpolation and assignment
/// (proven to cross-link correctly; see notes above for what doesn't).
///
/// 宿主 f() 的解释执行替换体。分配大量短生命周期的插值字符串——足够在
/// 默认堆增长策略下可靠地在执行期间触发真实的 scavenger GC(大概率还有晋升)
/// ——只用字符串插值 + 赋值(证明能正确跨链接；不能用的东西见上面注释)。
@pragma('dyn-module:entry-point')
String fPatched() {
  var last = '';
  for (var i = 0; i < 300000; i++) {
    last = 'garbage-$i'; // new String each iteration; previous value becomes garbage
  }
  return 'PATCHED-AFTER-ALLOC-last=$last';
}
