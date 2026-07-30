// Copyright / 版权: spike code for flutter_hot_patcher Gate 1 (V2 call-forms matrix).
//
// V1 proved static direct calls (g()->f()) are redirectable via runtime
// call-site machine-code patching. V2 asks: what about the other two call
// shapes NOTES.md identifies — virtual/interface dispatch and closure calls?
// Each may compile to a DIFFERENT instruction shape than V1's plain
// `call rel32`, so each needs its own empirical disassembly + redirect
// experiment before we can claim anything about it.
//
// 核心问题：V1 证明了静态直调可以靠运行时改写调用点机器码来重定向。V2 要测
// NOTES.md 列的另外两种调用形态——虚调用/接口调用、闭包调用。每一种编译出来的
// 指令形态都可能和 V1 的 `call rel32` 不一样，得先反汇编看实际长什么样，
// 才能谈重定向。
library;

import 'dart:io';
import 'dart:_internal' as internal;

/// Interface used for the virtual/interface-call test. Two implementations
/// exist so the AOT compiler can't trivially devirtualize the call at
/// `callViaInterface` into a plain direct call (which would just degenerate
/// into V1's case).
///
/// 虚调用/接口调用测试用的接口。故意提供两个实现，防止 AOT 编译器把
/// `callViaInterface` 里的调用去虚化成普通直调(那样就退化成 V1 的情形了)。
abstract class Op {
  String run();
}

@pragma('vm:never-inline')
class OpOriginal implements Op {
  @override
  String run() => 'ORIGINAL';
}

@pragma('vm:never-inline')
class OpOther implements Op {
  @override
  String run() => 'OTHER-IMPL';
}

/// Replacement implementation. Only referenced by the redirect call in
/// [main] (never actually assigned to [theOp]) — its instance exists solely
/// so we can tear off its `.run` method, get the Closure wrapping it, and
/// read the Closure's `.function()` entry point to install into the
/// dispatch table slot for [theOp]'s class id.
///
/// 替换实现。只在 [main] 的重定向调用里被引用(从不真正赋给 [theOp])——
/// 存在的唯一目的是撕下它的 `.run` 方法拿到包着它的 Closure，读出
/// Closure 的 `.function()` entry point，装进 [theOp] 的 class id 对应的
/// dispatch table 槽位。
@pragma('vm:never-inline')
class OpPatched implements Op {
  @override
  String run() => 'PATCHED-VIA-DISPATCH-TABLE';
}

/// Which concrete Op backs the interface call — decided at runtime (via argv)
/// so the compiler cannot resolve `theOp` to a single class via CHA.
///
/// 接口调用背后实际用哪个具体类——运行时决定(取决于 argv)，编译器没法靠
/// class-hierarchy-analysis 把 `theOp` 静态解析成单一类。
late final Op theOp;

/// Existing caller reaching Op.run() via interface dispatch.
/// 既有调用方，经接口调用抵达 Op.run()。
@pragma('vm:never-inline')
String callViaInterface() => 'viaInterface: ${theOp.run()}';

/// Existing plain top-level function targeted by a closure call site.
/// 被闭包调用点指向的既有普通顶层函数。
@pragma('vm:never-inline')
String closureTarget() => 'ORIGINAL';

/// Second possible closure target, distinct from [closureTarget]. Only
/// exists so [closureVar]'s value is genuinely runtime-decided — without
/// this, AOT closure specialization proved closureVar could only ever hold
/// closureTarget and devirtualized callViaClosure into a plain direct call
/// (confirmed by disassembly; see NOTES.md).
///
/// 第二个可能的闭包目标，和 [closureTarget] 不同。存在的唯一目的是让
/// [closureVar] 的取值真正由运行时决定——没有它，AOT 闭包特化会证明
/// closureVar 只能是 closureTarget，把 callViaClosure 去虚化成普通直调
/// (反汇编已证实这一点，见 NOTES.md)。
@pragma('vm:never-inline')
String closureTargetAlt() => 'ALT';

/// Replacement closure target, referenced only via [main]'s redirect call —
/// its entry point gets read off and written into [closureVar]'s own Closure
/// object, never actually assigned to [closureVar] itself.
///
/// 替换闭包目标，只在 [main] 的重定向调用里被引用——它的 entry point 被读出来、
/// 写进 [closureVar] 自己的 Closure 对象里，从不真正赋值给 [closureVar]。
@pragma('vm:never-inline')
String closureTargetPatched() => 'PATCHED-VIA-CLOSURE-ENTRY-POINT';

/// The closure variable itself — a mutable top-level field holding a
/// reference to [closureTarget] or [closureTargetAlt], decided at runtime
/// (via argv) so the compiler can't resolve it to a single target and
/// devirtualize the call. `callViaClosure` calls through this variable,
/// which is exactly what "closure call" means here: dispatch via a Closure
/// object's own entry_point, not a fixed compiled-in address.
///
/// 闭包变量本身——一个可变顶层字段，持有指向 [closureTarget] 或
/// [closureTargetAlt] 的引用，运行时决定(取决于 argv)，编译器没法把它
/// 解析成单一目标去虚化。`callViaClosure` 经这个变量调用，这就是这里
/// "闭包调用"的含义：经 Closure 对象自己的 entry_point 调度，不是编译期
/// 固定的地址。
late final String Function() closureVar;

/// Existing caller reaching closureTarget() via a closure call.
/// 既有调用方，经闭包调用抵达 closureTarget()。
@pragma('vm:never-inline')
String callViaClosure() => 'viaClosure: ${closureVar()}';

void main(List<String> args) {
  theOp = args.contains('--other') ? OpOther() : OpOriginal();
  closureVar = args.contains('--alt') ? closureTargetAlt : closureTarget;

  print('BEFORE interface: ${callViaInterface()}');
  print('BEFORE closure:   ${callViaClosure()}');

  // Redirect ALL calls dispatching on theOp's class id to OpPatched.run —
  // a single dispatch-table-entry write, not a per-call-site patch.
  // 把所有按 theOp 的 class id 分发的调用重定向到 OpPatched.run——
  // 只改一个 dispatch table 项，不是逐个调用点打补丁。
  internal.redirectDispatchTableEntry(theOp, OpPatched().run);

  // Redirect calls through THIS closure instance (closureVar) to
  // closureTargetPatched — a single Closure-object field write.
  // 把经这一个闭包实例(closureVar)的调用重定向到 closureTargetPatched——
  // 只改这一个 Closure 对象自己的字段。
  internal.redirectClosureEntryPoint(closureVar, closureTargetPatched);

  print('AFTER interface:  ${callViaInterface()}');
  print('AFTER closure:    ${callViaClosure()}');

  final interfaceOk = callViaInterface().contains('PATCHED-VIA-DISPATCH-TABLE');
  final closureOk = callViaClosure().contains('PATCHED-VIA-CLOSURE-ENTRY-POINT');
  if (interfaceOk && closureOk) {
    print('V2 PASS: both dispatch-table and closure entry_point redirects observed');
    exit(0);
  }
  print('V2 FAIL: interfaceOk=$interfaceOk closureOk=$closureOk');
  exit(1);
}
