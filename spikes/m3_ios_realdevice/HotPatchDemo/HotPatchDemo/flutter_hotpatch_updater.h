#pragma once
#ifdef __cplusplus
extern "C" {
#endif

/** Initialize updater. data_dir: App data directory. Returns 0 on success. */
int fhp_init(const char* data_dir, const char* build_fingerprint);

/** Stage + verify a patch bundle. pubkey_hex: 64-char Ed25519 public key hex. */
int fhp_stage_patch(const char* bundle_dir, const char* pubkey_hex);

/** Get next-boot patch dir (NULL = pure baseline). Caller must fhp_free_string(). */
const char* fhp_get_next_boot_patch_dir(void);

/** Confirm App is healthy (call after first frame renders). */
void fhp_confirm_health(void);

/** Dump current state as JSON. Caller must fhp_free_string(). */
const char* fhp_state_json(void);

/** Free a string returned by fhp_*. */
void fhp_free_string(const char* s);

#ifdef __cplusplus
}
#endif
