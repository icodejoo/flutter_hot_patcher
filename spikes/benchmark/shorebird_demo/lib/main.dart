import 'dart:convert';
import 'dart:ffi';
import 'dart:io';
import 'package:ffi/ffi.dart';
import 'package:flutter/material.dart';
import 'package:path_provider/path_provider.dart';
import 'greet.dart';

// ─── FFI: getrusage (Darwin) ──────────────────────────────────────────────────
// On Darwin: tv_sec = int64, tv_usec = int32 (suseconds_t)
final class Timeval extends Struct {
  @Int64() external int tv_sec;
  @Int32() external int tv_usec;
  @Int32() external int _pad;
}

final class Rusage extends Struct {
  external Timeval ru_utime;
  external Timeval ru_stime;
  @Array(14) external Array<Int64> rest;
}

typedef GetrusageFn = Int32 Function(Int32 who, Pointer<Rusage> usage);
typedef GetrusageDart = int Function(int who, Pointer<Rusage> usage);

late final GetrusageDart _getrusage;
bool _ffiOk = false;

void _initFfi() {
  try {
    _getrusage = DynamicLibrary.process()
        .lookupFunction<GetrusageFn, GetrusageDart>('getrusage');
    _ffiOk = true;
  } catch (_) {}
}

int _rssKb() {
  try {
    if (Platform.isAndroid) {
      final status = File('/proc/self/status').readAsStringSync();
      final match = RegExp(r'VmRSS:\s+(\d+)').firstMatch(status);
      return match != null ? int.parse(match.group(1)!) : 0;
    }
    return ProcessInfo.currentRss ~/ 1024;
  } catch (_) { return 0; }
}

Duration _cpuUsed() {
  if (!_ffiOk) return Duration.zero;
  try {
    final r = calloc<Rusage>();
    _getrusage(0, r);
    final us = r.ref.ru_utime.tv_sec * 1000000 + r.ref.ru_utime.tv_usec +
               r.ref.ru_stime.tv_sec * 1000000 + r.ref.ru_stime.tv_usec;
    calloc.free(r);
    return Duration(microseconds: us);
  } catch (_) { return Duration.zero; }
}

double _cpuPercent(Duration elapsed, Duration cpuUsed) {
  if (elapsed.inMicroseconds == 0) return 0;
  return cpuUsed.inMicroseconds / elapsed.inMicroseconds * 100.0;
}

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  _initFfi();
  runApp(const BenchApp());
}

class BenchApp extends StatefulWidget {
  const BenchApp({super.key});
  @override
  State<BenchApp> createState() => _BenchAppState();
}

class _BenchAppState extends State<BenchApp> {
  String _status = 'Running benchmark...';

  @override
  void initState() {
    super.initState();
    _run();
  }

  Future<void> _run() async {
    String docsDir = '';
    try {
      docsDir = await _docsDir();
    } catch (e) {
      setState(() { _status = 'DOCS_ERR: $e'; });
      return;
    }
    // Write heartbeat to verify app is running
    try { 
      await File('$docsDir/heartbeat.txt').writeAsString('alive'); 
    } catch (_) {}
    
    // Debug: step tracking
    Future<void> dbg(String step) async {
      try { await File('$docsDir/debug_step.txt').writeAsString(step); } catch (_) {}
    }
    final coldStart = Stopwatch()..start();

    await dbg('reading_meta');
    final patchSizeBytes = _readFile('$docsDir/patch_size.txt', '0');
    final patchType = _readFile('$docsDir/patch_type.txt', 'none');

    await dbg('greet_warmup');
    greet();
    coldStart.stop();
    await dbg('greet_loop_start');

    final int greetIter = patchType == 'cpu' ? 10 : 1000;
    final sw = Stopwatch()..start();
    for (int i = 0; i < greetIter; i++) greet();
    sw.stop();
    final greetCallUs = sw.elapsedMicroseconds / greetIter.toDouble();

    await dbg('rss_measurement');
    final rssKb = _rssKb();

    await dbg('cpu_measurement');
    double cpuPeak = 0.0;
    if (patchType == 'cpu') {
      // Synchronous CPU measurement: run cpu-heavy greet() 100 times,
      // measure wall time vs CPU time (no Future.delayed - avoids iOS background throttle)
      final wallSw = Stopwatch()..start();
      final cpuBefore = _cpuUsed();
      for (int i = 0; i < 100; i++) greet();
      wallSw.stop();
      final cpuAfter = _cpuUsed();
      cpuPeak = _cpuPercent(
        Duration(microseconds: wallSw.elapsedMicroseconds),
        cpuAfter - cpuBefore,
      );
    }

    final result = {
      'variant': 'shorebird',
      'platform': Platform.isIOS ? 'ios' : 'android',
      'patch_type': patchType,
      'patch_size_bytes': int.tryParse(patchSizeBytes.trim()) ?? 0,
      'cold_start_ms': coldStart.elapsedMicroseconds / 1000.0,
      'greet_call_us': double.parse(greetCallUs.toStringAsFixed(2)),
      'memory_rss_kb': rssKb,
      'cpu_percent_peak': double.parse(cpuPeak.toStringAsFixed(1)),
    };

    await dbg('writing_json');
    try {
      await File('$docsDir/benchmark.json').writeAsString(jsonEncode(result));
    } catch (e) {
      setState(() { _status = 'ERROR writing JSON: $e'; });
      return;
    }

    setState(() {
      _status = 'Done: ${greet()}\n'
          'cold=${result['cold_start_ms']}ms '
          'greet=${result['greet_call_us']}μs\n'
          'rss=${result['memory_rss_kb']}KB '
          'cpu=${result['cpu_percent_peak']}%\n'
          'patch=$patchType';
    });
  }

  String _readFile(String path, String defaultVal) {
    try { return File(path).readAsStringSync(); }
    catch (_) { return defaultVal; }
  }

  Future<String> _docsDir() async {
    if (Platform.isAndroid) {
      final dir = await getExternalStorageDirectory();
      return dir?.path ??
          '/sdcard/Android/data/com.hotpatch.bench.shorebird_demo/files';
    }
    final dir = await getApplicationDocumentsDirectory();
    return dir.path;
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      home: Scaffold(
        body: Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Text(_status,
                textAlign: TextAlign.center,
                style: const TextStyle(fontFamily: 'monospace', fontSize: 14)),
          ),
        ),
      ),
    );
  }
}
