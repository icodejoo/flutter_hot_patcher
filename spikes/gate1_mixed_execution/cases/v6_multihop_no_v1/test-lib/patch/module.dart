// Copyright / 版权: spike code for flutter_hot_patcher Gate 1 (V6).
//
// The interpreted replacement for the WHOLE stepA->stepB->stepC chain,
// compiled to bytecode via dart2bytecode. All three steps are reimplemented
// here (not just C) -- this is exactly what closure propagation means:
// once C changes, A and B (its static/direct-call ancestors) also "must
// reinterpret", so the patch supplies bytecode for all three, chained via
// ordinary bytecode-level calls (never touching the host's native
// stepA/stepB/stepC at all).
//
// stepA->stepB->stepC 整条链的解释执行替换体，经 dart2bytecode 编译成字节码。
// 三步全部在这里重新实现(不只是 C)——这正是传递闭包的含义：C 一旦改动，
// A 和 B(它靠静态/直调追溯到的调用者)也"必须转解释"，所以补丁把三步都
// 提供成字节码，靠普通的字节码级调用串起来(完全不碰宿主原生的
// stepA/stepB/stepC)。
library;

@pragma('vm:never-inline')
String stepC_new() => 'PATCHED-C';

@pragma('vm:never-inline')
String stepB_new() => 'B-new(${stepC_new()})';

/// Entry point of the loaded module -- this is the Closure whose
/// `entry_point` gets installed into `entryVar` (see host/main.dart).
/// 加载模块的入口——它的 Closure `entry_point` 会被装进 `entryVar`
/// (见 host/main.dart)。
@pragma('dyn-module:entry-point')
String stepA_new() => 'A-new(${stepB_new()})';
