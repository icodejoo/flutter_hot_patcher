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


/**
 * Check for an available patch update from the server.
 * server_url: Base URL (e.g. "https://update.example.com")
 * app_id: Application identifier
 * release_version: Current release version string
 * current_patch_number: Current patch number, or -1 if on baseline
 * Returns JSON response string. Caller must fhp_free_string().
 */
const char* fhp_check_update(const char* server_url, const char* app_id,
                              const char* release_version, int current_patch_number);

/**
 * Download and stage a patch from the given URL.
 * download_url: Direct download URL for the .zst patch file
 * expected_sha256_hex: Expected SHA-256 hash (hex), or empty string to skip verification
 * patch_number: Patch number being applied
 * bundle_dir: Directory where the patch should be written
 * Returns 0 on success, negative on error.
 */
int fhp_download_and_stage(const char* download_url, const char* expected_sha256_hex,
                            unsigned int patch_number, const char* bundle_dir);

#ifdef __cplusplus
}
#endif
