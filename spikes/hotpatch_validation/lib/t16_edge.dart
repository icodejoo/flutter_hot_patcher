library hotpatch_validation.t16;

// T87: empty function → returns value
@pragma('vm:entry-point') @pragma('vm:never-inline')
String? edge_empty_fn() => null;

// T88: recursive termination value
@pragma('vm:entry-point') @pragma('vm:never-inline')
int edge_recursive(int n) => n <= 0 ? 0 : n + edge_recursive(n - 1);
@pragma('vm:entry-point') @pragma('vm:never-inline')
int edge_recursive_call() => edge_recursive(5);  // 15

// T89: mutual recursion
@pragma('vm:entry-point') @pragma('vm:never-inline')
bool edge_is_even(int n) => n == 0 ? true : edge_is_odd(n - 1);
@pragma('vm:entry-point') @pragma('vm:never-inline')
bool edge_is_odd(int n) => n == 0 ? false : edge_is_even(n - 1);
@pragma('vm:entry-point') @pragma('vm:never-inline')
String edge_mutual_recursive() => '${edge_is_even(4)},${edge_is_odd(3)}';  // 'true,true'

// T90: large string
@pragma('vm:entry-point') @pragma('vm:never-inline')
int edge_large_string() => ('x' * 1000 + 'baseline').length;  // 1008

// T91: identity — no changes (expect 0 in changed)
@pragma('vm:entry-point') @pragma('vm:never-inline')
String edge_identity_same() => 'unchanged';

void main() {}
