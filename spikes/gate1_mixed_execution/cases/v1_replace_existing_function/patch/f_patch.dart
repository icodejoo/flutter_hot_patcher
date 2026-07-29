// Copyright / 版权: spike code for flutter_hot_patcher Gate 1 (V1 replacement).
//
// The replacement body f', compiled to bytecode via dart2bytecode and executed
// by the interpreter. Behaviorally different from the baseline f() so that a
// successful redirect is OBSERVABLE.
//
// 替换体 f'，经 dart2bytecode 编译为字节码、由解释器执行。行为与基线 f() 不同，
// 使"重定向成功"可被观测。
library;

/// Interpreted replacement for host f(). Returns a distinct value.
/// 宿主 f() 的解释执行替换体，返回不同的值。
///
/// Returns "PATCHED"; if g() observes this, the existing call site was redirected.
/// 返回 "PATCHED"；若 g() 观测到它，则既有调用点已被重定向。
@pragma('dyn-module:entry-point')
String fPatched() => 'PATCHED';
