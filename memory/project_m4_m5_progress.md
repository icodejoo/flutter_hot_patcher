---
name: project-m4-m5-progress
description: M4/M5 全部完成 — 里程碑狀態和關鍵文件位置
metadata: 
  node_type: memory
  type: project
  originSessionId: 292d5de3-9451-4c03-89d3-fada43b9bbd2
  modified: 2026-08-06T09:49:29.792Z
---

## 完成狀態（2026-08-04，全部 DONE）

| 里程碑 | 狀態 | 位置 | 關鍵産出 |
|--------|------|------|---------|
| M3 iOS 真機 hotpatch | ✅ | spikes/m3_ios_realdevice/ | Dart_LoadLibraryFromBytecode + Dart_Invoke |
| 4-A kernel_linker 生産化 | ✅ | spikes/gate2_linker/tools/kernel_linker/ | manifest.json + entry_table.bin |
| 4-B 補丁流水線 | ✅ | tools/patch_builder/ | Ed25519 簽名，7 tests |
| 4-C Updater（Rust） | ✅ | tools/updater/ | 16 tests，boot-loop watchdog，C FFI |
| 4-D 運行時集成 | ✅ | spikes/m3_ios_realdevice/HotPatchDemo/ | libflutter_hotpatch_updater.a 集成，iPhone 14 PATCHED |
| 4-E 私有服務端 | ✅ | tools/patch_server/patch_server.py | /check /patches /telemetry，5 tests |
| 5-A 差分等價測試台 | ✅ | tools/patch_server/equivalence_tester.py | 4/4 PASS |
| 5-B 崩潰監控 + 熔斷 | ✅ | ViewController.m + withdraw.sh | 匿名遙測 + 5% 閾值警報 |

## 文件訪問注意
- Documents TCC 需要 Finder AppleScript 讀寫
- Terminal 命令通過 `osascript tell Terminal do script` 執行
- Git commit 通過 Terminal 的 shell script 執行

## 技術關鍵踩坑
- dart:_internal 不能用戶代碼 import → 用 @pragma vm:external-name
- Dart_LoadLibraryFromBytecode 返回庫，Dart_Invoke(lib,"greet") 直接調用
- Rust --packages flag 需要 = 連接（不能分開）
- URL fingerprint 1.0+1 被解碼成空格 → replace(' ','+')
- libflutter_hotpatch_updater OTHER_LDFLAGS 需要 -ldart_aot_ios 後面加

## Why:
用戶要求全程自決，從 M3 補完到 M5

## Shorebird 对齐（2026-08-06，Task 1-6 DONE）

在 M3-M5 基础上完成 Shorebird 协议对齐：
- tools/updater/: Shorebird 状态机 + fhp_check_update/fhp_download_and_stage FFI
- spikes/gate2_linker/: kernel_linker --pointers-json 输出
- tools/patch_builder/: zstd 压缩 + channel + patch_number
- tools/patch_server/: /api/v1/patches/check + /api/v1/events + /api/v1/channels
- spikes/m3_ios_realdevice/: AppDelegate init 前移（Shorebird 时序对齐）
- spikes/b_route_vmcode/: vmcode diff 算法已确认（bidiff+zstd），B-route 暂缓
- OTA 真机验证 PASS（commit 3295d38）：iPhone 从 Cloudflare tunnel 拉取 bundle.zst → 冷启动 PATCHED

## B-route Phase 1 PASS / Phase 2 前提已修正（2026-08-07）

Phase 1 iOS 14 真机（iPhone 14, arm64）PASS：greet() 从 "ORIGINAL" → "VMCODE_PATCHED"，diff 2.4KB，
全程 mmap(PROT_READ)。约束：只支持 data-only 变化（IsolateSnapshotInstructions 不变）。

Phase 2 的架构前提已被取证推翻，详见 [[project-b-route-phase2]]。
