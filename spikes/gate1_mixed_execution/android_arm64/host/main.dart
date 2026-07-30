// Copyright / 版权: spike code for flutter_hot_patcher Gate 1b (Android arm64 repro).
//
// Reproduces V1 (spikes/gate1_mixed_execution/cases/v1_replace_existing_function)
// on a real Android arm64 device instead of x86-64 desktop. The interpreter-side
// mechanism (VM patch: loadDynamicModuleClosure / invokeDynamicModuleClosure) is
// unchanged and arch-independent. What's NEW here is the call-site-rewrite half,
// which is genuinely architecture-specific:
//   - x86-64: `call rel32` (opcode 0xE8, 5 bytes, 4-byte rel32 displacement).
//   - arm64:  `bl` (opcode class 0b100101, 4 bytes, 26-bit signed word-offset
//             immediate, ±128MB range) — confirmed by disassembly (see NOTES.md),
//             not assumed.
// arm64 also requires an explicit instruction-cache flush after writing new
// code bytes (`__clear_cache`) — x86-64 doesn't need this because its cache
// coherency model guarantees self-modifying code is observed without an
// explicit flush; arm64 (like most non-x86 architectures) does not make that
// guarantee, so skipping this step risks executing stale cached instructions.
//
// 在真实 Android arm64 设备上复现 V1
// (spikes/gate1_mixed_execution/cases/v1_replace_existing_function)，而不是
// x86-64 桌面。接解释器那一半机制(VM 补丁:loadDynamicModuleClosure /
// invokeDynamicModuleClosure)完全不变、和架构无关。这里新增的是调用点改写
// 那一半，这部分是真正架构相关的:
//   - x86-64: `call rel32`(opcode 0xE8，5 字节，4 字节 rel32 位移)。
//   - arm64: `bl`(opcode 类 0b100101，4 字节，26 位有符号字偏移立即数，
//     ±128MB 范围)——反汇编实测确认(见 NOTES.md)，不是假设。
// arm64 还要求写完新指令字节后显式做指令缓存失效(`__clear_cache`)——x86-64
// 不需要这一步，因为它的缓存一致性模型保证自修改代码无需显式失效就能被观测到；
// arm64(和大多数非 x86 架构一样)不提供这个保证，跳过这一步有执行到缓存里
// 旧指令的风险。
library;

import 'dart:ffi';
import 'dart:io';
import 'dart:typed_data';
import 'dart:_internal' as internal;

@pragma('vm:never-inline')
String f() => 'ORIGINAL';

@pragma('vm:never-inline')
String g() => 'g() got: ${f()}';

Function? _cachedPatch;

@pragma('vm:entry-point')
@pragma('vm:never-inline')
String fAlt() => internal.invokeDynamicModuleClosure(_cachedPatch!) as String;

void main(List<String> args) {
  print('BEFORE: ${g()}');

  final activated = _tryActivatePatch(args);
  if (!activated) {
    print('GATE1B INCONCLUSIVE: patch activation failed');
    exit(3);
  }

  final after = g();
  print('AFTER: $after');

  if (after == 'g() got: PATCHED') {
    print('GATE1B-ANDROID-ARM64 PASS: existing call site g()->f() reached interpreted f\' on real arm64 hardware');
    exit(0);
  }
  print('GATE1B-ANDROID-ARM64 FAIL: call site still reaches ORIGINAL after activation');
  exit(1);
}

