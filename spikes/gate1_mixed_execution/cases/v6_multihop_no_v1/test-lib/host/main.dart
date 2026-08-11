// Copyright / 版权: spike code for flutter_hot_patcher Gate 1 (V6, "is V1 load-bearing?").
//
// Question: SPEC.md §5's "关键更正" claims redirection NEVER needs to touch
// machine code -- propagation (marking every static/direct-call ancestor of a
// changed function as "must reinterpret" too) should let redirection happen
// ENTIRELY via a single data-field write at the nearest virtual/closure
// dispatch boundary. GATE1_REPORT.md §5 phrases it differently ("any static
// direct call site needs V1's mechanism"). This case settles which reading is
// right, empirically, with ZERO code-page writes anywhere in the activation
// path -- no mprotect, no instruction-byte scanning, no V1 at all.
//
// 问题：SPEC.md §5 的"关键更正"断言重定向从不需要碰机器码——传递闭包(把一个被改
// 函数的所有仅靠静态/直调追溯到它的调用者也标记"转解释")应该能让重定向完全靠
// 在最近的虚调用/闭包边界处改一次数据字段来完成。GATE1_REPORT.md §5 的表述不太
// 一样("任何静态直调点都需要V1的机制")。这个用例用实测来判定哪种说法对——整个
// 激活路径里没有任何代码页写入，不做 mprotect，不扫描指令字节，完全不用 V1。
library;

import 'dart:io';
import 'dart:_internal' as internal;

/// Multi-hop static/direct-call chain. None of these three functions are
/// EVER touched (no instruction bytes rewritten) -- if the patch takes
/// effect, it's because the WHOLE chain got reimplemented in the loaded
/// bytecode module (patch/module.dart), not because these bytes changed.
///
/// 多跳静态/直调链。这三个函数的指令字节自始至终不会被碰——如果补丁生效，
/// 是因为整条链在加载的字节码模块(patch/module.dart)里被重新实现了一遍，
/// 不是因为这几个函数自己的字节被改了。
@pragma('vm:never-inline')
String stepC() => 'ORIGINAL-C';

@pragma('vm:never-inline')
String stepB() => 'B(${stepC()})';

@pragma('vm:never-inline')
String stepA() => 'A(${stepB()})';

/// Second candidate for [entryVar], distinct from [stepA]. Exists ONLY so
/// entryVar's value is genuinely runtime-decided -- V2's NOTES.md already
/// documented this exact trap: without a second candidate, AOT closure
/// specialization proves entryVar can only ever hold stepA and devirtualizes
/// `callViaClosure` into a plain direct call, which defeats the entire point
/// of this test (it would silently degenerate into testing V1's call form,
/// not V2's). Confirmed by this test's own first run: BEFORE this fix,
/// AFTER == BEFORE even though the redirect call succeeded with no error --
/// the redirect took effect on a Closure object nothing actually called
/// through anymore.
///
/// [entryVar] 第二个候选值，跟 [stepA] 不同。存在的唯一目的是让 entryVar 的
/// 取值真正由运行时决定——V2 的 NOTES.md 早就记录过这个坑：没有第二个候选值，
/// AOT 闭包特化会证明 entryVar 只能是 stepA，把 `callViaClosure` 去虚化成
/// 普通直调，这样整个测试就白做了(会悄悄退化成测 V1 的调用形态，不是 V2 的)。
/// 这次测试自己的第一轮跑就实锤复现了这个坑：修之前，重定向调用本身没报错，
/// 但 AFTER 跟 BEFORE 一模一样——重定向写对了一个 Closure 对象的字段，
/// 但已经没有任何调用点还经过它了。
@pragma('vm:never-inline')
String stepAAlt() => 'ALT-UNUSED';

/// The ONLY redirect point in this whole test: a closure field, exactly like
/// V2's `closureVar`. Its own `entry_point` field is the single thing that
/// gets rewritten -- a heap-data write, same mechanism V2 already validated,
/// never a code-page write.
///
/// 整个测试里唯一的重定向点：一个闭包字段，跟 V2 的 `closureVar`一样。
/// 会被改写的只有它自己的 `entry_point` 字段——堆上数据写，跟 V2 已验证过的
/// 机制一样，绝不是代码页写。
late final String Function() entryVar;

@pragma('vm:never-inline')
String callViaClosure() => 'viaClosure: ${entryVar()}';

