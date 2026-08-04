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

pub fn sha256_hex(data: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(data);
    hex::encode(hasher.finalize())
}

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

pub fn verify_bundle(
    bundle_dir: &std::path::Path,
    public_key_bytes: &[u8],
    app_fingerprint: &str,
    blacklist: &[String],
) -> Result<String, VerifyError> {
    let manifest_bytes = std::fs::read(bundle_dir.join("manifest.json"))
        .map_err(|e| VerifyError::MalformedData(e.to_string()))?;
    let sig_bytes = std::fs::read(bundle_dir.join("manifest.sig"))
        .map_err(|e| VerifyError::MalformedData(e.to_string()))?;
    let manifest: serde_json::Value = serde_json::from_slice(&manifest_bytes)
        .map_err(|e| VerifyError::MalformedData(e.to_string()))?;

    verify_manifest_signature(&manifest, &sig_bytes, public_key_bytes)?;

    let artifacts = manifest
        .get("artifacts")
        .and_then(|v| v.as_array())
        .map(|v| v.as_slice())
        .unwrap_or(&[]);
    for artifact in artifacts {
        let path = artifact.get("path").and_then(|v| v.as_str()).unwrap_or("");
        let expected = artifact.get("sha256").and_then(|v| v.as_str()).unwrap_or("");
        let data = std::fs::read(bundle_dir.join(path))
            .map_err(|e| VerifyError::MalformedData(format!("{path}: {e}")))?;
        verify_artifact_hash(&data, expected)?;
    }

    verify_fingerprint(&manifest, app_fingerprint)?;

    let patch_id = manifest
        .get("patch_id")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    if blacklist.contains(&patch_id.to_string()) {
        return Err(VerifyError::BlacklistedPatch { patch_id: patch_id.to_string() });
    }

    Ok(patch_id.to_string())
}

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

    fn sign_test(pkcs8: &[u8], manifest: &serde_json::Value) -> Vec<u8> {
        use ring::signature::{Ed25519KeyPair, KeyPair};
        let pair = Ed25519KeyPair::from_pkcs8(pkcs8).unwrap();
        pair.sign(&canonical_bytes(manifest)).as_ref().to_vec()
    }

    #[test]
    fn test_canonical_bytes_deterministic() {
        let a = canonical_bytes(&serde_json::json!({"b":2,"a":1}));
        let b = canonical_bytes(&serde_json::json!({"a":1,"b":2}));
        assert_eq!(a, b);
    }

    #[test]
    fn test_verify_manifest_ok() {
        let (pkcs8, pub_key) = test_key_pair();
        let manifest = serde_json::json!({"patch_id":"test-1","format_version":"1"});
        let sig = sign_test(&pkcs8, &manifest);
        assert!(verify_manifest_signature(&manifest, &sig, &pub_key).is_ok());
    }

    #[test]
    fn test_verify_manifest_tampered_fails() {
        let (pkcs8, pub_key) = test_key_pair();
        let original = serde_json::json!({"patch_id":"test-1"});
        let sig = sign_test(&pkcs8, &original);
        let tampered = serde_json::json!({"patch_id":"tampered"});
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
        assert!(verify_artifact_hash(b"hello", "deadbeef").is_err());
    }
}
