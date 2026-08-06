use serde::{Deserialize, Serialize};
use std::path::Path;

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum ShorebirdPatchState {
    None,
    Downloading { url: String, signature: String },
    Downloaded { url: String, signature: String, path: String },
    Installed { patch_number: u32 },
    Bad { patch_number: u32, reason: String },
}

#[derive(Debug, Serialize, Deserialize)]
pub struct ShorebirdState {
    pub patch_state: ShorebirdPatchState,
    pub next_boot_patch: Option<u32>,
    pub last_booted_patch: Option<u32>,
    pub currently_booting_patch: Option<u32>,
    pub rolled_back_patch_numbers: Vec<u32>,
    pub queued_events: Vec<PatchEvent>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PatchEvent {
    pub app_id: String,
    pub client_id: String,
    pub patch_number: Option<u32>,
    pub release_version: String,
    pub timestamp: String,
    pub message: String,
}

const STATE_FILE: &str = "shorebird_state.json";

impl ShorebirdState {
    pub fn new() -> Self {
        ShorebirdState {
            patch_state: ShorebirdPatchState::None,
            next_boot_patch: None,
            last_booted_patch: None,
            currently_booting_patch: None,
            rolled_back_patch_numbers: Vec::new(),
            queued_events: Vec::new(),
        }
    }

    pub fn load_or_new(data_dir: &Path) -> Self {
        let path = data_dir.join(STATE_FILE);
        if let Ok(data) = std::fs::read_to_string(&path) {
            if let Ok(state) = serde_json::from_str::<ShorebirdState>(&data) {
                return state;
            }
        }
        Self::new()
    }

    pub fn save(&self, data_dir: &Path) -> std::io::Result<()> {
        let path = data_dir.join(STATE_FILE);
        let json = serde_json::to_string_pretty(self)
            .map_err(|e| std::io::Error::new(std::io::ErrorKind::Other, e))?;
        std::fs::write(path, json)
    }

    pub fn begin_download(&mut self, url: &str, signature: &str) {
        self.patch_state = ShorebirdPatchState::Downloading {
            url: url.to_string(),
            signature: signature.to_string(),
        };
    }

    pub fn mark_downloaded(&mut self, path: &str) {
        if let ShorebirdPatchState::Downloading { url, signature } = self.patch_state.clone() {
            self.patch_state = ShorebirdPatchState::Downloaded {
                url,
                signature,
                path: path.to_string(),
            };
        } else {
            eprintln!("[shorebird] mark_downloaded called in unexpected state: {:?}", self.patch_state);
        }
    }

    pub fn mark_installed(&mut self, patch_number: u32) {
        self.patch_state = ShorebirdPatchState::Installed { patch_number };
        self.next_boot_patch = Some(patch_number);
    }

    pub fn mark_bad(&mut self, patch_number: u32, reason: &str) {
        self.patch_state = ShorebirdPatchState::Bad {
            patch_number,
            reason: reason.to_string(),
        };
        if !self.rolled_back_patch_numbers.contains(&patch_number) {
            self.rolled_back_patch_numbers.push(patch_number);
        }
        // Clear next_boot so we fall back to baseline
        if self.next_boot_patch == Some(patch_number) {
            self.next_boot_patch = None;
        }
    }

    /// Call at boot start to record we are attempting to boot with the staged patch.
    pub fn on_boot_start(&mut self) {
        if let Some(patch) = self.next_boot_patch {
            self.currently_booting_patch = Some(patch);
        }
    }

    /// Call when first frame is rendered (boot succeeded).
    pub fn on_boot_success(&mut self) {
        if let Some(patch) = self.currently_booting_patch.take() {
            self.last_booted_patch = Some(patch);
        }
    }

    /// Returns true if a boot loop was detected and patch was rolled back.
    /// A boot loop is detected when currently_booting_patch is still set
    /// (meaning the previous boot never called on_boot_success).
    pub fn check_boot_loop(&mut self) -> bool {
        if let Some(patch) = self.currently_booting_patch.take() {
            eprintln!("[shorebird] boot loop detected for patch {}", patch);
            self.mark_bad(patch, "BootLoop");
            return true;
        }
        false
    }

    pub fn is_patch_blacklisted(&self, patch_number: u32) -> bool {
        self.rolled_back_patch_numbers.contains(&patch_number)
    }
}

impl Default for ShorebirdState {
    fn default() -> Self {
        Self::new()
    }
}
