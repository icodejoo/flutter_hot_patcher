// Copyright / 版权: flutter_hot_patcher Gate 1b — end-to-end hot-patch demo.
//
// Everything before this file was a spike harness driven by CLI args (bytecode
// path / snapshot path / hex addresses all passed explicitly on every run —
// fine for isolating "does the mechanism work", wrong shape for "what would a
// real deploy look like"). This demo restructures the SAME validated
// mechanism (V1's arm64 call-site rewrite + VM-patched interpreter loading)
// into the actual target shape:
//
//   1. INSTALL (once): build this binary + a small manifest (function
//      addresses, resolved once at build time via `nm`) and push both to a
//      stable "app directory" on the device.
//   2. RUN (baseline): launch the app. No patch file present yet -> prints
//      ORIGINAL, exits. This is what users see before any patch ships.
//   3. PUSH PATCH: compile a NEW patch body to bytecode and push ONLY that
//      one small file into a separate "patches directory" — the installed
//      binary from step 1 is never touched again.
//   4. RESTART: launch the SAME installed binary again (no reinstall, no
//      rebuild). It notices the patch file is now present, loads it via the
//      VM's dynamic-module-as-closure extension, rewrites g()'s call site to
//      reach the interpreted replacement, and prints PATCHED.
//
// This mirrors the project's actual design (SPEC.md §5): the app decides at
// STARTUP whether to route each entry through baseline machine code or an
// interpreter stub, based on data (here: "does a patch file exist"), not by
// being recompiled. It is NOT a live/hot in-process code swap while running —
// per PRD.md §7 ("补丁需重启（冷启动）生效"), patches take effect on the next
// launch, matching what this demo does.
//
// 这份代码之前都是靠命令行参数驱动的 spike 骨架(字节码路径/快照路径/十六进制
// 地址每次跑都要显式传——适合单独验证"机制通不通"，但不像"真实部署会长什么样"。
// 这次把同一套已验证机制(V1 的 arm64 调用点改写 + VM 补丁的解释器加载)重新组织
// 成目标形态:
//
//   1. 安装(一次性)：编译这个二进制 + 一份小的清单(函数地址，构建期用 `nm`
//      算好一次)，把两者一起推到设备上一个稳定的"app 目录"。
//   2. 运行(基线)：启动 app。这时还没有补丁文件 -> 打印 ORIGINAL，退出。
//      这就是任何补丁上线前用户看到的样子。
//   3. 推送补丁：把新的补丁体编译成字节码，只推这一个小文件到独立的"补丁目录"
//      ——第 1 步安装的二进制不会再被碰。
//   4. 重启：再次启动**同一个**已安装的二进制(不重装、不重新编译)。它发现
//      补丁文件出现了，通过 VM 的"动态模块转闭包"扩展加载它，把 g() 的调用点
//      改写到解释执行的替换体，打印 PATCHED。
//
// 这正是对应项目实际设计(SPEC.md §5)：app 在**启动时**根据数据(这里是"补丁
// 文件存不存在")决定每个入口走基线机器码还是解释器 stub，而不是靠重新编译。
// 这不是"运行中原地热切换"——按 PRD.md §7("补丁需重启(冷启动)生效")，
// 补丁在下次启动时生效，和这个演示做的事完全一致。
library;

import 'dart:ffi';
import 'dart:io';
import 'dart:typed_data';
import 'dart:_internal' as internal;

/// Existing function a patch might replace.
/// 补丁可能要替换的既有函数。
@pragma('vm:never-inline')
String f() => 'ORIGINAL';

/// Existing caller — this call site is what gets redirected once a patch is
/// present, exactly like V1.
/// 既有调用方——补丁出现后，被重定向的正是这个调用点，和 V1 一样。
@pragma('vm:never-inline')
String g() => 'g() got: ${f()}';

Function? _cachedPatch;

@pragma('vm:entry-point')
@pragma('vm:never-inline')
String fAlt() => internal.invokeDynamicModuleClosure(_cachedPatch!) as String;

