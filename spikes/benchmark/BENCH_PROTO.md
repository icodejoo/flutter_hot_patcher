# Benchmark Result JSON Schema

Every demo app writes `benchmark.json` to its Documents directory on exit.

```json
{
  "variant": "hotpatch|shorebird",
  "platform": "ios|android",
  "patch_type": "none|normal|cpu",
  "patch_size_bytes": 365,
  "cold_start_ms": 312,
  "greet_call_us": 45,
  "memory_rss_kb": 48200,
  "cpu_percent_peak": 0.0
}
```

## Field Descriptions

- `variant`: Which hot-patch implementation is being tested
  - `hotpatch`: Self-developed hot-patch solution
  - `shorebird`: Shorebird hot-patch solution
- `platform`: Target platform for testing
  - `ios`: Apple iOS
  - `android`: Google Android
- `patch_type`: Type of patch being applied
  - `none`: Baseline, no patch applied
  - `normal`: Standard patch (code changes)
  - `cpu`: CPU-intensive patch benchmark
- `patch_size_bytes`: Size of the raw patch artifact pushed to device (set by script)
- `cold_start_ms`: Wall-clock time from process start to first greet() return, in milliseconds
- `greet_call_us`: Mean latency of 1000 sequential greet() calls, in microseconds
- `memory_rss_kb`: Resident Set Size memory usage after greet benchmark loop, in kilobytes (from getrusage/proc_pid_rusage)
- `cpu_percent_peak`: Peak CPU utilization percentage during CPU patch benchmark (0 for non-CPU runs)
