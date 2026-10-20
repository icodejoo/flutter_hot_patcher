# 复刻的 Shorebird dart-sdk（补丁序列）

Shorebird 的 dart-sdk（`shorebirdtech/dart-sdk`）是私有仓库，没有公开源码。本目录是我们按 CLAUDE.md 规则 3 自己实现的版本：以上游 Dart SDK **3.12.2 stable**（`d684a576a6aa954ae107a03b2b4e1d61c3bebe93`，与 Shorebird 同版本）为基点，加上 206 个提交，以 `git format-patch` 补丁序列的形式存放。这里只有我们自己写的代码，不含 Shorebird 的任何二进制或反编译产物。

- 补丁末端：`41693e90584a86ca9cf5025c6021f3db3ddd5fac`，分支 `agent/sdk-phase-c1`。
- 还原后的树哈希：`0f33054c387803f61b03bc452893c01f93213078`。

## 状态

复刻完成判据 G1–G4 已在 `41693e90584` 上按限定条件满足（2026-10-20）。依据见仓库根目录 `CLAUDE.md` 规则 0、`memo.md` 2026-10-19 至 10-20 各节，以及 `docs/device_evidence/`。限定条件：G1 只覆盖 92 个选项 × 3 组 fixture；G3 只在 iOS 26 的一台设备上验证；C1 对 RC3 有一个窄例外。

## 还原

```bash
git clone https://dart.googlesource.com/sdk.git dart-sdk   # 或用 depot_tools 的 fetch dart
cd dart-sdk
git checkout -b fhp d684a576a6aa954ae107a03b2b4e1d61c3bebe93
git am --empty=keep /path/to/flutter_hot_patcher/sdk/patches/*.patch
git rev-parse HEAD^{tree}   # 应为 0f33054c387803f61b03bc452893c01f93213078
```

必须加 `--empty=keep`：第 166 个补丁（`F37 erratum`）是一个只有说明、没有文件改动的提交。不加的话，`git am` 会在这里停下。

构建步骤见上游 Dart SDK 的文档，以及 `memo.md` 里各构建目录的 `args.gn` 说明。另外，在 Xcode 27 上，宿主侧构建要把 `mac_sdk_path` 指向 CLT 的 `MacOSX26.5.sdk`。

## 来历

2026-10-20，经操作者决定，补丁序列放进这个公开仓库。此前（2026-08-19）的做法是「自研 VM 改动不推公开仓库，只做离线 bundle」，已被这一决定取代。补丁序列由下面这条命令生成：

```bash
git -C ~/dart-3122/sdk format-patch --no-stat -o sdk/patches d684a576a6a..41693e90584
```

生成后已在一份干净的上游基点上用 `git am --empty=keep` 打回验证：206 个提交全部还原，树哈希与原分支逐字节相同。
