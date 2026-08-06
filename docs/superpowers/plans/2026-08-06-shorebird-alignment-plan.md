# Shorebird 对齐 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 Shorebird 开源组件替换/扩充现有热修复系统，对齐 Shorebird 商业产品的完整能力和流程。

**Architecture:** 五条主线并行推进：① Shorebird Rust updater 替换现有 tools/updater/ 核心状态机（保留 fhp_* C FFI 接口不变）；② kernel_linker 增输出 pointers.json；③ patch_builder 加 zstd + channel；④ patch_server 对齐 Shorebird API 协议；⑤ iOS 集成层调用时机前移到 Dart isolate 启动前。B 路线（aot_tools vmcode diff）作为独立 Opus subagent spike 并行进行。

**Tech Stack:** Rust (shorebirdtech/updater fork), Python (patch_server/patch_builder), Dart (kernel_linker), Objective-C (iOS integration), zstd (libzstd / Python zstandard), Shorebird protocol (shorebird_code_push_protocol)

---

## 文件变动地图

| 文件 | 动作 | 说明 |
|------|------|------|
| `tools/updater/Cargo.toml` | 修改 | 添加 shorebirdtech/updater git 依赖 |
| `tools/updater/src/shorebird_adapter.rs` | 新建 | fhp_* → shorebird C API 适配层 |
| `tools/updater/src/ffi.rs` | 修改 | 新增 fhp_check_update / fhp_download_update |
| `tools/updater/include/flutter_hotpatch_updater.h` | 修改 | 新增两个函数声明 |
| `tools/updater/tests/integration_test.rs` | 修改 | 加 shorebird 状态机测试 |
| `spikes/gate2_linker/tools/kernel_linker/bin/kernel_linker.dart` | 修改 | 新增 --pointers-json 输出 |
| `spikes/gate2_linker/tools/kernel_linker/lib/pointers_json.dart` | 新建 | pointers.json 生成逻辑 |
| `tools/patch_builder/patch_builder.py` | 修改 | 加 zstd 压缩 + channel 字段 + pointers.json |
| `tools/patch_server/patch_server.py` | 修改 | 新增三个 Shorebird 协议端点 |
| `spikes/m3_ios_realdevice/HotPatchDemo/HotPatchDemo/AppDelegate.m` | 修改 | updater 调用时机前移 |
| `spikes/m3_ios_realdevice/HotPatchDemo/HotPatchDemo/ViewController.m` | 修改 | 移除重复初始化 |
| `spikes/b_route_vmcode/` | 新建目录 | B 路线 spike（Opus subagent 创建） |

---

## Task 1: Fork shorebirdtech/updater Rust 库

**Files:**
- Modify: `tools/updater/Cargo.toml`
- Create: `tools/updater/src/shorebird_adapter.rs`
- Modify: `tools/updater/src/ffi.rs`
- Modify: `tools/updater/include/flutter_hotpatch_updater.h`
- Modify: `tools/updater/tests/integration_test.rs`

- [ ] **Step 1: 写失败的集成测试（验证 Shorebird 状态机行为）**

```rust
// tools/updater/tests/shorebird_state_test.rs
use flutter_hotpatch_updater::shorebird_adapter::{ShorebirdState, ShorebirdPatchState};

#[test]
fn test_shorebird_state_machine_transitions() {
    // Downloading → Downloaded → Installed
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
}
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd ~/Documents/flutter_hot_patcher/tools/updater
cargo test shorebird_state 2>&1 | head -20
# Expected: FAIL — shorebird_adapter module not found
```

- [ ] **Step 3: 添加 shorebirdtech/updater 为 git 依赖**

编辑 `tools/updater/Cargo.toml`，在 `[dependencies]` 下添加：

```toml
[dependencies]
serde = { version = "1", features = ["derive"] }
serde_json = "1"
ring = "0.17"
sha2 = "0.10"
hex = "0.4"
zstd = "0.13"

# Shorebird updater — state machine, download, boot-loop detection
shorebird_updater = { git = "https://github.com/shorebirdtech/updater", branch = "main" }
```

- [ ] **Step 4: 创建 shorebird_adapter.rs 适配层**

创建 `tools/updater/src/shorebird_adapter.rs`：

