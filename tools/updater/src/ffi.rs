use std::ffi::{CStr, CString};
use std::os::raw::{c_char, c_int, c_ulong};
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
        let crashed_patch = shorebird.rolled_back_patch_numbers.last().copied();
        let evt = PatchEvent {
            app_id: "com.hotpatch.demo".to_string(),
            client_id: fingerprint.clone(),
            patch_number: crashed_patch,
            release_version: fingerprint.clone(),
            timestamp: String::new(),
            message: "BootLoop".to_string(),
        };
        shorebird.queue_event(evt);
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

fn ureq_agent() -> ureq::Agent {
    ureq::AgentBuilder::new()
        .timeout_connect(std::time::Duration::from_secs(15))
        .timeout(std::time::Duration::from_secs(30))
        .build()
}

#[no_mangle]
pub extern "C" fn fhp_check_update(
    server_url: *const c_char,
    app_id: *const c_char,
    release_version: *const c_char,
    _channel: *const c_char,
) -> *const c_char {
    let server_url = unsafe { CStr::from_ptr(server_url) }.to_string_lossy().to_string();
    let app_id = unsafe { CStr::from_ptr(app_id) }.to_string_lossy().to_string();
    let release_version = unsafe { CStr::from_ptr(release_version) }.to_string_lossy().to_string();

    // Read current patch number from state
    let current_patch_number: i64 = {
        let ctx_guard = CONTEXT.lock().unwrap();
        ctx_guard.as_ref()
            .and_then(|c| c.state.staged_patch_id.as_ref())
            .and_then(|id| id.parse::<i64>().ok())
            .unwrap_or(-1)
    };

    let body = serde_json::json!({
        "app_id": app_id,
        "release_version": release_version,
        "patch_number": if current_patch_number < 0 { serde_json::Value::Null } else { current_patch_number.into() },
    });

    let url = format!("{}/api/v1/patches/check", server_url.trim_end_matches('/'));
    let result = ureq_agent().post(&url)
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
    bundle_dir_hint: *const c_char,
    patch_number: i32,
    pubkey_hex: *const c_char,
) -> i32 {
    use sha2::Digest;

    let url = unsafe { CStr::from_ptr(download_url) }.to_string_lossy().to_string();
    let expected_hash = unsafe { CStr::from_ptr(expected_sha256_hex) }.to_string_lossy().to_string();
    let bundle_dir_hint = unsafe { CStr::from_ptr(bundle_dir_hint) }.to_string_lossy().to_string();
    let pubkey = unsafe { CStr::from_ptr(pubkey_hex) }.to_string_lossy().to_string();

    // Download bytes
    let resp = match ureq_agent().get(&url).call() {
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

    // Decompress zstd -> tar bytes
    let tar_bytes = match zstd::decode_all(std::io::Cursor::new(&bytes)) {
        Ok(d) => d,
        Err(e) => { eprintln!("[updater] zstd decompress failed: {}", e); return -4; }
    };

    // Determine destination dir
    let patch_dir = if bundle_dir_hint.is_empty() {
        let ctx_guard = CONTEXT.lock().unwrap();
        match ctx_guard.as_ref() {
            Some(ctx) => ctx.data_dir.join("patches").join(patch_number.to_string()),
            None => return -2,
        }
    } else {
        std::path::PathBuf::from(&bundle_dir_hint)
    };

    if let Err(e) = std::fs::create_dir_all(&patch_dir) {
        eprintln!("[updater] mkdir failed: {}", e);
        return -5;
    }

    // Untar into patch_dir
    let mut archive = tar::Archive::new(std::io::Cursor::new(&tar_bytes));
    for entry in match archive.entries() {
        Ok(e) => e,
        Err(e) => { eprintln!("[updater] tar entries failed: {}", e); return -7; }
    } {
        let mut entry = match entry {
            Ok(e) => e,
            Err(e) => { eprintln!("[updater] tar entry failed: {}", e); return -7; }
        };
        let entry_path = match entry.path() {
            Ok(p) => p.to_path_buf(),
            Err(_) => continue,
        };
        // strip leading "bundle/" component
        let rel = entry_path.components()
            .skip(1)
            .collect::<std::path::PathBuf>();
        if rel.as_os_str().is_empty() { continue; }
        let dest = patch_dir.join(&rel);
        if let Some(parent) = dest.parent() {
            std::fs::create_dir_all(parent).ok();
        }
        if let Err(e) = entry.unpack(&dest) {
            eprintln!("[updater] unpack {:?} failed: {}", dest, e);
            return -8;
        }
    }

    // Verify bundle signature
    let pub_bytes = match hex::decode(&pubkey) {
        Ok(b) => b,
        Err(_) => { eprintln!("[updater] bad pubkey hex"); return -9; }
    };

    let mut ctx_guard = CONTEXT.lock().unwrap();
    let ctx = match ctx_guard.as_mut() { Some(c) => c, None => return -2 };

    let bundle_path_str = patch_dir.to_string_lossy().to_string();
    match verify::verify_bundle(&patch_dir, &pub_bytes, &ctx.app_fingerprint, &ctx.state.blacklist) {
        Ok(patch_id) => {
            ctx.state.set_staged(bundle_path_str, patch_id);
            ctx.state.mark_verified();
            ctx.state.mark_next_boot();
            ctx.state.save(&ctx.data_dir).ok();
            ctx.shorebird.mark_downloaded(&patch_dir.join("patch.bin").to_string_lossy().to_string());
            ctx.shorebird.mark_installed(patch_number as u32);
            ctx.shorebird.save(&ctx.data_dir).ok();
            0
        }
        Err(e) => { eprintln!("[updater] verify_bundle failed: {:?}", e); -10 }
    }
}


/// Apply a zstd-compressed bipatch diff to a base snapshot region and write the
/// patched result to `out_path`.
///
/// `base_ptr` / `base_len` point to the in-memory snapshot region (e.g.
/// `kDartIsolateSnapshotData` from the linked binary — no file I/O needed).
/// `diff_path` is the path to the downloaded `.vmdiff` file (zstd-compressed bipatch).
/// `out_path` is where the full patched region will be written.
/// Returns 0 on success, negative on error.
#[no_mangle]
pub extern "C" fn fhp_vmcode_stage(
    base_ptr: *const u8,
    base_len: c_ulong,
    diff_path: *const c_char,
    out_path: *const c_char,
) -> c_int {
    let diff_path = unsafe { CStr::from_ptr(diff_path) }.to_string_lossy().to_string();
    let out_path  = unsafe { CStr::from_ptr(out_path)  }.to_string_lossy().to_string();

    // Safety: caller guarantees pointer validity for the duration of this call.
    let base: &[u8] = unsafe { std::slice::from_raw_parts(base_ptr, base_len as usize) };

    // Read diff file
    let compressed = match std::fs::read(&diff_path) {
        Ok(b) => b,
        Err(e) => { eprintln!("[vmcode] read diff failed: {}", e); return -1; }
    };

    // Decompress zstd envelope
    let patch_bytes = match zstd::decode_all(std::io::Cursor::new(&compressed)) {
        Ok(b) => b,
        Err(e) => { eprintln!("[vmcode] zstd decompress failed: {}", e); return -2; }
    };

    // Apply bipatch
    let patched = {
        use bipatch::Reader;
        let patch_cursor = std::io::Cursor::new(&patch_bytes);
        let base_cursor  = std::io::Cursor::new(base);
        let mut reader = match Reader::new(patch_cursor, base_cursor) {
            Ok(r) => r,
            Err(e) => { eprintln!("[vmcode] bipatch init failed: {}", e); return -3; }
        };
        let mut out = Vec::new();
        if let Err(e) = std::io::Read::read_to_end(&mut reader, &mut out) {
            eprintln!("[vmcode] bipatch apply failed: {}", e); return -4;
        }
        out
    };

    // Ensure parent dir exists and write
    if let Some(parent) = std::path::Path::new(&out_path).parent() {
        std::fs::create_dir_all(parent).ok();
    }
    if let Err(e) = std::fs::write(&out_path, &patched) {
        eprintln!("[vmcode] write staged failed: {}", e); return -5;
    }

    eprintln!("[vmcode] staged {} bytes → {}", patched.len(), out_path);
    0
}

#[no_mangle]
pub extern "C" fn fhp_flush_events(server_url: *const c_char) -> i32 {
    let server_url = unsafe { CStr::from_ptr(server_url) }.to_string_lossy().to_string();
    let mut ctx_guard = CONTEXT.lock().unwrap();
    let ctx = match ctx_guard.as_mut() { Some(c) => c, None => return -1 };
    let events = ctx.shorebird.take_queued_events();
    if events.is_empty() { return 0; }
    ctx.shorebird.save(&ctx.data_dir).ok();
    drop(ctx_guard);

    let url = format!("{}/api/v1/events", server_url.trim_end_matches('/'));
    let body = serde_json::to_string(&events).unwrap_or_default();
    match ureq_agent().post(&url)
        .set("Content-Type", "application/json")
        .send_string(&body)
    {
        Ok(_) => {
            eprintln!("[updater] flushed {} events to {}", events.len(), url);
            0
        }
        Err(e) => {
            eprintln!("[updater] flush_events failed: {}", e);
            -2
        }
    }
}
