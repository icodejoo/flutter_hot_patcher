---
title: 补丁控制台架构与功能方案
status: draft
updated: 2026-10-22
summary: 在 CONSOLE_SPEC_20261021 的基础上定下组件、选型、存储、部署和分期，回答"控制台怎么搭、先做什么"。
---
# 补丁控制台架构与功能方案（2026-10-22）

> `CLAUDE.md` 把"自建分发基础设施 / 服务端"列为规则 0 完成前的待定项；本方案是操作者 2026-10-22 明确要求做的，按操作者指令推进。

## TL;DR

- 一个 Python 进程（Flask + waitress，单进程多线程）独占一个 SQLite 文件和一个内容寻址的 blob 目录。设备协议、REST API、静态页面都在这个进程里。
- **暴露面拆成两半**：设备用的 check / events / 下载必须上公网 HTTPS，其余（控制台页面、管理 API）只在内网。由反向代理按路径白名单分流，进程只有一个。
- 设备流水不按启动次数存，按"设备 × 小时"去重存，行数随设备数增长；spec §4.5 的全部指标都能从这张表算出来。
- 签名私钥永远不上服务端。服务端只存 `hash_signature`，验签留在 `fhpb` 本地（`fhpb verify` 已有）。
- 分四期：P0 接管设备协议（替换 `server.py`）→ P1 发布 API，`fhpb` 改走 API → P2 控制台第一版（MVP 到此）→ P3 指标 → P4 组织与协作。
- 阻塞的只有三件：登录方式、设备可达的公网域名、新依赖批准（§5）。

需求范围、端点清单、错误信封和验收判据以 [CONSOLE_SPEC_20261021](CONSOLE_SPEC_20261021.md) 为准，本文只写它没定的和需要订正的。

---

## 1. 依据与核验情况

| 来源 | 取得方式 | 状态 |
|---|---|---|
| Shorebird OpenAPI 规范 | 2026-10-22 `curl https://api.shorebird.dev/openapi.json`，369,603 B | ✅ 已读。sha256 = `0e129b71826e733c8b4f7ac7402c170802e59acfa2d32f7ae7ae90fa33657c02`，**与 spec 记的 `ad2b8fcc…` 不同**（见下） |
| 在线控制台 `console.shorebird.dev/orgs/60692/apps` | chrome-devtools 打开 | ❌ **在线页面未能核对**：跳转到登录页，未代填凭据。只观察到登录跳转本身：`auth.shorebird.dev/login`，OAuth 授权码 + PKCE（`code_challenge_method=S256`），`client_id=shorebird-console`，`scope=api` |
| `~/.shorebird/packages/shorebird_cli` | 本机（Windows）查 | ❌ 本机没有 `~/.shorebird`，spec 是在 macOS 上写的。CLI 源码这次**未核验** |
| `tools/broute/server.py`、`cli.py`、`RUNBOOK_ROUTE_B.md`、`ROADMAP.md` | 仓库 v1 @ `87d2db0` | ✅ 已读 |

页面结构（§4 的"对应页面"一列）全部从 API 形状推出来，没看过真页面。唯一有原文出处的是 "Account > API Keys"：规范 `securitySchemes.apiKey.description` 写着 key "minted in the Shorebird console (Account > API Keys)"。

### 1.1 对 spec 的订正

