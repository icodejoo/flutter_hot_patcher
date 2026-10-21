# 补丁控制台需求与方案（2026-10-21）

状态：**方案已存盘，未实现**。登录方式一项待操作者确认（见 §3）。

## 1. 为什么做、照着什么做

Shorebird 有一个 Web 控制台（console.shorebird.dev）：看 App / Release / Patch 列表、
每个补丁的安装量和失败数、回滚补丁、按渠道晋升、管理团队与 API key。
按规则 1 这是我们要对齐的产品能力；页面本身闭源，按规则 3 自实现。

**契约来源不是去猜 CLI，而是 Shorebird 公开的 OpenAPI 规范。**
`~/.shorebird/packages/shorebird_code_push_protocol/README.md` 写明该包由
`https://api.shorebird.dev/openapi.json` 生成；规范的 `info.description` 原文：
"it is the API the CLI and console use"。
⇒ 控制台调用的后端接口形状是公开的，闭源的只有页面。

| 项 | 值 |
|---|---|
| 规范 URL | `https://api.shorebird.dev/openapi.json` |
| 取得日期 | 2026-10-21 |
| sha256 | `ad2b8fccb83ba5afa95572374ca8d66a70d22a7e9984cff355952532781b2359` |
| 规范版本 | `info.version = 1.0.0`，服务器基址 `https://api.shorebird.dev/api/v1` |

规范**不入库**（它是对方的文档）；实现时由脚本按 URL 拉取并核对上面的 sha256，
对不上就拒绝跑契约测试，提示人工复核差异。

规范**不覆盖**的两处设备端接口，契约取自公开的 updater 源码
（`third_party/updater/library/src/network.rs`、`events.rs`）：
`POST /api/v1/patches/events`（`PatchEvent`：`app_id/arch/client_id/type/patch_number/platform/release_version/timestamp/message`，
`type` ∈ `__patch_install__` / `__patch_install_failure__`）与增量文件下载。

## 2. 范围

操作者 2026-10-21 选定：**完整控制台（组织、成员、角色、协作者、邀请、服务账号、API key、指标图表）
去掉计费**。

### 2.1 做

| 组 | 端点（均在 `/api/v1` 下） |
|---|---|
| 用户 | `GET/PATCH/DELETE /users/me`、`GET /users/me/personal-organization` |
| App | `GET/POST /apps`、`GET/PATCH/DELETE /apps/{appId}` |
| Channel | `GET/POST /apps/{appId}/channels`、`DELETE …/channels/{channelId}` |
| Release | `GET/POST /apps/{appId}/releases`、`GET/PATCH/DELETE …/releases/{releaseId}`、`GET/POST/DELETE …/releases/{releaseId}/artifacts` |
| Patch | `POST /apps/{appId}/patches`、`POST …/patches/{patchId}/artifacts`、`POST …/patches/promote`、`GET …/releases/{releaseId}/patches`、`PATCH …/patches/{patchId}`、`POST …/rollback`、`POST …/rollforward` |
| 指标 | `metrics/patch-installs`、`patch-downloads`、`patch-adoption`、`unique-users`、`version-distribution`、`new-devices`、`activity-heatmap`、`active-hours`；release 级的 `patch-installs`、`patch-downloads` |
| 组织 | `GET/POST /organizations`、`GET/PATCH/DELETE /organizations/{id}`、`…/apps`（含 `nav`、转入）、`…/users`（改角色、移除） |
| 协作者 | `GET/POST /apps/{appId}/collaborators`、`PATCH/DELETE …/{collaboratorId}` |
| 邀请 | 组织与 App 两级的列出/创建/撤销；被邀请方的 `GET /invitations`、`accept`、`decline`、`preview` |
| 服务账号 | `…/service-accounts` 增删改、`…/keys` 签发与吊销 |
| 审计日志 | `GET /organizations/{id}/audit-logs` |
| 设备端 | `POST /patches/check`、`POST /patches/events`、增量下载——**行为与现有 `tools/broute/server.py` 逐项相同**（§4.4） |

### 2.2 不做

