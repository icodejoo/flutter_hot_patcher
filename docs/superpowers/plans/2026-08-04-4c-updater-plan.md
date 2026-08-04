# 4-C Updater 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rust Updater 库：补丁验证 + 状态机 + boot-loop watchdog + C FFI API。

**Architecture:** Rust library crate，5 个模块（state/verify/watchdog/ffi/lib），`ring` 做 Ed25519 验签，`serde_json` 持久化状态，暴露 C FFI 供 dart_harness.c 调用。

**Tech Stack:** Rust 2021, ring 0.17, serde_json 1, sha2 0.10

**Working directory:** `~/Documents/flutter_hot_patcher/tools/updater/`

---

## Task 1: Cargo 项目骨架 + verify.rs（验签 + hash）

**Files:**
- Create: `tools/updater/Cargo.toml`
- Create: `tools/updater/src/verify.rs`
- Create: `tools/updater/src/lib.rs`

- [ ] **Step 1: 创建 Rust crate**

```bash
mkdir -p ~/Documents/flutter_hot_patcher/tools/updater
cd ~/Documents/flutter_hot_patcher/tools/updater
cargo init --lib 2>&1
```

- [ ] **Step 2: 写 Cargo.toml**

```toml
[package]
name = "flutter_hotpatch_updater"
version = "0.1.0"
edition = "2021"

[lib]
crate-type = ["staticlib", "cdylib", "rlib"]

[dependencies]
serde = { version = "1", features = ["derive"] }
serde_json = "1"
ring = "0.17"
sha2 = { version = "0.10", features = ["oid"] }
hex = "0.4"

[dev-dependencies]
tempfile = "3"
```

- [ ] **Step 3: 先写 verify.rs 测试**

```rust
// src/verify.rs
#[cfg(test)]
mod tests {
    use super::*;

    fn test_key_pair() -> (Vec<u8>, Vec<u8>) {
        use ring::rand::SystemRandom;
        use ring::signature::{Ed25519KeyPair, KeyPair};
        let rng = SystemRandom::new();
        let doc = Ed25519KeyPair::generate_pkcs8(&rng).unwrap();
        let pair = Ed25519KeyPair::from_pkcs8(doc.as_ref()).unwrap();
        let pub_key = pair.public_key().as_ref().to_vec();
        (doc.as_ref().to_vec(), pub_key)
    }

    #[test]
    fn test_canonical_bytes_deterministic() {
        let json = r#"{"b":2,"a":1}"#;
        let obj: serde_json::Value = serde_json::from_str(json).unwrap();
        let b1 = canonical_bytes(&obj);
        let b2 = canonical_bytes(&obj);
        assert_eq!(b1, b2);
    }

    #[test]
    fn test_verify_manifest_ok() {
        let (pkcs8, pub_key) = test_key_pair();
        let manifest: serde_json::Value = serde_json::json!({
            "patch_id": "test-1",
            "format_version": "1"
        });
        let sig = sign_test(&pkcs8, &manifest);
        assert!(verify_manifest_signature(&manifest, &sig, &pub_key).is_ok());
    }

    #[test]
    fn test_verify_manifest_tampered_fails() {
        let (pkcs8, pub_key) = test_key_pair();
        let original: serde_json::Value = serde_json::json!({ "patch_id": "test-1" });
        let sig = sign_test(&pkcs8, &original);
        let tampered: serde_json::Value = serde_json::json!({ "patch_id": "tampered" });
        assert!(verify_manifest_signature(&tampered, &sig, &pub_key).is_err());
    }

    #[test]
    fn test_verify_artifact_hash_ok() {
        let data = b"hello patch";
        let hash = sha256_hex(data);
        assert!(verify_artifact_hash(data, &hash).is_ok());
    }

    #[test]
    fn test_verify_artifact_hash_mismatch() {
        let data = b"hello patch";
        assert!(verify_artifact_hash(data, "deadbeef").is_err());
    }

    fn sign_test(pkcs8: &[u8], manifest: &serde_json::Value) -> Vec<u8> {
        use ring::signature::{Ed25519KeyPair, KeyPair};
        let pair = Ed25519KeyPair::from_pkcs8(pkcs8).unwrap();
        let bytes = canonical_bytes(manifest);
        pair.sign(&bytes).as_ref().to_vec()
    }
}
```

