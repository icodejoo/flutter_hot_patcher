#pragma once
#ifdef __cplusplus
extern "C" {
#endif

/* patch_bundle_dir: path to verified patch_bundle/ directory, or NULL for baseline */
const char* dart_run(const char* patch_bundle_dir);

/**
 * Returns mean ns per greet() call for the most recent bytecode OTA benchmark.
 * Valid after dart_run() with a patch_bundle_dir. Returns 0 otherwise.
 */
long long dart_get_bytecode_bench_ns(void);

/**
 * Load a B-route vmcode patch (staged IsolateSnapshotData file) into read-only
 * memory before dart_run() is called.
 * Returns 1=loaded, 0=no patch, -1=error.
 */
int dart_load_vmcode_patch(const char* staged_path);

/**
 * flutter_hot_patcher B4: Load Simulator link table from a vmcode file.
 * Must be called BEFORE dart_run(). Sets up SimulatorToCPU dispatch table.
 * Returns true on success (N>0 entries), false on failure or empty table.
 */
bool fhp_shorebird_load_vmcode(const char* vmcode_path);


/**
 * flutter_hot_patcher OTA: Load PATCH instructions + data + link table from a
 * vmcode_ota_patch.vmcode file. Must be called BEFORE dart_run().
 * Reads: [N][instr_size][data_size][N×8 link entries][pad to 16384][instr][data]
 * Returns: number of link entries loaded (>0 = success), 0 = not found, -1 = error.
 */
int dart_load_ota_patch(const char* vmcode_path);

/**
 * Apply a pre-compiled AOT patch variant (no bytecode loading).
 * Calls applyAOTPatch([variant]) in Dart — pure data pointer update.
 * variant=0: restore original greet()
 * variant=1: greet_patched() → 'PATCHED_AOT'
 * variant=2: greet_cpu_aot() → 10K loop, AOT speed
 * Returns: result of getResult() after patch applied, or error string.
 * MUST be called after dart_run() has initialized the isolate.
 */
const char* dart_apply_aot_patch(int variant);

/**
 * Benchmark greetVar() for n sequential calls.
 * Calls benchmarkGreet([n]) in Dart.
 * Returns: mean microseconds per call as null-terminated string (e.g. "0.051").
 * MUST be called after dart_run() has initialized the isolate.
 */
const char* dart_benchmark_greet(int n);

#ifdef __cplusplus
}
#endif

void dart_benchmark_aot_capi(int n);
long long dart_get_aot_capi_bench_ns(void);
