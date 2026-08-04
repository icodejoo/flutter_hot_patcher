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

// setup() initializes greetVar with two possible paths to prevent CHA devirtualization
@pragma('vm:entry-point')
void setup(List args) {
  greetVar = greetAlt; // path 1: CHA sees this
  greetVar = greet;    // path 2: always taken, CHA cannot devirt
}

@pragma('vm:entry-point')
String getResult() => callGreet();

void main() {}
