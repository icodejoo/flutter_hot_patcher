# 待实现

按优先级排列。每条都注明**当前状态**与**判定依据**，不写没根据的估计。

---

## 1. 自建分发基础设施（服务器 / 云 / CDN）

**现状**：`tools/broute/server.py` 是 151 行的 `ThreadingHTTPServer`，
只实现了协议本身。它**不能直接上生产**：

| 缺什么 | 后果 |
|---|---|
| TLS | 明文传输；`base_url` 必须是 HTTPS 才有意义 |
| 鉴权 / 限流 | 补丁仓库目录对外全开 |
| `Range` 支持 | 见下，断点续传失效 |
| 可观测性 | `events` 端点只落 `events.log`，无指标无告警 |
| 高可用 | 单进程单目录，无副本 |

### 关键结论：CDN 不需要可信

设备下载后会**独立校验** sha256 与 RSA 签名（`cache/signing.rs:37`，
公钥编译在包里）。因此下载内容即使被 CDN 或对象存储篡改，设备也会拒绝。

**这意味着分发可以拆成两半**：

```
POST /api/v1/patches/check     ← 必须是我们的服务（决定发什么补丁）
POST /api/v1/patches/events    ← 必须是我们的服务（遥测）
GET  <download_url>            ← 可以是任意 CDN / 对象存储，无需可信
```

`download_url` 由我们在 `index.json` 里指定，指向哪里都行
（`network.rs` 只有两个 URL 构造函数，都基于 `base_url`；下载地址完全由应答决定）。
所以 CDN 那一半是纯粹的静态文件分发，不承担安全责任。

### 必须实现 `Range`

更新器在续传时会发 `Range: bytes=N-`（`network.rs:90`），期望 `206` +
`Content-Range`。当前 `server.py` 忽略它、一律返回 200 全量。

**这不是正确性 bug** —— `network.rs:109` 明确写了「服务器忽略 Range 返回 200
就从头开始」，所以会优雅降级。但每次断网都要重下整个补丁。
选 CDN / 对象存储时确认它支持 Range（S3、GCS、多数 CDN 都支持）。

### 其他协议约束（自建时不能违反）

- `events` 端点必须返回 **201**
- `check` 应答里 `rolled_back_patch_numbers` 必须照常返回，
  否则已装被回滚补丁的设备卸不掉
- 已下线 / 增量文件缺失的补丁不得下发（`server.py` 已实现，迁移时别丢）

---

## 2. 设备经网络下载并 inflate 增量（**从未验证**）

整条链路唯一没有被真实数据覆盖的环节。

已验证：补丁应用本身（USB 注入，`BASELINE_V1` → `OTA_PATCHED_V2`）、
签名与 hash（`fhpb verify`）。

**未验证**：设备从网络下载增量，并用 bipatch inflate 还原出 `.vmcode`。
本地没有 inflate 实现，`fhpb verify` 验不了这一步；且开发环境的企业网络
阻断设备→开发机直连。部署到设备可达的 HTTPS 端点后必须复验一次。

---

## 3. 轮换签名私钥

`tools/fhpb rotate-key --app-dir <工程>`。

研发分支历史里那把私钥已推送到公开仓库，必须视为泄露。
本分支历史不含它，但钥匙本身已公开。**正式发布前必做**，
且换钥后必须重新发版（公钥编译进包）。详见 RUNBOOK「密钥保管与换钥」。

---

## 4. `base_url` 缺失的护栏

`shorebird.yaml` 不写 `base_url` 时，更新器会**静默回落**到
`https://api.shorebird.dev`（`config.rs:21` 的 `DEFAULT_BASE_URL`，
经 `.unwrap_or()` 生效），设备转而去请求一个不属于你的服务器，且无任何报错。

`fhpb init` 总是写这一行，但手工编辑 yaml 删掉就会中招。
应在 `fhpb release` / `patch` 里加检查：缺 `base_url` 就拒绝发布。

---

## 5. Android 支持

设备侧不需要构建任何东西 —— Shorebird 的 Android 引擎产物是预编译下发的，
Rust updater 本身已支持 Android（`android.rs` 处理 APK split 与 `libapp.so` 定位）。

需要移植的是服务端一侧：

| 项 | 说明 |
|---|---|
| `linker.py` 的页对齐 | 现在写死 `_PAGE_SIZE = 16384`（iOS arm64）。Android 传统 4KB、15+ 要求支持 16KB —— **必须真机实测确定，不能照搬** |
| 平台抽象 | 版本号从 `AndroidManifest.xml` 取（非 `Info.plist`）；产物路径 `android-arm64-release`；`platform` 字段 |
| base 二进制 | Android 的 `libapp.so` 本身就是 ELF，iOS 上「Mach-O 转 ELF」那一步**可能可省** —— 待实测 |
| 多架构 | `arm64-v8a` / `armeabi-v7a` / `x86_64` 各需一份补丁。当前仓库布局 `releases/<ver>/patches/<n>.bin` **没有 arch 维度**，属数据结构改动 |

平台无关的部分（LinkTable 生成、签名、分发协议、发布护栏）可直接复用。