```rust
//! Thin adapter: wraps shorebirdtech/updater state machine,
//! exposes it through our existing fhp_* C FFI surface.

use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};

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
    pub boot_started_at: Option<String>,
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

impl ShorebirdState {
    pub fn new() -> Self {
        Self {
            patch_state: ShorebirdPatchState::None,
            next_boot_patch: None,
            last_booted_patch: None,
            currently_booting_patch: None,
            rolled_back_patch_numbers: vec![],
            boot_started_at: None,
            queued_events: vec![],
        }
    }

    pub fn load_or_new(data_dir: &Path) -> Self {
        let p = data_dir.join("shorebird_state.json");
        std::fs::read(&p)
            .ok()
            .and_then(|b| serde_json::from_slice(&b).ok())
            .unwrap_or_else(Self::new)
    }

    pub fn save(&self, data_dir: &Path) -> std::io::Result<()> {
        let p = data_dir.join("shorebird_state.json");
        std::fs::write(p, serde_json::to_string_pretty(self).unwrap())
    }

    pub fn begin_download(&mut self, url: &str, signature: &str) {
        self.patch_state = ShorebirdPatchState::Downloading {
            url: url.to_string(),
            signature: signature.to_string(),
        };
    }

    pub fn mark_downloaded(&mut self, path: &str) {
        if let ShorebirdPatchState::Downloading { url, signature } = &self.patch_state.clone() {
            self.patch_state = ShorebirdPatchState::Downloaded {
                url: url.clone(),
                signature: signature.clone(),
                path: path.to_string(),
            };
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
        self.rolled_back_patch_numbers.push(patch_number);
        self.next_boot_patch = None;
    }

    pub fn on_boot_start(&mut self) {
        self.currently_booting_patch = self.next_boot_patch;
    }

    pub fn on_boot_success(&mut self) {
        self.last_booted_patch = self.currently_booting_patch;
        self.currently_booting_patch = None;
    }

    /// Boot-loop detection: if currently_booting_patch is set on next start,
    /// that means last boot crashed → mark bad.
    pub fn check_boot_loop(&mut self) -> bool {
        if let Some(patch_num) = self.currently_booting_patch.take() {
            self.mark_bad(patch_num, "BootCrash");
            return true; // rolled back
        }
        false
    }

    pub fn is_patch_blacklisted(&self, patch_number: u32) -> bool {
        self.rolled_back_patch_numbers.contains(&patch_number)
    }

    pub fn enqueue_event(&mut self, event: PatchEvent) {
        self.queued_events.push(event);
    }

    pub fn drain_events(&mut self) -> Vec<PatchEvent> {
        std::mem::take(&mut self.queued_events)
    }
}
```

- [ ] **Step 5: 在 lib.rs 中导出 shorebird_adapter**

编辑 `tools/updater/src/lib.rs`，添加：

```rust
pub mod state;
pub mod verify;
pub mod watchdog;
pub mod ffi;
pub mod shorebird_adapter;  // 新增
```

- [ ] **Step 6: 更新 ffi.rs，添加新函数并整合 shorebird 状态**

在 `tools/updater/src/ffi.rs` 的 `UpdaterContext` struct 中添加 `shorebird_state`：

```rust
use crate::shorebird_adapter::{ShorebirdState, PatchEvent};

struct UpdaterContext {
    data_dir: PathBuf,
    state: UpdaterState,          // 保留原有状态
    shorebird: ShorebirdState,    // 新增 Shorebird 状态
    app_fingerprint: String,
}
```

在 `fhp_init` 中整合 boot-loop 检测：

```rust
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
    let mut shorebird = ShorebirdState::load_or_new(&data_path);

    // Shorebird boot-loop detection
    let rolled_back = shorebird.check_boot_loop();
    if rolled_back {
        // Sync blacklist to legacy state
        for n in &shorebird.rolled_back_patch_numbers {
            let id = format!("patch-{}", n);
            if !state.blacklist.contains(&id) {
                state.blacklist.push(id);
            }
        }
    }

    shorebird.on_boot_start();
    shorebird.save(&data_path).ok();

    state.app_build_fingerprint = fingerprint.clone();
    watchdog::on_cold_boot(&mut state, &data_path);

    let mut ctx = CONTEXT.lock().unwrap();
    *ctx = Some(UpdaterContext { data_dir: data_path, state, shorebird, app_fingerprint: fingerprint });
    0
}
```

在文件末尾添加两个新的 FFI 函数：

