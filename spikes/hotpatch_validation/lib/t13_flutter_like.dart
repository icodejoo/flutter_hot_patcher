library hotpatch_validation.t13;

// Flutter-like patterns without Flutter Engine

class CounterState {
  int _count = 0;
  @pragma('vm:entry-point') @pragma('vm:never-inline')
  void increment() { _count += 1; }
  int get count => _count;
}
@pragma('vm:entry-point') @pragma('vm:never-inline')
int flutter_counter_logic() {  // T69
  final s = CounterState(); s.increment(); s.increment(); return s.count;
}

@pragma('vm:entry-point') @pragma('vm:never-inline')
String flutter_state_compute() {  // T70
  return 'Count: 0';
}

@pragma('vm:entry-point') @pragma('vm:never-inline')
String flutter_builder_fn() {  // T71
  String Function(int) builder = (n) => 'Item #$n';
  return builder(1);
}

@pragma('vm:entry-point') @pragma('vm:never-inline')
String flutter_callback() {  // T72
  String result = 'initial';
  void Function() onPressed = () { result = 'pressed'; };
  onPressed();
  return result;
}

@pragma('vm:entry-point') @pragma('vm:never-inline')
String flutter_form_validate() {  // T73
  String? validate(String value) => value.isEmpty ? 'Required' : null;
  return validate('') ?? 'valid';  // returns 'Required'
}

void main() {}
