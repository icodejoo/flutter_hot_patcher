#pragma once
#ifdef __cplusplus
extern "C" {
#endif

/* patch_dill_path: absolute path to patch.dill, or NULL for baseline */
const char* dart_run(int use_patch, const char* patch_dill_path);

#ifdef __cplusplus
}
#endif
