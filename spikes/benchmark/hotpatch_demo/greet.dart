library;

@pragma('vm:entry-point')
@pragma('vm:never-inline')
String greet() => 'ORIGINAL';

@pragma('vm:entry-point')
@pragma('vm:never-inline')
String greetAlt() => 'ALT';

@pragma('vm:entry-point')
late String Function() greetVar;

@pragma('vm:entry-point')
@pragma('vm:never-inline')
String callGreet() => greetVar();

@pragma('vm:entry-point')
void setup(List args) {
  greetVar = greetAlt;
  greetVar = greet;
}

@pragma('vm:entry-point')
String getResult() => callGreet();

void main() {}
