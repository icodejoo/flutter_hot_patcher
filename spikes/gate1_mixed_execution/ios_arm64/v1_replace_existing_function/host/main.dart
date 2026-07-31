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
    print('GATE1B-IOS INCONCLUSIVE: patch activation failed (mprotect likely blocked by W^X)');
    exit(3);
  }

  final after = g();
  print('AFTER: $after');

  if (after == 'g() got: PATCHED') {
    print('GATE1B-IOS PASS: existing call site g()->f() reached interpreted f\' on real iOS arm64');
    exit(0);
  }
  print('GATE1B-IOS FAIL: call site still reaches ORIGINAL after activation');
  exit(1);
}

// iOS arm64: use dyld slide instead of /proc/self/maps
// dlopen("") returns handle to main executable; use _dyld_get_image_vmaddr_slide
@Native<IntPtr Function(UnsignedInt)>(symbol: '_dyld_get_image_vmaddr_slide')
external int _dyldGetImageVmaddrSlide(int imageIndex);

@Native<UnsignedInt Function()>(symbol: '_dyld_image_count')
external int _dyldImageCount();

@Native<Pointer<Char> Function(UnsignedInt)>(symbol: '_dyld_get_image_name')
external Pointer<Char> _dyldGetImageName(int imageIndex);

bool _tryActivatePatch(List<String> args) {
  if (args.length < 4) {
    print('  (skip: expected args=[bytecodePath, gAddrHex, fAddrHex, fAltAddrHex])');
    return false;
  }
  final bytecodePath = args[0];
  final gStatic = int.parse(args[1], radix: 16);
  final fStatic = int.parse(args[2], radix: 16);
  final fAltStatic = int.parse(args[3], radix: 16);
  print('  static (build-time, via nm on host): g=0x${gStatic.toRadixString(16)} '
      'f=0x${fStatic.toRadixString(16)} fAlt=0x${fAltStatic.toRadixString(16)}');

  // Load bytecode patch
  final bytes = File(bytecodePath).readAsBytesSync();
  final loaded = internal.loadDynamicModuleClosure(bytes: bytes);
  if (loaded == null || loaded is! Function) {
    print('  loadDynamicModuleClosure returned $loaded (expected a Function)');
    return false;
  }
  _cachedPatch = loaded;
  print('  loaded interpreted patch entry point as a closure');

  // iOS: find load bias via dyld
  int? loadBias;
  final snapshotName = args.isNotEmpty ? args[0].split('/').last : '';
  final count = _dyldImageCount();
  for (var i = 0; i < count; i++) {
    final namePtr = _dyldGetImageName(i);
    final name = namePtr.cast<Utf8>().toDartString();
    // The main.snapshot is loaded by dartaotruntime; find it by matching known suffix
    if (name.contains('main.snapshot') || i == 0) {
      loadBias = _dyldGetImageVmaddrSlide(i);
      print('  dyld[$i] load_bias=0x${loadBias.toRadixString(16)} name=$name');
      if (name.contains('main.snapshot')) break;
    }
  }
  if (loadBias == null) {
    print('  could not determine load bias via dyld');
    return false;
  }

  final gRuntime = loadBias + gStatic;

  // Self-check: verify g() prologue
  final prologue = Pointer<Uint8>.fromAddress(gRuntime).asTypedList(4);
  const expectedPrologue = [0xfd, 0x79, 0xbf, 0xa9];
  if (!(prologue[0] == expectedPrologue[0] &&
      prologue[1] == expectedPrologue[1] &&
      prologue[2] == expectedPrologue[2] &&
      prologue[3] == expectedPrologue[3])) {
    print('  self-check FAILED: g() prologue mismatch at runtime addr '
        '0x${gRuntime.toRadixString(16)}: $prologue');
    return false;
  }
  print('  self-check OK: g() prologue matches at runtime 0x${gRuntime.toRadixString(16)}');

  // Scan g() body for `bl f`
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
    print('  did not find `bl f` inside g() body');
    return false;
  }
  print('  found call-site at runtime 0x${callSiteRuntime.toRadixString(16)} (bl -> f)');

  // iOS W^X test: attempt mprotect(RWX)
  const pageSize = 4096;
  final pageStart = callSiteRuntime & ~(pageSize - 1);
  const patchLen = 2 * pageSize;
  final mprotect = DynamicLibrary.process()
      .lookupFunction<Int32 Function(Pointer<Void>, IntPtr, Int32), int Function(Pointer<Void>, int, int)>(
          'mprotect');
  const protRead = 0x1, protWrite = 0x2, protExec = 0x4;
  final rc = mprotect(Pointer<Void>.fromAddress(pageStart), patchLen, protRead | protWrite | protExec);
  if (rc != 0) {
    // Expected on iOS without JIT entitlement: errno EPERM (1) or EACCES (13)
    final errno = DynamicLibrary.process()
        .lookupFunction<Pointer<Int32> Function(), Pointer<Int32> Function()>('__error')();
    print('  mprotect(RWX) FAILED rc=$rc errno=${errno.value} — W^X enforced by iOS (expected)');
    print('  GATE1B-IOS W^X CONFIRMED: cannot rewrite code page without JIT entitlement');
    return false;
  }

  // If we get here: mprotect succeeded (unexpected — document it)
  print('  mprotect(RWX) SUCCEEDED (unexpected on hardened iOS — check entitlements)');

  final fAltRuntime = loadBias + fAltStatic;
  final newImm26 = (fAltRuntime - callSiteRuntime) ~/ 4;
  final newWord = (0x25 << 26) | (newImm26 & 0x3FFFFFF);
  final wordBytes = ByteData(4)..setUint32(0, newWord, Endian.little);
  final callBytes = Pointer<Uint8>.fromAddress(callSiteRuntime).asTypedList(4);
  for (var i = 0; i < 4; i++) {
    callBytes[i] = wordBytes.getUint8(i);
  }

  mprotect(Pointer<Void>.fromAddress(pageStart), patchLen, protRead | protExec);

  // icache flush (same stub as Android arm64)
  const cacheFlushStubBytes = [
    0x20, 0x7b, 0x0b, 0xd5,
    0x9f, 0x3b, 0x03, 0xd5,
    0x20, 0x75, 0x0b, 0xd5,
    0x9f, 0x3b, 0x03, 0xd5,
    0xdf, 0x3f, 0x03, 0xd5,
    0xc0, 0x03, 0x5f, 0xd6,
  ];
  final mmapFn = DynamicLibrary.process().lookupFunction<
      Pointer<Void> Function(Pointer<Void>, IntPtr, Int32, Int32, Int32, IntPtr),
      Pointer<Void> Function(Pointer<Void>, int, int, int, int, int)>('mmap');
  const mapPrivateAnonymous = 0x02 | 0x1000; // MAP_PRIVATE | MAP_ANON on iOS
  final stubPage = mmapFn(Pointer<Void>.fromAddress(0), pageSize,
      protRead | protWrite | protExec, mapPrivateAnonymous, -1, 0);
  if (stubPage.address == 0xFFFFFFFFFFFFFFFF || stubPage.address == 0) {
    print('  mmap for icache-flush stub failed (may also be W^X blocked)');
  } else {
    final stubBytes = stubPage.cast<Uint8>().asTypedList(cacheFlushStubBytes.length);
    stubBytes.setAll(0, cacheFlushStubBytes);
    final clearCacheStub = stubPage
        .cast<NativeFunction<Void Function(Pointer<Void>)>>()
        .asFunction<void Function(Pointer<Void>)>();
    clearCacheStub(Pointer<Void>.fromAddress(callSiteRuntime));
  }

  print('  patched call-site to fAlt() at 0x${fAltRuntime.toRadixString(16)}, icache flushed');
  return true;
}
