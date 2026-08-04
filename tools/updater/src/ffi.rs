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
    if std::fs::create_dir_all(&data_path).is_err() { return -1; }
    let mut state = UpdaterState::load_or_default(&data_path);
    state.app_build_fingerprint = fingerprint.clone();
    watchdog::on_cold_boot(&mut state, &data_path);
    let mut ctx = CONTEXT.lock().unwrap();
    *ctx = Some(UpdaterContext { data_dir: data_path, state, app_fingerprint: fingerprint });
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
        Some(dir) => CString::new(dir).unwrap().into_raw(),
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
