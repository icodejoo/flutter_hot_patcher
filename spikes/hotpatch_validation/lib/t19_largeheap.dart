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
String process_item(int id) => 'item_$id';

// Create many workers holding closures to process_item
@pragma('vm:entry-point') @pragma('vm:never-inline')
String largeheap_test() {
  // Create 100 workers (simulates production-scale object graph)
  final workers = List.generate(100, (i) => Worker(() => process_item(i)));
  // Measure: call first and last
  return '${workers.first.work()}|${workers.last.work()}';
}

@pragma('vm:entry-point') @pragma('vm:never-inline')
int largeheap_count() => 100;  // baseline object count

void main() {}
