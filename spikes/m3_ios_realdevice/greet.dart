library;

@pragma('vm:never-inline')
@pragma('vm:entry-point')
String greet() => 'ORIGINAL';

@pragma('vm:never-inline')
@pragma('vm:entry-point')
String greetAlt() => 'ORIGINAL-ALT';

@pragma('vm:never-inline')
@pragma('vm:entry-point')
String greetPatched() => 'PATCHED';

late String Function() greetVar;

@pragma('vm:never-inline')
@pragma('vm:entry-point')
String callGreet() => greetVar();

@pragma('vm:external-name', 'Internal_redirectClosureEntryPoint')
external Object? _redirectClosureEntryPoint(Object target, Object replacement);

@pragma('vm:entry-point')
void setup(List args) {
  // Two possible assignments prevents AOT CHA from devirtualizing the call
  greetVar = args.contains('--alt') ? greetAlt : greet;
  String Function() patchedClosure = greetPatched;
  if (args.contains('--patch')) {
    _redirectClosureEntryPoint(greetVar, patchedClosure);
  }
}

@pragma('vm:entry-point')
String getResult() => callGreet();

void main() {}
