library;

@pragma('vm:never-inline')
String greet() => 'ORIGINAL';

@pragma('vm:never-inline')
String greetAlt() => 'ALT';

late String Function() greetVar;

@pragma('vm:never-inline')
String callGreet() => greetVar();

@pragma('vm:external-name', 'Internal_loadDynamicModuleClosure')
external Object? _loadDynamicModuleClosure(Object bytes);

@pragma('vm:external-name', 'Internal_invokeDynamicModuleClosure')
external Object? _invokeDynamicModuleClosure(Object closure);

Object? _patchClosure;

@pragma('vm:entry-point')
void setup(List args) {
  greetVar = args.contains('--alt') ? greetAlt : greet;
}

@pragma('vm:entry-point')
void applyPatch(Object bytes) {
  _patchClosure = _loadDynamicModuleClosure(bytes);
}

@pragma('vm:entry-point')
String getResult() {
  if (_patchClosure != null) {
    return _invokeDynamicModuleClosure(_patchClosure!) as String;
  }
  return callGreet();
}

void main() {}
