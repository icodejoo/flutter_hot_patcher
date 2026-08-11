library;

@pragma('vm:entry-point')
@pragma('vm:never-inline')
String greet() => 'ORIGINAL';

@pragma('vm:entry-point')
@pragma('vm:never-inline')
String greetAlt() => 'ALT';

// --- AOT Dormant Variants (pre-compiled, activated by applyAOTPatch) ---

@pragma('vm:entry-point')
@pragma('vm:never-inline')
String greet_patched() => 'PATCHED_AOT';

@pragma('vm:entry-point')
@pragma('vm:never-inline')
String greet_cpu_aot() {
  int sum = 0;
  for (int i = 0; i < 10000; i++) {
    sum += i;
  }
  return sum > 0 ? 'PATCHED_CPU_AOT' : 'PATCHED_CPU_AOT';
}

// --- CHA-defeating indirection (same as M3) ---

@pragma('vm:entry-point')
late String Function() greetVar;

@pragma('vm:entry-point')
@pragma('vm:never-inline')
String callGreet() => greetVar();

@pragma('vm:entry-point')
void setup(List args) {
  greetVar = greetAlt;  // path 1: CHA sees this
  greetVar = greet;     // path 2: always taken
}

// --- AOT Patch Activation (pure pointer update, no bytecode loading) ---

@pragma('vm:entry-point')
void applyAOTPatch(List args) {
  final int variant = args.isNotEmpty ? (args[0] as int) : 0;
  greetVar = greetAlt;  // CHA defeat
  if (variant == 1) {
    greetVar = greet_patched;
  } else if (variant == 2) {
    greetVar = greet_cpu_aot;
  } else {
    greetVar = greet;  // restore original
  }
}

// --- Benchmark: call greetVar N times, return mean microseconds as string ---

@pragma('vm:entry-point')
String benchmarkGreet(List args) {
  final int n = args.isNotEmpty ? (args[0] as int) : 1000;
  // Warm up
  callGreet();
  final sw = Stopwatch()..start();
  for (int i = 0; i < n; i++) {
    callGreet();
  }
  sw.stop();
  final us = sw.elapsedMicroseconds / n;
  return us.toStringAsFixed(3);
}

@pragma('vm:entry-point')
String getResult() => callGreet();

void main() {}