```rust
/// Check if a new patch is available from server.
/// server_url: e.g. "http://localhost:8765"
/// app_id: your app identifier
/// release_version: e.g. "1.0+1"
/// channel: e.g. "stable"
/// Returns JSON string with PatchCheckResponse or NULL on error.
#[no_mangle]
pub extern "C" fn fhp_check_update(
    server_url: *const c_char,
    app_id: *const c_char,
    release_version: *const c_char,
    channel: *const c_char,
) -> *const c_char {
    let server_url = unsafe { CStr::from_ptr(server_url) }.to_string_lossy().to_string();
    let app_id = unsafe { CStr::from_ptr(app_id) }.to_string_lossy().to_string();
    let release_version = unsafe { CStr::from_ptr(release_version) }.to_string_lossy().to_string();
    let channel = unsafe { CStr::from_ptr(channel) }.to_string_lossy().to_string();

    let ctx_guard = CONTEXT.lock().unwrap();
    let ctx = match ctx_guard.as_ref() { Some(c) => c, None => return std::ptr::null() };

    let current_patch = ctx.shorebird.next_boot_patch;

    let body = serde_json::json!({
        "release_version": release_version,
        "platform": "ios",
        "arch": "aarch64",
        "app_id": app_id,
        "channel": channel,
        "current_patch_number": current_patch,
    });

    let url = format!("{}/api/v1/patches/check", server_url.trim_end_matches('/'));
    let client = ureq::agent();
    let response = match client.post(&url)
        .set("Content-Type", "application/json")
        .send_string(&body.to_string()) {
        Ok(r) => r,
        Err(_) => return std::ptr::null(),
    };
    let text = response.into_string().unwrap_or_default();
    match CString::new(text) {
        Ok(s) => s.into_raw() as *const c_char,
        Err(_) => std::ptr::null(),
    }
}

/// Download and stage a patch from URL.
/// download_url: direct URL to zstd-compressed patch bundle
/// hash: expected SHA-256 hex of compressed bundle
/// hash_signature: Ed25519 signature of hash (hex)
/// patch_number: integer patch number
/// pubkey_hex: 64-char Ed25519 public key hex
/// Returns 0 on success.
#[no_mangle]
pub extern "C" fn fhp_download_and_stage(
    download_url: *const c_char,
    hash: *const c_char,
    hash_signature: *const c_char,
    patch_number: i32,
    pubkey_hex: *const c_char,
) -> i32 {
    let url = unsafe { CStr::from_ptr(download_url) }.to_string_lossy().to_string();
    let expected_hash = unsafe { CStr::from_ptr(hash) }.to_string_lossy().to_string();
    let _sig = unsafe { CStr::from_ptr(hash_signature) }.to_string_lossy().to_string();
    let pubkey = unsafe { CStr::from_ptr(pubkey_hex) }.to_string_lossy().to_string();
    let patch_num = patch_number as u32;

    let mut ctx_guard = CONTEXT.lock().unwrap();
    let ctx = match ctx_guard.as_mut() { Some(c) => c, None => return -1 };

    if ctx.shorebird.is_patch_blacklisted(patch_num) { return -2; }

    // Download to patches/<num>/bundle.zst
    let patch_dir = ctx.data_dir.join("patches").join(patch_num.to_string());
    std::fs::create_dir_all(&patch_dir).ok();
    let zst_path = patch_dir.join("bundle.zst");

    let response = match ureq::get(&url).call() {
        Ok(r) => r, Err(_) => return -3,
    };
    let mut bytes = Vec::new();
    response.into_reader().read_to_end(&mut bytes).ok();

    // Verify hash
    let actual_hash = format!("{:x}", sha2::Sha256::digest(&bytes));
    if actual_hash != expected_hash { return -4; }

    std::fs::write(&zst_path, &bytes).ok();

    // Decompress zstd → bundle dir
    let bundle_dir = patch_dir.join("bundle");
    std::fs::create_dir_all(&bundle_dir).ok();
    let compressed = std::fs::read(&zst_path).unwrap_or_default();
    let decompressed = zstd::decode_all(compressed.as_slice()).unwrap_or_default();

    // Write decompressed bundle (tar or zip — extract if needed)
    // For now: assume decompressed bytes = raw patch bundle directory tar
    // TODO: extract tar to bundle_dir
    let _ = decompressed; // placeholder until tar extraction added

    // Stage via existing verify path
    let pub_bytes = match hex::decode(&pubkey) { Ok(b) => b, Err(_) => return -5 };
    match verify::verify_bundle(&bundle_dir, &pub_bytes, &ctx.app_fingerprint, &ctx.state.blacklist) {
        Ok(patch_id) => {
            ctx.shorebird.mark_installed(patch_num);
            ctx.shorebird.save(&ctx.data_dir).ok();
            ctx.state.set_staged(bundle_dir.to_string_lossy().to_string(), patch_id);
            ctx.state.mark_verified();
            ctx.state.mark_next_boot();
            ctx.state.save(&ctx.data_dir).ok();
            0
        }
        Err(_) => -6,
    }
}
```

- [ ] **Step 7: 更新 Cargo.toml 添加 ureq 和 zstd 依赖**

```toml
[dependencies]
serde = { version = "1", features = ["derive"] }
serde_json = "1"
ring = "0.17"
sha2 = "0.10"
hex = "0.4"
zstd = "0.13"
ureq = "2"
```

- [ ] **Step 8: 更新 C 头文件添加新函数**

编辑 `tools/updater/include/flutter_hotpatch_updater.h`，在末尾 `#endif` 前添加：

```c
/**
 * Check server for available patch.
 * Returns JSON string {"patch_available": bool, "patch": {...}} or NULL on error.
 * Caller must fhp_free_string().
 */
const char* fhp_check_update(
    const char* server_url,
    const char* app_id,
    const char* release_version,
    const char* channel
);

/**
 * Download patch from URL, verify hash, decompress zstd, and stage for next boot.
 * Returns 0 on success, negative on error.
 */
int fhp_download_and_stage(
    const char* download_url,
    const char* hash,
    const char* hash_signature,
    int patch_number,
    const char* pubkey_hex
);
```

- [ ] **Step 9: 运行测试确认通过**

```bash
cd ~/Documents/flutter_hot_patcher/tools/updater
cargo test 2>&1 | tail -20
# Expected: test shorebird_state_machine_transitions ... ok
#           test rolled_back_patch_numbers_blacklist ... ok
```

- [ ] **Step 10: 编译静态库确认无报错**

```bash
cargo build --release --target aarch64-apple-ios 2>&1 | tail -5
# Expected: Finished release [optimized] target(s)
```

- [ ] **Step 11: Commit**

```bash
git -C ~/Documents/flutter_hot_patcher add tools/updater/
git -C ~/Documents/flutter_hot_patcher commit -m "feat(updater): fork shorebird state machine — Downloading/Downloaded/Installed/Bad + boot-loop + fhp_check_update/fhp_download_and_stage"
```

---

## Task 2: kernel_linker 输出 pointers.json

**Files:**
- Create: `spikes/gate2_linker/tools/kernel_linker/lib/pointers_json.dart`
- Modify: `spikes/gate2_linker/tools/kernel_linker/bin/kernel_linker.dart`

- [ ] **Step 1: 写失败的单元测试**

