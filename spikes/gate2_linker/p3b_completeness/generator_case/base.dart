// Completeness case: sync*/async* generator bodies. Like async (already PASS,
// see ../async_case/NOTES), generator functions lower to a state machine with
// synthetic closures. Probes whether a change to the YIELDED value inside a
// sync*/async* body is caught, and whether the caller (which drains the
// Iterable/Stream) cascades correctly.
library;

import 'dart:async';
import 'dart:io';

@pragma('vm:never-inline')
Iterable<int> syncGen(int x) sync* {
  yield x + 1; // patch: +1 -> +2
  yield x + 10;
}

@pragma('vm:never-inline')
Stream<int> asyncGen(int x) async* {
  yield x + 1; // patch: +1 -> +2
  await Future<void>.delayed(Duration.zero);
  yield x + 20;
}

@pragma('vm:never-inline')
int sumSync(int x) => syncGen(x).fold(0, (a, b) => a + b);

@pragma('vm:never-inline')
Future<int> sumAsync(int x) async {
  var total = 0;
  await for (final v in asyncGen(x)) {
    total += v;
  }
  return total;
}

void main(List<String> args) async {
  final n = args.length;
  final s = sumSync(n);
  final a = await sumAsync(n);
  stdout.writeln(s + a);
}
