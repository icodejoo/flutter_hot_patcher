use crate::state::{PatchStage, UpdaterState};
use std::path::Path;

pub fn on_cold_boot(state: &mut UpdaterState, data_dir: &Path) {
    match state.stage {
        PatchStage::PendingConfirmation => {
            let id = state.staged_patch_id.clone().unwrap_or_default();
            eprintln!("[updater] Boot-loop detected for '{}', auto-rollback", id);
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

pub fn confirm_health(state: &mut UpdaterState, data_dir: &Path) {
    state.confirm_health();
    state.save(data_dir).ok();
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::state::{PatchStage, UpdaterState};

    #[test]
    fn test_next_boot_becomes_pending() {
        let dir = tempfile::tempdir().unwrap();
        let mut state = UpdaterState::load_or_default(dir.path());
        state.set_staged("/tmp/b".to_string(), "p1".to_string());
        state.mark_next_boot();
        on_cold_boot(&mut state, dir.path());
        assert_eq!(state.stage, PatchStage::PendingConfirmation);
    }

    #[test]
    fn test_crash_triggers_blacklist() {
        let dir = tempfile::tempdir().unwrap();
        let mut state = UpdaterState::load_or_default(dir.path());
        state.set_staged("/tmp/b".to_string(), "bad-patch".to_string());
        state.begin_apply();
        on_cold_boot(&mut state, dir.path());
        assert_eq!(state.stage, PatchStage::Baseline);
        assert!(state.blacklist.contains(&"bad-patch".to_string()));
    }

    #[test]
    fn test_confirm_health_ok() {
        let dir = tempfile::tempdir().unwrap();
        let mut state = UpdaterState::load_or_default(dir.path());
        state.set_staged("/tmp/b".to_string(), "good-patch".to_string());
        state.begin_apply();
        confirm_health(&mut state, dir.path());
        assert_eq!(state.stage, PatchStage::ConfirmedGood);
        assert!(state.blacklist.is_empty());
    }
}
