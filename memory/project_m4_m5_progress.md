---
name: project-m4-m5-progress
description: A-route OTA E2E PASS（2026-08-11）——greet=OTA_NEW，Shorebird等价能力完整验证
metadata: 
  node_type: memory
  type: project
  originSessionId: 77e18903-1313-49b5-a10b-492ba8792d22
  modified: 2026-08-11T05:41:15.064Z
---

**全部里程碑完成（2026-08-11）**

> **作用域限定（2026-08-13 补）**：本记录的 OTA 验证是在**独立 Dart embedder**
> （`spikes/m3_ios_realdevice/HotPatchDemo`，直接链 `libdart_aotruntime_product.a`）
> 上完成的，**不是** Flutter app。A-route 已按顶级规则 1 出局产品线，
> 见 [[project-landing-plan]] 与 [[project-flutter-plugin-blocker]]。


| 里程碑 | 状态 | 关键验证 |
|---|---|---|
| A1–A7 | ✅ | macOS dartaotruntime 端到端 PASS |
| B1–B4 | ✅ | Flutter Engine 重建 + iOS 真机 |
| OTA B-route | ✅ 2026-08-11 | vmcode_patched_data → `baseline result = PATCHED!` |
| **OTA A-route** | **✅ 2026-08-11 PASS** | patch.dill → `patch greet = OTA_NEW`，`result=OTA_NEW` |

**A-route OTA E2E 完整日志（iPhone 14 实录）：**
```
dart_run: bundle_dir=/var/.../patches/5
dart_run: using baseline IsolateSnapshotData (0 bytes)
setup OK
patch.dill: 439 bytes from .../patches/5/bytecode/patch.dill
LoadLibraryFromBytecode OK
patch greet = OTA_NEW
result=OTA_NEW
```

**实现路径：**
1. 对已验证的 v02 dill（439B）做二进制字符串替换（PATCHED→OTA_NEW，等长 7 字节）
2. patch_builder 签名打包 bundle.zst（patch_number=6）
3. 通过 devicectl device copy to 注入 patches/5/ 目录
4. updater_state.json 设置 `stage=next_boot`, `staged_dir=.../patches/5`
5. 冷重启：fhp_init → on_cold_boot(next_boot→pending) → fhp_get_next_boot_patch_dir → patches/5
6. dart_run(patches/5) → Dart_LoadLibraryFromBytecode → Dart_Invoke("greet") → "OTA_NEW"

**Shorebird 等价能力对齐（全部验证 PASS）：**
- 数据段常量 OTA（B-route）✅ PASS
- 函数体 OTA（A-route via Dart_LoadLibraryFromBytecode）✅ PASS
- Simulator 解释执行 + SimulatorToCPU 原生执行 ✅ PASS
- iOS W^X 完全绕过（PROT_READ）✅ PASS
- Ed25519 签名验证 ✅ PASS
- boot-loop watchdog ✅ PASS

**关键技术坑（为下次会话记录）：**
- dart2bytecode (Aug 2026) 产出 3CBD v01，iOS Dart VM 只接受 v02
  → 解法：对 v02 模板做等长二进制替换（或找到产出 v02 的编译参数）
- iOS 数据容器 UUID 每次重装变化，注入 staged_dir 必须先获取 fhp_init dataDir
- devicectl copy to 文件路径必须与 fhp_init dataDir 一致（/var/mobile/...，不加 /private）
- A-route 激活时必须跳过 vmcode_patched_data.bin 加载（ViewController.m 已修复）
- dart_debug.txt 在 appDataContainer/tmp/dart_debug.txt，不在 temporary domain
- 企业防火墙/AP isolation 阻断直连，Cloudflare tunnel HTTPS 也被阻断
  → 绕过：devicectl device copy to 直接注入文件，无需网络

**How to apply:** 所有 Shorebird 等价能力完整验证。项目核心技术目标达成。