- [ ] **Step 4: 运行测试（预期编译失败）**

```bash
cd ~/Documents/flutter_hot_patcher/tools/updater
cargo test 2>&1 | head -20
```

Expected: compile error (verify.rs not implemented)

- [ ] **Step 5: 实现 verify.rs**

```rust
// src/verify.rs
use ring::signature::{UnparsedPublicKey, ED25519};
use sha2::{Digest, Sha256};

#[derive(Debug)]
pub enum VerifyError {
    InvalidSignature,
    HashMismatch { path: String },
    FingerprintMismatch { expected: String, got: String },
    BlacklistedPatch { patch_id: String },
    MalformedData(String),
}

/// Deterministic JSON serialization (sorted keys, no extra whitespace).
pub fn canonical_bytes(value: &serde_json::Value) -> Vec<u8> {
    canonical_value(value).to_string().into_bytes()
}

fn canonical_value(value: &serde_json::Value) -> serde_json::Value {
    match value {
        serde_json::Value::Object(map) => {
            let mut sorted: Vec<_> = map.iter().collect();
            sorted.sort_by_key(|(k, _)| k.as_str());
            let new_map: serde_json::Map<String, serde_json::Value> = sorted
                .into_iter()
                .map(|(k, v)| (k.clone(), canonical_value(v)))
                .collect();
            serde_json::Value::Object(new_map)
        }
        serde_json::Value::Array(arr) => {
            serde_json::Value::Array(arr.iter().map(canonical_value).collect())
        }
        _ => value.clone(),
    }
}

/// Verify Ed25519 signature on manifest's canonical bytes.
pub fn verify_manifest_signature(
    manifest: &serde_json::Value,
    signature: &[u8],
    public_key_bytes: &[u8],
) -> Result<(), VerifyError> {
    let bytes = canonical_bytes(manifest);
    let key = UnparsedPublicKey::new(&ED25519, public_key_bytes);
    key.verify(&bytes, signature)
        .map_err(|_| VerifyError::InvalidSignature)
}

/// Compute SHA-256 hex of data.
pub fn sha256_hex(data: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(data);
    hex::encode(hasher.finalize())
}

/// Verify that data matches expected SHA-256 hex.
pub fn verify_artifact_hash(data: &[u8], expected_sha256: &str) -> Result<(), VerifyError> {
    let actual = sha256_hex(data);
    if actual == expected_sha256 {
        Ok(())
    } else {
        Err(VerifyError::HashMismatch {
            path: format!("expected={expected_sha256} got={actual}"),
        })
    }
}

/// Verify target_build_fingerprint matches this app's fingerprint.
pub fn verify_fingerprint(
    manifest: &serde_json::Value,
    app_fingerprint: &str,
) -> Result<(), VerifyError> {
    let target = manifest
        .get("target_build_fingerprint")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    if target == app_fingerprint {
        Ok(())
    } else {
        Err(VerifyError::FingerprintMismatch {
            expected: app_fingerprint.to_string(),
            got: target.to_string(),
        })
    }
}

/// Full bundle verification: sig + hashes + fingerprint + blacklist.
pub fn verify_bundle(
    bundle_dir: &std::path::Path,
    public_key_bytes: &[u8],
    app_fingerprint: &str,
    blacklist: &[String],
) -> Result<String, VerifyError> {
    // 1. Load manifest + sig
    let manifest_bytes = std::fs::read(bundle_dir.join("manifest.json"))
        .map_err(|e| VerifyError::MalformedData(e.to_string()))?;
    let sig_bytes = std::fs::read(bundle_dir.join("manifest.sig"))
        .map_err(|e| VerifyError::MalformedData(e.to_string()))?;
    let manifest: serde_json::Value = serde_json::from_slice(&manifest_bytes)
        .map_err(|e| VerifyError::MalformedData(e.to_string()))?;

    // 2. Verify signature
    verify_manifest_signature(&manifest, &sig_bytes, public_key_bytes)?;

    // 3. Verify artifact hashes
    let artifacts = manifest
        .get("artifacts")
        .and_then(|v| v.as_array())
        .unwrap_or(&vec![]);
    for artifact in artifacts {
        let path = artifact.get("path").and_then(|v| v.as_str()).unwrap_or("");
        let expected_sha256 = artifact.get("sha256").and_then(|v| v.as_str()).unwrap_or("");
        let data = std::fs::read(bundle_dir.join(path))
            .map_err(|e| VerifyError::MalformedData(format!("{path}: {e}")))?;
        verify_artifact_hash(&data, expected_sha256)?;
    }

    // 4. Verify fingerprint
    verify_fingerprint(&manifest, app_fingerprint)?;

    // 5. Check blacklist
    let patch_id = manifest
        .get("patch_id")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    if blacklist.contains(&patch_id.to_string()) {
        return Err(VerifyError::BlacklistedPatch { patch_id: patch_id.to_string() });
    }

    Ok(patch_id.to_string())
}
```