| 端点 | 原因 |
|---|---|
| `/plan`、`/usage`、`/usage/patch_limit_exceeded`、`/organizations/{id}/plan`、`/organizations/{id}/usage`、`/admin/users/{id}/plan`、`/users/me/plan-cache` | 计费，操作者 2026-10-21 明确去掉 |
| `/zap/previews/**` | Shorebird 的另一个产品（预览构建），不属于代码推送 |
| `/diagnostics/gcp_*` | 测的是 Shorebird 自己的 GCP 存储速度，对我们无意义 |
| `/stats` | Shorebird 全平台公开统计 |
| `/users/me/terms`、`/users/me/notification_preferences` | 我们没有服务条款，也不发邮件/通知 |
| `…/trust-rules`（服务账号的 OIDC 信任规则） | 需要外部 OIDC 签发方；第一期 CI 用 API key 即可。表结构预留，不实现端点 |
| `…/size-analysis`、`/apps/{appId}/icon` | 我们的 release 流程不产出这两样数据；要做先改 `fhpb release` |

不做的端点一律回 `404` + 规范的 `ErrorResponse` 信封，`code = "not_implemented"`。

## 3. 待确认：登录方式

**默认采用「先做自管账号，OAuth 留接口」**（2026-10-21 我给的建议，操作者尚未回复）：

- 人：邮箱 + 密码（argon2id 哈希），服务端会话 cookie（`HttpOnly; SameSite=Lax`）。第一个用户用
  `fhpb console create-admin` 在本机建，之后靠邀请加人。
- 程序：`Authorization: Bearer sb_api_…` 的 API key（规范的 `apiKey` 方案），只存哈希，签发时只显示一次。
- 账号表按「一个用户多种登录身份」建（`user_identities(provider, subject)`），以后接 Google/GitHub OAuth
  只加一行 provider，不动 API key 与权限。
- 部署假设：内网或 VPN。公网部署需要先补 HTTPS 与速率限制（§6）。

操作者若改选公网 + OAuth，§3 与 §6 重写，其余不变。

## 4. 架构

```
                 浏览器（控制台页面）        fhpb / CI（API key）        设备 updater
                          │                         │                       │
                          ▼                         ▼                       ▼
            ┌──────────────────────────── fhp-console 服务进程 ─────────────────────────┐
            │  /            静态页面                                                     │
            │  /api/v1/**   OpenAPI 子集：鉴权 → 权限检查 → 处理 → 审计日志              │
            │  /api/v1/patches/check、/patches/events、/patches/<ver>/<n>.bin  设备协议   │
            └────────────────────┬──────────────────────────────┬────────────────────────┘
                                 ▼                              ▼
                        SQLite（元数据、事件）            blob 目录（release / patch 产物）
```

### 4.1 组件

| 单元 | 位置 | 职责 | 依赖 |
|---|---|---|---|
| `store` | `tools/console/store.py` | SQLite 模式、迁移、全部读写；别的单元不写 SQL | 标准库 `sqlite3` |
| `auth` | `tools/console/auth.py` | 会话、API key、密码哈希；产出「当前主体 + 所在组织 + 角色」 | `store` |
| `perms` | `tools/console/perms.py` | 角色 → 权限表；`require(principal, perm, resource)` | 无 |
| `api` | `tools/console/api/*.py` | 每组端点一个文件，只做参数校验、调 `store`、组装规范形状的 JSON | `store` `auth` `perms` `audit` |
| `device` | `tools/console/device.py` | check / events / 下载；不经过 `auth`（规范里 `patches/check` 的 `security: []`） | `store` |
| `metrics` | `tools/console/metrics.py` | 从事件表聚合出规范的指标响应 | `store` |
| `audit` | `tools/console/audit.py` | 每个改状态的 API 调用写一条规范形状的 `AuditLogEvent` | `store` |
| `web` | `tools/console/web/` | 静态页面，无构建步骤（原生 ES module），图表用内联 SVG 自绘；只调 `/api/v1` | 无 |

