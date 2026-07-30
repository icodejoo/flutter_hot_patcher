// Completeness case: raw Stream/StreamController subscription (distinct from
// the already-tested async* generator lowering — this is StreamController.add()
// firing a registered .listen() callback, a different codegen/registration
// path). Change lands inside the listen callback body. Verifies the callback
// closure is caught and the driver (which sets up the controller + listen +
// pumps values) cascades correctly.
library;

import 'dart:async';
import 'dart:io';

@pragma('vm:never-inline')
int transform(int v) => v * 2 + 2;

@pragma('vm:never-inline')
Future<int> pumpStream(int n) {
  final controller = StreamController<int>();
  final completer = Completer<int>();
  var total = 0;
  controller.stream.listen(
    (v) => total += transform(v), // callback body calls transform directly
    onDone: () => completer.complete(total),
  );
  for (var i = 0; i < 3; i++) {
    controller.add(n + i);
  }
  controller.close();
  return completer.future;
}

@pragma('vm:never-inline')
int unrelatedStream(int n) => n * 7 + 2; // expect equivalent

void main(List<String> args) async {
  final n = args.length;
  final s = await pumpStream(n);
  stdout.writeln(s + unrelatedStream(n));
}