- [ ] **Step 6: 运行测试**

```bash
cd ~/Documents/flutter_hot_patcher/tools/updater
cargo test verify 2>&1
```

Expected: `test verify::tests::test_canonical_bytes_deterministic ... ok` × 4 tests

- [ ] **Step 7: commit**

```bash
cd ~/Documents/flutter_hot_patcher
git add tools/updater/
git commit -m "feat(4-C): verify.rs — Ed25519 + artifact hashes + fingerprint, 4 tests pass"
```

---

## Task 2: state.rs（状态机持久化）+ watchdog.rs

**Files:**
- Create: `tools/updater/src/state.rs`
- Create: `tools/updater/src/watchdog.rs`

- [ ] **Step 1: 写 state.rs 测试**

```rust
// 在 src/state.rs 的 #[cfg(test)] 块里：

#[test]
fn test_initial_state_is_baseline() {
    let dir = tempfile::tempdir().unwrap();
    let state = UpdaterState::load_or_default(dir.path());
    assert_eq!(state.stage, PatchStage::Baseline);
    assert!(state.blacklist.is_empty());
}

#[test]
fn test_stage_and_mark_next_boot() {
    let dir = tempfile::tempdir().unwrap();
    let mut state = UpdaterState::load_or_default(dir.path());
    state.set_staged("/tmp/bundle".to_string(), "patch-1".to_string());
    state.save(dir.path()).unwrap();
    state.mark_next_boot();
    state.save(dir.path()).unwrap();
    let loaded = UpdaterState::load_or_default(dir.path());
    assert_eq!(loaded.stage, PatchStage::NextBoot);
    assert_eq!(loaded.staged_patch_id.as_deref(), Some("patch-1"));
}

#[test]
fn test_blacklist_persists() {
    let dir = tempfile::tempdir().unwrap();
    let mut state = UpdaterState::load_or_default(dir.path());
    state.blacklist.push("bad-patch-1".to_string());
    state.save(dir.path()).unwrap();
    let loaded = UpdaterState::load_or_default(dir.path());
    assert!(loaded.blacklist.contains(&"bad-patch-1".to_string()));
}
```

- [ ] **Step 2: 实现 state.rs**

