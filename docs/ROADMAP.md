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

## 5. 自建引擎（摆脱对 Shorebird 预编译产物的依赖）

`shorebirdtech/{flutter,engine,updater}` 都是公开仓库，**但 dart-sdk fork 未公开**
（查过 shorebirdtech 组织全量 33 个仓库，没有 dart-sdk）。我们用的是他们编译好的
`gen_snapshot` / `analyze_snapshot` / `Flutter.xcframework`，不是源码。

双模执行机制已通过反汇编对照搞清，见
**[SHOREBIRD_DISPATCH_MECHANISM.md](SHOREBIRD_DISPATCH_MECHANISM.md)**。
结论：我们缺的是 `CPUToSimulator`（原生→模拟器方向），它靠切换 `Thread` 里
缓存的 7 个 stub 入口实现，**不需要新建可执行内存**，所以 iOS 的 W^X 不是障碍。

已有的（`~/dart/sdk`，8 个提交，备份在 `~/fhp_backups/dartsdk-20260818/`）：
模拟器→原生逃逸（A2/A5/A7）、`analyze_snapshot --shorebird`（B2）、
`Dart_ShorebirdLoadVmcode`（B4）。

**C1 已完成**：`CPUToSimulator` 等效物 `SimBridge`（`~/dart/sdk` commit
`348397748e8`），5 项单测通过，含「原生代码调用 vm_remap 出的 trampoline →
进入模拟器 → 执行不可执行内存里的代码」这条承重链路。详见
[SHOREBIRD_DISPATCH_MECHANISM.md](SHOREBIRD_DISPATCH_MECHANISM.md) §9。

**C1–C5 代码已完成**（`~/dart/sdk` 5 个提交 + 引擎接线一处），机制细节与验证见 [SHOREBIRD_DISPATCH_MECHANISM.md](SHOREBIRD_DISPATCH_MECHANISM.md)：

- C1 `SimBridge`（CPU→Sim），C2 模板取自已签名 `__TEXT`
- **真机验证 `vm_remap` PASS** —— 唯一的平台级风险点已排除
- C3a/C3b 拆分 `SIMULATOR_AVAILABLE` 与 `USING_SIMULATOR`，3143 个测试差分**回归 0**，拆分构建确为原生代码生成
- C4 混合栈执行模式记账（`SimTransition`）
- C5 引擎接线：修好 `Dart_ShorebirdLoadVmcode` 在生产配置下的守卫，并让 `patch_cache.cc` 真正调用它

仍需：去掉 A1 无条件强开、Transition 记账抽象、
引擎侧接线（当前引擎从不调用 `Dart_ShorebirdLoadVmcode`，link table 从未填充）。

**这条路也可能是授权问题的出路** —— 若使用他们的预编译产物在条款上有障碍，
自建引擎是合规替代。

## 6. Android 支持

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
