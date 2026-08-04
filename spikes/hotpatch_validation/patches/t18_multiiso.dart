library hotpatch_validation.t18;

int _counter = 0;

@pragma('vm:entry-point') @pragma('vm:never-inline')
String multiiso_value() => 'isolate_patched_$_counter';  // T96: CHANGED

// Helper to increment (simulates state change across "invocations")
@pragma('vm:entry-point') @pragma('vm:never-inline')  
String multiiso_increment() { _counter += 2; return 'count:$_counter'; }  // T96: CHANGED +2

void main() {}
