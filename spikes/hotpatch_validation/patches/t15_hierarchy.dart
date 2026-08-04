library hotpatch_validation.t15;

// T82: added age field → class_hierarchy_changed expected
class PersonT82 {
  final String name;
  final int age;  // NEW FIELD
  PersonT82(this.name, {this.age = 0});
  @pragma('vm:entry-point') @pragma('vm:never-inline')
  String describe() => 'Person: $name, age: $age';
}
@pragma('vm:entry-point') @pragma('vm:never-inline')
String hierarchy_add_field() => PersonT82('Alice').describe();

// T83: removed price field → class_hierarchy_changed expected
class ItemT83 {
  final String label;
  // price field removed
  ItemT83(this.label);
  @pragma('vm:entry-point') @pragma('vm:never-inline')
  String describe() => '$label: free';
}
@pragma('vm:entry-point') @pragma('vm:never-inline')
String hierarchy_remove_field() => ItemT83('widget').describe();

// T84: new ExtraClass added → detected in kernel_linker 'added'
class ExtraClass {
  @pragma('vm:entry-point') @pragma('vm:never-inline')
  String hello() => 'extra_class_hello';
}
@pragma('vm:entry-point') @pragma('vm:never-inline')
String hierarchy_add_class() => ExtraClass().hello();

// T85: RemovedClass is gone
@pragma('vm:entry-point') @pragma('vm:never-inline')
String hierarchy_remove_class() => 'class_was_removed';

// T86: now inherits BaseB
class BaseA { String tag() => 'A'; }
class BaseB { String tag() => 'B'; }
class ChildT86 extends BaseB {  // CHANGED: was BaseA
  @pragma('vm:entry-point') @pragma('vm:never-inline')
  String whoami() => 'Child of ${tag()}';
}
@pragma('vm:entry-point') @pragma('vm:never-inline')
String hierarchy_change_inheritance() => ChildT86().whoami();

void main() {}