```rust
// src/state.rs
use serde::{Deserialize, Serialize};
use std::path::Path;

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PatchStage {
    Baseline,
    Staged,
    Verified,
    NextBoot,
    PendingConfirmation,
    ConfirmedGood,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct UpdaterState {
    pub stage: PatchStage,
    pub staged_dir: Option<String>,
    pub staged_patch_id: Option<String>,
    pub app_build_fingerprint: String,
    pub blacklist: Vec<String>,
}

impl UpdaterState {
    pub fn load_or_default(data_dir: &Path) -> Self {
        let path = data_dir.join("updater_state.json");
        if let Ok(bytes) = std::fs::read(&path) {
            if let Ok(state) = serde_json::from_slice(&bytes) {
                return state;
            }
        }
        Self {
            stage: PatchStage::Baseline,
            staged_dir: None,
            staged_patch_id: None,
            app_build_fingerprint: String::new(),
            blacklist: Vec::new(),
        }
    }

    pub fn save(&self, data_dir: &Path) -> std::io::Result<()> {
        let path = data_dir.join("updater_state.json");
        let json = serde_json::to_string_pretty(self).unwrap();
        std::fs::write(path, json)
    }

    pub fn set_staged(&mut self, dir: String, patch_id: String) {
        self.staged_dir = Some(dir);
        self.staged_patch_id = Some(patch_id);
        self.stage = PatchStage::Staged;
    }

    pub fn mark_verified(&mut self) {
        self.stage = PatchStage::Verified;
    }

    pub fn mark_next_boot(&mut self) {
        self.stage = PatchStage::NextBoot;
    }

    pub fn begin_apply(&mut self) {
        self.stage = PatchStage::PendingConfirmation;
    }

    pub fn confirm_health(&mut self) {
        if self.stage == PatchStage::PendingConfirmation {
            self.stage = PatchStage::ConfirmedGood;
        }
    }

    pub fn auto_rollback(&mut self) {
        if let Some(id) = self.staged_patch_id.take() {
            if !self.blacklist.contains(&id) {
                self.blacklist.push(id);
            }
        }
        self.staged_dir = None;
        self.stage = PatchStage::Baseline;
    }

    pub fn get_next_boot_dir(&self) -> Option<&str> {
        if matches!(self.stage, PatchStage::NextBoot | PatchStage::PendingConfirmation) {
            self.staged_dir.as_deref()
        } else {
            None
        }
    }
}
```

- [ ] **Step 3: 实现 watchdog.rs**

```rust
// src/watchdog.rs
use crate::state::{PatchStage, UpdaterState};
use std::path::Path;

/// Call on cold boot. If PendingConfirmation → last boot crashed → auto-rollback.
/// If NextBoot → transition to PendingConfirmation.
pub fn on_cold_boot(state: &mut UpdaterState, data_dir: &Path) {
    match state.stage {
        PatchStage::PendingConfirmation => {
            // Last boot crashed (confirm_health was never called)
            let patch_id = state.staged_patch_id.clone().unwrap_or_default();
            eprintln!("[updater] Boot-loop detected for patch '{}', auto-rollback", patch_id);
            state.auto_rollback();
            state.save(data_dir).ok();
        }
        PatchStage::NextBoot => {
            state.begin_apply();
            state.save(data_dir).ok();
        }
        _ => {}
    }
}

/// Call after successful app start (first frame rendered / N seconds stable).
pub fn confirm_health(state: &mut UpdaterState, data_dir: &Path) {
    state.confirm_health();
    state.save(data_dir).ok();
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::state::PatchStage;

    #[test]
    fn test_next_boot_becomes_pending_on_cold_boot() {
        let dir = tempfile::tempdir().unwrap();
        let mut state = UpdaterState::load_or_default(dir.path());
        state.set_staged("/tmp/bundle".to_string(), "p1".to_string());
        state.mark_next_boot();
        on_cold_boot(&mut state, dir.path());
        assert_eq!(state.stage, PatchStage::PendingConfirmation);
    }

    #[test]
    fn test_crash_triggers_blacklist() {
        let dir = tempfile::tempdir().unwrap();
        let mut state = UpdaterState::load_or_default(dir.path());
        state.set_staged("/tmp/bundle".to_string(), "bad-patch".to_string());
        state.begin_apply(); // simulate: was in PendingConfirmation
        on_cold_boot(&mut state, dir.path()); // next boot without confirm = crash
        assert_eq!(state.stage, PatchStage::Baseline);
        assert!(state.blacklist.contains(&"bad-patch".to_string()));
    }

    #[test]
    fn test_confirm_health_ok() {
        let dir = tempfile::tempdir().unwrap();
        let mut state = UpdaterState::load_or_default(dir.path());
        state.set_staged("/tmp/bundle".to_string(), "good-patch".to_string());
        state.begin_apply();
        confirm_health(&mut state, dir.path());
        assert_eq!(state.stage, PatchStage::ConfirmedGood);
        assert!(state.blacklist.is_empty());
    }
}
```

