// Copyright / 版权: spike code for flutter_hot_patcher Gate 1b (Android arm64 repro).
// arm64 port of ../../cases/v5_stress — same two scenarios (high-frequency
// repeated calls after activation; concurrent isolates racing the LIVE
// call-site patch). Only the call-site-rewrite mechanism differs (arm64 bl +
// icache flush; see ../v1_replace_existing_function/host/main.dart).
//
// V5 压测在 Android arm64 上的移植版——同样两个场景(激活后高频重复调用；
// 并发 isolate 争抢正在被改写的调用点)。唯一不同的是调用点改写机制
// (arm64 bl + icache 刷新；见 ../v1_replace_existing_function/host/main.dart)。
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

/// Only the MAIN isolate ever loads/activates the patch. Worker isolates
/// never set [_cachedPatch] (isolates don't share heaps/globals — only
/// compiled code is shared within a group), so this must be null-safe.
///
/// 只有主 isolate 会加载/激活补丁。工作 isolate 永远不会设置 [_cachedPatch]
/// (isolate 之间不共享堆/全局变量——只有编译产物在一个 group 内共享)，
/// 所以这里必须对空值安全。
@pragma('vm:entry-point')
@pragma('vm:never-inline')
String fAlt() {
  final patch = _cachedPatch;
  if (patch == null) {
    return 'PATCHED-BUT-NO-LOCAL-CLOSURE';
  }
  return internal.invokeDynamicModuleClosure(patch) as String;
}

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
    print('GATE1B-V5 INCONCLUSIVE: patch activation failed');
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

  const highFreqIterations = 100000;
  var okCount = 0;
  for (var i = 0; i < highFreqIterations; i++) {
    if (g() == 'g() got: PATCHED') okCount++;
  }
  print('V5a high-frequency: $okCount/$highFreqIterations calls observed PATCHED');
  final v5aOk = okCount == highFreqIterations;

  if (v5aOk && v5bOk) {
    print('GATE1B-V5-ANDROID-ARM64 PASS: stable under high-frequency calls; no crash/corruption racing the live call-site patch across isolates on real arm64 hardware');
    exit(0);
  }
  print('GATE1B-V5-ANDROID-ARM64 FAIL: v5aOk=$v5aOk v5bOk=$v5bOk');
  exit(1);
}

/// arm64 call-site-rewrite mechanism (single call site). See
/// ../v1_replace_existing_function/host/main.dart for the full explanation.
bool _tryActivatePatch(List<String> args) {
  if (args.length < 5) {
    print('  (skip: expected 5 args, see NOTES.md)');
    return false;
  }
  final bytecodePath = args[0];
  final selfPath = args[1];
  final gStatic = int.parse(args[2], radix: 16);
  final fStatic = int.parse(args[3], radix: 16);
  final fAltStatic = int.parse(args[4], radix: 16);

  final bytes = File(bytecodePath).readAsBytesSync();
  final loaded = internal.loadDynamicModuleClosure(bytes: bytes);
  if (loaded == null || loaded is! Function) {
    print('  loadDynamicModuleClosure returned $loaded (expected a Function)');
    return false;
  }
  _cachedPatch = loaded;
  print('  loaded interpreted patch entry point as a closure');

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
  for (var i = 0; i + 4 <= scanWindow; i += 4) {
    final word = ByteData.sublistView(body, i, i + 4).getUint32(0, Endian.little);
    if ((word >> 26) != 0x25) continue;
    var imm26 = word & 0x3FFFFFF;
    if (imm26 & 0x2000000 != 0) imm26 -= 0x4000000;
    final siteStatic = (gRuntime + i) - loadBias;
    final targetStatic = siteStatic + imm26 * 4;
    if (targetStatic == fStatic) {
      callSiteRuntime = gRuntime + i;
      break;
    }
  }
  if (callSiteRuntime == null) {
    print('  did not find `bl f` inside g() body (scanned $scanWindow bytes)');
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
  final newImm26 = (fAltRuntime - callSiteRuntime) ~/ 4;
  final newWord = (0x25 << 26) | (newImm26 & 0x3FFFFFF);
  final wordBytes = ByteData(4)..setUint32(0, newWord, Endian.little);
  final callBytes = Pointer<Uint8>.fromAddress(callSiteRuntime).asTypedList(4);
  for (var i = 0; i < 4; i++) {
    callBytes[i] = wordBytes.getUint8(i);
  }

  rc = mprotect(Pointer<Void>.fromAddress(pageStart), patchLen, protRead | protExec);
  if (rc != 0) {
    print('  mprotect(RX restore) failed: rc=$rc');
  }

  const cacheFlushStubBytes = [
    0x20, 0x7b, 0x0b, 0xd5, // dc cvau, x0
    0x9f, 0x3b, 0x03, 0xd5, // dsb ish
    0x20, 0x75, 0x0b, 0xd5, // ic ivau, x0
    0x9f, 0x3b, 0x03, 0xd5, // dsb ish
    0xdf, 0x3f, 0x03, 0xd5, // isb
    0xc0, 0x03, 0x5f, 0xd6, // ret
  ];
  final mmapFn = DynamicLibrary.process().lookupFunction<
      Pointer<Void> Function(Pointer<Void>, IntPtr, Int32, Int32, Int32, IntPtr),
      Pointer<Void> Function(Pointer<Void>, int, int, int, int, int)>('mmap');
  const protReadWriteExec = 0x1 | 0x2 | 0x4;
  const mapPrivateAnonymous = 0x02 | 0x20;
  final stubPage = mmapFn(Pointer<Void>.fromAddress(0), pageSize,
      protReadWriteExec, mapPrivateAnonymous, -1, 0);
  if (stubPage.address == -1 || stubPage.address == 0) {
    print('  mmap for cache-flush stub failed');
    return false;
  }
  final stubBytes = stubPage.cast<Uint8>().asTypedList(cacheFlushStubBytes.length);
  stubBytes.setAll(0, cacheFlushStubBytes);
  final clearCacheStub = stubPage
      .cast<NativeFunction<Void Function(Pointer<Void>)>>()
      .asFunction<void Function(Pointer<Void>)>();
  clearCacheStub(Pointer<Void>.fromAddress(callSiteRuntime));

  print('  patched call-site to target fAlt(), icache flushed');
  return true;
}