| spec 原文 | 实测 | 处理 |
|---|---|---|
| 规范 sha256 `ad2b8fcc…` | 今天是 `0e129b71…`，73 个 path | 规范一天内变了，或 spec 记的不是同一份字节，判断不了。实现前把两份 diff 一遍再重新钉。今天比 spec 多出 `DELETE /users/{userId}`（管理员删用户），归入不做 |
| 权限名列了约 15 个，含 `invitations.view` | 从各端点 `description` 里抽出 26 个，没有 `invitations.view`；`rollforward` 要的是 `patches.promoteToStable`，删协作者要 `appRoleGrants.delete`，看审计日志要 `auditLogs.view` | `perms.py` 以规范原文抽出的权限名为准，抽取脚本落盘 |
| 审计日志写"规范形状的 `AuditLogEvent`" | 规范把它定为 **OCSF 1.9.0 API Activity**（`class_uid` 恒为 6003），必填 13 个字段 | 按 OCSF 字段建表，见 §2.4 |
| `tools/patch_server/patch_server_flask.py` 记录过 ENOTCONN | v1 上没有这个目录；它在 master / route-a-research 的 `e5e5b11` | 只当历史证据引用，不复用代码 |
| "Flask 本机已装 3.1.3" | 这台 Windows 机器上 `import flask` 失败 | Flask 算新依赖，要批准（§5） |
| 回滚的处置 | 规范写明：对已回滚的补丁再回滚答 `304`；回滚会清空该 release 的 check 应答缓存，清不掉答 `424` | 我们 P0 不缓存 check 应答，所以不会出现 424；304 照做 |
| 设备 API 只列了 key 管理在服务账号下 | 控制台有个人 API key（Account > API Keys），但规范里**没有**对应端点 | 需要一组规范外的端点，形状自定（§2.6），标为偏差 |

---

## 2. 架构

### 2.1 总图

```
  公网                                        内网 / VPN
  ─────────────────────────────               ─────────────────────────────────
  设备 updater                                 浏览器（控制台）   fhpb / CI（API key）
      │ HTTPS                                        │                   │
      ▼                                              ▼                   ▼
  ┌──────────────────────── 反向代理（TLS 终结、路径白名单、限流）──────────────────┐
  │ 公网监听只放行：POST /api/v1/patches/check   POST /api/v1/patches/events        │
  │                 GET  /d/<sha256>              GET  /patches/<ver>/<n>.bin（旧）  │
  │ 内网监听：其余全部                                                             │
  └───────────────────────────────────────┬────────────────────────────────────────┘
                                          ▼
                    fhp-console（单进程，waitress 多线程）
          device ── api/* ── auth ── perms ── audit ── metrics ── web（静态）
                    │                                   │
                    ▼                                   ▼
         SQLite（WAL，console.db）            blobs/（按 sha256 存，只增不改）
```

为什么拆暴露面：spec §3 假设"内网或 VPN"，但装了 App 的手机在公网上，check 和下载必须公网可达。管理面不上公网，spec §6 说的 HTTPS、限流缺口就只剩设备那三个端点要补，代理一层就能补上。

### 2.2 组件

在 spec §4.1 的八个单元上改两处、加四个：

| 单元 | 变化 | 职责 |
|---|---|---|
| `device` | 改 | check / events / 下载。check 逻辑从 `server.py` 原样搬过来，数据源从 `index.json` 换成 `store`；流水写入走 `ingest` |
| `store` | 改 | 除 spec 所列，还负责补丁号分配与"补丁行永不删除"这条不变量（§2.5） |
| `blobs` | 新 | `put(stream) -> sha256`、`open(sha256)`、`public_url(sha256)`、`signed_url(sha256, ttl)`。目前是本地目录；换对象存储或 CDN 只改这一个文件 |
| `ingest` | 新 | 设备流水的内存队列 + 单写线程，每秒批量落库。check 请求不等写库 |
| `uploads` | 新 | 处理 `create*Artifact` 返回的上传 URL：HMAC 签名的一次性令牌，收字节、校验大小、写 `blobs`、把产物置为 `ready` |
| `importer` | 新 | `fhpb console import`，把现有补丁仓库导进来并自证答复不变（§3.3） |

依赖方向不变：`api → auth/perms/audit → store`，`device → store/ingest/blobs`；只有 `store` 写 SQL。

### 2.3 技术选型