- [ ] **Step 4: 运行所有测试**

```bash
cd ~/Documents/flutter_hot_patcher/tools/updater
cargo test 2>&1 | tail -15
```

Expected: `test result: ok. N passed`

- [ ] **Step 5: commit**

```bash
cd ~/Documents/flutter_hot_patcher
git add tools/updater/
git commit -m "feat(4-C): state.rs + watchdog.rs — boot-loop detection + auto-blacklist, tests pass"
```

---

## Task 3: ffi.rs（C FFI API）+ lib.rs 整合

**Files:**
- Create: `tools/updater/src/ffi.rs`
- Create: `tools/updater/src/lib.rs`（最终版）
- Create: `tools/updater/include/flutter_hotpatch_updater.h`

- [ ] **Step 1: 实现 ffi.rs**

```rust
// src/ffi.rs — C FFI API
use std::ffi::{CStr, CString};
use std::os::raw::c_char;
use std::path::PathBuf;
use std::sync::Mutex;

use crate::state::UpdaterState;
use crate::watchdog;
use crate::verify;

struct UpdaterContext {
    data_dir: PathBuf,
    state: UpdaterState,
    public_key_hex: String,
    app_fingerprint: String,
}

static CONTEXT: Mutex<Option<UpdaterContext>> = Mutex::new(None);

#[no_mangle]
pub extern "C" fn fhp_init(
    data_dir: *const c_char,
    build_fingerprint: *const c_char,
) -> i32 {
    let data_dir = unsafe { CStr::from_ptr(data_dir) }.to_string_lossy().to_string();
    let fingerprint = unsafe { CStr::from_ptr(build_fingerprint) }.to_string_lossy().to_string();
    let data_path = PathBuf::from(&data_dir);
    std::fs::create_dir_all(&data_path).ok();
    let mut state = UpdaterState::load_or_default(&data_path);
    state.app_build_fingerprint = fingerprint.clone();
    // Run watchdog on init (= cold boot)
    watchdog::on_cold_boot(&mut state, &data_path);
    let mut ctx = CONTEXT.lock().unwrap();
    *ctx = Some(UpdaterContext {
        data_dir: data_path,
        state,
        public_key_hex: String::new(),
        app_fingerprint: fingerprint,
    });
    0
}

#[no_mangle]
pub extern "C" fn fhp_stage_patch(
    bundle_dir: *const c_char,
    pubkey_hex: *const c_char,
) -> i32 {
    let bundle = unsafe { CStr::from_ptr(bundle_dir) }.to_string_lossy().to_string();
    let pubkey = unsafe { CStr::from_ptr(pubkey_hex) }.to_string_lossy().to_string();
    let pub_bytes = match hex::decode(&pubkey) {
        Ok(b) => b,
        Err(_) => return -1,
    };
    let mut ctx_guard = CONTEXT.lock().unwrap();
    let ctx = match ctx_guard.as_mut() {
        Some(c) => c,
        None => return -2,
    };
    let bundle_path = PathBuf::from(&bundle);
    match verify::verify_bundle(&bundle_path, &pub_bytes, &ctx.app_fingerprint, &ctx.state.blacklist) {
        Ok(patch_id) => {
            ctx.state.set_staged(bundle.clone(), patch_id);
            ctx.state.mark_verified();
            ctx.state.mark_next_boot();
            ctx.state.save(&ctx.data_dir).ok();
            ctx.public_key_hex = pubkey;
            0
        }
        Err(e) => {
            eprintln!("[updater] stage_patch failed: {:?}", e);
            -3
        }
    }
}

#[no_mangle]
pub extern "C" fn fhp_get_next_boot_patch_dir() -> *const c_char {
    let ctx_guard = CONTEXT.lock().unwrap();
    match ctx_guard.as_ref().and_then(|c| c.state.get_next_boot_dir()) {
        Some(dir) => {
            let s = CString::new(dir).unwrap();
            s.into_raw()
        }
        None => std::ptr::null(),
    }
}

#[no_mangle]
pub extern "C" fn fhp_confirm_health() {
    let mut ctx_guard = CONTEXT.lock().unwrap();
    if let Some(ctx) = ctx_guard.as_mut() {
        watchdog::confirm_health(&mut ctx.state, &ctx.data_dir);
    }
}

#[no_mangle]
pub extern "C" fn fhp_free_string(s: *const c_char) {
    if !s.is_null() {
        unsafe { drop(CString::from_raw(s as *mut c_char)) };
    }
}

#[no_mangle]
pub extern "C" fn fhp_state_json() -> *const c_char {
    let ctx_guard = CONTEXT.lock().unwrap();
    let json = match ctx_guard.as_ref() {
        Some(ctx) => serde_json::to_string_pretty(&ctx.state).unwrap_or_default(),
        None => "{}".to_string(),
    };
    CString::new(json).unwrap().into_raw()
}
```

