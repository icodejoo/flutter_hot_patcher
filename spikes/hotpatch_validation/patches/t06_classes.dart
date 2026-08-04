library hotpatch_validation.t06;

class Calculator {
  @pragma('vm:entry-point') @pragma('vm:never-inline')
  int add(int a, int b) => a - b;  // T35: subtraction
}
@pragma('vm:entry-point') @pragma('vm:never-inline')
int cls_basic_method() => Calculator().add(3, 4);

class Formatter {
  @pragma('vm:entry-point') @pragma('vm:never-inline')
  static String format(int n) => 'Num: $n';  // T36
}
@pragma('vm:entry-point') @pragma('vm:never-inline')
String cls_static_method() => Formatter.format(42);

class Config {
  @pragma('vm:entry-point') @pragma('vm:never-inline')
  int get value => 60;  // T37: 60
}
@pragma('vm:entry-point') @pragma('vm:never-inline')
int cls_getter() => Config().value;

class Store {
  String _data = 'empty';
  @pragma('vm:entry-point') @pragma('vm:never-inline')
  set data(String v) { _data = v.toLowerCase(); }  // T38: lower
  String get data => _data;
}
@pragma('vm:entry-point') @pragma('vm:never-inline')
String cls_setter() { final s = Store(); s.data = 'HELLO'; return s.data; }

class Animal {
  @pragma('vm:entry-point') @pragma('vm:never-inline')
  String describe() => 'animal';
}
class Dog extends Animal {
  @pragma('vm:entry-point') @pragma('vm:never-inline')
  @override String describe() => 'Dog (patched)';  // T39
}
@pragma('vm:entry-point') @pragma('vm:never-inline')
String cls_inheritance() => Dog().describe();

abstract class Validator {
  bool validate(String s);
}
class LengthValidator extends Validator {
  @pragma('vm:entry-point') @pragma('vm:never-inline')
  @override bool validate(String s) => s.length >= 3;  // T40: >=3
}
@pragma('vm:entry-point') @pragma('vm:never-inline')
bool cls_abstract() => LengthValidator().validate('hi');

mixin Greetable {
  @pragma('vm:entry-point') @pragma('vm:never-inline')
  String greet() => 'Hi from mixin';  // T41
}
class Person with Greetable {}
@pragma('vm:entry-point') @pragma('vm:never-inline')
String cls_mixin() => Person().greet();

enum Status { active, inactive }
extension StatusExt on Status {
  @pragma('vm:entry-point') @pragma('vm:never-inline')
  String get label => this == Status.active ? 'ON' : 'OFF';  // T42
}
@pragma('vm:entry-point') @pragma('vm:never-inline')
String cls_enum() => Status.active.label;
void main() {}
