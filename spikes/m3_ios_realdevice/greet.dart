library;

import 'dart:_internal' as internal;

@pragma('vm:never-inline')
String greet() => 'ORIGINAL';

@pragma('vm:never-inline')
String greetPatched() => 'PATCHED';

late String Function() greetVar;

@pragma('vm:never-inline')
String callGreet() => greetVar();

@pragma('vm:entry-point')
void setup(List args) {  /* List<dynamic>: Dart_NewList returns untyped List */
  greetVar = greet;
  if (args.contains('--patch')) {
    internal.redirectClosureEntryPoint(greetVar, greetPatched);
  }
}

@pragma('vm:entry-point')
String getResult() => callGreet();
