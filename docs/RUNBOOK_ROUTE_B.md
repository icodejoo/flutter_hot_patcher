# Route-B 运维手册（生产）

发布一次补丁的完整流程。所有命令可直接复制执行。

全流程由 `tools/fhpb` 一个 CLI 覆盖：

| 命令 | 干什么 |
|---|---|
| `fhpb init` | 配 app_id / 签名密钥 / `shorebird.yaml` |
| `fhpb release` | 归档一个基线版本，后续补丁都以它为基准 |
| `fhpb patch` | 改完源码后生成、签名并发布一个补丁 |
| `fhpb list` | 看 release 与补丁状态 |
| `fhpb verify` | 按设备侧规则复核一个已发布的补丁 |
| `fhpb rollback` | 下线某个补丁 |
| `fhpb serve` | 起分发服务端 |

## 前置

```bash
SB=~/.shorebird/bin/cache/flutter/c15ef6379403a0a55531a058bdb2c8e55bc05c98
```

App 必须用 **Shorebird 的 Flutter SDK** 构建（`$SB/bin/flutter`）。
X1 引擎不可用于产品，原因见 `docs/PRODUCTION_RELEASE.md`。

`fhpb` 需要 `cryptography`，缺时按它的提示建 venv：

```bash
python3 -m venv tools/patch_builder/.venv
tools/patch_builder/.venv/bin/pip install -r tools/patch_builder/requirements.txt
```

## 一次性：初始化

```bash
tools/fhpb init --app-dir <你的工程> --base-url https://patches.example.com
```

它会：生成 RSA 密钥对（`tools/broute/keys/`，权限 600）、写 `shorebird.yaml`
（含 `app_id`、`base_url`、`patch_public_key`）、把 `shorebird.yaml` 挂进
`pubspec.yaml` 的 flutter assets。

重跑是幂等的 —— 已有的 `app_id` 会被沿用。**换掉 `app_id` 会让线上所有设备
拿不到补丁**，只有确实要换时才加 `--force`。

**私钥 `tools/broute/keys/patch_private.pem` 不要提交。**

## 发布 release（每个版本一次）

```bash
tools/fhpb release --app-dir <你的工程> --repo /srv/patches --build
```

`--build` 会先跑 `$SB/bin/flutter build ios --release`；已经构建过就省掉它。

归档内容：

```
/srv/patches/releases/<release_version>/
    release.json    元数据（app_id / 时间 / 各产物 sha256 / kernel 版本）
    App.baseline    App.framework/App
    app.dill        基线 kernel —— 补丁必须对着它编
    base.aot        由 app.dill 产出并**已验证可被 gen_snapshot 接受**的 ELF
    base.blob       增量的基准
```

`release_version` 从 `Info.plist` 的 `CFBundleShortVersionString` +
`CFBundleVersion` 推出，与设备上报的一致。

**为什么要在这一步验 kernel**：一个工程被多套工具链构建过时，
`.dart_tool/flutter_build` 下会同时留着 kernel 版本不同的 `app.dill`
（实测遇到过 X1 的 v121 与 Shorebird 的 v130 并存，且 v121 那份 mtime 更新）。
只按时间挑会静默归档一份和 `App.baseline` 不同源的 kernel，
真要发补丁那天才炸。`release` 因此逐个用 `gen_snapshot` 验，取第一个能用的；
一个都不能用就当场失败，不留半成品。

同名 release 默认拒绝覆盖（覆盖基线会让已下发的补丁全部错位），
确需重来时加 `--force`。

## 发布补丁

改完源码后：

```bash
tools/fhpb patch --app-dir <你的工程> --repo /srv/patches \
    --private-key tools/broute/keys/patch_private.pem \
    --note "修 XXX"
```

补丁号自动自增，`base_url` 从 `shorebird.yaml` 读，release 自动对上当前
`Info.plist` 的版本。灰度用 `--channel beta`（默认 `stable`）。

产出：

```
releases/<ver>/patches/<n>.bin     zstd 压缩的 bipatch 增量（下发的就是它）
releases/<ver>/patches/<n>.json    该补丁的元数据
releases/<ver>/index.json          服务端据此应答
```

实测体积：4,423,848 B 的 `.vmcode` → 增量 **402,153 B（9.1%）**。

> 带插件或带 dynamic interface 的工程，复现 flutter 那串前端参数不可靠
> （实测 link% 会掉到 2.62%）。这类工程改让 flutter 自己编补丁 kernel，
> 再用 `FHP_PATCH_DILL=<patched app.dill>` 传进来。

发完复核一下：

