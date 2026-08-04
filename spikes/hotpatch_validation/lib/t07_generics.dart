library hotpatch_validation.t07;

T _identity<T>(T x) => x;
@pragma('vm:entry-point') @pragma('vm:never-inline')
String generic_fn() => _identity('hello');  // T43

class Box<T> {
  final T _value;
  Box(this._value);
  @pragma('vm:entry-point') @pragma('vm:never-inline')
  T get value => _value;
}
@pragma('vm:entry-point') @pragma('vm:never-inline')
int generic_class() => Box<int>(42).value;  // T44

T _add<T extends num>(T a, T b) => (a + b) as T;
@pragma('vm:entry-point') @pragma('vm:never-inline')
num generic_constraint() => _add(3, 4);  // T45

List<T> _reverse<T>(List<T> input) => input.reversed.toList();
@pragma('vm:entry-point') @pragma('vm:never-inline')
String generic_list() => _reverse([1, 2, 3]).toString();  // T46
