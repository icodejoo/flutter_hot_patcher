use flutter_hotpatch_updater::shorebird_adapter::{ShorebirdState, ShorebirdPatchState};

#[test]
fn test_shorebird_state_machine_transitions() {
    let mut state = ShorebirdState::new();
    assert_eq!(state.patch_state, ShorebirdPatchState::None);
    state.begin_download("http://example.com/patch.zst", "abc123hash");
    assert!(matches!(state.patch_state, ShorebirdPatchState::Downloading { .. }));
    state.mark_downloaded("/data/patches/1/patch.zst");
    assert!(matches!(state.patch_state, ShorebirdPatchState::Downloaded { .. }));
    state.mark_installed(1);
    assert!(matches!(state.patch_state, ShorebirdPatchState::Installed { .. }));
}

#[test]
fn test_rolled_back_patch_numbers_blacklist() {
    let mut state = ShorebirdState::new();
    state.mark_installed(3);
    state.mark_bad(3, "BootCrash");
    assert!(state.rolled_back_patch_numbers.contains(&3));
    assert!(state.is_patch_blacklisted(3));
}

#[test]
fn test_boot_loop_detection() {
    let mut state = ShorebirdState::new();
    state.mark_installed(2);
    state.on_boot_start();
    let rolled_back = state.check_boot_loop();
    assert!(rolled_back);
    assert!(state.rolled_back_patch_numbers.contains(&2));
}

#[test]
fn test_save_and_load_roundtrip() {
    let dir = tempfile::tempdir().unwrap();
    let mut state = ShorebirdState::new();
    state.begin_download("http://example.com/1.zst", "sig1");
    state.mark_downloaded("/tmp/1.zst");
    state.mark_installed(7);
    state.save(dir.path()).unwrap();

    let loaded = ShorebirdState::load_or_new(dir.path());
    assert!(matches!(loaded.patch_state, ShorebirdPatchState::Installed { patch_number: 7 }));
}
