#pragma once
#ifdef __cplusplus
extern "C" {
#endif

/* patch_bundle_dir: path to verified patch_bundle/ directory, or NULL for baseline */
const char* dart_run(const char* patch_bundle_dir);

#ifdef __cplusplus
}
#endif
