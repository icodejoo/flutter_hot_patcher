// Multi-function patch.
//
// dart2bytecode enforces exactly ONE @pragma('dyn-module:entry-point') per
// module, and it must be a static, non-generic, no-argument method
// (bytecode_generator.dart:657-668). The return type is unconstrained, so a
// patch exposes many functions by returning a map of closures: the arity
// restriction applies to the entry point, not to what it hands back.
library;

String _greet() => 'MULTI_GREET';

int _addNumbers(int a, int b) => a + b;

String _describe(int n) {
  if (n < 0) return 'negative';
  if (n == 0) return 'zero';
  return 'positive:$n';
}

// Not exported: reachable only from the closures above.
String _internal() => 'internal';

@pragma('dyn-module:entry-point')
Map<String, Function> patchEntry() => {
      'greet': _greet,
      'addNumbers': _addNumbers,
      'describe': _describe,
    };
