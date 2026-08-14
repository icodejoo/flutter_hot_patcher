---
name: project-route-a-archived
description: Route-A 仍归档但已复活可跑（2026-08-14 复核）；四项约束里三条被推翻，端到端本机 PASS
metadata:
  node_type: memory
  type: project
---

**Route-A 归档于 2026-08-14；同日复核推翻了归档时的多条技术前提。**
详见 `docs/ROUTE_A_RESEARCH.md`（新增）与 `archive/route_a/README.md`。

## 定位不变

按规则 1，Shorebird 不提供此能力 → 不进产品线，只作研究能力。
性能优势（KBC 15.64 ns/迭代 vs Route-B 62.30，4.0×）落在无用区间，见 [[project-kbc-benchmark]]。

## 复核推翻的三条约束

1. **`loadDynamicModule` 对 Flutter app 可达**（原说不可达）。
   `pkg/kernel/lib/target/targets.dart:347` 白名单放行**包名**为
   `dart_internal` / `dynamic_modules` 的包 import `dart:_internal`。
   stock Flutter 3.29.0 实测：`dart run` / `dart compile aot-snapshot` /
   `flutter build bundle` / `frontend_server_aot --target=flutter --aot --tfa` 全部通过。
   shim 在 `spikes/route_a_v2/dart_internal/`，**包名是 load-bearing，不能改**。
2. **v02 是外来 VM 的格式**。`~/dart/sdk` 的 `constants_kbc.h:245` 是 1，
   `bytecode_reader.cc:741` 拒绝非 1。v02 属于 `spikes/m3_ios_realdevice` 里那份
   预编译 `libdart_aotruntime_product.a`（导出 `Dart_LoadLibraryFromBytecode` 等
   `~/dart/sdk` 根本没有的 API）。**2026-08-11 的 A-route 真机验证跑的是那份外来 VM**，
   结论不能平移到 X1。`dbc.dart` 已恢复上游 1，原改动存 `archive/route_a/dbc_v02.patch`。
3. **X1 跑不了 Flutter app 的根因是我们自己**：见 [[project-x1-research-branch]]。
   Route-A 不需要 Simulator，去掉 A1 hunk 重建即可（`args.gn` 里 `dart_dynamic_modules=true` 已就绪）。

约束 1（每模块一个 entry point，须 static/无参/无类型参数）仍然成立。
但有了 `--import-dill`，模块可直接写 app 顶层字段，不必再用闭包表回传。

## 新增可跑资产

- `tools/route_a/{build_sdk,build,test}.sh` — 流水线取自上游
  `pkg/dynamic_modules/test/runner/aot.dart`，四步缺一不可：
  app kernel 编两遍（`--aot` + `--no-aot`，都带 `--dynamic-interface`）→
  `gen_snapshot --snapshot-kind=app-aot-elf` →
  `dart2bytecode --import-dill <app_no_aot.dill> --validate <yaml>`。
  旧的 `tools/build_ios_patch.sh` 缺后两项，产出的模块看不见 app 任何声明。
- `spikes/route_a_v2/` — 最小 app + 模块，`tools/route_a/test.sh` → `PASS route_a_e2e`
  （BASELINE → PATCHED_V1，574 B KBC v01 模块）。
- host SDK：`~/dart/sdk/xcodebuild/ReleaseARM64DM`（`dart_dynamic_modules=true`，
  独立 out 目录，不影响 Route-B 的 `ReleaseARM64`）。上游 AOT 套件 **12/12 pass**
  （`multiple_classes` 需给它自己的 yaml 的 `callable:` 补 `- library: 'dart:core'`，是上游测试数据缺口）。

## Flutter 侧进展（2026-08-14 下午）

- X1 引擎已带 FFI 补丁重建（382/382）。产出的 `Flutter.xcframework` 离线校验：
  `Not supported on simulated architectures` = 0、`Loading of dynamic modules is not supported` = 0。
- **Flutter iOS release app 已能打出来**（`--local-engine ios_release`），
  app 里经 `package:dart_internal` import `dart:_internal`：
  不带 dynamic interface 68.2 MB ✅；带 dynamic interface 70.4 MB ✅（需下面的补丁）。
