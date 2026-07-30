// Copyright / 版权: spike code for flutter_hot_patcher Gate 1 (V4 GC inside patch).
//
// V1-V3 proved replacement + exception propagation work on the mixed
// AOT<->interpreter stack. V4 asks: what if the interpreted replacement
// triggers a GC WHILE it's running? Does GC correctly scan/preserve objects
// that are alive on the calling AOT frame (reached via a runtime-patched
// call site), and does allocation inside the interpreter keep working
// correctly after that GC?
//
// V1-V3 证明了替换 + 异常传播在混合 AOT<->解释器栈上都成立。V4 要问：如果解释
// 执行的替换体在运行期间触发 GC 会怎样？GC 能不能正确扫描/保住调用方 AOT 帧
// (经运行时改写的调用点抵达)上存活的对象，GC 之后解释器内部的分配是否依然正常？
library;

import 'dart:ffi';
import 'dart:io';
import 'dart:typed_data';
import 'dart:_internal' as internal;

/// Existing function to be replaced.
/// 待替换的既有函数。
@pragma('vm:never-inline')
String f() => 'ORIGINAL';

/// Existing caller. Holds a heap-allocated marker object ALIVE across the
/// call to f() — after the call (which forces a full GC mid-flight, inside
/// interpreted code), the marker's contents must be exactly unchanged.
/// A GC bug in scanning this AOT frame's roots (because the call site was
/// runtime-patched rather than a normal compiled call) would corrupt or lose
/// this object.
///
/// 既有调用方。持有一个堆上的标记对象，在调用 f() 期间保持存活——这次调用
/// (在解释执行代码里强制触发一次全量 GC)结束后，标记对象的内容必须原样不变。
/// 如果 GC 扫描这个 AOT 帧的根集合出了问题(因为调用点是运行时改写的、不是
/// 正常编译产生的调用)，这个对象就会被破坏或丢失。
@pragma('vm:never-inline')
String g() {
  final marker = List<int>.filled(4, 0);
  marker[0] = 0x11111111;
  marker[1] = 0x22222222;
  marker[2] = 0x33333333;
  marker[3] = 0x44444444;

  final result = f(); // redirected to interpreted fPatched(), forces GC mid-call

  final markerIntact = marker[0] == 0x11111111 &&
      marker[1] == 0x22222222 &&
      marker[2] == 0x33333333 &&
      marker[3] == 0x44444444;

  return 'g() got: $result; markerIntact=$markerIntact';
}

/// Cached closure over the interpreted patch entry point (see V1's vm_patch).
/// V1 的解释执行补丁入口闭包缓存(见 V1 的 vm_patch)。
Function? _cachedPatch;

/// Redirect target for g()'s call to f(). Forwards to the cached
/// interpreted closure via the direct-invoke native.
///
/// g() 对 f() 调用点的重定向目标。经直接调用原生入口转发给缓存的解释执行闭包。
@pragma('vm:entry-point')
@pragma('vm:never-inline')
String fAlt() => internal.invokeDynamicModuleClosure(_cachedPatch!) as String;

void main(List<String> args) {
  print('BEFORE: ${g()}');

  final activated = _tryActivatePatch(args);
  if (!activated) {
    print('V4 INCONCLUSIVE: patch activation failed');
    exit(3);
  }

  final after = g();
  print('AFTER:  $after');

  final patchedOk = after.contains('PATCHED-AFTER-ALLOC-last=garbage-299999');
  final markerOk = after.contains('markerIntact=true');

  if (patchedOk && markerOk) {
    print('V4 PASS: GC triggered inside interpreted code did not corrupt caller roots or post-GC allocation');
    exit(0);
  }
  print('V4 FAIL: patchedOk=$patchedOk markerOk=$markerOk');
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
