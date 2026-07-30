// Copyright / 版权: spike code for flutter_hot_patcher Gate 1 (V3 exception passthrough).
//
// The interpreted replacement throws instead of returning — tests whether an
// exception raised INSIDE interpreted bytecode correctly unwinds through the
// AOT-compiled caller frames it was redirected into.
//
// 解释执行的替换体抛异常而不是返回值——测试解释执行字节码内部抛出的异常，
// 能否正确穿透被重定向进来的 AOT 编译调用帧完成栈展开。
/// Note: an earlier version declared a custom `PatchException implements
/// Exception` class here. That failed at bytecode LOAD time with
/// "Unable to find function Object. in Library:'dart:core' Class: Object" —
/// allocating a new bytecode-declared class needs the interpreter to resolve
/// the implicit `Object()` super-constructor against the host's canonical
/// dart:core, which this minimal (no dynamic_interface.yaml) build doesn't
/// wire up. Sidestepped by throwing a plain dart:core `StateError` instead —
/// referencing an existing type, not declaring a new one, so no implicit
/// allocation/linkage is needed. That resolution mechanism is out of scope
/// for V3 (which is about propagation, not module-declared type linkage).
///
/// 早期版本在这里声明了一个自定义的 `PatchException implements Exception`
/// 类。在字节码**加载**阶段就失败了，报
/// "Unable to find function Object. in Library:'dart:core' Class: Object"——
/// 分配一个字节码里声明的新类，需要解释器把隐式的 `Object()` 父类构造调用
/// 解析到宿主的 dart:core 里去，这个没配 dynamic_interface.yaml 的最小构建
/// 没打通这条链路。改成抛 dart:core 自带的 `StateError`——引用既有类型，
/// 不声明新类型，不需要隐式分配/链接。这条链接机制不是 V3 要测的东西
/// (V3 测的是穿透，不是模块声明类型的链接)。
library;

/// Interpreted replacement for host f(). Throws instead of returning.
/// 宿主 f() 的解释执行替换体。不返回值，直接抛异常。
@pragma('dyn-module:entry-point')
String fPatched() {
  throw StateError('PATCHED-EXCEPTION');
}