- **新阻碍并已修**：`--dynamic-interface` + Flutter AOT 派发表 →
  `gen_snapshot` FATAL `Function has no assigned selector ID`
  （实测是 `package:flutter/.../shortcuts.dart` 的 `KeySet._set_`）。
  annotator 保活了从不被动态派发的成员，TFA 不给它们分配 selector；
  同文件的 `SetupSelectorRows` 本来就跳过 `kInvalidSelectorId`，只有 `NumberSelectors`
  那处 FATAL 没有。改成 `continue` 即可 → `engine/patches/dartsdk_dynamic_modules_aot.diff`。
- **dynamic interface 不能绕过**：不传它时模块能编，加载时 VM 报
  `bytecode_reader.cc:922 Unable to find library package:...`。

## 工具链已打通（2026-08-14 傍晚）

**卡点根因**：`flutter_tools/artifacts.dart:1466` 找不到 `<host_out>/dart-sdk/bin`
就回落 `engine_src/flutter/prebuilts/macos-arm64/dart-sdk`（预编译 Dart，kernel **122**），
而 `~/dart/sdk` 是 **121** → `dart2bytecode --import-dill` 直接拒绝。
`out/host_release` 还是 `target_cpu="x64"`（M2 上走 Rosetta）——
`target_cpu` 是 gn gen 时传的，不会随机器变。

**修法**：`tools/route_a/build_host_engine.sh` 建 `out/host_release_arm64`
（`target_cpu=arm64` + `full_dart_sdk=true`）。app 构建必须带
`--local-engine-host host_release_arm64`，否则 app.dill 还是 122。

**结果**：
- Flutter iOS app 69.7 MB，`app.dill` kernel **121** ✅
- **Flutter 的 KBC 模块已产出**：`tools/route_a/build_flutter_module.sh` → 510 B KBC v1，
  引用并改写 `package:fapp/patchable.dart` 的顶层字段，`--validate` 通过
- Route-B 的 `.vmcode` 也按新引擎重做：link% 100%、link table 7123、
  内嵌 ELF 偏移 65536 逐字节 == patch.aot；按分节比对 **`.text` 1,597,072 B 逐字节相同**，
  差异只在 `.rodata` +96 B。`tools/build_app_patch.sh` 已改为优先用 host_release_arm64 的 dart-sdk

## 真机 PASS（2026-08-14，iPhone 14 / iOS 26.6，`00008110-000E583836F3601E`）

**Route-A 在真实 Flutter app 上跑通** —— 归档说的「上不了 Flutter」被推翻：
```
FHP_A=before=BASELINE / module=586B / status=loaded / after=PATCHED_V1
```
app 在 `spikes/route_a_v2/flutter_app`（`com.hotpatch.bench.hotpatch`），
模块推到 `Documents/module.bytecode`。

**FFI 修复在 iOS 运行时也 PASS**：该 app 用 `path_provider`(MethodChannel) +
`dart:io` 读文件，都成功；整轮日志 `Not supported on simulated architectures` **0 次**。

**Route-B `.vmcode` 真机 PASS**：`active path: .../patches/1/dlc.vmcode` →
`FHP_RESULT=OTA_PATCHED_V2`（baseline 那轮是 BASELINE_V1）。

## 真机操作要点（下次直接用）

1. **state root 没有 `<app_id>` 那一层**。`e2e_device.sh` 原按
   `shorebird.cc:158-159` 推成 `.../shorebird_updater/<app_id>`，updater 完全不看，
   日志停在 `no active patch`。正确路径：
   `Library/Application Support/shorebird/shorebird_updater/{pointers.json,patches/<N>/{dlc.vmcode,state.json}}`。
   `pointers.json` 还多一个 `"boot_started_at": null`。脚本已改正。
2. **构建不能加 `--no-codesign`**，否则没有 `embedded.mobileprovision`，`devicectl install` 直接失败。
   `e2e_device.sh` 的重签步骤已改成「已正确签过就跳过」——原来用 `find-identity` 第一条，
   那是别的 team 的证书，重签会让描述文件对不上。
3. **免费开发者账号，同设备最多 3 个 app**。装第 4 个必须先卸一个。
4. 判定用 `idevicesyslog -u <udid>`，不要用 `devicectl --console`（Flutter 的 print 走 os_log，
   `--console` 抓不到）。**同时只开一个 idevicesyslog**，多开会互相抢流。
5. valapp29 的 bundle id 是 `com.hotpatch.bench.shorebirdDemo`。

## 仍未做

- 同引擎 A/B 性能对拍（`bench_device.sh` 需按上面第 1 条改 state root 后跑）；已无前置阻碍
