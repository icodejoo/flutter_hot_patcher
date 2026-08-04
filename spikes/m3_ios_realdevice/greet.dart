library;

@pragma('vm:never-inline')
String greet() => 'ORIGINAL';

// greetAlt prevents CHA devirtualization of greetVar (AOT would otherwise inline greet() directly)
@pragma('vm:never-inline')
String greetAlt() => 'ALT';

late String Function() greetVar;

@pragma('vm:never-inline')
String callGreet() => greetVar();

@pragma('vm:external-name', 'Internal_redirectClosureEntryPoint')
external Object? _redirectClosureEntryPoint(Object target, Object replacement);

@pragma('vm:entry-point')
void setup(List args) {
  greetVar = args.contains('--alt') ? greetAlt : greet;
}

@pragma('vm:entry-point')
void redirectToPatch(Object patchFn) {
  _redirectClosureEntryPoint(greetVar, patchFn);
}

@pragma('vm:entry-point')
String getResult() => callGreet();

void main() {}
