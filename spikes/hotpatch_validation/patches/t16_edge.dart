library hotpatch_validation.t16;

// T87: was null, now returns a value
@pragma('vm:entry-point') @pragma('vm:never-inline')
String? edge_empty_fn() => 'was_empty';  // CHANGED

// T88: termination value 1 instead of 0
@pragma('vm:entry-point') @pragma('vm:never-inline')
int edge_recursive(int n) => n <= 0 ? 1 : n + edge_recursive(n - 1);  // CHANGED: base=1, result=16
@pragma('vm:entry-point') @pragma('vm:never-inline')
int edge_recursive_call() => edge_recursive(5);

// T89: swap even/odd logic
@pragma('vm:entry-point') @pragma('vm:never-inline')
bool edge_is_even(int n) => n == 0 ? false : edge_is_odd(n - 1);  // CHANGED: was true
@pragma('vm:entry-point') @pragma('vm:never-inline')
bool edge_is_odd(int n) => n == 0 ? true : edge_is_even(n - 1);   // CHANGED: was false
@pragma('vm:entry-point') @pragma('vm:never-inline')
String edge_mutual_recursive() => '${edge_is_even(4)},${edge_is_odd(3)}';  // 'false,false'

// T90: different suffix
@pragma('vm:entry-point') @pragma('vm:never-inline')
int edge_large_string() => ('x' * 1000 + 'patched').length;  // CHANGED: 1007

// T91: IDENTICAL — must produce 0 changes
@pragma('vm:entry-point') @pragma('vm:never-inline')
String edge_identity_same() => 'unchanged';  // SAME as baseline

void main() {}