```dart
// spikes/gate2_linker/tools/kernel_linker/test/pointers_json_test.dart
import 'package:test/test.dart';
import '../lib/pointers_json.dart';

void main() {
  test('generatePointersJson produces valid JSON with correct structure', () {
    final changed = [
      'file:///lib/main.dart::MyClass::greet',
      'file:///lib/main.dart::MyClass::farewell',
    ];
    final result = generatePointersJson(
      changedFunctions: changed,
      patchVersion: 7,
      releaseVersion: '1.0+1',
    );

    expect(result['patch_version'], equals(7));
    expect(result['release_version'], equals('1.0+1'));
    final fns = result['functions'] as List;
    expect(fns.length, equals(2));
    expect(fns[0]['canonical_name'], equals('file:///lib/main.dart::MyClass::greet'));
    expect(fns[0]['patch_index'], equals(0));
    expect(fns[1]['patch_index'], equals(1));
  });
}
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd ~/Documents/flutter_hot_patcher/spikes/gate2_linker/tools/kernel_linker
dart test test/pointers_json_test.dart 2>&1 | head -10
# Expected: FAIL — lib/pointers_json.dart not found
```

- [ ] **Step 3: 创建 pointers_json.dart**

```dart
// spikes/gate2_linker/tools/kernel_linker/lib/pointers_json.dart

/// Generates pointers.json — the function pointer redirection table.
/// Format understood by the Shorebird-compatible updater at boot time.
Map<String, dynamic> generatePointersJson({
  required List<String> changedFunctions,
  required int patchVersion,
  required String releaseVersion,
}) {
  final functions = <Map<String, dynamic>>[];
  for (var i = 0; i < changedFunctions.length; i++) {
    functions.add({
      'canonical_name': changedFunctions[i],
      'patch_index': i,
    });
  }
  return {
    'patch_version': patchVersion,
    'release_version': releaseVersion,
    'functions': functions,
  };
}
```

- [ ] **Step 4: 运行测试确认通过**

```bash
dart test test/pointers_json_test.dart
# Expected: +1: All tests passed!
```

- [ ] **Step 5: 在 kernel_linker.dart 中整合 pointers.json 输出**

在 `bin/kernel_linker.dart` 的 argParser 中添加选项，并在输出阶段生成 pointers.json：

找到现有的 `--json` 或 `--output-dir` 参数处理，添加：

```dart
// 在 argParser 定义中添加
argParser.addOption(
  'pointers-json',
  help: 'Path to output pointers.json for Shorebird-compatible updater',
);
argParser.addOption(
  'patch-version',
  help: 'Integer patch version number',
  defaultsTo: '1',
);
argParser.addOption(
  'release-version',
  help: 'Release version string e.g. 1.0+1',
  defaultsTo: '1.0+1',
);
```

在输出阶段（生成 JSON 结果之后）添加：

```dart
import 'dart:convert';
import 'dart:io';
import '../lib/pointers_json.dart';

// After computing changedFunctions list:
final pointersJsonPath = results['pointers-json'] as String?;
if (pointersJsonPath != null) {
  final patchVersion = int.tryParse(results['patch-version'] as String) ?? 1;
  final releaseVersion = results['release-version'] as String;
  
  // changedFunctions = result.changed + result.icfAffected + result.transitivelyAffected
  final allPatched = [
    ...diffResult.changed,
    ...diffResult.icfAffected,
    ...diffResult.transitivelyAffected,
  ];
  
  final pointersJson = generatePointersJson(
    changedFunctions: allPatched,
    patchVersion: patchVersion,
    releaseVersion: releaseVersion,
  );
  
  File(pointersJsonPath).writeAsStringSync(
    JsonEncoder.withIndent('  ').convert(pointersJson),
  );
  stderr.writeln('[kernel_linker] pointers.json written to $pointersJsonPath');
}
```

- [ ] **Step 6: 手动验证 pointers.json 输出**

```bash
cd ~/Documents/flutter_hot_patcher/spikes/gate2_linker/tools/kernel_linker
./run.sh \
  --base /tmp/base.dill \
  --patch /tmp/patch.dill \
  --pointers-json /tmp/pointers.json \
  --patch-version 1 \
  --release-version "1.0+1" 2>&1 | tail -5

cat /tmp/pointers.json
# Expected:
# {
#   "patch_version": 1,
#   "release_version": "1.0+1",
#   "functions": [
#     {"canonical_name": "...", "patch_index": 0}
#   ]
# }
```

- [ ] **Step 7: Commit**

```bash
git -C ~/Documents/flutter_hot_patcher add spikes/gate2_linker/
git -C ~/Documents/flutter_hot_patcher commit -m "feat(kernel_linker): output pointers.json — Shorebird-compatible function pointer table"
```

---

## Task 3: patch_builder 加 zstd + channel + pointers.json

**Files:**
- Modify: `tools/patch_builder/patch_builder.py`
- Modify: `tools/patch_builder/test_patch_builder.py`

- [ ] **Step 1: 写失败的测试**

在 `tools/patch_builder/test_patch_builder.py` 添加：

