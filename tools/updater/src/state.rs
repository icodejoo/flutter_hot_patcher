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

    pub fn mark_verified(&mut self) { self.stage = PatchStage::Verified; }
    pub fn mark_next_boot(&mut self) { self.stage = PatchStage::NextBoot; }
    pub fn begin_apply(&mut self) { self.stage = PatchStage::PendingConfirmation; }

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

#[cfg(test)]
mod tests {
    use super::*;

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

    #[test]
    fn test_auto_rollback_adds_to_blacklist() {
        let dir = tempfile::tempdir().unwrap();
        let mut state = UpdaterState::load_or_default(dir.path());
        state.set_staged("/tmp/b".to_string(), "bad".to_string());
        state.auto_rollback();
        assert_eq!(state.stage, PatchStage::Baseline);
        assert!(state.blacklist.contains(&"bad".to_string()));
    }
}