| 项 | 推荐 | 理由 |
|---|---|---|
| 语言 | Python 3 | `fhpb`、`linker.py`、check 逻辑都是 Python，check 代码能直接搬，导入工具也能直接读 `index.json` |
| Web 框架 | Flask | spec 已选；路由 + 请求解析就够用。`send_file` 自带 `Range`，ROADMAP §1 缺的断点续传顺手补上（Werkzeug 的行为，本项目未实测） |
| 应用服务器 | waitress | 纯 Python，Windows 和 Linux 都能跑（开发机是 Windows + macOS，部署在 Linux），**单进程多线程**，正好让一个进程独占 SQLite，免掉多进程抢写锁 |
| 数据库 | SQLite（WAL，`busy_timeout`） | 零运维，备份就是一个文件。写入集中在 `ingest` 的单线程里，规模上限见 §5 的非阻塞默认值 |
| 密码哈希 | argon2-cffi（argon2id） | spec §3 已定 argon2id，Python 下这个包是标准选择 |
| API key 哈希 | 标准库 `hashlib.sha256` | key 本身 256 位随机，不需要慢哈希；查找一次就是一次索引命中 |
| 契约测试 | jsonschema（仅开发依赖） | 判据 1 要用规范里的 schema 校验每个响应 |
| 前端 | 原生 ES module，无构建；图表内联 SVG 自绘 | spec 已定。内网不依赖 CDN，也不引入 node 工具链 |
| 反向代理 | Caddy | 自动签 HTTPS 证书，路径白名单和按 IP 限流几行配置就写完；系统级安装，不进 Python 依赖 |

以上除标准库外都要操作者批准，见 §5 第 3 条。

### 2.4 数据模型

以 spec §4.2 为底，改动如下：

**设备流水（改）**：spec 的 `device_checks` 每次 check 一行，行数等于 App 启动次数。改成：

```
devices(app_id, client_id, first_seen_at)                         -- 新设备指标
device_hours(app_id, client_id, hour_utc, release_version,        -- UNIQUE(app_id, client_id, hour_utc)
             platform, arch, channel, patch_number)               -- 同一小时内后到的覆盖先到的
```

每台设备每个活跃小时一行。spec §4.5 的口径都能算：活跃设备 = 窗内去重 `client_id`；版本分布 = 每台设备最近一行；热力图 = 按 UTC 星期 × 小时数去重设备；新设备 = `first_seen_at` 落在窗内。原始 check 不落库，默认保留 90 天后按天裁剪。

**设备事件（照 spec）**：`device_events` 存 `PatchEvent` 全字段。安装 / 失败数量级是"每台设备每个补丁一两次"，不需要去重。

**补丁与渠道（简化）**：规范的 `ReleasePatch.channel` 是单个字符串，所以 spec 的 `patch_channel` 多对多表改成 `patches.channel_id` 一列，`NULL` = 还没晋升，设备看不到。

**产物（加状态）**：`release_artifacts`、`patch_artifacts` 都加 `blob_sha256`、`state ∈ pending/ready`。只有 `ready` 的产物会出现在 check 应答里，这是 `server.py`"增量文件缺失就跳过"那条规则的一般化。

**元数据（沿用规范的口子）**：`CreatePatchRequest.metadata` 是开放对象，`fhpb` 把 `link%`、`size_uncompressed`、`split_debug_info`、构建主机写进去，原样存一列 JSON。控制台不单独展示 `link%`，Shorebird 控制台没有这一项（规则 1）。

**审计日志（按 OCSF）**：`audit_log` 存 OCSF 必填字段拆出的列（时间、actor、api 操作、资源、状态、来源 IP）加整条 JSON。写入与状态改动在同一事务（spec §5）。

**ID**：照 spec，API 里的 `id` 是整数主键；`app_id` 沿用现有字符串 UUID，已装机 App 的 `shorebird.yaml` 不用改。

### 2.5 补丁号与 release 重建

