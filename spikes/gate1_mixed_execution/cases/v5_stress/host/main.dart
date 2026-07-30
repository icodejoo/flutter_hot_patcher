// Copyright / 版权: spike code for flutter_hot_patcher Gate 1 (V5 stress).
//
// V1-V4 proved the mechanism works for ONE activation, ONE call, checked
// once. V5 asks two stress questions:
//
//   (a) High-frequency: after activation, does EVERY subsequent call to
//       g() consistently observe the patched behavior, across tens of
//       thousands of calls, with no flakiness or corruption?
//
//   (b) Concurrency: in AOT mode, compiled code is shared across isolates
//       in the same isolate group (only the heap is per-isolate). If OTHER
//       isolates are concurrently EXECUTING g()'s call instruction while
//       the main isolate's mprotect+byte-write patches it, is that safe?
//       This is a genuine data race on live instruction bytes — the kind
//       real hot-patching frameworks solve with quiescence windows or
//       int3-based breakpoint patching, NOT naive concurrent byte writes.
//       V5b tests what our naive approach actually does under that race,
//       honestly — including "it crashes" as a valid, important finding.
//
// V1-V4 证明了机制在"激活一次、调用一次、检查一次"的场景下成立。V5 问两个
// 压测问题：
//
//   (a) 高频：激活之后，接下来几万次调用 g()，是不是每一次都稳定观测到补丁
//       行为，没有偶发的不一致或数据损坏？
//
//   (b) 并发：AOT 模式下，编译产物在同一个 isolate group 内跨 isolate 共享
//       (只有堆是各 isolate 独立的)。如果主 isolate 在做 mprotect+改字节
//       的时候，其他 isolate 正在并发执行 g() 的调用指令，这样安全吗？
//       这是对"活着的指令字节"的真实数据竞争——真正的热补丁框架靠静默窗口
//       或 int3 断点式改写来解决这个问题，不是像我们这样直接并发改字节。
//       V5b 诚实地测一下我们这套朴素做法在这种竞争下到底会怎样——
//       "会崩"本身也是一个重要、有效的结论。
library;

import 'dart:async';
import 'dart:ffi';
import 'dart:io';
import 'dart:isolate';
import 'dart:typed_data';
import 'dart:_internal' as internal;

@pragma('vm:never-inline')
String f() => 'ORIGINAL';

@pragma('vm:never-inline')
String g() => 'g() got: ${f()}';

Function? _cachedPatch;

/// Only the MAIN isolate ever loads/activates the patch (loading the SAME
/// module bytes from multiple isolates risks a separate, unverified
/// "duplicate library" failure — a different question, out of scope here;
/// see NOTES.md). Worker isolates never set [_cachedPatch], so this must be
/// null-safe: it reports a distinct marker instead of crashing, which is
/// itself the V5b signal — "call site IS shared (workers reach fAlt() the
/// instant main patches it), closure STATE is NOT (workers have no local
/// patch loaded)".
///
/// 只有主 isolate 会加载/激活补丁(让多个 isolate 各自加载同一份模块字节，
/// 有撞上另一个未验证的"重复加载"限制的风险——这是另一个问题，这里不测，
/// 见 NOTES.md)。工作 isolate 永远不会设置 [_cachedPatch]，所以这里必须
/// 对空值安全——报一个能区分的标记而不是崩溃，这本身就是 V5b 要的信号：
/// "调用点是共享的(主 isolate 一改，worker 立刻就能落到 fAlt())，
/// 闭包状态不是(worker 没有加载本地补丁)"。
@pragma('vm:entry-point')
@pragma('vm:never-inline')
String fAlt() {
  final patch = _cachedPatch;
  if (patch == null) {
    return 'PATCHED-BUT-NO-LOCAL-CLOSURE';
  }
  return internal.invokeDynamicModuleClosure(patch) as String;
}

