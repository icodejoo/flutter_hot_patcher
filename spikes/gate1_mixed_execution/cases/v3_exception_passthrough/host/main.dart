// Copyright / 版权: spike code for flutter_hot_patcher Gate 1 (V3 exception passthrough).
//
// V1 proved static direct calls are redirectable to interpreted, behaviorally
// different code. V3 asks: what happens to CONTROL FLOW when the interpreted
// replacement throws instead of returning? Two scenarios, both on the same
// mixed AOT<->interpreter stack:
//   (a) the AOT caller catches it (try/catch around the redirected call site)
//   (b) the AOT caller does NOT catch it — does the exception correctly
//       unwind past that frame to an outer (also AOT) catch?
//
// V1 证明了静态直调可以被重定向到解释执行的、行为不同的代码。V3 要问：当解释执行
// 的替换体抛异常而不是返回值时，控制流会怎样？两种场景，都发生在同一套
// AOT<->解释器混合栈上：
//   (a) AOT 调用方接住了(在被重定向的调用点外包 try/catch)
//   (b) AOT 调用方没接住——异常能不能正确穿透这一帧，被更外层(同样是 AOT)的
//       try/catch 接住？
library;

import 'dart:ffi';
import 'dart:io';
import 'dart:typed_data';
import 'dart:_internal' as internal;

/// Existing function to be replaced. Marked never-inline so it keeps a real,
/// separate entry point that a redirect can target.
///
/// 待替换的既有函数。标记 never-inline，使其保留独立入口以便重定向。
@pragma('vm:never-inline')
String f() => 'ORIGINAL';

/// Existing caller #1: catches whatever f() throws right at the call site.
/// 既有调用方 #1：在调用点外直接接住 f() 抛出的任何异常。
@pragma('vm:never-inline')
String gCatches() {
  try {
    return 'g() got: ${f()}';
  } catch (e) {
    return 'g() caught: $e';
  }
}

/// Existing caller #2: does NOT catch — an exception from f() must unwind
/// past this whole AOT frame to whatever catches it further up the stack.
///
/// 既有调用方 #2：不接住——f() 抛出的异常必须穿透这整个 AOT 帧，
/// 被栈上更外层的 catch 接住。
@pragma('vm:never-inline')
String gPropagates() => 'g() got: ${f()}';

/// Cached closure over the interpreted patch entry point, loaded once via
/// the VM-level `loadDynamicModuleClosure` extension (see V1's vm_patch),
/// then invoked synchronously and repeatedly from [fAlt].
///
/// 缓存的解释执行补丁入口闭包，经 VM 层扩展 `loadDynamicModuleClosure`
/// (见 V1 的 vm_patch)只加载一次，之后由 [fAlt] 反复同步调用。
Function? _cachedPatch;

/// Redirect target for both gCatches's and gPropagates's calls to f().
/// Forwards to the cached interpreted closure via the direct-invoke native
/// (Internal_invokeDynamicModuleClosure), which correctly propagates any
/// exception the interpreted body throws as a real Dart exception at this
/// call site — not a native crash, not a swallowed error.
///
/// gCatches 和 gPropagates 对 f() 的调用点都重定向到这里。转发给缓存的
/// 解释执行闭包(经 Internal_invokeDynamicModuleClosure 直接调用)，
/// 解释体抛出的任何异常都会在这个调用点正确地以真正的 Dart 异常形式
/// 冒出来——不是原生层崩溃，也不会被吞掉。
@pragma('vm:entry-point')
@pragma('vm:never-inline')
String fAlt() => internal.invokeDynamicModuleClosure(_cachedPatch!) as String;

