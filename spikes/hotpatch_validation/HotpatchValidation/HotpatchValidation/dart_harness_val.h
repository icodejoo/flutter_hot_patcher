#pragma once
#ifdef __cplusplus
extern "C" {
#endif
// Run all 5 spot-check validation cases.
// Returns JSON array string (static buffer, valid until next call).
const char* dart_run_all_validations(void);
#ifdef __cplusplus
}
#endif
