library;

@pragma('vm:entry-point')
@pragma('vm:never-inline')
String greet() {
  int sum = 0;
  for (int i = 0; i < 10000000; i++) {
    sum += i;
  }
  return 'PATCHED_CPU:$sum';
}
