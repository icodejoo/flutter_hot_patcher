#pragma once
#ifdef __cplusplus
extern "C" {
#endif

/* Returns "ORIGINAL" or "PATCHED". Caller must not free. */
const char* dart_run(int use_patch);

#ifdef __cplusplus
}
#endif
