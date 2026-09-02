// B5 device test: verify C6 fix — BLR dispatch survives HasScheduledInterrupts
//
// C6 removed a `break` in simulator_arm64.cc:DecodeUnconditionalBranchReg that
// silently skipped BLR (indirect register call) dispatch when HasScheduledInterrupts().
// This app exercises that path:
//   1. Allocates objects to trigger GC → HasScheduledInterrupts becomes true
//   2. Calls functions via typed closures → BLR dispatch in Shorebird simulator
//   3. Shows PASS/FAIL on screen
//
// ⚠️  REQUIREMENT: Flutter.framework MUST be built with dart_force_simulator=true
//     Without it, Dart runs on real ARM64 CPU (not simulator), and C6 is not exercised.
//     See: tools/b5_device_test/gn_add_dart_force_simulator.sh

import 'dart:async';
import 'package:flutter/material.dart';

// Function types that force BLR (indirect register) dispatch in the simulator
typedef IntBinaryFn = int Function(int, int);
typedef StringFromInt = String Function(int);

int addFn(int a, int b) => a + b;
int mulFn(int a, int b) => a * b;
String itoaFn(int n) => n.toString();

Future<(bool, String)> runB5Test() async {
  const int iterations = 20000;
  final List<Object> gcPressure = [];

  // Keep in typed variables → forces BLR dispatch in simulator
  final IntBinaryFn fnAdd = addFn;
  final IntBinaryFn fnMul = mulFn;
  final StringFromInt fnStr = itoaFn;

  int addErrors = 0;
  int mulErrors = 0;
  int strErrors = 0;

  for (int i = 0; i < iterations; i++) {
    // GC pressure every 50 iterations → triggers HasScheduledInterrupts
    if (i % 50 == 0) {
      for (int j = 0; j < 500; j++) {
        gcPressure.add(List<int>.filled(64, j));
      }
      // Yield to avoid blocking UI thread
      if (i % 1000 == 0) await Future.delayed(Duration.zero);
    }

    final int addResult = fnAdd(i, i + 1);
    if (addResult != 2 * i + 1) addErrors++;

    final int mulResult = fnMul(i, 3);
    if (mulResult != i * 3) mulErrors++;

    final String strResult = fnStr(i);
    if (strResult != '$i') strErrors++;
  }

  final bool pass = addErrors == 0 && mulErrors == 0 && strErrors == 0;
  final String msg = pass
      ? 'PASS ✅\n'
          '$iterations iterations, ${gcPressure.length} GC objects\n'
          'All BLR dispatches correct under GC pressure'
      : 'FAIL ❌\n'
          'add=$addErrors mul=$mulErrors str=$strErrors errors\n'
          'BLR dispatch produced incorrect results (C6 bug?)';
  return (pass, msg);
}

void main() => runApp(const B5TestApp());

class B5TestApp extends StatefulWidget {
  const B5TestApp({super.key});
  @override
  State<B5TestApp> createState() => _B5TestAppState();
}

class _B5TestAppState extends State<B5TestApp> {
  String _status = 'Tap RUN to start B5 test';
  Color _color = Colors.grey;
  bool _running = false;

  Future<void> _runTest() async {
    setState(() {
      _status = 'Running… (${20000} iterations + GC pressure)';
      _color = Colors.blue;
      _running = true;
    });

    final (bool pass, String msg) = await runB5Test();

    setState(() {
      _status = msg;
      _color = pass ? Colors.green : Colors.red;
      _running = false;
    });
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'B5 Device Test',
      home: Scaffold(
        appBar: AppBar(
          title: const Text('B5: C6 BLR Dispatch Test'),
          backgroundColor: Colors.blueGrey,
          foregroundColor: Colors.white,
        ),
        body: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Text(
                '⚠️ Flutter.framework must be built with\ndart_force_simulator=true\nfor this test to exercise C6.',
                style: TextStyle(fontSize: 13, color: Colors.orange),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 24),
              Expanded(
                child: Container(
                  decoration: BoxDecoration(
                    color: _color.withOpacity(0.1),
                    border: Border.all(color: _color, width: 2),
                    borderRadius: BorderRadius.circular(12),
                  ),
                  padding: const EdgeInsets.all(16),
                  child: Center(
                    child: Text(
                      _status,
                      style: TextStyle(fontSize: 18, color: _color, fontWeight: FontWeight.bold),
                      textAlign: TextAlign.center,
                    ),
                  ),
                ),
              ),
              const SizedBox(height: 24),
              ElevatedButton(
                onPressed: _running ? null : _runTest,
                style: ElevatedButton.styleFrom(
                  padding: const EdgeInsets.symmetric(vertical: 16),
                  backgroundColor: Colors.blueGrey,
                  foregroundColor: Colors.white,
                ),
                child: Text(_running ? 'Running…' : 'RUN B5 TEST', style: const TextStyle(fontSize: 18)),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