/// Cached interpreted-chain entry, loaded once via the VM-level
/// `loadDynamicModuleClosure` extension (same mechanism V1 already validated
/// for reaching the interpreter -- what's NEW here is how we reach IT: via a
/// data redirect, not a physically-rewritten call site).
///
/// 缓存的解释执行链入口，用 VM 层 `loadDynamicModuleClosure` 扩展加载一次
/// (跟 V1 已验证过的够到解释器的机制一样——这里新的地方是"怎么够到它"：
/// 靠数据重定向，不是物理改写调用点)。
Function? _cachedPatch;

/// AOT trampoline that invokes the cached interpreted chain. Kept alive via
/// `vm:entry-point` since no Dart source calls it directly -- the ONLY path
/// to it is through `entryVar`'s redirected entry_point field.
///
/// 调用缓存的解释执行链的 AOT 蹦床函数。用 `vm:entry-point` 保活，因为源码里
/// 没有任何调用点直接调它——唯一到达路径是经 `entryVar` 被重定向后的
/// entry_point 字段。
@pragma('vm:entry-point')
@pragma('vm:never-inline')
String patchTrampoline() =>
    internal.invokeDynamicModuleClosure(_cachedPatch!) as String;

void main(List<String> args) {
  // Runtime-decided (depends on argv content, which the compiler cannot
  // resolve at compile time) -- see stepAAlt's doc comment for why this
  // matters. In every normal invocation this evaluates to stepA; the point
  // is that the COMPILER can't prove that.
  entryVar = args.contains('--alt') ? stepAAlt : stepA;
  print('BEFORE: ${callViaClosure()}'); // expect: viaClosure: A(B(ORIGINAL-C))

  final activated = _tryActivatePatch(args);
  final after = callViaClosure();
  print('AFTER: $after');

  if (!activated) {
    print('V6 INCONCLUSIVE: patch activation not wired (expected args[0]=bytecode path)');
    exit(3);
  }
  if (after.contains('PATCHED-C')) {
    print('V6 PASS: multi-hop static-call chain (stepA->stepB->stepC) reached '
        'the patched C via ONLY a closure entry_point redirect (V2 mechanism) '
        '-- zero code-page writes, V1 never invoked');
    exit(0);
  }
  print('V6 FAIL: chain still reaches ORIGINAL-C after activation');
  exit(1);
}

/// V6 activation -- deliberately does NOT touch any existing call site's
/// machine code. Two steps, both data-only:
///
/// (a) Load the patch bytecode via `loadDynamicModuleClosure` (same as V1;
///     loading bytecode into the VM is not a code-page write, it's ordinary
///     module loading, always available).
/// (b) Rewrite `entryVar`'s OWN Closure `entry_point` field to point at
///     `patchTrampoline` (the exact mechanism V2 already validated for
///     closure calls) -- a single heap-data write, nothing else.
///
/// stepA/stepB/stepC's compiled bytes, and callViaClosure's compiled bytes,
/// are NEVER read or written by this function. If this test PASSes, it
/// proves the multi-hop chain never needed V1's mechanism at all.
///
/// V6 激活——刻意不碰任何既有调用点的机器码。两步，都是纯数据操作：
///
/// (a) 用 `loadDynamicModuleClosure` 加载补丁字节码(跟 V1 一样；把字节码加载
///     进 VM 不是代码页写，是普通的模块加载，随时可用)。
/// (b) 改写 `entryVar` 自己的 Closure `entry_point` 字段，指向 `patchTrampoline`
///     (V2 已验证过的闭包调用重定向机制)——一次堆数据写，仅此而已。
///
/// stepA/stepB/stepC 的编译字节、callViaClosure 的编译字节，这个函数从头到尾
/// 不读也不写。如果这个测试 PASS，就证明多跳链条从来不需要 V1 的机制。
bool _tryActivatePatch(List<String> args) {
  if (args.isEmpty) {
    print('  (skip: expected args[0]=bytecode path)');
    return false;
  }
  final bytes = File(args[0]).readAsBytesSync();
  final loaded = internal.loadDynamicModuleClosure(bytes: bytes);
  if (loaded == null || loaded is! Function) {
    print('  loadDynamicModuleClosure returned $loaded (expected a Function)');
    return false;
  }
  _cachedPatch = loaded;
  print('  loaded interpreted patch chain as a closure');

  internal.redirectClosureEntryPoint(entryVar, patchTrampoline);
  print('  redirected entryVar entry_point to patchTrampoline (data write only, '
      'no mprotect, no instruction bytes touched)');
  return true;
}
