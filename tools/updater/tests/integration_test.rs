use flutter_hotpatch_updater::{state::*, verify, watchdog};
use ring::signature::{Ed25519KeyPair, KeyPair};
use std::path::Path;

fn gen_key() -> (Vec<u8>, Vec<u8>) {
    let rng = ring::rand::SystemRandom::new();
    let doc = Ed25519KeyPair::generate_pkcs8(&rng).unwrap();
    let pair = Ed25519KeyPair::from_pkcs8(doc.as_ref()).unwrap();
    (doc.as_ref().to_vec(), pair.public_key().as_ref().to_vec())
}

fn make_bundle(dir: &Path, pkcs8: &[u8], fingerprint: &str) {
    let bytecode_dir = dir.join("bytecode");
    std::fs::create_dir_all(&bytecode_dir).unwrap();
    let dill = b"\x90\x90\x90";
    let entry = b"\x00\x00\x00\x00";
    let cid = b"\x00\x00\x00\x00";
    std::fs::write(bytecode_dir.join("patch.dill"), dill).unwrap();
    std::fs::write(dir.join("entry_table.bin"), entry).unwrap();
    std::fs::write(dir.join("cid_map.bin"), cid).unwrap();

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
            {"path": "entry_table.bin", "sha256": verify::sha256_hex(entry), "size": 4},
            {"path": "cid_map.bin", "sha256": verify::sha256_hex(cid), "size": 4},
        ]
    });

    let pair = Ed25519KeyPair::from_pkcs8(pkcs8).unwrap();
    let sig = pair.sign(&verify::canonical_bytes(&manifest));
    std::fs::write(dir.join("manifest.json"),
        serde_json::to_string_pretty(&manifest).unwrap()).unwrap();
    std::fs::write(dir.join("manifest.sig"), sig.as_ref()).unwrap();
}

#[test]
fn test_full_pipeline_crash_rollback() {
    let data_dir = tempfile::tempdir().unwrap();
    let bundle_dir = tempfile::tempdir().unwrap();
    let (pkcs8, pub_key) = gen_key();
    make_bundle(bundle_dir.path(), &pkcs8, "1.0+1");

    let blacklist: Vec<String> = vec![];
    let patch_id = verify::verify_bundle(bundle_dir.path(), &pub_key, "1.0+1", &blacklist)
        .expect("should verify");
    assert_eq!(patch_id, "test-patch-1");

    let mut state = UpdaterState::load_or_default(data_dir.path());
    state.set_staged(bundle_dir.path().to_str().unwrap().to_string(), patch_id);
    state.mark_next_boot();
    watchdog::on_cold_boot(&mut state, data_dir.path());
    assert_eq!(state.stage, PatchStage::PendingConfirmation);
    assert!(state.get_next_boot_dir().is_some());

    // Simulate crash: next cold boot without confirm
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
    make_bundle(bundle_dir.path(), &pkcs8, "1.0+2");

    let blacklist: Vec<String> = vec![];
    let patch_id = verify::verify_bundle(bundle_dir.path(), &pub_key, "1.0+2", &blacklist)
        .expect("should verify");

    let mut state = UpdaterState::load_or_default(data_dir.path());
    state.set_staged(bundle_dir.path().to_str().unwrap().to_string(), patch_id);
    state.mark_next_boot();
    watchdog::on_cold_boot(&mut state, data_dir.path()); // → PendingConfirmation
    watchdog::confirm_health(&mut state, data_dir.path()); // → ConfirmedGood
    assert_eq!(state.stage, PatchStage::ConfirmedGood);
    assert!(state.blacklist.is_empty());
}

#[test]
fn test_wrong_fingerprint_rejected() {
    let bundle_dir = tempfile::tempdir().unwrap();
    let (pkcs8, pub_key) = gen_key();
    make_bundle(bundle_dir.path(), &pkcs8, "1.0+1");
    let blacklist: Vec<String> = vec![];
    let result = verify::verify_bundle(bundle_dir.path(), &pub_key, "WRONG_FP", &blacklist);
    assert!(result.is_err());
}

#[test]
fn test_blacklisted_patch_rejected() {
    let bundle_dir = tempfile::tempdir().unwrap();
    let (pkcs8, pub_key) = gen_key();
    make_bundle(bundle_dir.path(), &pkcs8, "1.0+1");
    let blacklist = vec!["test-patch-1".to_string()];
    let result = verify::verify_bundle(bundle_dir.path(), &pub_key, "1.0+1", &blacklist);
    assert!(result.is_err());
}
