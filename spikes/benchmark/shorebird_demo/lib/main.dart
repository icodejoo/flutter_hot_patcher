import 'dart:convert';
import 'dart:ffi';
import 'package:ffi/ffi.dart';
import 'dart:io';
import 'package:flutter/material.dart';
import 'greet.dart';

// ─── FFI: getrusage ───────────────────────────────────────────────────────────
final class Timeval extends Struct {
  @Int64() external int tv_sec;
  @Int64() external int tv_usec;
}

final class Rusage extends Struct {
  external Timeval ru_utime;
  external Timeval ru_stime;
  @Array(14) external Array<Int64> padding;
}

typedef GetrusageFn = Int32 Function(Int32 who, Pointer<Rusage> usage);
typedef GetrusageDart = int Function(int who, Pointer<Rusage> usage);

final _lib = DynamicLibrary.process();
final _getrusage = _lib.lookupFunction<GetrusageFn, GetrusageDart>('getrusage');

int _rssKb() {
  if (Platform.isAndroid) {
    try {
      final status = File('/proc/self/status').readAsStringSync();
      final match = RegExp(r'VmRSS:\s+(\d+)').firstMatch(status);
      return match != null ? int.parse(match.group(1)!) : 0;
    } catch (_) { return 0; }
  }
  // iOS: getrusage maxrss is in bytes on Darwin
  // Use ProcessInfo.currentRss as fallback
  try {
    return ProcessInfo.currentRss ~/ 1024;
  } catch (_) { return 0; }
}

Duration _cpuUsed() {
  final r = calloc<Rusage>();
  _getrusage(0, r);
  final us = r.ref.ru_utime.tv_sec * 1000000 + r.ref.ru_utime.tv_usec +
              r.ref.ru_stime.tv_sec * 1000000 + r.ref.ru_stime.tv_usec;
  calloc.free(r);
  return Duration(microseconds: us);
}

double _cpuPercent(Duration elapsed, Duration cpuUsed) {
  if (elapsed.inMicroseconds == 0) return 0;
  return cpuUsed.inMicroseconds / elapsed.inMicroseconds * 100.0;
}

// ─── Main ─────────────────────────────────────────────────────────────────────
void main() async {
  WidgetsFlutterBinding.ensureInitialized();
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
    final coldStart = Stopwatch()..start();
    final patchSizeBytes = _readPatchSize();
    final patchType = _readPatchType();

    greet(); // warm up
    coldStart.stop();

    // 1000-call latency benchmark
    final sw = Stopwatch()..start();
    for (int i = 0; i < 1000; i++) greet();
    sw.stop();
    final greetCallUs = sw.elapsedMicroseconds ~/ 1000;

    final rssKb = _rssKb();

    double cpuPeak = 0.0;
    if (patchType == 'cpu') {
      final samples = <double>[];
      for (int s = 0; s < 10; s++) {
        final t0 = DateTime.now();
        final c0 = _cpuUsed();
        greet(); // trigger the CPU work
        await Future.delayed(const Duration(milliseconds: 100));
        final t1 = DateTime.now();
        final c1 = _cpuUsed();
        samples.add(_cpuPercent(t1.difference(t0), c1 - c0));
      }
      cpuPeak = samples.reduce((a, b) => a > b ? a : b);
    }

    final result = {
      'variant': 'shorebird',
      'platform': Platform.isIOS ? 'ios' : 'android',
      'patch_type': patchType,
      'patch_size_bytes': patchSizeBytes,
      'cold_start_ms': coldStart.elapsedMilliseconds,
      'greet_call_us': greetCallUs,
      'memory_rss_kb': rssKb,
      'cpu_percent_peak': double.parse(cpuPeak.toStringAsFixed(1)),
    };

    await _writeResult(result);

    setState(() {
      _status = 'Done\n${greet()}\ncold=${result['cold_start_ms']}ms '
                'greet=${result['greet_call_us']}μs\n'
                'rss=${result['memory_rss_kb']}KB cpu=${result['cpu_percent_peak']}%';
    });
  }

  int _readPatchSize() {
    try {
      return int.parse(File('${_docsDir()}/patch_size.txt').readAsStringSync().trim());
    } catch (_) { return 0; }
  }

  String _readPatchType() {
    try {
      return File('${_docsDir()}/patch_type.txt').readAsStringSync().trim();
    } catch (_) { return 'none'; }
  }

  String _docsDir() {
    if (Platform.isIOS) {
      final home = Platform.environment['HOME'] ?? '';
      return '$home/Documents';
    }
    return '/sdcard/Android/data/com.hotpatch.bench.shorebird_demo/files';
  }

  Future<void> _writeResult(Map<String, dynamic> result) async {
    final file = File('${_docsDir()}/benchmark.json');
    await file.writeAsString(jsonEncode(result));
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      home: Scaffold(
        body: Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Text(_status, textAlign: TextAlign.center,
                style: const TextStyle(fontFamily: 'monospace', fontSize: 14)),
          ),
        ),
      ),
    );
  }
}
