library hotpatch_validation.t15;

// T82: baseline has 1 field; patch adds a field → class_hierarchy_changed
class PersonT82 {
  final String name;
  PersonT82(this.name);
  @pragma('vm:entry-point') @pragma('vm:never-inline')
  String describe() => 'Person: $name';
}
@pragma('vm:entry-point') @pragma('vm:never-inline')
String hierarchy_add_field() => PersonT82('Alice').describe();

// T83: baseline has 2 fields; patch removes one → class_hierarchy_changed
class ItemT83 {
  final String label;
  final int price;
  ItemT83(this.label, this.price);
  @pragma('vm:entry-point') @pragma('vm:never-inline')
  String describe() => '$label: $price';
}
@pragma('vm:entry-point') @pragma('vm:never-inline')
String hierarchy_remove_field() => ItemT83('widget', 10).describe();

// T84: baseline has no ExtraClass; patch adds it → added functions detected
@pragma('vm:entry-point') @pragma('vm:never-inline')
String hierarchy_add_class() => 'no_extra_class';

// T85: baseline has RemovedClass; patch removes it → removed functions detected
class RemovedClass {
  @pragma('vm:entry-point') @pragma('vm:never-inline')
  String value() => 'will_be_removed';
}
@pragma('vm:entry-point') @pragma('vm:never-inline')
String hierarchy_remove_class() => RemovedClass().value();

// T86: baseline inherits BaseA; patch changes to BaseB → class_hierarchy_changed
class BaseA { String tag() => 'A'; }
class BaseB { String tag() => 'B'; }
class ChildT86 extends BaseA {
  @pragma('vm:entry-point') @pragma('vm:never-inline')
  String whoami() => 'Child of ${tag()}';
}
@pragma('vm:entry-point') @pragma('vm:never-inline')
String hierarchy_change_inheritance() => ChildT86().whoami();

void main() {}
