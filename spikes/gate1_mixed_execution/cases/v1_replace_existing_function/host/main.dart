// Copyright / 版权: spike code for flutter_hot_patcher Gate 1 (V1 replacement).
//
// The CORE thesis: can an already-AOT-compiled, existing call site (g -> f) be
// redirected at runtime to reach an interpreted, behaviorally-different f'?
// This is the unprecedented part. Interop (adding new functions) is NOT the target.
//
// 核心命题：已经 AOT 编译的既有调用点（g -> f）能否在运行时被重定向到解释执行、
// 行为不同的 f'？这才是无公开先例的部分。"新增函数的互操作"不是目标。
library;

import 'dart:ffi';
import 'dart:io';
import 'dart:typed_data';
import 'dart:_internal' as internal;

/// Existing function to be replaced. Marked never-inline so it keeps a real,
/// separate entry point that a redirect can target.
///
/// 待替换的既有函数。标记 never-inline，使其保留独立入口以便重定向。
///
/// Returns "ORIGINAL" in the baseline build. The patch f' must make g() observe "PATCHED".
/// 基线构建返回 "ORIGINAL"；补丁 f' 须让 g() 观测到 "PATCHED"。
@pragma('vm:never-inline')
String f() => 'ORIGINAL';

/// Existing caller. Its call to f() is compiled by AOT (static direct call).
/// After activation, this same call must land in the interpreted f'.
///
/// 既有调用方。它对 f() 的调用被 AOT 编译（静态直调）。激活补丁后，
/// 这个调用必须落进解释执行的 f'。
@pragma('vm:never-inline')
String g() => 'g() got: ${f()}';

/// Cached closure over the interpreted patch entry point (fPatched), loaded
/// once via the VM-level `loadDynamicModuleClosure` extension (see
/// runtime/lib/object.cc Internal_loadDynamicModuleClosure) and then called
/// synchronously, repeatedly, from [fAlt]. Loading the same module bytes
/// twice would throw ("duplicate library"), so activation loads exactly once.
///
/// 缓存的解释执行补丁入口闭包(fPatched)，经 VM 层扩展 `loadDynamicModuleClosure`
/// 只加载一次(`runtime/lib/object.cc` 的 `Internal_loadDynamicModuleClosure`)，
/// 之后由 [fAlt] 反复同步调用。同一份模块字节重复加载会报错("重复库")，
/// 所以激活阶段只加载这一次。
Function? _cachedPatch;

/// Redirect target used by the runtime call-site-patch proof-of-concept.
/// Kept reachable via `vm:entry-point` so AOT tree-shaking doesn't strip it
/// (nothing calls it from Dart source — it's only ever reached by patching
/// g's compiled call instruction to point here instead of at f()). Forwards
/// to the cached interpreted closure — every call genuinely re-enters the
/// bytecode interpreter, not a precomputed constant.
///
/// 运行时调用点改写实验的重定向目标。用 `vm:entry-point` 保活，防止 AOT 树摇
/// 把它删掉(源码里没有任何 Dart 调用点调用它——唯一到达路径是把 g 编译产物里
/// 的调用指令改指向这里，而不是 f())。转发给缓存的解释执行闭包——每次调用
/// 都是真实重新进入字节码解释器，不是预算好的常量。
@pragma('vm:entry-point')
@pragma('vm:never-inline')
String fAlt() => internal.invokeDynamicModuleClosure(_cachedPatch!) as String;

/// V1 spike host entry.
/// Prints g() before and after patch activation; PASS iff the AFTER call
/// observably reflects the interpreted f' ("PATCHED").
///
/// V1 spike 宿主入口。补丁激活前后各调一次 g()；当 AFTER 调用可观测地反映
/// 解释执行的 f'（"PATCHED"）时判 PASS。
void main(List<String> args) {
  print('BEFORE: ${g()}'); // 期望 ORIGINAL

  // ── 待验证的核心机制（见 NOTES.md）─────────────────────────────
  // 把 f 的入口切到解释器里的 f'。公共 API loadModuleFromBytes 只做"新增"，
  // 不做"替换既有函数入口"，因此这一步很可能需要 VM 层改动来实现/探索。
  // Redirect f's entry to the interpreted f'. The public loadModuleFromBytes
  // only ADDS; replacing an existing function's entry likely needs VM-level work.
  final activated = _tryActivatePatch(args);
  // ──────────────────────────────────────────────────────────────

  final after = g();
  print('AFTER: $after');

  if (!activated) {
    print('V1 INCONCLUSIVE: patch activation mechanism not wired yet');
    exit(3);
  }
  if (after.contains('PATCHED')) {
    print('V1 PASS: existing call site g()->f() reached interpreted f\'');
    exit(0);
  }
  print('V1 FAIL: call site still reaches ORIGINAL after activation');
  exit(1);
}

