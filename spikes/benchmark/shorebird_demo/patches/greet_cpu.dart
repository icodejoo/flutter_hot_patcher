String greet() {
  int sum = 0;
  for (int i = 0; i < 1000000; i++) {
    sum += i;
  }
  return 'PATCHED_CPU:$sum';
}
