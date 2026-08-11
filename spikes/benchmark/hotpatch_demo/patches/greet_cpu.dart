library;

@pragma('vm:entry-point')
@pragma('vm:never-inline')
String greet() {
  int sum = 0;
  for (int i = 0; i < 1000000; i++) {
    sum += i;
  }
  // Return fixed string to avoid buffer overflow in dart_harness
  return sum > 0 ? 'PATCHED_CPU' : 'PATCHED_CPU';
}
