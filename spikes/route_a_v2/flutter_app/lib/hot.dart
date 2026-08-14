library;

/// The measured workload. Same shape as the historical benchmark
/// (spikes/benchmark/hotpatch_demo/patches/greet_cpu.dart): a 10K-iteration
/// accumulation, so the numbers stay comparable across sessions.
@pragma('vm:never-inline')
int hotLoopNative() {
  int sum = 0;
  for (int i = 0; i < 10000; i++) {
    sum += i;
  }
  return sum;
}

/// Indirection the KBC module can rebind. All three configurations call through
/// it, so the extra indirect call is a constant and does not skew the ratios.
int Function() hotLoop = hotLoopNative;