现有 `fhpb` 有两条不能丢的规则（`cli.py` `next_patch_number` 与 `cmd_release`）：补丁号只增不减（`high_water`）；`release --force` 会让旧补丁全部失效。

搬到服务端后的做法：

- 补丁号由 `createPatch` 在事务里分配：`max(number) + 1`，范围是这个 release 的全部补丁行。
- **补丁行永不删除**，只会被回滚。于是 `max(number)` 本身就是高水位，不再需要单独的 `high_water` 字段；导入时把旧仓库的 `high_water` 写成一行占位补丁（`is_rolled_back = true`，无产物），保住编号。
- 重建基线 = `fhpb` 先回滚这个 release 的全部补丁，再 `deleteReleaseArtifacts`、重新上传。服务端在还有未回滚补丁时拒绝 `deleteReleaseArtifacts`（`409 conflict`），挡住"基线换了、旧增量还在发"这种装不上、又没有任何提示的情况。

### 2.6 与现有协议的衔接

**设备协议**：零行为变化，判据照 spec §4.4 和验收判据 2。补充两点：

- 现有 `--app-id` 是全局过滤。新服务天然多 App：按请求里的 `app_id` 查，查不到就答 `{"patch_available": false}`，和现在不匹配时的答复逐字节相同。
- 下载地址分新旧两种。**导入的**补丁保留原 `download_url`（`<base_url>/patches/<ver>/<n>.bin`），服务端继续提供这条路由。**新发的**补丁用 `<base_url>/d/<sha256>`：旧路径里没有 `app_id` 也没有 arch，多 App、Android 多架构（ROADMAP §5）都会撞路径；按内容寻址的地址不可变，以后挂 CDN 也不用改什么。updater 每次都从 check 应答里拿下载地址（ROADMAP §1 的结论），地址格式改了，已装机设备不受影响。

**上传**：规范的 `create{Release,Patch}Artifact` 先登记元数据，回一个上传 `url` 和 `upload_method ∈ multipart/resumable`。我们回 `<内网基址>/api/v1/uploads/<令牌>`，`upload_method = multipart`；令牌用 HMAC 签（内容是产物 id + 期望大小 + 1 小时有效期）。收完字节核大小，算 sha256 写进 `blobs`，产物置 `ready`。补丁产物的 `hash` 是 `.vmcode` 的 sha256，不是增量文件的（RUNBOOK「协议要点」），服务端算不了它，只能原样存。

**release 产物**：现在基线文件（`App.baseline`、`app.dill`、`base.aot`、`base.blob`、`symbols/`）只存在发布机的 `--repo` 目录里，所以补丁只能在那台机器上出。改成 `fhpb release` 把它们作为 release artifact 上传（`symbols/` 打成 tar），`fhpb patch` 按 release id 拉下来，按 sha256 缓存在本地。这样 CI 拿 API key 就能出补丁。release 产物里有 App 本体，**不能公开**：`ReleaseArtifact.url` 只发给已登录的调用方，是 10 分钟有效的签名地址。补丁增量才走公开的 `/d/`。

**fhpb**：子命令和参数不变，内部换成调 API（spec §4.6 的调用顺序）。原来的本地仓库模式保留一个版本，P2 真机过了再删，同时删掉 `fhpb serve` 和 `server.py`。

### 2.7 鉴权与签名

| 调用方 | 方式 |
|---|---|
| 设备 | 无（规范里 `patchCheck` 的 `security: []`）。靠代理按 IP 限流，events 请求体上限 8 KB |
| 浏览器 | 服务端会话 cookie（`HttpOnly; Secure; SameSite=Lax`）。改状态的请求还要求 `Content-Type: application/json` 且 `Origin` 是本站，挡 CSRF |
| fhpb / CI | `Authorization: Bearer sb_api_<32 字节随机>`。前缀照规范，方便日后探测真 `shorebird` CLI 能不能直连（spec §6）。库里只存 sha256，签发时显示一次 |

