import 'package:flutter/material.dart';

/// A/B 性能对比用。与历史数据同函数：10K 迭代累加
/// （spikes/benchmark/hotpatch_demo/patches/greet_cpu.dart），
/// 以便与 Shorebird 806.7µs / A-route 156.4µs 直接可比。
@pragma('vm:never-inline')
int hotLoop() {
  int sum = 0;
  for (int i = 0; i < 10001; i++) {  // 10001 而非 10000：确保 hash 变化、不被 link 回原生
    sum += i;
  }
  return sum;
}

String variantLabel() => 'PATCHED';

void main() => runApp(const BenchApp());

class BenchApp extends StatefulWidget {
  const BenchApp({super.key});
  @override
  State<BenchApp> createState() => _BenchAppState();
}

class _BenchAppState extends State<BenchApp> {
  String _result = '测量中…';

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _measure());
  }

  void _measure() {
    // 预热，避免把首次进入解释器的开销算进去
    for (int i = 0; i < 50; i++) {
      hotLoop();
    }
    const iterations = 1000;
    final sw = Stopwatch()..start();
    for (int i = 0; i < iterations; i++) {
      hotLoop();
    }
    sw.stop();
    final nsPerCall = sw.elapsedMicroseconds * 1000 / iterations;
    setState(() {
      _result = '${variantLabel()}\n'
          '${nsPerCall.toStringAsFixed(0)} ns/call\n'
          '(${(nsPerCall / 1000).toStringAsFixed(1)} µs)';
    });
    debugPrint('BENCH ${variantLabel()} ${nsPerCall.toStringAsFixed(0)} ns/call');
  }

  @override
  Widget build(BuildContext context) => MaterialApp(
        home: Scaffold(
          body: Center(
            child: Text(_result,
                textAlign: TextAlign.center,
                style: const TextStyle(
                    fontSize: 22, fontWeight: FontWeight.bold)),
          ),
        ),
      );
}
