library hotpatch_validation.t05;

@pragma('vm:entry-point') @pragma('vm:never-inline')
String fn_toplevel() => 'baseline';  // T26

@pragma('vm:entry-point') @pragma('vm:never-inline')
int fn_anonymous() {
  late int Function() f;
  f = () => 42;
  return f();
}  // T27

@pragma('vm:entry-point') @pragma('vm:never-inline')
int fn_closure_capture() {
  int multiplier = 2;
  int Function(int) multiply = (x) => x * multiplier;
  return multiply(5);
}  // T28

@pragma('vm:entry-point') @pragma('vm:never-inline')
String fn_named_param() => _named(name: 'World');  // T29
String _named({String name = 'World'}) => 'Hello, $name!';

@pragma('vm:entry-point') @pragma('vm:never-inline')
int fn_optional_param() => _optional(0);  // T30
int _optional([int x = 0]) => x + 10;

@pragma('vm:entry-point') @pragma('vm:never-inline')
int fn_higher_order() {
  int Function(int) doubleIt = (x) => x * 2;
  return doubleIt(doubleIt(3));
}  // T31

@pragma('vm:entry-point') @pragma('vm:never-inline')
String fn_transform() => [1, 2, 3].map((x) => x + 10).toList().toString();  // T32

@pragma('vm:entry-point') @pragma('vm:never-inline')
String fn_async_label() => 'async_baseline';  // T33 (sync proxy)

@pragma('vm:entry-point') @pragma('vm:never-inline')
String fn_generator() => _gen().toList().toString();  // T34
Iterable<int> _gen() sync* { yield 1; yield 2; yield 3; }