/// Fixed, "installed app" layout on the device. Real deployments would use
/// the platform's actual app-private storage; this demo uses a stable
/// /data/local/tmp path to stand in for it (see NOTES.md for why: no APK/
/// Flutter Engine integration in this repo yet — that is Gate 2 territory —
/// so a plain executable with a fixed data directory is the most honest
/// stand-in for "app that persists across restarts and can be patched").
///
/// 设备上固定的"已安装 app"目录布局。真实部署会用平台的 app 私有存储；
/// 这个演示用一个稳定的 /data/local/tmp 路径代替(为什么见 NOTES.md：这个仓库
/// 目前没有 APK/Flutter Engine 集成——那是 Gate 2 的范畴——所以用一个有固定
/// 数据目录、能跨重启存活的普通可执行文件，是对"可以被打补丁的 app"最诚实的替代)。
const _appDir = '/data/local/tmp/hotpatch_demo/app';
const _patchDir = '/data/local/tmp/hotpatch_demo/patches';
const _manifestPath = '$_appDir/manifest.txt';
const _patchBytecodePath = '$_patchDir/current.bytecode';
const _selfSnapshotName = 'app.snapshot'; // must match install.sh's push target

void main(List<String> args) {
  print('=== hotpatch_demo starting ===');
  print('BEFORE: ${g()}');

  final patchFile = File(_patchBytecodePath);
  if (!patchFile.existsSync()) {
    print('(no patch file at $_patchBytecodePath — running baseline, nothing to activate)');
    print('=== done (baseline) ===');
    return;
  }

  final activated = _tryActivatePatch(patchFile);
  if (!activated) {
    print('HOTPATCH INCONCLUSIVE: patch file present but activation failed');
    exit(3);
  }

  print('AFTER:  ${g()}');
  print('=== done (patch applied on this run) ===');
}

/// Same arm64 call-site-rewrite mechanism as V1/V3/V4/V5 (see
/// ../v1_replace_existing_function/host/main.dart for the full line-by-line
/// explanation of every step). The one structural difference: addresses
/// come from a manifest file written once at install time, not from CLI
/// args — because a restarted app doesn't get to renegotiate its own argv.
///
/// 和 V1/V3/V4/V5 同一套 arm64 调用点改写机制(每一步的完整解释见
/// ../v1_replace_existing_function/host/main.dart)。唯一的结构性差异：
/// 地址来自安装时写一次的清单文件，不是命令行参数——因为重启的 app
/// 没法重新和自己的 argv 谈条件。
bool _tryActivatePatch(File patchFile) {
  if (!File(_manifestPath).existsSync()) {
    print('  manifest not found at $_manifestPath (did install.sh run?)');
    return false;
  }
  final manifest = <String, int>{};
  for (final line in File(_manifestPath).readAsLinesSync()) {
    final parts = line.split('=');
    if (parts.length != 2) continue;
    manifest[parts[0].trim()] = int.parse(parts[1].trim(), radix: 16);
  }
  for (final required in ['g', 'f', 'fAlt']) {
    if (!manifest.containsKey(required)) {
      print('  manifest missing "$required": $manifest');
      return false;
    }
  }
  final gStatic = manifest['g']!;
  final fStatic = manifest['f']!;
  final fAltStatic = manifest['fAlt']!;

  final bytes = patchFile.readAsBytesSync();
  final loaded = internal.loadDynamicModuleClosure(bytes: bytes);
  if (loaded == null || loaded is! Function) {
    print('  loadDynamicModuleClosure returned $loaded (expected a Function)');
    return false;
  }
  _cachedPatch = loaded;
  print('  loaded patch bytecode from $_patchBytecodePath as a closure');

  final maps = File('/proc/self/maps').readAsStringSync();
  final mapRe = RegExp(
      r'^([0-9a-fA-F]+)-[0-9a-fA-F]+\s+r-xp\s+([0-9a-fA-F]+)\s+\S+\s+\d+\s+(.*)$',
      multiLine: true);
  int? loadBias;
  for (final m in mapRe.allMatches(maps)) {
    final path = m.group(3)!.trim();
    if (path.endsWith(_selfSnapshotName)) {
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
