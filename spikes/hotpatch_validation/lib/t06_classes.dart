library hotpatch_validation.t06;

class Calculator {
  @pragma('vm:entry-point') @pragma('vm:never-inline')
  int add(int a, int b) => a + b;
}
@pragma('vm:entry-point') @pragma('vm:never-inline')
int cls_basic_method() => Calculator().add(3, 4);  // T35

class Formatter {
  @pragma('vm:entry-point') @pragma('vm:never-inline')
  static String format(int n) => 'Value: $n';
}
@pragma('vm:entry-point') @pragma('vm:never-inline')
String cls_static_method() => Formatter.format(42);  // T36

class Config {
  @pragma('vm:entry-point') @pragma('vm:never-inline')
  int get value => 20;
}
@pragma('vm:entry-point') @pragma('vm:never-inline')
int cls_getter() => Config().value;  // T37

class Store {
  String _data = 'empty';
  @pragma('vm:entry-point') @pragma('vm:never-inline')
  set data(String v) { _data = v.toUpperCase(); }
  String get data => _data;
}
@pragma('vm:entry-point') @pragma('vm:never-inline')
String cls_setter() { final s = Store(); s.data = 'hello'; return s.data; }  // T38

class Animal {
  @pragma('vm:entry-point') @pragma('vm:never-inline')
  String describe() => 'animal';
}
class Dog extends Animal {
  @pragma('vm:entry-point') @pragma('vm:never-inline')
  @override String describe() => 'dog';
}
@pragma('vm:entry-point') @pragma('vm:never-inline')
String cls_inheritance() => Dog().describe();  // T39

abstract class Validator {
  bool validate(String s);
}
class LengthValidator extends Validator {
  @pragma('vm:entry-point') @pragma('vm:never-inline')
  @override bool validate(String s) => s.length >= 5;
}
@pragma('vm:entry-point') @pragma('vm:never-inline')
bool cls_abstract() => LengthValidator().validate('hello');  // T40

mixin Greetable {
  @pragma('vm:entry-point') @pragma('vm:never-inline')
  String greet() => 'Hello from mixin';
}
class Person with Greetable {}
@pragma('vm:entry-point') @pragma('vm:never-inline')
String cls_mixin() => Person().greet();  // T41

enum Status { active, inactive }
extension StatusExt on Status {
  @pragma('vm:entry-point') @pragma('vm:never-inline')
  String get label => this == Status.active ? 'Active' : 'Inactive';
}
@pragma('vm:entry-point') @pragma('vm:never-inline')
String cls_enum() => Status.active.label;  // T42
