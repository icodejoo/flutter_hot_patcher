// Copyright / 版权: spike code for flutter_hot_patcher Gate 1b (Android arm64 repro).
// arm64 port of ../../cases/v3_exception_passthrough — same two scenarios
// (local catch, propagate past a patched frame), same patch body (throws
// StateError). The only thing that changes is the arm64 call-site-rewrite
// mechanism (see v1_replace_existing_function/host/main.dart for why), now
// generalized to patch TWO independent call sites instead of one.
//
// V3 异常穿透在 Android arm64 上的移植版——同样两个场景(本地 catch、
// 穿透被打补丁的帧)，同样的补丁体(抛 StateError)。唯一变化的是 arm64
// 调用点改写机制(为什么见 v1_replace_existing_function/host/main.dart)，
// 这次泛化成同时改写两个独立的调用点，而不是一个。
library;

import 'dart:ffi';
import 'dart:io';
import 'dart:typed_data';
import 'dart:_internal' as internal;

@pragma('vm:never-inline')
String f() => 'ORIGINAL';

@pragma('vm:never-inline')
String gCatches() {
  try {
    return 'g() got: ${f()}';
  } catch (e) {
    return 'g() caught: $e';
  }
}

@pragma('vm:never-inline')
String gPropagates() => 'g() got: ${f()}';

Function? _cachedPatch;

@pragma('vm:entry-point')
@pragma('vm:never-inline')
String fAlt() => internal.invokeDynamicModuleClosure(_cachedPatch!) as String;

void main(List<String> args) {
  print('BEFORE gCatches:    ${gCatches()}');
  print('BEFORE gPropagates: ${gPropagates()}');

  final activated = _tryActivatePatch(args);
  if (!activated) {
    print('GATE1B-V3 INCONCLUSIVE: patch activation failed');
    exit(3);
  }

  final caught = gCatches();
  print('AFTER gCatches:     $caught');
  final scenarioAOk = caught == 'g() caught: Bad state: PATCHED-EXCEPTION';

  var scenarioBOk = false;
  try {
    final result = gPropagates();
    print('AFTER gPropagates:  $result (expected: unreachable)');
  } catch (e) {
    print('AFTER gPropagates:  propagated to main, caught: $e');
    scenarioBOk = e.toString() == 'Bad state: PATCHED-EXCEPTION';
  }

  if (scenarioAOk && scenarioBOk) {
    print('GATE1B-V3-ANDROID-ARM64 PASS: exception from interpreted code both caught-at-site and propagated-past-frame correctly on real arm64 hardware');
    exit(0);
  }
  print('GATE1B-V3-ANDROID-ARM64 FAIL: scenarioAOk=$scenarioAOk scenarioBOk=$scenarioBOk');
  exit(1);
}

/// arm64 call-site-rewrite mechanism, generalized to patch BOTH gCatches's
/// and gPropagates's independent `bl f` sites. See
/// ../v1_replace_existing_function/host/main.dart for the full explanation
/// of each arm64-specific step (bl encoding, icache flush via assembled stub,
/// build-time address resolution since the device has no nm).
///
/// arm64 调用点改写机制，泛化成同时改写 gCatches 和 gPropagates 两个独立的
/// `bl f` 调用点。每一步 arm64 专属细节(bl 编码、通过汇编 stub 刷新 icache、
/// 因设备无 nm 而在构建期算地址)的完整解释见
/// ../v1_replace_existing_function/host/main.dart。
///
/// args: [0]=bytecode path, [1]=own snapshot path, [2]=f static addr (hex),
/// [3]=fAlt static addr (hex), [4]=gCatches static addr (hex), [5]=gPropagates
/// static addr (hex).
bool _tryActivatePatch(List<String> args) {
  if (args.length < 6) {
    print('  (skip: expected 6 args, see NOTES.md)');
    return false;
  }
  final bytecodePath = args[0];
  final selfPath = args[1];
  final fStatic = int.parse(args[2], radix: 16);
  final fAltStatic = int.parse(args[3], radix: 16);
  final callerStatics = {
    'gCatches': int.parse(args[4], radix: 16),
    'gPropagates': int.parse(args[5], radix: 16),
  };

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

  const pageSize = 4096;
  final mprotect = DynamicLibrary.process()
      .lookupFunction<Int32 Function(Pointer<Void>, IntPtr, Int32), int Function(Pointer<Void>, int, int)>(
          'mprotect');
  const protRead = 0x1, protWrite = 0x2, protExec = 0x4;
  final fAltRuntime = loadBias + fAltStatic;

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

  for (final entry in callerStatics.entries) {
    final callerName = entry.key;
    final callerStatic = entry.value;
    final callerRuntime = loadBias + callerStatic;

    const scanWindow = 256;
    final body = Pointer<Uint8>.fromAddress(callerRuntime).asTypedList(scanWindow);
    int? callSiteRuntime;
    for (var i = 0; i + 4 <= scanWindow; i += 4) {
      final word = ByteData.sublistView(body, i, i + 4).getUint32(0, Endian.little);
      if ((word >> 26) != 0x25) continue;
      var imm26 = word & 0x3FFFFFF;
      if (imm26 & 0x2000000 != 0) imm26 -= 0x4000000;
      final siteStatic = (callerRuntime + i) - loadBias;
      final targetStatic = siteStatic + imm26 * 4;
      if (targetStatic == fStatic) {
        callSiteRuntime = callerRuntime + i;
        break;
      }
    }
    if (callSiteRuntime == null) {
      print('  did not find `bl f` inside $callerName body (scanned $scanWindow bytes)');
      return false;
    }

    final pageStart = callSiteRuntime & ~(pageSize - 1);
    const patchLen = 2 * pageSize;
    var rc = mprotect(Pointer<Void>.fromAddress(pageStart), patchLen, protRead | protWrite | protExec);
    if (rc != 0) {
      print('  mprotect(RWX) failed for $callerName: rc=$rc');
      return false;
    }

    final newImm26 = (fAltRuntime - callSiteRuntime) ~/ 4;
    final newWord = (0x25 << 26) | (newImm26 & 0x3FFFFFF);
    final wordBytes = ByteData(4)..setUint32(0, newWord, Endian.little);
    final callBytes = Pointer<Uint8>.fromAddress(callSiteRuntime).asTypedList(4);
    for (var i = 0; i < 4; i++) {
      callBytes[i] = wordBytes.getUint8(i);
    }

    rc = mprotect(Pointer<Void>.fromAddress(pageStart), patchLen, protRead | protExec);
    if (rc != 0) {
      print('  mprotect(RX restore) failed for $callerName: rc=$rc');
    }
    clearCacheStub(Pointer<Void>.fromAddress(callSiteRuntime));
    print('  patched call-site in $callerName to target fAlt(), icache flushed');
  }

  return true;
}
