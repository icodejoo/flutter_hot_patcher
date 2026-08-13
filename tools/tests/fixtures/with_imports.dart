// Patch exercising cross-library imports.
//
// Verifies that dart:* libraries resolve at bytecode-compile time and that the
// referenced members survive into the module, rather than being silently
// dropped. Uses the single map-of-closures entry point required by
// dart2bytecode (see multi_function.dart for why).
library;

import 'dart:convert';
import 'dart:math' as math;

String _greet() {
  final values = <int>[3, 1, 4, 1, 5, 9, 2, 6];
  values.sort();
  final maxValue = values.reduce(math.max);
  return 'IMPORTS_OK max=$maxValue sorted=${values.join(",")}';
}

String _encodeState(int counter) {
  return jsonEncode({
    'counter': counter,
    'sqrt2': math.sqrt(2).toStringAsFixed(3),
  });
}

@pragma('dyn-module:entry-point')
Map<String, Function> patchEntry() => {
      'greet': _greet,
      'encodeState': _encodeState,
    };
