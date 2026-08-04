# 4-C Updater 设计规格

版本 v1.0 · 2026-08-04

---

## 0. 范围

**4-C 实现**：Rust 库，管理补丁状态机 + 验证 + boot-loop watchdog + C API。

**范围内（MVP）**：
- 补丁包验证（Ed25519 签名 + artifact hashes + fingerprint）
- 状态机：staged → verified → next-boot → applied/blacklisted
- Boot-loop watchdog（pending_confirmation → confirmed / 自动黑名单）
- C FFI API（供 4-D dart_harness.c 调用）
- 本地文件 staging（从本地路径安装补丁）

**范围外（留到 4-E）**：
- HTTP 轮询服务端
- 匿名崩溃上报
- 机群级熔断

---

## 1. 状态机

```
               stage_patch()         verify_patch()
未打补丁  ────────────────────→  staged  ────→  verified
                                                    │
                                               mark_next_boot()
                                                    │
                                                    ▼
                               cold start     next-boot
                    ┌──────────────────────────────┤
                    │                              │
              pending_confirmation          [applied]
                    │
         ┌──────────┴──────────────┐
    confirm_health()         crash detected
         │                         │
    confirmed_good         patch_id → blacklist
                                    │
                              fallback to baseline
```

**状态持久化**：`{data_dir}/updater_state.json`

```json
{
  "staged_dir": "/path/to/patch_bundle/",
  "staged_patch_id": "greet-v1-ios-2026-08-04",
  "state": "next-boot",
  "pending_confirmation_since": null,
  "blacklist": [],
  "app_build_fingerprint": "1.0+1"
}
```

---

## 2. 验证流程（对齐 PATCH_DELIVERY_SPEC §4.1）

```
verify_patch(bundle_dir, public_key_bytes, app_fingerprint):
  1. 读 manifest.json + manifest.sig
  2. 验 Ed25519 签名（canonical bytes）────── fail → reject
  3. 逐 artifact 校验 SHA-256 ───────────── fail → reject
  4. 比对 target_build_fingerprint ─────── mismatch → reject
  5. 检查 patch_id 不在黑名单 ─────────── 命中 → reject
  6. → OK: state = verified
```

所有 reject 路径 = fail-closed，不部分应用。

---

## 3. Boot-loop watchdog

```
on cold boot:
  if state == "next-boot":
    state = "pending_confirmation"
    record pending_time = now()

confirm_health():
  if state == "pending_confirmation":
    state = "confirmed_good"

on next cold boot:
  if state == "pending_confirmation":
    // 上次未确认 = 上次崩溃/异常退出
    add current patch_id to blacklist
    state = "baseline"
    log "auto-rollback: boot-loop detected"
```

---

## 4. C FFI API（`flutter_hotpatch_updater.h`）

```c
// 初始化 Updater（data_dir：App 数据目录，build_fp：当前 build fingerprint）
int fhp_init(const char* data_dir, const char* build_fingerprint);

// 从本地 bundle_dir 安装补丁（验证 + 暂存）
// pubkey_hex: 64 hex chars Ed25519 public key
int fhp_stage_patch(const char* bundle_dir, const char* pubkey_hex);

// 把已验证补丁标记为 next-boot（将在下次冷启动生效）
int fhp_mark_next_boot(const char* patch_id);

// 获取当前 next-boot 补丁路径（NULL = 纯基线）
const char* fhp_get_next_boot_patch_dir(void);

// 确认 App 健康（首帧渲染后调用）
void fhp_confirm_health(void);

// 查询当前状态（调试用）
const char* fhp_state_json(void);

// 释放由 fhp_* 返回的字符串
void fhp_free_string(const char* s);
```

返回值：0 = OK，非 0 = 错误码。

---

## 5. 文件结构

```
tools/updater/
├── Cargo.toml
├── src/
│   ├── lib.rs          Rust 库入口
│   ├── state.rs        状态机 + 持久化
│   ├── verify.rs       验签 + artifact hash + fingerprint
│   ├── watchdog.rs     Boot-loop 看门狗
│   └── ffi.rs          C FFI API
├── include/
│   └── flutter_hotpatch_updater.h   C 头文件
└── tests/
    └── integration_test.rs
```

---

## 6. 依赖

```toml
[dependencies]
serde = { version = "1", features = ["derive"] }
serde_json = "1"
ring = "0.17"          # Ed25519 verify
sha2 = "0.10"          # SHA-256 artifact hash
hex = "0.4"
chrono = "1"
```

---

## 7. 与其他里程碑接口

- **4-B patch_builder**：生成 `patch_bundle/`（manifest.json + manifest.sig + artifacts），4-C 读取并验证
- **4-D 运行时集成**：在 dart_harness.c 里调用 `fhp_init()` → `fhp_get_next_boot_patch_dir()` → 加载补丁
- **4-E 服务端**：实现网络下载后，在 4-C 里补充 `fhp_download_patch(url)` 接口