/// V5b worker isolate: calls g() in a tight loop [iterations] times, tallies
/// how many calls observed ORIGINAL vs the "call site shared, no local
/// closure" marker vs anything unexpected (a crash/garbage result while the
/// caller frame's call target is mid-write would land here), while the MAIN
/// isolate concurrently mprotect+byte-writes the SHARED call site. Reports
/// back through [sendPort].
///
/// V5b 工作 isolate：在紧循环里调 g() [iterations] 次，统计观测到 ORIGINAL /
/// "调用点已共享但没有本地闭包"标记 / 其他意外结果(调用目标字节被改到一半时
/// 崩溃/读到垃圾数据会落在这一档)各多少次，同时主 isolate 正在并发地对
/// **共享的**调用点做 mprotect+改字节。通过 [sendPort] 汇报。
void _worker(List<Object> args) {
  final sendPort = args[0] as SendPort;
  final iterations = args[1] as int;
  var original = 0, sharedNoClosure = 0, unexpected = 0;
  for (var i = 0; i < iterations; i++) {
    final r = g();
    if (r == 'g() got: ORIGINAL') {
      original++;
    } else if (r == 'g() got: PATCHED-BUT-NO-LOCAL-CLOSURE') {
      sharedNoClosure++;
    } else {
      unexpected++;
    }
  }
  sendPort.send([original, sharedNoClosure, unexpected]);
}

void main(List<String> args) async {
  print('BEFORE: ${g()}');

  // ── V5b: concurrent isolates racing the LIVE call-site patch ──────────
  // V5b：并发 isolate 争抢正在被改写的调用点
  //
  // Spawn workers BEFORE activation so they're actively mid-loop, calling
  // g() as fast as possible against the UNPATCHED call site, while the main
  // isolate's mprotect+byte-write races against them. This is the real
  // stress: are worker isolates concurrently fetching/executing this exact
  // instruction while main is rewriting 4 of its 5 bytes? A torn read could
  // crash, jump somewhere invalid, or return garbage — any of those show up
  // as "unexpected" below.
  //
  // 先起 worker(此时还没打补丁)，让它们立刻开始拼命调 g()，跟主 isolate
  // 的 mprotect+改字节形成真正的竞争。这才是压测的核心：主 isolate 正在改写
  // 这条指令 5 个字节里的 4 个的同时，worker isolate 会不会恰好在并发取指/
  // 执行这条指令？读到"改到一半"的字节可能崩溃、跳到乱七八糟的地方、或者
  // 返回垃圾——这些都会落进下面的"unexpected"里。
  const numIsolates = 8;
  const perIsolateIterations = 20000000;
  final receivePort = ReceivePort();
  final results = <List<int>>[];
  final resultsDone = Completer<void>();
  var received = 0;
  receivePort.listen((message) {
    results.add((message as List).cast<int>());
    received++;
    if (received == numIsolates) {
      resultsDone.complete();
      receivePort.close();
    }
  });

  for (var i = 0; i < numIsolates; i++) {
    await Isolate.spawn(_worker, [receivePort.sendPort, perIsolateIterations]);
  }

  final activated = _tryActivatePatch(args);
  if (!activated) {
    print('V5 INCONCLUSIVE: patch activation failed');
    exit(3);
  }

  await resultsDone.future;

  var totalOriginal = 0, totalSharedNoClosure = 0, totalUnexpected = 0;
  for (final r in results) {
    totalOriginal += r[0];
    totalSharedNoClosure += r[1];
    totalUnexpected += r[2];
  }
  final totalCalls = numIsolates * perIsolateIterations;
  print('V5b concurrent isolates: $totalOriginal ORIGINAL (before the race caught up), '
      '$totalSharedNoClosure saw the shared call site flip (no local closure), '
      '$totalUnexpected unexpected/corrupted (out of $totalCalls total)');
  final v5bOk = totalUnexpected == 0 && (totalOriginal + totalSharedNoClosure) == totalCalls;

  // ── V5a: high-frequency repeated calls after activation ──────────────
  // V5a：激活之后的高频重复调用
  const highFreqIterations = 100000;
  var okCount = 0;
  for (var i = 0; i < highFreqIterations; i++) {
    if (g() == 'g() got: PATCHED') okCount++;
  }
  print('V5a high-frequency: $okCount/$highFreqIterations calls observed PATCHED');
  final v5aOk = okCount == highFreqIterations;

  if (v5aOk && v5bOk) {
    print('V5 PASS: stable under high-frequency calls; no crash/corruption racing the live call-site patch across isolates');
    exit(0);
  }
  print('V5 FAIL: v5aOk=$v5aOk v5bOk=$v5bOk');
  exit(1);
}

