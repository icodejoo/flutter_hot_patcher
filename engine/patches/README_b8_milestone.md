# B8 里程碑所依赖的引擎树改动（2026-09-04 抢救入库）

`b8_milestone_engine_tree.diff` 是 **2026-09-03 真机 `PATCHED_V2 ✅`** 那次构建
所依赖的、**从未进过版本控制的 33 行引擎改动**。

- 构建树：`~/shorebird_engine/engine/src/flutter/engine/src/flutter/`（engine HEAD `e16cf749`）
- 产物：`out/ios_release/Flutter.framework/Flutter`，md5 `2597bced835ed9870fb0ed2911d2b7be`
- `flutter/third_party/dart -> ~/dart-3122/sdk`（SDK HEAD `1f1e51ad16e`）

⚠️ **这棵树是第四棵工作树，不在运行契约第八节的三棵之内**，
所以每轮「三棵树干净」为真的同时，它可以带着未提交改动参与构建 —— 而且确实如此。

## 三类改动，只有第一类可以直接扔

| 类 | 文件 | 内容 | 处置 |
|---|---|---|---|
| **A 纯插桩** | `patch_cache.cc`(×2)、`dart_snapshot.cc`(×4) | `fprintf(stderr,"FHPMARK …")` | 可还原 |
| **B 观测通路** | `dart_vm_initializer.cc`、`dart_runtime_hooks.cc` | `write(2)` 转发到 stderr | 🔴 **还原＝判据消失** |
| **C 真逻辑改动** | `dart_snapshot.cc`(4 行)、`dart_vm.cc`(3 行) | ELF 符号名、`params.vm_snapshot_*` | 🔴 **还原＝功能消失** |

**B 类为何不可扔**：`dart_runtime_hooks.cc` 把 Dart `print()` 转发到 stderr，
注释写明「iOS 上 `LogMessage` 走 os_log，`devicectl` 抓不到」。
⇒ **`[B5_RESULT] PASS: PATCHED_V2 ✅` 能被观测到，全靠这 5 行。**

**C 类是什么**：
1. `dart_snapshot.cc` 把四个符号名从 Shorebird 的 `kDartSnapshotData`/`kDartSnapshotText`
   改成标准 AOT 名 `kDartVmSnapshotData` / `kDartVmSnapshotInstructions` /
   `kDartIsolateSnapshotData` / `kDartIsolateSnapshotInstructions`
2. `dart_vm.cc` 给 `Dart_InitializeParams` 补上 `vm_snapshot_data` 与
   `vm_snapshot_instructions`（取自 `vm_data_->GetVMSnapshot()`）

🔴 **判据教训**：`grep -c FHPMARK` **即使跑在对的树上也不够** —— 它只覆盖 A 类。
B、C 两类一行都抓不到。**判据既选错了树，也选错了谓词。**
正确判据是 `git -C <构建树> status --porcelain`，不是按标记串 grep。

## 2026-09-04 更新：探针已清，里程碑在干净产物上复现

`engine_tree_current_probefree.diff` = 清掉 A 类探针后的当前树（**4 文件 / +19 −4**，
只剩 B、C 两类）。`b8_milestone_engine_tree.diff` 保留为历史（含探针，对应 md5 `2597bced83…`）。

| 产物 | md5 | FHPMARK |
|---|---|---|
| 09-03 23:52（里程碑当时） | `2597bced835ed9870fb0ed2911d2b7be` | 6 |
| **09-04 10:14（清理后）** | **`03a8062739f1f67190115faf56b1633a`** | **0** |

`ninja` 真 exit 0（首次尝试 `[code=127] vpython3: command not found` 卡在打包
`Flutter.xcframework`，加 `PATH=~/depot_tools:$PATH` 后通过）。
⚠️ **那次失败留下一个现行陷阱**：`Flutter.xcframework/ios-arm64/…/Flutter` 一度仍是
09-03 那份**带探针**的旧二进制，而同目录的 `Flutter.framework/Flutter` 已是新的。
两份现在同 md5、同时间、FHPMARK 均为 0。

**真机复验（干净引擎）**：`[B5_RESULT] PASS: PATCHED_V2 ✅`，
engine 与 installed 的 `LC_UUID` 同为 `4C4C44D5-5555-3144-A12F-3535AE13BF66`。

🔑 **判据为何密不透风**：`b5_test_app/lib/main.dart` 在 git 里**未修改**，
基线文案是 `'PASS ✅\n$iterations iterations, …'`，**不含 `PATCHED_V2`**
⇒ 该串只可能来自补丁；补丁未加载时（B7 那种回落）看到的会是 `20000 iterations`。
**这是自带的负控制。**
⚠️ 不要用 `strings app.dill | grep -c PATCHED_V2` 判断 —— 含 `✅` 的字面量是
UTF-16 TwoByteString，`strings` 看不见，它给 0 是**假阴性**。