/// V1 activation, two independent mechanisms wired together:
///
/// (a) **Reach the interpreter**: load the patch bytecode via the VM-level
///     `internal.loadDynamicModuleClosure` extension added for this spike
///     (see runtime/lib/object.cc `Internal_loadDynamicModuleClosure`),
///     which returns a *closure* over the bytecode entry point instead of
///     invoking it — sidesteps both the public API's Future-wrapping (the
///     underlying native call is actually synchronous) and its "can't load
///     the same module twice" limit (we load once, call the closure many
///     times). Cached into [_cachedPatch].
///
/// (b) **Reach the call site**: locate the `call f` instruction inside g()'s
///     compiled machine code and rewrite its rel32 target to point at
///     fAlt() (which forwards to [_cachedPatch]). Pure userspace
///     (dart:ffi + mprotect) — no VM changes needed for this half.
///
/// Both are needed: (a) alone can't reach g()'s existing call site (that's
/// exactly the "additive only" limitation in NOTES.md "关键发现"); (b) alone
/// can only redirect to other AOT-compiled code, not interpreted bytecode.
///
/// args[0] = path to the compiled patch bytecode (f_patch.dart -> dart2bytecode).
/// args[1] = absolute path to this program's own AOT ELF snapshot (for `nm`).
///
/// V1 激活，接上两个独立机制:
///
/// (a) **够到解释器**:通过本 spike 新增的 VM 层扩展 `internal.loadDynamicModuleClosure`
///     (`runtime/lib/object.cc` 的 `Internal_loadDynamicModuleClosure`)加载补丁字节码，
///     返回一个包着字节码入口的**闭包**而不是直接调用它——绕开了公开 API 的 Future 包装
///     (底层原生调用本身是同步的)以及"同一模块不能加载两次"的限制(只加载一次，
///     闭包可以反复调用)。缓存进 [_cachedPatch]。
///
/// (b) **够到调用点**:在 g() 编译产物里找到 `call f` 指令，把它的 rel32 目标改写成
///     fAlt()(转发给 [_cachedPatch])。这一半纯用户态实现(dart:ffi + mprotect)，
///     不需要改 VM。
///
/// 两者缺一不可:只有 (a) 够不到 g() 的既有调用点(这正是 NOTES.md「关键发现」里
/// "只能加法扩展"的限制)；只有 (b) 只能重定向到其他 AOT 编译代码，够不到解释执行字节码。
bool _tryActivatePatch(List<String> args) {
  if (args.length < 2) {
    print('  (skip: expected args[0]=bytecode path, args[1]=own main.snapshot path)');
    return false;
  }
  final bytecodePath = args[0];
  final selfPath = args[1];

  // 0. Load the patch bytecode via the VM-level closure extension.
  final bytes = File(bytecodePath).readAsBytesSync();
  final loaded = internal.loadDynamicModuleClosure(bytes: bytes);
  if (loaded == null || loaded is! Function) {
    print('  loadDynamicModuleClosure returned $loaded (expected a Function)');
    return false;
  }
  _cachedPatch = loaded;
  print('  loaded interpreted patch entry point as a closure');

  // 1. Resolve link-time (static) addresses of g, f, fAlt via `nm` on our
  //    own ELF (it's built --no-embed-sources but NOT stripped).
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
  if (!addrs.containsKey('g') || !addrs.containsKey('f') || !addrs.containsKey('fAlt')) {
    print('  nm did not resolve g/f/fAlt: $addrs');
    return false;
  }
  final gStatic = addrs['g']!;
  final fStatic = addrs['f']!;
  final fAltStatic = addrs['fAlt']!;
  print('  static: g=0x${gStatic.toRadixString(16)} f=0x${fStatic.toRadixString(16)} '
      'fAlt=0x${fAltStatic.toRadixString(16)}');

  // 2. Find the runtime load bias for this ELF: match the executable ('r-xp')
  //    mapping backed by our own snapshot file in /proc/self/maps, and
  //    compute bias = runtime_start - file_offset (holds when p_vaddr ==
  //    p_offset per PT_LOAD segment, standard for lld/gold-linked output).
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
  print('  load_bias=0x${loadBias.toRadixString(16)}');

  // 3. Self-check: bytes at runtime g() address must match the known AOT
  //    function prologue (push rbp; mov rsp,rbp) — confirms bias math is
  //    correct before we go anywhere near a write.
  final gRuntime = loadBias + gStatic;
  final prologue = Pointer<Uint8>.fromAddress(gRuntime).asTypedList(4);
  if (!(prologue[0] == 0x55 && prologue[1] == 0x48 && prologue[2] == 0x89 && prologue[3] == 0xe5)) {
    print('  self-check FAILED: g() prologue mismatch at runtime addr '
        '0x${gRuntime.toRadixString(16)}: $prologue');
    return false;
  }
  print('  self-check OK: g() prologue matches at runtime 0x${gRuntime.toRadixString(16)}');

  // 4. Scan g()'s body for a `call rel32` (opcode 0xE8) whose computed target
  //    equals f's static address — that's our call site, found dynamically
  //    (no hardcoded offset, since adding fAlt() shifts everything).
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
  print('  found call-site at runtime 0x${callSiteRuntime.toRadixString(16)} (call -> f)');

  // 5. mprotect the containing page(s) RWX, patch the 4 displacement bytes to
  //    retarget the call at fAlt(), restore RX.
  const pageSize = 4096;
  final pageStart = callSiteRuntime & ~(pageSize - 1);
  const patchLen = 2 * pageSize; // safety margin if the call site straddles a page
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
  print('  patched call-site to target fAlt() at runtime 0x${fAltRuntime.toRadixString(16)}');
  return true;
}