个人 API key 的端点规范里没有，自定为 `GET/POST /api/v1/users/me/api-keys`、`DELETE …/{keyId}`，返回形状照抄 `ServiceAccountKey` / `CreateServiceAccountKeyResponse`，算一处有编号的偏差。

**签名**：信任根是 `patch_private.pem`（RUNBOOK「密钥保管与换钥」），它不进服务端。`fhpb patch` 在本地签名，上传前先按设备规则自验一遍（复用 `cmd_verify`），服务端只存、只转发 `hash_signature`。服务端不验签：Shorebird 服务端验不验没法知道（未核验），而发错的补丁设备会拒收、会回落，不会装上。

### 2.8 部署形态

- 一台 Linux 主机或一个容器。数据目录 `/srv/fhp-console/`，下面是 `console.db`、`blobs/`、`secrets/`（HMAC 密钥、会话密钥）。
- Caddy 监听两个地址：公网域名只开 §2.1 那四条路径，内网地址全开。
- **切换**：已装机 App 的 `base_url` 指向哪台主机，新服务就得接管那台主机（同域名、同路径）。`fhpb init` 写的是什么域名，就用什么域名。
- 备份：每晚 `sqlite3 console.db ".backup"`；`blobs/` 只增不改，rsync 增量即可。
- 首个管理员：`fhpb console create-admin`，只能在服务器本机执行（spec §3）。

---

## 3. 功能分期

"Shorebird 对应"一列的页面名按 API 推断，**在线页面未核验**。"规则 1"一列：✅ Shorebird 有；⚙️ Shorebird 没有、但属于迁移或兼容我们自己的存量，不对外。

### 3.1 P0 接管设备协议（替换 `server.py`）

| 项 | Shorebird 对应 | 规则 1 |
|---|---|---|
| `store` + `ingest` + `blobs`（本地目录） | 后端存储 | ✅ |
| `POST /patches/check`、`POST /patches/events`、旧下载路径 | 设备 API | ✅ |
| `fhpb console import` + 答复自证 | — | ⚙️ |

验收：spec 判据 2（新旧服务逐字节相同，含负控制）。这一期不改任何对外行为，`Range` 也留到 P1。

### 3.2 P1 发布 API，`fhpb` 改走 API

| 项 | Shorebird 对应 | 规则 1 |
|---|---|---|
| 个人 API key（只做后端 + `fhpb console create-key`） | Account > API Keys | ✅ |
| Apps / Channels / Releases / Release artifacts / Patches / Patch artifacts / promote / rollback / rollforward | `shorebird release`、`shorebird patch` 调用的那组端点 | ✅ |
| 上传令牌、`/d/<sha256>`、`Range` | 规范的签名上传 URL；对象存储的 Range | ✅ |
| `fhpb release/patch/list/rollback` 改调 API；`patch` 拉 release 产物 | CLI 行为 | ✅ |
| 删 release 产物前要求补丁全部回滚（§2.5） | — | ⚙️ 守住现有护栏 |

验收：spec 判据 1（这部分端点）、判据 3（`developer` / `appManager` / `viewer` 三个角色）；`tools/tests/test_fhpb_lifecycle.sh` 改成对着新服务跑，50 项全过。

### 3.3 P2 控制台第一版（MVP 到此为止）

| 页面 | Shorebird 对应（推断） | 规则 1 |
|---|---|---|
| 登录 / 登出 | 登录页（Shorebird 用 OAuth，见 §5 第 1 条） | ✅ |
| App 列表 | `/orgs/{id}/apps` | ✅ |
| App 详情：Releases、Channels | App 页 | ✅ |
| Release 详情：补丁表（号、渠道、安装 / 失败 / 下载数、状态），回滚 / 恢复 / 晋升，危险操作二次确认 | Release 页 | ✅ |
| Account > API Keys：签发、吊销 | 有原文出处（§1） | ✅ |