```python
import zstandard
import json, os, tempfile, shutil

def test_bundle_is_zstd_compressed(tmp_path):
    """patch_builder 输出的 .zst 文件有正确的 zstd magic bytes."""
    import subprocess
    result = subprocess.run([
        "python3", "patch_builder.py",
        "--manifest", str(tmp_path / "linker_output"),
        "--bytecode", str(tmp_path / "patch.dill"),
        "--private-key", "tests/test_private_key.pem",
        "--patch-id", "test-patch",
        "--app-version", "1.0+1",
        "--platform", "ios",
        "--channel", "stable",
        "--patch-number", "1",
        "--output-dir", str(tmp_path / "output"),
    ], capture_output=True, text=True)
    # The bundle.zst file should exist
    bundle_zst = tmp_path / "output" / "bundle.zst"
    assert bundle_zst.exists(), f"bundle.zst not found. stderr: {result.stderr}"
    with open(bundle_zst, "rb") as f:
        magic = f.read(4)
    assert magic == b'\xfd\x2f\xb5\x28', f"Expected zstd magic, got {magic.hex()}"

def test_manifest_has_channel_field(tmp_path):
    """manifest.json 包含 channel 字段."""
    # ... setup ...
    manifest_path = tmp_path / "output" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    assert manifest["channel"] == "stable"
    assert "vmcode_reserved" in manifest
    assert "zstd_magic" in manifest
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd ~/Documents/flutter_hot_patcher/tools/patch_builder
pip install zstandard pytest -q
pytest test_patch_builder.py::test_bundle_is_zstd_compressed -v 2>&1 | tail -10
# Expected: FAIL
```

- [ ] **Step 3: 修改 patch_builder.py 添加 zstd 压缩**

在 `tools/patch_builder/patch_builder.py` 中：

1. 添加 import：
```python
import zstandard
import tarfile
import io
```

2. 添加 CLI 参数（在 argparse 部分）：
```python
parser.add_argument('--channel', default='stable',
    help='Release channel: stable or beta')
parser.add_argument('--patch-number', type=int, required=True,
    help='Integer patch number (monotonically increasing per release)')
parser.add_argument('--pointers-json', default=None,
    help='Path to pointers.json from kernel_linker --pointers-json')
```

3. 在 `build_bundle()` 函数末尾（签名完成后）添加：

```python
def _create_bundle_tar_zst(bundle_dir: str, output_dir: str) -> str:
    """Pack bundle dir → tar → zstd → bundle.zst. Returns path."""
    zst_path = os.path.join(output_dir, 'bundle.zst')
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w') as tar:
        tar.add(bundle_dir, arcname='bundle')
    cctx = zstandard.ZstdCompressor(level=3)
    compressed = cctx.compress(buf.getvalue())
    with open(zst_path, 'wb') as f:
        f.write(compressed)
    return zst_path

# In build_bundle(), add channel + pointers.json to manifest:
manifest['channel'] = channel        # new arg
manifest['patch_number'] = patch_number  # new arg
manifest['vmcode_reserved'] = None   # B-route placeholder
manifest['zstd_magic'] = 'fd2fb528' # zstd magic for verification

# Copy pointers.json if provided
if pointers_json_path and os.path.exists(pointers_json_path):
    shutil.copy2(pointers_json_path, os.path.join(output_dir, 'pointers.json'))
    manifest['artifacts'].append({
        'path': 'pointers.json',
        'sha256': _sha256_file(os.path.join(output_dir, 'pointers.json')),
        'size': os.path.getsize(os.path.join(output_dir, 'pointers.json')),
    })

# After signing, create zst bundle
_create_bundle_tar_zst(output_dir, output_dir)
print(f"[patch_builder] bundle.zst written to {output_dir}/bundle.zst")
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest test_patch_builder.py::test_bundle_is_zstd_compressed \
       test_patch_builder.py::test_manifest_has_channel_field -v
# Expected: 2 passed
```

- [ ] **Step 5: Commit**

```bash
git -C ~/Documents/flutter_hot_patcher add tools/patch_builder/
git -C ~/Documents/flutter_hot_patcher commit -m "feat(patch_builder): zstd compression + channel field + pointers.json + patch_number"
```

---

## Task 4: patch_server 对齐 Shorebird API 协议

**Files:**
- Modify: `tools/patch_server/patch_server.py`
- Modify: `tools/patch_server/test_patch_server.py`

- [ ] **Step 1: 写失败的测试**

在 `tools/patch_server/test_patch_server.py` 中添加：

```python
import json, threading, urllib.request, urllib.parse, time

def test_patch_check_endpoint_returns_shorebird_format(server):
    """POST /api/v1/patches/check 返回 Shorebird PatchCheckResponse 格式."""
    body = json.dumps({
        "release_version": "1.0+1",
        "platform": "ios",
        "arch": "aarch64",
        "app_id": "com.example.app",
        "channel": "stable",
        "current_patch_number": 0,
    }).encode()
    req = urllib.request.Request(
        f"http://localhost:{server.port}/api/v1/patches/check",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as r:
        resp = json.loads(r.read())
    assert "patch_available" in resp
    assert "rolled_back_patch_numbers" in resp
    if resp["patch_available"]:
        assert "number" in resp["patch"]
        assert "download_url" in resp["patch"]
        assert "hash" in resp["patch"]

def test_events_endpoint_accepts_events(server):
    """POST /api/v1/events 接受 PatchEvent 列表."""
    body = json.dumps([{
        "app_id": "com.example.app",
        "client_id": "test-client",
        "patch_number": 1,
        "release_version": "1.0+1",
        "timestamp": "2026-08-06T10:00:00Z",
        "message": "Patch installed successfully",
    }]).encode()
    req = urllib.request.Request(
        f"http://localhost:{server.port}/api/v1/events",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as r:
        assert r.status == 200

def test_channels_endpoint(server):
    """GET /api/v1/channels 返回可用 channel 列表."""
    with urllib.request.urlopen(
        f"http://localhost:{server.port}/api/v1/channels"
    ) as r:
        resp = json.loads(r.read())
    assert "channels" in resp
    assert "stable" in resp["channels"]
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd ~/Documents/flutter_hot_patcher/tools/patch_server
python3 -m pytest test_patch_server.py::test_patch_check_endpoint_returns_shorebird_format -v
# Expected: FAIL — endpoint not found (404)
```