- [ ] **Step 2: 更新 lib.rs**

```rust
// src/lib.rs
pub mod state;
pub mod verify;
pub mod watchdog;
pub mod ffi;
```

- [ ] **Step 3: 写 C 头文件**

```c
// include/flutter_hotpatch_updater.h
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
```

- [ ] **Step 4: 编写集成测试**

```rust
// tests/integration_test.rs
use std::path::Path;
use flutter_hotpatch_updater::{state::*, verify, watchdog};
use ring::signature::{Ed25519KeyPair, KeyPair};

fn gen_key() -> (Vec<u8>, Vec<u8>) {
    let rng = ring::rand::SystemRandom::new();
    let doc = Ed25519KeyPair::generate_pkcs8(&rng).unwrap();
    let pair = Ed25519KeyPair::from_pkcs8(doc.as_ref()).unwrap();
    (doc.as_ref().to_vec(), pair.public_key().as_ref().to_vec())
}

fn make_bundle(dir: &Path, pkcs8: &[u8], fingerprint: &str) -> String {
    // Write a minimal valid patch bundle
    let bytecode_dir = dir.join("bytecode");
    std::fs::create_dir_all(&bytecode_dir).unwrap();
    let dill = b"\x90\x90\x90";
    std::fs::write(bytecode_dir.join("patch.dill"), dill).unwrap();

    let entry_table = b"\x00\x00\x00\x00";
    std::fs::write(dir.join("entry_table.bin"), entry_table).unwrap();
    let cid_map = b"\x00\x00\x00\x00";
    std::fs::write(dir.join("cid_map.bin"), cid_map).unwrap();

    let manifest = serde_json::json!({
        "format_version": "1",
        "patch_id": "test-patch-1",
        "target_build_fingerprint": fingerprint,
        "dart_sdk_commit": "abc",
        "baseline_sha256": "",
        "changed_functions": [],
        "icf_affected": [],
        "affected_closure": [],
        "class_hierarchy_changed": false,
        "class_hierarchy": {},
        "sig_alg": "ed25519",
        "cert_chain": [],
        "artifacts": [
            {"path": "bytecode/patch.dill", "sha256": verify::sha256_hex(dill), "size": 3},
            {"path": "entry_table.bin", "sha256": verify::sha256_hex(entry_table), "size": 4},
            {"path": "cid_map.bin", "sha256": verify::sha256_hex(cid_map), "size": 4},
        ]
    });

    let pair = Ed25519KeyPair::from_pkcs8(pkcs8).unwrap();
    let sig = pair.sign(&verify::canonical_bytes(&manifest));
    std::fs::write(dir.join("manifest.json"),
        serde_json::to_string_pretty(&manifest).unwrap()).unwrap();
    std::fs::write(dir.join("manifest.sig"), sig.as_ref()).unwrap();

    "test-patch-1".to_string()
}

#[test]
fn test_full_pipeline_verified_then_rollback() {
    let data_dir = tempfile::tempdir().unwrap();
    let bundle_dir = tempfile::tempdir().unwrap();
    let (pkcs8, pub_key) = gen_key();
    let fingerprint = "1.0+1";

    make_bundle(bundle_dir.path(), &pkcs8, fingerprint);

    // Stage + verify
    let blacklist: Vec<String> = vec![];
    let patch_id = verify::verify_bundle(bundle_dir.path(), &pub_key, fingerprint, &blacklist)
        .expect("bundle should verify");
    assert_eq!(patch_id, "test-patch-1");

    // State machine
    let mut state = UpdaterState::load_or_default(data_dir.path());
    state.set_staged(bundle_dir.path().to_str().unwrap().to_string(), patch_id);
    state.mark_verified();
    state.mark_next_boot();
    state.save(data_dir.path()).unwrap();
    assert!(state.get_next_boot_dir().is_some());

    // Cold boot 1: NextBoot → PendingConfirmation
    watchdog::on_cold_boot(&mut state, data_dir.path());
    assert_eq!(state.stage, PatchStage::PendingConfirmation);

    // Cold boot 2 without confirm = crash → auto-rollback
    watchdog::on_cold_boot(&mut state, data_dir.path());
    assert_eq!(state.stage, PatchStage::Baseline);
    assert!(state.blacklist.contains(&"test-patch-1".to_string()));
    assert!(state.get_next_boot_dir().is_none());
}

#[test]
fn test_full_pipeline_healthy_confirm() {
    let data_dir = tempfile::tempdir().unwrap();
    let bundle_dir = tempfile::tempdir().unwrap();
    let (pkcs8, pub_key) = gen_key();
    let fingerprint = "1.0+2";
    make_bundle(bundle_dir.path(), &pkcs8, fingerprint);

    let blacklist: Vec<String> = vec![];
    let patch_id = verify::verify_bundle(bundle_dir.path(), &pub_key, fingerprint, &blacklist)
        .expect("bundle should verify");

    let mut state = UpdaterState::load_or_default(data_dir.path());
    state.set_staged(bundle_dir.path().to_str().unwrap().to_string(), patch_id);
    state.mark_next_boot();
    watchdog::on_cold_boot(&mut state, data_dir.path()); // → PendingConfirmation
    watchdog::confirm_health(&mut state, data_dir.path()); // → ConfirmedGood
    assert_eq!(state.stage, PatchStage::ConfirmedGood);
    assert!(state.blacklist.is_empty());
}
```

