library hotpatch_validation.t07;

T _identity<T>(T x) => x;
@pragma('vm:entry-point') @pragma('vm:never-inline')
String generic_fn() => _identity('world');  // T43: 'world'

class Box<T> {
  final T _value;
  Box(this._value);
  @pragma('vm:entry-point') @pragma('vm:never-inline')
  T get value => _value;
}
@pragma('vm:entry-point') @pragma('vm:never-inline')
int generic_class() => Box<int>(99).value;  // T44: 99

T _add<T extends num>(T a, T b) => (a + b) as T;
@pragma('vm:entry-point') @pragma('vm:never-inline')
num generic_constraint() => _add(10, 20);  // T45: 30

List<T> _reverse<T>(List<T> input) => input.toList();  // T46: no reverse
@pragma('vm:entry-point') @pragma('vm:never-inline')
String generic_list() => _reverse([1, 2, 3]).toString();
void main() {}
