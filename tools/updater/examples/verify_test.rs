fn main() {
    let pubkey_hex = "70fe9e96bec44e7a6ab78f98fd6e931cd550b615fab4cd501053e80c72f8ef55";
    let pub_bytes = hex::decode(pubkey_hex).expect("bad pubkey hex");
    
    for (label, manifest_path, sig_path) in [
        ("OTA bundle (patch-v2)", "/Users/Cruz/Documents/flutter_hot_patcher/tools/patch_server/patches/1.0+1/patch-v2/manifest.json", "/Users/Cruz/Documents/flutter_hot_patcher/tools/patch_server/patches/1.0+1/patch-v2/manifest.sig"),
        ("Embedded patch_bundle", "/Users/Cruz/Documents/flutter_hot_patcher/spikes/m3_ios_realdevice/HotPatchDemo/HotPatchDemo/patch_bundle/manifest.json", "/Users/Cruz/Documents/flutter_hot_patcher/spikes/m3_ios_realdevice/HotPatchDemo/HotPatchDemo/patch_bundle/manifest.sig"),
    ] {
        let manifest_bytes = std::fs::read(manifest_path).unwrap_or_default();
        let sig_bytes = std::fs::read(sig_path).unwrap_or_default();
        
        if manifest_bytes.is_empty() || sig_bytes.is_empty() {
            println!("{}: MISSING FILES", label);
            continue;
        }
        
        let manifest: serde_json::Value = serde_json::from_slice(&manifest_bytes).unwrap();
        
        fn canonical(v: &serde_json::Value) -> serde_json::Value {
            match v {
                serde_json::Value::Object(map) => {
                    let mut sorted: Vec<_> = map.iter().collect();
                    sorted.sort_by_key(|(k, _)| k.as_str());
                    serde_json::Value::Object(sorted.into_iter().map(|(k, v)| (k.clone(), canonical(v))).collect())
                }
                serde_json::Value::Array(arr) => serde_json::Value::Array(arr.iter().map(canonical).collect()),
                _ => v.clone(),
            }
        }
        let bytes = canonical(&manifest).to_string().into_bytes();
        
        use ed25519_dalek::{VerifyingKey, Signature, Verifier};
        let key_array: [u8; 32] = pub_bytes.as_slice().try_into().unwrap();
        let key = VerifyingKey::from_bytes(&key_array).unwrap();
        let sig_array: [u8; 64] = sig_bytes.as_slice().try_into().unwrap();
        let sig = Signature::from_bytes(&sig_array);
        
        match key.verify(&bytes, &sig) {
            Ok(()) => println!("{}: SIGNATURE VALID", label),
            Err(e) => println!("{}: SIGNATURE INVALID: {}", label, e),
        }
    }
}
