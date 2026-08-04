library hotpatch_validation.t19;

// Simulates a large heap scenario:
// A function that many objects "hold" via closures.
// Tests: does patching work correctly when there are many closure instances?

class Worker {
  final String Function() _fn;
  Worker(this._fn);
  String work() => _fn();
}

// The target function (baseline version)
@pragma('vm:entry-point') @pragma('vm:never-inline')
String process_item(int id) => 'patched_item_$id';  // T97: CHANGED

// Create many workers holding closures to process_item
@pragma('vm:entry-point') @pragma('vm:never-inline')
String largeheap_test() {
  // Create 1000 workers (10× more)
  final workers = List.generate(1000, (i) => Worker(() => process_item(i)));  // T97: CHANGED to 1000
  // Measure: call first and last
  return '${workers.first.work()}|${workers.last.work()}';
}

@pragma('vm:entry-point') @pragma('vm:never-inline')
int largeheap_count() => 1000;  // T97: CHANGED to 1000

void main() {}
