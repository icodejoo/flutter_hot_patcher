#pragma once
#ifdef __cplusplus
extern "C" {
#endif

/* patch_bundle_dir: path to verified patch_bundle/ directory, or NULL for baseline */
const char* dart_run(const char* patch_bundle_dir);

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

#ifdef __cplusplus
}
#endif