```bash
tools/fhpb verify --repo /srv/patches --app-dir <你的工程>
```

验的是设备会验的东西：增量大小与 index 一致、`hash_signature` 能被
`shorebird.yaml` 里那把公钥验过、hash 等于 `.vmcode` 的 sha256。

## 起服务

```bash
tools/fhpb serve --repo /srv/patches --port 8765 --app-id <你的 app id>
```

生产部署务必套 HTTPS（反代或 CDN），并让 `base_url` 指向它。
`--app-id` 会拒绝把补丁下发给别的应用。

## 回滚

```bash
tools/fhpb rollback --repo /srv/patches --patch 3
```

该补丁被写进 `index.json` 的 `rolled_back`，服务端**立刻停止下发它**，
并把这个列表带给设备，设备下次 check 时卸载对应补丁。命令会打印回滚后
设备会落到哪个补丁（或基线）。

误操作可撤销：

```bash
tools/fhpb rollback --repo /srv/patches --patch 3 --undo
```

此外，若某补丁启动即崩，更新器会自动标记
`{"kind":"Bad","reason":"BootCrash"}` 并回落基线 —— 这一行为已在真机验证。

## 查看状态

```bash
tools/fhpb list --repo /srv/patches
```

```
release 1.0.0+1   app_id=1111…   建于 2026-08-18T01:47:21+00:00
  补丁   通道       状态            增量  创建时间
  #1   stable   当前        402,153B  2026-08-18T01:48:00+00:00  修 XXX
  #2   beta     当前        398,102B  …
  #3   stable   已下线      401,880B  …
```

## 校验

```bash
bash tools/tests/test_broute_server.sh      # 协议一致性，9 项
bash tools/tests/test_fhpb_lifecycle.sh     # 全生命周期语义，27 项
```

## 排障

| 现象 | 原因与处置 |
|---|---|
| `Failed to find shorebird.yaml, not starting updater` | 没打进 assets；跑 `fhpb init` 或手动加到 pubspec |
| `no active patch` | 服务端没匹配上 `release_version`，或该补丁已被判 Bad / 已下线 |
| `Invalid kernel binary format version` | 工程的 `app.dill` 与发布工具链不同源；用发布用的 SDK 重新构建 |
| `File offset must be page-aligned.` | `.vmcode` 头部未按 **16384** 对齐；确认用的是当前版 `tools/linker.py` |
| `Patch signature is invalid` | `patch_public_key` 与签名私钥不配对；跑 `fhpb verify` 定位 |
| link% 异常低 | 补丁 kernel 的编译参数与基线不一致，见上面 `FHP_PATCH_DILL` 那条 |
| 设备连不上服务端 | 本环境（企业网络）会阻断设备→Mac 直连；调试时改用 USB 注入，见 `spikes/shorebird_route/e2e_device.sh` |

## 验证边界（如实说明）

- 协议、签名、回滚、通道语义：本地自动化覆盖 ✅
- 打包链路：`release` + `patch` 已在真实 app 上跑通（link% 100%，
  `.vmcode` 4,423,848 B，增量 402,153 B）✅
- 设备侧补丁应用：USB 注入完整验证过（`BASELINE_V1` → `OTA_PATCHED_V2`）✅
- **设备经网络下载并 inflate 增量：仍未验过**。本地没有 inflate 实现
  （`fhpb verify` 只能验签名与 hash，验不了增量还原），且本机网络环境
  阻断设备→Mac 直连。部署到可达的 HTTPS 端点后需复验一次这条路径。

## 协议要点（自建服务端时需遵守）

依据 `third_party/updater/library/src/network.rs` 与 `cache/signing.rs`：

- `POST /api/v1/patches/check` → `{patch_available, patch{number,hash,download_url,hash_signature}, rolled_back_patch_numbers}`
- `POST /api/v1/patches/events` → 201
- `hash` 是**解压后**文件（即 `.vmcode`）的 hex sha256
- 下载内容是 **zstd 压缩的 bipatch 增量**，基准为设备端 4 段快照拼接
  （等同 `analyze_snapshot --dump_blobs` 的输出；实测 3,181,996 B，
  与设备日志 `SetBaseSnapshot mappings ... total=3181996` 一致）
- 签名：`RSA_PKCS1_2048_8192_SHA256`，对 **hex hash 字符串**签名，
  签名与公钥均为 base64；公钥是 DER SPKI
- 已下线（`rolled_back`）的补丁不得下发，且 `rolled_back_patch_numbers`
  必须照常带给设备，否则已装该补丁的设备卸不掉