- [ ] **Step 5: 运行全部测试**

```bash
cd ~/Documents/flutter_hot_patcher/tools/updater
cargo test 2>&1 | tail -20
```

Expected: all tests pass, `test result: ok. N passed; 0 failed`

If `cargo build` fails with iOS/macOS linking issues, add to Cargo.toml:
```toml
[target.'cfg(target_os = "ios")'.dependencies]
# No special iOS deps needed for this library
```

- [ ] **Step 6: 构建 static library**

```bash
cd ~/Documents/flutter_hot_patcher/tools/updater
cargo build --release 2>&1 | tail -5
ls -la target/release/libflutter_hotpatch_updater.a 2>/dev/null || \
ls -la target/release/libflutter_hotpatch_updater.dylib 2>/dev/null
```

- [ ] **Step 7: 最终 commit**

```bash
cd ~/Documents/flutter_hot_patcher

# Copy docs
cp /tmp/2026-08-04-4c-updater-design.md docs/superpowers/specs/
cp /tmp/2026-08-04-4c-updater-plan.md docs/superpowers/plans/

git add tools/updater/ docs/superpowers/
git commit -m "feat(4-C): COMPLETE — Updater Rust library

verify.rs: Ed25519 + artifact SHA-256 + fingerprint
state.rs: PatchStage state machine + JSON persistence
watchdog.rs: boot-loop detection + auto-blacklist
ffi.rs: C FFI API (fhp_init/stage_patch/confirm_health)
integration tests: full pipeline + rollback verified

Co-Authored-By: Claude Sonnet 4.6 (1M context) <noreply@anthropic.com>"
```