void main(List<String> args) {
  print('BEFORE gCatches:    ${gCatches()}');
  print('BEFORE gPropagates: ${gPropagates()}');

  final activated = _tryActivatePatch(args);
  if (!activated) {
    print('V3 INCONCLUSIVE: patch activation failed');
    exit(3);
  }

  // Scenario (a): AOT caller catches the exception from interpreted code.
  // 场景(a)：AOT 调用方接住了解释执行代码抛出的异常。
  final caught = gCatches();
  print('AFTER gCatches:     $caught');
  final scenarioAOk = caught == 'g() caught: Bad state: PATCHED-EXCEPTION';

  // Scenario (b): AOT caller does NOT catch — must unwind past gPropagates()
  // (an entirely separate patched AOT frame) to THIS outer try/catch in main.
  // 场景(b)：AOT 调用方没接住——必须穿透 gPropagates()(另一个独立的、
  // 被打了补丁的 AOT 帧)，被 main 这里更外层的 try/catch 接住。
  var scenarioBOk = false;
  try {
    final result = gPropagates();
    print('AFTER gPropagates:  $result (expected: unreachable, exception should propagate)');
  } catch (e) {
    print('AFTER gPropagates:  propagated to main, caught: $e');
    scenarioBOk = e.toString() == 'Bad state: PATCHED-EXCEPTION';
  }

  if (scenarioAOk && scenarioBOk) {
    print('V3 PASS: exception from interpreted code both caught-at-site and propagated-past-frame correctly');
    exit(0);
  }
  print('V3 FAIL: scenarioAOk=$scenarioAOk scenarioBOk=$scenarioBOk');
  exit(1);
}

/// Same mechanism as V1's _tryActivatePatch, generalized to patch BOTH
/// gCatches's and gPropagates's independent call sites to f() — each is a
/// separate `call rel32` instruction in a separate function body, found and
/// rewritten independently.
///
/// 和 V1 的 _tryActivatePatch 同一套机制，泛化成同时改写 gCatches 和
/// gPropagates 两个独立的、对 f() 的调用点——各自是不同函数体里独立的
/// `call rel32` 指令，分别定位、分别改写。
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
    if (name == 'gCatches' || name == 'gPropagates' || name == 'f' || name == 'fAlt') {
      addrs.putIfAbsent(name, () => int.parse(m.group(1)!, radix: 16));
    }
  }
  for (final required in ['gCatches', 'gPropagates', 'f', 'fAlt']) {
    if (!addrs.containsKey(required)) {
      print('  nm did not resolve $required: $addrs');
      return false;
    }
  }
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

  const pageSize = 4096;
  final mprotect = DynamicLibrary.process()
      .lookupFunction<Int32 Function(Pointer<Void>, IntPtr, Int32), int Function(Pointer<Void>, int, int)>(
          'mprotect');
  const protRead = 0x1, protWrite = 0x2, protExec = 0x4;
  final fAltRuntime = loadBias + fAltStatic;

  for (final callerName in ['gCatches', 'gPropagates']) {
    final callerStatic = addrs[callerName]!;
    final callerRuntime = loadBias + callerStatic;

    const scanWindow = 256;
    final body = Pointer<Uint8>.fromAddress(callerRuntime).asTypedList(scanWindow);
    int? callSiteRuntime;
    for (var i = 0; i + 5 <= scanWindow; i++) {
      if (body[i] != 0xE8) continue;
      final rel = ByteData.sublistView(body, i + 1, i + 5).getInt32(0, Endian.little);
      final siteStatic = (callerRuntime + i) - loadBias;
      final targetStatic = siteStatic + 5 + rel;
      if (targetStatic == fStatic) {
        callSiteRuntime = callerRuntime + i;
        break;
      }
    }
    if (callSiteRuntime == null) {
      print('  did not find `call f` inside $callerName body (scanned $scanWindow bytes)');
      return false;
    }

    final pageStart = callSiteRuntime & ~(pageSize - 1);
    const patchLen = 2 * pageSize;
    var rc = mprotect(Pointer<Void>.fromAddress(pageStart), patchLen, protRead | protWrite | protExec);
    if (rc != 0) {
      print('  mprotect(RWX) failed for $callerName: rc=$rc');
      return false;
    }

    final newRel = fAltRuntime - (callSiteRuntime + 5);
    final callBytes = Pointer<Uint8>.fromAddress(callSiteRuntime).asTypedList(5);
    final relBytes = ByteData(4)..setInt32(0, newRel, Endian.little);
    for (var i = 0; i < 4; i++) {
      callBytes[1 + i] = relBytes.getUint8(i);
    }

    rc = mprotect(Pointer<Void>.fromAddress(pageStart), patchLen, protRead | protExec);
    if (rc != 0) {
      print('  mprotect(RX restore) failed for $callerName: rc=$rc (patch already applied)');
    }
    print('  patched call-site in $callerName to target fAlt()');
  }

  return true;
}