服务框架用 Flask（本机已装 3.1.3；`tools/patch_server/patch_server_flask.py` 记录过
`http.server` 在 Python 3.14/macOS 上的 `ENOTCONN` 问题）。不引入前端构建链，内网环境不依赖 CDN。

### 4.2 数据模型（SQLite）

`users`、`user_identities`、`sessions`、`organizations`（`type ∈ personal/team`）、
`organization_members(org, user, role)`、`apps(id, org, display_name)`、`app_collaborators(app, user, role)`、
`invitations`、`service_accounts`、`api_keys(hash, owner, scopes, expires_at, last_used_at)`、
`channels(app, name)`、`releases(app, version, flutter_revision, notes)`、`release_platform_status(release, platform, status)`、
`release_artifacts`、`patches(release, number, notes)`、`patch_artifacts(patch, platform, arch, hash, size, hash_signature, blob)`、
`patch_channel(patch, channel)`、`patch_rollbacks(patch, at, by)`、
`device_checks(app, client_id, release_version, platform, arch, channel, current_patch, at)`、
`device_events(… PatchEvent 全字段 …, received_at)`、`downloads(patch_artifact, client_ip, at)`、`audit_log`。

API 返回的 `id` 一律是整数主键（规范如此）；`app_id` 沿用现有的字符串 UUID，已装机设备的
`shorebird.yaml` 不必改。

### 4.3 角色与权限

规范给出 `Role = owner / admin / appManager / developer / viewer / auditor / none`、
`AppCollaboratorRole = admin / developer`、`ServiceAccountRole = viewer / developer / appManager / auditor`，
以及部分端点的权限名（`apps.update`、`channels.delete`、`releases.delete`、`releases.view`、
`patches.rollback`、`invitations.view/create/revoke`、`organizations.view/update/delete/transfer`）。

**规范没有公开「角色 → 权限」映射。** 我们的映射是推断，原则：
`viewer` 只读；`auditor` 只读 + 审计日志；`developer` 能建 release/patch、晋升；
`appManager` 再加回滚、删 channel/release、管协作者；`admin` 再加组织成员、邀请、服务账号；
`owner` 再加删组织、转移 App。映射表写在 `perms.py` 一处，测试逐格钉住；
日后若能从对方行为观测到真实映射，以观测为准修改。

### 4.4 设备协议：零行为变化

现网设备正对 `tools/broute/server.py` 跑，新服务替换它时**设备侧看不出差别**。必须保留的现有行为：
`current_patch_number` 缺失时读旧字段 `patch_number`；`channel` 缺省 `stable`；
设了 app_id 过滤时不匹配一律 `patch_available: false`；跳过已回滚、跳过渠道不符、
跳过增量文件缺失的条目；`rolled_back_patch_numbers` 总是带上；下载路径 `/patches/<ver>/<n>.bin` 不变。

在此之上新增两件事：check 请求写 `device_checks`（指标要用），events 写 `device_events`（原来只追加到 `events.log`）。

### 4.5 指标口径

| 指标 | 来源 |
|---|---|
| 安装数 / 失败数 | `device_events` 里 `__patch_install__` / `__patch_install_failure__` 计数 |
| 下载数 | 服务端记录的 `.bin` 下载请求（updater 不上报下载事件） |
| 采用率 | 每个补丁装成功的去重 `client_id` 累计，除以该 release 的活跃设备数 |
| 活跃设备 / 新设备 | 时间窗内 `device_checks` 的去重 `client_id`；首次出现在窗内的算新设备 |
| 版本分布 | 每个 `client_id` 最近一次 check 的 `release_version` |
| 热力图 / 低峰时段 | `device_checks` 按 UTC 星期×小时的平均活跃设备数 |

`granularity ∈ hour/day/week`、`start/end`、`group_by=release` 按规范实现。
**限定**：`client_id` 是 updater 自己生成的设备 ID，重装 App 会变 ⇒ 活跃设备数偏高，与 Shorebird 同源同偏差。

### 4.6 与 fhpb 的关系