/// arm64 port of V1's _tryActivatePatch. Same overall shape (resolve static
/// addresses + /proc/self/maps + self-check + scan + mprotect), but the
/// instruction search/rewrite logic is arm64-specific, and there's one extra
/// step x86-64 never needed: __clear_cache.
///
/// Unlike V1 (which shelled out to `nm` on the running binary itself), Android
/// devices don't ship binutils — there's no `nm` to invoke on-device. Static
/// addresses are instead resolved via `nm` at BUILD time (on the host, where
/// the same unstripped snapshot ELF is available) and passed in as CLI args.
/// This is a legitimate substitute, not a weaker test: the actual mechanism
/// being verified (runtime call-site rewrite + icache flush, executed
/// on-device) is unchanged; only the “where do I get symbol addresses from”
/// bookkeeping moved from runtime introspection to build-time computation.
///
/// V1 的 _tryActivatePatch 的 arm64 移植版。整体形状一样(解析静态地址 +
/// /proc/self/maps + 自检 + 扫描 + mprotect)，但指令查找/改写逻辑是 arm64
/// 专属的，而且多一步 x86-64 从来不需要的：__clear_cache。
///
/// 和 V1(对着正在运行的自身二进制跑 `nm`)不同，Android 设备不自带
/// binutils——设备上没有 `nm` 可调。静态地址改成在**构建期**(宿主机上，
/// 同一份未 strip 的快照 ELF 可用)用 `nm` 算好，通过命令行参数传进来。
/// 这是合理的替代，不是弱化测试：真正要验证的机制(运行时改写调用点 + 刷新
/// 指令缓存，在设备上执行)完全没变；变的只是"符号地址从哪来"这个记账方式，
/// 从运行时自省挪到了构建期计算。
///
/// args: [0]=bytecode path (device), [1]=own snapshot path (device, for
/// /proc/self/maps matching), [2]=g static addr (hex), [3]=f static addr
/// (hex), [4]=fAlt static addr (hex).
bool _tryActivatePatch(List<String> args) {
  if (args.length < 5) {
    print('  (skip: expected args=[bytecodePath, selfPath, gAddrHex, fAddrHex, fAltAddrHex])');
    return false;
  }
  final bytecodePath = args[0];
  final selfPath = args[1];
  final gStatic = int.parse(args[2], radix: 16);
  final fStatic = int.parse(args[3], radix: 16);
  final fAltStatic = int.parse(args[4], radix: 16);
  print('  static (build-time, via nm on host): g=0x${gStatic.toRadixString(16)} '
      'f=0x${fStatic.toRadixString(16)} fAlt=0x${fAltStatic.toRadixString(16)}');

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
  print('  load_bias=0x${loadBias.toRadixString(16)}');

  // Self-check: g()'s prologue on arm64 is `stp x29, x30, [sp, #-0x10]!`
  // (confirmed by disassembly: `a9bf79fd`), not x86-64's `push rbp` — a
  // different architecture means a different expected byte pattern.
  //
  // 自检：arm64 上 g() 的序言是 `stp x29, x30, [sp, #-0x10]!`
  // (反汇编确认为 `a9bf79fd`)，不是 x86-64 的 `push rbp`——换了架构，
  // 期望的字节模式也得跟着换。
  final gRuntime = loadBias + gStatic;
  final prologue = Pointer<Uint8>.fromAddress(gRuntime).asTypedList(4);
  const expectedPrologue = [0xfd, 0x79, 0xbf, 0xa9]; // a9bf79fd, little-endian bytes
  if (!(prologue[0] == expectedPrologue[0] &&
      prologue[1] == expectedPrologue[1] &&
      prologue[2] == expectedPrologue[2] &&
      prologue[3] == expectedPrologue[3])) {
    print('  self-check FAILED: g() prologue mismatch at runtime addr '
        '0x${gRuntime.toRadixString(16)}: $prologue');
    return false;
  }
  print('  self-check OK: g() prologue matches at runtime 0x${gRuntime.toRadixString(16)}');

  // Scan g()'s body for a `bl` instruction whose computed target equals f's
  // static address. arm64 instructions are fixed 4 bytes; `bl` is identified
  // by its top 6 bits (0b100101); the low 26 bits are a signed word offset
  // (multiply by 4 for the byte displacement), PC-relative to the
  // instruction's own address.
  //
  // 在 g() 函数体里扫描 `bl` 指令，找目标地址等于 f 静态地址的那条。arm64
  // 指令定长 4 字节；`bl` 由高 6 位(0b100101)识别；低 26 位是有符号字偏移
  // (乘 4 才是字节位移)，相对指令自己的地址(PC-relative)。
  const scanWindow = 256;
  final body = Pointer<Uint8>.fromAddress(gRuntime).asTypedList(scanWindow);
  int? callSiteRuntime;
  for (var i = 0; i + 4 <= scanWindow; i += 4) {
    final word = ByteData.sublistView(body, i, i + 4).getUint32(0, Endian.little);
    if ((word >> 26) != 0x25) continue; // top 6 bits must be 0b100101 (BL)
    var imm26 = word & 0x3FFFFFF;
    if (imm26 & 0x2000000 != 0) imm26 -= 0x4000000; // sign-extend 26-bit field
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
  print('  found call-site at runtime 0x${callSiteRuntime.toRadixString(16)} (bl -> f)');

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
    print('  mprotect(RX restore) failed: rc=$rc (patch already applied)');
  }

  // arm64-only step: flush the instruction cache for the patched range.
  // Without this, other cores (or even the same core, depending on
  // microarchitecture) may still fetch the OLD cached instruction bytes.
  //
  // Neither `__clear_cache` (the usual compiler-rt/GCC builtin support
  // routine) nor the classic Android `cacheflush()` syscall wrapper are
  // exported by bionic's libc.so on arm64 — confirmed empirically via `nm -D`
  // on the NDK's stub libc (both lookups came back empty; AArch64 Linux has
  // no `cacheflush` syscall at all, unlike 32-bit ARM, because EL0 can
  // already issue cache-maintenance instructions directly without a
  // privileged syscall). So we can't dlsym our way to a ready-made flush
  // function. Instead: assemble the standard AArch64 self-modifying-code
  // sequence ourselves (`dc cvau` + `dsb ish` + `ic ivau` + `dsb ish` +
  // `isb` + `ret`) with the NDK's real cross-assembler (not hand-encoded —
  // see NOTES.md for the verified bytes and how they were obtained), write
  // those bytes into a freshly mmap'd RWX page, and call it as a function
  // pointer taking the patched address in x0.
  //
  // arm64 独有的一步：对改写区间做指令缓存失效。不做这一步，其他核心
  // (甚至同一个核心，取决于微架构)仍可能取到缓存里的旧指令字节。
  //
  // `__clear_cache`(通常的 compiler-rt/GCC 内建支持例程)和 Android 经典的
  // `cacheflush()` 系统调用包装，在 arm64 上 bionic 的 libc.so 里都没有导出
  // ——已经用 `nm -D` 对着 NDK 的桩 libc 实测确认(两个符号都查不到；AArch64
  // Linux 压根没有 `cacheflush` 系统调用，不像 32 位 ARM，因为 EL0 已经能
  // 直接发出缓存维护指令，不需要走特权系统调用)。所以没法靠 dlsym 找到现成的
  // 刷新函数。改成自己组装标准的 AArch64 自修改代码序列(`dc cvau` + `dsb ish`
  // + `ic ivau` + `dsb ish` + `isb` + `ret`)——用 NDK 真正的交叉汇编器汇编出来
  // (不是凭记忆手写指令编码——验证过的字节和获取方式见 NOTES.md)，写进一块
  // 新 mmap 出来的 RWX 页，当函数指针调用，x0 传入被改写的地址。
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

  print('  patched call-site to target fAlt() at runtime 0x${fAltRuntime.toRadixString(16)}, icache flushed');
  return true;
}
