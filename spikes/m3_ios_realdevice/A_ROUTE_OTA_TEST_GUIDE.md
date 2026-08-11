# A-route OTA E2E 测试指南

**目标：** 验证 patch_server 下发 `bytecode-v5` bundle（patch.dill 返回 'PATCHED_OTA_V2'），
Updater 下载解压验证，冷重启后 `dart_run` 加载 patch.dill，Result label 显示 **PATCHED_OTA_V2**。

**准备状态（已完成）：**
- `tools/patch_server/patches/1.0+1/bytecode-v5/bundle.zst` ✅
- patch_number=5（高于 vmcode-v4 的 4），type=bytecode ✅
- 签名已用 `tools/patch_builder/keys/private_key.pem` 生成，Ed25519 验证通过 ✅
- patch.dill: 365B，3CBD 格式，`String greet() => 'PATCHED_OTA_V2';` ✅

---

## 测试步骤

### 1. 启动 patch_server

在 Mac 上从用户 Terminal 启动（需要访问 Documents 目录的 TCC 权限）：

```bash
cd ~/Documents/flutter_hot_patcher/tools/patch_server
python3 patch_server_flask.py --patches-dir patches --port 8765
```

确认输出：
```
[server] Flask patch server on 0.0.0.0:8765
[server] Patches dir: .../patches
```

### 2. 确认 Mac IP

```bash
ipconfig getifaddr en0    # WiFi
# 或
ipconfig getifaddr en1    # Ethernet
```

记下 IP，例如 `192.168.1.5`。

### 3. 手动验证 server 返回 bytecode-v5

```bash
curl -s -X POST http://localhost:8765/api/v1/patches/check \
  -H "Content-Type: application/json" \
  -d '{"release_version":"1.0+1","platform":"ios","channel":"stable","current_patch_number":0}' \
  | python3 -m json.tool
```

期望：`"patch_type": "bytecode"`, `"number": 5`, `download_url` 含 `bytecode-v5/bundle.zst`

### 4. 修改 Info.plist 中的服务器 URL

在 Xcode 或直接编辑：
```xml
<key>HotPatchServerURL</key>
<string>http://192.168.1.5:8765</string>
```

确保 iPhone 和 Mac 在同一网络（推荐：Mac 开个人热点，iPhone 连接，IP 固定为 192.168.2.1）。

### 5. 清理设备已有状态（重要）

如果设备之前有 vmcode-v4 staged state，需要清除：
- 在设备上卸载 HotPatchDemo App
- 重新安装（这会清除 Application Support/HotPatchUpdater/ 目录）

### 6. 重建并部署 Xcode

```bash
cd spikes/m3_ios_realdevice/HotPatchDemo
xcodebuild -scheme HotPatchDemo -destination 'id=<UDID>' \
  -configuration Release build install
```

或在 Xcode 中 Product → Run。

### 7. 触发 OTA 下载（首次启动）

App 启动后 `_checkForUpdatesInBackground` 在后台线程：
1. `fhp_check_update(server_url, ...)` → server 返回 bytecode-v5
2. `fhp_download_and_stage(download_url, ...)` → 下载 bundle.zst，解压，验证，返回 0

从 Console 查看日志：
```
[Updater] Patch #5 type=bytecode url=http://192.168.1.5:8765/patches/1.0+1/bytecode-v5/bundle.zst
[Updater] Patch #5 staged OK. Cold restart to apply.
```

如果出现网络错误，检查：
- iPhone 和 Mac 是否在同一网络
- patch_server 是否从用户 Terminal 启动（TCC 问题）

### 8. 冷重启验证

杀掉 App（不是后台，要完全退出），重新启动。

从 Console 或 dart_debug.txt（TMPDIR）查看日志：
```
dart_run: bundle_dir=<path>/HotPatchUpdater/data/patches/5
patch.dill: 365 bytes from <path>/patches/5/bytecode/patch.dill
LoadLibraryFromBytecode OK
patch greet = PATCHED_OTA_V2
```

**Result label 显示：PATCHED_OTA_V2** ✅

---

## 预期结果

| 验证点 | 期望值 |
|--------|--------|
| server check response | `patch_available: true, number: 5, type: bytecode` |
| fhp_download_and_stage return | 0（成功） |
| fhp_get_next_boot_patch_dir | `.../patches/5/` |
| dart_run log | `patch greet = PATCHED_OTA_V2` |
| UI label | **PATCHED_OTA_V2** |
| fhp_confirm_health | 无 crash，patch 标记为 confirmed_good |

---

## 若测试 PASS 后续操作

1. 在 RESULTS.md 中追加 A-route OTA E2E 验证结果
2. 更新 GATE_STATUS.md 将该项标记为 ✅ PASS
3. 意味着 Shorebird 等价能力**完全闭环**：
   - 数据段 OTA（B-route）✅
   - 函数体 OTA（A-route via dart2bytecode + Dart_LoadLibraryFromBytecode）✅
   - W^X 合规 ✅
   - Ed25519 签名验证 ✅
   - boot-loop watchdog ✅

---

## Bundle 构建命令（如需重建）

```bash
# 1. 编译新 patch.dill
AOTRUNTIME=~/engine_ios/src/out/host_release/dartaotruntime
D2B=~/engine_ios/src/out/host_release/gen/dart2bytecode.dart.snapshot
PLATFORM=~/engine_ios/src/out/host_release/vm_platform_strong.dill

"$AOTRUNTIME" "$D2B" \
  --platform "$PLATFORM" \
  --output /tmp/patch_new.dill \
  spikes/m3_ios_realdevice/patch_greet_v2.dart

# 2. 构建 bundle.zst
/tmp/pb_env/bin/python3 tools/patch_builder/patch_builder.py \
  --manifest spikes/m3_ios_realdevice/HotPatchDemo/HotPatchDemo/patch_bundle \
  --bytecode /tmp/patch_new.dill \
  --private-key tools/patch_builder/keys/private_key.pem \
  --patch-id "greet-bytecode-v3" \
  --patch-number 5 \
  --app-version "1.0+1" \
  --platform ios \
  --channel stable \
  --output-dir /tmp/bytecode-v5-new

cp -r /tmp/bytecode-v5-new/* tools/patch_server/patches/1.0+1/bytecode-v5/
```
