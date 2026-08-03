library;

@pragma('vm:never-inline')
String greet() => 'ORIGINAL';

@pragma('vm:never-inline')
String greetPatched() => 'PATCHED';

late String Function() greetVar;

@pragma('vm:never-inline')
String callGreet() => greetVar();

@pragma('vm:external-name', 'Internal_redirectClosureEntryPoint')
external Object? _redirectClosureEntryPoint(Object target, Object replacement);

@pragma('vm:entry-point')
void setup(List args) {
  greetVar = greet;
  if (args.contains('--patch')) {
    _redirectClosureEntryPoint(greetVar, greetPatched);
  }
}

@pragma('vm:entry-point')
String getResult() => callGreet();

void main() {}
