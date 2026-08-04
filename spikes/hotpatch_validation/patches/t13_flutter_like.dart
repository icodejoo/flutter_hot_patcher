library hotpatch_validation.t13;

class CounterState {
  int _count = 0;
  @pragma('vm:entry-point') @pragma('vm:never-inline')
  void increment() { _count += 2; }  // T69: step 2
  int get count => _count;
}
@pragma('vm:entry-point') @pragma('vm:never-inline')
int flutter_counter_logic() {
  final s = CounterState(); s.increment(); s.increment(); return s.count;
}

@pragma('vm:entry-point') @pragma('vm:never-inline')
String flutter_state_compute() => 'Total: 0';  // T70

@pragma('vm:entry-point') @pragma('vm:never-inline')
String flutter_builder_fn() {  // T71
  String Function(int) builder = (n) => 'Element #$n';
  return builder(1);
}

@pragma('vm:entry-point') @pragma('vm:never-inline')
String flutter_callback() {  // T72
  String result = 'initial';
  void Function() onPressed = () { result = 'clicked'; };
  onPressed();
  return result;
}

@pragma('vm:entry-point') @pragma('vm:never-inline')
String flutter_form_validate() {  // T73
  String? validate(String value) => value.length < 3 ? 'Too short' : null;
  return validate('hi') ?? 'valid';  // returns 'Too short'
}

void main() {}