/// Same mechanism as V1's _tryActivatePatch.
/// 和 V1 的 _tryActivatePatch 同一套机制。
bool _tryActivatePatch(List<String> args) {
  if (args.length < 2) {
    print('  (skip: expected args[0]=bytecode path, args[1]=own main.snapshot path)');
    return false;
  }
  final bytecodePath = args[0];
  final selfPath = args[1];

  final bytes = File(bytecodePath).readAsBytesSync();
  final loaded = internal.loadDynamicModuleClosure(bytes: bytes);
  if (loaded == null || loaded is! Function) {
    print('  loadDynamicModuleClosure returned $loaded (expected a Function)');
    return false;
  }
  _cachedPatch = loaded;
  print('  loaded interpreted patch entry point as a closure');

  final nmResult = Process.runSync('nm', [selfPath]);
  if (nmResult.exitCode != 0) {
    print('  nm failed: ${nmResult.stderr}');
    return false;
  }
  final symRe = RegExp(r'^([0-9a-fA-F]+)\s+t\s+(\S+)$', multiLine: true);
  final addrs = <String, int>{};
  for (final m in symRe.allMatches(nmResult.stdout as String)) {
    final name = m.group(2)!;
    if (name == 'g' || name == 'f' || name == 'fAlt') {
      addrs.putIfAbsent(name, () => int.parse(m.group(1)!, radix: 16));
    }
  }
  for (final required in ['g', 'f', 'fAlt']) {
    if (!addrs.containsKey(required)) {
      print('  nm did not resolve $required: $addrs');
      return false;
    }
  }
  final gStatic = addrs['g']!;
  final fStatic = addrs['f']!;
  final fAltStatic = addrs['fAlt']!;

  final maps = File('/proc/self/maps').readAsStringSync();
  final mapRe = RegExp(
      r'^([0-9a-fA-F]+)-[0-9a-fA-F]+\s+r-xp\s+([0-9a-fA-F]+)\s+\S+\s+\d+\s+(.*)$',
      multiLine: true);
  int? loadBias;
  for (final m in mapRe.allMatches(maps)) {
    final path = m.group(3)!.trim();
    if (path.endsWith(selfPath.split('/').last)) {
      final segStart = int.parse(m.group(1)!, radix: 16);
      final segOffset = int.parse(m.group(2)!, radix: 16);
      loadBias = segStart - segOffset;
      break;
    }
  }
  if (loadBias == null) {
    print('  could not find own executable mapping in /proc/self/maps');
    return false;
  }

  final gRuntime = loadBias + gStatic;
  const scanWindow = 256;
  final body = Pointer<Uint8>.fromAddress(gRuntime).asTypedList(scanWindow);
  int? callSiteRuntime;
  for (var i = 0; i + 5 <= scanWindow; i++) {
    if (body[i] != 0xE8) continue;
    final rel = ByteData.sublistView(body, i + 1, i + 5).getInt32(0, Endian.little);
    final siteStatic = (gRuntime + i) - loadBias;
    final targetStatic = siteStatic + 5 + rel;
    if (targetStatic == fStatic) {
      callSiteRuntime = gRuntime + i;
      break;
    }
  }
  if (callSiteRuntime == null) {
    print('  did not find `call f` inside g() body (scanned $scanWindow bytes)');
    return false;
  }

  const pageSize = 4096;
  final pageStart = callSiteRuntime & ~(pageSize - 1);
  const patchLen = 2 * pageSize;
  final mprotect = DynamicLibrary.process()
      .lookupFunction<Int32 Function(Pointer<Void>, IntPtr, Int32), int Function(Pointer<Void>, int, int)>(
          'mprotect');
  const protRead = 0x1, protWrite = 0x2, protExec = 0x4;
  var rc = mprotect(Pointer<Void>.fromAddress(pageStart), patchLen, protRead | protWrite | protExec);
  if (rc != 0) {
    print('  mprotect(RWX) failed: rc=$rc');
    return false;
  }

  final fAltRuntime = loadBias + fAltStatic;
  final newRel = fAltRuntime - (callSiteRuntime + 5);
  final callBytes = Pointer<Uint8>.fromAddress(callSiteRuntime).asTypedList(5);
  final relBytes = ByteData(4)..setInt32(0, newRel, Endian.little);
  for (var i = 0; i < 4; i++) {
    callBytes[1 + i] = relBytes.getUint8(i);
  }

  rc = mprotect(Pointer<Void>.fromAddress(pageStart), patchLen, protRead | protExec);
  if (rc != 0) {
    print('  mprotect(RX restore) failed: rc=$rc (patch already applied)');
  }
  print('  patched call-site to target fAlt()');
  return true;
}
