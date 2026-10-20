# G4 真机重跑（2026-10-19，固定提交）

**结论：在固定的 SDK 和引擎提交上，六项里有五项我们与参考终态相同，其中错版本这一项处置完全一致；坏 ELF 是操作者认可的限定例外。** 审计脚本 `audit.py` 共 31 项检查全部通过，5 个负控制全部报红。

## 构建身份

| 项 | 值 |
| --- | --- |
| SDK | `~/dart-3122/sdk` `agent/sdk-phase-c1` `b93028d6307`，工作树干净 |
| 引擎 | `/Users/Cruz/shorebird_engine/engine/src/flutter` 本地分支 `fhp/g4-20261019` `6e5b9c85`，基于 `e16cf749`，已跟踪文件干净 |
| Flutter.framework（签名后） | `8fbcb2e5…7a66` |
| gen_snapshot_arm64 | `f628e0aa…ce9b` |
| 正常补丁 valid.vmcode | `abeac3f0…d0b2`，linker 100.00% |
| 设备 | QA-iPhone-YPVYHY2D90（iPhone 14 / iOS 26.6） |
| 参考 | 沿用 10-16 的运行：v2，错版本一项用 v5；参考二进制没有变化 |

引擎里没有快照版本预检，参考也没有。updater 的 base 流文件与参考引擎源码（Shorebird flutter `c2515c46`）逐字节相同；附加块长度由 SDK 的 `Dart_SnapshotDataSize` 计算。

## 结果

| 输入 | 我们（v7） | 参考 | 判定 |
| --- | --- | --- | --- |
| 正常补丁 | `PATCH_V2`，存活 | 相同 | 相同 |
| 快照版本改坏（一位 ASCII 十六进制） | 两次各约 15.6 s 无标记，存活，`Installed` | 相同 | **相同** |
| ELF 类型改坏 | 首启回落 `BASE_V1`，`Bad`，存活 | 首启 SIGABRT，次启回落 `BASE_V1`，`Bad` | 终态相同；限定例外 G4-20261016-03/ELF |
| 错 base | `BASE_V1`，`Bad`，存活 | 相同 | 相同 |
| 错签名 | `BASE_V1`，`Bad`，存活 | 相同 | 相同 |
| 半截文件 | `BASE_V1`，`Bad`，存活 | 相同 | 相同 |

对照 10-16：错版本一项在 v6 上回落为 `Bad`，原因是当时引擎里加了预检。撤掉预检后，我们和参考一样，补丁仍是 `Installed`，没有标记。

## 其他检查

- 引擎 `shorebird_unittests` 27/27 通过（10-16 是 28 项，少的那一项是撤掉的预检单测）。负控制：临时撤回 SDK 里 `Dart_SnapshotDataSize` 的附加块计算，`CreateForSnapshotsMatchesDumpBlobsOrderAndSizes` 和 `CreateForSnapshotsOmitsAbsentExtraBlock` 两项失败；恢复并重建后，27 项全部通过。
- 6 个测试 app 运行后均已卸载。原 `com.fhp.b5TestApp` 在本次运行前就已不在设备上：10-16 清理后它还在，本次的卸载命令只针对 `com.fhp.g4.ours.*v7`。

## 工具链限定（Xcode 已升到 27.1）

- iOS 目标使用 iPhoneOS 27.1 SDK 的 APFS 克隆 `~/.local/share/fhp_sdk_compat/iPhoneOS27.1.sdk`，只在 `.tbd` 文件里删掉了 `arm64e.x1` 目标。原因是引擎自带的 lld 解析不了这个目标。头文件与原 SDK 逐字节相同。负控制：用未修改的 SDK，同一程序链接失败。
- 宿主工具使用 Command Line Tools 自带的 MacOSX26.5 SDK，与 10-16 的版本相同。
- 改 SDK 路径之前的 `args.gn` 备份在 `scratchpad/g4_g1_decisions_20261019/`。
- Metal Toolchain 27A266a 通过 `xcodebuild -downloadComponent MetalToolchain` 安装。

原始运行记录在 `scratchpad/g4_rerun_20261019/`。
