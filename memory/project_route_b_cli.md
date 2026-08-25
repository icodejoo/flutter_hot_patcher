---
name: project-route-b-cli
description: Route-B 定为唯一产品方案；fhpb CLI 全流程 + 发布护栏 + 换钥；私钥已公开待轮换（2026-08-18）
metadata: 
  node_type: memory
  type: project
  originSessionId: dc4cce83-bc27-467b-8fb1-5ed4b50d62f0
  modified: 2026-08-18T01:53:20.636Z
---

**2026-08-18 用户定案：产品线只走 Route-B，Route-A 不再考虑。**
补齐了 Shorebird 那样的完整生命周期，入口是 `tools/fhpb`（实现 `tools/broute/cli.py`）。

## 命令

`init`（幂等，重跑不换 app_id）/ `release` / `patch`（补丁号自增、`--channel`）/
`verify` / `rollback [--undo]` / `list` / `serve`。
手册：`docs/RUNBOOK_ROUTE_B.md`。

## 本轮发现并修掉的三个真问题

1. **app.dill 选错会静默产出错基线**。工程被多套工具链构建过时
   `.dart_tool/flutter_build` 下同时有 kernel v121（X1）和 v130（Shorebird）的
   `app.dill`，且 **v121 那份 mtime 更新**。原来按 mtime 挑 → 归档到和
   `App.baseline` 不同源的 kernel。现在 `release` 逐个用 `gen_snapshot` 验，
   取第一个能用的，全不能用就当场失败且不留半成品。
2. **回滚后服务端仍会下发被回滚的补丁**。原 `server.py` 取 `patches[-1]`，
   不看 `rolled_back`。已改为先过滤 `rolled_back` 再按 channel 选最新。
3. **`build_app_patch.sh` 在 macOS bash 3.2 下崩**：`set -u` + 空数组
   `"${DI_ARGS[@]}"` → unbound variable。改成 `${DI_ARGS[@]+"..."}`。

## 实测数据（真实 app，Shorebird SDK 构建）

- `base.blob` **3,181,996 B** —— 与设备日志 `SetBaseSnapshot total=3181996` 一致
- `.vmcode` 4,423,848 B，link% **100.00%**，增量 **402,153 B（9.1%）**
- 签名验签通过；换错公钥被拒

## 验证边界（别谎报）

- 协议/签名/回滚/通道：`tools/tests/test_fhpb_lifecycle.sh` 27 项 PASS
- 打包链路：真实 app 上 `release`+`patch` 跑通
- **设备经网络下载 + inflate 增量：仍未验过**。本地无 inflate 实现，
  `fhpb verify` 只能验签名与 hash；且本机网络阻断设备→Mac 直连。
  这是唯一剩下的缺口，见 [[project-landing-plan]]。

## 私钥已公开（必须处理）

`ce6fada` 的 `tools/broute/keys/patch_private.pem` **已推送到公开仓库**
`github.com/icodejoo/flutter_hot_patcher`。用户知情并决定 demo 阶段接受，
**正式发布前必须 `tools/fhpb rotate-key --app-dir <工程>`**。
`tools/broute/keys/` 现已 gitignore。

## 换钥的两个反直觉点（实测，别凭想象）

- `fhpb init --force` **换不了钥**（幂等，复用已有密钥），而且原来会**重新随机 app_id**
  → 等于让线上设备全失联。已修：init 保留 app_id，换钥必须用 `rotate-key`。
- 换钥后**必须重新发版**才生效：公钥编译进包。老版本设备只能用
  `keys/retired/<时间戳>/` 的旧钥继续签，泄露场景下应停发并引导升级。

## 待办

清理共存期补丁：纯 Route-B 不需要 `dartsdk_dynamic_modules_aot.diff`，
`dartsdk_simulator_ffi.diff` 也要复核是否还需要。见 [[project-route-a-archived]]。
