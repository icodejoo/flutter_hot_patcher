library hotpatch_validation.t18;

// Simulates the multi-isolate scenario at the Dart level.
// In production, closures in OTHER isolates are NOT redirected.
// This documents the behavior: patch is isolate-local.

int _counter = 0;

@pragma('vm:entry-point') @pragma('vm:never-inline')
String multiiso_value() => 'isolate_original_$_counter';

// Helper to increment (simulates state change across "invocations")
@pragma('vm:entry-point') @pragma('vm:never-inline')  
String multiiso_increment() { _counter++; return 'count:$_counter'; }

void main() {}
