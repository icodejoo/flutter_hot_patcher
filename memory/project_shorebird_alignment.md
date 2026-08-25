---
name: project-shorebird-alignment
description: Shorebird 对齐任务 — Task 1-6 全部完成，已合并到 master
metadata: 
  node_type: memory
  type: project
  originSessionId: fc9a8051-d863-4ccd-98ad-814c5b494e48
  modified: 2026-08-07T02:39:49.488Z
---

**当前状态（2026-08-06，全部 DONE）**

| Task | 内容 | 状态 | Commit |
|------|------|------|--------|
| 1 | Updater Shorebird 状态机 + fhp_check_update/fhp_download_and_stage | ✅ | d695106 |
| 2 | kernel_linker --pointers-json 输出 | ✅ | d44599f |
| 3 | patch_builder zstd + channel + pointers.json | ✅ | f0b3b8a |
| 4 | patch_server Shorebird API (/api/v1/patches/check 等) | ✅ | c84a2ad |
| 5 | iOS AppDelegate updater init 前移到 Dart isolate 前 | ✅ | a7ad5bb |
| 6 | B-route vmcode diff spike (Opus) | ✅ | d9cf8ec |

**B-route 关键发现：**
- Shorebird diff 算法：bidiff-1.0.0 + zstd（全部开源 MIT crates）
- dump_blobs = analyze_snapshot --dump_blobs，产出 4 段连接 blob
- 无 linker 情况下 B-route 退化为全量 2.9MB snapshot
- ~~建议：保持 A-route 为主线，B-route 暂缓~~ **（2026-08-13 已推翻，见 [[project-landing-plan]]）**
  现结论相反：B-route 为产品路径，A-route 出局。当时的"B-route 退化为全量 2.9MB"是无 linker 所致，linker 已实现，现为 6–7KB。
- 详见：spikes/b_route_vmcode/FINDINGS.md

**Why:** 替换现有热修复系统核心，对齐 Shorebird 商业产品完整能力。

**How to apply:** 所有 Task 已完成，下一步可做端到端验收测试（见计划文档验收标准）或继续其他里程碑。

## OTA 端到端验证（2026-08-06，PASS）

**commit:** 3295d38

**验证结果：** 设备 POST /api/v1/patches/check → 下载 bundle.zst → 冷启动后 patch greet = PATCHED ✅

**痛点/修复记录：**

| 问题 | 修复 |
|------|------|
| `ring` crate 在 iOS 交叉编译出现 `___chkstk_darwin` | 替换为 `ed25519-dalek = "2"`（纯 Rust） |
| `zstd_sys` iOS 编译失败 | 设置 `IPHONEOS_DEPLOYMENT_TARGET=13.0` |
| `ureq` 在 iOS 无法发 HTTPS 请求（静默挂起） | 添加 `features = ["native-tls"]` |
| patch_server 返回 `http://` download_url，Cloudflare 要求 HTTPS | 读取 `X-Forwarded-Proto` header 决定协议 |
| `Dart_ShutdownIsolate` crash 掉后台 OTA 线程 | 从 dart_harness.c 成功路径移除该调用 |
| 原 Ed25519 私钥丢失，bundle 签名失效 | 重新生成密钥对，重新签所有 bundle |
| bundle.zst 内 patch.dill 是 5.8MB 完整 kernel（magic `90abcdef`），不兼容 `Dart_LoadLibraryFromBytecode` | 替换为 439B bytecode 文件（magic `3CBD`） |
| WiFi AP client isolation，iPhone 无法访问 Mac | 使用 Cloudflare Tunnel（`cloudflared tunnel --protocol http2`）穿透 |

**新密钥：** `tools/patch_builder/keys/` 下已更新，公钥 `70fe9e96bec44e7a6ab78f98fd6e931cd550b615fab4cd501053e80c72f8ef55`

**已知限制：** Cloudflare 隧道延迟高（~5min OTA），生产用局域网 HTTP 无此问题。

## 已完成任务（2026-08-06，commit d9be1af）

| 任务 | 说明 |
|------|------|
| 崩溃回滚验证 | Rust 20 个测试通过，`test_full_pipeline_crash_rollback` 覆盖完整链路 |
| tar 解压修复 | 已实现（非 placeholder），tar::Archive 解压完整 |
| 事件上报 | `fhp_flush_events()` FFI — crash 入队 PatchEvent，背景 POST /api/v1/events |
| kServerURL plist config | AppDelegate.m 读 Info.plist["HotPatchServerURL"]，移除硬编码 |
| Release 构建签名 | project.pbxproj Release config DEVELOPMENT_TEAM = 7VP87G446C |
| OTA 真机验证（网络受限） | ⚠️ MDM 阻断 HTTPS，代码 OK，需无 MDM 设备重测 |

## 待完成任务

| 优先级 | 任务 | 说明 |
|--------|------|------|
| 1 | 私钥管理 | 当前密钥在 tools/patch_builder/keys/，记录备份方式 |
| 2 | B-route vmcode diff 实现 | 需 fork Dart VM linker（multi-person-month），最后执行 |

### OTA 真机验证阻断记录（2026-08-07）

**阻断原因：** 设备 MDM 策略阻断出站 HTTPS（WiFi + 蜂窝均不通），与代码无关。

**代码验证状态：**
- Rust 20 个测试通过 ✅
- Mac curl → Cloudflare → patch server E2E ✅
- iOS `patch greet = PATCHED`（本地 patch）✅
- iOS 出站 HTTPS（ureq + URLSession）❌ TCP hang

**痛点文档：** `/Users/Cruz/Desktop/ota_painpoints.md`（也应 commit 到 docs/）

**下次验证条件：** 使用无 MDM 管控的 iPhone 或个人 WiFi 热点。

**下次验证方案（已确认）：** Mac 开个人热点 → iPhone 连接 → patch_server 在 192.168.2.1:8765 → Info.plist 写 http://192.168.2.1:8765 → 无需 Cloudflare，无 MDM 干扰。
