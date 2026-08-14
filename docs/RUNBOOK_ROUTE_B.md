# Route-B 运维手册（生产）

发布一次补丁的完整流程。所有命令可直接复制执行。

## 前置

```bash
SB=~/.shorebird/bin/cache/flutter/c15ef6379403a0a55531a058bdb2c8e55bc05c98
PY=tools/patch_builder/.venv/bin/python     # 缺则：python3 -m venv 并装 requirements.txt
```

App 必须用 **Shorebird 的 Flutter SDK** 构建（`$SB/bin/flutter`）。
X1 引擎不可用于产品，原因见 `docs/PRODUCTION_RELEASE.md`。

## 一次性：签名密钥

```bash
$PY tools/broute/keygen.py --out tools/broute/keys
```

把输出的 `patch_public_key` 写进 app 的 `shorebird.yaml`：

```yaml
app_id: <你的 app id>
base_url: https://patches.example.com     # 设备可达
auto_update: true
patch_public_key: <base64 DER SPKI>
```

`shorebird.yaml` 必须作为 asset 打进包：

```yaml
flutter:
  assets:
    - shorebird.yaml
```

**私钥 `tools/broute/keys/patch_private.pem` 不要提交。**

## 发布 release（每个版本一次）

正常构建并归档 App 二进制 —— 后续所有补丁都以它为基准：

```bash
$SB/bin/flutter build ios --release
cp build/ios/iphoneos/Runner.app/Frameworks/App.framework/App \
   releases/1.0.0+1/App.baseline
```

`release_version` = `CFBundleShortVersionString` + `+` + `CFBundleVersion`，
必须与设备上报的一致，否则服务端匹配不上。

## 发布补丁

```bash
# 1. 改源码后生成 .vmcode
FHP_TOOLCHAIN=shorebird bash tools/build_app_patch.sh <app_dir> <app_dir> /tmp/patch

# 2. 打包并签名，写入补丁仓库
$PY tools/broute/publish.py \
    --repo /srv/patches \
    --app-binary releases/1.0.0+1/App.baseline \
    --vmcode /tmp/patch/out.vmcode \
    --release-version "1.0.0+1" \
    --patch-number 1 \
    --base-url https://patches.example.com \
    --private-key tools/broute/keys/patch_private.pem
```

产出：

```
/srv/patches/releases/1.0.0+1/base.blob        增量基准（首次生成后复用）
/srv/patches/releases/1.0.0+1/patches/1.bin    zstd 压缩的 bipatch 增量
/srv/patches/releases/1.0.0+1/index.json       服务端据此应答
```

实测体积：4,423,848 B 的 .vmcode → 增量 **400,945 B（9.1%）**。

## 起服务

```bash
$PY tools/broute/server.py --repo /srv/patches --port 8765 --app-id <你的 app id>
```

生产部署务必套 HTTPS（反代或 CDN），并让 `base_url` 指向它。
`--app-id` 会拒绝把补丁下发给别的应用。

## 回滚

编辑 `index.json` 的 `rolled_back`：

```json
{"patches":[...], "rolled_back":[3]}
```

设备下次 check 会收到该列表并卸载对应补丁。
另外，若某补丁启动即崩，更新器会自动标记 `{"kind":"Bad","reason":"BootCrash"}`
并回落基线 —— 这一行为已在真机验证。

## 校验

```bash
bash tools/tests/test_broute_server.sh      # 协议一致性，9 项
```

## 排障

| 现象 | 原因与处置 |
|---|---|
| `Failed to find shorebird.yaml, not starting updater` | 没打进 assets |
| `no active patch` | 服务端没匹配上 `release_version`，或该补丁已被判 Bad |
| `File offset must be page-aligned.` | `.vmcode` 头部未按 **16384** 对齐；确认用的是当前版 `tools/linker.py` |
| `Patch signature is invalid` | `patch_public_key` 与签名私钥不配对 |
| 设备连不上服务端 | 本环境（企业网络）会阻断设备→Mac 直连；调试时改用 USB 注入，见 `spikes/shorebird_route/e2e_device.sh` |

## 协议要点（自建服务端时需遵守）

依据 `third_party/updater/library/src/network.rs` 与 `cache/signing.rs`：

- `POST /api/v1/patches/check` → `{patch_available, patch{number,hash,download_url,hash_signature}, rolled_back_patch_numbers}`
- `POST /api/v1/patches/events` → 201
- `hash` 是**解压后**文件（即 `.vmcode`）的 hex sha256
- 下载内容是 **zstd 压缩的 bipatch 增量**，基准为设备端 4 段快照拼接
  （等同 `analyze_snapshot --dump_blobs` 的输出，已实测两者字节数一致）
- 签名：`RSA_PKCS1_2048_8192_SHA256`，对 **hex hash 字符串**签名，
  签名与公钥均为 base64；公钥是 DER SPKI