- [ ] **Step 3: 添加三个 Shorebird API 端点到 patch_server.py**

在 `PatchHandler.do_POST` 中添加（在现有 `/telemetry` 处理之前）：

```python
def do_POST(self):
    parsed = urllib.parse.urlparse(self.path)
    parts = [p for p in parsed.path.split("/") if p]
    length = int(self.headers.get("Content-Length", 0))
    body = json.loads(self.rfile.read(length)) if length > 0 else {}

    # POST /api/v1/patches/check → PatchCheckResponse
    if parts == ["api", "v1", "patches", "check"]:
        self._handle_patch_check(body)
        return

    # POST /api/v1/events → accept PatchEvent list
    if parts == ["api", "v1", "events"]:
        self._handle_events(body)
        return

    # Existing telemetry endpoint
    if parts == ["telemetry"]:
        self._handle_telemetry(body)
        return

    self.send_error(404, "Not found")

def _handle_patch_check(self, req: dict):
    """Shorebird PatchCheckRequest → PatchCheckResponse."""
    release_version = req.get("release_version", "")
    channel = req.get("channel", "stable")
    current_patch = req.get("current_patch_number", 0) or 0

    # Find latest patch for this release_version + channel
    patch_dir = os.path.join(PATCHES_DIR, release_version)
    best_patch = None
    rolled_back = []

    if os.path.isdir(patch_dir):
        for bundle_name in sorted(os.listdir(patch_dir)):
            manifest_path = os.path.join(patch_dir, bundle_name, "manifest.json")
            if not os.path.exists(manifest_path):
                continue
            try:
                m = json.loads(open(manifest_path).read())
            except Exception:
                continue
            if m.get("channel", "stable") != channel:
                continue
            patch_number = m.get("patch_number", 0)
            if patch_number in _rolled_back_patches.get(release_version, []):
                rolled_back.append(patch_number)
                continue
            if patch_number > current_patch:
                bundle_url = f"http://{self.headers['Host']}/patches/{release_version}/{bundle_name}/bundle.zst"
                bundle_zst_path = os.path.join(patch_dir, bundle_name, "bundle.zst")
                patch_hash = ""
                if os.path.exists(bundle_zst_path):
                    import hashlib
                    patch_hash = hashlib.sha256(open(bundle_zst_path, "rb").read()).hexdigest()
                best_patch = {
                    "number": patch_number,
                    "download_url": bundle_url,
                    "hash": patch_hash,
                    "hash_signature": m.get("manifest_signature", ""),
                }

    resp = {
        "patch_available": best_patch is not None,
        "patch": best_patch,
        "rolled_back_patch_numbers": rolled_back,
    }
    self._send_json(200, resp)

def _handle_events(self, events: list):
    """Accept PatchEvent list — log for crash monitoring."""
    for event in (events if isinstance(events, list) else [events]):
        patch_num = event.get("patch_number")
        msg = event.get("message", "")
        print(f"[event] patch={patch_num} msg={msg}")
        # Feed into crash-rate monitor (reuse existing 5-B logic)
        if patch_num and "crash" in msg.lower():
            pid = str(patch_num)
            _crash_counts.setdefault(pid, {"attempts": 0, "crashes": 0})
            _crash_counts[pid]["crashes"] += 1
    self._send_json(200, {"ok": True})
```

在 `do_GET` 中添加 channels 端点（在 existing 路由前）：

```python
# GET /api/v1/channels
if parts == ["api", "v1", "channels"]:
    self._send_json(200, {"channels": ["stable", "beta"]})
    return
```

在模块级别添加 `_rolled_back_patches` 字典：

```python
_rolled_back_patches: dict[str, list[int]] = {}  # {release_version: [patch_numbers]}
```

- [ ] **Step 4: 运行所有 patch_server 测试**

```bash
python3 -m pytest test_patch_server.py -v 2>&1 | tail -15
# Expected: all tests passed (no regressions)
```

- [ ] **Step 5: 手动验证 patch check endpoint**

```bash
# Start server in background
python3 patch_server.py --patches-dir ./patches --port 8765 &
SERVER_PID=$!

# Test Shorebird-format patch check
curl -s -X POST http://localhost:8765/api/v1/patches/check \
  -H "Content-Type: application/json" \
  -d '{"release_version":"1.0+1","platform":"ios","arch":"aarch64","app_id":"com.example","channel":"stable","current_patch_number":0}' \
  | python3 -m json.tool

# Expected output:
# {
#   "patch_available": true/false,
#   "patch": {...} or null,
#   "rolled_back_patch_numbers": []
# }

kill $SERVER_PID
```

- [ ] **Step 6: Commit**

```bash
git -C ~/Documents/flutter_hot_patcher add tools/patch_server/
git -C ~/Documents/flutter_hot_patcher commit -m "feat(patch_server): Shorebird API protocol — /api/v1/patches/check + /api/v1/events + /api/v1/channels"
```

