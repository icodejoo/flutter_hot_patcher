// Completeness case: change inside an async body. `compute` is async -> lowered
// to a state machine (synthetic closure/continuation symbols). Changing its
// return value must be caught SOMEWHERE in the closure (the state-machine
// symbol), and `caller` (awaits compute) should be handled correctly. Probes
// whether async lowering hides the change from the diff-linker.
library;

import 'dart:async';
import 'dart:io';

@pragma('vm:never-inline')
Future<int> compute(int x) async {
  await Future<void>.delayed(Duration.zero);
  return x + 1; // patch: +1 -> +2
}

@pragma('vm:never-inline')
Future<int> caller(int x) async => (await compute(x)) + 100;

void main(List<String> args) async {
  final n = args.length;
  stdout.writeln(await caller(n));
}
