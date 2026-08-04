library hotpatch_validation.t05;

@pragma('vm:entry-point') @pragma('vm:never-inline')
String fn_toplevel() => 'patched';  // T26

@pragma('vm:entry-point') @pragma('vm:never-inline')
int fn_anonymous() {
  late int Function() f;
  f = () => 99;
  return f();
}  // T27: 99

@pragma('vm:entry-point') @pragma('vm:never-inline')
int fn_closure_capture() {
  int multiplier = 3;
  int Function(int) multiply = (x) => x * multiplier;
  return multiply(5);
}  // T28: multiplier 3

@pragma('vm:entry-point') @pragma('vm:never-inline')
String fn_named_param() => _named(name: 'World');  // T29 — same call
String _named({String name = 'World'}) => 'Hi, $name!';  // changed greeting

@pragma('vm:entry-point') @pragma('vm:never-inline')
int fn_optional_param() => _optional(0);  // T30 — same call
int _optional([int x = 0]) => x + 20;    // +20

@pragma('vm:entry-point') @pragma('vm:never-inline')
int fn_higher_order() {
  int Function(int) tripleIt = (x) => x * 3;
  return tripleIt(tripleIt(3));
}  // T31: triple

@pragma('vm:entry-point') @pragma('vm:never-inline')
String fn_transform() => [1, 2, 3].map((x) => x + 100).toList().toString();  // T32: +100

@pragma('vm:entry-point') @pragma('vm:never-inline')
String fn_async_label() => 'async_patched';  // T33

@pragma('vm:entry-point') @pragma('vm:never-inline')
String fn_generator() => _gen().toList().toString();  // T34
Iterable<int> _gen() sync* { yield 10; yield 20; yield 30; }  // ×10