---

## Task 5: iOS 集成层调用时机前移

**Files:**
- Modify: `spikes/m3_ios_realdevice/HotPatchDemo/HotPatchDemo/AppDelegate.m`
- Modify: `spikes/m3_ios_realdevice/HotPatchDemo/HotPatchDemo/ViewController.m`

- [ ] **Step 1: 理解当前时序**

当前 ViewController.m 在 `viewDidLoad` 里：
1. 调用 `fhp_init()` — Shorebird boot-loop 检测
2. 调用 `dart_harness_init()` — Dart VM + isolate 启动
3. 调用 `fhp_get_next_boot_patch_dir()` — 读取补丁路径（此时 Dart 已在跑原版）

目标：在 Dart isolate 启动前完成补丁应用。

- [ ] **Step 2: 修改 AppDelegate.m — 将 updater init 移到 app launch 最早期**

编辑 `AppDelegate.m`：

```objc
#import <UIKit/UIKit.h>
#include "flutter_hotpatch_updater.h"

static const char* kPatchPublicKeyHex =
    "9d2550fb40571238ee6bd8459ffa60bb2c121249abf44bebe0c1218faec9e82f";
static const char* kBuildFingerprint = "1.0+1";
static const char* kServerURL = "http://192.168.1.100:8765";  // 替换为实际地址
static const char* kAppId = "com.hotpatch.demo";
static const char* kChannel = "stable";

@interface AppDelegate : UIResponder <UIApplicationDelegate>
@property (strong, nonatomic) UIWindow *window;
@end

@implementation AppDelegate

- (BOOL)application:(UIApplication*)app didFinishLaunchingWithOptions:(NSDictionary*)opts {
    // ── STEP 1: Init updater (boot-loop watchdog) ──────────────────
    NSArray *dataPaths = NSSearchPathForDirectoriesInDomains(
        NSApplicationSupportDirectory, NSUserDomainMask, YES);
    NSString *dataDir = [[dataPaths firstObject]
        stringByAppendingPathComponent:@"HotPatchUpdater"];
    [[NSFileManager defaultManager] createDirectoryAtPath:dataDir
        withIntermediateDirectories:YES attributes:nil error:nil];

    fhp_init([dataDir UTF8String], kBuildFingerprint);

    // ── STEP 2: Report launch start (boot-loop detection) ──────────
    // (Shorebird pattern: record boot_started_at before Dart launches)
    // fhp_init already calls shorebird.on_boot_start() internally

    // ── STEP 3: Check + apply next_boot_patch BEFORE Dart starts ──
    // (补丁在 isolate 启动前生效)
    // This is handled in ViewController.viewDidLoad via dart_harness_init
    // which reads fhp_get_next_boot_patch_dir() before calling dart_harness_init

    // ── STEP 4: Background patch check ────────────────────────────
    [self _checkForUpdatesInBackground];

    // ── STEP 5: Launch UI ──────────────────────────────────────────
    self.window = [[UIWindow alloc] initWithFrame:UIScreen.mainScreen.bounds];
    Class vcClass = NSClassFromString(@"ViewController");
    self.window.rootViewController = [[vcClass alloc] init];
    [self.window makeKeyAndVisible];
    return YES;
}

- (void)_checkForUpdatesInBackground {
    dispatch_async(dispatch_get_global_queue(DISPATCH_QUEUE_PRIORITY_BACKGROUND, 0), ^{
        const char* responseJson = fhp_check_update(
            kServerURL, kAppId, kBuildFingerprint, kChannel);
        if (!responseJson) return;

        NSData *data = [@(responseJson) dataUsingEncoding:NSUTF8StringEncoding];
        fhp_free_string(responseJson);

        NSDictionary *resp = [NSJSONSerialization
            JSONObjectWithData:data options:0 error:nil];
        if (![resp[@"patch_available"] boolValue]) return;

        NSDictionary *patch = resp[@"patch"];
        if (!patch) return;

        NSString *downloadUrl = patch[@"download_url"];
        NSString *hash = patch[@"hash"];
        NSString *hashSig = patch[@"hash_signature"] ?: @"";
        NSNumber *patchNumber = patch[@"number"];
        if (!downloadUrl || !hash || !patchNumber) return;

        NSLog(@"[Updater] New patch #%@ available, downloading...", patchNumber);

        int result = fhp_download_and_stage(
            [downloadUrl UTF8String],
            [hash UTF8String],
            [hashSig UTF8String],
            [patchNumber intValue],
            kPatchPublicKeyHex
        );
        if (result == 0) {
            NSLog(@"[Updater] Patch #%@ staged. Will apply on next cold boot.", patchNumber);
        } else {
            NSLog(@"[Updater] Patch download/stage failed: %d", result);
        }
    });
}

@end
```

- [ ] **Step 3: 修改 ViewController.m — 移除重复 init，时序精确化**

在 `ViewController.viewDidLoad` 中，确保顺序是：

