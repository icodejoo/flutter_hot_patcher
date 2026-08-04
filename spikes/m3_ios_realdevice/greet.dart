library;

import 'dart:typed_data';

@pragma('vm:never-inline')
String greet() => 'ORIGINAL';

@pragma('vm:never-inline')
String greetAlt() => 'ALT';

late String Function() greetVar;

@pragma('vm:never-inline')
String callGreet() => greetVar();

@pragma('vm:external-name', 'Internal_redirectClosureEntryPoint')
external Object? _redirectClosureEntryPoint(Object target, Object replacement);

@pragma('vm:external-name', 'Internal_loadDynamicModuleClosure')
external Object? _loadDynamicModuleClosure(Uint8List bytes);

@pragma('vm:entry-point')
void setup(List args) {
  greetVar = args.contains('--alt') ? greetAlt : greet;
}

@pragma('vm:entry-point')
void applyPatch(Uint8List bytes) {
  final fn = _loadDynamicModuleClosure(bytes);
  if (fn != null) _redirectClosureEntryPoint(greetVar, fn);
}

@pragma('vm:entry-point')
String getResult() => callGreet();

void main() {}
