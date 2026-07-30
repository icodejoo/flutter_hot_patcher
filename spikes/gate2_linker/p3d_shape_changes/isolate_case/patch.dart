// Completeness case: Isolate.spawn entry point. `isolateMain` is a top-level
// function passed BY REFERENCE (tear-off, cross-isolate-boundary) to
// Isolate.spawn — a different invocation mechanism than a direct call. It
// directly calls `helper`. Patch changes `helper`'s body only (isolateMain's
// own source unchanged) — verifies isolateMain, reached via Isolate.spawn's
// entry mechanism, still cascades correctly as helper's direct caller.
library;

import 'dart:io';
import 'dart:isolate';

@pragma('vm:never-inline')
int helper(int x) => x * 2 + 2;

@pragma('vm:entry-point')
void isolateMain(List<Object> args) {
  final sendPort = args[0] as SendPort;
  final n = args[1] as int;
  sendPort.send(helper(n)); // direct call to helper from inside the entry fn
}

@pragma('vm:never-inline')
int unrelatedIsolate(int n) => n * 8 + 6; // expect equivalent

void main(List<String> args) async {
  final n = args.length;
  final receivePort = ReceivePort();
  await Isolate.spawn(isolateMain, [receivePort.sendPort, n]);
  final result = await receivePort.first as int;
  stdout.writeln(result + unrelatedIsolate(n));
}