补丁表上的三个数直接数 `device_events` 和下载记录，不等 P3 的指标端点。

验收：spec 判据 5（真机：发补丁 → 生效、安装数 +1 → 回滚 → 回到基线）。**这也是 ROADMAP §2"设备经网络下载并 inflate 增量"第一次真跑**，所以 P2 的真机记录要单独写明这一条过没过。

### 3.4 P3 指标与图表

`metrics/*` 八个 App 级端点加两个 release 级端点，App 概览页的图表（安装趋势、采用率、版本分布、活跃热力图）。规则 1 ✅。验收：spec 判据 4（手工构造的事件集，答案已知）。

### 3.5 P4 组织与协作

组织 CRUD 与切换、成员与角色、App 协作者、组织 / App 两级邀请（被邀请方接受 / 拒绝 / 预览）、服务账号与 key、审计日志页（OCSF）、App 转移。规则 1 ✅。验收：spec 判据 1、3 剩下的部分。

### 3.6 不做

照 spec §2.2，另加：`DELETE /users/{userId}`（今天规范新增的管理员接口）；OAuth / SSO 等 §5 第 1 条定了再说；服务端验签（§2.7）；`link%` 展示（§2.4）。不做的端点统一回 `404` + `code = "not_implemented"`。

---

## 4. 风险

- **规范会变**：它自己写了"没有兼容性保证"，一天之内 sha256 就对不上了（§1.1）。钉 sha256，升级当成一次显式动作，重跑契约测试。
- **角色映射是推断**：规范只给权限名，不给"角色 → 权限"表。映射只写在 `perms.py` 一处，测试逐格钉住。
- **单进程单 SQLite 的上限**：超出 §5 默认规模就得换库。`store` 是唯一写 SQL 的地方，换库只动它。
- **CDN 之后下载数会丢**：下载一旦交给 CDN，服务端就看不到下载请求了。到那时下载数要么接 CDN 日志，要么从页面上拿掉。

---

## 5. 开放问题

**阻塞的三件**（各附推荐默认值，不反对就按默认走）：

1. **登录方式**（挡 P2）。Shorebird 自己是 OAuth 授权码 + PKCE（§1 观察到的跳转）。推荐默认：照 spec §3，自管账号 + API key，`user_identities` 表留好位置，以后接 OAuth 只加 provider。
2. **设备能访问的公网 HTTPS 域名**（挡 P0 上线和 P2 真机）。推荐默认：用已装机 App `shorebird.yaml` 里 `base_url` 的那个域名，新服务接管它。若那是开发期的临时隧道，需要操作者给一个正式域名。
3. **新依赖批准**（挡 P0 开工）：`flask`、`waitress`、`argon2-cffi`、`jsonschema`（仅开发），以及系统级的 Caddy。推荐默认：全部批准，前四个写进 `tools/requirements.txt`。

**非阻塞的默认值**：

- OpenAPI 规范重新钉到 `0e129b71…`，钉之前先和 spec 那份 diff 一遍。
- 设备流水保留 90 天。
- 规模假设：每天 100 万次 check 以内用 SQLite，超出再换库。
- 旧下载路径只给导入的补丁用，新补丁一律 `/d/<sha256>`。
- 本地仓库模式在 P2 真机通过后删除。

---

## 6. 未核验项

- 在线控制台的全部页面结构（登录墙，未登录）。
- `shorebird_cli` 怎么用 release 产物出补丁、怎么上传（本机没有源码）。§2.6 的做法是从规范的上传形状和 `fhpb` 现状推的。
- 规范 sha256 和 spec 对不上的原因。
- Shorebird 服务端是否校验 `hash_signature`。
- Werkzeug `send_file` 对 `Range: bytes=N-` 回 206（文档行为，本项目未实测）。
- 真 `shorebird` CLI 能否通过 `SHOREBIRD_HOSTED_URL` 连我们的服务（spec §6，原样保留）。
