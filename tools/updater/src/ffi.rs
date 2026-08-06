use std::ffi::{CStr, CString};
use std::os::raw::c_char;
use std::io::Read;
use std::path::PathBuf;
use std::sync::Mutex;

use crate::state::UpdaterState;
use crate::watchdog;
use crate::verify;
use crate::shorebird_adapter::{ShorebirdState, PatchEvent};

struct UpdaterContext {
    data_dir: PathBuf,
    state: UpdaterState,
    app_fingerprint: String,
    shorebird: ShorebirdState,
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
    if std::fs::create_dir_all(&data_path).is_err() { return -1; }
    let mut state = UpdaterState::load_or_default(&data_path);
    state.app_build_fingerprint = fingerprint.clone();
    watchdog::on_cold_boot(&mut state, &data_path);
    let mut shorebird = ShorebirdState::load_or_new(&data_path);
    if shorebird.check_boot_loop() {
        shorebird.save(&data_path).ok();
    }
    shorebird.on_boot_start();
    shorebird.save(&data_path).ok();
    let mut ctx = CONTEXT.lock().unwrap();
    *ctx = Some(UpdaterContext { data_dir: data_path, state, app_fingerprint: fingerprint, shorebird });
    0
}

#[no_mangle]
pub extern "C" fn fhp_stage_patch(
    bundle_dir: *const c_char,
    pubkey_hex: *const c_char,
) -> i32 {
    let bundle = unsafe { CStr::from_ptr(bundle_dir) }.to_string_lossy().to_string();
    let pubkey = unsafe { CStr::from_ptr(pubkey_hex) }.to_string_lossy().to_string();
    let pub_bytes = match hex::decode(&pubkey) { Ok(b) => b, Err(_) => return -1 };
    let mut ctx_guard = CONTEXT.lock().unwrap();
    let ctx = match ctx_guard.as_mut() { Some(c) => c, None => return -2 };
    let bundle_path = PathBuf::from(&bundle);
    match verify::verify_bundle(&bundle_path, &pub_bytes, &ctx.app_fingerprint, &ctx.state.blacklist) {
        Ok(patch_id) => {
            ctx.state.set_staged(bundle.clone(), patch_id);
            ctx.state.mark_verified();
            ctx.state.mark_next_boot();
            ctx.state.save(&ctx.data_dir).ok();
            0
        }
        Err(e) => { eprintln!("[updater] stage_patch failed: {:?}", e); -3 }
    }
}

#[no_mangle]
pub extern "C" fn fhp_get_next_boot_patch_dir() -> *const c_char {
    let ctx_guard = CONTEXT.lock().unwrap();
    match ctx_guard.as_ref().and_then(|c| c.state.get_next_boot_dir()) {
        Some(dir) => CString::new(dir).unwrap_or_default().into_raw(),
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
    CString::new(json).unwrap_or_default().into_raw()
}

#[no_mangle]
pub extern "C" fn fhp_check_update(
    server_url: *const c_char,
    app_id: *const c_char,
    release_version: *const c_char,
    current_patch_number: i32,
) -> *const c_char {
    let server_url = unsafe { CStr::from_ptr(server_url) }.to_string_lossy().to_string();
    let app_id = unsafe { CStr::from_ptr(app_id) }.to_string_lossy().to_string();
    let release_version = unsafe { CStr::from_ptr(release_version) }.to_string_lossy().to_string();

    let body = serde_json::json!({
        "app_id": app_id,
        "release_version": release_version,
        "patch_number": if current_patch_number < 0 { serde_json::Value::Null } else { current_patch_number.into() },
    });

    let url = format!("{}/api/v1/patches/check", server_url.trim_end_matches('/'));
    let result = ureq::post(&url)
        .set("Content-Type", "application/json")
        .send_string(&body.to_string());

    let json_str = match result {
        Ok(resp) => resp.into_string().unwrap_or_default(),
        Err(e) => {
            let err = serde_json::json!({ "error": e.to_string() });
            err.to_string()
        }
    };

    CString::new(json_str).unwrap_or_default().into_raw()
}

#[no_mangle]
pub extern "C" fn fhp_download_and_stage(
    download_url: *const c_char,
    expected_sha256_hex: *const c_char,
    patch_number: u32,
    bundle_dir: *const c_char,
) -> i32 {
    use sha2::Digest;

    let url = unsafe { CStr::from_ptr(download_url) }.to_string_lossy().to_string();
    let expected_hash = unsafe { CStr::from_ptr(expected_sha256_hex) }.to_string_lossy().to_string();
    let bundle_dir = unsafe { CStr::from_ptr(bundle_dir) }.to_string_lossy().to_string();

    // Download bytes
    let resp = match ureq::get(&url).call() {
        Ok(r) => r,
        Err(e) => { eprintln!("[updater] download failed: {}", e); return -1; }
    };
    let mut bytes = Vec::new();
    if let Err(e) = resp.into_reader().read_to_end(&mut bytes) {
        eprintln!("[updater] read failed: {}", e);
        return -2;
    }

    // Verify sha256
    let actual_hash = hex::encode(sha2::Sha256::digest(&bytes));
    if !expected_hash.is_empty() && actual_hash != expected_hash.to_lowercase() {
        eprintln!("[updater] hash mismatch: {} != {}", actual_hash, expected_hash);
        return -3;
    }

    // Decompress zstd
    let decompressed = match zstd::decode_all(std::io::Cursor::new(&bytes)) {
        Ok(d) => d,
        Err(e) => { eprintln!("[updater] zstd decompress failed: {}", e); return -4; }
    };

    // Write to bundle_dir
    let patch_dir = std::path::PathBuf::from(&bundle_dir);
    if let Err(e) = std::fs::create_dir_all(&patch_dir) {
        eprintln!("[updater] mkdir failed: {}", e);
        return -5;
    }
    let out_path = patch_dir.join("patch.bin");
    if let Err(e) = std::fs::write(&out_path, &decompressed) {
        eprintln!("[updater] write failed: {}", e);
        return -6;
    }

    // Update shorebird state
    let path_str = match out_path.to_str() {
        Some(s) => s.to_string(),
        None => return -6,
    };

    let mut ctx_guard = CONTEXT.lock().unwrap();
    if let Some(ctx) = ctx_guard.as_mut() {
        ctx.shorebird.mark_downloaded(&path_str);
        ctx.shorebird.mark_installed(patch_number);
        ctx.shorebird.save(&ctx.data_dir).ok();
    }

    0
}