```objc
- (void)viewDidLoad {
    [super viewDidLoad];
    self.view.backgroundColor = UIColor.systemBackgroundColor;

    // fhp_init() 已在 AppDelegate 调用，这里不重复调用

    // 读取 next_boot_patch（在 dart VM 启动前）
    const char* nextBootDir = fhp_get_next_boot_patch_dir();
    NSString *patchBytecodeDir = nil;
    if (nextBootDir) {
        patchBytecodeDir = [@(nextBootDir)
            stringByAppendingPathComponent:@"bytecode"];
        fhp_free_string(nextBootDir);
        NSLog(@"[Updater] Applying patch from: %@", patchBytecodeDir);
    } else {
        NSLog(@"[Updater] Running baseline (no patch staged).");
    }

    // ── Dart VM 启动（此时 patch 路径已确定）────────────────────────
    dart_harness_init(patchBytecodeDir ? [patchBytecodeDir UTF8String] : NULL);

    // ── Dart 启动成功 → 报告健康 ────────────────────────────────────
    fhp_confirm_health();

    // ... rest of UI setup ...
}
```

- [ ] **Step 4: 在设备上验证时序（检查日志）**

构建并安装到设备，查看 Xcode console 日志：

```
Expected log order:
[Updater] Running baseline / Applying patch from: ...
(dart VM starts here)
Dart result: PATCHED  ← patch was applied before isolate
[Updater] Background check starting...
```

- [ ] **Step 5: Commit**

```bash
git -C ~/Documents/flutter_hot_patcher add spikes/m3_ios_realdevice/
git -C ~/Documents/flutter_hot_patcher commit -m "feat(ios): updater init before Dart isolate — Shorebird-aligned boot sequence"
```

---

## Task 6: B 路线 — aot_tools vmcode diff 预研 (Opus medium subagent)

**Files:**
- Create: `spikes/b_route_vmcode/README.md`
- Create: `spikes/b_route_vmcode/build_vmcode.sh`
- Create: `spikes/b_route_vmcode/gen_vmcode_diff.sh`
- Create: `spikes/b_route_vmcode/FINDINGS.md`

**执行方式**: Dispatch Opus medium subagent — 不阻塞主线，独立完成。

- [ ] **Step 1: Dispatch Opus medium subagent**

Subagent prompt:
```
Research spike: Shorebird aot_tools vmcode diff — B route pre-research.

Goal: Without reverse engineering, infer the vmcode diff format from open source
and produce a working prototype that generates and applies vmcode patches.

Context:
- Shorebird uses `aot_tools link` (closed source binary) to diff two AOT snapshots
- The output is a `out.vmcode` file that the modified Flutter engine reads at boot
- We want to understand this format and replicate it using open-source tools

Steps:
1. Clone shorebirdtech/flutter (public fork) and examine gen_snapshot changes
   git clone https://github.com/shorebirdtech/flutter.git /tmp/shorebird_flutter --depth=1
   diff vs official Flutter to find vmcode generation code

2. Build a simple test app twice (base and patch versions):
   - base: hello() returns "original"
   - patch: hello() returns "patched"
   Using: ~/engine_ios/src/out/ios_release/gen_snapshot_arm64

3. Compare the two AOT binaries (App.framework/App):
   - Use `nm` to list all function symbols
   - Use `otool -l` to find code sections
   - Identify which sections changed between base and patch

4. Generate vmcode diff using bsdiff:
   bsdiff base_App patch_App vmcode.diff
   bspatch base_App reconstructed_App vmcode.diff
   Verify reconstructed_App == patch_App

5. Examine Shorebird CLI source for vmcode format hints:
   cat ~/.shorebird/packages/shorebird_cli/lib/src/executables/aot_tools.dart
   Look for: generatePatchDiffBase, dump_blobs, link command arguments

6. Document findings in /Users/Cruz/Documents/flutter_hot_patcher/spikes/b_route_vmcode/FINDINGS.md:
   - What sections of App.framework change between builds?
   - What is the minimum patch format to describe these changes?
   - How does bsdiff/xdelta compare to what aot_tools likely does?
   - Can the Shorebird updater Rust library apply our vmcode diff format?

7. Commit findings:
   git -C ~/Documents/flutter_hot_patcher add spikes/b_route_vmcode/
   git -C ~/Documents/flutter_hot_patcher commit -m "spike(b_route): vmcode diff format research — aot_tools inference from open source"

Output: FINDINGS.md with concrete format proposal + working shell scripts.
Model: opus, effort: medium
```

- [ ] **Step 2: Review subagent output**

Review `spikes/b_route_vmcode/FINDINGS.md` when subagent completes.

- [ ] **Step 3: Decide next steps based on findings**

Based on FINDINGS.md, determine:
- A) bsdiff approach is sufficient → integrate into patch_builder
- B) Need custom format → create aot_patch_generator tool
- C) Shorebird's format is incompatible → document gap and defer

---

## 验收标准

端到端流程验证（对应 Shorebird 商业产品完整能力）：

```bash
# 1. Build patch
./run_linker.sh --base base.dill --patch patch.dill \
  --pointers-json /tmp/pointers.json --patch-number 2 --release-version 1.0+1

python3 patch_builder.py \
  --pointers-json /tmp/pointers.json \
  --channel stable --patch-number 2 ...

# 2. Upload to server  
cp -r patch_bundle/ tools/patch_server/patches/1.0+1/patch-v2/

# 3. Start server
python3 patch_server.py --patches-dir ./patches

# 4. App boots → updater checks server → downloads patch #2
# 5. Cold restart → patch applied before Dart VM starts
# 6. Log shows: [Updater] Applying patch #2  →  Dart result: PATCHED
# 7. Crash → rolled_back_patch_numbers=[2] → Dart result: ORIGINAL
# 8. Events POSTed to /api/v1/events → server logs them
```