- `fhpb release` / `fhpb patch` 改为通过 API 发布（API key 鉴权），走规范的
  `createRelease → createReleaseArtifact`、`createPatch → createPatchArtifact → promotePatch` 顺序。
  签名、构建、链接这些本地步骤不变。
- `fhpb rollback` 调 `rollback` / `rollforward`；`fhpb list` 调 `getReleases` / `getReleasePatches`。
- `fhpb console import --repo <dir>`：把现有的 `releases/<ver>/{release.json,index.json,patches/*.bin}`
  一次性导入，导入后对每个 release 用现有 check 逻辑与新服务各问一遍，答复逐字节相同才算导入成功。
- 现有 `fhpb serve` 与 `tools/broute/server.py` 在新服务真机验证通过后才删。

### 4.7 页面

参照 Shorebird 控制台的信息结构（需要时由操作者登录后浏览器对照，不抓取其页面代码）：
组织切换 → App 列表 → App 详情（概览指标、Releases、Channels、协作者）→ Release 详情（补丁表：
号、渠道、安装/失败/下载、采用率、状态；回滚/恢复/晋升按钮，危险操作二次确认）→
组织设置（成员、邀请、服务账号与 key、审计日志）→ 个人设置。

## 5. 错误处理

- 所有错误用规范的 `ErrorResponse{code, message, details?, documentation_url?}`。
  `401 unauthenticated`、`403 forbidden`（带缺的权限名）、`404 not_found`、`409 conflict`（重复补丁号/版本）、
  `422 invalid_request`。
- 补丁号由服务端在事务内分配，并发发布不撞号。
- 产物先写临时 blob、校验 sha256 与签名后再落库；落库失败删 blob。设备只会看到完整的补丁。
- 回滚与晋升是单条事务；审计日志与状态改动在同一事务里写，不会出现「改了但没记」。

## 6. 已知偏差与风险

- 不发 `RateLimit-*` 头、不做 429。内网假设下可接受；上公网前必须补。
- 规范自述「没有兼容性保证，随 CLI 与控制台变化」⇒ 钉 sha256，升级规范是一次显式动作，要重跑契约测试。
- 角色映射是推断（§4.3）。
- 真 `shorebird` CLI 能否通过 `SHOREBIRD_HOSTED_URL` 指向我们的服务（`shorebird_env.dart:277` 读这个变量）**未实测**，
  它的登录走 OAuth JWT，与我们的鉴权未必兼容。不作为验收条件，只作为实现后的一次探测。

## 7. 验收判据

1. **契约**：每个已实现端点的每种响应，用规范里对应的 schema 做 JSON Schema 校验，全部通过。
   负控制：在一个响应里删掉一个必填字段（如 `ReleasePatch.is_rolled_back`），校验必须报红。
2. **设备协议零变化**：同一份数据，新旧两个服务对一组 check 请求（含旧字段、缺省渠道、错 app_id、
   已回滚、文件缺失）的答复逐字节相同。负控制：去掉「跳过文件缺失」那条逻辑，必须报出差异。
3. **权限**：角色 × 端点矩阵逐格测试允许/拒绝；负控制：把 `viewer` 临时加上 `patches.rollback`，测试必须红。
4. **指标**：用一份手工构造的事件集（已知答案）跑每个指标端点，数值与手算一致。
5. **真机**：QA-iPhone-YPVYHY2D90（iOS 26.6）上，用控制台发布一个补丁 → 设备生效、控制台安装数 +1 →
   控制台回滚 → 设备回到基线、控制台显示已回滚。证据存 `docs/device_evidence/console_<日期>/`。

## 8. 实施顺序

每步结束都可单独验证，前一步不过不进下一步：

1. `store` + `device` + 导入工具：替换 `server.py`，过判据 2。
2. `auth`（自管账号 + API key）+ App / Release / Patch / Channel 端点 + `fhpb` 改走 API：过判据 1（这部分）、3。
3. 页面第一版：列表、补丁表（安装/失败数）、回滚/恢复/晋升：过判据 5。
4. `metrics` + 图表：过判据 4。
5. 组织、成员、协作者、邀请、服务账号、审计日志：过判据 1、3 的剩余部分。
