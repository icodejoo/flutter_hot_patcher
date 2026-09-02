// B5 device test: verify C6 fix — BLR dispatch survives HasScheduledInterrupts
//
// C6 removed a `break` in simulator_arm64.cc:DecodeUnconditionalBranchReg that
// silently skipped BLR (indirect register call) dispatch when the Dart thread had
// pending interrupts (e.g. GC safepoint request). This test exercises that path:
//   - Allocates objects to trigger GC (→ HasScheduledInterrupts becomes true)
//   - Makes indirect calls via function pointers (→ BLR dispatch in simulator)
//   - Verifies ALL calls return correct results
//
// REQUIREMENT: Flutter.framework must be built with dart_force_simulator=true
// so that ALL Dart runs through the simulator (not just patched functions).
// Without that flag, Dart AOT runs on the real CPU and this test is a no-op.
// See: gn_add_dart_force_simulator.sh

import 'dart:io';

// Function pointers → stored in variables → BLR dispatch in simulator
typedef IntBinaryFn = int Function(int, int);
typedef StringFromInt = String Function(int);

int add(int a, int b) => a + b;
int multiply(int a, int b) => a * b;
String itoa(int n) => n.toString();

void main() {
  print('B5 device test starting...');
  print('(Requires dart_force_simulator=true in Flutter.framework for C6 to be exercised)');

  final List<Object> gcPressure = [];

  // Keep references to functions via typed variables → forces BLR dispatch
  final IntBinaryFn fnAdd = add;
  final IntBinaryFn fnMul = multiply;
  final StringFromInt fnStr = itoa;

  int addErrors = 0;
  int mulErrors = 0;
  int strErrors = 0;

  const int iterations = 20000;

  for (int i = 0; i < iterations; i++) {
    // Trigger GC pressure every 50 iterations
    if (i % 50 == 0) {
      for (int j = 0; j < 500; j++) {
        gcPressure.add(List<int>.filled(64, j)); // 512-byte allocations
      }
    }

    // BLR dispatch: add
    final int addResult = fnAdd(i, i + 1);
    final int addExpected = 2 * i + 1;
    if (addResult != addExpected) addErrors++;

    // BLR dispatch: multiply
    final int mulResult = fnMul(i, 3);
    final int mulExpected = i * 3;
    if (mulResult != mulExpected) mulErrors++;

    // BLR dispatch: string conversion (triggers more allocation)
    final String strResult = fnStr(i);
    if (strResult != '$i') strErrors++;
  }

  final bool pass = addErrors == 0 && mulErrors == 0 && strErrors == 0;

  print('');
  print('=== B5 RESULT ===');
  print('Iterations: $iterations');
  print('GC objects allocated: ${gcPressure.length}');
  print('add errors:    $addErrors');
  print('mul errors:    $mulErrors');
  print('string errors: $strErrors');
  print('');
  if (pass) {
    print('PASS: BLR dispatch correct under GC pressure — C6 fix holds');
    exit(0);
  } else {
    print('FAIL: BLR dispatch produced incorrect results — C6 bug present');
    exit(1);
  }
}
